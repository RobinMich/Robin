#!/usr/bin/env python3
"""
EMA Fractal EA – Python Backtester
===================================
Replicates the TradingView Pine Script "EMA Fractal EA v4" strategy logic:
  1. Compute 4 EMAs + ATR on the data
  2. Detect Williams fractals (5-bar: 2 left, pivot, 2 right)
  3. Classify fractals as HH/LH/LL/HL to derive market structure
  4. Determine HTF trend from market structure (bullish = last HH+HL, bearish = last LL+LH)
  5. On bullish trend → wait for Fractal High → place BUY STOP at FH with SL at last FL
  6. On bearish trend → wait for Fractal Low → place SELL STOP at FL with SL at last FH
  7. Trail SL with ATR, partial TP 50 % at 1R, let remainder ride trailing stop
"""

import pandas as pd
import numpy as np
import os, sys, json
from dataclasses import dataclass, field
from typing import Optional

# ─── Strategy Parameters ──────────────────────────────────────────────────────

@dataclass
class StrategyParams:
    # EMA periods
    ema1_period: int = 9
    ema2_period: int = 21
    ema3_period: int = 50
    ema4_period: int = 200
    # ATR
    atr_period: int = 14
    # Fractal detection: n bars on each side
    fractal_n: int = 2
    # Risk management
    risk_pct: float = 2.0        # percent of equity risked per trade
    initial_equity: float = 10000.0
    # SL mode: "full" = full fractal distance, "half" = half distance
    sl_mode: str = "full"
    # Distance filter: max % distance from fractal to EMA2 (0 = disabled)
    ema_distance_filter: float = 0.0
    # Timeout: max bars to wait for fractal after setup (0 = disabled)
    fractal_timeout: int = 0
    # Timeout: max bars a pending order stays active (0 = disabled)
    order_timeout: int = 30
    # Entry distance cancel: max % distance from entry to current close (0 = disabled)
    entry_distance_filter: float = 0.0
    # Partial TP at 1R: fraction of position to close (0 = disabled)
    partial_tp_frac: float = 0.5
    # Commission per trade (one-way, as fraction of trade value)
    commission: float = 0.0
    # Slippage in price points
    slippage: float = 0.0

# ─── Indicator computation ─────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    """Add EMA1-4, ATR, Fractal High/Low, HH/LH/LL/HL columns."""
    df = df.copy()

    # EMAs
    df["EMA1"] = df["close"].ewm(span=p.ema1_period, adjust=False).mean()
    df["EMA2"] = df["close"].ewm(span=p.ema2_period, adjust=False).mean()
    df["EMA3"] = df["close"].ewm(span=p.ema3_period, adjust=False).mean()
    df["EMA4"] = df["close"].ewm(span=p.ema4_period, adjust=False).mean()

    # ATR (Wilder smoothing = EWM with alpha=1/period)
    tr = pd.DataFrame({
        "hl": df["high"] - df["low"],
        "hc": (df["high"] - df["close"].shift(1)).abs(),
        "lc": (df["low"]  - df["close"].shift(1)).abs(),
    }).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1.0 / p.atr_period, adjust=False).mean()

    n = p.fractal_n
    length = len(df)
    fh = np.zeros(length, dtype=int)
    fl = np.zeros(length, dtype=int)

    for i in range(n, length - n):
        is_fh = True
        is_fl = True
        for j in range(1, n + 1):
            if df["high"].iat[i] <= df["high"].iat[i - j] or df["high"].iat[i] <= df["high"].iat[i + j]:
                is_fh = False
            if df["low"].iat[i] >= df["low"].iat[i - j] or df["low"].iat[i] >= df["low"].iat[i + j]:
                is_fl = False
        if is_fh:
            fh[i] = 1
        if is_fl:
            fl[i] = 1

    df["FractalHigh"] = fh
    df["FractalLow"] = fl

    # Classify fractals as HH/LH/LL/HL
    hh = np.zeros(length, dtype=int)
    lh = np.zeros(length, dtype=int)
    ll = np.zeros(length, dtype=int)
    hl = np.zeros(length, dtype=int)

    last_fh_price = np.nan
    last_fl_price = np.nan

    for i in range(length):
        if fh[i]:
            cur = df["high"].iat[i]
            if not np.isnan(last_fh_price):
                if cur > last_fh_price:
                    hh[i] = 1
                else:
                    lh[i] = 1
            last_fh_price = cur
        if fl[i]:
            cur = df["low"].iat[i]
            if not np.isnan(last_fl_price):
                if cur < last_fl_price:
                    ll[i] = 1
                else:
                    hl[i] = 1
            last_fl_price = cur

    df["HH"] = hh
    df["LH"] = lh
    df["LL"] = ll
    df["HL"] = hl

    return df

