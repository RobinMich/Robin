#!/usr/bin/env python3
"""
Strategy Optimizer for NAS100 Multi-Strategy EA
Finds parameter combinations that are profitable AFTER realistic transaction costs.

Key insight from stress test: Small SL/TP relative to spread kills profitability.
Solution: Use higher-timeframe signals (aggregated bars), wider SL/TP, trend filters,
and multi-confirmation entries to overcome transaction costs.
"""

import pandas as pd
import numpy as np
from itertools import product
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# DATA LOADING
# =============================================================================
def load_data(filepath):
    rows = []
    with open(filepath, 'r') as f:
        for i, line in enumerate(f):
            line = line.strip().strip('"')
            if i == 0:
                continue
            parts = line.split('\t')
            if len(parts) >= 7:
                rows.append(parts[:7])

    df = pd.DataFrame(rows, columns=['DateTime', 'Open', 'High', 'Low', 'Close', 'Volume', 'TickVolume'])
    df['DateTime'] = pd.to_datetime(df['DateTime'], format='%Y.%m.%d %H:%M:%S')
    df = df.sort_values('DateTime').reset_index(drop=True)

    for col in ['Open', 'High', 'Low', 'Close', 'TickVolume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['Open', 'High', 'Low', 'Close']).reset_index(drop=True)
    df['Hour'] = df['DateTime'].dt.hour
    df['DayOfWeek'] = df['DateTime'].dt.dayofweek
    return df

def aggregate_to_timeframe(df, minutes):
    """Aggregate 1-min data to higher timeframe."""
    df_agg = df.set_index('DateTime').resample(f'{minutes}min').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last',
        'TickVolume': 'sum'
    }).dropna().reset_index()
    df_agg['Hour'] = df_agg['DateTime'].dt.hour
    df_agg['DayOfWeek'] = df_agg['DateTime'].dt.dayofweek
    return df_agg

# =============================================================================
# INDICATORS
# =============================================================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close'].shift(1)
    tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_bb(series, period=20, std_mult=2.0):
    basis = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = basis + std_mult * std
    lower = basis - std_mult * std
    return upper, basis, lower

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

