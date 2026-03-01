#!/usr/bin/env python3
"""
Stress Test & Parameter Optimization for TrendPullbackEA
=========================================================
1. Monte Carlo stress test (randomize trade order, simulate variance)
2. Parameter sensitivity analysis
3. Walk-forward optimization
4. Robustness tests (different market regimes)
"""

import os
import sys
import json
import itertools
import warnings
from copy import deepcopy
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from backtester import (
    StrategyParams, Backtester, run_multi_symbol_backtest,
    print_results, ALL_SYMBOLS, load_symbol_data, add_indicators,
    resample_to_weekly
)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


# ============================================================
# 1. MONTE CARLO STRESS TEST
# ============================================================
def monte_carlo_stress_test(trades_df, initial_capital=100000.0, n_simulations=1000,
                            confidence_levels=(0.95, 0.99)):
    """
    Shuffle trade order N times to get distribution of outcomes.
    Tests if strategy is robust regardless of trade sequence.
    """
    print("\n" + "=" * 65)
    print("  MONTE CARLO STRESS TEST")
    print(f"  Simulations: {n_simulations} | Initial Capital: ${initial_capital:,.0f}")
    print("=" * 65)

    if trades_df is None or len(trades_df) == 0:
        print("  No trades to simulate.")
        return None

    pnl_array = trades_df["pnl"].values
    n_trades = len(pnl_array)

    final_capitals = []
    max_drawdowns = []
    max_drawdowns_pct = []

    for sim in range(n_simulations):
        # Shuffle trade order
        shuffled_pnl = np.random.permutation(pnl_array)

        # Build equity curve
        equity = initial_capital + np.cumsum(shuffled_pnl)
        equity = np.insert(equity, 0, initial_capital)

        # Calculate max drawdown
        peak = np.maximum.accumulate(equity)
        dd = equity - peak
        max_dd = dd.min()
        max_dd_pct = (dd / peak * 100).min() if peak.max() > 0 else 0

        final_capitals.append(equity[-1])
        max_drawdowns.append(max_dd)
        max_drawdowns_pct.append(max_dd_pct)

    final_capitals = np.array(final_capitals)
    max_drawdowns = np.array(max_drawdowns)
    max_drawdowns_pct = np.array(max_drawdowns_pct)

    print(f"\n  Final Capital Distribution:")
    print(f"    Mean:   ${final_capitals.mean():>12,.2f}")
    print(f"    Median: ${np.median(final_capitals):>12,.2f}")
    print(f"    Std:    ${final_capitals.std():>12,.2f}")
    print(f"    Min:    ${final_capitals.min():>12,.2f}")
    print(f"    Max:    ${final_capitals.max():>12,.2f}")

    for cl in confidence_levels:
        pctile = (1 - cl) * 100
        val = np.percentile(final_capitals, pctile)
        print(f"    {cl*100:.0f}% VaR: ${val:>12,.2f}")

    print(f"\n  Max Drawdown Distribution:")
    print(f"    Mean:   ${max_drawdowns.mean():>12,.2f} ({max_drawdowns_pct.mean():.2f}%)")
    print(f"    Median: ${np.median(max_drawdowns):>12,.2f} ({np.median(max_drawdowns_pct):.2f}%)")
    print(f"    Worst:  ${max_drawdowns.min():>12,.2f} ({max_drawdowns_pct.min():.2f}%)")

    for cl in confidence_levels:
        pctile = (1 - cl) * 100
        dd_val = np.percentile(max_drawdowns, pctile)
        dd_pct_val = np.percentile(max_drawdowns_pct, pctile)
        print(f"    {cl*100:.0f}% Worst DD: ${dd_val:>10,.2f} ({dd_pct_val:.2f}%)")

    # Probability of ruin (losing > 50% of capital)
    ruin_count = np.sum(max_drawdowns_pct < -50)
    ruin_prob = ruin_count / n_simulations * 100
    print(f"\n  Probability of >50% drawdown: {ruin_prob:.2f}%")

    # Probability of profit
    profit_prob = np.sum(final_capitals > initial_capital) / n_simulations * 100
    print(f"  Probability of profit: {profit_prob:.1f}%")

    mc_results = {
        "n_simulations": n_simulations,
        "n_trades": n_trades,
        "final_capital_mean": round(final_capitals.mean(), 2),
        "final_capital_median": round(np.median(final_capitals), 2),
        "final_capital_std": round(final_capitals.std(), 2),
        "final_capital_min": round(final_capitals.min(), 2),
        "final_capital_max": round(final_capitals.max(), 2),
        "max_dd_mean_pct": round(max_drawdowns_pct.mean(), 2),
        "max_dd_worst_pct": round(max_drawdowns_pct.min(), 2),
        "prob_profit": round(profit_prob, 2),
        "prob_ruin_50pct": round(ruin_prob, 2),
    }

    return mc_results


