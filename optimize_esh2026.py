#!/usr/bin/env python3
"""Fast optimizer: 2-stage approach. Stage 1 finds best indicators+time with few combos.
Stage 2 fine-tunes SL/TP/trades on winners."""
import csv,datetime,math
from dataclasses import dataclass
from typing import List,Optional

@dataclass
class Bar:
    o:float;h:float;l:float;c:float;hour:int;minute:int

def load(path):
    bars=[]
    with open(path) as f:
        for r in csv.DictReader(f):
            t=int(r['time'])
            dt=datetime.datetime.fromtimestamp(t,tz=datetime.timezone(datetime.timedelta(hours=1)))
            bars.append(Bar(float(r['open']),float(r['high']),float(r['low']),float(r['close']),dt.hour,dt.minute))
    return bars

def sma(v,p):
    r=[None]*len(v)
    if len(v)<p:return r
    s=sum(v[:p]);r[p-1]=s/p
    for i in range(p,len(v)):s+=v[i]-v[i-p];r[i]=s/p
    return r

def stdev(v,p):
    r=[None]*len(v)
    for i in range(p-1,len(v)):
        w=v[i-p+1:i+1];m=sum(w)/p;r[i]=math.sqrt(sum((x-m)**2 for x in w)/p)
    return r

def calc_cci(bars,p):
    tp=[(b.h+b.l+b.c)/3 for b in bars];sm=sma(tp,p);r=[None]*len(bars)
    for i in range(p-1,len(bars)):
        if not sm[i]:continue
        w=tp[i-p+1:i+1];md=sum(abs(x-sm[i]) for x in w)/p
        r[i]=(tp[i]-sm[i])/(0.015*md) if md>0 else 0
    return r

def calc_atr(bars,p):
    r=[None]*len(bars)
    for i in range(1,len(bars)):
        tr=max(bars[i].h-bars[i].l,abs(bars[i].h-bars[i-1].c),abs(bars[i].l-bars[i-1].c))
        if i>=p and r[i-1]:r[i]=(r[i-1]*(p-1)+tr)/p
        elif i>=p:
            trs=[max(bars[j].h-bars[j].l,abs(bars[j].h-bars[j-1].c),abs(bars[j].l-bars[j-1].c)) for j in range(i-p+1,i+1)]
            r[i]=sum(trs)/len(trs)
        elif i==1:r[i]=tr
    return r

def calc_mt(bars,cci_v,atr_v,mult):
    n=len(bars);mt=[None]*n;bull=[False]*n
    for i in range(n):
        if cci_v[i] is None or atr_v[i] is None:
            if i>0:mt[i]=mt[i-1];bull[i]=bull[i-1]
            continue
        up=bars[i].l-atr_v[i]*mult;dn=bars[i].h+atr_v[i]*mult
        if cci_v[i]>=0:
            prev=mt[i-1] if i>0 and mt[i-1] is not None else up
            mt[i]=max(up,prev);bull[i]=True
        else:
            prev=mt[i-1] if i>0 and mt[i-1] is not None else dn
            mt[i]=min(dn,prev);bull[i]=False
    return mt,bull

def calc_bb(bars,l,m):
    c=[b.c for b in bars];ba=sma(c,l);dv=stdev(c,l)
    n=len(bars);u=[None]*n;lo=[None]*n
    for i in range(n):
        if ba[i] and dv[i]:u[i]=ba[i]+dv[i]*m;lo[i]=ba[i]-dv[i]*m
    return u,ba,lo

class Ind:
    def __init__(s,bars,cp,ap,am,bl,bm):
        c=calc_cci(bars,cp);a=calc_atr(bars,ap)
        s.atr=a;s.mt,s.bull=calc_mt(bars,c,a,am)
        s.bbu,s.bbb,s.bbl=calc_bb(bars,bl,bm)

@dataclass
class T:
    idx:int;d:str;ep:float;sl:float;tp:float
    xi:int=-1;xp:float=0;pnl:float=0;r:str=""

