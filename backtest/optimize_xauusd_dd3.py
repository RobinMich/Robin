#!/usr/bin/env python3
"""
XAUUSD DD Optimizer v3 - Fast targeted optimization.
Phase 1 showed: TF=2, risk=3%, maxpos=5 → PF 4.50, DD -7.4%
Now test ~50 key variations quickly.
"""
import sys, os, io
from contextlib import redirect_stdout
sys.path.insert(0, os.path.dirname(__file__))

from backtester_v4 import StrategyParams, Backtester, load_symbol_data, get_xauusd_params
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

print("Loading data...", flush=True)
with redirect_stdout(io.StringIO()):
    DATA = load_symbol_data("XAUUSD", DATA_DIR)
print("Data loaded.", flush=True)

# Build TF combos
ALL_COMBOS = []
if "W1" in DATA and "D1" in DATA and "H1" in DATA:
    ALL_COMBOS.append(("W1/D1/H1", DATA["W1"], DATA["D1"], DATA["H1"]))
if "W1" in DATA and "D1" in DATA and "H4" in DATA:
    ALL_COMBOS.append(("W1/D1/H4", DATA["W1"], DATA["D1"], DATA["H4"]))
if "W1" in DATA and "H4" in DATA and "H1" in DATA:
    ALL_COMBOS.append(("W1/H4/H1", DATA["W1"], DATA["H4"], DATA["H1"]))
if "D1" in DATA and "H4" in DATA and "H1" in DATA:
    ALL_COMBOS.append(("D1/H4/H1", DATA["D1"], DATA["H4"], DATA["H1"]))


def run_test(params, tf_indices, initial_capital=100_000):
    """Run test with specific TF combo indices."""
    bt = Backtester(params=params, initial_capital=initial_capital)
    with redirect_stdout(io.StringIO()):
        for idx in tf_indices:
            _, ctx, val, entry = ALL_COMBOS[idx]
            bt.run("XAUUSD", ctx, val, entry)

    trades = bt.trades
    if not trades or len(trades) < 5:
        return None

    pnls = [t.pnl for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    max_dd = dd.min()
    dd_idx = np.argmin(dd)
    peak_val = initial_capital + peak[dd_idx]
    dd_pct = (max_dd / peak_val) * 100 if peak_val > 0 else -999

    consec = max_c = 0
    for p in pnls:
        if p < 0:
            consec += 1
            max_c = max(max_c, consec)
        else:
            consec = 0

    gw = sum(winners) if winners else 0
    gl = abs(sum(losers)) if losers else 1
    pf = gw / gl if gl > 0 else 999

    return {
        'trades': len(trades), 'wr': len(winners)/len(trades)*100,
        'pnl': sum(pnls), 'pf': pf, 'dd_pct': dd_pct, 'max_dd': max_dd,
        'consec': max_c, 'final': initial_capital + sum(pnls),
    }


def main():
    print("=" * 100, flush=True)

    # First: test each individual TF combo to find the best ones
    print("\n--- Individual TF combos ---", flush=True)
    base = get_xauusd_params()
    base.risk_percent = 3.0
    base.max_positions = 5

    for i, (name, _, _, _) in enumerate(ALL_COMBOS):
        r = run_test(base, [i])
        if r:
            print(f"  Combo {i} ({name}): {r['trades']} trades, WR {r['wr']:.0f}%, "
                  f"PnL ${r['pnl']:,.0f}, PF {r['pf']:.2f}, DD {r['dd_pct']:.1f}%", flush=True)

    # Test each pair of combos
    print("\n--- Pairs of TF combos ---", flush=True)
    pairs = [(0,1), (0,2), (0,3), (1,2), (1,3), (2,3)]
    best_pair = None
    best_pair_score = 0
    for i, j in pairs:
        r = run_test(base, [i, j])
        if r:
            dd_pen = min(1.0, -25.0 / r['dd_pct']) if r['dd_pct'] < -1 else 1.0
            score = r['pnl'] * dd_pen * (r['pf'] ** 0.5)
            if score > best_pair_score:
                best_pair_score = score
                best_pair = (i, j)
            print(f"  Pair ({i},{j}): {r['trades']} trades, WR {r['wr']:.0f}%, "
                  f"PnL ${r['pnl']:,.0f}, PF {r['pf']:.2f}, DD {r['dd_pct']:.1f}%, Score {score:,.0f}", flush=True)

    print(f"\nBest pair: {best_pair}", flush=True)

    # Now optimize key params for the best pair and TF=2 (first 2 combos)
    print("\n--- Optimizing key params for best configs ---", flush=True)

    test_configs = [
        # (description, tf_indices)
        ("best_pair", list(best_pair) if best_pair else [0,1]),
        ("first_2", [0, 1]),
    ]

    results = []

    for desc, tf_idx in test_configs:
        for risk in [2.0, 3.0, 4.0, 5.0]:
            for mom_min in [35, 45, 55]:
                for pb_atr in [2.5, 3.5, 4.5]:
                    for sl_mult in [3.0, 3.5, 4.0]:
                        p = get_xauusd_params()
                        p.risk_percent = risk
                        p.max_positions = 5
                        p.mom_score_min = mom_min
                        p.pb_atr_buffer = pb_atr
                        p.atr_sl_multiplier = sl_mult

                        r = run_test(p, tf_idx)
                        if r:
                            r['cfg'] = f"{desc} r={risk} mom={mom_min} pb={pb_atr} sl={sl_mult}"
                            dd_pen = min(1.0, -25.0 / r['dd_pct']) if r['dd_pct'] < -1 else 1.0
                            r['score'] = r['pnl'] * dd_pen * (r['pf'] ** 0.5)
                            results.append(r)

    print(f"  Tested {len(results)} configs", flush=True)

    results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n{'='*110}")
    print(f"TOP 20 BY SCORE:")
    print(f"{'Config':<55} {'Tr':>4} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3} {'Score':>14}")
    print("-" * 110)
    for r in results[:20]:
        print(f"{r['cfg']:<55} {r['trades']:>4} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd_pct']:>6.1f}% {r['consec']:>3} {r['score']:>14,.0f}")

    # Safe configs
    safe = [r for r in results if r['dd_pct'] > -20]
    safe.sort(key=lambda x: x['pnl'], reverse=True)
    print(f"\n{'='*110}")
    print(f"TOP 10 WITH DD < 20% (by PnL):")
    print(f"{'Config':<55} {'Tr':>4} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3}")
    print("-" * 110)
    for r in safe[:10]:
        print(f"{r['cfg']:<55} {r['trades']:>4} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd_pct']:>6.1f}% {r['consec']:>3}")

    # Also test reducing to just 1 TF combo with higher risk
    print(f"\n--- Single best combo with higher risk ---", flush=True)
    for i in range(4):
        for risk in [3.0, 4.0, 5.0]:
            for mom_min in [35, 45, 55]:
                p = get_xauusd_params()
                p.risk_percent = risk
                p.max_positions = 5
                p.mom_score_min = mom_min
                r = run_test(p, [i])
                if r:
                    dd_pen = min(1.0, -25.0 / r['dd_pct']) if r['dd_pct'] < -1 else 1.0
                    score = r['pnl'] * dd_pen * (r['pf'] ** 0.5)
                    name = ALL_COMBOS[i][0]
                    print(f"  {name} r={risk} mom={mom_min}: {r['trades']} tr, WR {r['wr']:.0f}%, "
                          f"PnL ${r['pnl']:,.0f}, PF {r['pf']:.2f}, DD {r['dd_pct']:.1f}%, Score {score:,.0f}", flush=True)


if __name__ == "__main__":
    main()
