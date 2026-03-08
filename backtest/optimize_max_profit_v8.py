#!/usr/bin/env python3
"""
v8.0 Optimizer: Max Profit + Min DD + Most Trades + WR > 50%
=============================================================
2-Phase approach: coarse sweep -> fine-tune around best configs.
Score = PnL * WR_bonus * DD_penalty * trade_count_bonus * PF_bonus
Only WR >= 50% configs considered.
"""
import sys, os, io, itertools, time
from contextlib import redirect_stdout
sys.path.insert(0, os.path.dirname(__file__))

from backtester_v4 import (
    StrategyParams, Backtester, load_symbol_data,
    get_xauusd_params, get_stocks_params, get_indices_params
)
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_sym(sym):
    with redirect_stdout(io.StringIO()):
        return load_symbol_data(sym, DATA_DIR)


def get_tf_combos(symbol, data):
    is_gold = "XAU" in symbol
    is_index = symbol in ("US100", "US500")
    combos = []
    if is_gold or is_index:
        if "W1" in data and "D1" in data and "H1" in data:
            combos.append(("W1/D1/H1", data["W1"], data["D1"], data["H1"]))
        if "W1" in data and "D1" in data and "H4" in data:
            combos.append(("W1/D1/H4", data["W1"], data["D1"], data["H4"]))
        if "W1" in data and "H4" in data and "H1" in data:
            combos.append(("W1/H4/H1", data["W1"], data["H4"], data["H1"]))
        if "D1" in data and "H4" in data and "H1" in data:
            combos.append(("D1/H4/H1", data["D1"], data["H4"], data["H1"]))
    else:
        ctx = data.get("D1") or data.get("W1")
        val = data.get("H4") or data.get("D1")
        entry = data.get("H1") or data.get("H4")
        if ctx is not None and val is not None and entry is not None:
            combos.append(("D1/H4/H1", ctx, val, entry))
    return combos


def run_single(params, sym, sdata, combo_indices=None, capital=100_000):
    """Run backtest for a single symbol."""
    combos = get_tf_combos(sym, sdata)
    if not combos:
        return None
    if combo_indices is not None:
        combos = [combos[i] for i in combo_indices if i < len(combos)]

    bt = Backtester(params=params, initial_capital=capital)
    for name, ctx, val, entry in combos:
        with redirect_stdout(io.StringIO()):
            bt_pass = Backtester(params=params, initial_capital=bt.capital)
            bt_pass.run(f"{sym}_{name}", ctx, val, entry)
        for t in bt_pass.trades:
            bt.trades.append(t)
        bt.capital = bt_pass.capital
        bt._peak_equity = max(bt._peak_equity, bt_pass._peak_equity)
        bt.equity_curve.extend(bt_pass.equity_curve)
        bt._equity_values.extend(bt_pass._equity_values)
    return bt


def run_multi(params, sym_data_dict, combo_map=None, capital=100_000):
    """Run across multiple symbols. combo_map: {sym: [indices]}."""
    bt = Backtester(params=params, initial_capital=capital)
    for sym, sdata in sym_data_dict.items():
        ci = combo_map.get(sym) if combo_map else None
        bt_sym = run_single(params, sym, sdata, ci, bt.capital)
        if bt_sym and bt_sym.trades:
            for t in bt_sym.trades:
                bt.trades.append(t)
            bt.capital = bt_sym.capital
            bt._peak_equity = max(bt._peak_equity, bt_sym._peak_equity)
            bt.equity_curve.extend(bt_sym.equity_curve)
            bt._equity_values.extend(bt_sym._equity_values)
    return bt


