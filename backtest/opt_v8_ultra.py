#!/usr/bin/env python3
"""
v8.0 ULTRA Optimizer - Surgical parameter sweep
================================================
~30 configs per asset = ~10 min total runtime.
Focus on the most impactful parameters only.
"""
import sys, os, io, time, itertools
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

def run_bt(params, runs, capital=100_000):
    bt = Backtester(params=params, initial_capital=capital)
    with redirect_stdout(io.StringIO()):
        for label, ctx, val, entry in runs:
            bp = Backtester(params=params, initial_capital=bt.capital)
            bp.run(label, ctx, val, entry)
            for t in bp.trades: bt.trades.append(t)
            bt.capital = bp.capital
            bt._peak_equity = max(bt._peak_equity, bp._peak_equity)
            bt.equity_curve.extend(bp.equity_curve)
            bt._equity_values.extend(bp._equity_values)
    return bt

def met(bt, cap=100_000):
    tr = bt.trades
    if not tr or len(tr) < 5: return None
    pnls = [t.pnl for t in tr]
    w = [p for p in pnls if p > 0]
    l = [p for p in pnls if p < 0]
    eq = np.cumsum(pnls); pk = np.maximum.accumulate(eq)
    dd = eq - pk; ddm = dd.min(); di = np.argmin(dd)
    pv = cap + pk[di]; dd_p = (ddm/pv)*100 if pv > 0 else -999
    gw = sum(w) if w else 0; gl = abs(sum(l)) if l else 1
    pf = gw/gl if gl > 0 else 999
    cs = mx = 0
    for p in pnls:
        if p < 0: cs += 1; mx = max(mx, cs)
        else: cs = 0
    return {'tr': len(tr), 'wr': len(w)/len(tr)*100, 'pnl': sum(pnls),
            'pf': pf, 'dd': dd_p, 'cl': mx, 'fin': cap+sum(pnls)}

def sc(r):
    if r is None or r['wr'] < 50: return -1e18
    dd = abs(r['dd'])
    dm = 1.5 if dd<=10 else (1.2 if dd<=15 else (1.0 if dd<=20 else (0.5 if dd<=30 else 0.1)))
    return r['pnl'] * dm * (r['tr']/200)**0.3 * (1+(r['wr']-50)*0.03) * min(r['pf'],5)**0.5

def pr(r, cfg=""):
    if r is None: return
    mark = " ***" if r['wr'] >= 50 else ""
    print(f"    {cfg:<60} {r['tr']:>4} tr, WR {r['wr']:>5.1f}%, PF {r['pf']:>5.2f}, DD {r['dd']:>6.1f}%, PnL ${r['pnl']:>12,.0f}{mark}")

# =====================================================================
print("Loading data...", flush=True)
XD = load_sym('XAUUSD')
XC = []
if "W1" in XD and "D1" in XD and "H1" in XD: XC.append(("W1/D1/H1", XD["W1"], XD["D1"], XD["H1"]))
if "W1" in XD and "D1" in XD and "H4" in XD: XC.append(("W1/D1/H4", XD["W1"], XD["D1"], XD["H4"]))
if "W1" in XD and "H4" in XD and "H1" in XD: XC.append(("W1/H4/H1", XD["W1"], XD["H4"], XD["H1"]))
if "D1" in XD and "H4" in XD and "H1" in XD: XC.append(("D1/H4/H1", XD["D1"], XD["H4"], XD["H1"]))

ID = {}
for s in ['US100','US500']:
    try: ID[s] = load_sym(s)
    except: pass

SS = ["AAPL","AMD","AMZN","AVGO","GOOG","META","MSFT","NVDA","TSLA",
      "WMT","WDC","MU","PLTR","SAP","RHM","STX","BAC","GS","AXP","LLY",
      "COST","XOM","CAT","CSCO","SIEGY","TJX"]
SD = {}
for s in SS:
    try: SD[s] = load_sym(s)
    except: pass

