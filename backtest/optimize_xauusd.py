#!/usr/bin/env python3
"""
XAUUSD (Gold) Strategy Optimization
====================================
Gold behaves differently from stocks:
- Stronger trending phases (safe haven + inflation hedge)
- Can trend both directions (but we're long-only per strategy)
- Higher volatility, larger ATR
- Volume data from futures may differ
- 24h market (different session dynamics)

We test multiple parameter sets to find the best for XAUUSD.
"""

import sys, os, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester import (
    StrategyParams, Backtester, run_multi_symbol_backtest,
    print_results, load_symbol_data, add_indicators,
    resample_to_weekly
)
from optimizer import monte_carlo_stress_test, regime_analysis


def run_single_symbol_bt(symbol, params, initial_capital=100000.0):
    """Run backtest on a single symbol and return results."""
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    bt = Backtester(params=params, initial_capital=initial_capital)

    data = load_symbol_data(symbol, data_dir)
    ctx_df = data.get("W1")
    val_df = data.get("D1")
    entry_df = data.get("H4")
    if entry_df is None:
        entry_df = data.get("H2")
    if entry_df is None:
        entry_df = data.get("H1")

    if ctx_df is None and val_df is not None:
        ctx_df = resample_to_weekly(val_df)

    if entry_df is None:
        entry_df = val_df

    if ctx_df is None or val_df is None or entry_df is None:
        print(f"  Missing data for {symbol}")
        return None, None

    bt.run(symbol, ctx_df, val_df, entry_df)
    return bt.get_results()


# ============================================================
# XAUUSD-SPECIFIC PARAMETER CONFIGURATIONS
# ============================================================
# Gold has unique characteristics:
# - Strong multi-year trends (2019-2020, 2023-2024 bull runs)
# - Pullbacks tend to be deeper than stocks (more volatile)
# - BBW squeeze is very relevant (gold consolidates before breakouts)
# - Volume from futures is less reliable as a filter

configs = {
    # Current stock-optimized params as baseline
    "Stock_Optimal": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.05, trail_start_rr=1.5,
        pb_atr_buffer=1.0, be_mode='pullback',
        require_bullish_bar=True,
    ),

    # Gold-specific: wider pullback zone (gold pulls back more)
    "Gold_Wide_PB": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=2.0, atr_trail_multiplier=2.5,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.0,  # less strict volume for futures
        trail_start_rr=1.5, pb_atr_buffer=1.5,
        be_mode='pullback', require_bullish_bar=True,
    ),

    # Faster EMAs for gold (catches trend changes quicker)
    "Gold_Fast_EMA": StrategyParams(
        ema_fast=13, ema_mid=34, ema_slow=89,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        bbw_squeeze_percentile=40.0, donchian_period=12,
        volume_multiplier=1.0, trail_start_rr=1.5,
        pb_atr_buffer=1.2, be_mode='pullback',
        require_bullish_bar=True,
    ),

    # Wider trailing for gold's bigger moves
    "Gold_Wide_Trail": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=2.0, atr_trail_multiplier=3.0,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.0, trail_start_rr=2.0,
        pb_atr_buffer=1.2, be_mode='pullback',
        require_bullish_bar=True,
    ),

    # Relaxed entry for more gold signals
    "Gold_Relaxed": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=12.0, adx_threshold_validation=8.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        bbw_squeeze_percentile=55.0, donchian_period=12,
        volume_multiplier=1.0, trail_start_rr=1.5,
        pb_atr_buffer=1.5, be_mode='pullback',
        require_bullish_bar=False,
    ),

    # RR-based BE for gold (compare with pullback BE)
    "Gold_RR_BE": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=2.0, atr_trail_multiplier=2.5,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.0, trail_start_rr=2.0,
        pb_atr_buffer=1.2, be_mode='rr', be_rr_ratio=1.0,
        require_bullish_bar=True,
    ),

    # Conservative gold: tighter filters, wider stops
    "Gold_Conservative": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=20.0, adx_threshold_validation=15.0,
        atr_sl_multiplier=2.5, atr_trail_multiplier=3.0,
        bbw_squeeze_percentile=35.0, donchian_period=20,
        volume_multiplier=1.0, trail_start_rr=2.0,
        pb_atr_buffer=1.0, be_mode='pullback',
        require_bullish_bar=True,
    ),

    # Aggressive gold: looser everything, more trades
    "Gold_Aggressive": StrategyParams(
        ema_fast=13, ema_mid=34, ema_slow=89,
        adx_threshold_context=10.0, adx_threshold_validation=8.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        bbw_squeeze_percentile=60.0, donchian_period=10,
        volume_multiplier=1.0, trail_start_rr=1.2,
        pb_atr_buffer=2.0, be_mode='pullback',
        require_bullish_bar=False, max_positions=3,
    ),
}

print("=" * 70)
print("  XAUUSD (GOLD) STRATEGY OPTIMIZATION")
print("=" * 70)

all_results = {}

