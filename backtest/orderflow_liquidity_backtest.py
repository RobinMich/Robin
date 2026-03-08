#!/usr/bin/env python3
"""
Orderflow Liquidity Map Backtester v1.0
========================================
Integrates the TradingView "Orderflow Liquidity Map [Proxy]" indicator
as an additional confirmation filter for the TrendPullbackEA strategy.

Key concepts from the PineScript indicator:
1. Liquidity Levels: Pivot highs/lows with volume → key S/R levels
2. Flow Ribbon: Cumulative delta proxy (volume * (close-open)/range)
   with fast/slow EMA crossover → bullish/bearish flow detection
3. Sweep Detection: When price sweeps a liquidity level, it signals
   potential reversal or continuation

Integration approach:
- Orderflow bullish shift (flow cross up) = confirmation for long entries
- Orderflow bearish shift (flow cross down) = confirmation for short entries
- Liquidity level proximity = higher momentum score bonus
- Tested on M1/M5 timeframes with yfinance data

Uses backtester_v4.py as base engine.
"""

import os
import sys
import json
import warnings
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Import base backtester
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtester_v4 import (
    StrategyParams, Trade, Backtester,
    calc_ema, calc_atr, calc_adx, calc_bollinger, calc_rsi,
    calc_supertrend, calc_donchian_upper, calc_donchian_lower,
    calc_volume_ma, add_indicators,
    get_context_signal_long, get_context_signal_short,
    get_validation_signal_long, get_validation_signal_short,
    get_entry_signal_long, get_entry_signal_short,
    check_rsi_filter, check_supertrend_filter, check_session_filter,
    calculate_momentum_score, find_htf_bar, find_htf_bar_by_ratio,
    _has_valid_timestamps, _safe_get,
    print_results, max_consecutive,
)


# ============================================================
# ORDERFLOW LIQUIDITY MAP PARAMETERS
# ============================================================
@dataclass
class OrderflowParams:
    # Pivot detection
    pivot_len: int = 5
    max_levels: int = 20

    # Flow Ribbon (cumulative delta proxy)
    flow_fast_len: int = 8
    flow_slow_len: int = 21
    flow_atr_mult: float = 0.8

    # Confirmation mode
    require_flow_confirmation: bool = True   # Require bullish/bearish flow shift
    require_liquidity_proximity: bool = True  # Price near liquidity level = bonus
    liquidity_proximity_atr: float = 2.0     # Within X ATR of a liquidity level
    mom_score_liq_bonus: int = 15            # Bonus momentum score near liquidity

    # Sweep detection
    sweep_as_entry: bool = True              # Allow entry on liquidity sweep
    sweep_lookback: int = 3                  # Bars to confirm sweep

    # Flow strength threshold
    flow_norm_threshold: float = 0.3         # Min normalized flow signal


# ============================================================
# ORDERFLOW INDICATOR CALCULATIONS
# ============================================================
def calc_orderflow_indicators(df):
    """Calculate all orderflow liquidity map indicators.

    Returns DataFrame with added columns:
    - delta_proxy: Volume-weighted price direction
    - cum_delta: Cumulative delta
    - flow_fast: Fast EMA of cum_delta
    - flow_slow: Slow EMA of cum_delta
    - flow_signal: flow_fast - flow_slow (positive = bullish)
    - norm_signal: Normalized flow signal
    - bull_shift: Boolean, bullish flow crossover
    - bear_shift: Boolean, bearish flow crossunder
    - pivot_high: Pivot high prices
    - pivot_low: Pivot low prices
    - pivot_high_vol: Volume at pivot highs
    - pivot_low_vol: Volume at pivot lows
    """
    df = df.copy()

    # === DELTA PROXY (from PineScript) ===
    spread = (df['high'] - df['low']).clip(lower=df['close'] * 0.0001)
    df['delta_proxy'] = df['volume'] * ((df['close'] - df['open']) / spread)
    df['cum_delta'] = df['delta_proxy'].cumsum()

    # === FLOW RIBBON ===
    of_params = OrderflowParams()
    df['flow_fast'] = calc_ema(df['cum_delta'], of_params.flow_fast_len)
    df['flow_slow'] = calc_ema(df['cum_delta'], of_params.flow_slow_len)
    df['flow_signal'] = df['flow_fast'] - df['flow_slow']

    # Normalized signal (stdev-based, like PineScript)
    stdev_base = df['cum_delta'].rolling(50).std()
    df['norm_signal'] = np.where(
        stdev_base != 0,
        df['flow_signal'] / stdev_base,
        0
    )
    df['clipped_signal'] = df['norm_signal'].abs().clip(upper=3.0)

    # Bull/Bear shifts (crossovers)
    df['bull_shift'] = (df['flow_fast'] > df['flow_slow']) & (df['flow_fast'].shift(1) <= df['flow_slow'].shift(1))
    df['bear_shift'] = (df['flow_fast'] < df['flow_slow']) & (df['flow_fast'].shift(1) >= df['flow_slow'].shift(1))

    # Current flow state
    df['flow_bullish'] = df['flow_fast'] > df['flow_slow']
    df['flow_bearish'] = df['flow_fast'] < df['flow_slow']

    return df