# Pre-build stock runs
SRUNS = []
for sym, sdata in SD.items():
    ctx = sdata.get("D1") if "D1" in sdata else sdata.get("W1")
    val = sdata.get("H4") if "H4" in sdata else sdata.get("D1")
    entry = sdata.get("H1") if "H1" in sdata else sdata.get("H4")
    if ctx is not None and val is not None and entry is not None:
        SRUNS.append((sym, ctx, val, entry))

print(f"Loaded: {len(XC)} XAU combos, {len(ID)} idx, {len(SD)} stocks ({len(SRUNS)} tradeable)\n")

# =====================================================================
# XAUUSD
# =====================================================================
print("="*120)
print("  XAUUSD OPTIMIZATION")
print("="*120)
t0 = time.time()
xr = []

# Current v7.0 baseline
print("\n  Baselines (v7.0):")
base = get_xauusd_params()
# Individual combos
for i, (name, ctx, val, entry) in enumerate(XC):
    r = met(run_bt(base, [(f"XAU_{name}", ctx, val, entry)]))
    pr(r, f"[{i}] {name}")

# Current 2-combo (v7.0)
r = met(run_bt(base, [(f"XAU_{XC[0][0]}", XC[0][1], XC[0][2], XC[0][3]),
                        (f"XAU_{XC[1][0]}", XC[1][1], XC[1][2], XC[1][3])]))
pr(r, "[0,1] v7.0 baseline")

# Now sweep: only the most impactful params
# Key insight: risk%, momentum, and pb_buffer are the biggest levers
print("\n  Sweep: risk + momentum + pullback (biggest impact params):")
configs = [
    # (risk, mom, pb, sl, trail, be) - targeted combinations
    # Higher risk for more profit
    (3, 45, 2.5, 4.0, 2.5, 2.5),  # v7.0 baseline with r=3
    (4, 45, 2.5, 4.0, 2.5, 2.5),  # r=4
    (5, 45, 2.5, 4.0, 2.5, 2.5),  # r=5 (v7.0)
    (6, 45, 2.5, 4.0, 2.5, 2.5),  # r=6
    (7, 45, 2.5, 4.0, 2.5, 2.5),  # r=7
    (8, 45, 2.5, 4.0, 2.5, 2.5),  # r=8
    # Looser momentum for more trades
    (5, 30, 2.5, 4.0, 2.5, 2.5),
    (5, 35, 2.5, 4.0, 2.5, 2.5),
    (5, 40, 2.5, 4.0, 2.5, 2.5),
    (5, 50, 2.5, 4.0, 2.5, 2.5),
    (5, 55, 2.5, 4.0, 2.5, 2.5),
    # Wider pullback for more trades
    (5, 45, 3.0, 4.0, 2.5, 2.5),
    (5, 45, 3.5, 4.0, 2.5, 2.5),
    (5, 45, 4.0, 4.0, 2.5, 2.5),
    (5, 45, 2.0, 4.0, 2.5, 2.5),
    # Wider SL for better WR
    (5, 45, 2.5, 3.5, 2.5, 2.5),
    (5, 45, 2.5, 4.5, 2.5, 2.5),
    (5, 45, 2.5, 5.0, 2.5, 2.5),
    # Trail variations
    (5, 45, 2.5, 4.0, 2.0, 2.5),
    (5, 45, 2.5, 4.0, 3.0, 2.5),
    (5, 45, 2.5, 4.0, 3.5, 2.5),
    # BE variations
    (5, 45, 2.5, 4.0, 2.5, 1.5),
    (5, 45, 2.5, 4.0, 2.5, 2.0),
    (5, 45, 2.5, 4.0, 2.5, 3.0),
    # Best combos: high risk + loose mom + wider pb
    (6, 35, 3.0, 4.0, 2.5, 2.5),
    (7, 35, 3.0, 4.0, 2.5, 2.5),
    (6, 40, 3.0, 4.0, 2.5, 2.0),
    (7, 40, 3.0, 4.0, 2.5, 2.0),
    (6, 35, 3.5, 4.0, 2.5, 2.0),
    (7, 35, 3.5, 4.0, 2.5, 2.0),
    (8, 35, 3.0, 4.0, 2.5, 2.5),
    (5, 30, 3.5, 4.0, 2.5, 2.0),
    (6, 30, 3.5, 4.0, 2.5, 2.0),
    (7, 30, 3.5, 4.0, 2.5, 2.0),
    (5, 35, 3.5, 4.5, 3.0, 2.0),
    (6, 35, 3.5, 4.5, 3.0, 2.0),
    # Aggressive: max trades + ok WR
    (5, 25, 4.0, 4.0, 2.5, 2.0),
    (5, 25, 4.0, 4.5, 3.0, 2.0),
    (6, 25, 4.0, 4.0, 2.5, 2.0),
    (4, 30, 4.0, 4.5, 3.0, 2.0),
    # Safe: low risk, strict mom, low DD
    (3, 50, 2.5, 4.0, 2.5, 2.5),
    (3, 55, 2.0, 4.0, 2.5, 2.5),
    (4, 50, 2.0, 4.0, 2.0, 2.5),
    (3, 45, 2.0, 4.5, 2.5, 3.0),
]