# ============================================================
# 2. PARAMETER SENSITIVITY ANALYSIS
# ============================================================
def parameter_sensitivity(symbols, base_params=None, initial_capital=100000.0):
    """
    Test how sensitive the strategy is to parameter changes.
    Varies one parameter at a time while keeping others constant.
    """
    print("\n" + "=" * 65)
    print("  PARAMETER SENSITIVITY ANALYSIS")
    print("=" * 65)

    if base_params is None:
        base_params = StrategyParams()

    # Parameters to test with their ranges
    param_ranges = {
        "ema_fast": [13, 17, 21, 26, 34],
        "ema_mid": [34, 42, 50, 65, 80],
        "adx_threshold_context": [15, 18, 20, 25, 30],
        "adx_threshold_validation": [10, 12, 15, 18, 20],
        "atr_sl_multiplier": [1.0, 1.25, 1.5, 2.0, 2.5],
        "atr_trail_multiplier": [1.5, 2.0, 2.5, 3.0, 4.0],
        "donchian_period": [10, 15, 20, 25, 30],
        "bb_period": [14, 18, 20, 25, 30],
        "bbw_squeeze_percentile": [15, 20, 25, 30, 40],
        "volume_multiplier": [1.0, 1.1, 1.2, 1.3, 1.5],
        "be_rr_ratio": [0.8, 1.0, 1.2, 1.5, 2.0],
        "trail_start_rr": [1.5, 2.0, 2.5, 3.0, 4.0],
        "pb_atr_buffer": [0.3, 0.4, 0.5, 0.7, 1.0],
    }

    all_results = {}

    for param_name, values in param_ranges.items():
        print(f"\n  Testing {param_name}: {values}")
        param_results = []

        for val in values:
            test_params = deepcopy(base_params)
            setattr(test_params, param_name, val)

            bt, tested = run_multi_symbol_backtest(
                symbols, test_params, initial_capital
            )

            result = bt.get_results()
            if isinstance(result, tuple):
                stats, _ = result
                param_results.append({
                    "value": val,
                    "total_pnl": stats["total_pnl"],
                    "win_rate": stats["win_rate"],
                    "profit_factor": stats["profit_factor"],
                    "max_dd_pct": stats["max_drawdown_pct"],
                    "avg_rr": stats["avg_rr"],
                    "total_trades": stats["total_trades"],
                })
                print(f"    {param_name}={val}: PnL=${stats['total_pnl']:,.0f} | "
                      f"WR={stats['win_rate']:.1f}% | PF={stats['profit_factor']:.2f} | "
                      f"MaxDD={stats['max_drawdown_pct']:.1f}%")
            else:
                param_results.append({"value": val, "total_pnl": 0, "error": True})

        all_results[param_name] = param_results

    return all_results


