#!/usr/bin/env python3
"""Final optimization: test best combined configs from all rounds."""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warnings
warnings.filterwarnings("ignore")

from backtester_v4 import (
    StrategyParams, Backtester, run_multi_symbol_backtest, ALL_SYMBOLS,
    get_stocks_params
)

STOCK_SYMBOLS = [s for s in ALL_SYMBOLS if s not in ("XAUUSD", "US100", "US500")]
base = get_stocks_params()
_real_stdout = sys.stdout

def run_test(overrides, symbols=STOCK_SYMBOLS, capital=100000.0):
    p_dict = base.to_dict()
    p_dict.update(overrides)
    p = StrategyParams.from_dict(p_dict)
    sys.stdout = io.StringIO()
    bt, tested = run_multi_symbol_backtest(symbols, params=p, initial_capital=capital, use_preset=False)
    sys.stdout = _real_stdout
    if not bt.trades:
        return None
    result, _ = bt.get_results()
    sym_pnl = {}
    sym_wr = {}
    for t in bt.trades:
        if t.symbol not in sym_pnl:
            sym_pnl[t.symbol] = 0
            sym_wr[t.symbol] = [0, 0]
        sym_pnl[t.symbol] += t.pnl
        sym_wr[t.symbol][1] += 1
        if t.pnl > 0:
            sym_wr[t.symbol][0] += 1
    losers = {s: p for s, p in sym_pnl.items() if p < 0}
    profitable = sum(1 for v in sym_pnl.values() if v > 0)
    return {
        "sym_pnl": dict(sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)),
        "sym_wr": sym_wr, "losers": losers, "profitable": profitable,
        "total_syms": len(sym_pnl), "pnl": result.get("total_pnl", 0),
        "pf": result.get("profit_factor", 0), "wr": result.get("win_rate", 0),
        "dd": result.get("max_drawdown_pct", -100), "trades": result.get("total_trades", 0),
    }

configs = [
    ({"atr_sl_multiplier": 2.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "R2 Best: SL2.5+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "atr_trail_multiplier": 3.0}, "R3 MaxPnL: SL3+Trail3+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "volume_multiplier": 1.5}, "R3 ZeroLoss: SL3+Vol1.5+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "volume_multiplier": 1.2}, "Balance: SL3+Vol1.2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "atr_trail_multiplier": 3.0, "volume_multiplier": 1.2}, "Combo: SL3+Trail3+Vol1.2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "atr_trail_multiplier": 3.0, "volume_multiplier": 1.5}, "MaxProfit0Loss: SL3+Trail3+Vol1.5"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "atr_trail_multiplier": 2.5, "volume_multiplier": 1.3}, "Balanced: SL3+Trail2.5+Vol1.3"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0, "atr_trail_multiplier": 3.0}, "BigTP: SL3+Trail3+TP2.5/5"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0, "atr_trail_multiplier": 3.0, "volume_multiplier": 1.2, "donchian_period": 10}, "AllBest: SL3+Trail3+Vol1.2+Don10+TP2.5/5"),
]

print("=" * 110)
print("FINAL OPTIMIZATION")
print("=" * 110)

for overrides, label in configs:
    _real_stdout.write(f"\r  {label:<55}")
    _real_stdout.flush()
    r = run_test(overrides)
    if r is None:
        print(f" -> NO TRADES"); continue
    n_losers = len(r["losers"])
    amd = r["sym_pnl"].get("AMD", 0)
    wdc = r["sym_pnl"].get("WDC", 0)
    print(f" PnL:${r['pnl']:>12,.0f} PF:{r['pf']:.2f} WR:{r['wr']:.1f}% DD:{r['dd']:.1f}% Prof:{r['profitable']}/{r['total_syms']} AMD:${amd:>8,.0f} WDC:${wdc:>8,.0f}")

print(f"\n{'='*110}")
print("STRESS TESTS ON ZERO-LOSS CONFIGS")
print("=" * 110)

zl = [
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "volume_multiplier": 1.5}, "SL3+Vol1.5+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "atr_trail_multiplier": 3.0, "volume_multiplier": 1.5}, "SL3+Trail3+Vol1.5"),
]
stress = [("Normal", {}), ("High costs", {"commission": 0.0005, "slippage_atr_frac": 0.15})]

for bo, bl in zl:
    print(f"\n  {bl}:")
    for sl, se in stress:
        c = {**bo, **se}
        r = run_test(c)
        if r is None:
            print(f"    {sl}: NO TRADES"); continue
        ls = ", ".join(f"{s}:${v:,.0f}" for s, v in sorted(r["losers"].items(), key=lambda x: x[1])) if r["losers"] else "NONE"
        print(f"    {sl:<15} PnL:${r['pnl']:>12,.0f} PF:{r['pf']:.2f} WR:{r['wr']:.1f}% DD:{r['dd']:.1f}% Prof:{r['profitable']}/{r['total_syms']} Losers:{ls}")

# Full breakdown of best zero-loss
print(f"\n{'='*110}")
print("FULL BREAKDOWN: SL3+Trail3+Vol1.5+TP2/4")
print("=" * 110)
r = run_test({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "atr_trail_multiplier": 3.0, "volume_multiplier": 1.5})
if r:
    print(f"  PnL: ${r['pnl']:,.0f} | PF: {r['pf']:.2f} | WR: {r['wr']:.1f}% | DD: {r['dd']:.1f}%")
    print(f"  Profitable: {r['profitable']}/{r['total_syms']}")
    for s, p in r["sym_pnl"].items():
        wd = r["sym_wr"].get(s, [0, 1])
        wr = wd[0] / max(wd[1], 1) * 100
        m = "+" if p > 0 else "-"
        print(f"    {s:<8} {m}${abs(p):>12,.2f} ({wd[1]:>3}t, {wr:.0f}%WR)")