# Test each config on both TF setups
for tf_idx, tf_label in [([0, 1], "01"), ([0], "0")]:
    runs = [(f"XAU_{XC[i][0]}", XC[i][1], XC[i][2], XC[i][3]) for i in tf_idx]
    for risk, mom, pb, sl, trail, be in configs:
        p = get_xauusd_params()
        p.risk_percent = risk; p.mom_score_min = mom; p.pb_atr_buffer = pb
        p.atr_sl_multiplier = sl; p.atr_trail_multiplier = trail; p.be_rr_ratio = be
        r = met(run_bt(p, runs))
        if r:
            r['sc'] = sc(r)
            cfg = f"tf={tf_label} r={risk} mom={mom} pb={pb} sl={sl} tr={trail} be={be}"
            r['cfg'] = cfg
            r['p'] = dict(tf=tf_idx, risk=risk, mom=mom, pb=pb, sl=sl, trail=trail, be=be)
            if r['wr'] >= 50:
                xr.append(r)
            pr(r, cfg)
    print(f"  --- TF={tf_label} done ---\n")

# Sort and show results
if xr:
    xr.sort(key=lambda x: x['sc'], reverse=True)
    print(f"\n{'='*120}")
    print(f"  XAUUSD TOP CONFIGS (WR>=50%, by composite score)")
    print(f"  {'#':>2} {'Config':<60} {'Tr':>5} {'WR%':>5} {'PnL':>14} {'PF':>5} {'DD%':>7}")
    print("-"*120)
    for i, r in enumerate(xr[:20]):
        print(f"  {i+1:>2} {r['cfg']:<60} {r['tr']:>5} {r['wr']:>5.1f} ${r['pnl']:>12,.0f} "
              f"{r['pf']:>5.2f} {r['dd']:>6.1f}%")

    # Also show by different criteria
    low_dd = sorted([r for r in xr if r['dd'] > -15], key=lambda x: x['pnl'], reverse=True)
    if low_dd:
        print(f"\n  XAUUSD LOWEST DD (<15%) by PnL:")
        for i, r in enumerate(low_dd[:5]):
            print(f"    {i+1}. {r['cfg']:<60} {r['tr']:>4} tr, WR {r['wr']:.1f}%, PF {r['pf']:.2f}, DD {r['dd']:.1f}%, PnL ${r['pnl']:,.0f}")

    most_tr = sorted(xr, key=lambda x: x['tr'], reverse=True)
    print(f"\n  XAUUSD MOST TRADES:")
    for i, r in enumerate(most_tr[:5]):
        print(f"    {i+1}. {r['cfg']:<60} {r['tr']:>4} tr, WR {r['wr']:.1f}%, PF {r['pf']:.2f}, DD {r['dd']:.1f}%, PnL ${r['pnl']:,.0f}")

print(f"\n  XAUUSD done: {len(xr)} valid configs in {time.time()-t0:.0f}s")