def bt(bars,ind,sh,sm,eh,em,mode,nmt,slt,slv,tpt,tpv,mxt,pyr,mxp,tl,ts,comm=4.0):
    trades=[];opn=[];st=sh*60+sm;et=eh*60+em;sess=0;pi=False
    for i in range(1,len(bars)):
        b=bars[i];p=bars[i-1];ct=b.hour*60+b.minute
        inw=ct>=st and ct<et;atc=ct>=et and ct<(et+5)
        if inw and not pi:sess=0
        pi=inw
        nw=[]
        for t in opn:
            hit=False
            if t.d=='L':
                if b.l<=t.sl:t.xi=i;t.xp=t.sl;t.pnl=t.xp-t.ep-comm;t.r='SL';hit=True
                elif b.h>=t.tp:t.xi=i;t.xp=t.tp;t.pnl=t.xp-t.ep-comm;t.r='TP';hit=True
            else:
                if b.h>=t.sl:t.xi=i;t.xp=t.sl;t.pnl=t.ep-t.xp-comm;t.r='SL';hit=True
                elif b.l<=t.tp:t.xi=i;t.xp=t.tp;t.pnl=t.ep-t.xp-comm;t.r='TP';hit=True
            if not hit:nw.append(t)
        opn=nw
        if atc and opn:
            for t in opn:t.xi=i;t.xp=b.c;t.pnl=(t.xp-t.ep if t.d=='L' else t.ep-t.xp)-comm;t.r='EOD'
            opn=[]
        if not inw:continue
        can=sess<mxt and (pyr or not opn) and (not pyr or len(opn)<mxp)
        if not can:continue
        u=ind.bbu[i];lo=ind.bbl[i];ba=ind.bbb[i]
        if not u or not lo or not ba:continue
        up=ind.bbu[i-1];lp=ind.bbl[i-1]
        if not up or not lp:continue
        ib=b.c>b.o;ie=b.c<b.o;mb=ind.bull[i]
        bo_l=b.c>u and p.c<=up and ib
        bo_s=b.c<lo and p.c>=lp and ie
        mr_l=b.c>lo and (p.c<lp or b.l<lo) and ib
        mr_s=b.c<u and (p.c>up or b.h>u) and ie
        ls=ss=False
        if mode=='bo':ls,ss=bo_l,bo_s
        elif mode=='mr':ls,ss=mr_l,mr_s
        else:ls,ss=bo_l or mr_l,bo_s or mr_s
        if nmt:ls=ls and mb;ss=ss and not mb
        ls=ls and tl;ss=ss and ts
        def mk(d):
            nonlocal sess
            a=ind.atr[i]
            if d=='L':
                sl=b.c-(a*slv if slt=='a' and a else slv if slt=='f' else abs(b.c-ba))
                sd=max(abs(b.c-sl),0.01)
                tp=b.c+(sd*tpv if tpt=='r' else tpv if tpt=='f' else max(u-b.c,sd*1.5))
            else:
                sl=b.c+(a*slv if slt=='a' and a else slv if slt=='f' else abs(ba-b.c))
                sd=max(abs(sl-b.c),0.01)
                tp=b.c-(sd*tpv if tpt=='r' else tpv if tpt=='f' else max(b.c-lo,sd*1.5))
            t=T(i,d,b.c,sl,tp);trades.append(t);opn.append(t);sess+=1
        if ls:mk('L')
        if ss and(not ls or pyr)and sess<mxt:mk('S')
    for t in opn:t.xi=len(bars)-1;t.xp=bars[-1].c;t.pnl=(t.xp-t.ep if t.d=='L' else t.ep-t.xp)-comm;t.r='END'
    return trades

def pnl(trades):return sum(t.pnl for t in trades)

