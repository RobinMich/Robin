#!/usr/bin/env python3
"""
Multi-Instrument Backtest
Tests trading strategies across US100, NVDA, NFLX, PLTR, DELL, AVGO, LLY, MSFT, AAPL, JPM, TPL
using daily, 1h, 15m, and 5m data from Yahoo Finance.

Strategies tested:
1. EMA Crossover with Trend Filter
2. Bollinger Band Reversal + RSI
3. MACD Histogram Crossover + Trend
4. Breakout (N-bar high/low) + Volume
5. RSI Momentum Continuation
6. EMA + Volume Confirmation
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = '/home/user/Robin/market_data'

INSTRUMENTS = {
    'US100': {'type': 'index', 'cost_pct': 0.0003},    # ~3 pts on 20000 = 0.015%
    'NVDA':  {'type': 'stock', 'cost_pct': 0.001},      # ~$0.18 on $180
    'NFLX':  {'type': 'stock', 'cost_pct': 0.001},
    'PLTR':  {'type': 'stock', 'cost_pct': 0.002},      # higher spread on PLTR
    'DELL':  {'type': 'stock', 'cost_pct': 0.001},
    'AVGO':  {'type': 'stock', 'cost_pct': 0.001},
    'LLY':   {'type': 'stock', 'cost_pct': 0.0008},     # very liquid
    'MSFT':  {'type': 'stock', 'cost_pct': 0.0005},     # very liquid
    'AAPL':  {'type': 'stock', 'cost_pct': 0.0005},     # very liquid
    'JPM':   {'type': 'stock', 'cost_pct': 0.0006},
    'TPL':   {'type': 'stock', 'cost_pct': 0.003},      # less liquid
}

# =============================================================================
# DATA LOADING
# =============================================================================
def load_yahoo_data(symbol, timeframe):
    """Load Yahoo Finance CSV data."""
    filepath = os.path.join(DATA_DIR, f'{symbol}_{timeframe}.csv')
    if not os.path.exists(filepath):
        return None

    df = pd.read_csv(filepath, parse_dates=['Date' if timeframe == 'daily' else 'Datetime'])
    date_col = 'Date' if timeframe == 'daily' else 'Datetime'

    df = df.rename(columns={date_col: 'DateTime'})
    df = df.sort_values('DateTime').reset_index(drop=True)

    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['Open', 'High', 'Low', 'Close']).reset_index(drop=True)

    if 'DateTime' in df.columns:
        df['Hour'] = pd.to_datetime(df['DateTime']).dt.hour
    return df

# =============================================================================
# INDICATORS
# =============================================================================
def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi_calc(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=p-1, min_periods=p).mean()
    l = (-d.clip(upper=0)).ewm(com=p-1, min_periods=p).mean()
    return 100 - 100 / (1 + g/l)

def atr_calc(df, p=14):
    tr = pd.concat([df['High']-df['Low'],
                    (df['High']-df['Close'].shift(1)).abs(),
                    (df['Low']-df['Close'].shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

# =============================================================================
# BACKTEST ENGINE (percentage-based for cross-instrument comparison)
# =============================================================================
def backtest_pct(df, signals, sl_pct, tp_pct, max_hold, cost_pct=0.001):
    """
    Backtest using percentage-based SL/TP for cross-instrument compatibility.
    sl_pct, tp_pct: e.g. 0.01 = 1%
    cost_pct: round-trip cost as fraction of price
    """
    sig = signals.values
    closes = df['Close'].values
    highs = df['High'].values
    lows = df['Low'].values
    n = len(df)

    trades = []
    i = 0
    while i < n:
        if sig[i] == 0:
            i += 1
            continue

        direction = sig[i]
        entry = closes[i]
        sl_abs = entry * sl_pct
        tp_abs = entry * tp_pct
        cost_abs = entry * cost_pct

        for j in range(i + 1, min(i + max_hold + 1, n)):
            bars = j - i

            if direction == 1:  # LONG
                if lows[j] <= entry - sl_abs:
                    trades.append({'pnl_pct': -sl_pct - cost_pct, 'pnl_abs': -sl_abs - cost_abs,
                                  'direction': 'LONG', 'exit': 'SL', 'bars': bars})
                    i = j + 1; break
                elif highs[j] >= entry + tp_abs:
                    trades.append({'pnl_pct': tp_pct - cost_pct, 'pnl_abs': tp_abs - cost_abs,
                                  'direction': 'LONG', 'exit': 'TP', 'bars': bars})
                    i = j + 1; break
                elif bars >= max_hold:
                    pnl = (closes[j] - entry) / entry
                    trades.append({'pnl_pct': pnl - cost_pct, 'pnl_abs': closes[j] - entry - cost_abs,
                                  'direction': 'LONG', 'exit': 'TIME', 'bars': bars})
                    i = j + 1; break
            else:  # SHORT
                if highs[j] >= entry + sl_abs:
                    trades.append({'pnl_pct': -sl_pct - cost_pct, 'pnl_abs': -sl_abs - cost_abs,
                                  'direction': 'SHORT', 'exit': 'SL', 'bars': bars})
                    i = j + 1; break
                elif lows[j] <= entry - tp_abs:
                    trades.append({'pnl_pct': tp_pct - cost_pct, 'pnl_abs': tp_abs - cost_abs,
                                  'direction': 'SHORT', 'exit': 'TP', 'bars': bars})
                    i = j + 1; break
                elif bars >= max_hold:
                    pnl = (entry - closes[j]) / entry
                    trades.append({'pnl_pct': pnl - cost_pct, 'pnl_abs': entry - closes[j] - cost_abs,
                                  'direction': 'SHORT', 'exit': 'TIME', 'bars': bars})
                    i = j + 1; break
        else:
            i += 1
            continue

    return trades

# =============================================================================
# SIGNAL GENERATORS
# =============================================================================
def sig_ema_trend(df, fast=9, slow=21, trend=100):
    """EMA crossover with trend filter."""
    ef = ema(df['Close'], fast)
    es = ema(df['Close'], slow)
    et = ema(df['Close'], trend)

    cross_up = (ef.shift(1) <= es.shift(1)) & (ef > es)
    cross_down = (ef.shift(1) >= es.shift(1)) & (ef < es)
    above = df['Close'] > et
    below = df['Close'] < et

    signals = pd.Series(0, index=df.index)
    signals[cross_up & above] = 1
    signals[cross_down & below] = -1
    return signals

def sig_bb_rsi(df, bb_period=20, bb_std=2.0, rsi_period=14, rsi_ob=70, rsi_os=30):
    """Bollinger Band reversal with RSI confirmation."""
    basis = df['Close'].rolling(bb_period).mean()
    std = df['Close'].rolling(bb_period).std()
    upper = basis + bb_std * std
    lower = basis - bb_std * std
    r = rsi_calc(df['Close'], rsi_period)

    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] <= lower) & (r < rsi_os)] = 1
    signals[(df['Close'] >= upper) & (r > rsi_ob)] = -1
    return signals

def sig_macd_trend(df, fast=12, slow=26, signal_p=9, trend_p=50):
    """MACD histogram crossover with trend filter."""
    ef = ema(df['Close'], fast)
    es = ema(df['Close'], slow)
    macd_line = ef - es
    sig_line = ema(macd_line, signal_p)
    hist = macd_line - sig_line
    et = ema(df['Close'], trend_p)

    cross_up = (hist.shift(1) <= 0) & (hist > 0)
    cross_down = (hist.shift(1) >= 0) & (hist < 0)
    above = df['Close'] > et
    below = df['Close'] < et

    signals = pd.Series(0, index=df.index)
    signals[cross_up & above] = 1
    signals[cross_down & below] = -1
    return signals

def sig_breakout(df, lookback=20, vol_mult=1.5, vol_period=20):
    """N-bar high/low breakout with volume confirmation."""
    high_n = df['High'].rolling(lookback).max().shift(1)
    low_n = df['Low'].rolling(lookback).min().shift(1)

    vol_ok = pd.Series(True, index=df.index)
    if 'Volume' in df.columns:
        vol_ma = df['Volume'].rolling(vol_period).mean()
        vol_ok = (vol_ma > 0) & (df['Volume'] >= vol_ma * vol_mult)

    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] > high_n) & vol_ok] = 1
    signals[(df['Close'] < low_n) & vol_ok] = -1
    return signals

def sig_rsi_momentum(df, rsi_period=14, upper=80, lower=20):
    """RSI momentum continuation."""
    r = rsi_calc(df['Close'], rsi_period)
    signals = pd.Series(0, index=df.index)
    signals[r > upper] = 1
    signals[r < lower] = -1
    return signals

def sig_ema_vol(df, fast=12, slow=26, trend=50, vol_mult=1.5, vol_period=20):
    """EMA crossover confirmed by volume."""
    ef = ema(df['Close'], fast)
    es = ema(df['Close'], slow)
    et = ema(df['Close'], trend)

    cross_up = (ef.shift(1) <= es.shift(1)) & (ef > es)
    cross_down = (ef.shift(1) >= es.shift(1)) & (ef < es)
    above = df['Close'] > et
    below = df['Close'] < et

    vol_ok = pd.Series(True, index=df.index)
    if 'Volume' in df.columns:
        vol_ma = df['Volume'].rolling(vol_period).mean()
        vol_ok = (vol_ma > 0) & (df['Volume'] >= vol_ma * vol_mult)

    signals = pd.Series(0, index=df.index)
    signals[cross_up & above & vol_ok] = 1
    signals[cross_down & below & vol_ok] = -1
    return signals

# =============================================================================
# STATISTICS
# =============================================================================
def calc_stats(trades, label=""):
    if not trades or len(trades) < 3:
        return None

    pnls = np.array([t['pnl_pct'] for t in trades])
    n = len(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    total = pnls.sum() * 100  # convert to percentage
    wr = len(wins) / n * 100
    gp = wins.sum() if len(wins) > 0 else 0
    gl = abs(losses.sum()) if len(losses) > 0 else 0.0001
    pf = gp / gl
    expect = pnls.mean() * 100

    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    max_dd = dd.max() * 100

    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0

    mcl = 0; curr = 0
    for p in pnls:
        if p <= 0: curr += 1; mcl = max(mcl, curr)
        else: curr = 0

    return {
        'label': label, 'trades': n, 'total_pct': total,
        'win_rate': wr, 'profit_factor': pf, 'max_dd_pct': max_dd,
        'sharpe': sharpe, 'expectancy_pct': expect, 'max_consec_loss': mcl
    }

def fmt_stats(s):
    if s is None: return "  -- No trades --"
    return (f"T:{s['trades']:>4d} | WR:{s['win_rate']:>5.1f}% | PF:{s['profit_factor']:>5.2f} | "
            f"Return:{s['total_pct']:>7.2f}% | MaxDD:{s['max_dd_pct']:>6.2f}% | "
            f"Sharpe:{s['sharpe']:>6.2f} | Exp:{s['expectancy_pct']:>6.3f}% | MCL:{s['max_consec_loss']}")

# =============================================================================
# STRATEGY CONFIGS TO TEST
# =============================================================================
STRATEGIES = {
    'EMA(9/21) Trend100': {
        'func': sig_ema_trend,
        'params': {'fast': 9, 'slow': 21, 'trend': 100},
        'sl_pct': 0.015, 'tp_pct': 0.03, 'max_hold': 60,
    },
    'EMA(12/30) Trend50': {
        'func': sig_ema_trend,
        'params': {'fast': 12, 'slow': 30, 'trend': 50},
        'sl_pct': 0.01, 'tp_pct': 0.02, 'max_hold': 40,
    },
    'BB(20,2.0) RSI70/30': {
        'func': sig_bb_rsi,
        'params': {'bb_period': 20, 'bb_std': 2.0, 'rsi_period': 14, 'rsi_ob': 70, 'rsi_os': 30},
        'sl_pct': 0.01, 'tp_pct': 0.015, 'max_hold': 30,
    },
    'BB(20,2.5) RSI80/20': {
        'func': sig_bb_rsi,
        'params': {'bb_period': 20, 'bb_std': 2.5, 'rsi_period': 14, 'rsi_ob': 80, 'rsi_os': 20},
        'sl_pct': 0.015, 'tp_pct': 0.025, 'max_hold': 60,
    },
    'MACD(12/26/9) Trend50': {
        'func': sig_macd_trend,
        'params': {'fast': 12, 'slow': 26, 'signal_p': 9, 'trend_p': 50},
        'sl_pct': 0.015, 'tp_pct': 0.03, 'max_hold': 60,
    },
    'MACD(8/21/7) Trend30': {
        'func': sig_macd_trend,
        'params': {'fast': 8, 'slow': 21, 'signal_p': 7, 'trend_p': 30},
        'sl_pct': 0.01, 'tp_pct': 0.02, 'max_hold': 40,
    },
    'Breakout(20) Vol1.5x': {
        'func': sig_breakout,
        'params': {'lookback': 20, 'vol_mult': 1.5, 'vol_period': 20},
        'sl_pct': 0.015, 'tp_pct': 0.03, 'max_hold': 40,
    },
    'Breakout(10) Vol1.0x': {
        'func': sig_breakout,
        'params': {'lookback': 10, 'vol_mult': 1.0, 'vol_period': 20},
        'sl_pct': 0.01, 'tp_pct': 0.02, 'max_hold': 30,
    },
    'RSI(14) Mom 80/20': {
        'func': sig_rsi_momentum,
        'params': {'rsi_period': 14, 'upper': 80, 'lower': 20},
        'sl_pct': 0.015, 'tp_pct': 0.03, 'max_hold': 30,
    },
    'RSI(14) Mom 85/15': {
        'func': sig_rsi_momentum,
        'params': {'rsi_period': 14, 'upper': 85, 'lower': 15},
        'sl_pct': 0.02, 'tp_pct': 0.04, 'max_hold': 60,
    },
    'EMA(12/26)+Vol1.5x': {
        'func': sig_ema_vol,
        'params': {'fast': 12, 'slow': 26, 'trend': 50, 'vol_mult': 1.5, 'vol_period': 20},
        'sl_pct': 0.015, 'tp_pct': 0.03, 'max_hold': 60,
    },
}

# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    print("="*120)
    print("MULTI-INSTRUMENT STRATEGY BACKTEST")
    print("="*120)

    timeframes = ['daily', '1h', '15m', '5m']

    # Store all results for grand summary
    grand_results = {}  # {strategy_name: {symbol_tf: stats}}

    for symbol, meta in INSTRUMENTS.items():
        print(f"\n{'#'*120}")
        print(f"# {symbol} (Cost: {meta['cost_pct']*100:.2f}%)")
        print(f"{'#'*120}")

        for tf in timeframes:
            df = load_yahoo_data(symbol, tf)
            if df is None or len(df) < 100:
                continue

            print(f"\n  --- {symbol} {tf.upper()} ({len(df)} bars) ---")

            for strat_name, config in STRATEGIES.items():
                signals = config['func'](df, **config['params'])
                trades = backtest_pct(df, signals, config['sl_pct'], config['tp_pct'],
                                       config['max_hold'], meta['cost_pct'])
                stats = calc_stats(trades, strat_name)

                key = f"{symbol}_{tf}"
                if strat_name not in grand_results:
                    grand_results[strat_name] = {}
                grand_results[strat_name][key] = stats

                if stats and stats['trades'] >= 3:
                    marker = " ***" if stats['profit_factor'] > 1.2 else (" ++" if stats['profit_factor'] > 1.0 else "")
                    print(f"    {strat_name:>25}: {fmt_stats(stats)}{marker}")

    # =========================================================================
    # GRAND SUMMARY: STRATEGY PERFORMANCE ACROSS ALL INSTRUMENTS
    # =========================================================================
    print(f"\n{'='*120}")
    print("GRAND SUMMARY: STRATEGY PERFORMANCE ACROSS ALL INSTRUMENTS & TIMEFRAMES")
    print(f"{'='*120}")

    strategy_scores = {}

    for strat_name, results_dict in grand_results.items():
        profitable = 0
        total_tested = 0
        total_return = 0
        total_sharpe = 0
        total_pf = 0
        all_trades = 0

        for key, stats in results_dict.items():
            if stats and stats['trades'] >= 3:
                total_tested += 1
                if stats['profit_factor'] > 1.0:
                    profitable += 1
                total_return += stats['total_pct']
                total_sharpe += stats['sharpe']
                total_pf += stats['profit_factor']
                all_trades += stats['trades']

        if total_tested > 0:
            avg_return = total_return / total_tested
            avg_sharpe = total_sharpe / total_tested
            avg_pf = total_pf / total_tested
            win_pct = profitable / total_tested * 100

            strategy_scores[strat_name] = {
                'tested': total_tested, 'profitable': profitable,
                'win_pct': win_pct, 'avg_return': avg_return,
                'avg_sharpe': avg_sharpe, 'avg_pf': avg_pf,
                'total_trades': all_trades,
                'score': avg_sharpe * avg_pf * (win_pct/100)
            }

    # Sort by composite score
    sorted_strategies = sorted(strategy_scores.items(), key=lambda x: x[1]['score'], reverse=True)

    print(f"\n  {'Strategy':>30} | {'Tested':>6} | {'Profitable':>10} | {'Win%':>5} | "
          f"{'AvgReturn':>10} | {'AvgPF':>6} | {'AvgSharpe':>9} | {'Score':>6}")
    print(f"  {'-'*100}")

    for strat_name, scores in sorted_strategies:
        s = scores
        print(f"  {strat_name:>30} | {s['tested']:>6d} | {s['profitable']:>10d} | {s['win_pct']:>5.1f} | "
              f"{s['avg_return']:>9.2f}% | {s['avg_pf']:>6.2f} | {s['avg_sharpe']:>9.2f} | {s['score']:>6.2f}")

    # =========================================================================
    # BEST STRATEGY PER INSTRUMENT
    # =========================================================================
    print(f"\n{'='*120}")
    print("BEST STRATEGY PER INSTRUMENT & TIMEFRAME")
    print(f"{'='*120}")

    for symbol in INSTRUMENTS.keys():
        print(f"\n  {symbol}:")
        for tf in timeframes:
            key = f"{symbol}_{tf}"
            best_name = None
            best_score = -999

            for strat_name, results_dict in grand_results.items():
                if key in results_dict and results_dict[key] is not None:
                    s = results_dict[key]
                    if s['trades'] >= 3:
                        score = s['sharpe'] * s['profit_factor']
                        if score > best_score:
                            best_score = score
                            best_name = strat_name

            if best_name and key in grand_results[best_name] and grand_results[best_name][key]:
                stats = grand_results[best_name][key]
                print(f"    {tf:>6}: {best_name:>30} | {fmt_stats(stats)}")

    # =========================================================================
    # PER-INSTRUMENT HEATMAP: Which strategies work where?
    # =========================================================================
    print(f"\n{'='*120}")
    print("PROFIT FACTOR HEATMAP (Daily TF) - Strategies x Instruments")
    print(f"{'='*120}")

    print(f"\n  {'Strategy':>30}", end="")
    for symbol in INSTRUMENTS.keys():
        print(f" | {symbol:>6}", end="")
    print()
    print(f"  {'-'*30}", end="")
    for _ in INSTRUMENTS:
        print(f"-|-------", end="")
    print()

    for strat_name in [s[0] for s in sorted_strategies]:
        print(f"  {strat_name:>30}", end="")
        for symbol in INSTRUMENTS.keys():
            key = f"{symbol}_daily"
            if key in grand_results.get(strat_name, {}) and grand_results[strat_name][key]:
                pf = grand_results[strat_name][key]['profit_factor']
                if pf > 1.2:
                    print(f" | {pf:>5.2f}*", end="")
                elif pf > 1.0:
                    print(f" | {pf:>5.2f}+", end="")
                else:
                    print(f" | {pf:>5.2f} ", end="")
            else:
                print(f" |    -- ", end="")
        print()

    # Same for 5m
    print(f"\n  PROFIT FACTOR HEATMAP (5m TF)")
    print(f"\n  {'Strategy':>30}", end="")
    for symbol in INSTRUMENTS.keys():
        print(f" | {symbol:>6}", end="")
    print()
    print(f"  {'-'*30}", end="")
    for _ in INSTRUMENTS:
        print(f"-|-------", end="")
    print()

    for strat_name in [s[0] for s in sorted_strategies]:
        print(f"  {strat_name:>30}", end="")
        for symbol in INSTRUMENTS.keys():
            key = f"{symbol}_5m"
            if key in grand_results.get(strat_name, {}) and grand_results[strat_name][key]:
                pf = grand_results[strat_name][key]['profit_factor']
                if pf > 1.2:
                    print(f" | {pf:>5.2f}*", end="")
                elif pf > 1.0:
                    print(f" | {pf:>5.2f}+", end="")
                else:
                    print(f" | {pf:>5.2f} ", end="")
            else:
                print(f" |    -- ", end="")
        print()

    # =========================================================================
    # LONG-ONLY vs LONG+SHORT analysis
    # =========================================================================
    print(f"\n{'='*120}")
    print("LONG vs SHORT PERFORMANCE (DAILY)")
    print(f"{'='*120}")

    for symbol in INSTRUMENTS.keys():
        df = load_yahoo_data(symbol, 'daily')
        if df is None or len(df) < 100:
            continue

        # Test best strategy on daily, split by direction
        best_strat = sorted_strategies[0][0] if sorted_strategies else 'EMA(9/21) Trend100'
        config = STRATEGIES[best_strat]
        signals = config['func'](df, **config['params'])
        cost = INSTRUMENTS[symbol]['cost_pct']
        trades = backtest_pct(df, signals, config['sl_pct'], config['tp_pct'], config['max_hold'], cost)

        long_trades = [t for t in trades if t['direction'] == 'LONG']
        short_trades = [t for t in trades if t['direction'] == 'SHORT']

        long_stats = calc_stats(long_trades, "LONG") if long_trades else None
        short_stats = calc_stats(short_trades, "SHORT") if short_trades else None

        print(f"\n  {symbol} ({best_strat}):")
        if long_stats:
            print(f"    LONG:  {fmt_stats(long_stats)}")
        if short_stats:
            print(f"    SHORT: {fmt_stats(short_stats)}")

    print(f"\n{'='*120}")
    print("MULTI-INSTRUMENT BACKTEST COMPLETE")
    print(f"{'='*120}")
