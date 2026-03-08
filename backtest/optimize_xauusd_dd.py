#!/usr/bin/env python3
"""
XAUUSD Drawdown Optimizer
==========================
Problem: Current XAUUSD preset has -125% DD from peak (goes negative!).
  - 32% WR, 27 consecutive losses
  - 5% risk, 10 max positions, 4 TF passes = massive exposure

Strategy: Test parameter combinations to find best DD/profit trade-off.
Key levers:
  1. risk_percent (1-5%)
  2. max_positions (1-5)
  3. TF passes (1-4)
  4. mom_score_min (35-70)
  5. pb_atr_buffer (2.0-4.0)
  6. atr_sl_multiplier (2.5-4.0)
  7. be_rr_ratio (1.5-3.0)
"""

import sys
import os
import itertools
sys.path.insert(0, os.path.dirname(__file__))

from backtester_v4 import (
    StrategyParams, Backtester, load_symbol_data, get_xauusd_params
)
import numpy as np
import io
from contextlib import redirect_stdout

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

_cached_data = None

def _get_data():
    global _cached_data
    if _cached_data is None:
        _cached_data = load_symbol_data("XAUUSD", DATA_DIR)
    return _cached_data


def run_xauusd_test(params, tf_passes=4, initial_capital=100_000):
    """Run XAUUSD backtest with given params and number of TF passes."""
    data = _get_data()

    # Build TF combos based on pass count
    all_combos = []
    if "W1" in data and "D1" in data and "H1" in data:
        all_combos.append(("W1/D1/H1", data["W1"], data["D1"], data["H1"]))
    if "W1" in data and "D1" in data and "H4" in data:
        all_combos.append(("W1/D1/H4", data["W1"], data["D1"], data["H4"]))
    if "W1" in data and "H4" in data and "H1" in data:
        all_combos.append(("W1/H4/H1", data["W1"], data["H4"], data["H1"]))
    if "D1" in data and "H4" in data and "H1" in data:
        all_combos.append(("D1/H4/H1", data["D1"], data["H4"], data["H1"]))

    tf_combos = all_combos[:tf_passes]

    bt = Backtester(params=params, initial_capital=initial_capital)

    with redirect_stdout(io.StringIO()):
        for combo_name, ctx, val, entry in tf_combos:
            bt.run("XAUUSD", ctx, val, entry)

    trades = bt.trades
    if not trades:
        return None

    # Calculate stats
    pnls = [t.pnl for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    equity_curve = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = equity_curve - peak
    max_dd = drawdowns.min()
    peak_at_dd = peak[np.argmin(drawdowns)]
    max_dd_pct = (max_dd / (initial_capital + peak_at_dd)) * 100 if peak_at_dd > 0 else -999

    # Consecutive losses
    max_consec = 0
    consec = 0
    for p in pnls:
        if p < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    total_pnl = sum(pnls)
    gross_win = sum(winners) if winners else 0
    gross_loss = abs(sum(losers)) if losers else 1
    pf = gross_win / gross_loss if gross_loss > 0 else 999

    return {
        'trades': len(trades),
        'win_rate': len(winners) / len(trades) * 100,
        'total_pnl': total_pnl,
        'pf': pf,
        'max_dd': max_dd,
        'max_dd_pct': max_dd_pct,
        'max_consec_loss': max_consec,
        'final_capital': initial_capital + total_pnl,
    }


def main():
    print("=" * 80)
    print("XAUUSD DRAWDOWN OPTIMIZER")
    print("=" * 80)

    # First: test current preset as baseline
    print("\n--- BASELINE (current preset) ---")
    base_params = get_xauusd_params()
    baseline = run_xauusd_test(base_params, tf_passes=4)
    if baseline:
        print(f"  Trades: {baseline['trades']}, WR: {baseline['win_rate']:.1f}%, "
              f"PnL: ${baseline['total_pnl']:,.0f}, PF: {baseline['pf']:.2f}")
        print(f"  Max DD: ${baseline['max_dd']:,.0f} ({baseline['max_dd_pct']:.1f}%), "
              f"Consec Loss: {baseline['max_consec_loss']}")

    # Parameter grid
    results = []

    # Key optimization dimensions
    risk_pcts = [1.0, 2.0, 3.0, 4.0]
    max_pos_list = [1, 2, 3, 5]
    tf_pass_list = [1, 2, 3, 4]
    mom_mins = [35, 45, 55, 65]
    pb_atrs = [2.0, 2.5, 3.0, 3.5]
    sl_mults = [2.5, 3.0, 3.5, 4.0]
    be_rrs = [1.5, 2.0, 2.5, 3.0]

    # Phase 1: Find best tf_passes x risk x max_positions (coarse)
    print("\n--- PHASE 1: TF passes x Risk x Max positions ---")
    phase1_results = []

    for tf_pass, risk, max_pos in itertools.product(tf_pass_list, risk_pcts, max_pos_list):
        p = get_xauusd_params()
        p.risk_percent = risk
        p.max_positions = max_pos

        r = run_xauusd_test(p, tf_passes=tf_pass)
        if r and r['trades'] > 10:
            r['config'] = f"TF={tf_pass}, risk={risk}%, maxpos={max_pos}"
            r['tf_pass'] = tf_pass
            r['risk'] = risk
            r['max_pos'] = max_pos
            phase1_results.append(r)

    # Sort by a score: high PnL but penalize heavy DD
    # Score = PnL * min(1, -30/DD_pct) to cap DD at -30%
    for r in phase1_results:
        dd_penalty = min(1.0, -30.0 / r['max_dd_pct']) if r['max_dd_pct'] < -1 else 1.0
        r['score'] = r['total_pnl'] * dd_penalty * (r['pf'] ** 0.5)

    phase1_results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\nTop 15 configs (sorted by score = PnL * DD_penalty * sqrt(PF)):")
    print(f"{'Config':<35} {'Trades':>6} {'WR%':>5} {'PnL':>14} {'PF':>5} {'MaxDD%':>7} {'ConsL':>5} {'Score':>14}")
    print("-" * 100)
    for r in phase1_results[:15]:
        print(f"{r['config']:<35} {r['trades']:>6} {r['win_rate']:>5.1f} ${r['total_pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['max_dd_pct']:>6.1f}% {r['max_consec_loss']:>5} {r['score']:>14,.0f}")

    # Phase 2: Take top 3 from phase 1 and optimize entry filters
    print("\n--- PHASE 2: Optimize entry filters for top configs ---")

    top3 = phase1_results[:3]
    phase2_results = []

    for base in top3:
        for mom_min, pb_atr, sl_mult, be_rr in itertools.product(mom_mins, pb_atrs, sl_mults, be_rrs):
            p = get_xauusd_params()
            p.risk_percent = base['risk']
            p.max_positions = base['max_pos']
            p.mom_score_min = mom_min
            p.pb_atr_buffer = pb_atr
            p.atr_sl_multiplier = sl_mult
            p.be_rr_ratio = be_rr

            r = run_xauusd_test(p, tf_passes=base['tf_pass'])
            if r and r['trades'] > 10:
                r['config'] = (f"TF={base['tf_pass']}, r={base['risk']}%, mp={base['max_pos']}, "
                               f"mom={mom_min}, pb={pb_atr}, sl={sl_mult}, be={be_rr}")
                r['tf_pass'] = base['tf_pass']
                r['risk'] = base['risk']
                r['max_pos'] = base['max_pos']
                r['mom_min'] = mom_min
                r['pb_atr'] = pb_atr
                r['sl_mult'] = sl_mult
                r['be_rr'] = be_rr

                dd_penalty = min(1.0, -30.0 / r['max_dd_pct']) if r['max_dd_pct'] < -1 else 1.0
                r['score'] = r['total_pnl'] * dd_penalty * (r['pf'] ** 0.5)
                phase2_results.append(r)

    phase2_results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\nTop 20 configs:")
    print(f"{'Config':<70} {'Tr':>4} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3} {'Score':>14}")
    print("-" * 130)
    for r in phase2_results[:20]:
        print(f"{r['config']:<70} {r['trades']:>4} {r['win_rate']:>5.1f} ${r['total_pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['max_dd_pct']:>6.1f}% {r['max_consec_loss']:>3} {r['score']:>14,.0f}")

    # Best result
    if phase2_results:
        best = phase2_results[0]
        print(f"\n{'='*80}")
        print(f"BEST CONFIG:")
        print(f"  {best['config']}")
        print(f"  Trades: {best['trades']}, WR: {best['win_rate']:.1f}%")
        print(f"  PnL: ${best['total_pnl']:,.0f}, PF: {best['pf']:.2f}")
        print(f"  Max DD: {best['max_dd_pct']:.1f}%, Consec Loss: {best['max_consec_loss']}")
        print(f"  Final Capital: ${best['final_capital']:,.0f}")

        # Also show configs with DD < 30% and best PnL
        safe_configs = [r for r in phase2_results if r['max_dd_pct'] > -35]
        if safe_configs:
            safe_configs.sort(key=lambda x: x['total_pnl'], reverse=True)
            print(f"\nBEST CONFIG WITH DD < 35%:")
            best_safe = safe_configs[0]
            print(f"  {best_safe['config']}")
            print(f"  Trades: {best_safe['trades']}, WR: {best_safe['win_rate']:.1f}%")
            print(f"  PnL: ${best_safe['total_pnl']:,.0f}, PF: {best_safe['pf']:.2f}")
            print(f"  Max DD: {best_safe['max_dd_pct']:.1f}%, Consec Loss: {best_safe['max_consec_loss']}")


if __name__ == "__main__":
    main()
