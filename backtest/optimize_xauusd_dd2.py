#!/usr/bin/env python3
"""
XAUUSD DD Optimizer v2 - Targeted optimization based on Phase 1 findings.
Best from Phase 1: TF=2, risk=3%, maxpos=5 → PF 4.50, DD -7.4%
Now fine-tune entry filters for this config.
"""

import sys, os, io, itertools
from contextlib import redirect_stdout
sys.path.insert(0, os.path.dirname(__file__))

from backtester_v4 import StrategyParams, Backtester, load_symbol_data, get_xauusd_params
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Load data once
print("Loading data...")
with redirect_stdout(io.StringIO()):
    DATA = load_symbol_data("XAUUSD", DATA_DIR)
print("Data loaded.")

# Build all TF combos
ALL_COMBOS = []
if "W1" in DATA and "D1" in DATA and "H1" in DATA:
    ALL_COMBOS.append(("W1/D1/H1", DATA["W1"], DATA["D1"], DATA["H1"]))
if "W1" in DATA and "D1" in DATA and "H4" in DATA:
    ALL_COMBOS.append(("W1/D1/H4", DATA["W1"], DATA["D1"], DATA["H4"]))
if "W1" in DATA and "H4" in DATA and "H1" in DATA:
    ALL_COMBOS.append(("W1/H4/H1", DATA["W1"], DATA["H4"], DATA["H1"]))
if "D1" in DATA and "H4" in DATA and "H1" in DATA:
    ALL_COMBOS.append(("D1/H4/H1", DATA["D1"], DATA["H4"], DATA["H1"]))