# ============================================================
# 3. WALK-FORWARD OPTIMIZATION
# ============================================================
def walk_forward_test(symbols, n_folds=5, initial_capital=100000.0):
    """
    Walk-forward analysis: optimize on in-sample, test on out-of-sample.
    Splits data chronologically into folds.
    """
    print("\n" + "=" * 65)
    print("  WALK-FORWARD OPTIMIZATION")
    print(f"  Folds: {n_folds}")
    print("=" * 65)

    # Key parameters to optimize
    param_grid = {
        "ema_fast": [17, 21, 26],
        "ema_mid": [42, 50, 65],
        "atr_sl_multiplier": [1.25, 1.5, 2.0],
        "atr_trail_multiplier": [2.0, 2.5, 3.0],
        "donchian_period": [15, 20, 25],
        "be_rr_ratio": [1.0, 1.2, 1.5],
    }

    # Generate combinations (limited for speed)
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    print(f"  Parameter combinations: {len(combos)}")

    # Load data for all symbols
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    all_data = {}
    for sym in symbols:
        data = load_symbol_data(sym, data_dir)
        if data:
            all_data[sym] = data

    if not all_data:
        print("  No data available for walk-forward test.")
        return None

    # Get date range from first symbol's daily data
    sample_sym = list(all_data.keys())[0]
    sample_df = None
    for tf in ["D1", "H4", "H2", "H1"]:
        if tf in all_data[sample_sym]:
            sample_df = all_data[sample_sym][tf]
            break

    if sample_df is None:
        print("  No suitable data found.")
        return None

    dates = sample_df.index
    fold_size = len(dates) // n_folds
    oos_results = []

    for fold in range(1, n_folds):
        train_end = dates[fold * fold_size]
        test_start = train_end
        test_end = dates[min((fold + 1) * fold_size, len(dates) - 1)]

        print(f"\n  Fold {fold}/{n_folds-1}: Train to {train_end.date()} | "
              f"Test {test_start.date()} to {test_end.date()}")

        # Find best params on training data
        best_pnl = -np.inf
        best_params = None

        for combo in combos[:50]:  # Limit combos for speed
            params = StrategyParams()
            for i, k in enumerate(keys):
                setattr(params, k, combo[i])

            bt = Backtester(params=params, initial_capital=initial_capital)

            for sym, data in all_data.items():
                ctx_df = data.get("W1")
                val_df = data.get("D1")
                entry_df = data.get("H4") if data.get("H4") is not None else (data.get("H2") if data.get("H2") is not None else data.get("H1"))

                if ctx_df is None and val_df is not None:
                    ctx_df = resample_to_weekly(val_df)

                if entry_df is None:
                    entry_df = val_df

                if ctx_df is None or val_df is None or entry_df is None:
                    continue

                # Filter to training period
                ctx_train = ctx_df[ctx_df.index <= train_end]
                val_train = val_df[val_df.index <= train_end]
                ent_train = entry_df[entry_df.index <= train_end]

                if len(ctx_train) > 50 and len(val_train) > 50 and len(ent_train) > 50:
                    bt.run(sym, ctx_train, val_train, ent_train)

            result = bt.get_results()
            if isinstance(result, tuple):
                stats, _ = result
                if stats["total_pnl"] > best_pnl and stats["total_trades"] > 5:
                    best_pnl = stats["total_pnl"]
                    best_params = deepcopy(params)

        if best_params is None:
            print(f"    No valid params found for fold {fold}")
            continue

        print(f"    Best IS params: EMA={best_params.ema_fast}/{best_params.ema_mid} | "
              f"ATR_SL={best_params.atr_sl_multiplier} | DC={best_params.donchian_period}")

        # Test on OOS data
        bt_oos = Backtester(params=best_params, initial_capital=initial_capital)

        for sym, data in all_data.items():
            ctx_df = data.get("W1")
            val_df = data.get("D1")
            entry_df = data.get("H4") if data.get("H4") is not None else (data.get("H2") if data.get("H2") is not None else data.get("H1"))

            if ctx_df is None and val_df is not None:
                ctx_df = resample_to_weekly(val_df)
            if entry_df is None:
                entry_df = val_df
            if ctx_df is None or val_df is None or entry_df is None:
                continue

            # Filter to test period
            ctx_test = ctx_df[(ctx_df.index >= test_start) & (ctx_df.index <= test_end)]
            val_test = val_df[(val_df.index >= test_start) & (val_df.index <= test_end)]
            ent_test = entry_df[(entry_df.index >= test_start) & (entry_df.index <= test_end)]

            # Need some history before test period for indicators
            lookback = 200
            ctx_with_history = ctx_df[ctx_df.index <= test_end].tail(len(ctx_test) + lookback)
            val_with_history = val_df[val_df.index <= test_end].tail(len(val_test) + lookback)
            ent_with_history = entry_df[entry_df.index <= test_end].tail(len(ent_test) + lookback)

            if len(ctx_with_history) > 50 and len(val_with_history) > 50 and len(ent_with_history) > 50:
                bt_oos.run(sym, ctx_with_history, val_with_history, ent_with_history)

        result_oos = bt_oos.get_results()
        if isinstance(result_oos, tuple):
            stats_oos, _ = result_oos
            oos_results.append(stats_oos)
            print(f"    OOS: PnL=${stats_oos['total_pnl']:,.0f} | "
                  f"WR={stats_oos['win_rate']:.1f}% | "
                  f"PF={stats_oos['profit_factor']:.2f} | "
                  f"Trades={stats_oos['total_trades']}")

    if oos_results:
        avg_oos_pnl = np.mean([r["total_pnl"] for r in oos_results])
        avg_oos_wr = np.mean([r["win_rate"] for r in oos_results])
        avg_oos_pf = np.mean([r["profit_factor"] for r in oos_results])

        print(f"\n  WALK-FORWARD SUMMARY:")
        print(f"    Average OOS P&L:          ${avg_oos_pnl:,.2f}")
        print(f"    Average OOS Win Rate:      {avg_oos_wr:.1f}%")
        print(f"    Average OOS Profit Factor: {avg_oos_pf:.2f}")

    return oos_results