for name, params in configs.items():
    print(f"\n{'='*70}\n  {name}\n{'='*70}")

    result = run_single_symbol_bt("XAUUSD", params)

    if result is not None and isinstance(result, tuple):
        stats, trades_df = result
        n_trades = stats["total_trades"]

        all_results[name] = {
            "stats": stats, "trades_df": trades_df, "params": params
        }

        print(f"\n  >> {name}: {n_trades} trades | "
              f"WR={stats['win_rate']:.1f}% | PF={stats['profit_factor']:.2f} | "
              f"Return={stats['total_return_pct']:.1f}% | "
              f"MaxDD={stats['max_drawdown_pct']:.1f}% | "
              f"AvgRR={stats['avg_rr']:.2f}")
    else:
        print(f"  >> {name}: No trades or error")

# ============================================================
# SUMMARY
# ============================================================
print(f"\n\n{'='*70}")
print("  XAUUSD OPTIMIZATION SUMMARY")
print(f"{'='*70}")
print(f"  {'Config':<22s} {'Trades':>6s} {'WR%':>6s} {'PF':>6s} {'AvgRR':>6s} {'Return%':>8s} {'MaxDD%':>7s}")
print(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*7}")

for name, r in all_results.items():
    s = r["stats"]
    if s["total_trades"] > 0:
        print(f"  {name:<22s} {s['total_trades']:>6d} {s['win_rate']:>5.1f}% "
              f"{s['profit_factor']:>5.2f} {s['avg_rr']:>+5.2f} "
              f"{s['total_return_pct']:>7.1f}% {s['max_drawdown_pct']:>6.1f}%")

# Find best by composite score
best_name = None
best_score = -999
for name, r in all_results.items():
    s = r["stats"]
    if s["total_trades"] < 3:
        continue
    score = (s["profit_factor"] *
             np.sqrt(max(s["total_trades"], 1)) *
             (1 - abs(s["max_drawdown_pct"]) / 100) *
             (s["win_rate"] / 50))
    if score > best_score:
        best_score = score
        best_name = name

if best_name:
    best = all_results[best_name]
    print(f"\n  BEST CONFIG: {best_name} (score: {best_score:.2f})")
    print_results(best["stats"], f"XAUUSD BEST: {best_name}")

    # Monte Carlo
    if best["trades_df"] is not None and len(best["trades_df"]) > 0:
        mc = monte_carlo_stress_test(best["trades_df"], n_simulations=2000)

    # Save
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(results_dir, exist_ok=True)

    xau_output = {
        "symbol": "XAUUSD",
        "best_config": best_name,
        "parameters": best["params"].to_dict(),
        "performance": best["stats"],
        "monte_carlo": mc if 'mc' in dir() else None,
    }
    with open(os.path.join(results_dir, "xauusd_optimized.json"), "w") as f:
        json.dump(xau_output, f, indent=2, default=str)

    best["trades_df"].to_csv(
        os.path.join(results_dir, "xauusd_trades.csv"), index=False
    )

    print(f"\n  Results saved to: {results_dir}/xauusd_optimized.json")

    # Now run combined: all stocks + XAUUSD
    print(f"\n\n{'='*70}")
    print("  COMBINED BACKTEST: ALL STOCKS + XAUUSD")
    print(f"{'='*70}")

    from backtester import ALL_SYMBOLS
    combined_symbols = ALL_SYMBOLS + ["XAUUSD"]

    bt_combined, tested = run_multi_symbol_backtest(
        combined_symbols, best["params"], initial_capital=100000.0
    )
    combined_result = bt_combined.get_results()
    if isinstance(combined_result, tuple):
        combined_stats, combined_trades = combined_result
        print_results(combined_stats, "COMBINED: STOCKS + XAUUSD")

        n_syms = combined_trades["symbol"].nunique()
        sym_list = sorted(combined_trades["symbol"].unique().tolist())
        print(f"\n  Symbols ({n_syms}): {sym_list}")

        print(f"\n  PER-SYMBOL BREAKDOWN:")
        print(f"  {'Symbol':<8s} {'Trades':>7s} {'WR%':>7s} {'AvgRR':>7s} {'BestRR':>7s} {'PnL':>12s}")
        print(f"  {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*12}")
        for sym in sym_list:
            st = combined_trades[combined_trades["symbol"] == sym]
            n = len(st)
            wr = (st["pnl"] > 0).mean() * 100
            avg_rr = st["rr"].mean()
            best_rr = st["rr"].max()
            pnl = st["pnl"].sum()
            print(f"  {sym:<8s} {n:>7d} {wr:>6.1f}% {avg_rr:>+6.2f} {best_rr:>+6.2f} ${pnl:>11,.0f}")

        # Monte Carlo on combined
        mc_combined = monte_carlo_stress_test(combined_trades, n_simulations=2000)

        combined_output = {
            "strategy": "TrendPullbackEA v2.1 (Stocks + Gold)",
            "best_xauusd_config": best_name,
            "parameters": best["params"].to_dict(),
            "combined_performance": combined_stats,
            "combined_monte_carlo": mc_combined,
            "symbols_trading": sym_list,
        }
        with open(os.path.join(results_dir, "combined_stocks_gold.json"), "w") as f:
            json.dump(combined_output, f, indent=2, default=str)
        combined_trades.to_csv(
            os.path.join(results_dir, "combined_trades.csv"), index=False
        )
        print(f"\n  Combined results saved to: {results_dir}/combined_stocks_gold.json")
else:
    print("\n  No valid XAUUSD configurations found - all had too few trades.")
    print("  Gold may need a different strategy approach for this data period.")