# ─── Market Structure / HTF Trend ─────────────────────────────────────────────

def get_htf_trend(hh_count: int, lh_count: int, ll_count: int, hl_count: int):
    """
    Simple trend determination from recent fractal structure.
    bullish  = last swing-high was HH AND last swing-low was HL
    bearish  = last swing-high was LH AND last swing-low was LL
    neutral  = everything else
    Returns: 1 (bullish), -1 (bearish), 0 (neutral)
    """
    if hh_count > 0 and hl_count > 0:
        return 1
    if lh_count > 0 and ll_count > 0:
        return -1
    return 0

# ─── Backtester ────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    direction: int          # 1 = long, -1 = short
    entry_price: float
    sl_price: float
    trail_sl: float
    qty: float
    init_risk: float        # |entry - sl|
    entry_bar: int
    partial_closed: bool = False
    partial_qty: float = 0.0
    pnl: float = 0.0
    exit_price: float = 0.0
    exit_bar: int = 0


@dataclass
class PendingOrder:
    direction: int          # 1 = long, -1 = short
    entry_price: float
    sl_price: float
    bars_active: int = 0


def run_backtest(df: pd.DataFrame, p: StrategyParams, verbose: bool = False):
    """Run the EMA Fractal EA backtest on indicator-enriched DataFrame."""
    equity = p.initial_equity
    trades: list[Trade] = []
    position: Optional[Trade] = None
    pending: Optional[PendingOrder] = None

    # Track last fractal prices for SL placement
    last_fh_price = np.nan
    last_fl_price = np.nan

    # Track last fractal type for HTF trend (simple: keep last swing-high type + last swing-low type)
    last_swing_high_type = 0   # 1=HH, -1=LH
    last_swing_low_type  = 0   # 1=HL, -1=LL

    # Setup state
    setup_dir = 0   # 0=none, 1=long setup, -1=short setup
    setup_bar = 0

    warmup = max(p.ema4_period, p.atr_period) + p.fractal_n + 5

    for i in range(len(df)):
        if i < warmup:
            # still accumulate fractal prices
            if df["FractalHigh"].iat[i]:
                last_fh_price = df["high"].iat[i]
            if df["FractalLow"].iat[i]:
                last_fl_price = df["low"].iat[i]
            if df["HH"].iat[i]:
                last_swing_high_type = 1
            elif df["LH"].iat[i]:
                last_swing_high_type = -1
            if df["HL"].iat[i]:
                last_swing_low_type = 1
            elif df["LL"].iat[i]:
                last_swing_low_type = -1
            continue

        o = df["open"].iat[i]
        h = df["high"].iat[i]
        l = df["low"].iat[i]
        c = df["close"].iat[i]
        atr = df["ATR"].iat[i]

        # ── Update fractal tracking (these are confirmed n bars ago) ──
        if df["FractalHigh"].iat[i]:
            last_fh_price = df["high"].iat[i]
        if df["FractalLow"].iat[i]:
            last_fl_price = df["low"].iat[i]

        if df["HH"].iat[i]:
            last_swing_high_type = 1
        elif df["LH"].iat[i]:
            last_swing_high_type = -1
        if df["HL"].iat[i]:
            last_swing_low_type = 1
        elif df["LL"].iat[i]:
            last_swing_low_type = -1

        # ── HTF trend ──
        htf_bullish = (last_swing_high_type == 1 and last_swing_low_type == 1)
        htf_bearish = (last_swing_high_type == -1 and last_swing_low_type == -1)

        # ── Manage open position ──
        if position is not None:
            d = position.direction
            # Check stop hit
            stopped = False
            if d == 1:
                # Long: trail SL is below; check if low touched it
                if l <= position.trail_sl:
                    exit_px = max(position.trail_sl, l)  # assume fill at trail_sl
                    stopped = True
                else:
                    # Update trailing stop (ATR-based, only ratchet up)
                    new_trail = c - atr
                    if new_trail > position.trail_sl:
                        position.trail_sl = new_trail
                    # Partial TP at 1R
                    if not position.partial_closed and p.partial_tp_frac > 0:
                        profit = c - position.entry_price
                        if profit >= position.init_risk:
                            # close partial
                            partial_qty = position.qty * p.partial_tp_frac
                            partial_pnl = partial_qty * profit
                            partial_pnl -= partial_qty * position.entry_price * p.commission  # commission
                            position.partial_closed = True
                            position.partial_qty = partial_qty
                            position.pnl += partial_pnl
                            position.qty -= partial_qty
                            equity += partial_pnl
                            # Move SL to at least breakeven
                            be = position.entry_price + p.slippage
                            if position.trail_sl < be:
                                position.trail_sl = be
            else:
                # Short: trail SL is above; check if high touched it
                if h >= position.trail_sl:
                    exit_px = min(position.trail_sl, h)
                    stopped = True
                else:
                    new_trail = c + atr
                    if new_trail < position.trail_sl:
                        position.trail_sl = new_trail
                    if not position.partial_closed and p.partial_tp_frac > 0:
                        profit = position.entry_price - c
                        if profit >= position.init_risk:
                            partial_qty = position.qty * p.partial_tp_frac
                            partial_pnl = partial_qty * profit
                            partial_pnl -= partial_qty * position.entry_price * p.commission
                            position.partial_closed = True
                            position.partial_qty = partial_qty
                            position.pnl += partial_pnl
                            position.qty -= partial_qty
                            equity += partial_pnl
                            be = position.entry_price - p.slippage
                            if position.trail_sl > be:
                                position.trail_sl = be

            if stopped:
                remaining_pnl = position.qty * (exit_px - position.entry_price) * d
                remaining_pnl -= position.qty * position.entry_price * p.commission
                position.pnl += remaining_pnl
                position.exit_price = exit_px
                position.exit_bar = i
                equity += remaining_pnl
                trades.append(position)
                if verbose:
                    print(f"  Bar {i}: CLOSED {'LONG' if d==1 else 'SHORT'} @ {exit_px:.2f}  PnL={position.pnl:.2f}  Equity={equity:.2f}")
                position = None
            continue  # don't open new orders while in position

        # ── Check pending order fill ──
        if pending is not None:
            pending.bars_active += 1
            d = pending.direction

            # HTF invalidation
            if d == 1 and not htf_bullish:
                if verbose:
                    print(f"  Bar {i}: CANCELLED LONG order – HTF no longer bullish")
                pending = None
            elif d == -1 and not htf_bearish:
                if verbose:
                    print(f"  Bar {i}: CANCELLED SHORT order – HTF no longer bearish")
                pending = None
            # Order timeout
            elif p.order_timeout > 0 and pending.bars_active > p.order_timeout:
                if verbose:
                    print(f"  Bar {i}: CANCELLED order – timeout {pending.bars_active} bars")
                pending = None
            # Entry distance filter
            elif p.entry_distance_filter > 0:
                dist = abs(pending.entry_price - c) / c * 100
                if dist > p.entry_distance_filter:
                    if verbose:
                        print(f"  Bar {i}: CANCELLED order – entry too far ({dist:.1f}%)")
                    pending = None

            if pending is not None:
                filled = False
                fill_px = pending.entry_price + p.slippage * d

                if d == 1 and h >= pending.entry_price:
                    # Buy stop triggered
                    fill_px = max(o, pending.entry_price) + p.slippage
                    filled = True
                elif d == -1 and l <= pending.entry_price:
                    fill_px = min(o, pending.entry_price) - p.slippage
                    filled = True

                if filled:
                    sl = pending.sl_price
                    init_risk = abs(fill_px - sl)
                    if init_risk < 1e-9:
                        pending = None
                        continue
                    risk_dollars = equity * (p.risk_pct / 100.0)
                    qty = risk_dollars / init_risk
                    # Commission on entry
                    entry_comm = qty * fill_px * p.commission
                    position = Trade(
                        direction=d,
                        entry_price=fill_px,
                        sl_price=sl,
                        trail_sl=sl,
                        qty=qty,
                        init_risk=init_risk,
                        entry_bar=i,
                        pnl=-entry_comm,
                    )
                    equity -= entry_comm
                    pending = None
                    if verbose:
                        print(f"  Bar {i}: OPENED {'LONG' if d==1 else 'SHORT'} @ {fill_px:.2f}  SL={sl:.2f}  Qty={qty:.2f}")
                    continue

        # ── Setup activation ──
        if position is None and pending is None:
            # Determine EMA alignment for additional confluence
            ema1 = df["EMA1"].iat[i]
            ema2 = df["EMA2"].iat[i]
            ema3 = df["EMA3"].iat[i]
            ema4 = df["EMA4"].iat[i]

            if htf_bullish and setup_dir != 1:
                setup_dir = 1
                setup_bar = i
                if verbose:
                    print(f"  Bar {i}: LONG SETUP activated")
            elif htf_bearish and setup_dir != -1:
                setup_dir = -1
                setup_bar = i
                if verbose:
                    print(f"  Bar {i}: SHORT SETUP activated")
            elif not htf_bullish and not htf_bearish:
                setup_dir = 0

        # ── Fractal timeout ──
        if setup_dir != 0 and p.fractal_timeout > 0:
            if i - setup_bar > p.fractal_timeout:
                if verbose:
                    print(f"  Bar {i}: Setup TIMEOUT after {i - setup_bar} bars")
                setup_dir = 0

        # ── Check for fractal entry signal ──
        if setup_dir == 1 and df["FractalHigh"].iat[i] and pending is None and position is None:
            fh_price = df["high"].iat[i]
            # Distance filter
            if p.ema_distance_filter > 0:
                ema2_val = df["EMA2"].iat[i]
                dist = abs(fh_price - ema2_val) / ema2_val * 100
                if dist > p.ema_distance_filter:
                    if verbose:
                        print(f"  Bar {i}: FH blocked – distance {dist:.2f}% > {p.ema_distance_filter}%")
                    continue

            if np.isnan(last_fl_price):
                continue

            if p.sl_mode == "full":
                sl = last_fl_price
            else:
                sl = fh_price - (fh_price - last_fl_price) / 2

            if fh_price <= sl:
                continue

            pending = PendingOrder(direction=1, entry_price=fh_price, sl_price=sl)
            if verbose:
                print(f"  Bar {i}: LONG PENDING @ {fh_price:.2f}  SL={sl:.2f}")

        elif setup_dir == -1 and df["FractalLow"].iat[i] and pending is None and position is None:
            fl_price = df["low"].iat[i]
            if p.ema_distance_filter > 0:
                ema2_val = df["EMA2"].iat[i]
                dist = abs(fl_price - ema2_val) / ema2_val * 100
                if dist > p.ema_distance_filter:
                    if verbose:
                        print(f"  Bar {i}: FL blocked – distance {dist:.2f}% > {p.ema_distance_filter}%")
                    continue

            if np.isnan(last_fh_price):
                continue

            if p.sl_mode == "full":
                sl = last_fh_price
            else:
                sl = fl_price + (last_fh_price - fl_price) / 2

            if fl_price >= sl:
                continue

            pending = PendingOrder(direction=-1, entry_price=fl_price, sl_price=sl)
            if verbose:
                print(f"  Bar {i}: SHORT PENDING @ {fl_price:.2f}  SL={sl:.2f}")

    # Close any remaining position at last bar's close
    if position is not None:
        c = df["close"].iat[-1]
        remaining_pnl = position.qty * (c - position.entry_price) * position.direction
        remaining_pnl -= position.qty * position.entry_price * p.commission
        position.pnl += remaining_pnl
        position.exit_price = c
        position.exit_bar = len(df) - 1
        equity += remaining_pnl
        trades.append(position)

    return trades, equity