def calc_pivot_levels(df, pivot_len=5):
    """Calculate pivot highs and lows with their volumes.

    Returns lists of (bar_index, price, volume, is_high) tuples.
    """
    levels = []
    n = len(df)

    for i in range(pivot_len, n - pivot_len):
        # Pivot High
        is_pivot_high = True
        for j in range(1, pivot_len + 1):
            if df['high'].iloc[i] <= df['high'].iloc[i - j] or df['high'].iloc[i] <= df['high'].iloc[i + j]:
                is_pivot_high = False
                break

        if is_pivot_high:
            levels.append({
                'bar_idx': i,
                'price': df['high'].iloc[i],
                'volume': df['volume'].iloc[i],
                'is_high': True,
                'swept': False,
            })

        # Pivot Low
        is_pivot_low = True
        for j in range(1, pivot_len + 1):
            if df['low'].iloc[i] >= df['low'].iloc[i - j] or df['low'].iloc[i] >= df['low'].iloc[i + j]:
                is_pivot_low = False
                break

        if is_pivot_low:
            levels.append({
                'bar_idx': i,
                'price': df['low'].iloc[i],
                'volume': df['volume'].iloc[i],
                'is_high': False,
                'swept': False,
            })

    return levels


def check_liquidity_proximity(current_price, atr, levels, max_levels=20, atr_mult=2.0):
    """Check if price is near a liquidity level.

    Returns:
    - near_level: True if price within atr_mult * ATR of any level
    - level_above: Nearest resistance level above current price
    - level_below: Nearest support level below current price
    - avg_level_volume: Average volume at nearby levels
    """
    if not levels or atr <= 0:
        return False, None, None, 0

    active_levels = [l for l in levels[-max_levels:] if not l['swept']]
    if not active_levels:
        return False, None, None, 0

    proximity_range = atr * atr_mult
    near_level = False
    level_above = None
    level_below = None
    nearby_volumes = []

    for level in active_levels:
        dist = abs(current_price - level['price'])
        if dist <= proximity_range:
            near_level = True
            nearby_volumes.append(level['volume'])

        if level['price'] > current_price:
            if level_above is None or level['price'] < level_above:
                level_above = level['price']
        elif level['price'] < current_price:
            if level_below is None or level['price'] > level_below:
                level_below = level['price']

    avg_vol = np.mean(nearby_volumes) if nearby_volumes else 0
    return near_level, level_above, level_below, avg_vol


def check_sweep(current_high, current_low, levels, lookback_bars=3, current_idx=0):
    """Check if any liquidity level was just swept.

    Returns:
    - swept_high: True if a high liquidity level was swept (potential short)
    - swept_low: True if a low liquidity level was swept (potential long)
    - swept_prices: List of swept prices
    """
    swept_high = False
    swept_low = False
    swept_prices = []

    for level in levels:
        if level['swept']:
            continue

        # Only check recent levels (within lookback)
        if current_idx - level['bar_idx'] < 0:
            continue

        if level['is_high'] and current_high >= level['price']:
            level['swept'] = True
            swept_high = True
            swept_prices.append(level['price'])
        elif not level['is_high'] and current_low <= level['price']:
            level['swept'] = True
            swept_low = True
            swept_prices.append(level['price'])

    return swept_high, swept_low, swept_prices


