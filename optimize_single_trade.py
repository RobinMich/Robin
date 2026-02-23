#!/usr/bin/env python3
"""Single-Trade Optimizer: Findet den EINEN besten Trade pro Tag ab 15:30."""
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
    r = [None]*len(v)
    if len(v) < p: return r
    s = sum(v[:p]); r[p-1] = s/p
    for i in range(p, len(v)): s += v[i] - v[i-p]; r[i] = s/p
    return r

def stdev(v, p):
    r = [None]*len(v)
    for i in range(p-1, len(v)):
        w = v[i-p+1:i+1]; m = sum(w)/p; r[i] = math.sqrt(sum((x-m)**2 for x in w)/p)
    return r

def calc_cci(bars, p):
    tp = [(b.h+b.l+b.c)/3 for b in bars]; sm = sma(tp, p); r = [None]*len(bars)
    for i in range(p-1, len(bars)):
        if not sm[i]: continue
        w = tp[i-p+1:i+1]; md = sum(abs(x-sm[i]) for x in w)/p
        r[i] = (tp[i]-sm[i])/(0.015*md) if md > 0 else 0
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

def calc_mt(bars, cci_v, atr_v, mult):
    n = len(bars); mt = [None]*n; bull = [False]*n
    for i in range(n):
        if cci_v[i] is None or atr_v[i] is None:
            if i > 0: mt[i] = mt[i-1]; bull[i] = bull[i-1]
            continue
        up = bars[i].l - atr_v[i]*mult; dn = bars[i].h + atr_v[i]*mult
        if cci_v[i] >= 0:
            prev = mt[i-1] if i > 0 and mt[i-1] is not None else up
            mt[i] = max(up, prev); bull[i] = True
        else:
            prev = mt[i-1] if i > 0 and mt[i-1] is not None else dn
            mt[i] = min(dn, prev); bull[i] = False
    return mt, bull

def calc_bb(bars, l, m):
    c = [b.c for b in bars]; ba = sma(c, l); dv = stdev(c, l)
    n = len(bars); u = [None]*n; lo = [None]*n
    for i in range(n):
        if ba[i] and dv[i]: u[i] = ba[i]+dv[i]*m; lo[i] = ba[i]-dv[i]*m
    return u, ba, lo

class Ind:
    def __init__(s, bars, cp, ap, am, bl, bm):
        c = calc_cci(bars, cp); a = calc_atr(bars, ap)
        s.atr = a; s.mt, s.bull = calc_mt(bars, c, a, am)
        s.bbu, s.bbb, s.bbl = calc_bb(bars, bl, bm)

@dataclass
class T:
    idx:int; d:str; ep:float; sl:float; tp:float
    xi:int=-1; xp:float=0; pnl:float=0; r:str=""