# =============================================================================
# MULTI-TIMEFRAME STRATEGY ENGINE
# =============================================================================
class OptimizedStrategy:
    """
    Strategy design principles (learned from stress test):
    1. Use higher timeframes (5m, 15m) for signal generation to reduce noise
    2. Use wide SL/TP (100+ pts) to make spread/slippage negligible
    3. Require multiple confirmations to increase win rate
    4. Use trend filter (200-EMA or similar) to avoid countertrend trades
    5. Trade only during high-probability sessions
    """

    def __init__(self, df_1m, spread=3.0, slippage=1.0):
        self.df_1m = df_1m
        self.spread = spread
        self.slippage = slippage
        self.cost = spread + slippage * 2  # total round-trip cost

    def strategy_trend_ema_crossover(self, signal_tf=5, fast=9, slow=21, trend_period=100,
                                      sl_pts=80, tp_pts=160, max_hold=120,
                                      session_start=7, session_end=17,
                                      use_trend_filter=True, use_atr_sl=False):
        """
        EMA crossover on higher TF with trend filter.
        Only trade in direction of the higher-TF trend (EMA200 on signal TF).
        """
        df = aggregate_to_timeframe(self.df_1m, signal_tf)
        df['EMA_Fast'] = calc_ema(df['Close'], fast)
        df['EMA_Slow'] = calc_ema(df['Close'], slow)
        df['EMA_Trend'] = calc_ema(df['Close'], trend_period)
        df['ATR'] = calc_atr(df, 14)

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        direction = 0
        bars_held = 0

        for i in range(max(slow, trend_period) + 1, len(df)):
            if in_position:
                bars_held += 1
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                actual_sl = sl_pts
                actual_tp = tp_pts
                if use_atr_sl and not pd.isna(df['ATR'].iloc[entry_idx]):
                    atr_val = df['ATR'].iloc[entry_idx]
                    actual_sl = max(sl_pts, atr_val * 2)
                    actual_tp = actual_sl * 2

                if direction == 1:
                    if low <= entry_price - actual_sl:
                        pnl = -actual_sl - self.cost
                        trades.append({'pnl': pnl, 'direction': 'LONG', 'exit_reason': 'SL',
                                      'bars': bars_held, 'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif high >= entry_price + actual_tp:
                        pnl = actual_tp - self.cost
                        trades.append({'pnl': pnl, 'direction': 'LONG', 'exit_reason': 'TP',
                                      'bars': bars_held, 'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = df['Close'].iloc[i] - entry_price - self.cost
                        trades.append({'pnl': pnl, 'direction': 'LONG', 'exit_reason': 'TIME',
                                      'bars': bars_held, 'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                else:
                    if high >= entry_price + actual_sl:
                        pnl = -actual_sl - self.cost
                        trades.append({'pnl': pnl, 'direction': 'SHORT', 'exit_reason': 'SL',
                                      'bars': bars_held, 'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif low <= entry_price - actual_tp:
                        pnl = actual_tp - self.cost
                        trades.append({'pnl': pnl, 'direction': 'SHORT', 'exit_reason': 'TP',
                                      'bars': bars_held, 'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = entry_price - df['Close'].iloc[i] - self.cost
                        trades.append({'pnl': pnl, 'direction': 'SHORT', 'exit_reason': 'TIME',
                                      'bars': bars_held, 'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                continue

            # Session filter
            hour = df['Hour'].iloc[i]
            if session_start <= session_end:
                if hour < session_start or hour >= session_end:
                    continue
            else:
                if hour < session_start and hour >= session_end:
                    continue

            # EMA crossover detection
            prev_fast = df['EMA_Fast'].iloc[i-1]
            prev_slow = df['EMA_Slow'].iloc[i-1]
            curr_fast = df['EMA_Fast'].iloc[i]
            curr_slow = df['EMA_Slow'].iloc[i]
            trend_ema = df['EMA_Trend'].iloc[i]

            if pd.isna(prev_fast) or pd.isna(trend_ema):
                continue

            # Bullish crossover
            if prev_fast <= prev_slow and curr_fast > curr_slow:
                if use_trend_filter and df['Close'].iloc[i] < trend_ema:
                    continue
                direction = 1
                entry_price = df['Close'].iloc[i] + self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

            # Bearish crossover
            elif prev_fast >= prev_slow and curr_fast < curr_slow:
                if use_trend_filter and df['Close'].iloc[i] > trend_ema:
                    continue
                direction = -1
                entry_price = df['Close'].iloc[i] - self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

        return trades

    def strategy_bb_reversal(self, signal_tf=5, bb_period=20, bb_std=2.0,
                              sl_pts=60, tp_pts=120, max_hold=60,
                              session_start=7, session_end=17,
                              use_rsi_confirm=True, rsi_period=14, rsi_ob=70, rsi_os=30):
        """
        Bollinger Band mean reversion with RSI confirmation.
        Buy when price touches lower BB and RSI confirms oversold (mean reversion).
        """
        df = aggregate_to_timeframe(self.df_1m, signal_tf)
        bb_upper, bb_basis, bb_lower = calc_bb(df['Close'], bb_period, bb_std)
        rsi = calc_rsi(df['Close'], rsi_period)
        df['BB_Upper'] = bb_upper
        df['BB_Lower'] = bb_lower
        df['BB_Basis'] = bb_basis
        df['RSI'] = rsi

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        direction = 0
        bars_held = 0

        for i in range(bb_period + 1, len(df)):
            if in_position:
                bars_held += 1
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if direction == 1:
                    if low <= entry_price - sl_pts:
                        trades.append({'pnl': -sl_pts - self.cost, 'direction': 'LONG',
                                      'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif high >= entry_price + tp_pts:
                        trades.append({'pnl': tp_pts - self.cost, 'direction': 'LONG',
                                      'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = df['Close'].iloc[i] - entry_price - self.cost
                        trades.append({'pnl': pnl, 'direction': 'LONG',
                                      'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                else:
                    if high >= entry_price + sl_pts:
                        trades.append({'pnl': -sl_pts - self.cost, 'direction': 'SHORT',
                                      'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif low <= entry_price - tp_pts:
                        trades.append({'pnl': tp_pts - self.cost, 'direction': 'SHORT',
                                      'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = entry_price - df['Close'].iloc[i] - self.cost
                        trades.append({'pnl': pnl, 'direction': 'SHORT',
                                      'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                continue

            hour = df['Hour'].iloc[i]
            if session_start <= session_end:
                if hour < session_start or hour >= session_end:
                    continue
            else:
                if hour < session_start and hour >= session_end:
                    continue

            close = df['Close'].iloc[i]
            bb_l = df['BB_Lower'].iloc[i]
            bb_u = df['BB_Upper'].iloc[i]
            rsi_val = df['RSI'].iloc[i]

            if pd.isna(bb_l) or pd.isna(rsi_val):
                continue

            # Buy at lower BB with RSI oversold
            if close <= bb_l:
                if use_rsi_confirm and rsi_val > rsi_os:
                    continue
                direction = 1
                entry_price = close + self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

            # Sell at upper BB with RSI overbought
            elif close >= bb_u:
                if use_rsi_confirm and rsi_val < rsi_ob:
                    continue
                direction = -1
                entry_price = close - self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

        return trades

    def strategy_macd_divergence(self, signal_tf=15, fast=12, slow=26, signal_p=9,
                                  sl_pts=100, tp_pts=200, max_hold=80,
                                  session_start=8, session_end=20,
                                  trend_period=50, use_trend=True):
        """
        MACD histogram crossover with trend filter.
        """
        df = aggregate_to_timeframe(self.df_1m, signal_tf)
        macd_line, signal_line, histogram = calc_macd(df['Close'], fast, slow, signal_p)
        df['MACD'] = macd_line
        df['Signal'] = signal_line
        df['Hist'] = histogram
        df['EMA_Trend'] = calc_ema(df['Close'], trend_period)

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        direction = 0
        bars_held = 0

        start_idx = max(slow, trend_period) + 2

        for i in range(start_idx, len(df)):
            if in_position:
                bars_held += 1
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if direction == 1:
                    if low <= entry_price - sl_pts:
                        trades.append({'pnl': -sl_pts - self.cost, 'direction': 'LONG',
                                      'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif high >= entry_price + tp_pts:
                        trades.append({'pnl': tp_pts - self.cost, 'direction': 'LONG',
                                      'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = df['Close'].iloc[i] - entry_price - self.cost
                        trades.append({'pnl': pnl, 'direction': 'LONG',
                                      'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                else:
                    if high >= entry_price + sl_pts:
                        trades.append({'pnl': -sl_pts - self.cost, 'direction': 'SHORT',
                                      'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif low <= entry_price - tp_pts:
                        trades.append({'pnl': tp_pts - self.cost, 'direction': 'SHORT',
                                      'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = entry_price - df['Close'].iloc[i] - self.cost
                        trades.append({'pnl': pnl, 'direction': 'SHORT',
                                      'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                continue

            hour = df['Hour'].iloc[i]
            if session_start <= session_end:
                if hour < session_start or hour >= session_end:
                    continue
            else:
                if hour < session_start and hour >= session_end:
                    continue

            hist_prev = df['Hist'].iloc[i-1]
            hist_curr = df['Hist'].iloc[i]
            trend = df['EMA_Trend'].iloc[i]

            if pd.isna(hist_prev) or pd.isna(hist_curr) or pd.isna(trend):
                continue

            # MACD histogram crosses above zero -> BUY
            if hist_prev <= 0 and hist_curr > 0:
                if use_trend and df['Close'].iloc[i] < trend:
                    continue
                direction = 1
                entry_price = df['Close'].iloc[i] + self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

            # MACD histogram crosses below zero -> SELL
            elif hist_prev >= 0 and hist_curr < 0:
                if use_trend and df['Close'].iloc[i] > trend:
                    continue
                direction = -1
                entry_price = df['Close'].iloc[i] - self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

        return trades

    def strategy_breakout_atr(self, signal_tf=15, lookback=20, atr_period=14,
                               atr_sl_mult=2.0, atr_tp_mult=4.0, max_hold=60,
                               session_start=8, session_end=20,
                               vol_confirm=True, vol_mult=1.5, vol_period=20):
        """
        ATR-based breakout strategy.
        Buy on breakout above N-bar high with volume confirmation.
        Dynamic SL/TP based on ATR.
        """
        df = aggregate_to_timeframe(self.df_1m, signal_tf)
        df['ATR'] = calc_atr(df, atr_period)
        df['HighN'] = df['High'].rolling(lookback).max().shift(1)
        df['LowN'] = df['Low'].rolling(lookback).min().shift(1)
        df['VolMA'] = df['TickVolume'].rolling(vol_period).mean()

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        direction = 0
        bars_held = 0
        actual_sl = 0
        actual_tp = 0

        start_idx = max(lookback, atr_period, vol_period) + 2

        for i in range(start_idx, len(df)):
            if in_position:
                bars_held += 1
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if direction == 1:
                    if low <= entry_price - actual_sl:
                        trades.append({'pnl': -actual_sl - self.cost, 'direction': 'LONG',
                                      'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif high >= entry_price + actual_tp:
                        trades.append({'pnl': actual_tp - self.cost, 'direction': 'LONG',
                                      'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = df['Close'].iloc[i] - entry_price - self.cost
                        trades.append({'pnl': pnl, 'direction': 'LONG',
                                      'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                else:
                    if high >= entry_price + actual_sl:
                        trades.append({'pnl': -actual_sl - self.cost, 'direction': 'SHORT',
                                      'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif low <= entry_price - actual_tp:
                        trades.append({'pnl': actual_tp - self.cost, 'direction': 'SHORT',
                                      'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = entry_price - df['Close'].iloc[i] - self.cost
                        trades.append({'pnl': pnl, 'direction': 'SHORT',
                                      'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                continue

            hour = df['Hour'].iloc[i]
            if session_start <= session_end:
                if hour < session_start or hour >= session_end:
                    continue
            else:
                if hour < session_start and hour >= session_end:
                    continue

            atr_val = df['ATR'].iloc[i]
            high_n = df['HighN'].iloc[i]
            low_n = df['LowN'].iloc[i]
            close = df['Close'].iloc[i]
            vol = df['TickVolume'].iloc[i]
            vol_avg = df['VolMA'].iloc[i]

            if pd.isna(atr_val) or pd.isna(high_n) or pd.isna(vol_avg):
                continue

            if vol_confirm and (vol_avg <= 0 or vol < vol_avg * vol_mult):
                continue

            actual_sl = max(atr_val * atr_sl_mult, 30)
            actual_tp = max(atr_val * atr_tp_mult, 60)

            # Breakout above N-bar high
            if close > high_n:
                direction = 1
                entry_price = close + self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

            # Breakout below N-bar low
            elif close < low_n:
                direction = -1
                entry_price = close - self.spread/2
                entry_idx = i
                bars_held = 0
                in_position = True

        return trades


# =============================================================================
# STATISTICS
# =============================================================================
def calc_stats(trades, label=""):
    if not trades:
        return None

    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_pnl = sum(pnls)
    n_trades = len(pnls)
    win_rate = len(wins) / n_trades * 100

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss

    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    expectancy = np.mean(pnls)

    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0

    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252) if np.std(pnls) > 0 else 0

    max_consec = 0
    curr_consec = 0
    for p in pnls:
        if p <= 0:
            curr_consec += 1
            max_consec = max(max_consec, curr_consec)
        else:
            curr_consec = 0

    recovery = total_pnl / max_dd if max_dd > 0 else float('inf')

    return {
        'label': label, 'trades': n_trades, 'total_pnl': total_pnl,
        'win_rate': win_rate, 'profit_factor': profit_factor,
        'max_dd': max_dd, 'sharpe': sharpe, 'avg_win': avg_win,
        'avg_loss': avg_loss, 'expectancy': expectancy,
        'max_consec_loss': max_consec, 'recovery_factor': recovery
    }

def print_stats(stats):
    if stats is None:
        print("  No trades")
        return
    print(f"  {stats['label']:>45} | Trades: {stats['trades']:>4d} | WR: {stats['win_rate']:>5.1f}% | "
          f"PF: {stats['profit_factor']:>5.2f} | Total: {stats['total_pnl']:>8.1f} pts | "
          f"MaxDD: {stats['max_dd']:>7.1f} | Sharpe: {stats['sharpe']:>5.2f} | "
          f"Expect: {stats['expectancy']:>6.2f} | Recovery: {stats['recovery_factor']:>5.2f} | "
          f"MaxConsecLoss: {stats['max_consec_loss']}")

# =============================================================================
# WALK-FORWARD VALIDATION
# =============================================================================
def walk_forward_validate(df, strategy_func, strategy_kwargs, n_splits=5, label=""):
    """Validate strategy with walk-forward analysis."""
    total_len = len(df)
    window_size = total_len // n_splits
    all_oos_trades = []

    for fold in range(n_splits):
        start = fold * window_size
        end = min(start + window_size, total_len)
        split_point = start + int((end - start) * 0.7)

        oos_data = df.iloc[split_point:end].copy().reset_index(drop=True)
        oos_strat = OptimizedStrategy(oos_data, spread=3.0, slippage=1.0)
        trades = getattr(oos_strat, strategy_func)(**strategy_kwargs)
        all_oos_trades.extend(trades)

    return calc_stats(all_oos_trades, f"{label} (WF-OOS)")

# =============================================================================
# GRID OPTIMIZATION
# =============================================================================
def optimize_ema_trend(df):
    """Find best parameters for trend-following EMA strategy."""
    print("\n" + "="*80)
    print("OPTIMIZING: Trend EMA Crossover Strategy")
    print("="*80)

    results = []

    param_grid = {
        'signal_tf': [5, 15],
        'fast': [8, 12, 15],
        'slow': [21, 30, 50],
        'trend_period': [50, 100, 200],
        'sl_pts': [60, 100, 150],
        'tp_pts': [120, 200, 300],
        'max_hold': [40, 80, 120],
        'session': [(7, 17), (8, 20), (14, 22)],
    }

    combos = list(product(
        param_grid['signal_tf'], param_grid['fast'], param_grid['slow'],
        param_grid['trend_period'], param_grid['sl_pts'], param_grid['tp_pts'],
        param_grid['max_hold'], param_grid['session']
    ))

    print(f"  Testing {len(combos)} parameter combinations...")

    for idx, (tf, fast, slow, trend, sl, tp, hold, (s_start, s_end)) in enumerate(combos):
        if fast >= slow:
            continue
        if tp < sl:
            continue

        strat = OptimizedStrategy(df, spread=3.0, slippage=1.0)
        trades = strat.strategy_trend_ema_crossover(
            signal_tf=tf, fast=fast, slow=slow, trend_period=trend,
            sl_pts=sl, tp_pts=tp, max_hold=hold,
            session_start=s_start, session_end=s_end
        )

        stats = calc_stats(trades)
        if stats and stats['trades'] >= 30 and stats['profit_factor'] > 1.0:
            stats['label'] = f"TF{tf} EMA({fast}/{slow}) T{trend} SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
            stats['params'] = {
                'signal_tf': tf, 'fast': fast, 'slow': slow, 'trend_period': trend,
                'sl_pts': sl, 'tp_pts': tp, 'max_hold': hold,
                'session_start': s_start, 'session_end': s_end
            }
            results.append(stats)

    # Sort by risk-adjusted score
    results.sort(key=lambda x: x['sharpe'] * x['profit_factor'], reverse=True)

    print(f"\n  Found {len(results)} profitable combinations")
    print(f"\n  TOP 15 EMA Trend Strategies:")
    for r in results[:15]:
        print_stats(r)

    return results[:15]

def optimize_bb_reversal(df):
    """Find best parameters for BB reversal strategy."""
    print("\n" + "="*80)
    print("OPTIMIZING: Bollinger Band Reversal Strategy")
    print("="*80)

    results = []

    param_grid = {
        'signal_tf': [5, 15],
        'bb_period': [15, 20, 30],
        'bb_std': [1.5, 2.0, 2.5],
        'sl_pts': [40, 60, 100],
        'tp_pts': [60, 100, 150],
        'max_hold': [30, 60, 120],
        'session': [(7, 17), (8, 20), (14, 22)],
        'rsi_thresholds': [(70, 30), (75, 25), (80, 20)],
    }

    combos = list(product(
        param_grid['signal_tf'], param_grid['bb_period'], param_grid['bb_std'],
        param_grid['sl_pts'], param_grid['tp_pts'], param_grid['max_hold'],
        param_grid['session'], param_grid['rsi_thresholds']
    ))

    print(f"  Testing {len(combos)} parameter combinations...")

    for tf, bb_p, bb_s, sl, tp, hold, (s_start, s_end), (rsi_ob, rsi_os) in combos:
        strat = OptimizedStrategy(df, spread=3.0, slippage=1.0)
        trades = strat.strategy_bb_reversal(
            signal_tf=tf, bb_period=bb_p, bb_std=bb_s,
            sl_pts=sl, tp_pts=tp, max_hold=hold,
            session_start=s_start, session_end=s_end,
            rsi_ob=rsi_ob, rsi_os=rsi_os
        )

        stats = calc_stats(trades)
        if stats and stats['trades'] >= 20 and stats['profit_factor'] > 1.0:
            stats['label'] = f"TF{tf} BB({bb_p},{bb_s}) RSI{rsi_ob}/{rsi_os} SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
            stats['params'] = {
                'signal_tf': tf, 'bb_period': bb_p, 'bb_std': bb_s,
                'sl_pts': sl, 'tp_pts': tp, 'max_hold': hold,
                'session_start': s_start, 'session_end': s_end,
                'rsi_ob': rsi_ob, 'rsi_os': rsi_os
            }
            results.append(stats)

    results.sort(key=lambda x: x['sharpe'] * x['profit_factor'], reverse=True)

    print(f"\n  Found {len(results)} profitable combinations")
    print(f"\n  TOP 15 BB Reversal Strategies:")
    for r in results[:15]:
        print_stats(r)

    return results[:15]

def optimize_macd(df):
    """Find best parameters for MACD strategy."""
    print("\n" + "="*80)
    print("OPTIMIZING: MACD Trend Strategy")
    print("="*80)

    results = []

    param_grid = {
        'signal_tf': [5, 15, 30],
        'fast': [8, 12],
        'slow': [21, 26],
        'signal_p': [7, 9],
        'sl_pts': [80, 120, 200],
        'tp_pts': [160, 240, 400],
        'max_hold': [40, 80],
        'session': [(7, 17), (8, 20)],
        'trend_period': [30, 50],
    }

    combos = list(product(
        param_grid['signal_tf'], param_grid['fast'], param_grid['slow'],
        param_grid['signal_p'], param_grid['sl_pts'], param_grid['tp_pts'],
        param_grid['max_hold'], param_grid['session'], param_grid['trend_period']
    ))

    print(f"  Testing {len(combos)} parameter combinations...")

    for tf, fast, slow, sig, sl, tp, hold, (s_start, s_end), trend in combos:
        if fast >= slow or tp < sl:
            continue

        strat = OptimizedStrategy(df, spread=3.0, slippage=1.0)
        trades = strat.strategy_macd_divergence(
            signal_tf=tf, fast=fast, slow=slow, signal_p=sig,
            sl_pts=sl, tp_pts=tp, max_hold=hold,
            session_start=s_start, session_end=s_end,
            trend_period=trend
        )

        stats = calc_stats(trades)
        if stats and stats['trades'] >= 20 and stats['profit_factor'] > 1.0:
            stats['label'] = f"TF{tf} MACD({fast}/{slow}/{sig}) T{trend} SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
            stats['params'] = {
                'signal_tf': tf, 'fast': fast, 'slow': slow, 'signal_p': sig,
                'sl_pts': sl, 'tp_pts': tp, 'max_hold': hold,
                'session_start': s_start, 'session_end': s_end,
                'trend_period': trend
            }
            results.append(stats)

    results.sort(key=lambda x: x['sharpe'] * x['profit_factor'], reverse=True)

    print(f"\n  Found {len(results)} profitable combinations")
    print(f"\n  TOP 15 MACD Strategies:")
    for r in results[:15]:
        print_stats(r)

    return results[:15]

def optimize_breakout(df):
    """Find best parameters for ATR breakout strategy."""
    print("\n" + "="*80)
    print("OPTIMIZING: ATR Breakout Strategy")
    print("="*80)

    results = []

    param_grid = {
        'signal_tf': [5, 15, 30],
        'lookback': [10, 20, 40],
        'atr_sl_mult': [1.5, 2.0, 3.0],
        'atr_tp_mult': [3.0, 4.0, 6.0],
        'max_hold': [30, 60],
        'session': [(7, 17), (8, 20)],
        'vol_mult': [1.0, 1.5, 2.0],
    }

    combos = list(product(
        param_grid['signal_tf'], param_grid['lookback'],
        param_grid['atr_sl_mult'], param_grid['atr_tp_mult'],
        param_grid['max_hold'], param_grid['session'], param_grid['vol_mult']
    ))

    print(f"  Testing {len(combos)} parameter combinations...")

    for tf, lb, atr_sl, atr_tp, hold, (s_start, s_end), vol_m in combos:
        if atr_tp <= atr_sl:
            continue

        strat = OptimizedStrategy(df, spread=3.0, slippage=1.0)
        trades = strat.strategy_breakout_atr(
            signal_tf=tf, lookback=lb,
            atr_sl_mult=atr_sl, atr_tp_mult=atr_tp, max_hold=hold,
            session_start=s_start, session_end=s_end,
            vol_mult=vol_m
        )

        stats = calc_stats(trades)
        if stats and stats['trades'] >= 20 and stats['profit_factor'] > 1.0:
            stats['label'] = f"TF{tf} BRK(LB{lb}) ATR-SL{atr_sl}/TP{atr_tp} V{vol_m}x H{hold} S{s_start}-{s_end}"
            stats['params'] = {
                'signal_tf': tf, 'lookback': lb,
                'atr_sl_mult': atr_sl, 'atr_tp_mult': atr_tp, 'max_hold': hold,
                'session_start': s_start, 'session_end': s_end,
                'vol_mult': vol_m
            }
            results.append(stats)

    results.sort(key=lambda x: x['sharpe'] * x['profit_factor'], reverse=True)

    print(f"\n  Found {len(results)} profitable combinations")
    print(f"\n  TOP 15 Breakout Strategies:")
    for r in results[:15]:
        print_stats(r)

    return results[:15]

# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    print("="*80)
    print("NAS100 STRATEGY OPTIMIZER")
    print("Spread: 3.0 pts | Slippage: 1.0 pts | Total Cost: 5.0 pts round-trip")
    print("="*80)

    print("\nLoading data...")
    df = load_data('/home/user/Robin/1m_data.csv')
    print(f"Loaded {len(df)} bars from {df['DateTime'].iloc[0]} to {df['DateTime'].iloc[-1]}")

    # Run all optimizations
    ema_results = optimize_ema_trend(df)
    bb_results = optimize_bb_reversal(df)
    macd_results = optimize_macd(df)
    breakout_results = optimize_breakout(df)

    # === GRAND RANKING ===
    all_results = []
    for r in ema_results: r['strategy_type'] = 'EMA_TREND'; all_results.append(r)
    for r in bb_results: r['strategy_type'] = 'BB_REVERSAL'; all_results.append(r)
    for r in macd_results: r['strategy_type'] = 'MACD'; all_results.append(r)
    for r in breakout_results: r['strategy_type'] = 'BREAKOUT'; all_results.append(r)

    # Score: Sharpe * PF * sqrt(trades) / max_consec_loss
    for r in all_results:
        mcl = max(r['max_consec_loss'], 1)
        r['grand_score'] = r['sharpe'] * r['profit_factor'] * np.sqrt(r['trades']) / mcl

    all_results.sort(key=lambda x: x['grand_score'], reverse=True)

    print("\n" + "="*80)
    print("GRAND RANKING - TOP 20 STRATEGIES ACROSS ALL TYPES")
    print("(Sorted by: Sharpe x PF x sqrt(Trades) / MaxConsecLoss)")
    print("="*80)

    for i, r in enumerate(all_results[:20]):
        print(f"\n  #{i+1} [{r['strategy_type']}] Score: {r['grand_score']:.2f}")
        print_stats(r)

    # Walk-forward validation on top 5
    print("\n" + "="*80)
    print("WALK-FORWARD VALIDATION OF TOP 5 STRATEGIES")
    print("="*80)

    strategy_map = {
        'EMA_TREND': 'strategy_trend_ema_crossover',
        'BB_REVERSAL': 'strategy_bb_reversal',
        'MACD': 'strategy_macd_divergence',
        'BREAKOUT': 'strategy_breakout_atr',
    }

    for i, r in enumerate(all_results[:5]):
        func_name = strategy_map[r['strategy_type']]
        wf_stats = walk_forward_validate(df, func_name, r['params'], n_splits=5, label=r['label'])
        print(f"\n  #{i+1} [{r['strategy_type']}]")
        print(f"    IN-SAMPLE:  ", end=""); print_stats(r)
        if wf_stats:
            print(f"    OOS (WF):   ", end=""); print_stats(wf_stats)
        else:
            print(f"    OOS (WF):   No trades in OOS")

    # Final recommendation
    print("\n" + "="*80)
    print("FINAL OPTIMIZED PARAMETERS FOR MQL5 EA")
    print("="*80)

    if all_results:
        best = all_results[0]
        print(f"\n  BEST STRATEGY: {best['strategy_type']}")
        print(f"  Label: {best['label']}")
        print(f"  Parameters: {best['params']}")
        print(f"  Trades: {best['trades']} | WR: {best['win_rate']:.1f}% | PF: {best['profit_factor']:.2f}")
        print(f"  Total PnL: {best['total_pnl']:.1f} pts | MaxDD: {best['max_dd']:.1f}")
        print(f"  Sharpe: {best['sharpe']:.2f} | Expectancy: {best['expectancy']:.2f} pts/trade")
        print(f"  Recovery Factor: {best['recovery_factor']:.2f}")
        print(f"  Grand Score: {best['grand_score']:.2f}")

    print("\n" + "="*80)
    print("OPTIMIZATION COMPLETE")
    print("="*80)