# ─── Statistics ────────────────────────────────────────────────────────────────

def compute_stats(trades: list[Trade], initial_equity: float, df_len: int):
    if not trades:
        return {"total_trades": 0, "net_pnl": 0, "win_rate": 0, "profit_factor": 0,
                "max_drawdown_pct": 0, "final_equity": initial_equity, "return_pct": 0,
                "avg_win": 0, "avg_loss": 0, "expectancy": 0}

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001

    # Equity curve for drawdown
    eq = initial_equity
    peak = eq
    max_dd = 0
    for t in trades:
        eq += t.pnl
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    final_eq = initial_equity + sum(pnls)
    return {
        "total_trades": len(trades),
        "winners": len(wins),
        "losers": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "net_pnl": sum(pnls),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else 999,
        "max_drawdown_pct": max_dd,
        "final_equity": final_eq,
        "return_pct": (final_eq - initial_equity) / initial_equity * 100,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "expectancy": np.mean(pnls) if pnls else 0,
    }


# ─── Load data ─────────────────────────────────────────────────────────────────

def load_csv(path: str) -> pd.DataFrame:
    """Load a TradingView export CSV (time, open, high, low, close, ...)."""
    df = pd.read_csv(path)
    # Keep only OHLC columns we need (ignore pre-computed indicators – we recompute)
    required = ["time", "open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")
    df = df[required].copy()
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ─── Main ──────────────────────────────────────────────────────────────────────

