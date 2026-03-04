#!/usr/bin/env python3
"""Round 3: Fix last 2 losers (AMD, WDC) without hurting other symbols.
Strategy: Test different SL / entry filter combos that specifically help volatile/choppy stocks."""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warnings
warnings.filterwarnings("ignore")

from backtester_v4 import (
    StrategyParams, Backtester, run_multi_symbol_backtest, ALL_SYMBOLS,
    get_stocks_params
)

STOCK_SYMBOLS = [s for s in ALL_SYMBOLS if s not in ("XAUUSD", "US100", "US500")]
# Start from the best config found in round 2
base = get_stocks_params()
best_overrides = {'atr_sl_multiplier': 2.5, 'be_rr_ratio': 2.0, 'tp1_rr': 2.0, 'tp2_rr': 4.0}

_real_stdout = sys.stdout

def run_test(overrides, symbols=STOCK_SYMBOLS, capital=100000.0):
    p_dict = base.to_dict()
    p_dict.update(best_overrides)
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
            sym_wr[t.symbol] = [0, 0]  # wins, total
        sym_pnl[t.symbol] += t.pnl
        sym_wr[t.symbol][1] += 1
        if t.pnl > 0:
            sym_wr[t.symbol][0] += 1

    losers = {s: p for s, p in sym_pnl.items() if p < 0}
    profitable = sum(1 for v in sym_pnl.values() if v > 0)

    return {
        "sym_pnl": dict(sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)),
        "sym_wr": sym_wr,
        "losers": losers,
        "profitable": profitable,
        "total_syms": len(sym_pnl),
        "pnl": result.get("total_pnl", 0),
        "pf": result.get("profit_factor", 0),
        "wr": result.get("win_rate", 0),
        "dd": result.get("max_drawdown_pct", -100),
        "trades": result.get("total_trades", 0),
    }

# ============================================================
# ROUND 3: Aggressive search for 0 losers
# ============================================================
print("=" * 80)
print("ROUND 3: ZERO LOSERS TARGET")
print("Base: SL2.5 + BE2.0 + TP1=2.0 + TP2=4.0")
print("=" * 80)

configs = [
    ({}, "Base (24/26)"),
    # Higher SL to help choppy AMD/WDC
    ({"atr_sl_multiplier": 3.0}, "SL 3.0"),
    ({"atr_sl_multiplier": 3.5}, "SL 3.5"),
    ({"atr_sl_multiplier": 4.0}, "SL 4.0"),
    # Higher momentum filter (better quality entries)
    ({"mom_score_min": 45}, "Mom>=45"),
    ({"mom_score_min": 50}, "Mom>=50"),
    ({"mom_score_min": 55}, "Mom>=55"),
    ({"mom_score_min": 60}, "Mom>=60"),
    # Higher context ADX (stronger trends only)
    ({"adx_threshold_context": 12.0}, "CTX ADX>=12"),
    ({"adx_threshold_context": 15.0}, "CTX ADX>=15"),
    # Higher validation ADX
    ({"adx_threshold_validation": 8.0}, "VAL ADX>=8"),
    ({"adx_threshold_validation": 10.0}, "VAL ADX>=10"),
    # Stricter BBW (more squeeze = higher quality)
    ({"bbw_squeeze_percentile": 65.0}, "BBW<=65"),
    ({"bbw_squeeze_percentile": 60.0}, "BBW<=60"),
    # Require bullish candle
    ({"require_bullish_bar": True}, "Bullish bar req"),
    # Combined: SL wider + quality filter tighter
    ({"atr_sl_multiplier": 3.0, "mom_score_min": 50}, "SL3+Mom50"),
    ({"atr_sl_multiplier": 3.0, "mom_score_min": 55}, "SL3+Mom55"),
    ({"atr_sl_multiplier": 3.0, "adx_threshold_context": 12.0}, "SL3+cADX12"),
    ({"atr_sl_multiplier": 3.0, "adx_threshold_validation": 8.0}, "SL3+vADX8"),
    ({"atr_sl_multiplier": 3.0, "bbw_squeeze_percentile": 65.0}, "SL3+BBW65"),
    ({"atr_sl_multiplier": 3.0, "require_bullish_bar": True}, "SL3+BullBar"),
    ({"atr_sl_multiplier": 3.5, "mom_score_min": 50}, "SL3.5+Mom50"),
    ({"atr_sl_multiplier": 3.5, "mom_score_min": 55}, "SL3.5+Mom55"),
    ({"atr_sl_multiplier": 3.0, "mom_score_min": 50, "adx_threshold_context": 12.0}, "SL3+Mom50+cADX12"),
    ({"atr_sl_multiplier": 3.0, "mom_score_min": 50, "bbw_squeeze_percentile": 65.0}, "SL3+Mom50+BBW65"),
    ({"atr_sl_multiplier": 3.0, "mom_score_min": 50, "require_bullish_bar": True}, "SL3+Mom50+Bull"),
    # TP adjustments with wider SL
    ({"atr_sl_multiplier": 3.0, "tp1_rr": 1.5, "tp2_rr": 3.0}, "SL3+TP1.5/3"),
    ({"atr_sl_multiplier": 3.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3+TP2.5/5"),
    # Trail with wider SL
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 2.5}, "SL3+Trail2.5"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0}, "SL3+Trail3.0"),
    # Donchian longer (more selective)
    ({"atr_sl_multiplier": 3.0, "donchian_period": 10}, "SL3+Don10"),
    ({"atr_sl_multiplier": 3.0, "donchian_period": 12}, "SL3+Don12"),
    # Volume filter stricter
    ({"atr_sl_multiplier": 3.0, "volume_multiplier": 1.2}, "SL3+Vol1.2"),
    ({"atr_sl_multiplier": 3.0, "volume_multiplier": 1.5}, "SL3+Vol1.5"),
]

