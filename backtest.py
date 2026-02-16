#!/usr/bin/env python3
"""
Backtest: EMA Fractal Expert Advisor v2.0
==========================================
Alle 5 Verbesserungen implementiert:
1. Halber SL als Standard
2. Abstandsfilter 0.5%
3. Zeitfilter London/NY (08-20 UTC)
4. Short-Variante (gespiegelte Bedingungen)
5. Partielles TP 50% bei Breakeven
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional


# ============================================================================
# KONFIGURATION
# ============================================================================

@dataclass
class Config:
    ema_fast: int = 10
    ema_mid: int = 20
    ema_slow: int = 50
    fractal_lookback: int = 2
    max_candles_fractal: int = 10
    use_distance_filter: bool = True
    max_distance_pct: float = 0.5
    sl_mode: str = "half"                # "full" oder "half" (NEU: half als Standard)
    use_breakeven: bool = True
    use_partial_tp: bool = True          # NEU: Partielles TP
    partial_tp_pct: float = 50.0         # NEU: 50% schließen
    use_session_filter: bool = True      # NEU: Zeitfilter
    session_start: int = 8              # NEU: London open
    session_end: int = 20              # NEU: NY close
    trade_long: bool = True             # NEU: Long aktivieren
    trade_short: bool = True            # NEU: Short aktivieren
    initial_capital: float = 10000.0
    risk_per_trade_pct: float = 2.0
    commission_pct: float = 0.01


# ============================================================================
# DATEN & HILFSFUNKTIONEN
# ============================================================================

def load_data(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    return df


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def detect_fractals(df: pd.DataFrame, lookback: int = 2):
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    fractal_high = np.zeros(n, dtype=bool)
    fractal_low = np.zeros(n, dtype=bool)
    fractal_high_price = np.full(n, np.nan)
    fractal_low_price = np.full(n, np.nan)

    for i in range(lookback, n - lookback):
        is_fh = True
        for j in range(1, lookback + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_fh = False
                break
        if is_fh:
            fractal_high[i] = True
            fractal_high_price[i] = highs[i]

        is_fl = True
        for j in range(1, lookback + 1):
            if lows[i] <= lows[i - j] or lows[i] <= lows[i + j]:
                is_fl = False
                break
        if is_fl:
            fractal_low[i] = True
            fractal_low_price[i] = lows[i]

    df['fractal_high'] = fractal_high
    df['fractal_low'] = fractal_low
    df['fractal_high_price'] = fractal_high_price
    df['fractal_low_price'] = fractal_low_price
    return df


# ============================================================================
# TRADE
# ============================================================================

@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    sl_price: float
    direction: int  # 1=Long, -1=Short
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    position_size: float = 0.0
    breakeven_activated: bool = False
    partial_tp_done: bool = False
    partial_pnl: float = 0.0
    max_favorable: float = 0.0
    max_adverse: float = 0.0


# ============================================================================
# BACKTEST ENGINE v2
# ============================================================================

class Backtester:
    def __init__(self, config: Config):
        self.config = config
        self.trades: list[Trade] = []
        self.equity = config.initial_capital
        self.peak_equity = config.initial_capital

    def run(self, h2: pd.DataFrame, daily: pd.DataFrame, weekly: pd.DataFrame):
        cfg = self.config

        # EMAs berechnen
        h2['ema10'] = compute_ema(h2['close'], cfg.ema_fast)
        h2['ema20'] = compute_ema(h2['close'], cfg.ema_mid)

        daily['ema10'] = compute_ema(daily['close'], cfg.ema_fast)
        daily['ema20'] = compute_ema(daily['close'], cfg.ema_mid)

        weekly['ema10'] = compute_ema(weekly['close'], cfg.ema_fast)
        weekly['ema20'] = compute_ema(weekly['close'], cfg.ema_mid)
        weekly['ema50'] = compute_ema(weekly['close'], cfg.ema_slow)

        h2 = detect_fractals(h2, cfg.fractal_lookback)
        h2_arr = h2.reset_index()

        # HTF Bedingungen vorab berechnen
        weekly_bull = (weekly['ema10'] > weekly['ema20']) & (weekly['ema20'] > weekly['ema50'])
        weekly_bear = (weekly['ema10'] < weekly['ema20']) & (weekly['ema20'] < weekly['ema50'])
        daily_bull = daily['ema10'] > daily['ema20']
        daily_bear = daily['ema10'] < daily['ema20']

        n = len(h2_arr)

        # Zustandsmaschine
        waiting_for_fractal = False
        bars_since_setup = 0
        setup_direction = 0  # 1=Long, -1=Short
        in_position = False
        current_trade: Optional[Trade] = None
        order_pending = False
        order_direction = 0
        pending_entry_price = 0.0
        pending_sl_price = 0.0
        last_fractal_low_val = np.nan
        last_fractal_high_val = np.nan
        trailing_sl = np.nan
        breakeven_done = False
        partial_tp_done = False
        remaining_size_factor = 1.0

        for i in range(cfg.fractal_lookback + 1, n):
            row = h2_arr.iloc[i]
            ts = row['time']
            o, h_val, l_val, c = row['open'], row['high'], row['low'], row['close']
            ema10_val = row['ema10']
            ema20_val = row['ema20']

            if pd.isna(ema10_val) or pd.isna(ema20_val):
                continue

            # Zeitfilter
            if cfg.use_session_filter:
                hour_utc = ts.hour
                if hour_utc < cfg.session_start or hour_utc >= cfg.session_end:
                    # Kein neues Setup erlaubt, aber offene Positionen managen
                    in_session = False
                else:
                    in_session = True
            else:
                in_session = True

            # HTF Bedingungen
            w_mask = weekly.index <= ts
            d_mask = daily.index <= ts
            if not w_mask.any() or not d_mask.any():
                continue

            w_bull_ok = weekly_bull.loc[w_mask].iloc[-1]
            w_bear_ok = weekly_bear.loc[w_mask].iloc[-1]
            d_bull_ok = daily_bull.loc[d_mask].iloc[-1]
            d_bear_ok = daily_bear.loc[d_mask].iloc[-1]

            htf_bullish = w_bull_ok and d_bull_ok
            htf_bearish = w_bear_ok and d_bear_ok

            # Fractal Tracking
            if row['fractal_low']:
                last_fractal_low_val = row['fractal_low_price']
            if row['fractal_high']:
                last_fractal_high_val = row['fractal_high_price']

            # ============================================================
            # POSITION MANAGEMENT
            # ============================================================
            if in_position and current_trade is not None:
                td = current_trade.direction

                # MFE/MAE
                if td == 1:
                    current_trade.max_favorable = max(current_trade.max_favorable, h_val - current_trade.entry_price)
                    current_trade.max_adverse = max(current_trade.max_adverse, current_trade.entry_price - l_val)
                else:
                    current_trade.max_favorable = max(current_trade.max_favorable, current_trade.entry_price - l_val)
                    current_trade.max_adverse = max(current_trade.max_adverse, h_val - current_trade.entry_price)

                # SL Check
                sl_hit = False
                if td == 1 and l_val <= trailing_sl:
                    sl_hit = True
                elif td == -1 and h_val >= trailing_sl:
                    sl_hit = True

                if sl_hit:
                    current_trade.exit_time = ts
                    current_trade.exit_price = trailing_sl
                    current_trade.exit_reason = "Trailing SL" if breakeven_done else "Initial SL"
                    if td == 1:
                        pnl = (trailing_sl - current_trade.entry_price) * current_trade.position_size * remaining_size_factor
                    else:
                        pnl = (current_trade.entry_price - trailing_sl) * current_trade.position_size * remaining_size_factor
                    commission = abs(trailing_sl * current_trade.position_size * remaining_size_factor * cfg.commission_pct / 100)
                    current_trade.pnl = current_trade.partial_pnl + pnl - commission
                    current_trade.pnl_pct = current_trade.pnl / self.equity * 100
                    current_trade.breakeven_activated = breakeven_done
                    current_trade.partial_tp_done = partial_tp_done
                    self.equity += current_trade.pnl
                    self.peak_equity = max(self.peak_equity, self.equity)
                    self.trades.append(current_trade)
                    in_position = False
                    current_trade = None
                    trailing_sl = np.nan
                    breakeven_done = False
                    partial_tp_done = False
                    remaining_size_factor = 1.0
                    continue

                # Trailing SL nachziehen
                if td == 1 and row['fractal_low'] and not pd.isna(row['fractal_low_price']):
                    if row['fractal_low_price'] > trailing_sl:
                        trailing_sl = row['fractal_low_price']
                elif td == -1 and row['fractal_high'] and not pd.isna(row['fractal_high_price']):
                    if row['fractal_high_price'] < trailing_sl:
                        trailing_sl = row['fractal_high_price']

                # Breakeven + Partielles TP
                if cfg.use_breakeven and not breakeven_done:
                    be_triggered = False
                    if td == 1 and c > current_trade.entry_price:
                        be_triggered = True
                    elif td == -1 and c < current_trade.entry_price:
                        be_triggered = True

                    if be_triggered:
                        breakeven_done = True
                        # SL auf Entry setzen
                        if td == 1 and current_trade.entry_price > trailing_sl:
                            trailing_sl = current_trade.entry_price
                        elif td == -1 and current_trade.entry_price < trailing_sl:
                            trailing_sl = current_trade.entry_price

                        # Partielles TP: 50% der Position schließen
                        if cfg.use_partial_tp and not partial_tp_done:
                            close_fraction = cfg.partial_tp_pct / 100.0
                            if td == 1:
                                partial_pnl = (c - current_trade.entry_price) * current_trade.position_size * close_fraction
                            else:
                                partial_pnl = (current_trade.entry_price - c) * current_trade.position_size * close_fraction
                            partial_commission = abs(c * current_trade.position_size * close_fraction * cfg.commission_pct / 100)
                            current_trade.partial_pnl += partial_pnl - partial_commission
                            remaining_size_factor = 1.0 - close_fraction
                            partial_tp_done = True
                            self.equity += partial_pnl - partial_commission

                continue

            # ============================================================
            # PENDING ORDER CHECK
            # ============================================================
            if order_pending:
                # HTF Bedingung verloren → canceln
                should_cancel = (order_direction == 1 and not htf_bullish) or (order_direction == -1 and not htf_bearish)
                if should_cancel:
                    order_pending = False
                    order_direction = 0
                    continue

                # Order Fill Check
                filled = False
                if order_direction == 1 and h_val >= pending_entry_price:
                    filled = True
                elif order_direction == -1 and l_val <= pending_entry_price:
                    filled = True

                if filled:
                    risk_amount = self.equity * cfg.risk_per_trade_pct / 100
                    risk_per_unit = abs(pending_entry_price - pending_sl_price)
                    if risk_per_unit <= 0:
                        order_pending = False
                        order_direction = 0
                        continue
                    pos_size = risk_amount / risk_per_unit

                    current_trade = Trade(
                        entry_time=ts,
                        entry_price=pending_entry_price,
                        sl_price=pending_sl_price,
                        direction=order_direction,
                        position_size=pos_size
                    )
                    trailing_sl = pending_sl_price
                    in_position = True
                    order_pending = False
                    breakeven_done = False
                    partial_tp_done = False
                    remaining_size_factor = 1.0
                    continue

            # ============================================================
            # SETUP SIGNAL (nur in Session)
            # ============================================================
            if not waiting_for_fractal and not in_position and not order_pending and in_session:
                if i > 0:
                    prev_close = h2_arr.iloc[i - 1]['close']
                    prev_ema20 = h2_arr.iloc[i - 1]['ema20']

                    # LONG Setup
                    if cfg.trade_long and htf_bullish:
                        h2_pullback = ema10_val < ema20_val
                        cross_above = c > ema20_val and prev_close <= prev_ema20
                        if h2_pullback and cross_above:
                            waiting_for_fractal = True
                            bars_since_setup = 0
                            setup_direction = 1

                    # SHORT Setup
                    if not waiting_for_fractal and cfg.trade_short and htf_bearish:
                        h2_pullback_bear = ema10_val > ema20_val
                        cross_below = c < ema20_val and prev_close >= prev_ema20
                        if h2_pullback_bear and cross_below:
                            waiting_for_fractal = True
                            bars_since_setup = 0
                            setup_direction = -1

            # ============================================================
            # WARTEN AUF FRACTAL
            # ============================================================
            if waiting_for_fractal:
                bars_since_setup += 1

                if bars_since_setup > cfg.max_candles_fractal:
                    waiting_for_fractal = False
                    bars_since_setup = 0
                    setup_direction = 0
                    continue

                # LONG: Oberes Fractal → Buystop
                if setup_direction == 1 and row['fractal_high']:
                    fh_price = row['fractal_high_price']

                    if cfg.use_distance_filter:
                        dist_pct = abs(fh_price - ema20_val) / ema20_val * 100
                        if dist_pct > cfg.max_distance_pct:
                            continue

                    pending_entry_price = fh_price
                    if cfg.sl_mode == "full":
                        pending_sl_price = last_fractal_low_val if not np.isnan(last_fractal_low_val) else l_val
                    else:
                        fl = last_fractal_low_val if not np.isnan(last_fractal_low_val) else l_val
                        pending_sl_price = fh_price - (fh_price - fl) / 2

                    if pending_sl_price >= pending_entry_price:
                        waiting_for_fractal = False
                        setup_direction = 0
                        continue

                    order_pending = True
                    order_direction = 1
                    waiting_for_fractal = False
                    bars_since_setup = 0

                # SHORT: Unteres Fractal → Sellstop
                elif setup_direction == -1 and row['fractal_low']:
                    fl_price = row['fractal_low_price']

                    if cfg.use_distance_filter:
                        dist_pct = abs(fl_price - ema20_val) / ema20_val * 100
                        if dist_pct > cfg.max_distance_pct:
                            continue

                    pending_entry_price = fl_price
                    if cfg.sl_mode == "full":
                        pending_sl_price = last_fractal_high_val if not np.isnan(last_fractal_high_val) else h_val
                    else:
                        fh = last_fractal_high_val if not np.isnan(last_fractal_high_val) else h_val
                        pending_sl_price = fl_price + (fh - fl_price) / 2

                    if pending_sl_price <= pending_entry_price:
                        waiting_for_fractal = False
                        setup_direction = 0
                        continue

                    order_pending = True
                    order_direction = -1
                    waiting_for_fractal = False
                    bars_since_setup = 0

        # Offene Position am Ende schließen
        if in_position and current_trade is not None:
            last_row = h2_arr.iloc[-1]
            current_trade.exit_time = last_row['time']
            current_trade.exit_price = last_row['close']
            current_trade.exit_reason = "End of Data"
            td = current_trade.direction
            if td == 1:
                pnl = (last_row['close'] - current_trade.entry_price) * current_trade.position_size * remaining_size_factor
            else:
                pnl = (current_trade.entry_price - last_row['close']) * current_trade.position_size * remaining_size_factor
            commission = abs(last_row['close'] * current_trade.position_size * remaining_size_factor * cfg.commission_pct / 100)
            current_trade.pnl = current_trade.partial_pnl + pnl - commission
            self.equity += current_trade.pnl
            self.trades.append(current_trade)

    def report(self, label=""):
        if not self.trades:
            print("  Keine Trades gefunden.")
            return None

        total = len(self.trades)
        long_trades = [t for t in self.trades if t.direction == 1]
        short_trades = [t for t in self.trades if t.direction == -1]
        winners = [t for t in self.trades if t.pnl > 0]
        losers = [t for t in self.trades if t.pnl <= 0]
        win_rate = len(winners) / total * 100

        total_pnl = sum(t.pnl for t in self.trades)
        avg_win = np.mean([t.pnl for t in winners]) if winners else 0
        avg_loss = np.mean([t.pnl for t in losers]) if losers else 0

        gross_profit = sum(t.pnl for t in winners)
        gross_loss = sum(t.pnl for t in losers)
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else float('inf')

        # Max Drawdown
        equity_curve = [self.config.initial_capital]
        for t in self.trades:
            equity_curve.append(equity_curve[-1] + t.pnl)
        equity_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(equity_arr)
        dd = (peak - equity_arr) / peak * 100
        max_dd = np.max(dd)

        # Haltedauer
        durations = []
        for t in self.trades:
            if t.exit_time and t.entry_time:
                dur = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(dur)
        avg_duration = np.mean(durations) if durations else 0

        be_trades = [t for t in self.trades if t.breakeven_activated]
        pt_trades = [t for t in self.trades if t.partial_tp_done]

        # Long/Short Aufschlüsselung
        long_wins = len([t for t in long_trades if t.pnl > 0])
        short_wins = len([t for t in short_trades if t.pnl > 0])
        long_pnl = sum(t.pnl for t in long_trades)
        short_pnl = sum(t.pnl for t in short_trades)

        print("=" * 70)
        print(f"  BACKTEST: EMA Fractal EA v2 - XAUUSD H2 {label}")
        print("=" * 70)
        print(f"  Zeitraum:            {self.trades[0].entry_time.date()} - {self.trades[-1].exit_time.date() if self.trades[-1].exit_time else 'offen'}")
        print(f"  Startkapital:        ${self.config.initial_capital:,.2f}")
        print(f"  Endkapital:          ${self.equity:,.2f}")
        print(f"  Netto P/L:           ${total_pnl:,.2f} ({total_pnl / self.config.initial_capital * 100:.1f}%)")
        print("-" * 70)
        print(f"  Anzahl Trades:       {total} (Long: {len(long_trades)}, Short: {len(short_trades)})")
        print(f"  Gewinner:            {len(winners)} ({win_rate:.1f}%)")
        print(f"  Verlierer:           {len(losers)} ({100 - win_rate:.1f}%)")
        print(f"  Profit Factor:       {profit_factor:.2f}")
        print("-" * 70)
        print(f"  Ø Gewinn:            ${avg_win:,.2f}")
        print(f"  Ø Verlust:           ${avg_loss:,.2f}")
        print(f"  Ø Haltedauer:        {avg_duration:.1f} Stunden")
        print(f"  Max Drawdown:        {max_dd:.1f}%")
        print("-" * 70)
        print(f"  Long P/L:            ${long_pnl:,.2f} ({len(long_trades)} Trades, {long_wins} Wins)")
        print(f"  Short P/L:           ${short_pnl:,.2f} ({len(short_trades)} Trades, {short_wins} Wins)")
        print(f"  Breakeven aktiviert: {len(be_trades)} ({len(be_trades)/total*100:.1f}%)")
        print(f"  Partial TP 50%:      {len(pt_trades)} ({len(pt_trades)/total*100:.1f}%)")
        print("=" * 70)

        # Trade Log
        print(f"\n--- Trade Log (erste 30) ---")
        print(f"{'#':>3} | {'Dir':>5} | {'Entry Datum':>19} | {'Entry':>10} | {'Exit':>10} | {'SL':>10} | {'P/L':>10} | {'Grund':>15}")
        print("-" * 105)
        for i, t in enumerate(self.trades[:30], 1):
            exit_p = f"{t.exit_price:>10.2f}" if t.exit_price else "     offen"
            d = "LONG" if t.direction == 1 else "SHORT"
            print(f"{i:>3} | {d:>5} | {str(t.entry_time):>19} | {t.entry_price:>10.2f} | {exit_p} | {t.sl_price:>10.2f} | {t.pnl:>+10.2f} | {t.exit_reason:>15}")

        # Jahresweise
        print(f"\n--- Jahresweise Performance ---")
        yearly = {}
        for t in self.trades:
            year = t.entry_time.year
            if year not in yearly:
                yearly[year] = {"trades": 0, "pnl": 0.0, "wins": 0, "longs": 0, "shorts": 0}
            yearly[year]["trades"] += 1
            yearly[year]["pnl"] += t.pnl
            if t.pnl > 0:
                yearly[year]["wins"] += 1
            if t.direction == 1:
                yearly[year]["longs"] += 1
            else:
                yearly[year]["shorts"] += 1

        print(f"{'Jahr':>6} | {'Trades':>6} | {'L/S':>7} | {'Win%':>6} | {'P/L':>12}")
        print("-" * 50)
        for year in sorted(yearly.keys()):
            y = yearly[year]
            wr = y["wins"] / y["trades"] * 100 if y["trades"] > 0 else 0
            print(f"{year:>6} | {y['trades']:>6} | {y['longs']:>3}/{y['shorts']:<3} | {wr:>5.1f}% | ${y['pnl']:>+11.2f}")

        return {
            "total_trades": total,
            "long_trades": len(long_trades),
            "short_trades": len(short_trades),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "long_pnl": long_pnl,
            "short_pnl": short_pnl,
            "max_drawdown": max_dd,
            "avg_duration_hrs": avg_duration,
            "equity": self.equity,
            "partial_tp_count": len(pt_trades),
            "breakeven_count": len(be_trades)
        }


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Lade Daten...")
    h2 = load_data("PEPPERSTONE_XAUUSD, 120.csv")
    daily = load_data("PEPPERSTONE_XAUUSD, 1D.csv")
    weekly = load_data("PEPPERSTONE_XAUUSD, 1W.csv")

    print(f"  H2:     {len(h2)} Kerzen ({h2.index[0].date()} - {h2.index[-1].date()})")
    print(f"  Daily:  {len(daily)} Kerzen ({daily.index[0].date()} - {daily.index[-1].date()})")
    print(f"  Weekly: {len(weekly)} Kerzen ({weekly.index[0].date()} - {weekly.index[-1].date()})")

    # ===== TEST 1: v2 Komplett (alle Verbesserungen) =====
    print("\n" + "=" * 70)
    print("  TEST 1: v2 KOMPLETT (Half SL + Session + Short + Partial TP)")
    print("=" * 70)
    cfg1 = Config()
    bt1 = Backtester(cfg1)
    bt1.run(h2.copy(), daily.copy(), weekly.copy())
    r1 = bt1.report()

    # ===== TEST 2: v2 nur Long =====
    print("\n" + "=" * 70)
    print("  TEST 2: v2 nur LONG")
    print("=" * 70)
    cfg2 = Config(trade_short=False)
    bt2 = Backtester(cfg2)
    bt2.run(h2.copy(), daily.copy(), weekly.copy())
    r2 = bt2.report()

    # ===== TEST 3: v2 nur Short =====
    print("\n" + "=" * 70)
    print("  TEST 3: v2 nur SHORT")
    print("=" * 70)
    cfg3 = Config(trade_long=False)
    bt3 = Backtester(cfg3)
    bt3.run(h2.copy(), daily.copy(), weekly.copy())
    r3 = bt3.report()

    # ===== TEST 4: v2 ohne Session Filter =====
    print("\n" + "=" * 70)
    print("  TEST 4: v2 OHNE Session-Filter")
    print("=" * 70)
    cfg4 = Config(use_session_filter=False)
    bt4 = Backtester(cfg4)
    bt4.run(h2.copy(), daily.copy(), weekly.copy())
    r4 = bt4.report()

    # ===== TEST 5: v2 ohne Partial TP =====
    print("\n" + "=" * 70)
    print("  TEST 5: v2 OHNE Partial TP")
    print("=" * 70)
    cfg5 = Config(use_partial_tp=False)
    bt5 = Backtester(cfg5)
    bt5.run(h2.copy(), daily.copy(), weekly.copy())
    r5 = bt5.report()

    # ===== TEST 6: v1 Original (Vergleich) =====
    print("\n" + "=" * 70)
    print("  TEST 6: v1 ORIGINAL (Vergleichsbasis)")
    print("=" * 70)
    cfg6 = Config(
        sl_mode="half",
        use_session_filter=False,
        use_partial_tp=False,
        trade_short=False
    )
    bt6 = Backtester(cfg6)
    bt6.run(h2.copy(), daily.copy(), weekly.copy())
    r6 = bt6.report()

    # ===== VERGLEICH =====
    print("\n" + "=" * 85)
    print("  VERGLEICH: v1 vs v2 Varianten")
    print("=" * 85)
    results = [
        ("v2 KOMPLETT", r1),
        ("v2 nur Long", r2),
        ("v2 nur Short", r3),
        ("v2 ohne Session", r4),
        ("v2 ohne Partial TP", r5),
        ("v1 Original", r6),
    ]
    print(f"{'Variante':<25} | {'Trades':>6} | {'L/S':>7} | {'Win%':>6} | {'PF':>6} | {'P/L':>12} | {'MaxDD':>6}")
    print("-" * 85)
    for name, r in results:
        if r:
            ls = f"{r['long_trades']}/{r['short_trades']}"
            print(f"{name:<25} | {r['total_trades']:>6} | {ls:>7} | {r['win_rate']:>5.1f}% | {r['profit_factor']:>5.2f} | ${r['total_pnl']:>+11.2f} | {r['max_drawdown']:>5.1f}%")
        else:
            print(f"{name:<25} | {'N/A':>6} | {'N/A':>7} | {'N/A':>6} | {'N/A':>6} | {'N/A':>12} | {'N/A':>6}")


if __name__ == "__main__":
    main()
