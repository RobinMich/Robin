#!/usr/bin/env python3
"""
v8.0 FAST Optimizer: Max Profit + Min DD + Most Trades + WR > 50%
==================================================================
Streamlined: test each asset class separately with reduced search space.
Run XAUUSD first (fastest), then stocks, then indices.
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

def run_xau(params, combo_indices, capital=100_000):
    """Fast XAUUSD test with specific TF combo indices."""
    bt = Backtester(params=params, initial_capital=capital)
    with redirect_stdout(io.StringIO()):
        for idx in combo_indices:
            _, ctx, val, entry = XAU_COMBOS[idx]
            bt_p = Backtester(params=params, initial_capital=bt.capital)
            bt_p.run(f"XAUUSD_{idx}", ctx, val, entry)
            for t in bt_p.trades: bt.trades.append(t)
            bt.capital = bt_p.capital
            bt._peak_equity = max(bt._peak_equity, bt_p._peak_equity)
            bt.equity_curve.extend(bt_p.equity_curve)
            bt._equity_values.extend(bt_p._equity_values)
    return metrics(bt, capital)

def run_stocks(params, capital=100_000):
    """Run stocks backtest."""
    bt = Backtester(params=params, initial_capital=capital)
    with redirect_stdout(io.StringIO()):
        for sym, sdata in STOCK_DATA.items():
            ctx = sdata.get("D1") or sdata.get("W1")
            val = sdata.get("H4") or sdata.get("D1")
            entry = sdata.get("H1") or sdata.get("H4")
            if ctx is None or val is None or entry is None: continue
            bt_p = Backtester(params=params, initial_capital=bt.capital)
            bt_p.run(sym, ctx, val, entry)
            for t in bt_p.trades: bt.trades.append(t)
            bt.capital = bt_p.capital
            bt._peak_equity = max(bt._peak_equity, bt_p._peak_equity)
            bt.equity_curve.extend(bt_p.equity_curve)
            bt._equity_values.extend(bt_p._equity_values)
    return metrics(bt, capital)

def run_idx(params, sym, sdata, combo_idx=None, capital=100_000):
    """Run index backtest for single symbol."""
    combos = []
    if "W1" in sdata and "D1" in sdata and "H1" in sdata:
        combos.append(("W1/D1/H1", sdata["W1"], sdata["D1"], sdata["H1"]))
    if "W1" in sdata and "D1" in sdata and "H4" in sdata:
        combos.append(("W1/D1/H4", sdata["W1"], sdata["D1"], sdata["H4"]))
    if "W1" in sdata and "H4" in sdata and "H1" in sdata:
        combos.append(("W1/H4/H1", sdata["W1"], sdata["H4"], sdata["H1"]))
    if "D1" in sdata and "H4" in sdata and "H1" in sdata:
        combos.append(("D1/H4/H1", sdata["D1"], sdata["H4"], sdata["H1"]))
    if combo_idx is not None:
        combos = [combos[i] for i in combo_idx if i < len(combos)]
    bt = Backtester(params=params, initial_capital=capital)
    with redirect_stdout(io.StringIO()):
        for name, ctx, val, entry in combos:
            bt_p = Backtester(params=params, initial_capital=bt.capital)
            bt_p.run(f"{sym}_{name}", ctx, val, entry)
            for t in bt_p.trades: bt.trades.append(t)
            bt.capital = bt_p.capital
            bt._peak_equity = max(bt._peak_equity, bt_p._peak_equity)
            bt.equity_curve.extend(bt_p.equity_curve)
            bt._equity_values.extend(bt_p._equity_values)
    return metrics(bt, capital)

def run_idx_all(params, combo_idx=None, capital=100_000):
    """Run both US100 + US500."""
    bt = Backtester(params=params, initial_capital=capital)
    for sym, sdata in IDX_DATA.items():
        combos = []
        if "W1" in sdata and "D1" in sdata and "H1" in sdata:
            combos.append(sdata["W1"], sdata["D1"], sdata["H1"])
        # Just use run_idx per symbol and merge
        r_bt = Backtester(params=params, initial_capital=bt.capital)
        c = []
        if "W1" in sdata and "D1" in sdata and "H1" in sdata:
            c.append(("W1/D1/H1", sdata["W1"], sdata["D1"], sdata["H1"]))
        if "W1" in sdata and "D1" in sdata and "H4" in sdata:
            c.append(("W1/D1/H4", sdata["W1"], sdata["D1"], sdata["H4"]))
        if "W1" in sdata and "H4" in sdata and "H1" in sdata:
            c.append(("W1/H4/H1", sdata["W1"], sdata["H4"], sdata["H1"]))
        if "D1" in sdata and "H4" in sdata and "H1" in sdata:
            c.append(("D1/H4/H1", sdata["D1"], sdata["H4"], sdata["H1"]))
        if combo_idx is not None:
            c = [c[i] for i in combo_idx if i < len(c)]
        with redirect_stdout(io.StringIO()):
            for name, ctx, val, entry in c:
                bt_p = Backtester(params=params, initial_capital=bt.capital)
                bt_p.run(f"{sym}_{name}", ctx, val, entry)
                for t in bt_p.trades: bt.trades.append(t)
                bt.capital = bt_p.capital
                bt._peak_equity = max(bt._peak_equity, bt_p._peak_equity)
                bt.equity_curve.extend(bt_p.equity_curve)
                bt._equity_values.extend(bt_p._equity_values)
    return metrics(bt, capital)

def metrics(bt, capital=100_000):
    trades = bt.trades
    if not trades or len(trades) < 5: return None
    pnls = [t.pnl for t in trades]
    w = [p for p in pnls if p > 0]
    l = [p for p in pnls if p < 0]
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    dd_min = dd.min()
    di = np.argmin(dd)
    pv = capital + peak[di]
    dd_pct = (dd_min / pv) * 100 if pv > 0 else -999
    gw = sum(w) if w else 0
    gl = abs(sum(l)) if l else 1
    pf = gw / gl if gl > 0 else 999
    cs = mx = 0
    for p in pnls:
        if p < 0: cs += 1; mx = max(mx, cs)
        else: cs = 0
    return {'trades': len(trades), 'wr': len(w)/len(trades)*100,
            'pnl': sum(pnls), 'pf': pf, 'dd_pct': dd_pct, 'consec': mx, 'final': capital+sum(pnls)}

def sc(r):
    if r is None or r['wr'] < 50.0: return -1e18
    dd = abs(r['dd_pct'])
    dd_m = 1.5 if dd<=10 else (1.2 if dd<=15 else (1.0 if dd<=20 else (0.5 if dd<=30 else 0.1)))
    return r['pnl'] * dd_m * (r['trades']/200)**0.3 * (1+(r['wr']-50)*0.03) * min(r['pf'],5)**0.5


def fmt(results, title, n=20):
    if not results: print(f"\n  {title}: No results"); return
    results.sort(key=lambda x: x['sc'], reverse=True)
    print(f"\n{'='*130}")
    print(f"  {title} ({len(results)} valid configs)")
    print(f"  {'Config':<70} {'Tr':>5} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7} {'CL':>3} {'Score':>14}")
    print("-"*130)
    for r in results[:n]:
        print(f"  {r['cfg']:<70} {r['trades']:>5} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd_pct']:>6.1f}% {r['consec']:>3} {r['sc']:>14,.0f}")


# =====================================================================
print("Loading data...", flush=True)
XAU_DATA = load_sym('XAUUSD')
XAU_COMBOS = []
if "W1" in XAU_DATA and "D1" in XAU_DATA and "H1" in XAU_DATA:
    XAU_COMBOS.append(("W1/D1/H1", XAU_DATA["W1"], XAU_DATA["D1"], XAU_DATA["H1"]))
if "W1" in XAU_DATA and "D1" in XAU_DATA and "H4" in XAU_DATA:
    XAU_COMBOS.append(("W1/D1/H4", XAU_DATA["W1"], XAU_DATA["D1"], XAU_DATA["H4"]))
if "W1" in XAU_DATA and "H4" in XAU_DATA and "H1" in XAU_DATA:
    XAU_COMBOS.append(("W1/H4/H1", XAU_DATA["W1"], XAU_DATA["H4"], XAU_DATA["H1"]))
if "D1" in XAU_DATA and "H4" in XAU_DATA and "H1" in XAU_DATA:
    XAU_COMBOS.append(("D1/H4/H1", XAU_DATA["D1"], XAU_DATA["H4"], XAU_DATA["H1"]))

IDX_DATA = {}
for s in ['US100', 'US500']:
    try: IDX_DATA[s] = load_sym(s)
    except: pass

STOCK_SYMS = ["AAPL","AMD","AMZN","AVGO","GOOG","META","MSFT","NVDA","TSLA",
              "WMT","WDC","MU","PLTR","SAP","RHM","STX","BAC","GS","AXP","LLY",
              "COST","XOM","CAT","CSCO","SIEGY","TJX"]
STOCK_DATA = {}
for s in STOCK_SYMS:
    try: STOCK_DATA[s] = load_sym(s)
    except: pass

print(f"Loaded: {len(XAU_COMBOS)} XAU combos, {len(IDX_DATA)} indices, {len(STOCK_DATA)} stocks\n")


# =====================================================================
# XAUUSD
# =====================================================================
def opt_xauusd():
    print("="*120)
    print("  XAUUSD OPTIMIZATION")
    print("="*120)
    t0 = time.time()
    results = []

    # Test all TF combo groupings
    n = len(XAU_COMBOS)
    tf_groups = []
    for sz in range(1, n+1):
        for ci in itertools.combinations(range(n), sz):
            tf_groups.append(list(ci))

    cnt = 0
    for tf in tf_groups:
        tf_name = "+".join(XAU_COMBOS[i][0] for i in tf)
        for risk in [3, 5, 7]:
            for mom in [35, 45, 55]:
                for pb in [2.0, 3.0, 4.0]:
                    for sl in [3.5, 4.0]:
                        p = get_xauusd_params()
                        p.risk_percent = risk
                        p.mom_score_min = mom
                        p.pb_atr_buffer = pb
                        p.atr_sl_multiplier = sl
                        r = run_xau(p, tf)
                        cnt += 1
                        if r and r['wr'] >= 50:
                            r['sc'] = sc(r)
                            r['cfg'] = f"tf={tf_name} r={risk} mom={mom} pb={pb} sl={sl}"
                            r['p'] = {'tf': tf, 'tf_name': tf_name, 'risk': risk, 'mom': mom, 'pb': pb, 'sl': sl}
                            results.append(r)

    print(f"  Phase 1: {cnt} tested, {len(results)} valid, {time.time()-t0:.0f}s")
    fmt(results, "XAUUSD Phase 1", 10)

    # Phase 2: fine-tune top 3
    if results:
        results.sort(key=lambda x: x['sc'], reverse=True)
        phase2 = []
        seen = set()
        tops = []
        for r in results:
            k = str(r['p']['tf'])
            if k not in seen: seen.add(k); tops.append(r)
            if len(tops) >= 3: break

        for b in tops:
            bp = b['p']
            tf = bp['tf']; tf_name = bp['tf_name']
            for risk in [max(2, bp['risk']-2), bp['risk']-1, bp['risk'], bp['risk']+1, bp['risk']+2]:
                if risk < 1: continue
                for mom in [bp['mom']-10, bp['mom']-5, bp['mom'], bp['mom']+5, bp['mom']+10]:
                    if mom < 20: continue
                    for pb in [bp['pb']-0.5, bp['pb'], bp['pb']+0.5]:
                        if pb < 1.5: continue
                        for sl in [bp['sl']-0.5, bp['sl'], bp['sl']+0.5]:
                            if sl < 2: continue
                            for trail in [2.0, 2.5, 3.0]:
                                for be in [1.5, 2.0, 2.5, 3.0]:
                                    p = get_xauusd_params()
                                    p.risk_percent = float(risk)
                                    p.mom_score_min = int(mom)
                                    p.pb_atr_buffer = float(pb)
                                    p.atr_sl_multiplier = float(sl)
                                    p.atr_trail_multiplier = trail
                                    p.be_rr_ratio = be
                                    r = run_xau(p, tf)
                                    cnt += 1
                                    if r and r['wr'] >= 50:
                                        r['sc'] = sc(r)
                                        r['cfg'] = f"tf={tf_name} r={risk} mom={mom} pb={pb} sl={sl} tr={trail} be={be}"
                                        r['p'] = {'tf': tf, 'tf_name': tf_name, 'risk': risk, 'mom': mom,
                                                  'pb': pb, 'sl': sl, 'trail': trail, 'be': be}
                                        phase2.append(r)

        all_r = results + phase2
        all_r.sort(key=lambda x: x['sc'], reverse=True)
        print(f"  Phase 2: +{len(phase2)} configs, total {cnt}, {time.time()-t0:.0f}s")
        fmt(all_r, "XAUUSD FINAL", 25)

        # Best low-DD
        low = [r for r in all_r if r['dd_pct'] > -15]
        if low:
            low.sort(key=lambda x: x['pnl'], reverse=True)
            fmt(low, "XAUUSD LOW-DD (<15%)", 10)

        # Most trades
        hi_tr = sorted([r for r in all_r if r['dd_pct'] > -25], key=lambda x: x['trades'], reverse=True)
        if hi_tr:
            fmt(hi_tr, "XAUUSD MOST TRADES (DD<25%)", 10)

        return all_r
    return results


# =====================================================================
# INDICES
# =====================================================================
def opt_indices():
    print("\n" + "="*120)
    print("  INDICES OPTIMIZATION")
    print("="*120)
    t0 = time.time()
    results = []
    cnt = 0

    # Per-symbol, per-combo to find WR>50%
    for sym, sdata in IDX_DATA.items():
        combos = []
        if "W1" in sdata and "D1" in sdata and "H1" in sdata: combos.append(0)
        if "W1" in sdata and "D1" in sdata and "H4" in sdata: combos.append(1)
        if "W1" in sdata and "H4" in sdata and "H1" in sdata: combos.append(2)
        if "D1" in sdata and "H4" in sdata and "H1" in sdata: combos.append(3)

        for ci in combos:
            for risk in [2, 3, 4]:
                for mom in [40, 50, 60]:
                    for pb in [2.0, 2.5, 3.0]:
                        for sl in [3.5, 4.0, 4.5]:
                            for d in ['both', 'long']:
                                p = get_indices_params()
                                p.risk_percent = risk
                                p.mom_score_min = mom
                                p.pb_atr_buffer = pb
                                p.atr_sl_multiplier = sl
                                p.direction = d
                                r = run_idx(p, sym, sdata, [ci])
                                cnt += 1
                                if r and r['wr'] >= 50:
                                    r['sc'] = sc(r)
                                    r['cfg'] = f"{sym}_c{ci} r={risk} mom={mom} pb={pb} sl={sl} {d}"
                                    r['p'] = {'sym': sym, 'ci': ci, 'risk': risk, 'mom': mom, 'pb': pb, 'sl': sl, 'dir': d}
                                    results.append(r)

    # Also test both symbols combined with all combos
    for risk in [2, 3, 4]:
        for mom in [45, 55, 65]:
            for pb in [2.0, 2.5, 3.0]:
                for sl in [3.5, 4.0, 4.5]:
                    for d in ['both', 'long']:
                        p = get_indices_params()
                        p.risk_percent = risk
                        p.mom_score_min = mom
                        p.pb_atr_buffer = pb
                        p.atr_sl_multiplier = sl
                        p.direction = d
                        # Run both symbols with all combos
                        bt = Backtester(params=p, initial_capital=100_000)
                        for sym, sdata in IDX_DATA.items():
                            c = []
                            if "W1" in sdata and "D1" in sdata and "H1" in sdata:
                                c.append(("W1/D1/H1", sdata["W1"], sdata["D1"], sdata["H1"]))
                            if "W1" in sdata and "D1" in sdata and "H4" in sdata:
                                c.append(("W1/D1/H4", sdata["W1"], sdata["D1"], sdata["H4"]))
                            with redirect_stdout(io.StringIO()):
                                for name, ctx, val, entry in c:
                                    bp = Backtester(params=p, initial_capital=bt.capital)
                                    bp.run(f"{sym}_{name}", ctx, val, entry)
                                    for t in bp.trades: bt.trades.append(t)
                                    bt.capital = bp.capital
                                    bt._peak_equity = max(bt._peak_equity, bp._peak_equity)
                                    bt.equity_curve.extend(bp.equity_curve)
                                    bt._equity_values.extend(bp._equity_values)
                        r = metrics(bt)
                        cnt += 1
                        if r and r['wr'] >= 50:
                            r['sc'] = sc(r)
                            r['cfg'] = f"BOTH_2c r={risk} mom={mom} pb={pb} sl={sl} {d}"
                            r['p'] = {'risk': risk, 'mom': mom, 'pb': pb, 'sl': sl, 'dir': d}
                            results.append(r)

    print(f"  {cnt} tested, {len(results)} with WR>=50%, {time.time()-t0:.0f}s")
    fmt(results, "INDICES RESULTS", 20)

    # Phase 2 for top configs
    if results:
        results.sort(key=lambda x: x['sc'], reverse=True)
        phase2 = []
        for b in results[:3]:
            bp = b['p']
            for risk in [max(1,bp['risk']-1), bp['risk'], bp['risk']+1]:
                for mom in [bp['mom']-5, bp['mom'], bp['mom']+5]:
                    for pb in [bp['pb']-0.5, bp['pb'], bp['pb']+0.5]:
                        for sl in [bp['sl']-0.5, bp['sl'], bp['sl']+0.5]:
                            for trail in [2.5, 3.0, 3.5]:
                                for be in [1.5, 2.0, 2.5]:
                                    p = get_indices_params()
                                    p.risk_percent = risk
                                    p.mom_score_min = int(mom)
                                    p.pb_atr_buffer = float(pb)
                                    p.atr_sl_multiplier = float(sl)
                                    p.atr_trail_multiplier = trail
                                    p.be_rr_ratio = be
                                    p.direction = bp['dir']

                                    if 'sym' in bp:
                                        r = run_idx(p, bp['sym'], IDX_DATA[bp['sym']], [bp['ci']])
                                    else:
                                        # Both symbols, 2 combos
                                        bt2 = Backtester(params=p, initial_capital=100_000)
                                        for sym, sdata in IDX_DATA.items():
                                            c = []
                                            if "W1" in sdata and "D1" in sdata and "H1" in sdata:
                                                c.append(("W1/D1/H1", sdata["W1"], sdata["D1"], sdata["H1"]))
                                            if "W1" in sdata and "D1" in sdata and "H4" in sdata:
                                                c.append(("W1/D1/H4", sdata["W1"], sdata["D1"], sdata["H4"]))
                                            with redirect_stdout(io.StringIO()):
                                                for name, ctx, val, entry in c:
                                                    bp2 = Backtester(params=p, initial_capital=bt2.capital)
                                                    bp2.run(f"{sym}_{name}", ctx, val, entry)
                                                    for t in bp2.trades: bt2.trades.append(t)
                                                    bt2.capital = bp2.capital
                                                    bt2._peak_equity = max(bt2._peak_equity, bp2._peak_equity)
                                                    bt2.equity_curve.extend(bp2.equity_curve)
                                                    bt2._equity_values.extend(bp2._equity_values)
                                        r = metrics(bt2)
                                    cnt += 1
                                    if r and r['wr'] >= 50:
                                        r['sc'] = sc(r)
                                        r['cfg'] = f"{'SYM='+bp.get('sym','ALL') if 'sym' in bp else 'BOTH'} r={risk} mom={mom} pb={pb} sl={sl} tr={trail} be={be} {bp['dir']}"
                                        r['p'] = {**bp, 'risk': risk, 'mom': int(mom), 'pb': float(pb),
                                                  'sl': float(sl), 'trail': trail, 'be': be}
                                        phase2.append(r)

        all_r = results + phase2
        all_r.sort(key=lambda x: x['sc'], reverse=True)
        print(f"  Phase 2: +{len(phase2)}, {time.time()-t0:.0f}s")
        fmt(all_r, "INDICES FINAL", 20)
        return all_r

    return results


# =====================================================================
# STOCKS
# =====================================================================
def opt_stocks():
    print("\n" + "="*120)
    print("  STOCKS OPTIMIZATION")
    print("="*120)
    t0 = time.time()
    results = []
    cnt = 0

    for risk in [1.0, 1.5, 2.0]:
        for mom in [25, 35, 45]:
            for pb in [2.5, 3.0, 3.5, 4.0]:
                for sl in [2.5, 3.0, 3.5]:
                    for trail in [2.5, 3.0, 3.5]:
                        p = get_stocks_params()
                        p.risk_percent = risk
                        p.mom_score_min = mom
                        p.pb_atr_buffer = pb
                        p.atr_sl_multiplier = sl
                        p.atr_trail_multiplier = trail
                        r = run_stocks(p)
                        cnt += 1
                        if r and r['wr'] >= 50:
                            r['sc'] = sc(r)
                            r['cfg'] = f"r={risk} mom={mom} pb={pb} sl={sl} tr={trail}"
                            r['p'] = {'risk': risk, 'mom': mom, 'pb': pb, 'sl': sl, 'trail': trail}
                            results.append(r)
        print(f"    risk={risk} done... ({cnt} tested, {len(results)} valid)", flush=True)

    print(f"  Phase 1: {cnt} tested, {len(results)} valid, {time.time()-t0:.0f}s")
    fmt(results, "STOCKS Phase 1", 10)

    # Phase 2
    if results:
        results.sort(key=lambda x: x['sc'], reverse=True)
        phase2 = []
        for b in results[:3]:
            bp = b['p']
            for risk in np.arange(max(0.5, bp['risk']-0.5), bp['risk']+0.75, 0.25):
                for mom in [bp['mom']-5, bp['mom'], bp['mom']+5]:
                    for pb in [bp['pb']-0.5, bp['pb'], bp['pb']+0.5]:
                        for sl in [bp['sl']-0.5, bp['sl'], bp['sl']+0.5]:
                            for trail in [bp['trail']-0.5, bp['trail'], bp['trail']+0.5]:
                                for be in [1.5, 2.0, 2.5]:
                                    if any(v < 1 for v in [risk, pb, sl, trail]): continue
                                    p = get_stocks_params()
                                    p.risk_percent = float(risk)
                                    p.mom_score_min = int(mom)
                                    p.pb_atr_buffer = float(pb)
                                    p.atr_sl_multiplier = float(sl)
                                    p.atr_trail_multiplier = float(trail)
                                    p.be_rr_ratio = be
                                    r = run_stocks(p)
                                    cnt += 1
                                    if r and r['wr'] >= 50:
                                        r['sc'] = sc(r)
                                        r['cfg'] = f"r={risk:.2f} mom={mom} pb={pb} sl={sl} tr={trail} be={be}"
                                        r['p'] = {'risk': float(risk), 'mom': int(mom), 'pb': float(pb),
                                                  'sl': float(sl), 'trail': float(trail), 'be': be}
                                        phase2.append(r)

        all_r = results + phase2
        all_r.sort(key=lambda x: x['sc'], reverse=True)
        print(f"  Phase 2: +{len(phase2)}, total {cnt}, {time.time()-t0:.0f}s")
        fmt(all_r, "STOCKS FINAL", 20)
        return all_r
    return results


# =====================================================================
# MAIN
# =====================================================================
def main():
    print("="*120)
    print("  v8.0 FAST OPTIMIZER: Max Profit + Min DD + Most Trades + WR > 50%")
    print("="*120 + "\n")

    xau_r = opt_xauusd()
    idx_r = opt_indices()
    stock_r = opt_stocks()

    print("\n" + "="*120)
    print("  FINAL v8.0 SUMMARY")
    print("="*120)
    for name, res in [("XAUUSD", xau_r), ("INDICES", idx_r), ("STOCKS", stock_r)]:
        if res:
            b = res[0]
            print(f"\n  {name} BEST: {b['cfg']}")
            print(f"    {b['trades']} trades, WR {b['wr']:.1f}%, PF {b['pf']:.2f}, DD {b['dd_pct']:.1f}%, PnL ${b['pnl']:,.0f}")
            print(f"    Params: {b['p']}")
        else:
            print(f"\n  {name}: No config with WR>=50% found")


if __name__ == "__main__":
    main()