# ============================================================
# ORDERFLOW-ENHANCED BACKTESTER
# ============================================================
class OrderflowBacktester(Backtester):
    """Extended backtester with Orderflow Liquidity Map confirmation."""

    def __init__(self, params=None, of_params=None, initial_capital=100000.0):
        super().__init__(params=params, initial_capital=initial_capital)
        self.of_params = of_params or OrderflowParams()
        self.of_stats = {
            'flow_confirmed': 0,
            'flow_rejected': 0,
            'liq_proximity_bonus': 0,
            'sweeps_detected': 0,
        }

    def run(self, symbol, context_df, validation_df, entry_df):
        """Run backtest with orderflow confirmation on entry timeframe."""
        p = self.params
        ofp = self.of_params

        ctx = add_indicators(context_df, p)
        val = add_indicators(validation_df, p)
        ent = add_indicators(entry_df, p)

        # Add orderflow indicators to entry TF
        ent = calc_orderflow_indicators(ent)

        # Calculate pivot liquidity levels
        liq_levels = calc_pivot_levels(ent, ofp.pivot_len)
        print(f"    Orderflow: {len(liq_levels)} liquidity levels detected")

        min_bars = max(p.ema_slow, p.bbw_lookback + p.bb_period,
                       p.donchian_period + 5, 60)  # 60 for flow ribbon warmup
        if len(ent) < min_bars:
            print(f"    Not enough entry bars ({len(ent)} < {min_bars})")
            return

        use_ratio = not _has_valid_timestamps(ent)
        entry_total = len(ent)

        print(f"    Running ORDERFLOW backtest: {len(ent)} entry bars, "
              f"{len(val)} validation bars, {len(ctx)} context bars")

        for i in range(min_bars, len(ent)):
            current_time = ent.index[i]
            current_row = ent.iloc[i]

            equity = self._calc_equity(current_row["close"])
            self.equity_curve.append({
                "time": current_time,
                "equity": equity,
                "capital": self.capital
            })
            self._equity_values.append(equity)

            if equity > self._peak_equity:
                self._peak_equity = equity

            # Manage open trades
            self._manage_trades(ent, i)

            # Check for new entries
            if len(self.open_trades) >= p.max_positions:
                continue

            # Session filter
            if not check_session_filter(ent, i, p):
                continue

            # Equity curve filter
            if p.equity_filter_enabled and len(self._equity_values) > p.equity_filter_period:
                eq_arr = np.array(self._equity_values[-p.equity_filter_period:])
                eq_ma = eq_arr.mean()
                if self._equity_values[-1] < eq_ma:
                    continue

            # Momentum score (base)
            mom_score = calculate_momentum_score(ent, i, p)

            # === ORDERFLOW ENHANCEMENTS ===

            # 1. Check liquidity proximity → bonus momentum score
            current_price = float(current_row['close'])
            current_atr = float(current_row['atr']) if not pd.isna(current_row.get('atr', np.nan)) else 0

            near_liq, level_above, level_below, avg_liq_vol = check_liquidity_proximity(
                current_price, current_atr, liq_levels,
                ofp.max_levels, ofp.liquidity_proximity_atr
            )

            if near_liq and ofp.require_liquidity_proximity:
                mom_score += ofp.mom_score_liq_bonus
                self.of_stats['liq_proximity_bonus'] += 1

            # 2. Check sweeps
            current_high = float(current_row['high'])
            current_low = float(current_row['low'])
            swept_high, swept_low, swept_prices = check_sweep(
                current_high, current_low, liq_levels,
                ofp.sweep_lookback, i
            )
            if swept_high or swept_low:
                self.of_stats['sweeps_detected'] += 1

            # 3. Flow confirmation
            flow_bullish = bool(current_row.get('flow_bullish', False))
            flow_bearish = bool(current_row.get('flow_bearish', False))
            bull_shift = bool(current_row.get('bull_shift', False))
            bear_shift = bool(current_row.get('bear_shift', False))
            norm_signal = float(current_row.get('norm_signal', 0))

            # Check minimum momentum score
            if mom_score < p.mom_score_min:
                continue

            # HTF bar lookup
            if use_ratio:
                ctx_row = find_htf_bar_by_ratio(ctx, i, entry_total)
                val_row = find_htf_bar_by_ratio(val, i, entry_total)
            else:
                ctx_row = find_htf_bar(ctx, current_time)
                val_row = find_htf_bar(val, current_time)
            if ctx_row is None or val_row is None:
                continue

            # LONG entry
            if p.direction in ('long', 'both'):
                if (get_context_signal_long(ctx_row, p) and
                    get_validation_signal_long(val_row, p) and
                    get_entry_signal_long(ent, i, p) and
                    check_rsi_filter(ent, i, p, True) and
                    check_supertrend_filter(ent, i, p, True)):

                    # === ORDERFLOW CONFIRMATION FOR LONGS ===
                    of_confirmed = True

                    if ofp.require_flow_confirmation:
                        # Require bullish flow OR recent bull shift
                        # Also allow entry on low sweep (liquidity grab → bounce)
                        has_flow = flow_bullish or norm_signal > ofp.flow_norm_threshold
                        has_shift = any(ent.iloc[max(0, i-3):i+1].get('bull_shift', pd.Series([False])))
                        has_sweep_entry = ofp.sweep_as_entry and swept_low

                        if not (has_flow or has_shift or has_sweep_entry):
                            of_confirmed = False
                            self.of_stats['flow_rejected'] += 1

                    if of_confirmed:
                        self.of_stats['flow_confirmed'] += 1
                        # Bonus for strong flow + liquidity confluence
                        if flow_bullish and near_liq and level_below is not None:
                            mom_score += 5  # Extra bonus for confluent setup
                        self._open_trade(symbol, 'long', ent, i, mom_score)
                        continue

            # SHORT entry
            if p.direction in ('short', 'both'):
                if (get_context_signal_short(ctx_row, p) and
                    get_validation_signal_short(val_row, p) and
                    get_entry_signal_short(ent, i, p) and
                    check_rsi_filter(ent, i, p, False) and
                    check_supertrend_filter(ent, i, p, False)):

                    # === ORDERFLOW CONFIRMATION FOR SHORTS ===
                    of_confirmed = True

                    if ofp.require_flow_confirmation:
                        has_flow = flow_bearish or norm_signal < -ofp.flow_norm_threshold
                        has_shift = any(ent.iloc[max(0, i-3):i+1].get('bear_shift', pd.Series([False])))
                        has_sweep_entry = ofp.sweep_as_entry and swept_high

                        if not (has_flow or has_shift or has_sweep_entry):
                            of_confirmed = False
                            self.of_stats['flow_rejected'] += 1

                    if of_confirmed:
                        self.of_stats['flow_confirmed'] += 1
                        if flow_bearish and near_liq and level_above is not None:
                            mom_score += 5
                        self._open_trade(symbol, 'short', ent, i, mom_score)

        # Close remaining
        for t in list(self.open_trades):
            last_row = ent.iloc[-1]
            self._close_trade(t, ent.index[-1], last_row["close"], "end_of_data")

        return self.trades

    def get_results(self):
        """Get results with additional orderflow stats."""
        base_result = super().get_results()
        if isinstance(base_result, tuple):
            results, trades_df = base_result
            results['orderflow_stats'] = self.of_stats
            return results, trades_df
        return base_result