best_score = -999999
best_config = None
best_r = None

for overrides, label in configs:
    _real_stdout.write(f"\r  {label:<45}")
    _real_stdout.flush()

    r = run_test(overrides)
    if r is None:
        print(f" -> NO TRADES")
        continue

    n_losers = len(r["losers"])
    max_loss = min(r["losers"].values()) if r["losers"] else 0

    # Focus metrics on AMD and WDC
    amd_pnl = r["sym_pnl"].get("AMD", 0)
    wdc_pnl = r["sym_pnl"].get("WDC", 0)

    print(f" -> PnL: ${r['pnl']:>11,.0f} | PF: {r['pf']:.2f} | WR: {r['wr']:.1f}% | "
          f"Prof: {r['profitable']}/{r['total_syms']} | AMD: ${amd_pnl:>8,.0f} | WDC: ${wdc_pnl:>8,.0f}")

    # Score: heavy bonus for 0 losers, then PnL * PF
    score = r["pnl"] * min(r["pf"], 3.0) * (r["profitable"] / max(r["total_syms"], 1))
    if n_losers == 0:
        score *= 5.0  # Massive bonus
    elif n_losers == 1:
        score *= 2.0
    if r["dd"] < -30:
        score *= 0.7

    if score > best_score:
        best_score = score
        best_config = (overrides, label)
        best_r = r

print(f"\n\n{'='*80}")
print(f"BEST CONFIG: {best_config[1]}")
print(f"  Added overrides: {best_config[0]}")
print(f"  Full overrides: {dict(**best_overrides, **best_config[0])}")
print(f"  PnL: ${best_r['pnl']:,.0f} | PF: {best_r['pf']:.2f} | WR: {best_r['wr']:.1f}%")
print(f"  DD: {best_r['dd']:.1f}% | Profitable: {best_r['profitable']}/{best_r['total_syms']}")
print(f"  Losers: {best_r['losers']}")
print(f"\n  Per-Symbol:")
for s, p in best_r["sym_pnl"].items():
    wr_data = best_r["sym_wr"].get(s, [0, 1])
    wr_pct = wr_data[0] / max(wr_data[1], 1) * 100
    marker = "+" if p > 0 else "-"
    print(f"    {s:<8} {marker}${abs(p):>12,.2f}  ({wr_data[1]:>3} trades, {wr_pct:.0f}% WR)")

# Also show the stress test for the final winner
print(f"\n{'='*80}")
print("FINAL STRESS TESTS")
print(f"{'='*80}")
final_overrides = dict(**best_overrides, **best_config[0])

stress_tests = [
    ("Normal", {}),
    ("High costs (comm 0.05% + slip 0.15 ATR)", {"commission": 0.0005, "slippage_atr_frac": 0.15}),
    ("Conservative risk (0.5%)", {"risk_percent": 0.5}),
]

for st_label, st_extra in stress_tests:
    combined = {**final_overrides, **st_extra}
    _real_stdout.write(f"\r  Stress: {st_label:<50}")
    _real_stdout.flush()
    r = run_test(combined)
    if r is None:
        print(f" -> NO TRADES")
        continue
    n_losers = len(r["losers"])
    print(f" -> PnL: ${r['pnl']:>12,.0f} | PF: {r['pf']:.2f} | WR: {r['wr']:.1f}% | DD: {r['dd']:.1f}% | "
          f"Prof: {r['profitable']}/{r['total_syms']} | Losers: {n_losers}")
    if r["losers"]:
        for s, lp in sorted(r["losers"].items(), key=lambda x: x[1]):
            _real_stdout.write(f"          Loser: {s} ${lp:,.0f}\n")