# ============================================================
# 4. BE MODE COMPARISON
# ============================================================
def compare_be_modes(symbols, initial_capital=100000.0):
    """Compare the two breakeven modes: RR-based vs Pullback-breakout."""
    print("\n" + "=" * 65)
    print("  BREAKEVEN MODE COMPARISON")
    print("=" * 65)

    results = {}

    for mode, mode_name in [("rr", "RR-Based BE (1:1)"), ("pullback", "Pullback Breakout BE")]:
        print(f"\n  Testing: {mode_name}")
        params = StrategyParams()
        params.be_mode = mode

        bt, tested = run_multi_symbol_backtest(symbols, params, initial_capital)
        result = bt.get_results()

        if isinstance(result, tuple):
            stats, trades_df = result
            results[mode] = stats
            print(f"    P&L: ${stats['total_pnl']:,.0f} | WR: {stats['win_rate']:.1f}% | "
                  f"PF: {stats['profit_factor']:.2f} | Avg RR: {stats['avg_rr']:.2f}")

    if len(results) == 2:
        print("\n  COMPARISON:")
        print(f"  {'Metric':<25s} {'RR-Based':>12s} {'Pullback BO':>12s}")
        print(f"  {'-'*25} {'-'*12} {'-'*12}")
        for metric in ["total_pnl", "win_rate", "profit_factor", "avg_rr",
                        "max_drawdown_pct", "total_trades"]:
            v1 = results.get("rr", {}).get(metric, 0)
            v2 = results.get("pullback", {}).get(metric, 0)
            if isinstance(v1, float):
                print(f"  {metric:<25s} {v1:>12.2f} {v2:>12.2f}")
            else:
                print(f"  {metric:<25s} {v1:>12} {v2:>12}")

    return results


# ============================================================
# 5. MARKET REGIME ANALYSIS
# ============================================================
def regime_analysis(trades_df, equity_df=None):
    """Analyze performance across different market conditions."""
    print("\n" + "=" * 65)
    print("  MARKET REGIME ANALYSIS")
    print("=" * 65)

    if trades_df is None or len(trades_df) == 0:
        print("  No trades for analysis.")
        return

    trades_df = trades_df.copy()
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])

    # By year
    trades_df["year"] = trades_df["entry_time"].dt.year
    print("\n  Performance by Year:")
    print(f"  {'Year':<6s} {'Trades':>7s} {'WinRate':>8s} {'AvgRR':>7s} {'PnL':>12s} {'PF':>6s}")
    print(f"  {'-'*6} {'-'*7} {'-'*8} {'-'*7} {'-'*12} {'-'*6}")

    for year, group in trades_df.groupby("year"):
        n = len(group)
        wr = (group["pnl"] > 0).mean() * 100
        avg_rr = group["rr"].mean()
        pnl = group["pnl"].sum()
        gross_win = group[group["pnl"] > 0]["pnl"].sum()
        gross_loss = abs(group[group["pnl"] <= 0]["pnl"].sum())
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        print(f"  {year:<6d} {n:>7d} {wr:>7.1f}% {avg_rr:>+6.2f} ${pnl:>11,.0f} {pf:>5.2f}")

    # By month
    trades_df["month"] = trades_df["entry_time"].dt.month
    print("\n  Performance by Month:")
    for month, group in trades_df.groupby("month"):
        n = len(group)
        wr = (group["pnl"] > 0).mean() * 100
        pnl = group["pnl"].sum()
        print(f"  Month {month:>2d}: {n:>4d} trades | WR: {wr:>5.1f}% | PnL: ${pnl:>10,.0f}")

    # By symbol
    print("\n  Performance by Symbol:")
    print(f"  {'Symbol':<8s} {'Trades':>7s} {'WinRate':>8s} {'AvgRR':>7s} {'PnL':>12s}")
    print(f"  {'-'*8} {'-'*7} {'-'*8} {'-'*7} {'-'*12}")
    for sym, group in trades_df.groupby("symbol"):
        n = len(group)
        wr = (group["pnl"] > 0).mean() * 100
        avg_rr = group["rr"].mean()
        pnl = group["pnl"].sum()
        print(f"  {sym:<8s} {n:>7d} {wr:>7.1f}% {avg_rr:>+6.2f} ${pnl:>11,.0f}")