# ============================================================
# DATA LOADING FOR M1/M5 (yfinance format)
# ============================================================
def load_yfinance_data(filepath):
    """Load yfinance-formatted CSV (multi-header format)."""
    # yfinance saves with 3 header rows: Price, Ticker, Datetime
    df = pd.read_csv(filepath, header=0, skiprows=[1, 2])

    # Rename columns
    col_map = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl == 'datetime' or cl == 'date':
            col_map[c] = 'datetime'
        elif cl == 'open':
            col_map[c] = 'open'
        elif cl == 'high':
            col_map[c] = 'high'
        elif cl == 'low':
            col_map[c] = 'low'
        elif cl == 'close':
            col_map[c] = 'close'
        elif cl == 'volume':
            col_map[c] = 'volume'
        elif cl == 'price':
            col_map[c] = 'datetime'  # First column is typically datetime

    df.rename(columns=col_map, inplace=True)

    if 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
        df.set_index('datetime', inplace=True)

    df.sort_index(inplace=True)

    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'volume' not in df.columns:
        df['volume'] = 0

    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
    return df


def resample_timeframe(df, tf):
    """Resample M1/M5 data to higher timeframes."""
    tf_map = {
        'M5': '5min', 'M15': '15min', 'M30': '30min',
        'H1': '1h', 'H2': '2h', 'H4': '4h',
        'D1': '1D', 'W1': '1W',
    }
    rule = tf_map.get(tf, tf)
    resampled = df.resample(rule).agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna()
    return resampled


# ============================================================
# M1/M5 SPECIFIC PRESETS
# ============================================================
def get_xauusd_m5_params():
    """XAUUSD M5 entry preset - adapted from H1 preset for scalping.
    Uses M5 entry with H1 validation and H4 context.
    """
    return StrategyParams(
        ema_fast=13, ema_mid=34, ema_slow=89,
        adx_threshold_context=10.0,
        adx_threshold_validation=8.0,
        atr_sl_multiplier=3.0,           # Tighter SL for M5
        atr_trail_multiplier=2.5,        # Tighter trail for M5
        bbw_squeeze_percentile=60.0,
        donchian_period=10,
        pb_atr_buffer=2.0,              # Tighter pullback for M5
        be_mode='pullback',
        be_rr_ratio=2.0,               # Faster BE for scalping
        trail_start_rr=1.5,
        max_positions=3,                # Fewer positions for M5
        require_bullish_bar=False,
        direction='both',
        rsi_enabled=True,
        rsi_long_max=78.0,
        rsi_short_min=22.0,
        rsi_ob_level=80.0,
        rsi_os_level=20.0,
        supertrend_enabled=False,
        session_enabled=True,           # Session filter important for M5
        session_london_start=7,
        session_london_end=11,
        session_ny_start=13,
        session_ny_end=22,              # Extended NY for gold
        partial_tp_enabled=True,
        tp1_fraction=0.4, tp1_rr=2.0,  # Faster TP for M5
        tp2_fraction=0.3, tp2_rr=4.0,
        dyn_risk_enabled=True,
        dyn_risk_max_multi=1.5,
        risk_percent=2.0,              # Lower risk for M5 scalping
        mom_score_enabled=True,
        mom_score_min=40,
        equity_filter_enabled=False,
        contract_multiplier=100.0,      # Gold contract
        commission=0.0001,
    )


