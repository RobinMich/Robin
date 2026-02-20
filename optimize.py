#!/usr/bin/env python3
"""
EMA Fractal EA – Parameter Optimizer
=====================================
Tests parameter combinations per asset class and finds optimal settings.
"""

import os, json, itertools
import numpy as np
from backtest import StrategyParams, load_csv, compute_indicators, run_backtest, compute_stats

BASE = os.path.dirname(os.path.abspath(__file__))

# ─── Asset Groups ──────────────────────────────────────────────────────────────
ASSET_GROUPS = {
    "Gold": [
        ("XAUUSD_1D", os.path.join(BASE, "PEPPERSTONE_XAUUSD, 1D.csv")),
    ],
    "Crypto": [
        ("BTCUSD_1D", os.path.join(BASE, "BITSTAMP_BTCUSD, 1D.csv")),
    ],
    "US_Tech_Stocks": [
        ("AAPL_1D",  os.path.join(BASE, "BATS_AAPL, 1D.csv")),
        ("NVDA_1D",  os.path.join(BASE, "BATS_NVDA, 1D.csv")),
        ("TSLA_1D",  os.path.join(BASE, "BATS_TSLA, 1D.csv")),
        ("AMD_1D",   os.path.join(BASE, "BATS_AMD, 1D.csv")),
        ("MSFT_1D",  os.path.join(BASE, "BATS_MSFT, 1D.csv")),
    ],
    "Forex": [
        ("EURJPY_1W", os.path.join(BASE, "TICKMILL_EURJPY, 1W.csv")),
    ],
}

# ─── Parameter Grid ───────────────────────────────────────────────────────────
PARAM_GRID = {
    "ema1_period":  [5, 9],
    "ema2_period":  [21, 30],
    "ema3_period":  [50],
    "ema4_period":  [200],
    "atr_period":   [14],
    "risk_pct":     [1.0, 2.0, 3.0],
    "sl_mode":      ["full", "half"],
    "order_timeout": [20, 30],
    "partial_tp_frac": [0.0, 0.5],
}


def generate_param_combos():
    keys = list(PARAM_GRID.keys())
    vals = list(PARAM_GRID.values())
    for combo in itertools.product(*vals):
        d = dict(zip(keys, combo))
        # Enforce EMA ordering: ema1 < ema2 < ema3 < ema4
        if d["ema1_period"] >= d["ema2_period"]:
            continue
        if d["ema2_period"] >= d["ema3_period"]:
            continue
        if d["ema3_period"] >= d["ema4_period"]:
            continue
        yield d


def score(stats: dict) -> float:
    """Score combining return, drawdown control, and profit factor."""
    if stats["total_trades"] < 10:
        return -999
    ret = stats["return_pct"]
    dd = stats["max_drawdown_pct"]
    pf = stats["profit_factor"]
    wr = stats["win_rate"]
    # Penalize heavy drawdown
    if dd > 30:
        return -999
    # Calmar-like: return / drawdown, weighted by profit factor
    calmar = ret / max(dd, 1.0)
    return calmar * min(pf, 5.0) * (1 + wr / 100)


def optimize_group(group_name: str, assets: list, top_n: int = 5):
    """Find best parameters for an asset group by averaging score across assets."""
    # Pre-load data
    datasets = {}
    for key, path in assets:
        if not os.path.exists(path):
            print(f"  SKIP {key}: file not found")
            continue
        datasets[key] = load_csv(path)

    if not datasets:
        return None

    combos = list(generate_param_combos())
    print(f"\n{'='*80}")
    print(f"Optimizing {group_name} ({len(datasets)} assets, {len(combos)} parameter combinations)")
    print(f"{'='*80}")

    best_results = []

    for idx, pdict in enumerate(combos):
        params = StrategyParams(**pdict)
        group_score = 0
        group_stats = {}

        for key, raw_df in datasets.items():
            df = compute_indicators(raw_df, params)
            trades, final_eq = run_backtest(df, params)
            stats = compute_stats(trades, params.initial_equity, len(df))
            group_stats[key] = stats
            group_score += score(stats)

        avg_score = group_score / len(datasets)
        best_results.append((avg_score, pdict, group_stats))

        if (idx + 1) % 100 == 0:
            print(f"  Progress: {idx+1}/{len(combos)}")

    best_results.sort(key=lambda x: -x[0])

    print(f"\nTop {top_n} parameter sets for {group_name}:")
    print("-" * 80)
    for rank, (sc, pdict, gstats) in enumerate(best_results[:top_n], 1):
        avg_ret = np.mean([s["return_pct"] for s in gstats.values()])
        avg_dd = np.mean([s["max_drawdown_pct"] for s in gstats.values()])
        avg_pf = np.mean([s["profit_factor"] for s in gstats.values()])
        avg_wr = np.mean([s["win_rate"] for s in gstats.values()])
        avg_trades = np.mean([s["total_trades"] for s in gstats.values()])
        print(f"  #{rank}  Score={sc:.2f}  Ret={avg_ret:.1f}%  DD={avg_dd:.1f}%  PF={avg_pf:.2f}  WR={avg_wr:.1f}%  Trades={avg_trades:.0f}")
        print(f"        EMA={pdict['ema1_period']}/{pdict['ema2_period']}/{pdict['ema3_period']}/{pdict['ema4_period']}  "
              f"ATR={pdict['atr_period']}  Risk={pdict['risk_pct']}%  SL={pdict['sl_mode']}  "
              f"OrderTO={pdict['order_timeout']}  PartialTP={pdict['partial_tp_frac']}")
        for key, s in gstats.items():
            print(f"          {key}: {s['total_trades']} trades, {s['win_rate']:.1f}% WR, "
                  f"{s['return_pct']:.1f}% ret, {s['max_drawdown_pct']:.1f}% DD, PF={s['profit_factor']:.2f}")

    return best_results[0] if best_results else None


def main():
    all_best = {}
    for group_name, assets in ASSET_GROUPS.items():
        result = optimize_group(group_name, assets)
        if result:
            sc, pdict, gstats = result
            all_best[group_name] = {
                "score": sc,
                "params": pdict,
                "per_asset": {k: v for k, v in gstats.items()},
            }

    # Save optimization results
    out_path = os.path.join(BASE, "optimization_results.json")
    with open(out_path, "w") as f:
        json.dump(all_best, f, indent=2, default=str)
    print(f"\nOptimization results saved to {out_path}")

    # Print summary
    print(f"\n{'='*80}")
    print("OPTIMIZATION SUMMARY – Best Parameters per Asset Class")
    print(f"{'='*80}")
    for group, data in all_best.items():
        p = data["params"]
        print(f"\n{group}:")
        print(f"  EMA Periods: {p['ema1_period']} / {p['ema2_period']} / {p['ema3_period']} / {p['ema4_period']}")
        print(f"  ATR Period:  {p['atr_period']}")
        print(f"  Risk:        {p['risk_pct']}%")
        print(f"  SL Mode:     {p['sl_mode']}")
        print(f"  Order TO:    {p['order_timeout']} bars")
        print(f"  Partial TP:  {p['partial_tp_frac'] * 100:.0f}%")


if __name__ == "__main__":
    main()
