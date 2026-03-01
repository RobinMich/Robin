#!/usr/bin/env python3
"""
Strategy Optimizer for NAS100 Multi-Strategy EA (Vectorized)
Finds parameters profitable AFTER realistic transaction costs.
Uses vectorized numpy/pandas operations for speed.
"""

import pandas as pd
import numpy as np
from itertools import product
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
    return df

def aggregate_tf(df, minutes):
    agg = df.set_index('DateTime').resample(f'{minutes}min').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last',
        'TickVolume': 'sum'
    }).dropna().reset_index()
    agg['Hour'] = agg['DateTime'].dt.hour
    return agg

# =============================================================================
# VECTORIZED INDICATORS
# =============================================================================
def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=p-1, min_periods=p).mean()
    l = (-d.clip(upper=0)).ewm(com=p-1, min_periods=p).mean()
    return 100 - 100 / (1 + g/l)

def atr(df, p=14):
    tr = pd.concat([df['High']-df['Low'],
                    (df['High']-df['Close'].shift(1)).abs(),
                    (df['Low']-df['Close'].shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

# =============================================================================
# VECTORIZED BACKTEST ENGINE
# =============================================================================
def backtest_signals(df, signals, sl_pts, tp_pts, max_hold, cost=5.0):
    """
    Vectorized-ish backtest. signals: Series of +1 (buy), -1 (sell), 0 (none).
    Iterates trades but uses numpy arrays for speed.
    """
    sig = signals.values
    opens = df['Open'].values
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    n = len(df)

    trades = []
    i = 0
    while i < n:
        if sig[i] == 0:
            i += 1
            continue

        direction = sig[i]
        entry_price = closes[i]
        entry_i = i

        # Simulate forward
        for j in range(i + 1, min(i + max_hold + 1, n)):
            bars = j - entry_i

            if direction == 1:  # LONG
                if lows[j] <= entry_price - sl_pts:
                    trades.append(-sl_pts - cost)
                    i = j + 1
                    break
                elif highs[j] >= entry_price + tp_pts:
                    trades.append(tp_pts - cost)
                    i = j + 1
                    break
                elif bars >= max_hold:
                    trades.append(closes[j] - entry_price - cost)
                    i = j + 1
                    break
            else:  # SHORT
                if highs[j] >= entry_price + sl_pts:
                    trades.append(-sl_pts - cost)
                    i = j + 1
                    break
                elif lows[j] <= entry_price - tp_pts:
                    trades.append(tp_pts - cost)
                    i = j + 1
                    break
                elif bars >= max_hold:
                    trades.append(entry_price - closes[j] - cost)
                    i = j + 1
                    break
        else:
            i += 1
            continue
        # i already advanced in the break

    return trades

def calc_stats(trades, label=""):
    if not trades or len(trades) < 5:
        return None
    pnls = np.array(trades)
    n = len(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    total = pnls.sum()
    wr = len(wins) / n * 100
    gp = wins.sum() if len(wins) > 0 else 0
    gl = abs(losses.sum()) if len(losses) > 0 else 0.001
    pf = gp / gl
    expect = pnls.mean()
    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0

    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    max_dd = dd.max()

    # Max consecutive losses
    is_loss = (pnls <= 0).astype(int)
    mcl = 0
    curr = 0
    for x in is_loss:
        if x: curr += 1; mcl = max(mcl, curr)
        else: curr = 0

    recovery = total / max_dd if max_dd > 0 else float('inf')

    return {
        'label': label, 'trades': n, 'total_pnl': total,
        'win_rate': wr, 'profit_factor': pf, 'max_dd': max_dd,
        'sharpe': sharpe, 'expectancy': expect, 'max_consec_loss': mcl,
        'recovery_factor': recovery,
        'avg_win': wins.mean() if len(wins) > 0 else 0,
        'avg_loss': losses.mean() if len(losses) > 0 else 0,
    }

def fmt(s):
    if s is None: return "  No trades"
    return (f"  {s['label']:>55} | T:{s['trades']:>4d} | WR:{s['win_rate']:>5.1f}% | "
            f"PF:{s['profit_factor']:>5.2f} | PnL:{s['total_pnl']:>8.1f} | "
            f"DD:{s['max_dd']:>7.1f} | Sh:{s['sharpe']:>5.2f} | "
            f"Exp:{s['expectancy']:>6.2f} | Rec:{s['recovery_factor']:>5.2f} | MCL:{s['max_consec_loss']}")

# =============================================================================
# SIGNAL GENERATORS (vectorized)
# =============================================================================
def gen_ema_crossover(df, fast_p, slow_p, trend_p, session_start, session_end):
    """Generate EMA crossover signals with trend filter."""
    ef = ema(df['Close'], fast_p)
    es = ema(df['Close'], slow_p)
    et = ema(df['Close'], trend_p)

    cross_up = (ef.shift(1) <= es.shift(1)) & (ef > es)
    cross_down = (ef.shift(1) >= es.shift(1)) & (ef < es)

    # Session filter
    hour = df['Hour']
    if session_start <= session_end:
        in_session = (hour >= session_start) & (hour < session_end)
    else:
        in_session = (hour >= session_start) | (hour < session_end)

    # Trend filter
    above_trend = df['Close'] > et
    below_trend = df['Close'] < et

    buy = cross_up & in_session & above_trend
    sell = cross_down & in_session & below_trend

    signals = pd.Series(0, index=df.index)
    signals[buy] = 1
    signals[sell] = -1
    return signals

def gen_bb_reversal(df, bb_period, bb_std, rsi_period, rsi_ob, rsi_os, session_start, session_end):
    """Generate Bollinger Band reversal signals with RSI confirmation."""
    basis = df['Close'].rolling(bb_period).mean()
    std = df['Close'].rolling(bb_period).std()
    upper = basis + bb_std * std
    lower = basis - bb_std * std
    r = rsi(df['Close'], rsi_period)

    hour = df['Hour']
    if session_start <= session_end:
        in_session = (hour >= session_start) & (hour < session_end)
    else:
        in_session = (hour >= session_start) | (hour < session_end)

    buy = (df['Close'] <= lower) & (r < rsi_os) & in_session
    sell = (df['Close'] >= upper) & (r > rsi_ob) & in_session

    signals = pd.Series(0, index=df.index)
    signals[buy] = 1
    signals[sell] = -1
    return signals

def gen_macd(df, fast_p, slow_p, signal_p, trend_p, session_start, session_end):
    """Generate MACD histogram crossover signals with trend filter."""
    ef = ema(df['Close'], fast_p)
    es = ema(df['Close'], slow_p)
    macd_line = ef - es
    sig_line = ema(macd_line, signal_p)
    hist = macd_line - sig_line
    et = ema(df['Close'], trend_p)

    cross_up = (hist.shift(1) <= 0) & (hist > 0)
    cross_down = (hist.shift(1) >= 0) & (hist < 0)

    hour = df['Hour']
    if session_start <= session_end:
        in_session = (hour >= session_start) & (hour < session_end)
    else:
        in_session = (hour >= session_start) | (hour < session_end)

    above_trend = df['Close'] > et
    below_trend = df['Close'] < et

    buy = cross_up & in_session & above_trend
    sell = cross_down & in_session & below_trend

    signals = pd.Series(0, index=df.index)
    signals[buy] = 1
    signals[sell] = -1
    return signals

def gen_breakout(df, lookback, vol_mult, vol_period, session_start, session_end):
    """Generate breakout signals above/below N-bar high/low with volume."""
    high_n = df['High'].rolling(lookback).max().shift(1)
    low_n = df['Low'].rolling(lookback).min().shift(1)
    vol_ma = df['TickVolume'].rolling(vol_period).mean()

    hour = df['Hour']
    if session_start <= session_end:
        in_session = (hour >= session_start) & (hour < session_end)
    else:
        in_session = (hour >= session_start) | (hour < session_end)

    vol_ok = (vol_ma > 0) & (df['TickVolume'] >= vol_ma * vol_mult)

    buy = (df['Close'] > high_n) & in_session & vol_ok
    sell = (df['Close'] < low_n) & in_session & vol_ok

    signals = pd.Series(0, index=df.index)
    signals[buy] = 1
    signals[sell] = -1
    return signals

def gen_rsi_momentum(df, rsi_period, upper, lower, session_start, session_end):
    """RSI momentum continuation signals."""
    r = rsi(df['Close'], rsi_period)

    hour = df['Hour']
    if session_start <= session_end:
        in_session = (hour >= session_start) & (hour < session_end)
    else:
        in_session = (hour >= session_start) | (hour < session_end)

    buy = (r > upper) & in_session
    sell = (r < lower) & in_session

    signals = pd.Series(0, index=df.index)
    signals[buy] = 1
    signals[sell] = -1
    return signals

def gen_ema_vol_combined(df, fast_p, slow_p, trend_p, vol_mult, vol_period, session_start, session_end):
    """EMA crossover confirmed by volume spike."""
    ef = ema(df['Close'], fast_p)
    es = ema(df['Close'], slow_p)
    et = ema(df['Close'], trend_p)

    cross_up = (ef.shift(1) <= es.shift(1)) & (ef > es)
    cross_down = (ef.shift(1) >= es.shift(1)) & (ef < es)

    vol_ma = df['TickVolume'].rolling(vol_period).mean()
    vol_ok = (vol_ma > 0) & (df['TickVolume'] >= vol_ma * vol_mult)

    hour = df['Hour']
    if session_start <= session_end:
        in_session = (hour >= session_start) & (hour < session_end)
    else:
        in_session = (hour >= session_start) | (hour < session_end)

    above_trend = df['Close'] > et
    below_trend = df['Close'] < et

    buy = cross_up & in_session & above_trend & vol_ok
    sell = cross_down & in_session & below_trend & vol_ok

    signals = pd.Series(0, index=df.index)
    signals[buy] = 1
    signals[sell] = -1
    return signals

# =============================================================================
# OPTIMIZATION
# =============================================================================
def optimize_all(df_1m):
    """Run optimization across all strategy types and timeframes."""
    all_results = []
    cost = 5.0  # spread 3 + slippage 2

    timeframes = [5, 15]
    sessions = [(7, 17), (8, 20), (14, 22)]

    # Pre-aggregate data
    agg_data = {}
    for tf in timeframes:
        agg_data[tf] = aggregate_tf(df_1m, tf)
        print(f"  TF{tf}: {len(agg_data[tf])} bars")

    # =========================================================================
    # 1. EMA CROSSOVER WITH TREND
    # =========================================================================
    print("\n--- Optimizing EMA Crossover + Trend Filter ---")
    count = 0
    for tf in timeframes:
        df = agg_data[tf]
        for fast, slow, trend in product([8, 12, 15], [21, 30, 50], [50, 100, 200]):
            if fast >= slow:
                continue
            for s_start, s_end in sessions:
                for sl, tp, hold in product([60, 100, 150, 200], [120, 200, 300, 400], [40, 80, 120]):
                    if tp < sl * 1.5:
                        continue
                    signals = gen_ema_crossover(df, fast, slow, trend, s_start, s_end)
                    trades = backtest_signals(df, signals, sl, tp, hold, cost)
                    stats = calc_stats(trades)
                    if stats and stats['trades'] >= 20 and stats['profit_factor'] > 1.0:
                        stats['label'] = f"EMA TF{tf} ({fast}/{slow}) T{trend} SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
                        stats['strategy_type'] = 'EMA_TREND'
                        stats['params'] = dict(signal_tf=tf, fast=fast, slow=slow, trend_period=trend,
                                               sl=sl, tp=tp, max_hold=hold, session_start=s_start, session_end=s_end)
                        all_results.append(stats)
                    count += 1
    print(f"  Tested {count} combinations")

    # =========================================================================
    # 2. BOLLINGER BAND REVERSAL + RSI
    # =========================================================================
    print("--- Optimizing BB Reversal + RSI ---")
    count = 0
    for tf in timeframes:
        df = agg_data[tf]
        for bb_p, bb_s in product([15, 20, 30], [1.5, 2.0, 2.5]):
            for rsi_p, rsi_ob, rsi_os in [(14, 70, 30), (14, 75, 25), (14, 80, 20)]:
                for s_start, s_end in sessions:
                    for sl, tp, hold in product([40, 60, 100, 150], [60, 100, 150, 200], [30, 60, 120]):
                        if tp < sl:
                            continue
                        signals = gen_bb_reversal(df, bb_p, bb_s, rsi_p, rsi_ob, rsi_os, s_start, s_end)
                        trades = backtest_signals(df, signals, sl, tp, hold, cost)
                        stats = calc_stats(trades)
                        if stats and stats['trades'] >= 20 and stats['profit_factor'] > 1.0:
                            stats['label'] = f"BB TF{tf} ({bb_p},{bb_s}) RSI{rsi_ob}/{rsi_os} SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
                            stats['strategy_type'] = 'BB_REVERSAL'
                            stats['params'] = dict(signal_tf=tf, bb_period=bb_p, bb_std=bb_s,
                                                   rsi_period=rsi_p, rsi_ob=rsi_ob, rsi_os=rsi_os,
                                                   sl=sl, tp=tp, max_hold=hold, session_start=s_start, session_end=s_end)
                            all_results.append(stats)
                        count += 1
    print(f"  Tested {count} combinations")

    # =========================================================================
    # 3. MACD + TREND
    # =========================================================================
    print("--- Optimizing MACD + Trend ---")
    count = 0
    for tf in timeframes:
        df = agg_data[tf]
        for fast, slow, sig in product([8, 12], [21, 26], [7, 9]):
            if fast >= slow:
                continue
            for trend in [30, 50, 100]:
                for s_start, s_end in sessions:
                    for sl, tp, hold in product([80, 120, 200], [160, 240, 400], [40, 80]):
                        if tp < sl * 1.5:
                            continue
                        signals = gen_macd(df, fast, slow, sig, trend, s_start, s_end)
                        trades = backtest_signals(df, signals, sl, tp, hold, cost)
                        stats = calc_stats(trades)
                        if stats and stats['trades'] >= 15 and stats['profit_factor'] > 1.0:
                            stats['label'] = f"MACD TF{tf} ({fast}/{slow}/{sig}) T{trend} SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
                            stats['strategy_type'] = 'MACD'
                            stats['params'] = dict(signal_tf=tf, fast=fast, slow=slow, signal_p=sig,
                                                   trend_period=trend, sl=sl, tp=tp, max_hold=hold,
                                                   session_start=s_start, session_end=s_end)
                            all_results.append(stats)
                        count += 1
    print(f"  Tested {count} combinations")

    # =========================================================================
    # 4. BREAKOUT
    # =========================================================================
    print("--- Optimizing Breakout ---")
    count = 0
    for tf in timeframes:
        df = agg_data[tf]
        for lb in [10, 20, 40]:
            for vol_m, vol_p in product([1.0, 1.5, 2.0], [20]):
                for s_start, s_end in sessions:
                    for sl, tp, hold in product([60, 100, 150, 200], [120, 200, 300, 400], [30, 60]):
                        if tp < sl * 1.5:
                            continue
                        signals = gen_breakout(df, lb, vol_m, vol_p, s_start, s_end)
                        trades = backtest_signals(df, signals, sl, tp, hold, cost)
                        stats = calc_stats(trades)
                        if stats and stats['trades'] >= 15 and stats['profit_factor'] > 1.0:
                            stats['label'] = f"BRK TF{tf} LB{lb} V{vol_m}x SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
                            stats['strategy_type'] = 'BREAKOUT'
                            stats['params'] = dict(signal_tf=tf, lookback=lb, vol_mult=vol_m,
                                                   vol_period=vol_p, sl=sl, tp=tp, max_hold=hold,
                                                   session_start=s_start, session_end=s_end)
                            all_results.append(stats)
                        count += 1
    print(f"  Tested {count} combinations")

    # =========================================================================
    # 5. RSI MOMENTUM
    # =========================================================================
    print("--- Optimizing RSI Momentum ---")
    count = 0
    for tf in timeframes:
        df = agg_data[tf]
        for rsi_p in [10, 14, 20]:
            for upper, lower in [(75, 25), (80, 20), (85, 15)]:
                for s_start, s_end in sessions:
                    for sl, tp, hold in product([60, 100, 150, 200], [120, 200, 300], [15, 30, 60]):
                        if tp < sl:
                            continue
                        signals = gen_rsi_momentum(df, rsi_p, upper, lower, s_start, s_end)
                        trades = backtest_signals(df, signals, sl, tp, hold, cost)
                        stats = calc_stats(trades)
                        if stats and stats['trades'] >= 20 and stats['profit_factor'] > 1.0:
                            stats['label'] = f"RSI TF{tf} ({rsi_p}) {upper}/{lower} SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
                            stats['strategy_type'] = 'RSI_MOM'
                            stats['params'] = dict(signal_tf=tf, rsi_period=rsi_p, upper=upper, lower=lower,
                                                   sl=sl, tp=tp, max_hold=hold, session_start=s_start, session_end=s_end)
                            all_results.append(stats)
                        count += 1
    print(f"  Tested {count} combinations")

    # =========================================================================
    # 6. EMA + VOLUME CONFIRMED
    # =========================================================================
    print("--- Optimizing EMA + Volume Confirmation ---")
    count = 0
    for tf in timeframes:
        df = agg_data[tf]
        for fast, slow, trend in product([8, 12], [21, 30, 50], [50, 100]):
            if fast >= slow:
                continue
            for vol_m in [1.3, 1.5, 2.0]:
                for s_start, s_end in sessions:
                    for sl, tp, hold in product([60, 100, 150], [120, 200, 300], [40, 80]):
                        if tp < sl * 1.5:
                            continue
                        signals = gen_ema_vol_combined(df, fast, slow, trend, vol_m, 20, s_start, s_end)
                        trades = backtest_signals(df, signals, sl, tp, hold, cost)
                        stats = calc_stats(trades)
                        if stats and stats['trades'] >= 10 and stats['profit_factor'] > 1.0:
                            stats['label'] = f"E+V TF{tf} ({fast}/{slow}) T{trend} V{vol_m}x SL{sl}/TP{tp} H{hold} S{s_start}-{s_end}"
                            stats['strategy_type'] = 'EMA_VOL'
                            stats['params'] = dict(signal_tf=tf, fast=fast, slow=slow, trend_period=trend,
                                                   vol_mult=vol_m, vol_period=20, sl=sl, tp=tp,
                                                   max_hold=hold, session_start=s_start, session_end=s_end)
                            all_results.append(stats)
                        count += 1
    print(f"  Tested {count} combinations")

    return all_results

# =============================================================================
# WALK-FORWARD VALIDATION
# =============================================================================
def walk_forward_validate(df_1m, strategy_type, params, n_splits=5):
    """Validate strategy out-of-sample using walk-forward."""
    total_len = len(df_1m)
    window = total_len // n_splits
    all_trades = []

    signal_funcs = {
        'EMA_TREND': lambda df, p: gen_ema_crossover(df, p['fast'], p['slow'], p['trend_period'],
                                                      p['session_start'], p['session_end']),
        'BB_REVERSAL': lambda df, p: gen_bb_reversal(df, p['bb_period'], p['bb_std'], p['rsi_period'],
                                                      p['rsi_ob'], p['rsi_os'],
                                                      p['session_start'], p['session_end']),
        'MACD': lambda df, p: gen_macd(df, p['fast'], p['slow'], p['signal_p'], p['trend_period'],
                                        p['session_start'], p['session_end']),
        'BREAKOUT': lambda df, p: gen_breakout(df, p['lookback'], p['vol_mult'], p['vol_period'],
                                                p['session_start'], p['session_end']),
        'RSI_MOM': lambda df, p: gen_rsi_momentum(df, p['rsi_period'], p['upper'], p['lower'],
                                                    p['session_start'], p['session_end']),
        'EMA_VOL': lambda df, p: gen_ema_vol_combined(df, p['fast'], p['slow'], p['trend_period'],
                                                       p['vol_mult'], p['vol_period'],
                                                       p['session_start'], p['session_end']),
    }

    for fold in range(n_splits):
        start = fold * window
        end = min(start + window, total_len)
        split = start + int((end - start) * 0.7)

        oos = df_1m.iloc[split:end].copy().reset_index(drop=True)
        tf = params.get('signal_tf', 5)
        df_tf = aggregate_tf(oos, tf)

        if len(df_tf) < 50:
            continue

        signals = signal_funcs[strategy_type](df_tf, params)
        trades = backtest_signals(df_tf, signals, params['sl'], params['tp'], params['max_hold'], 5.0)
        all_trades.extend(trades)

    return all_trades

# =============================================================================
# MONTE CARLO
# =============================================================================
def monte_carlo(trades, n_sims=2000, balance=10000):
    """Monte Carlo simulation for risk analysis."""
    pnls = np.array(trades)
    n = len(pnls)
    if n < 10:
        return None

    final_balances = np.zeros(n_sims)
    max_dds = np.zeros(n_sims)

    for s in range(n_sims):
        shuffled = np.random.permutation(pnls)
        equity = np.cumsum(shuffled) + balance
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        max_dds[s] = dd.max()
        final_balances[s] = equity[-1]

    return {
        'final_mean': final_balances.mean(),
        'final_5th': np.percentile(final_balances, 5),
        'final_95th': np.percentile(final_balances, 95),
        'dd_mean': max_dds.mean(),
        'dd_95th': np.percentile(max_dds, 95),
        'dd_99th': np.percentile(max_dds, 99),
        'ruin_prob': (max_dds >= balance * 0.5).mean() * 100
    }

# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    print("="*80)
    print("NAS100 STRATEGY OPTIMIZER (Vectorized)")
    print("Cost model: Spread 3.0 + Slippage 2.0 = 5.0 pts round-trip")
    print("="*80)

    print("\nLoading data...")
    df = load_data('/home/user/Robin/1m_data.csv')
    print(f"Loaded {len(df)} bars: {df['DateTime'].iloc[0]} to {df['DateTime'].iloc[-1]}")

    # Run optimization
    all_results = optimize_all(df)

    print(f"\n{'='*80}")
    print(f"TOTAL PROFITABLE STRATEGIES FOUND: {len(all_results)}")
    print(f"{'='*80}")

    # Score & rank
    for r in all_results:
        mcl = max(r['max_consec_loss'], 1)
        r['score'] = r['sharpe'] * r['profit_factor'] * np.sqrt(r['trades']) / mcl

    all_results.sort(key=lambda x: x['score'], reverse=True)

    # Print top 30
    print(f"\nTOP 30 STRATEGIES (by composite score):")
    for i, r in enumerate(all_results[:30]):
        print(f"\n  #{i+1} [{r['strategy_type']}] Score: {r['score']:.2f}")
        print(fmt(r))

    # Walk-forward validation of top 10
    print(f"\n{'='*80}")
    print("WALK-FORWARD OUT-OF-SAMPLE VALIDATION (Top 10)")
    print(f"{'='*80}")

    validated = []
    for i, r in enumerate(all_results[:10]):
        oos_trades = walk_forward_validate(df, r['strategy_type'], r['params'])
        oos_stats = calc_stats(oos_trades, f"{r['label']} (OOS)")

        print(f"\n  #{i+1} [{r['strategy_type']}]")
        print(f"    IS:  {fmt(r)}")
        if oos_stats:
            print(f"    OOS: {fmt(oos_stats)}")
            if oos_stats['profit_factor'] > 1.0 and oos_stats['trades'] >= 10:
                validated.append({
                    'is': r, 'oos': oos_stats,
                    'oos_pf': oos_stats['profit_factor'],
                    'oos_sharpe': oos_stats['sharpe'],
                    'degradation': (r['profit_factor'] - oos_stats['profit_factor']) / r['profit_factor'] * 100
                })
        else:
            print(f"    OOS: No trades")

    # Monte Carlo on validated strategies
    if validated:
        print(f"\n{'='*80}")
        print("MONTE CARLO ANALYSIS OF VALIDATED STRATEGIES")
        print(f"{'='*80}")

        for i, v in enumerate(validated):
            r = v['is']
            tf = r['params'].get('signal_tf', 5)
            df_tf = aggregate_tf(df, tf)

            signal_funcs = {
                'EMA_TREND': lambda d, p: gen_ema_crossover(d, p['fast'], p['slow'], p['trend_period'],
                                                             p['session_start'], p['session_end']),
                'BB_REVERSAL': lambda d, p: gen_bb_reversal(d, p['bb_period'], p['bb_std'], p['rsi_period'],
                                                             p['rsi_ob'], p['rsi_os'],
                                                             p['session_start'], p['session_end']),
                'MACD': lambda d, p: gen_macd(d, p['fast'], p['slow'], p['signal_p'], p['trend_period'],
                                               p['session_start'], p['session_end']),
                'BREAKOUT': lambda d, p: gen_breakout(d, p['lookback'], p['vol_mult'], p['vol_period'],
                                                      p['session_start'], p['session_end']),
                'RSI_MOM': lambda d, p: gen_rsi_momentum(d, p['rsi_period'], p['upper'], p['lower'],
                                                          p['session_start'], p['session_end']),
                'EMA_VOL': lambda d, p: gen_ema_vol_combined(d, p['fast'], p['slow'], p['trend_period'],
                                                              p['vol_mult'], p['vol_period'],
                                                              p['session_start'], p['session_end']),
            }

            signals = signal_funcs[r['strategy_type']](df_tf, r['params'])
            trades = backtest_signals(df_tf, signals, r['params']['sl'], r['params']['tp'],
                                      r['params']['max_hold'], 5.0)

            mc = monte_carlo(trades)
            if mc:
                print(f"\n  #{i+1} [{r['strategy_type']}] {r['label']}")
                print(f"    OOS PF: {v['oos_pf']:.2f} | Degradation: {v['degradation']:.1f}%")
                print(f"    Monte Carlo (2000 sims):")
                print(f"      Final Balance: Mean=${mc['final_mean']:.0f} | 5th=${mc['final_5th']:.0f} | 95th=${mc['final_95th']:.0f}")
                print(f"      Max Drawdown:  Mean=${mc['dd_mean']:.0f} | 95th=${mc['dd_95th']:.0f} | 99th=${mc['dd_99th']:.0f}")
                print(f"      Risk of 50%% DD: {mc['ruin_prob']:.1f}%")

    # === FINAL RECOMMENDATIONS ===
    print(f"\n{'='*80}")
    print("FINAL OPTIMIZED PARAMETERS FOR MQL5 EA")
    print(f"{'='*80}")

    if validated:
        # Pick best validated strategy
        validated.sort(key=lambda x: x['oos_pf'] * x['oos_sharpe'], reverse=True)
        best = validated[0]
        r = best['is']
        print(f"\n  >>> BEST VALIDATED STRATEGY: {r['strategy_type']} <<<")
        print(f"  {r['label']}")
        print(f"  Parameters: {r['params']}")
        print(f"\n  In-Sample Performance:")
        print(f"    Trades: {r['trades']} | WR: {r['win_rate']:.1f}% | PF: {r['profit_factor']:.2f}")
        print(f"    Total PnL: {r['total_pnl']:.1f} | MaxDD: {r['max_dd']:.1f}")
        print(f"    Sharpe: {r['sharpe']:.2f} | Expectancy: {r['expectancy']:.2f}")
        print(f"\n  Out-of-Sample Performance:")
        oos = best['oos']
        print(f"    Trades: {oos['trades']} | WR: {oos['win_rate']:.1f}% | PF: {oos['profit_factor']:.2f}")
        print(f"    Total PnL: {oos['total_pnl']:.1f} | MaxDD: {oos['max_dd']:.1f}")
        print(f"    Sharpe: {oos['sharpe']:.2f} | Expectancy: {oos['expectancy']:.2f}")
        print(f"    Degradation from IS: {best['degradation']:.1f}%")

        # Show top 3 validated
        if len(validated) > 1:
            print(f"\n  Other validated strategies:")
            for j, v in enumerate(validated[1:4]):
                r2 = v['is']
                print(f"    #{j+2}: [{r2['strategy_type']}] {r2['label']}")
                print(f"       IS PF: {r2['profit_factor']:.2f} | OOS PF: {v['oos_pf']:.2f} | Degrad: {v['degradation']:.1f}%")
    else:
        # Fallback: show best IS results
        if all_results:
            best = all_results[0]
            print(f"\n  No strategies validated OOS. Best IS strategy:")
            print(f"  {best['label']}")
            print(f"  Parameters: {best['params']}")
            print(fmt(best))
        else:
            print("\n  WARNING: No profitable strategies found with current cost model.")
            print("  Consider: lower spread broker, higher timeframe, or different instrument.")

    print(f"\n{'='*80}")
    print("OPTIMIZATION COMPLETE")
    print(f"{'='*80}")