def get_indices_m5_params():
    """Indices M5 entry preset - adapted for scalping."""
    return StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=10.0,
        adx_threshold_validation=8.0,
        atr_sl_multiplier=3.0,
        atr_trail_multiplier=2.5,
        bbw_squeeze_percentile=60.0,
        donchian_period=8,
        pb_atr_buffer=2.5,
        be_mode='pullback',
        be_rr_ratio=2.0,
        trail_start_rr=1.5,
        max_positions=3,
        require_bullish_bar=False,
        direction='long',               # Long-only for indices
        rsi_enabled=True,
        rsi_long_max=78.0,
        rsi_short_min=22.0,
        rsi_ob_level=80.0,
        rsi_os_level=20.0,
        supertrend_enabled=False,
        session_enabled=True,
        session_ny_start=13,
        session_ny_end=21,
        partial_tp_enabled=True,
        tp1_fraction=0.4, tp1_rr=2.0,
        tp2_fraction=0.3, tp2_rr=4.0,
        dyn_risk_enabled=True,
        risk_percent=3.0,
        mom_score_enabled=True,
        mom_score_min=40,
        equity_filter_enabled=False,
        commission=0.0001,
    )


def get_orderflow_params_aggressive():
    """Aggressive orderflow params - more trades, lower threshold."""
    return OrderflowParams(
        pivot_len=5,
        max_levels=20,
        flow_fast_len=8,
        flow_slow_len=21,
        require_flow_confirmation=True,
        require_liquidity_proximity=True,
        liquidity_proximity_atr=2.5,
        mom_score_liq_bonus=15,
        sweep_as_entry=True,
        flow_norm_threshold=0.2,        # Lower threshold = more signals
    )


def get_orderflow_params_conservative():
    """Conservative orderflow params - fewer but higher quality trades."""
    return OrderflowParams(
        pivot_len=7,
        max_levels=15,
        flow_fast_len=8,
        flow_slow_len=21,
        require_flow_confirmation=True,
        require_liquidity_proximity=True,
        liquidity_proximity_atr=1.5,    # Tighter proximity
        mom_score_liq_bonus=20,         # Higher bonus for confluence
        sweep_as_entry=True,
        flow_norm_threshold=0.5,        # Higher threshold = stronger signals only
    )


# ============================================================
# COMPARISON TEST: WITH vs WITHOUT ORDERFLOW
# ============================================================
def run_comparison_test(symbol, entry_data, validation_data, context_data,
                        strategy_params, of_params=None, initial_capital=100000.0):
    """Run side-by-side comparison: base strategy vs orderflow-enhanced."""

    print(f"\n{'='*70}")
    print(f"  COMPARISON TEST: {symbol}")
    print(f"  Entry: {len(entry_data)} bars | Val: {len(validation_data)} bars | Ctx: {len(context_data)} bars")
    print(f"{'='*70}")

    # --- BASE (no orderflow) ---
    print(f"\n  [1/2] Running BASE strategy (no orderflow)...")
    bt_base = Backtester(params=strategy_params, initial_capital=initial_capital)
    bt_base.run(symbol, context_data, validation_data, entry_data)
    base_result = bt_base.get_results()

    if isinstance(base_result, tuple):
        base_results, base_trades = base_result
    else:
        base_results = base_result
        base_trades = pd.DataFrame()

    # --- ORDERFLOW ENHANCED ---
    print(f"\n  [2/2] Running ORDERFLOW-ENHANCED strategy...")
    of_p = of_params or OrderflowParams()
    bt_of = OrderflowBacktester(params=strategy_params, of_params=of_p,
                                 initial_capital=initial_capital)
    bt_of.run(symbol, context_data, validation_data, entry_data)
    of_result = bt_of.get_results()

    if isinstance(of_result, tuple):
        of_results, of_trades = of_result
    else:
        of_results = of_result
        of_trades = pd.DataFrame()

    # --- PRINT COMPARISON ---
    print(f"\n{'='*70}")
    print(f"  COMPARISON RESULTS: {symbol}")
    print(f"{'='*70}")

    def safe_get(d, key, default=0):
        if isinstance(d, dict):
            return d.get(key, default)
        return default

    metrics = [
        ('Total Trades', 'total_trades'),
        ('Win Rate %', 'win_rate'),
        ('Profit Factor', 'profit_factor'),
        ('Total P&L $', 'total_pnl'),
        ('Total Return %', 'total_return_pct'),
        ('Max DD %', 'max_drawdown_pct'),
        ('Avg RR', 'avg_rr'),
        ('Median RR', 'median_rr'),
        ('Avg Mom Score', 'avg_momentum_score'),
    ]

    print(f"\n  {'Metric':<20s} {'BASE':>15s} {'ORDERFLOW':>15s} {'DIFF':>12s}")
    print(f"  {'-'*62}")

    for label, key in metrics:
        base_val = safe_get(base_results, key, 0)
        of_val = safe_get(of_results, key, 0)
        if isinstance(base_val, (int, float)) and isinstance(of_val, (int, float)):
            diff = of_val - base_val
            diff_str = f"{diff:+.2f}"
        else:
            diff_str = "N/A"
        print(f"  {label:<20s} {str(base_val):>15s} {str(of_val):>15s} {diff_str:>12s}")

    # Orderflow stats
    if isinstance(of_results, dict) and 'orderflow_stats' in of_results:
        ofs = of_results['orderflow_stats']
        print(f"\n  ORDERFLOW STATISTICS:")
        print(f"    Flow Confirmed:      {ofs.get('flow_confirmed', 0)}")
        print(f"    Flow Rejected:       {ofs.get('flow_rejected', 0)}")
        print(f"    Liquidity Bonuses:   {ofs.get('liq_proximity_bonus', 0)}")
        print(f"    Sweeps Detected:     {ofs.get('sweeps_detected', 0)}")

    print(f"{'='*70}\n")

    return {
        'base': base_results,
        'orderflow': of_results,
        'base_trades': base_trades,
        'of_trades': of_trades,
        'of_stats': bt_of.of_stats,
    }