# ============================================================
# 6. OPTIMIZED PARAMETER SEARCH
# ============================================================
def find_optimal_params(symbols, initial_capital=100000.0, max_combos=100):
    """Find optimal parameters using grid search with key parameters."""
    print("\n" + "=" * 65)
    print("  PARAMETER OPTIMIZATION (Grid Search)")
    print("=" * 65)

    param_grid = {
        "ema_fast": [17, 21, 26],
        "ema_mid": [42, 50, 65],
        "atr_sl_multiplier": [1.25, 1.5, 2.0],
        "atr_trail_multiplier": [2.0, 2.5, 3.0],
        "donchian_period": [15, 20, 25],
        "bbw_squeeze_percentile": [20, 25, 30],
    }

    keys = list(param_grid.keys())
    all_combos = list(itertools.product(*[param_grid[k] for k in keys]))

    # Sample if too many
    if len(all_combos) > max_combos:
        np.random.seed(42)
        indices = np.random.choice(len(all_combos), max_combos, replace=False)
        combos = [all_combos[i] for i in indices]
    else:
        combos = all_combos

    print(f"  Testing {len(combos)} of {len(all_combos)} combinations")

    results_list = []

    for idx, combo in enumerate(combos):
        params = StrategyParams()
        for i, k in enumerate(keys):
            setattr(params, k, combo[i])

        bt, tested = run_multi_symbol_backtest(symbols, params, initial_capital)
        result = bt.get_results()

        if isinstance(result, tuple):
            stats, _ = result
            combo_dict = {keys[i]: combo[i] for i in range(len(keys))}
            combo_dict.update({
                "total_pnl": stats["total_pnl"],
                "win_rate": stats["win_rate"],
                "profit_factor": stats["profit_factor"],
                "max_dd_pct": stats["max_drawdown_pct"],
                "avg_rr": stats["avg_rr"],
                "total_trades": stats["total_trades"],
                "total_return_pct": stats["total_return_pct"],
            })

            # Composite score: profit factor * sqrt(trades) * (1 - abs(dd)/100)
            score = (stats["profit_factor"] *
                     np.sqrt(max(stats["total_trades"], 1)) *
                     (1 - abs(stats["max_drawdown_pct"]) / 100))
            combo_dict["score"] = round(score, 4)
            results_list.append(combo_dict)

        if (idx + 1) % 10 == 0:
            print(f"  Progress: {idx+1}/{len(combos)}")

    if not results_list:
        print("  No valid results found.")
        return None

    # Sort by composite score
    results_list.sort(key=lambda x: x.get("score", 0), reverse=True)

    print(f"\n  TOP 10 PARAMETER COMBINATIONS:")
    print(f"  {'#':>3s} {'EMA_F':>6s} {'EMA_M':>6s} {'ATR_SL':>7s} {'ATR_TR':>7s} "
          f"{'DC':>4s} {'BBW%':>5s} {'PnL':>10s} {'WR%':>6s} {'PF':>5s} {'DD%':>6s} {'Score':>7s}")
    print("  " + "-" * 80)

    for i, r in enumerate(results_list[:10]):
        print(f"  {i+1:>3d} {r['ema_fast']:>6d} {r['ema_mid']:>6d} "
              f"{r['atr_sl_multiplier']:>7.2f} {r['atr_trail_multiplier']:>7.2f} "
              f"{r['donchian_period']:>4d} {r['bbw_squeeze_percentile']:>5.0f} "
              f"${r['total_pnl']:>9,.0f} {r['win_rate']:>5.1f} {r['profit_factor']:>5.2f} "
              f"{r['max_dd_pct']:>5.1f} {r['score']:>7.2f}")

    # Best params
    best = results_list[0]
    print(f"\n  OPTIMAL PARAMETERS:")
    for k in keys:
        print(f"    {k}: {best[k]}")
    print(f"    Score: {best['score']}")

    return results_list