def calc_metrics(bt, capital=100_000):
    trades = bt.trades
    if not trades or len(trades) < 5:
        return None
    pnls = [t.pnl for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    max_dd_val = dd.min()
    dd_idx = np.argmin(dd)
    peak_val = capital + peak[dd_idx]
    dd_pct = (max_dd_val / peak_val) * 100 if peak_val > 0 else -999
    gw = sum(winners) if winners else 0
    gl = abs(sum(losers)) if losers else 1
    pf = gw / gl if gl > 0 else 999
    consec = max_c = 0
    for p in pnls:
        if p < 0: consec += 1; max_c = max(max_c, consec)
        else: consec = 0
    return {
        'trades': len(trades), 'wr': len(winners)/len(trades)*100,
        'pnl': sum(pnls), 'pf': pf, 'dd_pct': dd_pct, 'max_dd': max_dd_val,
        'consec': max_c, 'final': capital + sum(pnls),
    }


def score(r):
    if r is None or r['wr'] < 50.0:
        return -1e18
    dd = abs(r['dd_pct'])
    dd_m = 1.5 if dd <= 10 else (1.2 if dd <= 15 else (1.0 if dd <= 20 else (0.5 if dd <= 30 else 0.1)))
    tr_m = (r['trades'] / 200) ** 0.3
    wr_m = 1.0 + (r['wr'] - 50.0) * 0.03
    pf_m = min(r['pf'], 5.0) ** 0.5
    return r['pnl'] * dd_m * tr_m * wr_m * pf_m


def print_top(results, title, n=20):
    if not results:
        print(f"\n  {title}: No results found")
        return
    results.sort(key=lambda x: x['score'], reverse=True)
    print(f"\n{'='*130}")
    print(f"  {title} (top {min(n, len(results))} of {len(results)}):")
    print(f"  {'Config':<70} {'Tr':>5} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3} {'Score':>14}")
    print("-" * 130)
    for r in results[:n]:
        print(f"  {r['cfg']:<70} {r['trades']:>5} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd_pct']:>6.1f}% {r['consec']:>3} {r['score']:>14,.0f}")


# =====================================================================
# XAUUSD
# =====================================================================
def optimize_xauusd(xau_data):
    print("\n" + "=" * 120)
    print("  XAUUSD OPTIMIZATION")
    print("=" * 120)

    combos = get_tf_combos('XAUUSD', xau_data)
    sd = {'XAUUSD': xau_data}
    n = len(combos)
    print(f"  TF combos available: {[c[0] for c in combos]}")

    # Phase 1: Coarse sweep - all TF groupings x key params
    print("\n  Phase 1: Coarse sweep...", flush=True)
    t0 = time.time()
    results = []
    tested = 0

    # Generate TF groupings (singles, pairs, triples, all)
    tf_groups = []
    for size in range(1, n + 1):
        for ci in itertools.combinations(range(n), size):
            names = "+".join(combos[i][0] for i in ci)
            tf_groups.append((list(ci), names))

    for tf_idx, tf_name in tf_groups:
        for risk in [3.0, 5.0, 7.0]:
            for mom_min in [35, 45, 55]:
                for pb_atr in [2.0, 3.0, 4.0]:
                    for sl_mult in [3.0, 4.0]:
                        p = get_xauusd_params()
                        p.risk_percent = risk
                        p.mom_score_min = mom_min
                        p.pb_atr_buffer = pb_atr
                        p.atr_sl_multiplier = sl_mult
                        bt = run_multi(p, sd, {'XAUUSD': tf_idx})
                        r = calc_metrics(bt)
                        tested += 1
                        if r and r['wr'] >= 50.0:
                            s = score(r)
                            results.append({
                                **r, 'score': s,
                                'cfg': f"tf={tf_name} r={risk} mom={mom_min} pb={pb_atr} sl={sl_mult}",
                                'params': {'tf': tf_idx, 'tf_name': tf_name,
                                           'risk_percent': risk, 'mom_score_min': mom_min,
                                           'pb_atr_buffer': pb_atr, 'atr_sl_multiplier': sl_mult}
                            })

    print(f"  Phase 1: {tested} configs in {time.time()-t0:.0f}s, {len(results)} with WR>=50%")
    print_top(results, "XAUUSD PHASE 1", 15)

    # Phase 2: Fine-tune around top 5
    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        print(f"\n  Phase 2: Fine-tuning top configs...", flush=True)
        t0 = time.time()
        phase2 = []

        seen_tf = set()
        top_configs = []
        for r in results:
            tf_key = str(r['params']['tf'])
            if tf_key not in seen_tf:
                seen_tf.add(tf_key)
                top_configs.append(r)
            if len(top_configs) >= 3:
                break

        for base_r in top_configs:
            bp = base_r['params']
            tf_idx = bp['tf']
            tf_name = bp['tf_name']

            for risk in np.arange(max(1.0, bp['risk_percent']-2), bp['risk_percent']+3, 1.0):
                for mom_min in range(max(25, bp['mom_score_min']-10), bp['mom_score_min']+15, 5):
                    for pb_atr in np.arange(max(1.5, bp['pb_atr_buffer']-1.0), bp['pb_atr_buffer']+1.5, 0.5):
                        for sl_mult in np.arange(max(2.0, bp['atr_sl_multiplier']-1.0), bp['atr_sl_multiplier']+1.5, 0.5):
                            for trail_mult in [2.0, 2.5, 3.0, 3.5]:
                                for be_rr in [1.5, 2.0, 2.5, 3.0]:
                                    p = get_xauusd_params()
                                    p.risk_percent = float(risk)
                                    p.mom_score_min = int(mom_min)
                                    p.pb_atr_buffer = float(pb_atr)
                                    p.atr_sl_multiplier = float(sl_mult)
                                    p.atr_trail_multiplier = float(trail_mult)
                                    p.be_rr_ratio = float(be_rr)
                                    bt = run_multi(p, sd, {'XAUUSD': tf_idx})
                                    r2 = calc_metrics(bt)
                                    tested += 1
                                    if r2 and r2['wr'] >= 50.0:
                                        s = score(r2)
                                        phase2.append({
                                            **r2, 'score': s,
                                            'cfg': f"tf={tf_name} r={risk:.0f} mom={mom_min} pb={pb_atr:.1f} sl={sl_mult:.1f} tr={trail_mult} be={be_rr}",
                                            'params': {'tf': tf_idx, 'tf_name': tf_name,
                                                       'risk_percent': float(risk), 'mom_score_min': int(mom_min),
                                                       'pb_atr_buffer': float(pb_atr), 'atr_sl_multiplier': float(sl_mult),
                                                       'atr_trail_multiplier': float(trail_mult), 'be_rr_ratio': float(be_rr)}
                                        })

        all_results = results + phase2
        all_results.sort(key=lambda x: x['score'], reverse=True)
        print(f"  Phase 2: {len(phase2)} more configs in {time.time()-t0:.0f}s")
        print_top(all_results, "XAUUSD FINAL", 25)

        # Also show best by different criteria
        low_dd = sorted([r for r in all_results if r['dd_pct'] > -15], key=lambda x: x['pnl'], reverse=True)
        if low_dd:
            print_top(low_dd, "XAUUSD BEST LOW-DD (<15%)", 10)

        high_trades = sorted([r for r in all_results if r['dd_pct'] > -25], key=lambda x: x['trades'], reverse=True)
        if high_trades:
            print_top(high_trades, "XAUUSD MOST TRADES (DD<25%)", 10)

        return all_results
    return results


# =====================================================================
# INDICES
# =====================================================================
def optimize_indices(idx_data_dict):
    print("\n" + "=" * 120)
    print("  INDICES OPTIMIZATION")
    print("=" * 120)

    # Phase 1: Coarse - try to get WR > 50%
    print("\n  Phase 1: Coarse sweep...", flush=True)
    t0 = time.time()
    results = []
    tested = 0

    # Indices at 35% WR currently. To hit 50%: stricter momentum, tighter entries, long-only
    for risk in [2.0, 3.0, 4.0]:
        for mom_min in [40, 50, 60]:
            for pb_atr in [2.0, 2.5, 3.0]:
                for sl_mult in [3.0, 3.5, 4.0, 4.5]:
                    for direction in ['both', 'long']:
                        p = get_indices_params()
                        p.risk_percent = risk
                        p.mom_score_min = mom_min
                        p.pb_atr_buffer = pb_atr
                        p.atr_sl_multiplier = sl_mult
                        p.direction = direction
                        bt = run_multi(p, idx_data_dict)
                        r = calc_metrics(bt)
                        tested += 1
                        if r and r['wr'] >= 50.0:
                            s = score(r)
                            results.append({
                                **r, 'score': s,
                                'cfg': f"r={risk} mom={mom_min} pb={pb_atr} sl={sl_mult} dir={direction}",
                                'params': {'risk_percent': risk, 'mom_score_min': mom_min,
                                           'pb_atr_buffer': pb_atr, 'atr_sl_multiplier': sl_mult,
                                           'direction': direction}
                            })

    # If no results, try individual TF combos per symbol
    if not results:
        print("  All-combo didn't hit 50% WR. Trying per-symbol individual combos...")
        for sym, sdata in idx_data_dict.items():
            combos = get_tf_combos(sym, sdata)
            for i in range(len(combos)):
                for risk in [2.0, 3.0, 4.0]:
                    for mom_min in [45, 55, 65]:
                        for pb_atr in [2.0, 2.5, 3.0]:
                            for sl_mult in [3.5, 4.0, 4.5]:
                                p = get_indices_params()
                                p.risk_percent = risk
                                p.mom_score_min = mom_min
                                p.pb_atr_buffer = pb_atr
                                p.atr_sl_multiplier = sl_mult
                                p.direction = 'long'
                                bt = run_multi(p, {sym: sdata}, {sym: [i]})
                                r = calc_metrics(bt)
                                tested += 1
                                if r and r['wr'] >= 50.0:
                                    s = score(r)
                                    results.append({
                                        **r, 'score': s,
                                        'cfg': f"{sym}_{combos[i][0]} r={risk} mom={mom_min} pb={pb_atr} sl={sl_mult} long",
                                        'params': {'symbol': sym, 'tf_combo_idx': i,
                                                   'risk_percent': risk, 'mom_score_min': mom_min,
                                                   'pb_atr_buffer': pb_atr, 'atr_sl_multiplier': sl_mult,
                                                   'direction': 'long'}
                                    })

    print(f"  Phase 1: {tested} tested in {time.time()-t0:.0f}s, {len(results)} with WR>=50%")

    # Phase 2: Fine-tune if we found something
    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        print(f"\n  Phase 2: Fine-tuning...", flush=True)
        t0 = time.time()
        phase2 = []

        for base_r in results[:3]:
            bp = base_r['params']
            sym = bp.get('symbol')
            tf_ci = bp.get('tf_combo_idx')

            for risk in np.arange(max(1.0, bp['risk_percent']-1), bp['risk_percent']+2, 0.5):
                for mom_min in range(max(30, bp['mom_score_min']-10), bp['mom_score_min']+15, 5):
                    for pb_atr in np.arange(max(1.5, bp['pb_atr_buffer']-0.5), bp['pb_atr_buffer']+1.0, 0.5):
                        for sl_mult in np.arange(max(2.5, bp['atr_sl_multiplier']-0.5), bp['atr_sl_multiplier']+1.0, 0.5):
                            for trail_mult in [2.5, 3.0, 3.5]:
                                for be_rr in [1.5, 2.0, 2.5]:
                                    p = get_indices_params()
                                    p.risk_percent = float(risk)
                                    p.mom_score_min = int(mom_min)
                                    p.pb_atr_buffer = float(pb_atr)
                                    p.atr_sl_multiplier = float(sl_mult)
                                    p.atr_trail_multiplier = float(trail_mult)
                                    p.be_rr_ratio = float(be_rr)
                                    p.direction = bp['direction']

                                    if sym and tf_ci is not None:
                                        bt = run_multi(p, {sym: idx_data_dict[sym]}, {sym: [tf_ci]})
                                    else:
                                        bt = run_multi(p, idx_data_dict)
                                    r2 = calc_metrics(bt)
                                    if r2 and r2['wr'] >= 50.0:
                                        s = score(r2)
                                        phase2.append({
                                            **r2, 'score': s,
                                            'cfg': f"{'SYM='+sym+'_'+str(tf_ci)+' ' if sym else ''}r={risk:.1f} mom={mom_min} pb={pb_atr:.1f} sl={sl_mult:.1f} tr={trail_mult} be={be_rr} dir={bp['direction']}",
                                            'params': {**bp, 'risk_percent': float(risk), 'mom_score_min': int(mom_min),
                                                       'pb_atr_buffer': float(pb_atr), 'atr_sl_multiplier': float(sl_mult),
                                                       'atr_trail_multiplier': float(trail_mult), 'be_rr_ratio': float(be_rr)}
                                        })

        all_results = results + phase2
        all_results.sort(key=lambda x: x['score'], reverse=True)
        print(f"  Phase 2: {len(phase2)} more in {time.time()-t0:.0f}s")
        print_top(all_results, "INDICES FINAL", 20)
        return all_results

    print("  WARNING: No index config achieved WR >= 50%. Indices may need fundamentally different approach.")
    return results


# =====================================================================
# STOCKS
# =====================================================================
def optimize_stocks(stock_data_dict):
    print("\n" + "=" * 120)
    print("  STOCKS OPTIMIZATION")
    print("=" * 120)
    print(f"  {len(stock_data_dict)} symbols loaded")

    print("\n  Phase 1: Coarse sweep...", flush=True)
    t0 = time.time()
    results = []
    tested = 0

    for risk in [1.0, 1.5, 2.0]:
        for mom_min in [25, 35, 45]:
            for pb_atr in [2.5, 3.0, 3.5, 4.0]:
                for sl_mult in [2.5, 3.0, 3.5]:
                    for trail_mult in [2.5, 3.0, 3.5]:
                        p = get_stocks_params()
                        p.risk_percent = risk
                        p.mom_score_min = mom_min
                        p.pb_atr_buffer = pb_atr
                        p.atr_sl_multiplier = sl_mult
                        p.atr_trail_multiplier = trail_mult
                        bt = run_multi(p, stock_data_dict)
                        r = calc_metrics(bt)
                        tested += 1
                        if r and r['wr'] >= 50.0:
                            s = score(r)
                            results.append({
                                **r, 'score': s,
                                'cfg': f"r={risk} mom={mom_min} pb={pb_atr} sl={sl_mult} tr={trail_mult}",
                                'params': {'risk_percent': risk, 'mom_score_min': mom_min,
                                           'pb_atr_buffer': pb_atr, 'atr_sl_multiplier': sl_mult,
                                           'atr_trail_multiplier': trail_mult}
                            })

    print(f"  Phase 1: {tested} tested in {time.time()-t0:.0f}s, {len(results)} with WR>=50%")

    # Phase 2: Fine-tune
    if results:
        results.sort(key=lambda x: x['score'], reverse=True)
        print(f"\n  Phase 2: Fine-tuning...", flush=True)
        t0 = time.time()
        phase2 = []

        for base_r in results[:3]:
            bp = base_r['params']
            for risk in np.arange(max(0.5, bp['risk_percent']-0.5), bp['risk_percent']+1.0, 0.25):
                for mom_min in range(max(20, bp['mom_score_min']-10), bp['mom_score_min']+10, 5):
                    for pb_atr in np.arange(max(2.0, bp['pb_atr_buffer']-0.5), bp['pb_atr_buffer']+1.0, 0.5):
                        for sl_mult in np.arange(max(2.0, bp['atr_sl_multiplier']-0.5), bp['atr_sl_multiplier']+0.5, 0.5):
                            for trail_mult in np.arange(max(2.0, bp['atr_trail_multiplier']-0.5), bp['atr_trail_multiplier']+1.0, 0.5):
                                for be_rr in [1.5, 2.0, 2.5]:
                                    p = get_stocks_params()
                                    p.risk_percent = float(risk)
                                    p.mom_score_min = int(mom_min)
                                    p.pb_atr_buffer = float(pb_atr)
                                    p.atr_sl_multiplier = float(sl_mult)
                                    p.atr_trail_multiplier = float(trail_mult)
                                    p.be_rr_ratio = float(be_rr)
                                    bt = run_multi(p, stock_data_dict)
                                    r2 = calc_metrics(bt)
                                    if r2 and r2['wr'] >= 50.0:
                                        s = score(r2)
                                        phase2.append({
                                            **r2, 'score': s,
                                            'cfg': f"r={risk:.2f} mom={mom_min} pb={pb_atr:.1f} sl={sl_mult:.1f} tr={trail_mult:.1f} be={be_rr}",
                                            'params': {'risk_percent': float(risk), 'mom_score_min': int(mom_min),
                                                       'pb_atr_buffer': float(pb_atr), 'atr_sl_multiplier': float(sl_mult),
                                                       'atr_trail_multiplier': float(trail_mult), 'be_rr_ratio': float(be_rr)}
                                        })

        all_results = results + phase2
        all_results.sort(key=lambda x: x['score'], reverse=True)
        print(f"  Phase 2: {len(phase2)} more in {time.time()-t0:.0f}s")
        print_top(all_results, "STOCKS FINAL", 20)
        return all_results
    return results


def main():
    print("=" * 120)
    print("  v8.0 OPTIMIZER: Max Profit + Min DD + Most Trades + WR > 50%")
    print("=" * 120)

    print("\nLoading data...", flush=True)
    t_start = time.time()

    # Load all symbols
    xau_data = load_sym('XAUUSD')

    idx_data = {}
    for s in ['US100', 'US500']:
        try: idx_data[s] = load_sym(s)
        except: pass

    stock_syms = [
        "AAPL", "AMD", "AMZN", "AVGO", "GOOG", "META", "MSFT", "NVDA", "TSLA",
        "WMT", "WDC", "MU", "PLTR", "SAP", "RHM", "STX",
        "BAC", "GS", "AXP", "LLY", "COST", "XOM", "CAT", "CSCO", "SIEGY", "TJX"
    ]
    stock_data = {}
    for s in stock_syms:
        try: stock_data[s] = load_sym(s)
        except: pass

    print(f"Data loaded in {time.time()-t_start:.0f}s: XAUUSD + {len(idx_data)} indices + {len(stock_data)} stocks\n")

    # Run optimizations
    xau_results = optimize_xauusd(xau_data)
    idx_results = optimize_indices(idx_data)
    stock_results = optimize_stocks(stock_data)

    # Summary
    print("\n" + "=" * 120)
    print("  FINAL v8.0 OPTIMIZATION SUMMARY")
    print("=" * 120)

    for name, res in [("XAUUSD", xau_results), ("INDICES", idx_results), ("STOCKS", stock_results)]:
        if res:
            b = res[0]
            print(f"\n  {name} BEST:")
            print(f"    Config:  {b['cfg']}")
            print(f"    Trades:  {b['trades']}, WR: {b['wr']:.1f}%, PF: {b['pf']:.2f}, DD: {b['dd_pct']:.1f}%, PnL: ${b['pnl']:,.0f}")
            print(f"    Params:  {b['params']}")
        else:
            print(f"\n  {name}: No config with WR>=50% found")

    print(f"\n  Total optimization time: {time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