def bt_single(bars, ind, sh, sm, eh, em, mode, nmt, slt, slv, tpt, tpv, tl, ts, comm=4.0):
    """Backtest: NUR 1 Trade pro Sitzung, erster passender Signal."""
    trades = []; opn = None; st = sh*60+sm; et = eh*60+em; traded = False; pi = False
    for i in range(1, len(bars)):
        b = bars[i]; p = bars[i-1]; ct = b.hour*60+b.minute
        inw = ct >= st and ct < et; atc = ct >= et and ct < (et+5)
        if inw and not pi:
            traded = False
            opn = None
        pi = inw

        # Check open trade for SL/TP
        if opn:
            if opn.d == 'L':
                if b.l <= opn.sl: opn.xi=i; opn.xp=opn.sl; opn.pnl=opn.xp-opn.ep-comm; opn.r='SL'; opn=None
                elif b.h >= opn.tp: opn.xi=i; opn.xp=opn.tp; opn.pnl=opn.xp-opn.ep-comm; opn.r='TP'; opn=None
            else:
                if b.h >= opn.sl: opn.xi=i; opn.xp=opn.sl; opn.pnl=opn.ep-opn.xp-comm; opn.r='SL'; opn=None
                elif b.l <= opn.tp: opn.xi=i; opn.xp=opn.tp; opn.pnl=opn.ep-opn.xp-comm; opn.r='TP'; opn=None

        # EOD close
        if atc and opn:
            opn.xi=i; opn.xp=b.c
            opn.pnl = (opn.xp-opn.ep if opn.d=='L' else opn.ep-opn.xp) - comm
            opn.r = 'EOD'; opn = None

        if not inw or traded: continue

        # Signal detection
        u = ind.bbu[i]; lo = ind.bbl[i]; ba = ind.bbb[i]
        if not u or not lo or not ba: continue
        up = ind.bbu[i-1]; lp = ind.bbl[i-1]
        if not up or not lp: continue

        ib = b.c > b.o; ie = b.c < b.o; mb = ind.bull[i]
        bo_l = b.c > u and p.c <= up and ib
        bo_s = b.c < lo and p.c >= lp and ie
        mr_l = b.c > lo and (p.c < lp or b.l < lo) and ib
        mr_s = b.c < u and (p.c > up or b.h > u) and ie

        ls = ss = False
        if mode == 'bo': ls, ss = bo_l, bo_s
        elif mode == 'mr': ls, ss = mr_l, mr_s
        else: ls, ss = bo_l or mr_l, bo_s or mr_s
        if nmt: ls = ls and mb; ss = ss and not mb
        ls = ls and tl; ss = ss and ts

        sig = None
        if ls: sig = 'L'
        elif ss: sig = 'S'
        if not sig: continue

        # Place single trade
        a = ind.atr[i]
        if sig == 'L':
            sl = b.c - (a*slv if slt=='a' and a else slv if slt=='f' else abs(b.c-ba))
            sd = max(abs(b.c-sl), 0.01)
            tp = b.c + (sd*tpv if tpt=='r' else tpv if tpt=='f' else max(u-b.c, sd*1.5))
        else:
            sl = b.c + (a*slv if slt=='a' and a else slv if slt=='f' else abs(ba-b.c))
            sd = max(abs(sl-b.c), 0.01)
            tp = b.c - (sd*tpv if tpt=='r' else tpv if tpt=='f' else max(b.c-lo, sd*1.5))

        t = T(i, sig, b.c, sl, tp); trades.append(t); opn = t; traded = True

    if opn:
        opn.xi = len(bars)-1; opn.xp = bars[-1].c
        opn.pnl = (opn.xp-opn.ep if opn.d=='L' else opn.ep-opn.xp) - comm
        opn.r = 'END'
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

