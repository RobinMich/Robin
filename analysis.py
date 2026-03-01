#!/usr/bin/env python3
"""
Comprehensive NAS100 1-Minute Trading Strategy Analysis
========================================================
Parses ~262k rows of 1-minute OHLCV data and tests multiple
indicator combinations for profitability.
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────
# 1. DATA LOADING & PARSING
# ─────────────────────────────────────────────────────────────
def load_data(filepath):
    """Load tab-separated, quoted OHLCV data (reverse chronological)."""
    print("=" * 80)
    print("LOADING DATA")
    print("=" * 80)

    # Each line is entirely wrapped in double quotes with tabs inside.
    # Strip the outer quotes first, then parse as TSV.
    import io
    with open(filepath, 'r') as f:
        cleaned = f.read().replace('"', '')
    df = pd.read_csv(
        io.StringIO(cleaned),
        sep='\t',
        parse_dates=['DateTime'],
        date_format='%Y.%m.%d %H:%M:%S'
    )

    # Sort chronologically (data is newest-first)
    df = df.sort_values('DateTime').reset_index(drop=True)

    # Basic type enforcement
    for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'TickVolume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"  Rows loaded       : {len(df):,}")
    print(f"  Date range        : {df['DateTime'].iloc[0]} → {df['DateTime'].iloc[-1]}")
    print(f"  Price range       : {df['Low'].min():.1f} – {df['High'].max():.1f}")
    print(f"  Columns           : {list(df.columns)}")
    print()
    return df


# ─────────────────────────────────────────────────────────────
# 2. KEY STATISTICS
# ─────────────────────────────────────────────────────────────
def compute_statistics(df):
    print("=" * 80)
    print("KEY STATISTICS")
    print("=" * 80)

    df['Range'] = df['High'] - df['Low']
    df['Body'] = abs(df['Close'] - df['Open'])
    df['Return'] = df['Close'].pct_change()

    # Per-bar stats
    print(f"  Avg 1-min range        : {df['Range'].mean():.2f} pts")
    print(f"  Median 1-min range     : {df['Range'].median():.2f} pts")
    print(f"  Avg 1-min body         : {df['Body'].mean():.2f} pts")
    print(f"  Avg TickVolume/bar     : {df['TickVolume'].mean():.1f}")
    print(f"  Median TickVolume/bar  : {df['TickVolume'].median():.1f}")

    # Daily stats
    df['Date'] = df['DateTime'].dt.date
    daily = df.groupby('Date').agg(
        DayHigh=('High', 'max'),
        DayLow=('Low', 'min'),
        DayOpen=('Open', 'first'),
        DayClose=('Close', 'last'),
        TotalTickVol=('TickVolume', 'sum'),
        Bars=('Close', 'count')
    )
    daily['DayRange'] = daily['DayHigh'] - daily['DayLow']
    daily['DayReturn'] = (daily['DayClose'] - daily['DayOpen'])

    print(f"\n  Trading days           : {len(daily)}")
    print(f"  Avg daily range        : {daily['DayRange'].mean():.1f} pts")
    print(f"  Avg daily return       : {daily['DayReturn'].mean():.2f} pts")
    print(f"  Daily return std       : {daily['DayReturn'].std():.2f} pts")
    print(f"  Avg bars/day           : {daily['Bars'].mean():.0f}")

    # Annualised volatility (from 1-min returns)
    ann_vol = df['Return'].std() * np.sqrt(252 * 390)  # ~390 trading mins/day
    print(f"  Annualised volatility  : {ann_vol*100:.1f}%")

    # Trend characteristic: autocorrelation of returns
    ac1 = df['Return'].autocorr(lag=1)
    ac5 = df['Return'].autocorr(lag=5)
    ac15 = df['Return'].autocorr(lag=15)
    print(f"\n  Return autocorr lag-1  : {ac1:.4f}")
    print(f"  Return autocorr lag-5  : {ac5:.4f}")
    print(f"  Return autocorr lag-15 : {ac15:.4f}")

    # Up/down bar ratio
    up = (df['Close'] > df['Open']).sum()
    down = (df['Close'] < df['Open']).sum()
    flat = (df['Close'] == df['Open']).sum()
    print(f"\n  Up bars   : {up:,} ({up/len(df)*100:.1f}%)")
    print(f"  Down bars : {down:,} ({down/len(df)*100:.1f}%)")
    print(f"  Flat bars : {flat:,} ({flat/len(df)*100:.1f}%)")
    print()
    return df


# ─────────────────────────────────────────────────────────────
# 3. INDICATOR HELPERS
# ─────────────────────────────────────────────────────────────
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def sma(series, period):
    return series.rolling(window=period).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def bollinger_bands(series, period=20, std_dev=2):
    mid = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


# ─────────────────────────────────────────────────────────────
# 4. BACKTESTING ENGINE
# ─────────────────────────────────────────────────────────────
def backtest(df, signals, hold_bars, sl_pts=None, tp_pts=None, label="Strategy"):
    """
    Vectorised backtest.
    signals: Series with 1 = long entry, -1 = short entry, 0 = no signal.
    hold_bars: how many bars to hold if no SL/TP hit.
    sl_pts / tp_pts: stop-loss / take-profit in index points.
    Returns dict of performance metrics.
    """
    closes = df['Close'].values
    highs = df['High'].values
    lows = df['Low'].values
    sig = signals.values
    n = len(df)

    trades = []  # (entry_price, exit_price, direction, pnl)
    in_trade = False
    entry_idx = 0
    entry_price = 0.0
    direction = 0
    bars_held = 0

    for i in range(n):
        if in_trade:
            bars_held += 1
            pnl = 0.0
            exited = False

            if direction == 1:  # long
                # Check SL
                if sl_pts is not None and lows[i] <= entry_price - sl_pts:
                    pnl = -sl_pts
                    exited = True
                # Check TP
                elif tp_pts is not None and highs[i] >= entry_price + tp_pts:
                    pnl = tp_pts
                    exited = True
                # Time exit
                elif bars_held >= hold_bars:
                    pnl = closes[i] - entry_price
                    exited = True
            else:  # short
                if sl_pts is not None and highs[i] >= entry_price + sl_pts:
                    pnl = -sl_pts
                    exited = True
                elif tp_pts is not None and lows[i] <= entry_price - tp_pts:
                    pnl = tp_pts
                    exited = True
                elif bars_held >= hold_bars:
                    pnl = entry_price - closes[i]
                    exited = True

            if exited:
                trades.append(pnl)
                in_trade = False
        else:
            if sig[i] == 1 or sig[i] == -1:
                in_trade = True
                entry_price = closes[i]
                direction = sig[i]
                bars_held = 0

    return evaluate_trades(trades, label)


def evaluate_trades(trades, label):
    """Compute performance metrics from a list of PnL values."""
    if len(trades) < 5:
        return {
            'label': label, 'trades': len(trades),
            'win_rate': 0, 'profit_factor': 0,
            'total_return': 0, 'max_dd': 0,
            'avg_win': 0, 'avg_loss': 0,
            'sharpe': 0, 'expectancy': 0,
        }

    trades = np.array(trades)
    wins = trades[trades > 0]
    losses = trades[trades < 0]

    total = trades.sum()
    win_rate = len(wins) / len(trades) * 100
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1e-9
    pf = gross_profit / gross_loss

    # Max drawdown from cumulative PnL
    cum = np.cumsum(trades)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = dd.max()

    # Sharpe (per-trade)
    sharpe = trades.mean() / trades.std() if trades.std() > 0 else 0
    # Annualise roughly: assume ~5 trades/day, 252 days
    sharpe_ann = sharpe * np.sqrt(min(len(trades), 252 * 5))

    expectancy = trades.mean()

    return {
        'label': label,
        'trades': len(trades),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(pf, 3),
        'total_return': round(total, 1),
        'max_dd': round(max_dd, 1),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'sharpe': round(sharpe_ann, 3),
        'expectancy': round(expectancy, 2),
    }


def print_results(results_list):
    """Pretty-print a list of result dicts as a table."""
    if not results_list:
        return
    # Sort by total_return descending
    results_list = sorted(results_list, key=lambda x: x['total_return'], reverse=True)

    header = (f"  {'Strategy':<45} {'Trades':>7} {'WinR%':>7} {'PF':>7} "
              f"{'TotalPts':>10} {'MaxDD':>9} {'AvgWin':>8} {'AvgLoss':>8} "
              f"{'Sharpe':>8} {'Expect':>8}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in results_list:
        print(f"  {r['label']:<45} {r['trades']:>7} {r['win_rate']:>7.1f} {r['profit_factor']:>7.2f} "
              f"{r['total_return']:>10.1f} {r['max_dd']:>9.1f} {r['avg_win']:>8.2f} {r['avg_loss']:>8.2f} "
              f"{r['sharpe']:>8.2f} {r['expectancy']:>8.2f}")
    print()


# ─────────────────────────────────────────────────────────────
# 5. STRATEGY TESTS
# ─────────────────────────────────────────────────────────────

def test_ema_crossovers(df):
    """Test multiple EMA crossover period combos."""
    print("=" * 80)
    print("STRATEGY GROUP 1: EMA CROSSOVERS")
    print("=" * 80)
    results = []

    combos = [(5, 20), (8, 21), (9, 21), (10, 50), (20, 50), (12, 26), (5, 13), (10, 30)]

    for fast_p, slow_p in combos:
        ema_fast = ema(df['Close'], fast_p)
        ema_slow = ema(df['Close'], slow_p)

        cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
        cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

        signals = pd.Series(0, index=df.index)
        signals[cross_up] = 1
        signals[cross_down] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (20, 40), (15, 30), (10, 20), (25, 50), (30, 60)]:
                lbl = f"EMA({fast_p}/{slow_p}) hold={hold}"
                if sl is not None:
                    lbl += f" SL={sl} TP={tp}"
                r = backtest(df, signals, hold_bars=hold, sl_pts=sl, tp_pts=tp, label=lbl)
                results.append(r)

    print_results(results)
    return results


def test_rsi_strategies(df):
    """Test RSI overbought/oversold with various thresholds."""
    print("=" * 80)
    print("STRATEGY GROUP 2: RSI MEAN REVERSION")
    print("=" * 80)
    results = []

    rsi_14 = rsi(df['Close'], 14)
    rsi_7 = rsi(df['Close'], 7)
    rsi_21 = rsi(df['Close'], 21)

    configs = [
        (rsi_14, 14, 30, 70),
        (rsi_14, 14, 25, 75),
        (rsi_14, 14, 20, 80),
        (rsi_7,   7, 30, 70),
        (rsi_7,   7, 20, 80),
        (rsi_7,   7, 25, 75),
        (rsi_21, 21, 30, 70),
        (rsi_21, 21, 25, 75),
    ]

    for rsi_series, period, oversold, overbought in configs:
        # Mean-reversion: buy oversold, sell overbought
        signals_mr = pd.Series(0, index=df.index)
        signals_mr[rsi_series < oversold] = 1
        signals_mr[rsi_series > overbought] = -1

        # Momentum: buy overbought (trend continuation), sell oversold
        signals_mom = pd.Series(0, index=df.index)
        signals_mom[rsi_series > overbought] = 1
        signals_mom[rsi_series < oversold] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40), (25, 50)]:
                lbl_mr = f"RSI({period}) MR <{oversold}/>{ overbought} h={hold}"
                lbl_mom = f"RSI({period}) MOM >{overbought}/<{oversold} h={hold}"
                if sl is not None:
                    lbl_mr += f" SL={sl}/TP={tp}"
                    lbl_mom += f" SL={sl}/TP={tp}"
                results.append(backtest(df, signals_mr, hold, sl, tp, lbl_mr))
                results.append(backtest(df, signals_mom, hold, sl, tp, lbl_mom))

    print_results(results)
    return results


def test_bollinger_bands(df):
    """Bollinger Band bounce & breakout strategies."""
    print("=" * 80)
    print("STRATEGY GROUP 3: BOLLINGER BANDS")
    print("=" * 80)
    results = []

    for bb_period in [20, 30]:
        for bb_std in [1.5, 2.0, 2.5]:
            upper, mid, lower = bollinger_bands(df['Close'], bb_period, bb_std)

            # Bounce: buy near lower band, sell near upper band
            signals_bounce = pd.Series(0, index=df.index)
            signals_bounce[df['Close'] < lower] = 1
            signals_bounce[df['Close'] > upper] = -1

            # Breakout: buy above upper, sell below lower
            signals_breakout = pd.Series(0, index=df.index)
            signals_breakout[df['Close'] > upper] = 1
            signals_breakout[df['Close'] < lower] = -1

            for hold in [15, 30, 60]:
                for sl, tp in [(None, None), (15, 30), (20, 40), (25, 50)]:
                    lbl_b = f"BB({bb_period},{bb_std}) Bounce h={hold}"
                    lbl_k = f"BB({bb_period},{bb_std}) Breakout h={hold}"
                    if sl is not None:
                        lbl_b += f" SL={sl}/TP={tp}"
                        lbl_k += f" SL={sl}/TP={tp}"
                    results.append(backtest(df, signals_bounce, hold, sl, tp, lbl_b))
                    results.append(backtest(df, signals_breakout, hold, sl, tp, lbl_k))

    print_results(results)
    return results


def test_vwap_strategies(df):
    """VWAP-like analysis using TickVolume as proxy."""
    print("=" * 80)
    print("STRATEGY GROUP 4: VWAP (TickVolume-weighted)")
    print("=" * 80)
    results = []

    # Compute session VWAP (reset each day)
    df['TypicalPrice'] = (df['High'] + df['Low'] + df['Close']) / 3.0
    df['TPxVol'] = df['TypicalPrice'] * df['TickVolume']
    df['Date'] = df['DateTime'].dt.date
    df['CumTPxVol'] = df.groupby('Date')['TPxVol'].cumsum()
    df['CumVol'] = df.groupby('Date')['TickVolume'].cumsum()
    df['VWAP'] = df['CumTPxVol'] / df['CumVol'].replace(0, np.nan)

    # VWAP deviation
    df['VWAP_dev'] = df['Close'] - df['VWAP']

    for dev_thresh in [5, 10, 15, 20]:
        # Mean reversion to VWAP
        signals = pd.Series(0, index=df.index)
        signals[df['VWAP_dev'] < -dev_thresh] = 1   # below VWAP → buy
        signals[df['VWAP_dev'] > dev_thresh] = -1    # above VWAP → sell

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40), (10, 20)]:
                lbl = f"VWAP MR dev>{dev_thresh} h={hold}"
                if sl is not None:
                    lbl += f" SL={sl}/TP={tp}"
                results.append(backtest(df, signals, hold, sl, tp, lbl))

    # VWAP trend-following: above VWAP and rising → long
    vwap_slope = df['VWAP'].diff(5)
    for hold in [15, 30, 60]:
        signals_tf = pd.Series(0, index=df.index)
        signals_tf[(df['Close'] > df['VWAP']) & (vwap_slope > 0)] = 1
        signals_tf[(df['Close'] < df['VWAP']) & (vwap_slope < 0)] = -1

        # Reduce signal frequency: only fire when crossing VWAP
        cross_above = (df['Close'] > df['VWAP']) & (df['Close'].shift(1) <= df['VWAP'].shift(1))
        cross_below = (df['Close'] < df['VWAP']) & (df['Close'].shift(1) >= df['VWAP'].shift(1))
        signals_cross = pd.Series(0, index=df.index)
        signals_cross[cross_above] = 1
        signals_cross[cross_below] = -1

        for sl, tp in [(None, None), (15, 30), (20, 40)]:
            lbl = f"VWAP Cross h={hold}"
            if sl is not None:
                lbl += f" SL={sl}/TP={tp}"
            results.append(backtest(df, signals_cross, hold, sl, tp, lbl))

    print_results(results)
    return results


def test_session_analysis(df):
    """Session-based analysis: identify most profitable trading hours."""
    print("=" * 80)
    print("STRATEGY GROUP 5: SESSION / TIME-OF-DAY ANALYSIS")
    print("=" * 80)

    df['Hour'] = df['DateTime'].dt.hour
    df['Minute'] = df['DateTime'].dt.minute
    df['HourMinute'] = df['Hour'] * 100 + df['Minute']
    df['Weekday'] = df['DateTime'].dt.dayofweek  # 0=Mon

    # Per-hour statistics
    df['BarReturn'] = df['Close'] - df['Open']
    hourly = df.groupby('Hour').agg(
        AvgReturn=('BarReturn', 'mean'),
        StdReturn=('BarReturn', 'std'),
        AvgRange=('Range', 'mean'),
        AvgTickVol=('TickVolume', 'mean'),
        Count=('Close', 'count')
    )
    hourly['Sharpe'] = hourly['AvgReturn'] / hourly['StdReturn']

    print("\n  Hourly Performance (server time):")
    print(f"  {'Hour':>6} {'AvgRet':>9} {'StdRet':>9} {'Sharpe':>8} {'AvgRange':>9} {'AvgTickVol':>11} {'Bars':>8}")
    print("  " + "-" * 65)
    for h, row in hourly.iterrows():
        print(f"  {h:>6} {row['AvgReturn']:>9.3f} {row['StdReturn']:>9.3f} "
              f"{row['Sharpe']:>8.4f} {row['AvgRange']:>9.2f} {row['AvgTickVol']:>11.1f} {int(row['Count']):>8}")

    # Weekday analysis
    daily_by_wd = df.groupby('Weekday').agg(
        AvgReturn=('BarReturn', 'mean'),
        AvgRange=('Range', 'mean'),
        AvgTickVol=('TickVolume', 'mean'),
        Count=('Close', 'count')
    )
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    print("\n  Weekday Performance:")
    print(f"  {'Day':>6} {'AvgReturn':>10} {'AvgRange':>10} {'AvgTickVol':>11}")
    print("  " + "-" * 40)
    for wd, row in daily_by_wd.iterrows():
        print(f"  {day_names[wd]:>6} {row['AvgReturn']:>10.4f} {row['AvgRange']:>10.2f} {row['AvgTickVol']:>11.1f}")

    # Session strategies: only trade during specific hours
    results = []
    # Define sessions (server time, which appears to be UTC-ish based on data)
    sessions = {
        'Asia (0-6)':       (0, 6),
        'London (7-14)':    (7, 14),
        'NY (14-21)':       (14, 21),
        'LondonOpen (7-9)': (7, 9),
        'NYOpen (13-16)':   (13, 16),
        'Overlap (13-16)':  (13, 16),
        'HighVol (14-20)':  (14, 20),
    }

    # Use EMA 9/21 crossover as base signal, filtered by session
    ema_fast = ema(df['Close'], 9)
    ema_slow = ema(df['Close'], 21)
    cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
    cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

    base_signals = pd.Series(0, index=df.index)
    base_signals[cross_up] = 1
    base_signals[cross_down] = -1

    for sess_name, (start_h, end_h) in sessions.items():
        mask = (df['Hour'] >= start_h) & (df['Hour'] < end_h)
        filtered = base_signals.copy()
        filtered[~mask] = 0

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40), (25, 50)]:
                lbl = f"EMA(9/21) {sess_name} h={hold}"
                if sl is not None:
                    lbl += f" SL={sl}/TP={tp}"
                results.append(backtest(df, filtered, hold, sl, tp, lbl))

    print_results(results)
    return results


def test_momentum_breakout(df):
    """Momentum and breakout pattern strategies."""
    print("=" * 80)
    print("STRATEGY GROUP 6: MOMENTUM & BREAKOUT")
    print("=" * 80)
    results = []

    # --- A. N-bar high/low breakout ---
    for lookback in [10, 20, 30, 50]:
        rolling_high = df['High'].rolling(lookback).max().shift(1)
        rolling_low = df['Low'].rolling(lookback).min().shift(1)

        signals = pd.Series(0, index=df.index)
        signals[df['Close'] > rolling_high] = 1
        signals[df['Close'] < rolling_low] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40), (30, 60)]:
                lbl = f"Breakout({lookback}) h={hold}"
                if sl is not None:
                    lbl += f" SL={sl}/TP={tp}"
                results.append(backtest(df, signals, hold, sl, tp, lbl))

    # --- B. Momentum (rate of change) ---
    for mom_period in [5, 10, 15, 20, 30]:
        roc = df['Close'].pct_change(mom_period) * 100
        for thresh in [0.05, 0.1, 0.15]:
            signals = pd.Series(0, index=df.index)
            signals[roc > thresh] = 1
            signals[roc < -thresh] = -1

            for hold in [15, 30]:
                for sl, tp in [(None, None), (15, 30), (20, 40)]:
                    lbl = f"MOM({mom_period})>{thresh} h={hold}"
                    if sl is not None:
                        lbl += f" SL={sl}/TP={tp}"
                    results.append(backtest(df, signals, hold, sl, tp, lbl))

    # --- C. Volume spike breakout ---
    vol_ma = df['TickVolume'].rolling(20).mean()
    for vol_mult in [1.5, 2.0, 2.5]:
        vol_spike = df['TickVolume'] > (vol_ma * vol_mult)
        bar_dir = np.sign(df['Close'] - df['Open'])

        signals = pd.Series(0, index=df.index)
        signals[vol_spike & (bar_dir == 1)] = 1
        signals[vol_spike & (bar_dir == -1)] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40)]:
                lbl = f"VolSpike({vol_mult}x) h={hold}"
                if sl is not None:
                    lbl += f" SL={sl}/TP={tp}"
                results.append(backtest(df, signals, hold, sl, tp, lbl))

    print_results(results)
    return results


def test_atr_strategies(df):
    """ATR-based stop-loss/take-profit analysis."""
    print("=" * 80)
    print("STRATEGY GROUP 7: ATR-BASED SL/TP OPTIMISATION")
    print("=" * 80)
    results = []

    atr_14 = atr(df, 14)
    atr_val = atr_14.median()
    print(f"  ATR(14) median: {atr_val:.2f} pts")
    print(f"  ATR(14) mean  : {atr_14.mean():.2f} pts")
    print(f"  ATR(14) 25th  : {atr_14.quantile(0.25):.2f} pts")
    print(f"  ATR(14) 75th  : {atr_14.quantile(0.75):.2f} pts")
    print()

    # Use EMA 9/21 as base signal and vary ATR multiples for SL/TP
    ema_fast = ema(df['Close'], 9)
    ema_slow = ema(df['Close'], 21)
    cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
    cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
    signals = pd.Series(0, index=df.index)
    signals[cross_up] = 1
    signals[cross_down] = -1

    # Dynamic ATR-based SL/TP backtest
    for sl_mult in [1.0, 1.5, 2.0, 2.5, 3.0]:
        for tp_mult in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
            if tp_mult <= sl_mult:
                continue
            sl_pts = round(atr_val * sl_mult, 1)
            tp_pts = round(atr_val * tp_mult, 1)
            for hold in [30, 60, 120]:
                lbl = f"EMA9/21 ATR SL={sl_mult}x({sl_pts}) TP={tp_mult}x({tp_pts}) h={hold}"
                results.append(backtest(df, signals, hold, sl_pts, tp_pts, lbl))

    # Also test with RSI filter + ATR SL/TP
    rsi_14 = rsi(df['Close'], 14)
    for sl_mult in [1.5, 2.0, 2.5]:
        for tp_mult in [2.0, 3.0, 4.0]:
            if tp_mult <= sl_mult:
                continue
            sl_pts = round(atr_val * sl_mult, 1)
            tp_pts = round(atr_val * tp_mult, 1)

            # EMA cross + RSI confirmation
            signals_rsi = pd.Series(0, index=df.index)
            signals_rsi[cross_up & (rsi_14 < 60)] = 1
            signals_rsi[cross_down & (rsi_14 > 40)] = -1

            for hold in [30, 60, 120]:
                lbl = f"EMA9/21+RSI ATR SL={sl_mult}x TP={tp_mult}x h={hold}"
                results.append(backtest(df, signals_rsi, hold, sl_pts, tp_pts, lbl))

    print_results(results)
    return results


def test_support_resistance(df):
    """Support/Resistance level strategies using pivot points and price clusters."""
    print("=" * 80)
    print("STRATEGY GROUP 8: SUPPORT / RESISTANCE")
    print("=" * 80)
    results = []

    # Daily pivot points
    df['Date'] = df['DateTime'].dt.date
    daily = df.groupby('Date').agg(
        DH=('High', 'max'), DL=('Low', 'min'), DC=('Close', 'last')
    )
    daily['Pivot'] = (daily['DH'] + daily['DL'] + daily['DC']) / 3
    daily['R1'] = 2 * daily['Pivot'] - daily['DL']
    daily['S1'] = 2 * daily['Pivot'] - daily['DH']
    daily['R2'] = daily['Pivot'] + (daily['DH'] - daily['DL'])
    daily['S2'] = daily['Pivot'] - (daily['DH'] - daily['DL'])

    # Shift pivots to next day (use yesterday's pivots for today)
    daily_shifted = daily.shift(1)
    daily_shifted.columns = ['prev_DH', 'prev_DL', 'prev_DC', 'Pivot', 'R1', 'S1', 'R2', 'S2']

    # Merge back
    df_pvt = df.merge(daily_shifted[['Pivot', 'R1', 'S1', 'R2', 'S2']],
                       left_on='Date', right_index=True, how='left')

    # Strategy: bounce off S1 (long) / R1 (short)
    tol = 5  # points tolerance
    for tol in [3, 5, 8, 10]:
        signals = pd.Series(0, index=df_pvt.index)
        signals[(df_pvt['Low'] <= df_pvt['S1'] + tol) & (df_pvt['Close'] > df_pvt['S1'])] = 1
        signals[(df_pvt['High'] >= df_pvt['R1'] - tol) & (df_pvt['Close'] < df_pvt['R1'])] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40), (10, 20)]:
                lbl = f"Pivot S1/R1 tol={tol} h={hold}"
                if sl is not None:
                    lbl += f" SL={sl}/TP={tp}"
                results.append(backtest(df_pvt, signals, hold, sl, tp, lbl))

    # S2/R2 bounce
    for tol in [3, 5, 8]:
        signals = pd.Series(0, index=df_pvt.index)
        signals[(df_pvt['Low'] <= df_pvt['S2'] + tol) & (df_pvt['Close'] > df_pvt['S2'])] = 1
        signals[(df_pvt['High'] >= df_pvt['R2'] - tol) & (df_pvt['Close'] < df_pvt['R2'])] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40)]:
                lbl = f"Pivot S2/R2 tol={tol} h={hold}"
                if sl is not None:
                    lbl += f" SL={sl}/TP={tp}"
                results.append(backtest(df_pvt, signals, hold, sl, tp, lbl))

    # Pivot breakout: break above R1 → long, below S1 → short
    for tol in [0, 3, 5]:
        signals_bo = pd.Series(0, index=df_pvt.index)
        signals_bo[df_pvt['Close'] > df_pvt['R1'] + tol] = 1
        signals_bo[df_pvt['Close'] < df_pvt['S1'] - tol] = -1

        # Reduce to first crossing only
        prev_above_r1 = df_pvt['Close'].shift(1) <= df_pvt['R1'].shift(1) + tol
        prev_below_s1 = df_pvt['Close'].shift(1) >= df_pvt['S1'].shift(1) - tol

        signals_cross = pd.Series(0, index=df_pvt.index)
        signals_cross[(df_pvt['Close'] > df_pvt['R1'] + tol) & prev_above_r1] = 1
        signals_cross[(df_pvt['Close'] < df_pvt['S1'] - tol) & prev_below_s1] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(None, None), (15, 30), (20, 40), (25, 50)]:
                lbl = f"Pivot BO tol={tol} h={hold}"
                if sl is not None:
                    lbl += f" SL={sl}/TP={tp}"
                results.append(backtest(df_pvt, signals_cross, hold, sl, tp, lbl))

    print_results(results)
    return results


def test_combined_strategies(df):
    """Test the best combinations: EMA + RSI + BB + Session filters."""
    print("=" * 80)
    print("STRATEGY GROUP 9: COMBINED / MULTI-INDICATOR")
    print("=" * 80)
    results = []

    ema_9 = ema(df['Close'], 9)
    ema_21 = ema(df['Close'], 21)
    ema_50 = ema(df['Close'], 50)
    rsi_14 = rsi(df['Close'], 14)
    rsi_7 = rsi(df['Close'], 7)
    atr_14 = atr(df, 14)
    upper_20, mid_20, lower_20 = bollinger_bands(df['Close'], 20, 2.0)

    df['Hour'] = df['DateTime'].dt.hour

    # A. EMA cross + RSI filter + session filter
    cross_up = (ema_9 > ema_21) & (ema_9.shift(1) <= ema_21.shift(1))
    cross_down = (ema_9 < ema_21) & (ema_9.shift(1) >= ema_21.shift(1))

    for rsi_lo, rsi_hi in [(35, 65), (40, 60), (30, 70), (25, 75)]:
        for start_h, end_h, sess in [(7, 20, '7-20'), (8, 18, '8-18'), (13, 20, '13-20'), (14, 21, '14-21')]:
            sess_mask = (df['Hour'] >= start_h) & (df['Hour'] < end_h)

            signals = pd.Series(0, index=df.index)
            signals[cross_up & (rsi_14 < rsi_hi) & (rsi_14 > 30) & sess_mask] = 1
            signals[cross_down & (rsi_14 > rsi_lo) & (rsi_14 < 70) & sess_mask] = -1

            for hold in [30, 60]:
                for sl, tp in [(15, 30), (20, 40), (25, 50), (20, 60)]:
                    lbl = f"EMA9/21+RSI({rsi_lo}-{rsi_hi})+{sess} h={hold} SL={sl}/TP={tp}"
                    results.append(backtest(df, signals, hold, sl, tp, lbl))

    # B. EMA trend + BB bounce
    for start_h, end_h, sess in [(7, 20, '7-20'), (13, 20, '13-20')]:
        sess_mask = (df['Hour'] >= start_h) & (df['Hour'] < end_h)

        signals = pd.Series(0, index=df.index)
        # Long: price touches lower BB + EMA9 > EMA21 (uptrend pullback)
        signals[(df['Close'] < lower_20) & (ema_9 > ema_21) & sess_mask] = 1
        # Short: price touches upper BB + EMA9 < EMA21
        signals[(df['Close'] > upper_20) & (ema_9 < ema_21) & sess_mask] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(15, 30), (20, 40), (25, 50)]:
                lbl = f"EMA+BB bounce {sess} h={hold} SL={sl}/TP={tp}"
                results.append(backtest(df, signals, hold, sl, tp, lbl))

    # C. Triple EMA alignment + momentum
    for start_h, end_h, sess in [(7, 20, '7-20'), (13, 20, '13-20')]:
        sess_mask = (df['Hour'] >= start_h) & (df['Hour'] < end_h)

        signals = pd.Series(0, index=df.index)
        # Long: 9 > 21 > 50 and RSI rising
        long_cond = (ema_9 > ema_21) & (ema_21 > ema_50) & (rsi_14 > 50) & (rsi_14 < 75) & sess_mask
        # Trigger on EMA9/21 cross when EMA21 already above 50
        signals[cross_up & (ema_21 > ema_50) & (rsi_14 > 45) & (rsi_14 < 75) & sess_mask] = 1
        signals[cross_down & (ema_21 < ema_50) & (rsi_14 < 55) & (rsi_14 > 25) & sess_mask] = -1

        for hold in [30, 60, 120]:
            for sl, tp in [(15, 30), (20, 40), (25, 50), (20, 60), (30, 60)]:
                lbl = f"TripleEMA+RSI {sess} h={hold} SL={sl}/TP={tp}"
                results.append(backtest(df, signals, hold, sl, tp, lbl))

    # D. RSI divergence-like: RSI oversold + price near support (BB lower) + volume confirmation
    vol_ma = df['TickVolume'].rolling(20).mean()
    for start_h, end_h, sess in [(7, 20, '7-20'), (13, 20, '13-20')]:
        sess_mask = (df['Hour'] >= start_h) & (df['Hour'] < end_h)

        signals = pd.Series(0, index=df.index)
        signals[(rsi_14 < 30) & (df['Close'] < lower_20) & (df['TickVolume'] > vol_ma * 1.5) & sess_mask] = 1
        signals[(rsi_14 > 70) & (df['Close'] > upper_20) & (df['TickVolume'] > vol_ma * 1.5) & sess_mask] = -1

        for hold in [15, 30, 60]:
            for sl, tp in [(15, 30), (20, 40), (25, 50)]:
                lbl = f"RSI+BB+Vol {sess} h={hold} SL={sl}/TP={tp}"
                results.append(backtest(df, signals, hold, sl, tp, lbl))

    # E. EMA crossover with ATR-dynamic SL/TP
    atr_med = atr_14.median()
    for start_h, end_h, sess in [(7, 20, '7-20'), (13, 20, '13-20')]:
        sess_mask = (df['Hour'] >= start_h) & (df['Hour'] < end_h)

        signals = pd.Series(0, index=df.index)
        signals[cross_up & sess_mask] = 1
        signals[cross_down & sess_mask] = -1

        for sl_m, tp_m in [(1.5, 3.0), (2.0, 3.0), (2.0, 4.0), (1.5, 4.0), (2.5, 5.0)]:
            sl = round(atr_med * sl_m, 1)
            tp = round(atr_med * tp_m, 1)
            for hold in [30, 60, 120]:
                lbl = f"EMA9/21 {sess} ATR SL={sl_m}x TP={tp_m}x h={hold}"
                results.append(backtest(df, signals, hold, sl, tp, lbl))

    print_results(results)
    return results


# ─────────────────────────────────────────────────────────────
# 6. MAIN
# ─────────────────────────────────────────────────────────────
def main():
    filepath = '/home/user/Robin/1m_data.csv'
    df = load_data(filepath)
    df = compute_statistics(df)

    all_results = []

    r1 = test_ema_crossovers(df)
    all_results.extend(r1)

    r2 = test_rsi_strategies(df)
    all_results.extend(r2)

    r3 = test_bollinger_bands(df)
    all_results.extend(r3)

    r4 = test_vwap_strategies(df)
    all_results.extend(r4)

    r5 = test_session_analysis(df)
    all_results.extend(r5)

    r6 = test_momentum_breakout(df)
    all_results.extend(r6)

    r7 = test_atr_strategies(df)
    all_results.extend(r7)

    r8 = test_support_resistance(df)
    all_results.extend(r8)

    r9 = test_combined_strategies(df)
    all_results.extend(r9)

    # ─────────────────────────────────────────────────────────
    # GRAND SUMMARY: TOP STRATEGIES
    # ─────────────────────────────────────────────────────────
    print("=" * 80)
    print("=" * 80)
    print("  GRAND SUMMARY: TOP 30 STRATEGIES BY TOTAL RETURN")
    print("=" * 80)
    print("=" * 80)
    print()

    # Filter strategies with at least 50 trades
    viable = [r for r in all_results if r['trades'] >= 50]
    viable_sorted = sorted(viable, key=lambda x: x['total_return'], reverse=True)

    header = (f"  {'#':>3} {'Strategy':<52} {'Trades':>7} {'WinR%':>7} {'PF':>7} "
              f"{'TotalPts':>10} {'MaxDD':>9} {'AvgWin':>8} {'AvgLoss':>8} "
              f"{'Sharpe':>8} {'Expect':>8}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, r in enumerate(viable_sorted[:30], 1):
        print(f"  {i:>3} {r['label']:<52} {r['trades']:>7} {r['win_rate']:>7.1f} {r['profit_factor']:>7.2f} "
              f"{r['total_return']:>10.1f} {r['max_dd']:>9.1f} {r['avg_win']:>8.2f} {r['avg_loss']:>8.2f} "
              f"{r['sharpe']:>8.2f} {r['expectancy']:>8.2f}")

    print()
    print("=" * 80)
    print("  TOP 20 BY PROFIT FACTOR (min 100 trades)")
    print("=" * 80)
    viable_pf = [r for r in all_results if r['trades'] >= 100 and r['profit_factor'] > 0]
    viable_pf_sorted = sorted(viable_pf, key=lambda x: x['profit_factor'], reverse=True)

    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, r in enumerate(viable_pf_sorted[:20], 1):
        print(f"  {i:>3} {r['label']:<52} {r['trades']:>7} {r['win_rate']:>7.1f} {r['profit_factor']:>7.2f} "
              f"{r['total_return']:>10.1f} {r['max_dd']:>9.1f} {r['avg_win']:>8.2f} {r['avg_loss']:>8.2f} "
              f"{r['sharpe']:>8.2f} {r['expectancy']:>8.2f}")

    print()
    print("=" * 80)
    print("  TOP 20 BY SHARPE RATIO (min 100 trades)")
    print("=" * 80)
    viable_sh = [r for r in all_results if r['trades'] >= 100]
    viable_sh_sorted = sorted(viable_sh, key=lambda x: x['sharpe'], reverse=True)

    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, r in enumerate(viable_sh_sorted[:20], 1):
        print(f"  {i:>3} {r['label']:<52} {r['trades']:>7} {r['win_rate']:>7.1f} {r['profit_factor']:>7.2f} "
              f"{r['total_return']:>10.1f} {r['max_dd']:>9.1f} {r['avg_win']:>8.2f} {r['avg_loss']:>8.2f} "
              f"{r['sharpe']:>8.2f} {r['expectancy']:>8.2f}")

    print()
    print("=" * 80)
    print("  TOP 10 RISK-ADJUSTED (Sharpe * ProfitFactor, min 200 trades)")
    print("=" * 80)
    viable_ra = [r for r in all_results if r['trades'] >= 200 and r['profit_factor'] > 0]
    for r in viable_ra:
        r['risk_adj_score'] = r['sharpe'] * r['profit_factor']
    viable_ra_sorted = sorted(viable_ra, key=lambda x: x['risk_adj_score'], reverse=True)

    header2 = (f"  {'#':>3} {'Strategy':<52} {'Trades':>7} {'WinR%':>7} {'PF':>7} "
               f"{'TotalPts':>10} {'MaxDD':>9} {'Sharpe':>8} {'Score':>8}")
    print(header2)
    print("  " + "-" * (len(header2) - 2))
    for i, r in enumerate(viable_ra_sorted[:10], 1):
        print(f"  {i:>3} {r['label']:<52} {r['trades']:>7} {r['win_rate']:>7.1f} {r['profit_factor']:>7.2f} "
              f"{r['total_return']:>10.1f} {r['max_dd']:>9.1f} "
              f"{r['sharpe']:>8.2f} {r['risk_adj_score']:>8.2f}")

    # Best overall
    print()
    print("=" * 80)
    print("  BEST OVERALL RECOMMENDATION")
    print("=" * 80)
    if viable_sorted:
        best = viable_sorted[0]
        print(f"\n  HIGHEST TOTAL RETURN:")
        for k, v in best.items():
            print(f"    {k:<20}: {v}")

    if viable_pf_sorted:
        best_pf = viable_pf_sorted[0]
        print(f"\n  HIGHEST PROFIT FACTOR (100+ trades):")
        for k, v in best_pf.items():
            if k != 'risk_adj_score':
                print(f"    {k:<20}: {v}")

    if viable_sh_sorted:
        best_sh = viable_sh_sorted[0]
        print(f"\n  HIGHEST SHARPE RATIO (100+ trades):")
        for k, v in best_sh.items():
            if k != 'risk_adj_score':
                print(f"    {k:<20}: {v}")

    if viable_ra_sorted:
        best_ra = viable_ra_sorted[0]
        print(f"\n  BEST RISK-ADJUSTED (200+ trades):")
        for k, v in best_ra.items():
            print(f"    {k:<20}: {v}")

    # Summary stats
    total_strats = len(all_results)
    profitable = len([r for r in all_results if r['total_return'] > 0 and r['trades'] >= 50])
    print(f"\n  Total strategy variants tested : {total_strats}")
    print(f"  Profitable (50+ trades)       : {profitable}")
    print(f"  Profitable %                  : {profitable/max(total_strats,1)*100:.1f}%")
    print()


if __name__ == '__main__':
    main()
