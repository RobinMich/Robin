#!/usr/bin/env python3
"""Quick parameter tuning test - find params that generate trades across all symbols."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester import (
    StrategyParams, Backtester, run_multi_symbol_backtest,
    print_results, ALL_SYMBOLS
)

configs = {
    "Baseline": StrategyParams(),
    "Wider_Pullback": StrategyParams(
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=15
    ),
    "Relaxed_Squeeze": StrategyParams(
        pb_atr_buffer=0.8, bbw_squeeze_percentile=50.0,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        volume_multiplier=1.0, donchian_period=15,
        require_bullish_bar=False
    ),
    "Aggressive_Trail": StrategyParams(
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=15,
        atr_trail_multiplier=2.0, trail_start_rr=1.5,
        be_rr_ratio=1.0
    ),
    "EMA_13_34": StrategyParams(
        ema_fast=13, ema_mid=34,
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=15
    ),
    "Conservative_RR": StrategyParams(
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=20,
        atr_sl_multiplier=2.0, atr_trail_multiplier=3.0,
        trail_start_rr=2.0, be_rr_ratio=1.2
    ),
    "Pullback_BE": StrategyParams(
        pb_atr_buffer=1.0, bbw_squeeze_percentile=40.0,
        adx_threshold_context=18.0, adx_threshold_validation=12.0,
        volume_multiplier=1.1, donchian_period=15,
        be_mode='pullback'
    ),
}

print("=" * 80)
print("  QUICK PARAMETER TUNING")
print("=" * 80)

results_summary = []

for name, params in configs.items():
    print(f"\n{'='*80}")
    print(f"  CONFIG: {name}")
    print(f"{'='*80}")

    bt, tested = run_multi_symbol_backtest(ALL_SYMBOLS, params, initial_capital=100000.0)
    result = bt.get_results()

    if isinstance(result, tuple):
        stats, trades_df = result
        n_syms_with_trades = trades_df["symbol"].nunique()
        results_summary.append({
            "name": name,
            "trades": stats["total_trades"],
            "symbols": n_syms_with_trades,
            "win_rate": stats["win_rate"],
            "pnl": stats["total_pnl"],
            "pf": stats["profit_factor"],
            "avg_rr": stats["avg_rr"],
            "max_dd": stats["max_drawdown_pct"],
            "return": stats["total_return_pct"],
        })
        print(f"\n  >> {name}: {stats['total_trades']} trades across {n_syms_with_trades} symbols | "
              f"WR={stats['win_rate']:.1f}% | PF={stats['profit_factor']:.2f} | "
              f"Return={stats['total_return_pct']:.1f}% | MaxDD={stats['max_drawdown_pct']:.1f}%")
    else:
        results_summary.append({"name": name, "trades": 0, "error": True})
        print(f"\n  >> {name}: No trades")

print(f"\n\n{'='*80}")
print("  SUMMARY COMPARISON")
print(f"{'='*80}")
print(f"  {'Config':<20s} {'Trades':>6s} {'Syms':>5s} {'WR%':>6s} {'PF':>6s} {'AvgRR':>6s} {'Return%':>8s} {'MaxDD%':>7s}")
print(f"  {'-'*20} {'-'*6} {'-'*5} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*7}")

for r in results_summary:
    if "error" not in r:
        print(f"  {r['name']:<20s} {r['trades']:>6d} {r['symbols']:>5d} {r['win_rate']:>5.1f}% "
              f"{r['pf']:>5.2f} {r['avg_rr']:>+5.2f} {r['return']:>7.1f}% {r['max_dd']:>6.1f}%")