def run_test(params, tf_passes=2, initial_capital=100_000):
    tf_combos = ALL_COMBOS[:tf_passes]
    bt = Backtester(params=params, initial_capital=initial_capital)
    with redirect_stdout(io.StringIO()):
        for _, ctx, val, entry in tf_combos:
            bt.run("XAUUSD", ctx, val, entry)

    trades = bt.trades
    if not trades or len(trades) < 5:
        return None

    pnls = [t.pnl for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    equity_curve = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = equity_curve - peak
    max_dd = drawdowns.min()
    dd_idx = np.argmin(drawdowns)
    peak_val = initial_capital + peak[dd_idx]
    max_dd_pct = (max_dd / peak_val) * 100 if peak_val > 0 else -999

    consec = 0
    max_consec = 0
    for p in pnls:
        if p < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    gross_win = sum(winners) if winners else 0
    gross_loss = abs(sum(losers)) if losers else 1
    pf = gross_win / gross_loss if gross_loss > 0 else 999

    return {
        'trades': len(trades),
        'wr': len(winners) / len(trades) * 100,
        'pnl': sum(pnls),
        'pf': pf,
        'dd_pct': max_dd_pct,
        'max_dd': max_dd,
        'consec': max_consec,
        'final': initial_capital + sum(pnls),
    }


def make_params(risk, max_pos, mom_min, pb_atr, sl_mult, be_rr, trail_mult=2.5,
                tp1_rr=2.5, tp2_rr=5.0, dyn_max=2.0):
    p = get_xauusd_params()
    p.risk_percent = risk
    p.max_positions = max_pos
    p.mom_score_min = mom_min
    p.pb_atr_buffer = pb_atr
    p.atr_sl_multiplier = sl_mult
    p.be_rr_ratio = be_rr
    p.atr_trail_multiplier = trail_mult
    p.tp1_rr = tp1_rr
    p.tp2_rr = tp2_rr
    p.dyn_risk_max_multi = dyn_max
    return p


def main():
    print("=" * 90)
    print("XAUUSD DD OPTIMIZER v2 - Targeted")
    print("=" * 90)

    results = []

    # Test configs based on Phase 1 best: TF=2, risk=3-4%, maxpos=3-5
    # Also test TF=1 (just the best single combo)
    configs = [
        # (tf, risk, maxpos)
        (2, 3.0, 5),   # Phase 1 winner: PF 4.50, DD -7.4%
        (2, 4.0, 5),   # Phase 1 #7: PF 3.07, DD -13.2%
        (2, 4.0, 3),   # Phase 1 #9: PF 3.29, DD -9.0%
        (2, 3.0, 3),   # Phase 1 #12: PF 3.68, DD -6.8%
        (1, 3.0, 5),   # Single best TF combo
        (1, 4.0, 5),
        (1, 5.0, 5),
        (3, 3.0, 5),   # 3-pass
    ]

    # Fine-tune: mom_min, pb_atr, sl_mult, be_rr
    mom_mins = [35, 40, 45, 50, 55, 60]
    pb_atrs = [2.0, 2.5, 3.0, 3.5, 4.0]
    sl_mults = [2.5, 3.0, 3.5, 4.0]
    be_rrs = [1.5, 2.0, 2.5, 3.0]

    total = len(configs) * len(mom_mins) * len(pb_atrs) * len(sl_mults) * len(be_rrs)
    print(f"Testing {total} combinations...")

    count = 0
    for tf, risk, max_pos in configs:
        for mom_min, pb_atr, sl_mult, be_rr in itertools.product(mom_mins, pb_atrs, sl_mults, be_rrs):
            count += 1
            if count % 200 == 0:
                print(f"  Progress: {count}/{total} ({count*100//total}%)")

            p = make_params(risk, max_pos, mom_min, pb_atr, sl_mult, be_rr)
            r = run_test(p, tf_passes=tf)
            if r:
                r['cfg'] = f"TF={tf} r={risk} mp={max_pos} mom={mom_min} pb={pb_atr} sl={sl_mult} be={be_rr}"
                r['tf'] = tf
                r['risk'] = risk
                r['max_pos'] = max_pos
                r['mom_min'] = mom_min
                r['pb_atr'] = pb_atr
                r['sl_mult'] = sl_mult
                r['be_rr'] = be_rr

                # Score: PnL * DD penalty * sqrt(PF)
                dd_pen = min(1.0, -25.0 / r['dd_pct']) if r['dd_pct'] < -1 else 1.0
                r['score'] = r['pnl'] * dd_pen * (r['pf'] ** 0.5)
                results.append(r)

    results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n{'='*120}")
    print(f"TOP 30 RESULTS (by score = PnL * DD_penalty * sqrt(PF)):")
    print(f"{'Config':<60} {'Tr':>4} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3} {'Score':>14}")
    print("-" * 120)
    for r in results[:30]:
        print(f"{r['cfg']:<60} {r['trades']:>4} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd_pct']:>6.1f}% {r['consec']:>3} {r['score']:>14,.0f}")

    # Show best with DD < 25%
    safe = [r for r in results if r['dd_pct'] > -25]
    safe.sort(key=lambda x: x['pnl'], reverse=True)
    print(f"\n{'='*120}")
    print(f"TOP 20 WITH DD < 25% (by PnL):")
    print(f"{'Config':<60} {'Tr':>4} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3}")
    print("-" * 120)
    for r in safe[:20]:
        print(f"{r['cfg']:<60} {r['trades']:>4} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd_pct']:>6.1f}% {r['consec']:>3}")

    # Best with DD < 15%
    very_safe = [r for r in results if r['dd_pct'] > -15]
    very_safe.sort(key=lambda x: x['pnl'], reverse=True)
    print(f"\n{'='*120}")
    print(f"TOP 10 WITH DD < 15% (by PnL):")
    print(f"{'Config':<60} {'Tr':>4} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3}")
    print("-" * 120)
    for r in very_safe[:10]:
        print(f"{r['cfg']:<60} {r['trades']:>4} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd_pct']:>6.1f}% {r['consec']:>3}")

    if results:
        best = results[0]
        print(f"\n{'='*90}")
        print(f"RECOMMENDATION:")
        print(f"  {best['cfg']}")
        print(f"  {best['trades']} trades, {best['wr']:.1f}% WR, PF {best['pf']:.2f}")
        print(f"  PnL: ${best['pnl']:,.0f}, DD: {best['dd_pct']:.1f}%, Consec Loss: {best['consec']}")
        print(f"  Final Capital: ${best['final']:,.0f}")


if __name__ == "__main__":
    main()
