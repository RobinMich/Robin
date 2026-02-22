#!/usr/bin/env python3
"""
Magic Trend + Bollinger Bands Breakout Strategy - Parameter Optimizer
=====================================================================
Testet verschiedene Parameterkombinationen auf CAPITALCOM_US100 1min Daten
und findet die optimalen Einstellungen.
"""

import csv
import math
import itertools
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# =============================================================================
# DATEN LADEN
# =============================================================================

@dataclass
class Candle:
    time: int
    dt_berlin: datetime
    open: float
    high: float
    low: float
    close: float


def load_data(filepath: str) -> List[Candle]:
    berlin_offset = timedelta(hours=1)  # CET
    candles = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row['time'])
            dt = datetime.utcfromtimestamp(ts) + berlin_offset
            candles.append(Candle(
                time=ts,
                dt_berlin=dt,
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
            ))
    return candles


# =============================================================================
# INDIKATOREN
# =============================================================================

def calc_sma(values: List[float], period: int) -> List[Optional[float]]:
    result = [None] * len(values)
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1:i + 1]) / period
    return result


def calc_stdev(values: List[float], period: int) -> List[Optional[float]]:
    sma = calc_sma(values, period)
    result = [None] * len(values)
    for i in range(period - 1, len(values)):
        mean = sma[i]
        variance = sum((values[j] - mean) ** 2 for j in range(i - period + 1, i + 1)) / period
        result[i] = math.sqrt(variance)
    return result


def calc_tr(candles: List[Candle]) -> List[float]:
    """True Range"""
    tr = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        hl = candles[i].high - candles[i].low
        hc = abs(candles[i].high - candles[i - 1].close)
        lc = abs(candles[i].low - candles[i - 1].close)
        tr.append(max(hl, hc, lc))
    return tr


def calc_atr(candles: List[Candle], period: int) -> List[Optional[float]]:
    """Average True Range using RMA (Wilder's smoothing)"""
    tr = calc_tr(candles)
    result = [None] * len(tr)
    # First ATR = SMA of first 'period' TR values
    if len(tr) < period:
        return result
    result[period - 1] = sum(tr[:period]) / period
    for i in range(period, len(tr)):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


def calc_cci(candles: List[Candle], period: int) -> List[Optional[float]]:
    """Commodity Channel Index"""
    tp = [(c.high + c.low + c.close) / 3.0 for c in candles]
    sma = calc_sma(tp, period)
    result = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        mean = sma[i]
        mean_dev = sum(abs(tp[j] - mean) for j in range(i - period + 1, i + 1)) / period
        if mean_dev != 0:
            result[i] = (tp[i] - mean) / (0.015 * mean_dev)
        else:
            result[i] = 0.0
    return result


def calc_magic_trend(candles: List[Candle], cci_period: int, atr_period: int, atr_mult: float):
    """Returns (magic_trend_values, is_bullish) lists"""
    cci = calc_cci(candles, cci_period)
    atr = calc_atr(candles, atr_period)

    mt = [None] * len(candles)
    bullish = [None] * len(candles)

    for i in range(len(candles)):
        if cci[i] is None or atr[i] is None:
            continue

        up_trend = candles[i].low - atr[i] * atr_mult
        down_trend = candles[i].high + atr[i] * atr_mult

        if cci[i] >= 0:
            prev = mt[i - 1] if i > 0 and mt[i - 1] is not None else up_trend
            mt[i] = max(up_trend, prev)
            bullish[i] = True
        else:
            prev = mt[i - 1] if i > 0 and mt[i - 1] is not None else down_trend
            mt[i] = min(down_trend, prev)
            bullish[i] = False

    return mt, bullish


def calc_bollinger_bands(candles: List[Candle], length: int, mult: float):
    """Returns (basis, upper, lower) lists"""
    closes = [c.close for c in candles]
    basis = calc_sma(closes, length)
    stdev = calc_stdev(closes, length)

    upper = [None] * len(candles)
    lower = [None] * len(candles)

    for i in range(len(candles)):
        if basis[i] is not None and stdev[i] is not None:
            upper[i] = basis[i] + mult * stdev[i]
            lower[i] = basis[i] - mult * stdev[i]

    return basis, upper, lower


# =============================================================================
# STRATEGIE + BACKTESTER
# =============================================================================

@dataclass
class Trade:
    direction: str  # "long" or "short"
    entry_price: float
    entry_time: datetime
    sl: float
    tp: float
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    pnl: float = 0.0


