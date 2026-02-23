#!/usr/bin/env python3
"""Quick optimizer: Find best single-trade params WITHOUT MT filter (universal)."""
import csv, datetime, math
from dataclasses import dataclass

@dataclass
class Bar:
    o:float; h:float; l:float; c:float; hour:int; minute:int

def load(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            t = int(r['time'])
            dt = datetime.datetime.fromtimestamp(t, tz=datetime.timezone(datetime.timedelta(hours=1)))
            bars.append(Bar(float(r['open']), float(r['high']), float(r['low']), float(r['close']), dt.hour, dt.minute))
    return bars

def sma(v, p):
    r = [None]*len(v); s = sum(v[:p]); r[p-1] = s/p
    for i in range(p, len(v)): s += v[i] - v[i-p]; r[i] = s/p
    return r

def stdev(v, p):
    r = [None]*len(v)
    for i in range(p-1, len(v)):
        w = v[i-p+1:i+1]; m = sum(w)/p; r[i] = math.sqrt(sum((x-m)**2 for x in w)/p)
    return r

def calc_atr(bars, p):
    r = [None]*len(bars)
    for i in range(1, len(bars)):
        tr = max(bars[i].h-bars[i].l, abs(bars[i].h-bars[i-1].c), abs(bars[i].l-bars[i-1].c))
        if i >= p and r[i-1]: r[i] = (r[i-1]*(p-1)+tr)/p
        elif i >= p:
            trs = [max(bars[j].h-bars[j].l, abs(bars[j].h-bars[j-1].c), abs(bars[j].l-bars[j-1].c)) for j in range(i-p+1, i+1)]
            r[i] = sum(trs)/len(trs)
        elif i == 1: r[i] = tr
    return r

def calc_bb(bars, l, m):
    c = [b.c for b in bars]; ba = sma(c, l); dv = stdev(c, l)
    n = len(bars); u = [None]*n; lo = [None]*n
    for i in range(n):
        if ba[i] and dv[i]: u[i] = ba[i]+dv[i]*m; lo[i] = ba[i]-dv[i]*m
    return u, ba, lo

@dataclass
class T:
    idx:int; d:str; ep:float; sl:float; tp:float
    xi:int=-1; xp:float=0; pnl:float=0; r:str=""

def bt(bars, bbu, bbb, bbl, atr, sh, sm, eh, em, mode, slt, slv, tpt, tpv, comm=4.0):
    """Single-trade backtest, NO MT filter, Long only."""
    trades = []; opn = None; st = sh*60+sm; et = eh*60+em; traded = False; pi = False
    for i in range(1, len(bars)):
        b = bars[i]; p = bars[i-1]; ct = b.hour*60+b.minute
        inw = ct >= st and ct < et; atc = ct >= et and ct < (et+5)
        if inw and not pi: traded = False; opn = None
        pi = inw
        if opn:
            if b.l <= opn.sl: opn.xi=i; opn.xp=opn.sl; opn.pnl=opn.xp-opn.ep-comm; opn.r='SL'; opn=None
            elif b.h >= opn.tp: opn.xi=i; opn.xp=opn.tp; opn.pnl=opn.xp-opn.ep-comm; opn.r='TP'; opn=None
        if atc and opn:
            opn.xi=i; opn.xp=b.c; opn.pnl=opn.xp-opn.ep-comm; opn.r='EOD'; opn=None
        if not inw or traded: continue
        u = bbu[i]; lo = bbl[i]; ba = bbb[i]
        if not u or not lo or not ba: continue
        up = bbu[i-1]; lp = bbl[i-1]
        if not up or not lp: continue
        ib = b.c > b.o
        bo_l = b.c > u and p.c <= up and ib
        mr_l = b.c > lo and (p.c < lp or b.l < lo) and ib
        sig = False
        if mode == 'bo': sig = bo_l
        elif mode == 'mr': sig = mr_l
        else: sig = bo_l or mr_l
        if not sig: continue
        a = atr[i] if atr[i] else 5.0
        if slt == 'a': sl = b.c - a*slv
        elif slt == 'f': sl = b.c - slv
        else: sl = ba  # bb mitte
        sd = max(abs(b.c - sl), 0.01)
        if tpt == 'r': tp = b.c + sd*tpv
        elif tpt == 'f': tp = b.c + tpv
        else: tp = max(u, b.c + sd*1.5)  # gegenband
        t = T(i, 'L', b.c, sl, tp); trades.append(t); opn = t; traded = True
    if opn:
        opn.xi=len(bars)-1; opn.xp=bars[-1].c; opn.pnl=opn.xp-opn.ep-comm; opn.r='END'
    return trades

def pnl(trades): return sum(t.pnl for t in trades)

def score(trades):
    if not trades: return -99999, 0, 0, 0, 0
    p = pnl(trades); w = sum(1 for t in trades if t.pnl > 0); wr = w/len(trades)*100
    gp = sum(t.pnl for t in trades if t.pnl > 0)
    gl = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = gp/gl if gl > 0 else 999
    eq = pk = dd = 0
    for t in trades: eq += t.pnl; pk = max(pk, eq); dd = max(dd, pk-eq)
    return p, len(trades), wr, pf, dd

def main():
    print("=== UNIVERSAL SINGLE-TRADE OPTIMIZER (ohne MT) ===\n")
    esh = load('/home/user/Robin/CAPITALCOM_ESH2026, 1.csv')
    us = load('/home/user/Robin/CAPITALCOM_US100, 1.csv')
    print(f"ESH: {len(esh)} | US100: {len(us)}\n")

    tws = [
        (15,30,16,0),(15,30,16,15),(15,30,16,30),(15,30,16,45),
        (15,30,17,0),(15,30,17,30),(15,30,17,55),(15,30,18,0),
        (15,30,18,30),(15,30,19,0),(15,30,20,0),(15,30,21,0),(15,30,22,0),
        (15,35,16,5),(15,35,16,30),(15,35,17,0),
        (15,25,16,0),(15,25,16,30),(15,25,17,0),
    ]

    # BB params (no CCI/MT needed)
    bb_combos = [
        (5, 1.0), (5, 1.5), (5, 2.0), (5, 2.5), (5, 3.0),
        (7, 1.0), (7, 1.5), (7, 2.0), (7, 2.5), (7, 3.0),
        (10, 1.0), (10, 1.5), (10, 2.0), (10, 2.5), (10, 3.0),
        (14, 1.0), (14, 1.5), (14, 2.0), (14, 2.5), (14, 3.0),
        (20, 1.5), (20, 2.0), (20, 2.5), (20, 3.0),
        (28, 2.0), (28, 2.5), (28, 3.0),
    ]
    atr_lens = [5, 7, 10, 14]
    modes = ['bo', 'mr', 'co']

    slc = [
        ('a',0.8),('a',1.0),('a',1.2),('a',1.5),('a',1.8),('a',2.0),('a',2.5),('a',3.0),('a',3.5),('a',4.0),
        ('f',5),('f',8),('f',10),('f',15),('f',20),('f',30),('f',50),('f',72),('f',100),
        ('b',0),
    ]
    tpc = [
        ('r',0.5),('r',1.0),('r',1.5),('r',2.0),('r',2.5),('r',3.0),('r',4.0),('r',5.0),('r',7.0),('r',10.0),
        ('f',10),('f',15),('f',20),('f',30),('f',50),('f',72),('f',100),('f',150),
        ('o',0),
    ]

    # Stage 1: Find best BB+TW+Mode
    print("=== STAGE 1: BB + Zeitfenster + Modus ===")
    total = len(bb_combos) * len(atr_lens) * len(tws) * len(modes)
    print(f"Teste {total} Kombos...")
    results = []; n = 0

    for bl, bm in bb_combos:
        bbu_e, bbb_e, bbl_e = calc_bb(esh, bl, bm)
        bbu_u, bbb_u, bbl_u = calc_bb(us, bl, bm)
        for al in atr_lens:
            atr_e = calc_atr(esh, al)
            atr_u = calc_atr(us, al)
            for tw in tws:
                for m in modes:
                    te = bt(esh, bbu_e, bbb_e, bbl_e, atr_e, tw[0],tw[1],tw[2],tw[3], m, 'a',2.0, 'r',1.5)
                    tu = bt(us, bbu_u, bbb_u, bbl_u, atr_u, tw[0],tw[1],tw[2],tw[3], m, 'a',2.0, 'r',1.5)
                    pe = pnl(te); pu = pnl(tu)
                    _,ne,we,_,_ = score(te)
                    sc = pe + pu  # Combined score for universality
                    conf = (bl, bm, al, tw, m)
                    results.append((sc, pe, pu, conf, ne, we))
                    n += 1
                    if n % 5000 == 0:
                        results.sort(reverse=True); results = results[:50]
                        print(f"  {n}/{total} | Best combined: {results[0][1]:+.1f}+{results[0][2]:+.1f}={results[0][0]:+.1f}")

    results.sort(reverse=True)
    print(f"\nS1 fertig: {n}")
    print(f"\nTop 15 (ESH+US100 combined, ohne MT):")
    print(f"  {'Comb':>7} {'ESH':>7} {'US100':>7} {'#E':>3} {'WR':>5} | BB ATR TW Mode")
    print("  " + "-"*75)
    for sc, pe, pu, conf, ne, we in results[:15]:
        bl, bm, al, tw, m = conf
        print(f"  {sc:+7.1f} {pe:+7.1f} {pu:+7.1f} {ne:3d} {we:4.0f}% | BB={bl}/{bm} ATR={al} {tw[0]:02d}:{tw[1]:02d}-{tw[2]:02d}:{tw[3]:02d} {m}")

    # Stage 2: SL/TP optimization on top configs
    print("\n=== STAGE 2: SL/TP Optimierung ===")
    tops = set()
    for _, _, _, conf, _, _ in results[:25]: tops.add(conf)
    print(f"Teste {len(tops)} Top-Configs...")

    bep = -99999; bup = -99999; bcp = -99999
    bef = None; buf = None; bcf = None; s2 = 0

    for conf in tops:
        bl, bm, al, tw, m = conf
        bbu_e, bbb_e, bbl_e = calc_bb(esh, bl, bm)
        bbu_u, bbb_u, bbl_u = calc_bb(us, bl, bm)
        atr_e = calc_atr(esh, al); atr_u = calc_atr(us, al)
        for slt, slv in slc:
            for tpt, tpv in tpc:
                te = bt(esh, bbu_e, bbb_e, bbl_e, atr_e, tw[0],tw[1],tw[2],tw[3], m, slt, slv, tpt, tpv)
                tu = bt(us, bbu_u, bbb_u, bbl_u, atr_u, tw[0],tw[1],tw[2],tw[3], m, slt, slv, tpt, tpv)
                pe = pnl(te); pu = pnl(tu)
                full = (conf, slt, slv, tpt, tpv)
                if pe > bep: bep = pe; bef = (full, te)
                if pu > bup: bup = pu; buf = (full, tu)
                if pe+pu > bcp: bcp = pe+pu; bcf = (full, te, tu)
                s2 += 1
                if s2 % 20000 == 0:
                    print(f"  S2: {s2} | ESH={bep:+.1f} US={bup:+.1f} Comb={bcp:+.1f}")

    print(f"S2 fertig: {s2}")

    # Stage 3: Fine-tune TW
    print("\n=== STAGE 3: TW Feintuning ===")
    if bcf:
        full = bcf[0]; conf = full[0]; slt, slv, tpt, tpv = full[1:]
        bl, bm, al, tw, m = conf
        bbu_e, bbb_e, bbl_e = calc_bb(esh, bl, bm)
        bbu_u, bbb_u, bbl_u = calc_bb(us, bl, bm)
        atr_e = calc_atr(esh, al); atr_u = calc_atr(us, al)
        btp = bcp; btw = tw
        for sh in range(max(0,tw[0]-1), min(24,tw[0]+2)):
            for sm in range(0, 60, 5):
                for eh in range(sh, min(24, sh+8)):
                    for em in range(0, 60, 5):
                        if eh*60+em <= sh*60+sm+15: continue
                        if eh*60+em > sh*60+sm+480: continue
                        te = bt(esh, bbu_e, bbb_e, bbl_e, atr_e, sh,sm,eh,em, m, slt, slv, tpt, tpv)
                        tu = bt(us, bbu_u, bbb_u, bbl_u, atr_u, sh,sm,eh,em, m, slt, slv, tpt, tpv)
                        cp = pnl(te) + pnl(tu)
                        if cp > btp: btp = cp; btw = (sh,sm,eh,em)
        if btw != tw:
            te = bt(esh, bbu_e, bbb_e, bbl_e, atr_e, btw[0],btw[1],btw[2],btw[3], m, slt, slv, tpt, tpv)
            tu = bt(us, bbu_u, bbb_u, bbl_u, atr_u, btw[0],btw[1],btw[2],btw[3], m, slt, slv, tpt, tpv)
            print(f"  Verbessert: {btw[0]:02d}:{btw[1]:02d}-{btw[2]:02d}:{btw[3]:02d} Comb={btp:+.1f} (war {bcp:+.1f})")
            bcp = btp; nc = (bl,bm,al,btw,m); bcf = ((nc,slt,slv,tpt,tpv), te, tu)
        else:
            print("  Keine Verbesserung")

    # Stage 4: Fine SL/TP
    print("\n=== STAGE 4: SL/TP Feintuning ===")
    if bcf:
        full = bcf[0]; conf = full[0]; slt, slv, tpt, tpv = full[1:]
        bl, bm, al, tw, m = conf
        bbu_e, bbb_e, bbl_e = calc_bb(esh, bl, bm)
        bbu_u, bbb_u, bbl_u = calc_bb(us, bl, bm)
        atr_e = calc_atr(esh, al); atr_u = calc_atr(us, al)
        bfp = bcp; bfs = (slt, slv); bftp = (tpt, tpv)
        if slt == 'a': slr = [slv+x*0.02 for x in range(-20,21) if slv+x*0.02 > 0.2]
        elif slt == 'f': slr = [slv+x*max(0.5,slv*0.03) for x in range(-20,21) if slv+x*max(0.5,slv*0.03) > 0.5]
        else: slr = [0]
        if tpt == 'r': tpr = [tpv+x*0.02 for x in range(-20,21) if tpv+x*0.02 > 0.2]
        elif tpt == 'f': tpr = [tpv+x*max(0.5,tpv*0.03) for x in range(-20,21) if tpv+x*max(0.5,tpv*0.03) > 0.5]
        else: tpr = [0]
        for sv2 in slr:
            for tv2 in tpr:
                te = bt(esh, bbu_e, bbb_e, bbl_e, atr_e, tw[0],tw[1],tw[2],tw[3], m, slt, sv2, tpt, tv2)
                tu = bt(us, bbu_u, bbb_u, bbl_u, atr_u, tw[0],tw[1],tw[2],tw[3], m, slt, sv2, tpt, tv2)
                cp = pnl(te) + pnl(tu)
                if cp > bfp: bfp = cp; bfs = (slt, sv2); bftp = (tpt, tv2)
        if bfp > bcp:
            te = bt(esh, bbu_e, bbb_e, bbl_e, atr_e, tw[0],tw[1],tw[2],tw[3], m, bfs[0], bfs[1], bftp[0], bftp[1])
            tu = bt(us, bbu_u, bbb_u, bbl_u, atr_u, tw[0],tw[1],tw[2],tw[3], m, bfs[0], bfs[1], bftp[0], bftp[1])
            print(f"  SL={bfs[0]}:{bfs[1]:.2f} TP={bftp[0]}:{bftp[1]:.2f} Comb={bfp:+.1f} (war {bcp:+.1f})")
            bcp = bfp; bcf = (((bl,bm,al,tw,m), bfs[0],bfs[1],bftp[0],bftp[1]), te, tu)
        else:
            print("  Keine Verbesserung")

    # RESULT
    print("\n" + "="*80)
    print("BESTES UNIVERSELLES SINGLE-TRADE SETUP (ohne MT-Filter)")
    print("="*80)
    if bcf:
        full = bcf[0]; te = bcf[1]; tu = bcf[2]
        conf = full[0]; slt, slv, tpt, tpv = full[1:]
        bl, bm, al, tw, m = conf
        pe, ne, we, pfe, de = score(te)
        pu, nu, wu, pfu, du = score(tu)
        ms = {'bo':'Breakout', 'mr':'Mean Reversion', 'co':'Kombiniert'}[m]
        ss = {'a':'ATR', 'f':'Fest (Punkte)', 'b':'BB Mitte'}[slt]
        ts = {'r':'RR Verhaeltnis', 'f':'Fest (Punkte)', 'o':'Gegenband BB'}[tpt]

        print(f"""
PINE EINSTELLUNGEN:
  i_startH={tw[0]}  i_startM={tw[1]}  i_endH={tw[2]}  i_endM={tw[3]}
  i_bbLen={bl}  i_bbMult={bm}
  i_atrLen={al}
  i_mode="{ms}"  i_needMT=false
  i_slType="{ss}"  i_slAtr={slv if slt=='a' else 2.5}  i_slFix={slv if slt=='f' else 50.0}
  i_tpType="{ts}"  i_tpRR={tpv if tpt=='r' else 1.5}  i_tpFix={tpv if tpt=='f' else 100.0}
  i_maxTrades=1  pyramiding=1  i_tradeLong=true  i_tradeShort=false

ESH2026: PnL={pe:+.1f} Trades={ne} WR={we:.1f}% PF={pfe:.2f} MaxDD={de:.1f} Avg={pe/ne if ne else 0:+.1f}
US100:   PnL={pu:+.1f} Trades={nu} WR={wu:.1f}% PF={pfu:.2f} MaxDD={du:.1f} Avg={pu/nu if nu else 0:+.1f}
TOTAL:   PnL={pe+pu:+.1f}
""")
        print("  ESH2026 Trades:")
        eq = 0
        for i, t in enumerate(te):
            eq += t.pnl
            print(f"  #{i+1:2d} E={t.ep:.1f} X={t.xp:.1f} PnL={t.pnl:+.1f} {t.r:3s} | Eq={eq:+.1f}")
        print(f"\n  US100 Trades:")
        eq = 0
        for i, t in enumerate(tu):
            eq += t.pnl
            print(f"  #{i+1:2d} E={t.ep:.1f} X={t.xp:.1f} PnL={t.pnl:+.1f} {t.r:3s} | Eq={eq:+.1f}")

if __name__ == '__main__':
    main()
