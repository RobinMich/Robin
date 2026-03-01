#!/usr/bin/env python3
"""
Comprehensive Stress Test for NAS100 Multi-Strategy EA
Tests the strategy under adverse conditions:
1. Walk-Forward Analysis (in-sample/out-of-sample splits)
2. Monte Carlo Simulation (randomized trade sequences)
3. Spread Sensitivity Analysis
4. Slippage Simulation
5. Drawdown Stress Test
6. Regime Analysis (trending vs ranging vs volatile)
7. Correlation between strategies
8. Parameter Sensitivity (perturbation analysis)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# DATA LOADING
# =============================================================================
def load_data(filepath):
    """Load and parse the 1-minute data (entire lines are quoted)."""
    rows = []
    with open(filepath, 'r') as f:
        for i, line in enumerate(f):
            line = line.strip().strip('"')
            if i == 0:
                continue  # skip header
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

# =============================================================================
# INDICATOR CALCULATIONS
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

# =============================================================================
# STRATEGY SIMULATION ENGINE
# =============================================================================
class StrategySimulator:
    def __init__(self, df, spread=2.0, slippage=0.5, commission=0.0):
        """
        df: DataFrame with OHLCV data
        spread: in points (1 point = 0.1 on NAS100)
        slippage: in points
        commission: per lot per side
        """
        self.df = df.copy()
        self.spread = spread
        self.slippage = slippage
        self.commission = commission
        self.prepare_indicators()

    def prepare_indicators(self):
        """Pre-calculate all indicators."""
        self.df['EMA9'] = calc_ema(self.df['Close'], 9)
        self.df['EMA21'] = calc_ema(self.df['Close'], 21)
        self.df['RSI14'] = calc_rsi(self.df['Close'], 14)
        self.df['ATR14'] = calc_atr(self.df, 14)
        self.df['VolMA20'] = self.df['TickVolume'].rolling(20).mean()
        self.df['Hour'] = self.df['DateTime'].dt.hour
        self.df['DayOfWeek'] = self.df['DateTime'].dt.dayofweek  # 0=Mon

    def simulate_ema_strategy(self, fast=9, slow=21, sl_pts=25.0, tp_pts=50.0,
                               max_hold=30, session_start=7, session_end=9):
        """Simulate EMA crossover strategy with session filter."""
        df = self.df.copy()
        ema_fast = calc_ema(df['Close'], fast)
        ema_slow = calc_ema(df['Close'], slow)

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        direction = 0
        bars_held = 0

        for i in range(1, len(df)):
            if in_position:
                bars_held += 1
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if direction == 1:  # Long
                    if low <= entry_price - sl_pts:
                        pnl = -sl_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif high >= entry_price + tp_pts:
                        pnl = tp_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = df['Close'].iloc[i] - entry_price - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                else:  # Short
                    if high >= entry_price + sl_pts:
                        pnl = -sl_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif low <= entry_price - tp_pts:
                        pnl = tp_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = entry_price - df['Close'].iloc[i] - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                continue

            # Check session filter
            hour = df['Hour'].iloc[i]
            if session_start <= session_end:
                if hour < session_start or hour >= session_end:
                    continue
            else:
                if hour < session_start and hour >= session_end:
                    continue

            # EMA crossover detection
            prev_fast = ema_fast.iloc[i-1]
            prev_slow = ema_slow.iloc[i-1]
            curr_fast = ema_fast.iloc[i]
            curr_slow = ema_slow.iloc[i]

            if prev_fast <= prev_slow and curr_fast > curr_slow:
                direction = 1
                entry_price = df['Close'].iloc[i] + self.spread/2 + self.slippage
                entry_idx = i
                bars_held = 0
                in_position = True
            elif prev_fast >= prev_slow and curr_fast < curr_slow:
                direction = -1
                entry_price = df['Close'].iloc[i] - self.spread/2 - self.slippage
                entry_idx = i
                bars_held = 0
                in_position = True

        return trades

    def simulate_volume_strategy(self, vol_mult=2.5, vol_period=20,
                                  sl_pts=20.0, tp_pts=40.0, max_hold=30):
        """Simulate volume spike strategy."""
        df = self.df.copy()
        vol_ma = df['TickVolume'].rolling(vol_period).mean()

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        direction = 0
        bars_held = 0

        for i in range(vol_period + 1, len(df)):
            if in_position:
                bars_held += 1
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if direction == 1:
                    if low <= entry_price - sl_pts:
                        pnl = -sl_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif high >= entry_price + tp_pts:
                        pnl = tp_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = df['Close'].iloc[i] - entry_price - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                else:
                    if high >= entry_price + sl_pts:
                        pnl = -sl_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif low <= entry_price - tp_pts:
                        pnl = tp_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = entry_price - df['Close'].iloc[i] - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                continue

            # Volume spike detection
            curr_vol = df['TickVolume'].iloc[i-1]  # Confirmed bar
            avg_vol = vol_ma.iloc[i-1]

            if pd.isna(avg_vol) or avg_vol <= 0:
                continue

            if curr_vol >= avg_vol * vol_mult:
                bar_open = df['Open'].iloc[i-1]
                bar_close = df['Close'].iloc[i-1]

                if bar_close > bar_open:
                    direction = 1
                    entry_price = df['Close'].iloc[i] + self.spread/2 + self.slippage
                elif bar_close < bar_open:
                    direction = -1
                    entry_price = df['Close'].iloc[i] - self.spread/2 - self.slippage
                else:
                    continue

                entry_idx = i
                bars_held = 0
                in_position = True

        return trades

    def simulate_rsi_strategy(self, period=14, upper=80, lower=20,
                               sl_pts=25.0, tp_pts=50.0, max_hold=15):
        """Simulate RSI momentum continuation strategy."""
        df = self.df.copy()
        rsi = calc_rsi(df['Close'], period)

        trades = []
        in_position = False
        entry_price = 0
        entry_idx = 0
        direction = 0
        bars_held = 0

        for i in range(period + 1, len(df)):
            if in_position:
                bars_held += 1
                high = df['High'].iloc[i]
                low = df['Low'].iloc[i]

                if direction == 1:
                    if low <= entry_price - sl_pts:
                        pnl = -sl_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif high >= entry_price + tp_pts:
                        pnl = tp_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = df['Close'].iloc[i] - entry_price - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'LONG', 'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                else:
                    if high >= entry_price + sl_pts:
                        pnl = -sl_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'SL', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif low <= entry_price - tp_pts:
                        pnl = tp_pts - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'TP', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                    elif bars_held >= max_hold:
                        pnl = entry_price - df['Close'].iloc[i] - self.spread - self.slippage
                        trades.append({'entry_idx': entry_idx, 'exit_idx': i, 'pnl': pnl,
                                      'direction': 'SHORT', 'exit_reason': 'TIME', 'bars': bars_held,
                                      'entry_time': df['DateTime'].iloc[entry_idx]})
                        in_position = False
                continue

            rsi_val = rsi.iloc[i-1]  # Confirmed bar
            if pd.isna(rsi_val):
                continue

            if rsi_val > upper:
                direction = 1
                entry_price = df['Close'].iloc[i] + self.spread/2 + self.slippage
                entry_idx = i
                bars_held = 0
                in_position = True
            elif rsi_val < lower:
                direction = -1
                entry_price = df['Close'].iloc[i] - self.spread/2 - self.slippage
                entry_idx = i
                bars_held = 0
                in_position = True

        return trades

# =============================================================================
# STATISTICS CALCULATOR
# =============================================================================
def calc_stats(trades, label=""):
    """Calculate comprehensive statistics for a list of trades."""
    if not trades:
        return {'label': label, 'trades': 0, 'total_pnl': 0, 'win_rate': 0,
                'profit_factor': 0, 'max_dd': 0, 'sharpe': 0, 'avg_win': 0,
                'avg_loss': 0, 'expectancy': 0, 'max_consec_loss': 0}

    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    expectancy = np.mean(pnls) if pnls else 0

    # Max drawdown
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0

    # Sharpe ratio (annualized, assuming ~252 trading days, ~500 trades/year)
    if len(pnls) > 1:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252) if np.std(pnls) > 0 else 0
    else:
        sharpe = 0

    # Max consecutive losses
    max_consec = 0
    curr_consec = 0
    for p in pnls:
        if p <= 0:
            curr_consec += 1
            max_consec = max(max_consec, curr_consec)
        else:
            curr_consec = 0

    return {
        'label': label,
        'trades': len(pnls),
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'expectancy': expectancy,
        'max_consec_loss': max_consec
    }

def print_stats(stats):
    """Print formatted statistics."""
    print(f"  Trades: {stats['trades']:>6d} | WR: {stats['win_rate']:>5.1f}% | "
          f"PF: {stats['profit_factor']:>5.2f} | Total: {stats['total_pnl']:>8.1f} pts | "
          f"MaxDD: {stats['max_dd']:>7.1f} | Sharpe: {stats['sharpe']:>5.2f} | "
          f"Expect: {stats['expectancy']:>5.2f} | MaxConsecLoss: {stats['max_consec_loss']}")

# =============================================================================
# STRESS TEST FUNCTIONS
# =============================================================================
def walk_forward_analysis(df, n_splits=5):
    """Walk-forward analysis: train on 70%, test on 30%, rolling forward."""
    print("\n" + "="*80)
    print("STRESS TEST 1: WALK-FORWARD ANALYSIS")
    print("="*80)

    total_len = len(df)
    window_size = total_len // n_splits

    all_oos_trades = {'ema': [], 'vol': [], 'rsi': []}

    for fold in range(n_splits):
        start = fold * window_size
        end = min(start + window_size, total_len)

        split_point = start + int((end - start) * 0.7)

        is_data = df.iloc[start:split_point].copy().reset_index(drop=True)
        oos_data = df.iloc[split_point:end].copy().reset_index(drop=True)

        date_start = df['DateTime'].iloc[start].strftime('%Y-%m-%d')
        date_split = df['DateTime'].iloc[split_point].strftime('%Y-%m-%d')
        date_end = df['DateTime'].iloc[min(end-1, total_len-1)].strftime('%Y-%m-%d')

        print(f"\n--- Fold {fold+1}/{n_splits}: IS={date_start} to {date_split} | OOS={date_split} to {date_end} ---")

        # Test on OOS data
        sim = StrategySimulator(oos_data, spread=2.0, slippage=0.5)

        ema_trades = sim.simulate_ema_strategy()
        vol_trades = sim.simulate_volume_strategy()
        rsi_trades = sim.simulate_rsi_strategy()

        all_oos_trades['ema'].extend(ema_trades)
        all_oos_trades['vol'].extend(vol_trades)
        all_oos_trades['rsi'].extend(rsi_trades)

        print(f"  EMA OOS: ", end=""); print_stats(calc_stats(ema_trades, "EMA"))
        print(f"  VOL OOS: ", end=""); print_stats(calc_stats(vol_trades, "VOL"))
        print(f"  RSI OOS: ", end=""); print_stats(calc_stats(rsi_trades, "RSI"))

    print(f"\n--- COMBINED OOS RESULTS ---")
    for name, trades in all_oos_trades.items():
        stats = calc_stats(trades, name.upper())
        print(f"  {name.upper()} Total OOS: ", end=""); print_stats(stats)

    return all_oos_trades

def monte_carlo_simulation(trades, n_sims=1000, initial_balance=10000):
    """Monte Carlo: shuffle trade order, measure worst-case outcomes."""
    print("\n" + "="*80)
    print("STRESS TEST 2: MONTE CARLO SIMULATION (1000 iterations)")
    print("="*80)

    if not trades:
        print("  No trades to simulate.")
        return {}

    pnls = np.array([t['pnl'] for t in trades])
    n_trades = len(pnls)

    max_dds = []
    final_balances = []
    max_consec_losses_list = []
    ruin_count = 0
    ruin_threshold = initial_balance * 0.5  # 50% drawdown = ruin

    for _ in range(n_sims):
        shuffled = np.random.permutation(pnls)
        equity = np.cumsum(shuffled) + initial_balance
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        max_dd = np.max(dd)
        max_dds.append(max_dd)
        final_balances.append(equity[-1])

        # Count max consecutive losses
        consec = 0
        max_consec = 0
        for p in shuffled:
            if p <= 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0
        max_consec_losses_list.append(max_consec)

        if max_dd >= ruin_threshold:
            ruin_count += 1

    max_dds = np.array(max_dds)
    final_balances = np.array(final_balances)

    print(f"  Total Trades: {n_trades}")
    print(f"  Original Total PnL: {sum(pnls):.1f} pts")
    print(f"  --- Final Balance Distribution ---")
    print(f"    Mean:   ${np.mean(final_balances):>10.2f}")
    print(f"    Median: ${np.median(final_balances):>10.2f}")
    print(f"    5th %%:  ${np.percentile(final_balances, 5):>10.2f}")
    print(f"    95th %%: ${np.percentile(final_balances, 95):>10.2f}")
    print(f"    Worst:  ${np.min(final_balances):>10.2f}")
    print(f"    Best:   ${np.max(final_balances):>10.2f}")
    print(f"  --- Max Drawdown Distribution ---")
    print(f"    Mean:   ${np.mean(max_dds):>10.2f}")
    print(f"    Median: ${np.median(max_dds):>10.2f}")
    print(f"    95th %%: ${np.percentile(max_dds, 95):>10.2f}")
    print(f"    99th %%: ${np.percentile(max_dds, 99):>10.2f}")
    print(f"    Worst:  ${np.max(max_dds):>10.2f}")
    print(f"  --- Risk of Ruin ---")
    print(f"    Prob of 50%% DD: {ruin_count/n_sims*100:.1f}%")
    print(f"  --- Max Consecutive Losses ---")
    print(f"    Mean:   {np.mean(max_consec_losses_list):.1f}")
    print(f"    95th %%: {np.percentile(max_consec_losses_list, 95):.0f}")
    print(f"    Worst:  {np.max(max_consec_losses_list):.0f}")

    return {
        'max_dd_95': np.percentile(max_dds, 95),
        'final_balance_5th': np.percentile(final_balances, 5),
        'ruin_prob': ruin_count / n_sims
    }

def spread_sensitivity_analysis(df):
    """Test strategy performance across different spread levels."""
    print("\n" + "="*80)
    print("STRESS TEST 3: SPREAD SENSITIVITY ANALYSIS")
    print("="*80)

    spreads = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0]

    print(f"\n  {'Spread':>8} | {'Strategy':>8} | {'Trades':>6} | {'WR%':>5} | {'PF':>5} | {'Total PnL':>10} | {'Expectancy':>10}")
    print(f"  {'-'*75}")

    for spread in spreads:
        sim = StrategySimulator(df, spread=spread, slippage=0.5)

        ema_trades = sim.simulate_ema_strategy()
        vol_trades = sim.simulate_volume_strategy()
        rsi_trades = sim.simulate_rsi_strategy()

        for name, trades in [('EMA', ema_trades), ('VOL', vol_trades), ('RSI', rsi_trades)]:
            s = calc_stats(trades, name)
            print(f"  {spread:>8.1f} | {name:>8} | {s['trades']:>6d} | {s['win_rate']:>5.1f} | "
                  f"{s['profit_factor']:>5.2f} | {s['total_pnl']:>10.1f} | {s['expectancy']:>10.2f}")

def slippage_sensitivity_analysis(df):
    """Test strategy performance across different slippage levels."""
    print("\n" + "="*80)
    print("STRESS TEST 4: SLIPPAGE SENSITIVITY ANALYSIS")
    print("="*80)

    slippages = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0]

    print(f"\n  {'Slippage':>8} | {'Strategy':>8} | {'Trades':>6} | {'WR%':>5} | {'PF':>5} | {'Total PnL':>10} | {'Expectancy':>10}")
    print(f"  {'-'*75}")

    for slippage in slippages:
        sim = StrategySimulator(df, spread=2.0, slippage=slippage)

        ema_trades = sim.simulate_ema_strategy()
        vol_trades = sim.simulate_volume_strategy()
        rsi_trades = sim.simulate_rsi_strategy()

        for name, trades in [('EMA', ema_trades), ('VOL', vol_trades), ('RSI', rsi_trades)]:
            s = calc_stats(trades, name)
            print(f"  {slippage:>8.1f} | {name:>8} | {s['trades']:>6d} | {s['win_rate']:>5.1f} | "
                  f"{s['profit_factor']:>5.2f} | {s['total_pnl']:>10.1f} | {s['expectancy']:>10.2f}")

def regime_analysis(df):
    """Analyze performance in different market regimes."""
    print("\n" + "="*80)
    print("STRESS TEST 5: MARKET REGIME ANALYSIS")
    print("="*80)

    # Calculate daily returns and volatility
    df_daily = df.set_index('DateTime').resample('D').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'
    }).dropna()

    df_daily['Return'] = df_daily['Close'].pct_change()
    df_daily['Volatility'] = df_daily['Return'].rolling(5).std()
    df_daily['Trend'] = df_daily['Close'].rolling(20).mean()

    # Classify regimes
    median_vol = df_daily['Volatility'].median()

    # Get dates for each regime
    trending_up_dates = set(df_daily[
        (df_daily['Close'] > df_daily['Trend']) & (df_daily['Return'].rolling(5).mean() > 0)
    ].index.date)

    trending_down_dates = set(df_daily[
        (df_daily['Close'] < df_daily['Trend']) & (df_daily['Return'].rolling(5).mean() < 0)
    ].index.date)

    high_vol_dates = set(df_daily[df_daily['Volatility'] > median_vol * 1.5].index.date)
    low_vol_dates = set(df_daily[df_daily['Volatility'] < median_vol * 0.5].index.date)

    # Filter trades by regime
    sim = StrategySimulator(df, spread=2.0, slippage=0.5)

    for strat_name, strat_func in [
        ('EMA', sim.simulate_ema_strategy),
        ('VOL', sim.simulate_volume_strategy),
        ('RSI', sim.simulate_rsi_strategy)
    ]:
        trades = strat_func()
        if not trades:
            continue

        print(f"\n  --- {strat_name} Strategy by Regime ---")

        regimes = {
            'Trending Up': trending_up_dates,
            'Trending Down': trending_down_dates,
            'High Volatility': high_vol_dates,
            'Low Volatility': low_vol_dates
        }

        for regime_name, dates in regimes.items():
            regime_trades = [t for t in trades if t['entry_time'].date() in dates]
            if regime_trades:
                s = calc_stats(regime_trades, regime_name)
                print(f"    {regime_name:>16}: ", end=""); print_stats(s)
            else:
                print(f"    {regime_name:>16}: No trades")

def parameter_sensitivity(df):
    """Test small perturbations of key parameters to check robustness."""
    print("\n" + "="*80)
    print("STRESS TEST 6: PARAMETER SENSITIVITY (PERTURBATION)")
    print("="*80)

    base_params = {
        'EMA': {'fast': 9, 'slow': 21, 'sl': 25, 'tp': 50, 'max_hold': 30},
        'VOL': {'mult': 2.5, 'period': 20, 'sl': 20, 'tp': 40, 'max_hold': 30},
        'RSI': {'period': 14, 'upper': 80, 'lower': 20, 'sl': 25, 'tp': 50, 'max_hold': 15}
    }

    sim = StrategySimulator(df, spread=2.0, slippage=0.5)

    # EMA perturbations
    print(f"\n  --- EMA Strategy Parameter Sensitivity ---")
    ema_variants = [
        ('Base (9/21)', 9, 21, 25, 50, 30),
        ('Fast 7/21',   7, 21, 25, 50, 30),
        ('Fast 11/21', 11, 21, 25, 50, 30),
        ('Slow 9/18',   9, 18, 25, 50, 30),
        ('Slow 9/25',   9, 25, 25, 50, 30),
        ('SL 20/TP 40', 9, 21, 20, 40, 30),
        ('SL 30/TP 60', 9, 21, 30, 60, 30),
        ('SL 20/TP 60', 9, 21, 20, 60, 30),
        ('Hold 20',     9, 21, 25, 50, 20),
        ('Hold 45',     9, 21, 25, 50, 45),
    ]

    for name, fast, slow, sl, tp, hold in ema_variants:
        trades = sim.simulate_ema_strategy(fast=fast, slow=slow, sl_pts=sl, tp_pts=tp, max_hold=hold)
        s = calc_stats(trades, name)
        print(f"    {name:>16}: ", end=""); print_stats(s)

    # Volume perturbations
    print(f"\n  --- Volume Strategy Parameter Sensitivity ---")
    vol_variants = [
        ('Base 2.5x',    2.5, 20, 20, 40, 30),
        ('Mult 2.0x',    2.0, 20, 20, 40, 30),
        ('Mult 3.0x',    3.0, 20, 20, 40, 30),
        ('Period 15',    2.5, 15, 20, 40, 30),
        ('Period 30',    2.5, 30, 20, 40, 30),
        ('SL 15/TP 30',  2.5, 20, 15, 30, 30),
        ('SL 25/TP 50',  2.5, 20, 25, 50, 30),
        ('SL 15/TP 45',  2.5, 20, 15, 45, 30),
        ('Hold 20',      2.5, 20, 20, 40, 20),
        ('Hold 45',      2.5, 20, 20, 40, 45),
    ]

    for name, mult, period, sl, tp, hold in vol_variants:
        trades = sim.simulate_volume_strategy(vol_mult=mult, vol_period=period,
                                               sl_pts=sl, tp_pts=tp, max_hold=hold)
        s = calc_stats(trades, name)
        print(f"    {name:>16}: ", end=""); print_stats(s)

    # RSI perturbations
    print(f"\n  --- RSI Strategy Parameter Sensitivity ---")
    rsi_variants = [
        ('Base 80/20',    14, 80, 20, 25, 50, 15),
        ('RSI 75/25',     14, 75, 25, 25, 50, 15),
        ('RSI 85/15',     14, 85, 15, 25, 50, 15),
        ('Period 10',     10, 80, 20, 25, 50, 15),
        ('Period 20',     20, 80, 20, 25, 50, 15),
        ('SL 20/TP 40',   14, 80, 20, 20, 40, 15),
        ('SL 30/TP 60',   14, 80, 20, 30, 60, 15),
        ('SL 20/TP 60',   14, 80, 20, 20, 60, 15),
        ('Hold 10',       14, 80, 20, 25, 50, 10),
        ('Hold 25',       14, 80, 20, 25, 50, 25),
    ]

    for name, period, upper, lower, sl, tp, hold in rsi_variants:
        trades = sim.simulate_rsi_strategy(period=period, upper=upper, lower=lower,
                                            sl_pts=sl, tp_pts=tp, max_hold=hold)
        s = calc_stats(trades, name)
        print(f"    {name:>16}: ", end=""); print_stats(s)

def strategy_correlation_analysis(df):
    """Analyze correlation between strategy returns."""
    print("\n" + "="*80)
    print("STRESS TEST 7: STRATEGY CORRELATION & DIVERSIFICATION")
    print("="*80)

    sim = StrategySimulator(df, spread=2.0, slippage=0.5)

    ema_trades = sim.simulate_ema_strategy()
    vol_trades = sim.simulate_volume_strategy()
    rsi_trades = sim.simulate_rsi_strategy()

    # Create daily PnL series for each strategy
    all_dates = sorted(set(t['entry_time'].date() for t in ema_trades + vol_trades + rsi_trades))

    daily_pnl = {d: {'EMA': 0, 'VOL': 0, 'RSI': 0} for d in all_dates}

    for t in ema_trades:
        d = t['entry_time'].date()
        if d in daily_pnl:
            daily_pnl[d]['EMA'] += t['pnl']
    for t in vol_trades:
        d = t['entry_time'].date()
        if d in daily_pnl:
            daily_pnl[d]['VOL'] += t['pnl']
    for t in rsi_trades:
        d = t['entry_time'].date()
        if d in daily_pnl:
            daily_pnl[d]['RSI'] += t['pnl']

    if len(daily_pnl) < 5:
        print("  Not enough data for correlation analysis")
        return

    df_daily = pd.DataFrame.from_dict(daily_pnl, orient='index')

    # Correlation matrix
    corr = df_daily.corr()
    print(f"\n  Daily PnL Correlation Matrix:")
    print(f"        EMA     VOL     RSI")
    for name in ['EMA', 'VOL', 'RSI']:
        print(f"  {name}  {corr.loc[name, 'EMA']:>7.3f} {corr.loc[name, 'VOL']:>7.3f} {corr.loc[name, 'RSI']:>7.3f}")

    # Combined portfolio stats
    combined_daily = df_daily.sum(axis=1)
    print(f"\n  --- Combined Portfolio (Equal Weight) ---")
    print(f"  Total Days: {len(combined_daily)}")
    print(f"  Total PnL: {combined_daily.sum():.1f} pts")
    print(f"  Daily Mean: {combined_daily.mean():.2f} pts")
    print(f"  Daily Std: {combined_daily.std():.2f} pts")
    print(f"  Daily Sharpe: {combined_daily.mean()/combined_daily.std():.3f}" if combined_daily.std() > 0 else "  Daily Sharpe: N/A")

    equity = combined_daily.cumsum()
    peak = equity.cummax()
    dd = peak - equity
    print(f"  Max Drawdown: {dd.max():.1f} pts")
    print(f"  Calmar Ratio: {combined_daily.sum() / dd.max():.2f}" if dd.max() > 0 else "  Calmar Ratio: N/A")

    # Diversification benefit
    individual_dds = []
    for strat in ['EMA', 'VOL', 'RSI']:
        eq = df_daily[strat].cumsum()
        pk = eq.cummax()
        d = pk - eq
        individual_dds.append(d.max())

    avg_individual_dd = np.mean(individual_dds)
    print(f"\n  Avg Individual MaxDD: {avg_individual_dd:.1f} pts")
    print(f"  Combined MaxDD: {dd.max():.1f} pts")
    print(f"  Diversification Benefit: {(1 - dd.max()/avg_individual_dd)*100:.1f}%" if avg_individual_dd > 0 else "")

def worst_period_analysis(df):
    """Find and analyze the worst performing periods."""
    print("\n" + "="*80)
    print("STRESS TEST 8: WORST PERIOD ANALYSIS")
    print("="*80)

    sim = StrategySimulator(df, spread=2.0, slippage=0.5)

    for strat_name, strat_func in [
        ('EMA', sim.simulate_ema_strategy),
        ('VOL', sim.simulate_volume_strategy),
        ('RSI', sim.simulate_rsi_strategy)
    ]:
        trades = strat_func()
        if not trades:
            continue

        print(f"\n  --- {strat_name} Strategy Worst Periods ---")

        # Group by week
        weekly_pnl = {}
        for t in trades:
            week = t['entry_time'].isocalendar()[:2]
            week_key = f"{week[0]}-W{week[1]:02d}"
            if week_key not in weekly_pnl:
                weekly_pnl[week_key] = {'pnl': 0, 'trades': 0, 'wins': 0}
            weekly_pnl[week_key]['pnl'] += t['pnl']
            weekly_pnl[week_key]['trades'] += 1
            if t['pnl'] > 0:
                weekly_pnl[week_key]['wins'] += 1

        # Sort by PnL
        sorted_weeks = sorted(weekly_pnl.items(), key=lambda x: x[1]['pnl'])

        print(f"    5 Worst Weeks:")
        for week, data in sorted_weeks[:5]:
            wr = data['wins']/data['trades']*100 if data['trades'] > 0 else 0
            print(f"      {week}: PnL={data['pnl']:>8.1f} | Trades={data['trades']:>3d} | WR={wr:>5.1f}%")

        print(f"    5 Best Weeks:")
        for week, data in sorted_weeks[-5:]:
            wr = data['wins']/data['trades']*100 if data['trades'] > 0 else 0
            print(f"      {week}: PnL={data['pnl']:>8.1f} | Trades={data['trades']:>3d} | WR={wr:>5.1f}%")

# =============================================================================
# MAIN EXECUTION
# =============================================================================
if __name__ == "__main__":
    print("="*80)
    print("NAS100 MULTI-STRATEGY EA - COMPREHENSIVE STRESS TEST")
    print("="*80)

    print("\nLoading data...")
    df = load_data('/home/user/Robin/1m_data.csv')
    print(f"Loaded {len(df)} bars from {df['DateTime'].iloc[0]} to {df['DateTime'].iloc[-1]}")

    # === BASELINE PERFORMANCE ===
    print("\n" + "="*80)
    print("BASELINE PERFORMANCE (Spread=2.0, Slippage=0.5)")
    print("="*80)

    sim = StrategySimulator(df, spread=2.0, slippage=0.5)

    ema_trades = sim.simulate_ema_strategy()
    vol_trades = sim.simulate_volume_strategy()
    rsi_trades = sim.simulate_rsi_strategy()

    print(f"\n  EMA(9/21) LondonOpen: ", end=""); print_stats(calc_stats(ema_trades, "EMA"))
    print(f"  VolSpike(2.5x):       ", end=""); print_stats(calc_stats(vol_trades, "VOL"))
    print(f"  RSI(14) Mom:          ", end=""); print_stats(calc_stats(rsi_trades, "RSI"))

    combined = ema_trades + vol_trades + rsi_trades
    combined.sort(key=lambda x: x['entry_idx'])
    print(f"\n  COMBINED:             ", end=""); print_stats(calc_stats(combined, "ALL"))

    # === RUN ALL STRESS TESTS ===
    oos_trades = walk_forward_analysis(df, n_splits=5)

    # Monte Carlo on each strategy
    for name, trades in [('EMA', ema_trades), ('VOL', vol_trades), ('RSI', rsi_trades), ('COMBINED', combined)]:
        print(f"\n  >>> Monte Carlo: {name}")
        monte_carlo_simulation(trades, n_sims=1000)

    spread_sensitivity_analysis(df)
    slippage_sensitivity_analysis(df)
    regime_analysis(df)
    parameter_sensitivity(df)
    strategy_correlation_analysis(df)
    worst_period_analysis(df)

    print("\n" + "="*80)
    print("STRESS TEST COMPLETE")
    print("="*80)