@dataclass
class StrategyParams:
    # Magic Trend
    cci_period: int = 20
    atr_period: int = 5
    atr_mult: float = 1.0
    # Bollinger Bands
    bb_length: int = 20
    bb_mult: float = 2.0
    # Entry
    mode: str = "breakout"  # "breakout", "mean_reversion", "combined"
    need_mt: bool = True
    body_filter: bool = True
    body_min_ratio: float = 0.3
    use_squeeze: bool = False
    squeeze_lookback: int = 50
    # Risk
    sl_type: str = "atr"  # "atr", "fixed", "bb_mid"
    sl_atr_mult: float = 1.5
    sl_fixed: float = 50.0
    tp_type: str = "rr"  # "rr", "fixed", "bb_opposite"
    tp_rr: float = 2.0
    tp_fixed: float = 100.0
    max_trades_per_session: int = 3
    # Time
    start_h: int = 15
    start_m: int = 30
    end_h: int = 16
    end_m: int = 30
    close_at_end: bool = True


@dataclass
class BacktestResult:
    params: StrategyParams
    trades: List[Trade] = field(default_factory=list)
    total_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    sharpe_approx: float = 0.0
    expectancy: float = 0.0


def run_backtest(candles: List[Candle], params: StrategyParams) -> BacktestResult:
    # Pre-calculate indicators
    mt_values, mt_bullish = calc_magic_trend(candles, params.cci_period, params.atr_period, params.atr_mult)
    bb_basis, bb_upper, bb_lower = calc_bollinger_bands(candles, params.bb_length, params.bb_mult)
    atr = calc_atr(candles, params.atr_period)

    # BB width for squeeze
    bb_width = [None] * len(candles)
    for i in range(len(candles)):
        if bb_upper[i] is not None and bb_lower[i] is not None and bb_basis[i] is not None and bb_basis[i] != 0:
            bb_width[i] = (bb_upper[i] - bb_lower[i]) / bb_basis[i] * 100

    closes_for_width = [w for w in bb_width if w is not None]
    bb_width_avg = [None] * len(candles)
    if len(closes_for_width) >= params.squeeze_lookback:
        width_vals = [w if w is not None else 0.0 for w in bb_width]
        bb_width_avg = calc_sma(width_vals, params.squeeze_lookback)

    # Time window
    start_total = params.start_h * 60 + params.start_m
    end_total = params.end_h * 60 + params.end_m

    trades = []
    current_trade: Optional[Trade] = None
    session_trades = 0
    last_session_date = None

    # Need at least max indicator warmup period
    warmup = max(params.cci_period, params.atr_period, params.bb_length, params.squeeze_lookback) + 5

    for i in range(warmup, len(candles)):
        c = candles[i]
        prev = candles[i - 1]
        dt = c.dt_berlin
        current_total = dt.hour * 60 + dt.minute

        in_window = start_total <= current_total < end_total
        at_close = end_total <= current_total < end_total + 5

        # Session reset
        session_date = dt.date()
        if session_date != last_session_date and in_window:
            session_trades = 0
            last_session_date = session_date

        # Skip if indicators not ready
        if (mt_bullish[i] is None or bb_upper[i] is None or bb_lower[i] is None
                or bb_basis[i] is None or atr[i] is None):
            continue

        # Check open position against SL/TP
        if current_trade is not None:
            hit_sl = False
            hit_tp = False

            if current_trade.direction == "long":
                if c.low <= current_trade.sl:
                    hit_sl = True
                if c.high >= current_trade.tp:
                    hit_tp = True
            else:  # short
                if c.high >= current_trade.sl:
                    hit_sl = True
                if c.low <= current_trade.tp:
                    hit_tp = True

            if hit_sl and hit_tp:
                # Both hit in same candle - use open direction to decide
                # Conservative: assume SL hit first
                hit_tp = False

            if hit_sl:
                current_trade.exit_price = current_trade.sl
                current_trade.exit_time = dt
                current_trade.exit_reason = "SL"
                if current_trade.direction == "long":
                    current_trade.pnl = current_trade.sl - current_trade.entry_price
                else:
                    current_trade.pnl = current_trade.entry_price - current_trade.sl
                trades.append(current_trade)
                current_trade = None
            elif hit_tp:
                current_trade.exit_price = current_trade.tp
                current_trade.exit_time = dt
                current_trade.exit_reason = "TP"
                if current_trade.direction == "long":
                    current_trade.pnl = current_trade.tp - current_trade.entry_price
                else:
                    current_trade.pnl = current_trade.entry_price - current_trade.tp
                trades.append(current_trade)
                current_trade = None

            # Close at session end
            if current_trade is not None and params.close_at_end and at_close:
                current_trade.exit_price = c.close
                current_trade.exit_time = dt
                current_trade.exit_reason = "SESSION_END"
                if current_trade.direction == "long":
                    current_trade.pnl = c.close - current_trade.entry_price
                else:
                    current_trade.pnl = current_trade.entry_price - c.close
                trades.append(current_trade)
                current_trade = None

        # Entry signals (only if no open position and in window)
        if current_trade is None and in_window and session_trades < params.max_trades_per_session:
            # Candle analysis
            body_size = abs(c.close - c.open)
            candle_range = c.high - c.low
            body_ratio = body_size / candle_range if candle_range > 0 else 0
            is_bull = c.close > c.open
            is_bear = c.close < c.open
            body_ok = (not params.body_filter) or (body_ratio >= params.body_min_ratio)

            # Breakout signals
            breakout_long = (c.close > bb_upper[i] and prev.close <= bb_upper[i - 1] and is_bull) if (bb_upper[i - 1] is not None) else False
            breakout_short = (c.close < bb_lower[i] and prev.close >= bb_lower[i - 1] and is_bear) if (bb_lower[i - 1] is not None) else False

            # Mean reversion signals
            mr_long = (c.close > bb_lower[i] and (prev.close < bb_lower[i - 1] or c.low < bb_lower[i]) and is_bull) if (bb_lower[i - 1] is not None) else False
            mr_short = (c.close < bb_upper[i] and (prev.close > bb_upper[i - 1] or c.high > bb_upper[i]) and is_bear) if (bb_upper[i - 1] is not None) else False

            # Mode selection
            long_signal = False
            short_signal = False
            if params.mode == "breakout":
                long_signal = breakout_long
                short_signal = breakout_short
            elif params.mode == "mean_reversion":
                long_signal = mr_long
                short_signal = mr_short
            else:  # combined
                long_signal = breakout_long or mr_long
                short_signal = breakout_short or mr_short

            # Magic Trend filter
            if params.need_mt:
                long_signal = long_signal and mt_bullish[i] == True
                short_signal = short_signal and mt_bullish[i] == False

            # Body filter
            long_signal = long_signal and body_ok
            short_signal = short_signal and body_ok

            # Squeeze filter
            if params.use_squeeze and bb_width_avg[i - 1] is not None and bb_width[i - 1] is not None:
                in_squeeze = bb_width[i - 1] < bb_width_avg[i - 1]
                long_signal = long_signal and in_squeeze
                short_signal = short_signal and in_squeeze

            # Calculate SL/TP and enter
            if long_signal:
                entry = c.close
                if params.sl_type == "atr":
                    sl = entry - atr[i] * params.sl_atr_mult
                elif params.sl_type == "fixed":
                    sl = entry - params.sl_fixed
                else:  # bb_mid
                    sl = bb_basis[i]

                sl_dist = abs(entry - sl)
                if sl_dist < 0.01:
                    sl_dist = atr[i] * 0.5 if atr[i] else 5.0
                    sl = entry - sl_dist

                if params.tp_type == "rr":
                    tp = entry + sl_dist * params.tp_rr
                elif params.tp_type == "fixed":
                    tp = entry + params.tp_fixed
                else:  # bb_opposite
                    tp = bb_upper[i]
                    if tp <= entry:
                        tp = entry + sl_dist * 1.5

                current_trade = Trade("long", entry, dt, sl, tp)
                session_trades += 1

            elif short_signal:
                entry = c.close
                if params.sl_type == "atr":
                    sl = entry + atr[i] * params.sl_atr_mult
                elif params.sl_type == "fixed":
                    sl = entry + params.sl_fixed
                else:  # bb_mid
                    sl = bb_basis[i]

                sl_dist = abs(sl - entry)
                if sl_dist < 0.01:
                    sl_dist = atr[i] * 0.5 if atr[i] else 5.0
                    sl = entry + sl_dist

                if params.tp_type == "rr":
                    tp = entry - sl_dist * params.tp_rr
                elif params.tp_type == "fixed":
                    tp = entry - params.tp_fixed
                else:  # bb_opposite
                    tp = bb_lower[i]
                    if tp >= entry:
                        tp = entry - sl_dist * 1.5

                current_trade = Trade("short", entry, dt, sl, tp)
                session_trades += 1

    # Close any remaining position
    if current_trade is not None:
        last_c = candles[-1]
        current_trade.exit_price = last_c.close
        current_trade.exit_time = last_c.dt_berlin
        current_trade.exit_reason = "DATA_END"
        if current_trade.direction == "long":
            current_trade.pnl = last_c.close - current_trade.entry_price
        else:
            current_trade.pnl = current_trade.entry_price - last_c.close
        trades.append(current_trade)

    # Calculate results
    result = BacktestResult(params=params, trades=trades)

    if not trades:
        return result

    pnls = [t.pnl for t in trades]
    result.total_pnl = sum(pnls)
    result.win_count = sum(1 for p in pnls if p > 0)
    result.loss_count = sum(1 for p in pnls if p <= 0)
    total = result.win_count + result.loss_count
    result.win_rate = result.win_count / total * 100 if total > 0 else 0

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    result.avg_win = sum(wins) / len(wins) if wins else 0
    result.avg_loss = sum(losses) / len(losses) if losses else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0)

    # Max drawdown
    equity = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
    result.max_drawdown = max_dd

    # Expectancy
    if total > 0:
        result.expectancy = result.total_pnl / total

    # Sharpe approximation (annualized from daily)
    if len(pnls) > 1:
        mean_pnl = result.total_pnl / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        std_pnl = math.sqrt(variance) if variance > 0 else 0.001
        result.sharpe_approx = (mean_pnl / std_pnl) * math.sqrt(252) if std_pnl > 0 else 0
    else:
        result.sharpe_approx = 0

    return result