# =====================================================================
# INDICES
# =====================================================================
print("\n\n" + "="*120)
print("  INDICES OPTIMIZATION")
print("="*120)
t0 = time.time()
ir = []

# Baseline per symbol per combo
print("\n  Baselines:")
for sym, sdata in ID.items():
    ic = []
    if "W1" in sdata and "D1" in sdata and "H1" in sdata:
        ic.append(("W1/D1/H1", sdata["W1"], sdata["D1"], sdata["H1"]))
    if "W1" in sdata and "D1" in sdata and "H4" in sdata:
        ic.append(("W1/D1/H4", sdata["W1"], sdata["D1"], sdata["H4"]))
    for i, (name, ctx, val, entry) in enumerate(ic):
        r = met(run_bt(get_indices_params(), [(f"{sym}_{name}", ctx, val, entry)]))
        pr(r, f"{sym} {name}")

# Sweep targeted configs
print("\n  Sweep:")
idx_configs = [
    # (risk, mom, pb, sl, trail, be, dir)
    # Strict filter for WR
    (3, 50, 2.0, 4.0, 3.0, 2.0, 'long'),
    (3, 55, 2.0, 4.0, 3.0, 2.0, 'long'),
    (3, 60, 2.0, 4.0, 3.0, 2.0, 'long'),
    (3, 65, 2.0, 4.0, 3.0, 2.0, 'long'),
    (4, 50, 2.0, 4.0, 3.0, 2.0, 'long'),
    (4, 55, 2.0, 4.0, 3.0, 2.0, 'long'),
    (4, 60, 2.0, 4.0, 3.0, 2.0, 'long'),
    (4, 65, 2.0, 4.0, 3.0, 2.0, 'long'),
    # Wider SL
    (3, 55, 2.0, 4.5, 3.0, 2.0, 'long'),
    (3, 55, 2.0, 5.0, 3.0, 2.0, 'long'),
    (4, 55, 2.0, 4.5, 3.0, 2.0, 'long'),
    (4, 55, 2.0, 5.0, 3.0, 2.0, 'long'),
    # Both direction
    (3, 55, 2.0, 4.0, 3.0, 2.0, 'both'),
    (3, 60, 2.0, 4.0, 3.0, 2.0, 'both'),
    (3, 65, 2.0, 4.0, 3.0, 2.0, 'both'),
    (4, 55, 2.0, 4.0, 3.0, 2.0, 'both'),
    (4, 60, 2.0, 4.0, 3.0, 2.0, 'both'),
    # Wider pb for more trades
    (3, 55, 2.5, 4.0, 3.0, 2.0, 'long'),
    (3, 55, 3.0, 4.0, 3.0, 2.0, 'long'),
    (4, 50, 2.5, 4.0, 3.0, 2.0, 'long'),
    (4, 50, 3.0, 4.0, 3.0, 2.0, 'long'),
    # Different trail/BE
    (3, 55, 2.0, 4.0, 2.5, 2.0, 'long'),
    (3, 55, 2.0, 4.0, 3.5, 2.0, 'long'),
    (3, 55, 2.0, 4.0, 3.0, 2.5, 'long'),
    (3, 55, 2.0, 4.0, 3.0, 1.5, 'long'),
    (4, 55, 2.5, 4.5, 3.0, 2.0, 'long'),
    (4, 55, 2.5, 4.5, 3.5, 2.5, 'long'),
    # Aggressive
    (5, 50, 2.5, 4.0, 3.0, 2.0, 'long'),
    (5, 55, 2.5, 4.0, 3.0, 2.0, 'long'),
    (5, 60, 2.0, 4.5, 3.0, 2.5, 'long'),
]

