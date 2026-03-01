#!/usr/bin/env python3
"""Final optimization: combine best findings + fix symbol coverage."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester import (
    StrategyParams, Backtester, run_multi_symbol_backtest,
    print_results, ALL_SYMBOLS
)
from optimizer import monte_carlo_stress_test, regime_analysis

# Best findings from quick_tune:
# - Pullback BE mode = best WR (62.4%) and PF (2.74)
# - Wider pullback + lower ADX = more trades
# - EMA 13/34 = more symbols (5)
# - Need to reduce EMA slow to get more symbol coverage

configs = {
    "V1_PB_BE_Wide": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,  # shorter slow EMA
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=15,
        be_mode='pullback',
        atr_trail_multiplier=2.5, trail_start_rr=2.0,
    ),
    "V2_EMA13_PB_BE": StrategyParams(
        ema_fast=13, ema_mid=34, ema_slow=100,
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=15,
        be_mode='pullback',
        atr_trail_multiplier=2.5, trail_start_rr=2.0,
    ),
    "V3_Relaxed_PB_BE": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        pb_atr_buffer=1.2, bbw_squeeze_percentile=50.0,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        volume_multiplier=1.0, donchian_period=12,
        be_mode='pullback',
        atr_trail_multiplier=2.0, trail_start_rr=1.5,
        require_bullish_bar=False,
    ),
    "V4_MaxSymbols": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        pb_atr_buffer=1.5, bbw_squeeze_percentile=60.0,
        adx_threshold_context=12.0, adx_threshold_validation=8.0,
        volume_multiplier=1.0, donchian_period=10,
        be_mode='pullback',
        atr_trail_multiplier=2.5, trail_start_rr=2.0,
        require_bullish_bar=False,
    ),
    "V5_Balanced": StrategyParams(
        ema_fast=17, ema_mid=42, ema_slow=100,
        pb_atr_buffer=1.0, bbw_squeeze_percentile=45.0,
        adx_threshold_context=16.0, adx_threshold_validation=10.0,
        volume_multiplier=1.05, donchian_period=14,
        be_mode='pullback',
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.5,
        trail_start_rr=1.8, be_rr_ratio=1.0,
    ),
    "V6_AggressiveTrail_PB": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=15,
        be_mode='pullback',
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        trail_start_rr=1.5,
    ),
}

print("=" * 80)
print("  FINAL OPTIMIZATION - FINDING BEST CONFIGURATION")
print("=" * 80)

all_results = {}

for name, params in configs.items():
    print(f"\n{'='*80}\n  CONFIG: {name}\n{'='*80}")
    bt, tested = run_multi_symbol_backtest(ALL_SYMBOLS, params, initial_capital=100000.0)
    result = bt.get_results()

    if isinstance(result, tuple):
        stats, trades_df = result
        n_syms = trades_df["symbol"].nunique()
        sym_list = sorted(trades_df["symbol"].unique().tolist())
        all_results[name] = {"stats": stats, "trades_df": trades_df, "params": params,
                             "n_syms": n_syms, "sym_list": sym_list}
        print(f"\n  >> {name}: {stats['total_trades']} trades | {n_syms} symbols: {sym_list}")
        print(f"     WR={stats['win_rate']:.1f}% | PF={stats['profit_factor']:.2f} | "
              f"Return={stats['total_return_pct']:.1f}% | MaxDD={stats['max_drawdown_pct']:.1f}%")

# Summary
print(f"\n\n{'='*80}")
print("  FINAL COMPARISON")
print(f"{'='*80}")
print(f"  {'Config':<22s} {'Trades':>6s} {'Syms':>5s} {'WR%':>6s} {'PF':>6s} {'AvgRR':>6s} {'Return%':>8s} {'MaxDD%':>7s}")
print(f"  {'-'*22} {'-'*6} {'-'*5} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*7}")

for name, r in all_results.items():
    s = r["stats"]
    print(f"  {name:<22s} {s['total_trades']:>6d} {r['n_syms']:>5d} {s['win_rate']:>5.1f}% "
          f"{s['profit_factor']:>5.2f} {s['avg_rr']:>+5.2f} {s['total_return_pct']:>7.1f}% "
          f"{s['max_drawdown_pct']:>6.1f}%")

# Find the best by composite score
best_name = None
best_score = -999
for name, r in all_results.items():
    s = r["stats"]
    # Score: high PF, reasonable DD, decent trade count, high symbol coverage
    import numpy as np
    score = (s["profit_factor"] * np.sqrt(s["total_trades"]) *
             (1 - abs(s["max_drawdown_pct"]) / 100) *
             np.sqrt(r["n_syms"]))
    if score > best_score:
        best_score = score
        best_name = name

print(f"\n  BEST CONFIG: {best_name} (composite score: {best_score:.2f})")

# Run Monte Carlo on best
best = all_results[best_name]
print_results(best["stats"], f"BEST CONFIG: {best_name}")

print(f"\n  Symbols trading: {best['sym_list']}")
print(f"\n  Parameters:")
for k, v in best["params"].to_dict().items():
    print(f"    {k}: {v}")

# Monte Carlo stress test on best
mc = monte_carlo_stress_test(best["trades_df"], n_simulations=2000)

# Regime analysis on best
regime_analysis(best["trades_df"])

# Per-symbol breakdown
print(f"\n  PER-SYMBOL BREAKDOWN (BEST):")
print(f"  {'Symbol':<8s} {'Trades':>7s} {'WR%':>7s} {'AvgRR':>7s} {'PnL':>12s}")
print(f"  {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*12}")
for sym in best["sym_list"]:
    sym_trades = best["trades_df"][best["trades_df"]["symbol"] == sym]
    n = len(sym_trades)
    wr = (sym_trades["pnl"] > 0).mean() * 100
    avg_rr = sym_trades["rr"].mean()
    pnl = sym_trades["pnl"].sum()
    print(f"  {sym:<8s} {n:>7d} {wr:>6.1f}% {avg_rr:>+6.2f} ${pnl:>11,.0f}")

# Save best params
import json
results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(results_dir, exist_ok=True)

best_config = {
    "best_config_name": best_name,
    "params": best["params"].to_dict(),
    "stats": best["stats"],
    "monte_carlo": mc,
    "symbols_trading": best["sym_list"],
}
with open(os.path.join(results_dir, "best_config.json"), "w") as f:
    json.dump(best_config, f, indent=2, default=str)

best["trades_df"].to_csv(os.path.join(results_dir, "best_trades.csv"), index=False)
print(f"\n  Best config saved to: {results_dir}/best_config.json")