# =============================================================================
# OPTIMIERER
# =============================================================================

def run_optimization(candles: List[Candle]) -> List[BacktestResult]:
    """Testet verschiedene Parameterkombinationen"""

    # Parameter-Grid
    cci_periods = [7, 10, 14, 20, 28]
    atr_periods = [3, 5, 7, 10, 14]
    atr_mults = [0.5, 0.8, 1.0, 1.5, 2.0]
    bb_lengths = [10, 14, 20, 30]
    bb_mults = [1.5, 1.8, 2.0, 2.5]
    modes = ["breakout", "mean_reversion", "combined"]
    need_mt_opts = [True, False]
    sl_types = ["atr", "fixed", "bb_mid"]
    sl_atr_mults = [1.0, 1.5, 2.0, 2.5]
    tp_types = ["rr", "fixed"]
    tp_rrs = [1.5, 2.0, 2.5, 3.0]
    body_filter_opts = [True, False]
    squeeze_opts = [False, True]

    # Full grid would be enormous, so we do a smart 2-phase approach:
    # Phase 1: Test indicator parameters with fixed risk settings
    # Phase 2: Optimize risk settings with best indicator params

    print("=" * 80)
    print("PHASE 1: Indikator-Parameter Optimierung")
    print("=" * 80)

    results_phase1 = []
    total_combos = len(cci_periods) * len(atr_periods) * len(atr_mults) * len(bb_lengths) * len(bb_mults) * len(modes) * len(need_mt_opts)
    print(f"Teste {total_combos} Kombinationen...")

    count = 0
    for cci_p, atr_p, atr_m, bb_l, bb_m, mode, need_mt in itertools.product(
            cci_periods, atr_periods, atr_mults, bb_lengths, bb_mults, modes, need_mt_opts):
        count += 1
        if count % 500 == 0:
            print(f"  ... {count}/{total_combos}")

        p = StrategyParams(
            cci_period=cci_p, atr_period=atr_p, atr_mult=atr_m,
            bb_length=bb_l, bb_mult=bb_m,
            mode=mode, need_mt=need_mt,
            body_filter=True, body_min_ratio=0.3,
            use_squeeze=False,
            sl_type="atr", sl_atr_mult=1.5,
            tp_type="rr", tp_rr=2.0,
            max_trades_per_session=5,
        )
        r = run_backtest(candles, p)
        if len(r.trades) >= 3:  # Mindestens 3 Trades
            results_phase1.append(r)

    # Sort by composite score: profit_factor * sqrt(trades) weighted by win_rate
    def score(r):
        n = len(r.trades)
        if n == 0 or r.profit_factor <= 0:
            return -999
        # Composite: profit_factor * expectancy * sqrt(n) penalized by drawdown
        dd_penalty = 1.0 / (1.0 + r.max_drawdown / 100.0) if r.max_drawdown > 0 else 1.0
        return r.profit_factor * r.expectancy * math.sqrt(n) * dd_penalty

    results_phase1.sort(key=score, reverse=True)

    print(f"\nPhase 1 abgeschlossen: {len(results_phase1)} gueltige Kombinationen")
    print("\nTop 10 Indikator-Kombinationen:")
    print("-" * 120)
    print(f"{'#':>3} | {'CCI':>4} {'ATR_P':>5} {'ATR_M':>5} {'BB_L':>4} {'BB_M':>5} | {'Modus':<16} {'MT':>3} | {'Trades':>6} {'WinRate':>8} {'PnL':>10} {'PF':>6} {'MaxDD':>8} {'Expect':>8} | {'Score':>8}")
    print("-" * 120)
    for idx, r in enumerate(results_phase1[:10]):
        p = r.params
        print(f"{idx+1:>3} | {p.cci_period:>4} {p.atr_period:>5} {p.atr_mult:>5.1f} {p.bb_length:>4} {p.bb_mult:>5.1f} | "
              f"{p.mode:<16} {'Ja' if p.need_mt else '--':>3} | "
              f"{len(r.trades):>6} {r.win_rate:>7.1f}% {r.total_pnl:>+10.1f} {r.profit_factor:>6.2f} {r.max_drawdown:>8.1f} {r.expectancy:>+8.1f} | {score(r):>8.1f}")

    if not results_phase1:
        print("Keine gueltigen Ergebnisse in Phase 1!")
        return []

    # Phase 2: Optimize risk parameters with top 5 indicator sets
    print(f"\n{'=' * 80}")
    print("PHASE 2: Risikomanagement Optimierung (Top 5 Indikator-Sets)")
    print("=" * 80)

    results_phase2 = []
    top_indicator_params = results_phase1[:5]

    for base_r in top_indicator_params:
        bp = base_r.params
        for sl_t, sl_am, tp_t, tp_r, body_f, squeeze, max_t in itertools.product(
                sl_types, sl_atr_mults, tp_types, tp_rrs, body_filter_opts, squeeze_opts, [3, 5, 8]):
            p = StrategyParams(
                cci_period=bp.cci_period, atr_period=bp.atr_period, atr_mult=bp.atr_mult,
                bb_length=bp.bb_length, bb_mult=bp.bb_mult,
                mode=bp.mode, need_mt=bp.need_mt,
                body_filter=body_f, body_min_ratio=0.3,
                use_squeeze=squeeze, squeeze_lookback=50,
                sl_type=sl_t, sl_atr_mult=sl_am,
                tp_type=tp_t, tp_rr=tp_r,
                max_trades_per_session=max_t,
            )
            r = run_backtest(candles, p)
            if len(r.trades) >= 3:
                results_phase2.append(r)

    results_phase2.sort(key=score, reverse=True)

    print(f"Phase 2 abgeschlossen: {len(results_phase2)} gueltige Kombinationen")
    print("\nTop 20 Gesamtergebnisse:")
    print("-" * 160)
    print(f"{'#':>3} | {'CCI':>4} {'ATR_P':>5} {'ATR_M':>5} {'BB_L':>4} {'BB_M':>5} | {'Modus':<16} {'MT':>3} {'Body':>5} {'Sqz':>4} | {'SL_Typ':<6} {'SL_M':>5} {'TP_Typ':<6} {'TP_RR':>5} {'MaxT':>4} | {'Trades':>6} {'WinRate':>8} {'PnL':>10} {'PF':>6} {'MaxDD':>8} {'Expect':>8} | {'Score':>8}")
    print("-" * 160)
    for idx, r in enumerate(results_phase2[:20]):
        p = r.params
        print(f"{idx+1:>3} | {p.cci_period:>4} {p.atr_period:>5} {p.atr_mult:>5.1f} {p.bb_length:>4} {p.bb_mult:>5.1f} | "
              f"{p.mode:<16} {'Ja' if p.need_mt else '--':>3} {'Ja' if p.body_filter else '--':>5} {'Ja' if p.use_squeeze else '--':>4} | "
              f"{p.sl_type:<6} {p.sl_atr_mult:>5.1f} {p.tp_type:<6} {p.tp_rr:>5.1f} {p.max_trades_per_session:>4} | "
              f"{len(r.trades):>6} {r.win_rate:>7.1f}% {r.total_pnl:>+10.1f} {r.profit_factor:>6.2f} {r.max_drawdown:>8.1f} {r.expectancy:>+8.1f} | {score(r):>8.1f}")

    # Best result detail
    if results_phase2:
        best = results_phase2[0]
        print(f"\n{'=' * 80}")
        print("BESTE KONFIGURATION")
        print("=" * 80)
        bp = best.params
        print(f"""
Magic Trend:
  CCI Periode:       {bp.cci_period}
  ATR Periode:       {bp.atr_period}
  ATR Multiplikator: {bp.atr_mult}

Bollinger Bands:
  BB Laenge:         {bp.bb_length}
  BB Multiplikator:  {bp.bb_mult}

Einstiegslogik:
  Modus:             {bp.mode}
  Magic Trend Filt.: {'Ja' if bp.need_mt else 'Nein'}
  Koerper-Filter:    {'Ja' if bp.body_filter else 'Nein'}
  Squeeze-Filter:    {'Ja' if bp.use_squeeze else 'Nein'}

Risikomanagement:
  SL Typ:            {bp.sl_type}
  SL ATR Mult:       {bp.sl_atr_mult}
  TP Typ:            {bp.tp_type}
  TP RR Verhaeltnis: {bp.tp_rr}
  Max Trades/Sitz.:  {bp.max_trades_per_session}

Performance (10 Tage Backtest):
  Trades:            {len(best.trades)}
  Gewinnrate:        {best.win_rate:.1f}%
  Gesamt PnL:        {best.total_pnl:+.1f} Punkte
  Profit Factor:     {best.profit_factor:.2f}
  Max Drawdown:      {best.max_drawdown:.1f} Punkte
  Erwartungswert:    {best.expectancy:+.1f} Punkte/Trade
  Avg Win:           {best.avg_win:+.1f} Punkte
  Avg Loss:          {best.avg_loss:+.1f} Punkte
""")

        # Print individual trades
        print("Einzelne Trades:")
        print("-" * 100)
        print(f"{'#':>3} | {'Richtung':<8} | {'Einstieg':>12} | {'Ausstieg':>12} | {'PnL':>10} | {'Grund':<12} | {'Einstieg Zeit':<20} | {'Ausstieg Zeit':<20}")
        print("-" * 100)
        for idx, t in enumerate(best.trades):
            print(f"{idx+1:>3} | {t.direction:<8} | {t.entry_price:>12.1f} | {t.exit_price:>12.1f} | {t.pnl:>+10.1f} | {t.exit_reason:<12} | {t.entry_time.strftime('%Y-%m-%d %H:%M'):<20} | {t.exit_time.strftime('%Y-%m-%d %H:%M') if t.exit_time else 'OPEN':<20}")

    return results_phase2


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("Lade Daten...")
    candles = load_data("/home/user/Robin/CAPITALCOM_US100, 1.csv")
    print(f"Geladen: {len(candles)} Kerzen")
    print(f"Zeitraum: {candles[0].dt_berlin} bis {candles[-1].dt_berlin} (Berlin)")
    print()

    results = run_optimization(candles)

    if results:
        best = results[0]
        bp = best.params
        print(f"\n{'=' * 80}")
        print("EMPFOHLENE PINESCRIPT-EINSTELLUNGEN")
        print("=" * 80)
        print(f"""
Kopiere diese Werte in die TradingView Strategie-Inputs:

  Magic Trend:
    CCI Periode       = {bp.cci_period}
    ATR Periode       = {bp.atr_period}
    ATR Multiplikator = {bp.atr_mult}

  Bollinger Bands:
    BB Laenge         = {bp.bb_length}
    BB Multiplikator  = {bp.bb_mult}

  Einstiegslogik:
    Modus             = {"Breakout" if bp.mode == "breakout" else "Mean Reversion" if bp.mode == "mean_reversion" else "Kombiniert"}
    MT Bestaetigung   = {"aktiviert" if bp.need_mt else "deaktiviert"}
    Koerper-Filter    = {"aktiviert" if bp.body_filter else "deaktiviert"}
    Squeeze-Filter    = {"aktiviert" if bp.use_squeeze else "deaktiviert"}

  Risikomanagement:
    SL Typ            = {"ATR" if bp.sl_type == "atr" else "Fest (Punkte)" if bp.sl_type == "fixed" else "BB Mitte"}
    SL ATR Mult       = {bp.sl_atr_mult}
    TP Typ            = {"RR Verhaeltnis" if bp.tp_type == "rr" else "Fest (Punkte)"}
    TP RR Verhaeltnis = {bp.tp_rr}
    Max Trades/Sitz.  = {bp.max_trades_per_session}
""")