for sym, sdata in ID.items():
    ic = []
    if "W1" in sdata and "D1" in sdata and "H1" in sdata:
        ic.append((0, "W1/D1/H1", sdata["W1"], sdata["D1"], sdata["H1"]))
    if "W1" in sdata and "D1" in sdata and "H4" in sdata:
        ic.append((1, "W1/D1/H4", sdata["W1"], sdata["D1"], sdata["H4"]))

    for ci, cname, ctx, val, entry in ic:
        for risk, mom, pb, sl, trail, be, d in idx_configs:
            p = get_indices_params()
            p.risk_percent = risk; p.mom_score_min = mom; p.pb_atr_buffer = pb
            p.atr_sl_multiplier = sl; p.atr_trail_multiplier = trail
            p.be_rr_ratio = be; p.direction = d
            r = met(run_bt(p, [(f"{sym}_{cname}", ctx, val, entry)]))
            if r:
                cfg = f"{sym}_{cname} r={risk} mom={mom} pb={pb} sl={sl} tr={trail} be={be} {d}"
                r['sc'] = sc(r)
                r['cfg'] = cfg
                r['p'] = dict(sym=sym, ci=ci, risk=risk, mom=mom, pb=pb, sl=sl, trail=trail, be=be, dir=d)
                if r['wr'] >= 50:
                    ir.append(r)
                    pr(r, cfg)

if ir:
    ir.sort(key=lambda x: x['sc'], reverse=True)
    print(f"\n  INDICES TOP CONFIGS (WR>=50%):")
    for i, r in enumerate(ir[:15]):
        print(f"    {i+1}. {r['cfg']:<65} {r['tr']:>4} tr, WR {r['wr']:.1f}%, PF {r['pf']:.2f}, DD {r['dd']:.1f}%, PnL ${r['pnl']:,.0f}")
else:
    print("\n  WARNING: No index config hit WR>=50%. Try different approach.")

print(f"\n  INDICES done: {len(ir)} valid in {time.time()-t0:.0f}s")


# =====================================================================
# STOCKS
# =====================================================================
print("\n\n" + "="*120)
print("  STOCKS OPTIMIZATION")
print("="*120)
t0 = time.time()
sr = []

# Current baseline
print("\n  Baseline (v4.3):")
r = met(run_bt(get_stocks_params(), SRUNS))
pr(r, "v4.3 current")

# Sweep key params
print("\n  Sweep:")
stock_configs = [
    # (risk, mom, pb, sl, trail, be)
    # Risk variations
    (0.5, 35, 3.0, 3.0, 3.0, 2.0),
    (0.75, 35, 3.0, 3.0, 3.0, 2.0),
    (1.0, 35, 3.0, 3.0, 3.0, 2.0),
    (1.5, 35, 3.0, 3.0, 3.0, 2.0),
    (2.0, 35, 3.0, 3.0, 3.0, 2.0),
    (2.5, 35, 3.0, 3.0, 3.0, 2.0),
    # Momentum variations
    (1.0, 25, 3.0, 3.0, 3.0, 2.0),
    (1.0, 30, 3.0, 3.0, 3.0, 2.0),
    (1.0, 40, 3.0, 3.0, 3.0, 2.0),
    (1.0, 45, 3.0, 3.0, 3.0, 2.0),
    # Pullback variations
    (1.0, 35, 2.5, 3.0, 3.0, 2.0),
    (1.0, 35, 3.5, 3.0, 3.0, 2.0),
    (1.0, 35, 4.0, 3.0, 3.0, 2.0),
    (1.0, 35, 4.5, 3.0, 3.0, 2.0),
    # SL variations
    (1.0, 35, 3.0, 2.5, 3.0, 2.0),
    (1.0, 35, 3.0, 3.5, 3.0, 2.0),
    (1.0, 35, 3.0, 4.0, 3.0, 2.0),
    # Trail variations
    (1.0, 35, 3.0, 3.0, 2.5, 2.0),
    (1.0, 35, 3.0, 3.0, 3.5, 2.0),
    (1.0, 35, 3.0, 3.0, 4.0, 2.0),
    # BE variations
    (1.0, 35, 3.0, 3.0, 3.0, 1.5),
    (1.0, 35, 3.0, 3.0, 3.0, 2.5),
    # Combos: more trades (wider pb, lower mom)
    (1.5, 25, 3.5, 3.0, 3.0, 2.0),
    (1.5, 25, 4.0, 3.0, 3.0, 2.0),
    (2.0, 25, 3.5, 3.0, 3.0, 2.0),
    (2.0, 25, 4.0, 3.5, 3.0, 2.0),
    (1.5, 30, 3.5, 3.0, 3.0, 2.0),
    (2.0, 30, 3.5, 3.0, 3.0, 2.0),
    # Combos: low DD (lower risk, strict mom)
    (0.75, 40, 3.0, 3.0, 3.0, 2.0),
    (0.75, 45, 3.0, 3.0, 3.0, 2.0),
    (1.0, 40, 2.5, 3.0, 3.0, 2.5),
    (1.0, 45, 2.5, 3.0, 3.0, 2.5),
    # Combos: max profit (wider, higher risk)
    (2.0, 30, 3.5, 3.5, 3.0, 2.0),
    (2.5, 25, 3.5, 3.5, 3.0, 2.0),
    (2.0, 35, 3.5, 3.5, 3.5, 2.0),
    (2.5, 30, 4.0, 3.5, 3.0, 2.0),
    (1.5, 30, 4.0, 3.5, 3.5, 2.0),
    (2.0, 25, 4.0, 3.5, 3.5, 2.0),
    (1.5, 25, 4.5, 3.0, 3.0, 1.5),
    (2.0, 25, 4.5, 3.5, 3.0, 1.5),
]