def generate_log(bars, trades, name, tw, path):
    stH, stM, enH, enM = tw
    st_min = stH*60+stM; en_min = enH*60+enM
    entry_at = {t.idx: t for t in trades}
    exit_at = {t.xi: t for t in trades if t.xi >= 0}
    rows = []; in_window = False; sess_pnl = 0.0

    for i, b in enumerate(bars):
        ct = b.hour*60+b.minute; was_in = in_window
        in_window = ct >= st_min and ct < en_min

        if in_window and not was_in:
            sess_pnl = 0.0
            rows.append(f"=== SITZUNG START === {name} | {stH}:{stM:02d}-{enH}:{enM:02d}")
        if i in entry_at:
            t = entry_at[i]
            d = "LONG" if t.d == 'L' else "SHORT"
            rows.append(f"{d} @ {t.ep:.2f} | SL: {t.sl:.2f} (-{abs(t.ep-t.sl):.1f}) | TP: {t.tp:.2f} (+{abs(t.tp-t.ep):.1f})")
        if i in exit_at:
            t = exit_at[i]
            sess_pnl += t.pnl
            r = "WIN" if t.pnl >= 0 else "LOSS"
            rows.append(f"   {r} | Entry: {t.ep:.2f} Exit: {t.xp:.2f} | PnL: {t.pnl:+.2f} [{t.r}]")
        if not in_window and was_in:
            rows.append(f"=== SITZUNG ENDE === PnL: {sess_pnl:+.2f}")

    with open(path, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Nr', 'Nachricht'])
        for i, msg in enumerate(rows): w.writerow([i+1, msg])
    print(f"  Log: {path} ({len(rows)} Zeilen)")


def main():
    print("=== SINGLE-TRADE OPTIMIZER ===")
    print("Strategie: 1 Trade pro Tag, erster Signal nach 15:30\n")

    esh = load('/home/user/Robin/CAPITALCOM_ESH2026, 1.csv')
    us = load('/home/user/Robin/CAPITALCOM_US100, 1.csv')
    print(f"ESH: {len(esh)} Bars | US100: {len(us)} Bars\n")

    # Time windows focused on 15:30 start (US market open)
    tws = [
        (15,30,16,0), (15,30,16,15), (15,30,16,30), (15,30,16,45),
        (15,30,17,0), (15,30,17,30), (15,30,17,55),
        (15,30,18,0), (15,30,18,30), (15,30,19,0),
        (15,30,20,0), (15,30,21,0), (15,30,22,0),
        (15,35,16,5), (15,35,16,30), (15,35,17,0),
        (15,25,16,0), (15,25,16,30), (15,25,17,0),
    ]

    # Broader indicator space for single-trade (need quality signals)
    ind_combos = [
        # CCI, ATR_P, ATR_M, BB_L, BB_M
        (10,5,1.0,10,1.5), (10,7,1.0,14,2.0), (10,5,0.5,10,2.0),
        (14,5,1.0,10,1.5), (14,5,1.0,14,2.0), (14,7,1.0,14,2.0),
        (14,10,1.5,14,2.0), (14,5,2.0,14,2.0), (14,7,1.5,10,2.0),
        (14,10,1.0,20,2.0), (14,5,0.5,14,1.5), (14,7,1.0,10,1.5),
        (20,5,1.0,10,1.5), (20,7,1.0,14,2.0), (20,10,1.5,14,2.0),
        (20,5,1.0,14,2.5), (20,7,2.0,14,2.0), (20,10,1.0,20,2.5),
        (20,5,0.5,10,2.0), (20,14,1.5,20,2.0), (20,7,1.0,10,1.5),
        (28,5,1.0,10,1.5), (28,7,1.0,14,2.0), (28,10,1.5,14,2.0),
        (28,10,2.5,14,2.0), (28,7,2.0,14,2.5), (28,10,1.0,20,2.0),
        (28,5,0.5,14,1.5), (28,14,1.5,20,2.5), (28,7,1.0,10,2.0),
        (28,5,1.5,14,2.0), (28,10,2.0,10,2.5),
        (35,5,1.0,14,2.0), (35,7,1.5,14,2.0), (35,10,1.0,20,2.5),
        (35,14,2.0,14,2.0), (35,7,1.0,10,1.5), (35,5,2.0,14,2.5),
        (35,10,0.5,20,2.0), (35,7,2.5,14,2.0), (35,10,1.5,10,2.0),
        (35,5,1.0,20,3.0), (35,7,1.0,10,2.0),
        (50,7,1.0,14,2.0), (50,10,1.5,20,2.5), (50,5,1.0,10,1.5),
    ]

    modes = ['bo', 'mr', 'co']
    mt_opts = [True, False]

    # Stage 1: Find best indicator+time combos (only Long, single trade)
    print("=== STAGE 1: Indikator + Zeitfenster ===")
    total = len(ind_combos) * len(tws) * len(modes) * len(mt_opts)
    print(f"Teste {total} Kombinationen...")
    results = []; n = 0

    for ic in ind_combos:
        ie = Ind(esh, *ic); iu = Ind(us, *ic)
        for tw in tws:
            for m in modes:
                for nmt in mt_opts:
                    te = bt_single(esh, ie, tw[0],tw[1],tw[2],tw[3], m, nmt, 'a',2.0, 'r',1.5, True, False)
                    tu = bt_single(us, iu, tw[0],tw[1],tw[2],tw[3], m, nmt, 'a',2.0, 'r',1.5, True, False)
                    pe = pnl(te); pu = pnl(tu)
                    _,ne,we,_,_ = score(te)
                    conf = (ic, tw, m, nmt)
                    # Score: PnL + Bonus fuer hohe WR (Single-Trade braucht Zuverlaessigkeit)
                    sc = pe + (we - 50) * 2 if ne >= 3 else pe - 100
                    results.append((sc, pe, pu, conf, ne, we))
                    n += 1
                    if n % 5000 == 0:
                        results.sort(reverse=True)
                        results = results[:60]
                        print(f"  {n}/{total} | Best: {results[0][1]:+.1f} Pkt ({results[0][4]} Trades, {results[0][5]:.0f}% WR)")

    results.sort(reverse=True)
    print(f"\nS1 fertig: {n} getestet")
    print("\nTop 15 ESH2026:")
    print(f"  {'Score':>7} {'PnL':>7} {'#':>3} {'WR':>5} | CCI ATR BB TW Mode MT")
    print("  " + "-"*70)
    for sc, pe, pu, conf, ne, we in results[:15]:
        ic, tw, m, nmt = conf
        print(f"  {sc:+7.1f} {pe:+7.1f} {ne:3d} {we:4.0f}% | CCI={ic[0]:2d} ATR={ic[1]}/{ic[2]} BB={ic[3]}/{ic[4]} {tw[0]:02d}:{tw[1]:02d}-{tw[2]:02d}:{tw[3]:02d} {m} MT={nmt}")

    # Stage 2: SL/TP fine-tuning on top configs
    print("\n=== STAGE 2: SL/TP Optimierung ===")
    tops = set()
    for _, _, _, conf, _, _ in results[:30]: tops.add(conf)
    print(f"Teste {len(tops)} Top-Configs mit SL/TP Grid...")

    slc = [
        ('a',0.8),('a',1.0),('a',1.2),('a',1.5),('a',1.8),('a',2.0),('a',2.2),('a',2.5),('a',3.0),('a',3.5),('a',4.0),
        ('f',5),('f',8),('f',10),('f',12),('f',15),('f',18),('f',20),('f',25),('f',30),('f',40),('f',50),('f',60),('f',72),('f',80),('f',100),
        ('b',0),
    ]
    tpc = [
        ('r',0.5),('r',0.8),('r',1.0),('r',1.2),('r',1.5),('r',2.0),('r',2.5),('r',3.0),('r',4.0),('r',5.0),('r',7.0),('r',10.0),
        ('f',5),('f',8),('f',10),('f',15),('f',20),('f',25),('f',30),('f',40),('f',50),('f',60),('f',72),('f',80),('f',100),('f',120),('f',150),
        ('o',0),
    ]

    bep = -99999; bup = -99999
    bef = None; buf = None; s2 = 0

    for conf in tops:
        ic, tw, m, nmt = conf
        ie = Ind(esh, *ic); iu = Ind(us, *ic)
        for slt, slv in slc:
            for tpt, tpv in tpc:
                te = bt_single(esh, ie, tw[0],tw[1],tw[2],tw[3], m, nmt, slt, slv, tpt, tpv, True, False)
                tu = bt_single(us, iu, tw[0],tw[1],tw[2],tw[3], m, nmt, slt, slv, tpt, tpv, True, False)
                pe = pnl(te); pu = pnl(tu)
                full = (conf, slt, slv, tpt, tpv)
                if pe > bep: bep = pe; bef = (full, te)
                if pu > bup: bup = pu; buf = (full, tu)
                s2 += 1
                if s2 % 20000 == 0:
                    print(f"  S2: {s2} | ESH={bep:+.1f} US100={bup:+.1f}")

    print(f"S2 fertig: {s2} getestet")

    # Stage 3: Fine-tune time window
    print("\n=== STAGE 3: Zeitfenster Feintuning ===")
    if bef:
        full = bef[0]; conf = full[0]; slt, slv, tpt, tpv = full[1:]
        ic, tw, m, nmt = conf
        ie = Ind(esh, *ic); btp = bep; btw = tw; btt = bef[1]
        for sh in range(max(0, tw[0]-1), min(24, tw[0]+2)):
            for sm in range(0, 60, 5):
                for eh in range(sh, min(24, sh+8)):
                    for em in range(0, 60, 5):
                        if eh*60+em <= sh*60+sm+15: continue  # min 15 min window
                        if eh*60+em > sh*60+sm+480: continue  # max 8h window
                        te = bt_single(esh, ie, sh, sm, eh, em, m, nmt, slt, slv, tpt, tpv, True, False)
                        pe = pnl(te)
                        if pe > btp: btp = pe; btw = (sh,sm,eh,em); btt = te
        if btw != tw:
            print(f"  Verbessert: {btw[0]:02d}:{btw[1]:02d}-{btw[2]:02d}:{btw[3]:02d} PnL={btp:+.1f} (war {bep:+.1f})")
            bep = btp; nc = (ic, btw, m, nmt); bef = ((nc, slt, slv, tpt, tpv), btt)
        else:
            print("  Keine Verbesserung")

    # Stage 4: Fine SL/TP
    print("\n=== STAGE 4: SL/TP Feintuning ===")
    if bef:
        full = bef[0]; conf = full[0]; slt, slv, tpt, tpv = full[1:]
        ic, tw, m, nmt = conf
        ie = Ind(esh, *ic); bfp = bep; bft = bef[1]; bfs = (slt, slv); bftp = (tpt, tpv)
        if slt == 'a': slr = [slv+x*0.02 for x in range(-20,21) if slv+x*0.02 > 0.2]
        elif slt == 'f': slr = [slv+x*max(0.5, slv*0.03) for x in range(-20,21) if slv+x*max(0.5, slv*0.03) > 0.5]
        else: slr = [0]
        if tpt == 'r': tpr = [tpv+x*0.02 for x in range(-20,21) if tpv+x*0.02 > 0.2]
        elif tpt == 'f': tpr = [tpv+x*max(0.5, tpv*0.03) for x in range(-20,21) if tpv+x*max(0.5, tpv*0.03) > 0.5]
        else: tpr = [0]
        for sv2 in slr:
            for tv2 in tpr:
                te = bt_single(esh, ie, tw[0],tw[1],tw[2],tw[3], m, nmt, slt, sv2, tpt, tv2, True, False)
                pe = pnl(te)
                if pe > bfp: bfp = pe; bft = te; bfs = (slt, sv2); bftp = (tpt, tv2)
        if bfp > bep:
            print(f"  SL={bfs[0]}:{bfs[1]:.2f} TP={bftp[0]}:{bftp[1]:.2f} PnL={bfp:+.1f} (war {bep:+.1f})")
            bep = bfp; bef = (((ic,tw,m,nmt), bfs[0],bfs[1],bftp[0],bftp[1]), bft)
        else:
            print("  Keine Verbesserung")

    # ERGEBNIS
    print("\n" + "="*80)
    print("BESTES SINGLE-TRADE SETUP (ESH2026)")
    print("="*80)
    if bef:
        full = bef[0]; trades = bef[1]
        conf = full[0]; slt, slv, tpt, tpv = full[1:]
        ic, tw, m, nmt = conf
        p, nt, wr, pf, dd = score(trades)
        ms = {'bo':'Breakout', 'mr':'Mean Reversion', 'co':'Kombiniert'}[m]
        ss = {'a':'ATR', 'f':'Fest (Punkte)', 'b':'BB Mitte'}[slt]
        ts_ = {'r':'RR Verhaeltnis', 'f':'Fest (Punkte)', 'o':'Gegenband BB'}[tpt]

        print(f"""
PINE EINSTELLUNGEN:
  i_startH={tw[0]}  i_startM={tw[1]}  i_endH={tw[2]}  i_endM={tw[3]}
  i_cciLen={ic[0]}  i_atrLen={ic[1]}  i_atrMult={ic[2]}
  i_bbLen={ic[3]}  i_bbMult={ic[4]}
  i_mode="{ms}"  i_needMT={'true' if nmt else 'false'}
  i_slType="{ss}"  i_slAtr={slv if slt=='a' else 2.5}  i_slFix={slv if slt=='f' else 50.0}
  i_tpType="{ts_}"  i_tpRR={tpv if tpt=='r' else 1.5}  i_tpFix={tpv if tpt=='f' else 100.0}
  i_maxTrades=1  pyramiding=1  i_tradeLong=true  i_tradeShort=false

PERFORMANCE (1 Trade/Tag):
  PnL={p:+.1f}  Trades={nt}  WR={wr:.1f}%  PF={pf:.2f}  MaxDD={dd:.1f}  Avg={p/nt if nt else 0:+.1f}/Trade
""")
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = sum(1 for t in trades if t.pnl <= 0)
        avg_win = sum(t.pnl for t in trades if t.pnl > 0) / wins if wins else 0
        avg_loss = sum(t.pnl for t in trades if t.pnl <= 0) / losses if losses else 0
        print(f"  Wins: {wins} (avg {avg_win:+.1f}) | Losses: {losses} (avg {avg_loss:+.1f})")
        print(f"\n  Alle Trades:")
        eq = 0
        for i, t in enumerate(trades):
            eq += t.pnl
            print(f"  #{i+1:2d} {t.d} E={t.ep:.1f} X={t.xp:.1f} PnL={t.pnl:+.1f} {t.r:3s} | Equity={eq:+.1f}")

        # Pine-Log
        generate_log(esh, trades, 'ESH2026', tw,
                     '/home/user/Robin/pine-logs-MT+BB-ESH2026-backtest.csv')

        # Cross-validation US100
        iu = Ind(us, *ic)
        tu = bt_single(us, iu, tw[0],tw[1],tw[2],tw[3], m, nmt, slt, slv, tpt, tpv, True, False)
        pu, nu, wu, pfu, du = score(tu)
        print(f"\nUS100 CROSS-VAL: PnL={pu:+.1f} Trades={nu} WR={wu:.1f}% PF={pfu:.2f} DD={du:.1f}")

if __name__ == '__main__':
    main()