def score(trades):
    if not trades:return -99999,0,0,0,0
    p=pnl(trades);w=sum(1 for t in trades if t.pnl>0);wr=w/len(trades)*100
    gp=sum(t.pnl for t in trades if t.pnl>0);gl=abs(sum(t.pnl for t in trades if t.pnl<=0))
    pf=gp/gl if gl>0 else 999;eq=pk=dd=0
    for t in trades:eq+=t.pnl;pk=max(pk,eq);dd=max(dd,pk-eq)
    return p,len(trades),wr,pf,dd

def main():
    print("Loading...")
    esh=load('/home/user/Robin/CAPITALCOM_ESH2026, 1.csv')
    us=load('/home/user/Robin/CAPITALCOM_US100, 1.csv')
    print(f"ESH:{len(esh)} US100:{len(us)}")

    # Reduced but smart parameter space
    tws=[
        (15,30,16,0),(15,30,16,15),(15,30,16,30),(15,30,16,45),(15,30,17,0),(15,30,17,30),
        (15,0,16,0),(15,0,16,30),(15,0,17,0),
        (15,45,16,15),(15,45,16,30),(15,45,17,0),
        (16,0,16,30),(16,0,17,0),(16,0,17,30),(16,0,18,0),
        (16,30,17,0),(16,30,17,30),
        (9,0,10,0),(9,0,11,0),(9,0,12,0),(10,0,12,0),
        (14,30,17,0),(14,30,16,0),
        (3,0,6,0),(1,0,4,0),
        (20,0,22,0),(19,0,22,0),
        (15,30,15,45),(15,35,16,5),
    ]

    # Key indicator combos (reduced from 320 to ~48)
    ind_combos = [
        (14,5,1.0,10,1.5),(14,5,1.0,14,2.0),(14,7,1.0,14,2.0),(14,10,1.5,14,2.0),
        (14,5,2.0,14,2.0),(14,7,1.5,10,2.0),(14,10,1.0,20,2.0),(14,5,0.5,14,1.5),
        (20,5,1.0,10,1.5),(20,7,1.0,14,2.0),(20,10,1.5,14,2.0),(20,5,1.0,14,2.5),
        (20,7,2.0,14,2.0),(20,10,1.0,20,2.5),(20,5,0.5,10,2.0),(20,14,1.5,20,2.0),
        (28,5,1.0,10,1.5),(28,7,1.0,14,2.0),(28,10,1.5,14,2.0),(28,10,2.5,14,2.0),
        (28,7,2.0,14,2.5),(28,10,1.0,20,2.0),(28,5,0.5,14,1.5),(28,14,1.5,20,2.5),
        (28,7,1.0,10,2.0),(28,5,1.5,14,2.0),(28,10,2.0,10,2.5),(28,7,0.5,20,2.0),
        (35,5,1.0,14,2.0),(35,7,1.5,14,2.0),(35,10,1.0,20,2.5),(35,14,2.0,14,2.0),
        (35,7,1.0,10,1.5),(35,5,2.0,14,2.5),(35,10,0.5,20,2.0),(35,7,2.5,14,2.0),
        (14,5,1.0,14,2.5),(14,10,2.0,10,2.5),(20,7,0.5,14,2.0),(20,10,2.5,14,2.0),
        (28,5,2.5,14,2.0),(28,14,1.0,10,1.5),(35,10,1.5,10,2.0),(35,5,1.0,20,3.0),
        (14,7,2.5,20,2.5),(20,5,2.5,10,2.5),(28,7,1.5,20,3.0),(35,14,2.5,14,3.0),
    ]

    modes=['bo','mr','co']
    mt_opts=[True,False]
    dirs=[('B',True,True),('L',True,False),('S',False,True)]

    # Stage 1
    print("\n=== STAGE 1 ===")
    total=len(ind_combos)*len(tws)*len(modes)*len(mt_opts)*len(dirs)
    print(f"Combos: {total}")
    be=[];bu=[];n=0

    for ic in ind_combos:
        ie=Ind(esh,*ic);iu=Ind(us,*ic)
        for tw in tws:
            for m in modes:
                for nmt in mt_opts:
                    for dn,tl,ts in dirs:
                        te=bt(esh,ie,tw[0],tw[1],tw[2],tw[3],m,nmt,'a',2.0,'r',1.5,10,True,3,tl,ts)
                        tu=bt(us,iu,tw[0],tw[1],tw[2],tw[3],m,nmt,'a',2.0,'r',1.5,10,True,3,tl,ts)
                        pe=pnl(te);pu=pnl(tu)
                        conf=(ic,tw,m,nmt,dn,tl,ts)
                        be.append((pe,conf));bu.append((pu,conf))
                        n+=1
                        if n%10000==0:
                            be.sort(reverse=True);bu.sort(reverse=True)
                            be=be[:40];bu=bu[:40]
                            print(f"  {n}/{total} E={be[0][0]:+.1f} U={bu[0][0]:+.1f}")

    be.sort(reverse=True);bu.sort(reverse=True)
    print(f"\nS1 done:{n}")
    print("\nTop10 ESH:")
    for p,c in be[:10]:
        ic,tw,m,nmt,dn,_,_=c
        print(f"  {p:+.1f} CCI={ic[0]} ATR={ic[1]}/{ic[2]} BB={ic[3]}/{ic[4]} {tw[0]:02d}:{tw[1]:02d}-{tw[2]:02d}:{tw[3]:02d} {m} MT={nmt} {dn}")
    print("\nTop10 US100:")
    for p,c in bu[:10]:
        ic,tw,m,nmt,dn,_,_=c
        print(f"  {p:+.1f} CCI={ic[0]} ATR={ic[1]}/{ic[2]} BB={ic[3]}/{ic[4]} {tw[0]:02d}:{tw[1]:02d}-{tw[2]:02d}:{tw[3]:02d} {m} MT={nmt} {dn}")

    # Stage 2: SL/TP/trades optimization
    print("\n=== STAGE 2 ===")
    tops=set()
    for _,c in be[:20]:tops.add(c)
    for _,c in bu[:20]:tops.add(c)

    slc=[('a',0.5),('a',1.0),('a',1.5),('a',2.0),('a',2.5),('a',3.0),('a',3.5),('a',4.0),
         ('f',3),('f',5),('f',8),('f',10),('f',15),('f',20),('f',30),('f',50),('b',0)]
    tpc=[('r',0.5),('r',0.8),('r',1.0),('r',1.5),('r',2.0),('r',2.5),('r',3.0),('r',4.0),('r',5.0),
         ('f',3),('f',5),('f',8),('f',10),('f',15),('f',20),('f',30),('f',50),('o',0)]
    mto=[1,2,3,5,8,10,15,20]
    pyo=[(False,1),(True,2),(True,3),(True,5)]

    bep=-99999;bup=-99999;bcp=-99999
    bef=None;buf=None;bcf=None;s2=0

    for conf in tops:
        ic,tw,m,nmt,dn,tl,ts=conf
        ie=Ind(esh,*ic);iu=Ind(us,*ic)
        for st,sv in slc:
            for tt,tv in tpc:
                for mt in mto:
                    for ap,mp in pyo:
                        te=bt(esh,ie,tw[0],tw[1],tw[2],tw[3],m,nmt,st,sv,tt,tv,mt,ap,mp,tl,ts)
                        tu=bt(us,iu,tw[0],tw[1],tw[2],tw[3],m,nmt,st,sv,tt,tv,mt,ap,mp,tl,ts)
                        pe=pnl(te);pu=pnl(tu)
                        full=(conf,st,sv,tt,tv,mt,ap,mp)
                        if pe>bep:bep=pe;bef=(full,te)
                        if pu>bup:bup=pu;buf=(full,tu)
                        if pe+pu>bcp:bcp=pe+pu;bcf=(full,te,tu)
                        s2+=1
                        if s2%50000==0:print(f"  S2:{s2} E={bep:+.1f} U={bup:+.1f} C={bcp:+.1f}")

    print(f"S2 done:{s2}")

    # Stage 3: fine-tune TW for ESH best
    print("\n=== STAGE 3: Fine TW ===")
    if bef:
        full=bef[0];conf=full[0];st,sv,tt,tv,mt,ap,mp=full[1:]
        ic,tw,m,nmt,dn,tl,ts=conf
        ie=Ind(esh,*ic);btp=bep;btw=tw;btt=bef[1]
        for sh in range(max(0,tw[0]-2),min(24,tw[0]+3)):
            for sm in range(0,60,5):
                for eh in range(sh,min(24,sh+5)):
                    for em in range(0,60,5):
                        if eh*60+em<=sh*60+sm+10 or eh*60+em>sh*60+sm+240:continue
                        te=bt(esh,ie,sh,sm,eh,em,m,nmt,st,sv,tt,tv,mt,ap,mp,tl,ts)
                        pe=pnl(te)
                        if pe>btp:btp=pe;btw=(sh,sm,eh,em);btt=te
        if btw!=tw:
            print(f"  Improved:{btw[0]:02d}:{btw[1]:02d}-{btw[2]:02d}:{btw[3]:02d} PnL={btp:+.1f} (was {bep:+.1f})")
            bep=btp;nc=(ic,btw,m,nmt,dn,tl,ts);bef=((nc,st,sv,tt,tv,mt,ap,mp),btt)
        else:print("  No improvement")

    # Stage 4: fine SL/TP
    print("\n=== STAGE 4: Fine SL/TP ===")
    if bef:
        full=bef[0];conf=full[0];st,sv,tt,tv,mt,ap,mp=full[1:]
        ic,tw,m,nmt,dn,tl,ts=conf
        ie=Ind(esh,*ic);bfp=bep;bft=bef[1];bfs=(st,sv);bftp=(tt,tv)
        if st=='a':slr=[sv+x*0.05 for x in range(-15,16) if sv+x*0.05>0.2]
        elif st=='f':slr=[sv+x*max(0.5,sv*0.04) for x in range(-15,16) if sv+x*max(0.5,sv*0.04)>0.5]
        else:slr=[0]
        if tt=='r':tpr=[tv+x*0.05 for x in range(-15,16) if tv+x*0.05>0.2]
        elif tt=='f':tpr=[tv+x*max(0.5,tv*0.04) for x in range(-15,16) if tv+x*max(0.5,tv*0.04)>0.5]
        else:tpr=[0]
        for sv2 in slr:
            for tv2 in tpr:
                te=bt(esh,ie,tw[0],tw[1],tw[2],tw[3],m,nmt,st,sv2,tt,tv2,mt,ap,mp,tl,ts)
                pe=pnl(te)
                if pe>bfp:bfp=pe;bft=te;bfs=(st,sv2);bftp=(tt,tv2)
        if bfp>bep:
            print(f"  SL={bfs[0]}:{bfs[1]:.2f} TP={bftp[0]}:{bftp[1]:.2f} PnL={bfp:+.1f} (was {bep:+.1f})")
            bep=bfp;bef=((conf,bfs[0],bfs[1],bftp[0],bftp[1],mt,ap,mp),bft)
        else:print("  No improvement")

    # FINAL
    print("\n"+"="*80)
    print("FINAL BEST ESH2026")
    print("="*80)
    if bef:
        full=bef[0];trades=bef[1]
        conf=full[0];st,sv,tt,tv,mt,ap,mp=full[1:]
        ic,tw,m,nmt,dn,tl,ts=conf
        p,nt,wr,pf,dd=score(trades)
        ms={'bo':'Breakout','mr':'Mean Reversion','co':'Kombiniert'}[m]
        ss={'a':'ATR','f':'Fest (Punkte)','b':'BB Mitte'}[st]
        ts_={'r':'RR Verhaeltnis','f':'Fest (Punkte)','o':'Gegenband BB'}[tt]
        print(f"""
PINE PARAMS:
  i_startH={tw[0]}  i_startM={tw[1]}  i_endH={tw[2]}  i_endM={tw[3]}
  i_cciLen={ic[0]}  i_atrLen={ic[1]}  i_atrMult={ic[2]}
  i_bbLen={ic[3]}  i_bbMult={ic[4]}
  i_mode="{ms}"  i_needMT={'true' if nmt else 'false'}
  i_slType="{ss}"  i_slAtr={sv if st=='a' else 2.5}  i_slFix={sv if st=='f' else 50.0}
  i_tpType="{ts_}"  i_tpRR={tv if tt=='r' else 1.5}  i_tpFix={tv if tt=='f' else 100.0}
  i_maxTrades={mt}  i_tradeLong={'true' if tl else 'false'}  i_tradeShort={'true' if ts else 'false'}

PERFORMANCE:
  PnL={p:+.1f} Trades={nt} WR={wr:.1f}% PF={pf:.2f} DD={dd:.1f} Avg={p/nt if nt else 0:+.1f}
""")
        for i,t in enumerate(trades):
            print(f"  #{i+1:3d} {t.d} bar{t.idx}->bar{t.xi} E={t.ep:.1f} X={t.xp:.1f} PnL={t.pnl:+.1f} {t.r}")

        # Cross-val US100
        iu=Ind(us,*ic)
        tu=bt(us,iu,tw[0],tw[1],tw[2],tw[3],m,nmt,st,sv,tt,tv,mt,ap,mp,tl,ts)
        pu,nu,wu,pfu,du=score(tu)
        print(f"\nUS100 CROSS: PnL={pu:+.1f} Trades={nu} WR={wu:.1f}% PF={pfu:.2f} DD={du:.1f}")

    # Also print combined best
    print("\n"+"="*80)
    print("BEST COMBINED (ESH+US100)")
    print("="*80)
    if bcf:
        full=bcf[0];te=bcf[1];tu=bcf[2]
        conf=full[0];st,sv,tt,tv,mt,ap,mp=full[1:]
        ic,tw,m,nmt,dn,tl,ts=conf
        pe,ne,we,pfe,de=score(te)
        pu,nu,wu,pfu,du=score(tu)
        ms={'bo':'Breakout','mr':'Mean Reversion','co':'Kombiniert'}[m]
        ss={'a':'ATR','f':'Fest (Punkte)','b':'BB Mitte'}[st]
        ts_={'r':'RR Verhaeltnis','f':'Fest (Punkte)','o':'Gegenband BB'}[tt]
        print(f"""
PINE PARAMS:
  i_startH={tw[0]}  i_startM={tw[1]}  i_endH={tw[2]}  i_endM={tw[3]}
  i_cciLen={ic[0]}  i_atrLen={ic[1]}  i_atrMult={ic[2]}
  i_bbLen={ic[3]}  i_bbMult={ic[4]}
  i_mode="{ms}"  i_needMT={'true' if nmt else 'false'}
  i_slType="{ss}"  i_slAtr={sv if st=='a' else 2.5}  i_slFix={sv if st=='f' else 50.0}
  i_tpType="{ts_}"  i_tpRR={tv if tt=='r' else 1.5}  i_tpFix={tv if tt=='f' else 100.0}
  i_maxTrades={mt}  i_tradeLong={'true' if tl else 'false'}  i_tradeShort={'true' if ts else 'false'}

ESH2026: PnL={pe:+.1f} Trades={ne} WR={we:.1f}% PF={pfe:.2f} DD={de:.1f}
US100:   PnL={pu:+.1f} Trades={nu} WR={wu:.1f}% PF={pfu:.2f} DD={du:.1f}
TOTAL:   PnL={pe+pu:+.1f}
""")

if __name__=='__main__':
    main()