# ============================================================
# PARAMETER SWEEP FOR ORDERFLOW
# ============================================================
def sweep_orderflow_params(symbol, entry_data, validation_data, context_data,
                           strategy_params, initial_capital=100000.0):
    """Sweep orderflow parameters to find optimal configuration."""

    print(f"\n{'='*70}")
    print(f"  ORDERFLOW PARAMETER SWEEP: {symbol}")
    print(f"{'='*70}")

    sweep_configs = []

    # Sweep flow_norm_threshold
    for thresh in [0.1, 0.2, 0.3, 0.5, 0.8]:
        # Sweep liquidity_proximity_atr
        for liq_atr in [1.0, 1.5, 2.0, 2.5, 3.0]:
            # Sweep pivot_len
            for plen in [3, 5, 7]:
                # Sweep flow_fast_len
                for fast in [5, 8, 13]:
                    ofp = OrderflowParams(
                        pivot_len=plen,
                        flow_fast_len=fast,
                        flow_slow_len=21,
                        flow_norm_threshold=thresh,
                        liquidity_proximity_atr=liq_atr,
                        require_flow_confirmation=True,
                        require_liquidity_proximity=True,
                        sweep_as_entry=True,
                        mom_score_liq_bonus=15,
                    )
                    sweep_configs.append(ofp)

    print(f"  Testing {len(sweep_configs)} configurations...")

    results = []
    best_pf = 0
    best_config = None

    for idx, ofp in enumerate(sweep_configs):
        bt = OrderflowBacktester(params=strategy_params, of_params=ofp,
                                  initial_capital=initial_capital)
        bt.run(symbol, context_data, validation_data, entry_data)
        result = bt.get_results()

        if isinstance(result, tuple):
            r, _ = result
            trades = r.get('total_trades', 0)
            pf = r.get('profit_factor', 0)
            wr = r.get('win_rate', 0)
            dd = r.get('max_drawdown_pct', 0)
            pnl = r.get('total_pnl', 0)

            # Only consider configs with minimum trades
            if trades >= 3:
                score = pf * (wr / 100) * (1 + dd / 100)  # Composite score
                results.append({
                    'config': ofp,
                    'trades': trades,
                    'pf': pf,
                    'wr': wr,
                    'dd': dd,
                    'pnl': pnl,
                    'score': score,
                    'of_stats': bt.of_stats,
                })

                if score > best_pf:
                    best_pf = score
                    best_config = ofp

        if (idx + 1) % 50 == 0:
            print(f"    Tested {idx+1}/{len(sweep_configs)}...")

    # Sort by composite score
    results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n  TOP 10 CONFIGURATIONS:")
    print(f"  {'#':>3s} {'Trades':>6s} {'PF':>6s} {'WR%':>6s} {'DD%':>7s} {'PnL':>12s} {'Score':>8s} "
          f"{'Thresh':>6s} {'LiqATR':>6s} {'PvtL':>4s} {'Fast':>4s}")
    print(f"  {'-'*80}")

    for idx, r in enumerate(results[:10]):
        c = r['config']
        print(f"  {idx+1:>3d} {r['trades']:>6d} {r['pf']:>6.2f} {r['wr']:>5.1f}% {r['dd']:>6.1f}% "
              f"${r['pnl']:>11,.0f} {r['score']:>8.3f} "
              f"{c.flow_norm_threshold:>6.1f} {c.liquidity_proximity_atr:>6.1f} {c.pivot_len:>4d} {c.flow_fast_len:>4d}")

    return results, best_config