cnt = 0
for risk, mom, pb, sl, trail, be in stock_configs:
    p = get_stocks_params()
    p.risk_percent = risk; p.mom_score_min = mom; p.pb_atr_buffer = pb
    p.atr_sl_multiplier = sl; p.atr_trail_multiplier = trail; p.be_rr_ratio = be
    r = met(run_bt(p, SRUNS))
    cnt += 1
    if r:
        cfg = f"r={risk} mom={mom} pb={pb} sl={sl} tr={trail} be={be}"
        r['sc'] = sc(r)
        r['cfg'] = cfg
        r['p'] = dict(risk=risk, mom=mom, pb=pb, sl=sl, trail=trail, be=be)
        if r['wr'] >= 50:
            sr.append(r)
        pr(r, cfg)

if sr:
    sr.sort(key=lambda x: x['sc'], reverse=True)
    print(f"\n  STOCKS TOP CONFIGS (WR>=50%):")
    for i, r in enumerate(sr[:15]):
        print(f"    {i+1}. {r['cfg']:<55} {r['tr']:>5} tr, WR {r['wr']:.1f}%, PF {r['pf']:.2f}, DD {r['dd']:.1f}%, PnL ${r['pnl']:,.0f}")

    # Most trades
    most_tr = sorted(sr, key=lambda x: x['tr'], reverse=True)
    print(f"\n  STOCKS MOST TRADES (WR>=50%):")
    for i, r in enumerate(most_tr[:5]):
        print(f"    {i+1}. {r['cfg']:<55} {r['tr']:>5} tr, WR {r['wr']:.1f}%, PF {r['pf']:.2f}, DD {r['dd']:.1f}%, PnL ${r['pnl']:,.0f}")

print(f"\n  STOCKS done: {len(sr)} valid in {time.time()-t0:.0f}s")


# =====================================================================
# FINAL SUMMARY
# =====================================================================
print("\n\n" + "="*120)
print("  FINAL v8.0 OPTIMIZATION SUMMARY")
print("  Criteria: Max Profit + Min DD + Most Trades + WR > 50%")
print("="*120)

for name, res in [("XAUUSD", xr), ("INDICES", ir), ("STOCKS", sr)]:
    if res:
        res.sort(key=lambda x: x['sc'], reverse=True)
        b = res[0]
        print(f"\n  {name} WINNER:")
        print(f"    {b['cfg']}")
        print(f"    {b['tr']} trades | WR {b['wr']:.1f}% | PF {b['pf']:.2f} | DD {b['dd']:.1f}% | PnL ${b['pnl']:,.0f}")
        print(f"    Params: {b['p']}")
    else:
        print(f"\n  {name}: No config with WR>=50% found")