def backtest_file(path: str, params: StrategyParams, verbose: bool = False):
    name = os.path.basename(path).replace(".csv", "")
    df = load_csv(path)
    df = compute_indicators(df, params)
    trades, final_eq = run_backtest(df, params, verbose=verbose)
    stats = compute_stats(trades, params.initial_equity, len(df))
    return name, stats, trades


def main():
    base = os.path.dirname(os.path.abspath(__file__))

    # Asset groups
    files = {
        "XAUUSD_1D": os.path.join(base, "PEPPERSTONE_XAUUSD, 1D.csv"),
        "XAUUSD_2H": os.path.join(base, "PEPPERSTONE_XAUUSD, 120.csv"),
        "BTCUSD_1D": os.path.join(base, "BITSTAMP_BTCUSD, 1D.csv"),
        "BTCUSD_2H": os.path.join(base, "BITSTAMP_BTCUSD, 120.csv"),
        "AAPL_1D":   os.path.join(base, "BATS_AAPL, 1D.csv"),
        "AAPL_2H":   os.path.join(base, "BATS_AAPL, 120.csv"),
        "NVDA_1D":   os.path.join(base, "BATS_NVDA, 1D.csv"),
        "NVDA_2H":   os.path.join(base, "BATS_NVDA, 120.csv"),
        "TSLA_1D":   os.path.join(base, "BATS_TSLA, 1D.csv"),
        "TSLA_2H":   os.path.join(base, "BATS_TSLA, 120.csv"),
        "MSFT_1D":   os.path.join(base, "BATS_MSFT, 1D.csv"),
        "AMD_1D":    os.path.join(base, "BATS_AMD, 1D.csv"),
        "AMZN_1D":   os.path.join(base, "BATS_AMZN, 1D.csv"),
        "META_1D":   os.path.join(base, "BATS_META, 1D.csv"),
        "GOOG_1D":   os.path.join(base, "BATS_GOOG, 1D.csv"),
        "AVGO_1D":   os.path.join(base, "BATS_AVGO, 1D.csv"),
        "EURJPY_1W": os.path.join(base, "TICKMILL_EURJPY, 1W.csv"),
    }

    # Default v4 parameters
    params = StrategyParams()

    print("=" * 100)
    print("EMA Fractal EA v4 – Backtest Results (Default Parameters)")
    print("=" * 100)
    print(f"{'Asset':<20} {'Trades':>7} {'Win%':>7} {'Net PnL':>12} {'PF':>7} {'MaxDD%':>8} {'Return%':>9} {'Expectancy':>12}")
    print("-" * 100)

    all_results = {}
    for key, path in files.items():
        if not os.path.exists(path):
            print(f"{key:<20} FILE NOT FOUND: {path}")
            continue
        name, stats, trades = backtest_file(path, params, verbose=False)
        all_results[key] = stats
        print(f"{key:<20} {stats['total_trades']:>7} {stats['win_rate']:>6.1f}% {stats['net_pnl']:>11.2f} "
              f"{stats['profit_factor']:>7.2f} {stats['max_drawdown_pct']:>7.1f}% {stats['return_pct']:>8.1f}% "
              f"{stats['expectancy']:>11.2f}")

    print("=" * 100)

    # Save results as JSON for optimizer
    with open(os.path.join(base, "backtest_results.json"), "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to backtest_results.json")


if __name__ == "__main__":
    main()