# ============================================================
# MAIN: RUN M5 BACKTESTS
# ============================================================
def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(results_dir, exist_ok=True)

    print("=" * 70)
    print("  ORDERFLOW LIQUIDITY MAP BACKTESTER v1.0")
    print("  M1/M5 Timeframe Testing with Orderflow Confirmation")
    print("=" * 70)

    all_results = {}

    # ============================
    # TEST 1: XAUUSD M5
    # ============================
    xau_m5_path = os.path.join(repo_root, "data_XAUUSD_M5.csv")
    if os.path.exists(xau_m5_path):
        print(f"\n  Loading XAUUSD M5 data...")
        try:
            m5_data = load_yfinance_data(xau_m5_path)
            print(f"    M5: {len(m5_data)} bars, {m5_data.index[0]} to {m5_data.index[-1]}")

            # Resample to higher TFs for multi-TF analysis
            h1_data = resample_timeframe(m5_data, 'H1')
            h4_data = resample_timeframe(m5_data, 'H4')
            d1_data = resample_timeframe(m5_data, 'D1')
            print(f"    Resampled: H1={len(h1_data)}, H4={len(h4_data)}, D1={len(d1_data)} bars")

            xau_params = get_xauusd_m5_params()

            # Comparison test (H4 context, H1 validation, M5 entry)
            comp = run_comparison_test(
                "XAUUSD_M5", m5_data, h1_data, h4_data,
                xau_params, OrderflowParams(), initial_capital=100000.0
            )
            all_results['XAUUSD_M5'] = comp

            # Also test with D1 context, H4 validation, M5 entry
            if len(d1_data) >= 10:
                comp2 = run_comparison_test(
                    "XAUUSD_M5_v2", m5_data, h4_data, d1_data,
                    xau_params, OrderflowParams(), initial_capital=100000.0
                )
                all_results['XAUUSD_M5_v2'] = comp2

        except Exception as e:
            print(f"    ERROR loading XAUUSD M5: {e}")
            import traceback
            traceback.print_exc()

    # ============================
    # TEST 2: XAUUSD M1
    # ============================
    xau_m1_path = os.path.join(repo_root, "data_XAUUSD_M1.csv")
    if os.path.exists(xau_m1_path):
        print(f"\n  Loading XAUUSD M1 data...")
        try:
            m1_data = load_yfinance_data(xau_m1_path)
            print(f"    M1: {len(m1_data)} bars, {m1_data.index[0]} to {m1_data.index[-1]}")

            h1_data = resample_timeframe(m1_data, 'H1')
            h4_data = resample_timeframe(m1_data, 'H4')
            m5_from_m1 = resample_timeframe(m1_data, 'M5')
            print(f"    Resampled: M5={len(m5_from_m1)}, H1={len(h1_data)}, H4={len(h4_data)} bars")

            xau_params = get_xauusd_m5_params()
            xau_params.atr_sl_multiplier = 2.5   # Tighter for M1
            xau_params.atr_trail_multiplier = 2.0
            xau_params.donchian_period = 12

            # M1 entry with H1 validation and H4 context
            comp = run_comparison_test(
                "XAUUSD_M1", m1_data, h1_data, h4_data,
                xau_params, OrderflowParams(), initial_capital=100000.0
            )
            all_results['XAUUSD_M1'] = comp

        except Exception as e:
            print(f"    ERROR loading XAUUSD M1: {e}")
            import traceback
            traceback.print_exc()

    # ============================
    # TEST 3: US100 (NQ) M5
    # ============================
    nq_m5_path = os.path.join(repo_root, "data_US100_M5.csv")
    if os.path.exists(nq_m5_path):
        print(f"\n  Loading US100 (NQ) M5 data...")
        try:
            m5_data = load_yfinance_data(nq_m5_path)
            print(f"    M5: {len(m5_data)} bars, {m5_data.index[0]} to {m5_data.index[-1]}")

            h1_data = resample_timeframe(m5_data, 'H1')
            h4_data = resample_timeframe(m5_data, 'H4')
            d1_data = resample_timeframe(m5_data, 'D1')
            print(f"    Resampled: H1={len(h1_data)}, H4={len(h4_data)}, D1={len(d1_data)} bars")

            nq_params = get_indices_m5_params()

            comp = run_comparison_test(
                "US100_M5", m5_data, h1_data, h4_data,
                nq_params, OrderflowParams(), initial_capital=100000.0
            )
            all_results['US100_M5'] = comp

        except Exception as e:
            print(f"    ERROR loading US100 M5: {e}")
            import traceback
            traceback.print_exc()

    # ============================
    # TEST 4: US500 (ES) M5
    # ============================
    es_m5_path = os.path.join(repo_root, "data_US500_M5.csv")
    if os.path.exists(es_m5_path):
        print(f"\n  Loading US500 (ES) M5 data...")
        try:
            m5_data = load_yfinance_data(es_m5_path)
            print(f"    M5: {len(m5_data)} bars, {m5_data.index[0]} to {m5_data.index[-1]}")

            h1_data = resample_timeframe(m5_data, 'H1')
            h4_data = resample_timeframe(m5_data, 'H4')
            d1_data = resample_timeframe(m5_data, 'D1')
            print(f"    Resampled: H1={len(h1_data)}, H4={len(h4_data)}, D1={len(d1_data)} bars")

            es_params = get_indices_m5_params()

            comp = run_comparison_test(
                "US500_M5", m5_data, h1_data, h4_data,
                es_params, OrderflowParams(), initial_capital=100000.0
            )
            all_results['US500_M5'] = comp

        except Exception as e:
            print(f"    ERROR loading US500 M5: {e}")
            import traceback
            traceback.print_exc()

    # ============================
    # TEST 5: US100 M1
    # ============================
    nq_m1_path = os.path.join(repo_root, "data_US100_M1.csv")
    if os.path.exists(nq_m1_path):
        print(f"\n  Loading US100 (NQ) M1 data...")
        try:
            m1_data = load_yfinance_data(nq_m1_path)
            print(f"    M1: {len(m1_data)} bars, {m1_data.index[0]} to {m1_data.index[-1]}")

            m5_data = resample_timeframe(m1_data, 'M5')
            h1_data = resample_timeframe(m1_data, 'H1')
            h4_data = resample_timeframe(m1_data, 'H4')
            print(f"    Resampled: M5={len(m5_data)}, H1={len(h1_data)}, H4={len(h4_data)} bars")

            nq_params = get_indices_m5_params()
            nq_params.atr_sl_multiplier = 2.5
            nq_params.atr_trail_multiplier = 2.0

            comp = run_comparison_test(
                "US100_M1", m1_data, h1_data, h4_data,
                nq_params, OrderflowParams(), initial_capital=100000.0
            )
            all_results['US100_M1'] = comp

        except Exception as e:
            print(f"    ERROR loading US100 M1: {e}")
            import traceback
            traceback.print_exc()

    # ============================
    # PARAMETER SWEEP (on best performing symbol)
    # ============================
    if os.path.exists(xau_m5_path):
        print(f"\n  Running PARAMETER SWEEP on XAUUSD M5...")
        try:
            m5_data = load_yfinance_data(xau_m5_path)
            h1_data = resample_timeframe(m5_data, 'H1')
            h4_data = resample_timeframe(m5_data, 'H4')
            xau_params = get_xauusd_m5_params()

            sweep_results, best_of_config = sweep_orderflow_params(
                "XAUUSD_M5", m5_data, h1_data, h4_data,
                xau_params, initial_capital=100000.0
            )

            if best_of_config:
                print(f"\n  BEST ORDERFLOW CONFIG:")
                print(f"    pivot_len: {best_of_config.pivot_len}")
                print(f"    flow_fast_len: {best_of_config.flow_fast_len}")
                print(f"    flow_norm_threshold: {best_of_config.flow_norm_threshold}")
                print(f"    liquidity_proximity_atr: {best_of_config.liquidity_proximity_atr}")

                all_results['best_of_config'] = {
                    'pivot_len': best_of_config.pivot_len,
                    'flow_fast_len': best_of_config.flow_fast_len,
                    'flow_slow_len': best_of_config.flow_slow_len,
                    'flow_norm_threshold': best_of_config.flow_norm_threshold,
                    'liquidity_proximity_atr': best_of_config.liquidity_proximity_atr,
                    'mom_score_liq_bonus': best_of_config.mom_score_liq_bonus,
                    'sweep_as_entry': best_of_config.sweep_as_entry,
                }

        except Exception as e:
            print(f"    ERROR in sweep: {e}")
            import traceback
            traceback.print_exc()

    # ============================
    # SAVE ALL RESULTS
    # ============================
    summary = {}
    for key, val in all_results.items():
        if isinstance(val, dict):
            if 'base' in val and 'orderflow' in val:
                summary[key] = {
                    'base': {k: v for k, v in val['base'].items()
                             if k != 'exit_reasons'} if isinstance(val['base'], dict) else str(val['base']),
                    'orderflow': {k: v for k, v in val['orderflow'].items()
                                  if k not in ('exit_reasons', 'orderflow_stats')} if isinstance(val['orderflow'], dict) else str(val['orderflow']),
                    'of_stats': val.get('of_stats', {}),
                }
            else:
                summary[key] = val

    results_file = os.path.join(results_dir, "orderflow_m5_results.json")
    with open(results_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_file}")

    print(f"\n{'='*70}")
    print(f"  ALL TESTS COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