# ============================================================
# MAIN - RUN ALL TESTS
# ============================================================
def main():
    print("=" * 65)
    print("  TREND-FOLLOW PULLBACK STRATEGY")
    print("  STRESS TEST & OPTIMIZATION SUITE")
    print("=" * 65)

    # Use available symbols (those with data in repo or downloaded)
    test_symbols = ALL_SYMBOLS

    # 1. Run base backtest
    print("\n\n" + "#" * 65)
    print("  PHASE 1: BASELINE BACKTEST")
    print("#" * 65)

    base_params = StrategyParams()
    bt_base, symbols_tested = run_multi_symbol_backtest(
        test_symbols, base_params, initial_capital=100000.0
    )

    base_result = bt_base.get_results()
    trades_df = None
    base_stats = None

    if isinstance(base_result, tuple):
        base_stats, trades_df = base_result
        print_results(base_stats, "BASELINE RESULTS")
    else:
        print(f"  Baseline: {base_result}")

    # 2. Monte Carlo stress test
    print("\n\n" + "#" * 65)
    print("  PHASE 2: MONTE CARLO STRESS TEST")
    print("#" * 65)

    mc_results = None
    if trades_df is not None and len(trades_df) > 0:
        mc_results = monte_carlo_stress_test(trades_df, n_simulations=1000)

    # 3. Compare BE modes
    print("\n\n" + "#" * 65)
    print("  PHASE 3: BREAKEVEN MODE COMPARISON")
    print("#" * 65)

    be_results = compare_be_modes(symbols_tested, initial_capital=100000.0)

    # 4. Market regime analysis
    print("\n\n" + "#" * 65)
    print("  PHASE 4: MARKET REGIME ANALYSIS")
    print("#" * 65)

    if trades_df is not None:
        regime_analysis(trades_df)

    # 5. Parameter optimization
    print("\n\n" + "#" * 65)
    print("  PHASE 5: PARAMETER OPTIMIZATION")
    print("#" * 65)

    opt_results = find_optimal_params(symbols_tested, max_combos=50)

    # 6. Save all results
    os.makedirs(RESULTS_DIR, exist_ok=True)

    all_results = {
        "timestamp": datetime.now().isoformat(),
        "symbols_tested": symbols_tested,
        "base_params": base_params.to_dict(),
        "baseline_stats": base_stats,
        "monte_carlo": mc_results,
        "be_comparison": be_results,
    }

    if opt_results:
        all_results["optimization_top10"] = opt_results[:10]
        all_results["optimal_params"] = {k: opt_results[0][k]
                                         for k in ["ema_fast", "ema_mid", "atr_sl_multiplier",
                                                    "atr_trail_multiplier", "donchian_period",
                                                    "bbw_squeeze_percentile"]}

    with open(os.path.join(RESULTS_DIR, "stress_test_results.json"), "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    if trades_df is not None:
        trades_df.to_csv(os.path.join(RESULTS_DIR, "all_trades.csv"), index=False)

    print("\n\n" + "=" * 65)
    print("  ALL TESTS COMPLETE")
    print(f"  Results saved to: {RESULTS_DIR}")
    print("=" * 65)

    # Print final summary
    if base_stats and opt_results:
        print("\n  FINAL SUMMARY:")
        print(f"  Baseline PnL:   ${base_stats['total_pnl']:>12,.2f}")
        print(f"  Baseline WR:     {base_stats['win_rate']:>11.1f}%")
        print(f"  Baseline PF:     {base_stats['profit_factor']:>11.2f}")
        print(f"  Optimized PnL:  ${opt_results[0]['total_pnl']:>12,.0f}")
        print(f"  Optimized WR:    {opt_results[0]['win_rate']:>11.1f}%")
        print(f"  Optimized PF:    {opt_results[0]['profit_factor']:>11.2f}")

        if mc_results:
            print(f"  MC Prob Profit:  {mc_results['prob_profit']:>11.1f}%")
            print(f"  MC Worst DD:     {mc_results['max_dd_worst_pct']:>11.1f}%")


if __name__ == "__main__":
    main()
