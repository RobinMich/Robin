#!/usr/bin/env python3
"""
Fast targeted optimization for XAUUSD and Indices presets.
Tests only the most impactful parameter combinations.
"""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warnings
warnings.filterwarnings("ignore")

from backtester_v4 import (
    StrategyParams, Backtester, run_multi_symbol_backtest,
    get_xauusd_params, get_indices_params, get_stocks_params,
    ALL_SYMBOLS
)

_real_stdout = sys.stdout

XAUUSD_SYMBOLS = ["XAUUSD"]
INDEX_SYMBOLS = ["US100", "US500"]
STOCK_SYMBOLS = [s for s in ALL_SYMBOLS if s not in ("XAUUSD", "US100", "US500")]


def run_test(symbols, base_params, overrides):
    p_dict = base_params.to_dict()
    p_dict.update(overrides)
    p = StrategyParams.from_dict(p_dict)
    sys.stdout = io.StringIO()
    bt, tested = run_multi_symbol_backtest(symbols, params=p, initial_capital=100000.0, use_preset=False)
    sys.stdout = _real_stdout
    if not bt.trades:
        return None
    result, _ = bt.get_results()
    sym_pnl = {}
    for t in bt.trades:
        sym_pnl[t.symbol] = sym_pnl.get(t.symbol, 0) + t.pnl
    return {
        "pnl": result.get("total_pnl", 0),
        "pf": result.get("profit_factor", 0),
        "wr": result.get("win_rate", 0),
        "dd": result.get("max_drawdown_pct", -100),
        "trades": result.get("total_trades", 0),
        "avg_rr": result.get("avg_rr", 0),
        "tp1": result.get("tp1_count", 0),
        "tp2": result.get("tp2_count", 0),
        "sym_pnl": sym_pnl,
    }


def test_configs(name, symbols, base, configs):
    print(f"\n  Testing {len(configs)} configs for {name}...")
    results = []
    for i, (ov, label) in enumerate(configs):
        _real_stdout.write(f"\r  [{i+1}/{len(configs)}] {label:<55}")
        _real_stdout.flush()
        r = run_test(symbols, base, ov)
        if r and r["trades"] > 0:
            r["label"] = label
            r["overrides"] = ov
            results.append(r)
    print()
    results.sort(key=lambda x: x["pnl"], reverse=True)
    return results


def print_results(results, n=10, title="RESULTS"):
    print(f"\n  {title}:")
    print(f"  {'#':>3} {'PnL':>14} {'PF':>6} {'WR%':>6} {'DD%':>7} {'Tr':>5} {'RR':>6} | Config")
    print(f"  {'-'*90}")
    for i, r in enumerate(results[:n]):
        print(f"  {i+1:>3} ${r['pnl']:>12,.0f} {r['pf']:>5.2f} {r['wr']:>5.1f}% {r['dd']:>6.1f}% {r['trades']:>5} {r['avg_rr']:>+5.2f} | {r['label']}")


# ============================================================
# XAUUSD OPTIMIZATION
# ============================================================
print("=" * 90)
print("  XAUUSD OPTIMIZATION")
print("=" * 90)

xau = get_xauusd_params()

# Key insight from stocks: wider SL + wider trail + higher TP = more profit
# Test systematically: the main profit drivers
xau_configs = [
    # Baseline (current v4.1)
    ({}, "BASELINE v4.1"),
    # Wider SL tests
    ({"atr_sl_multiplier": 2.5}, "SL2.5"),
    ({"atr_sl_multiplier": 3.0}, "SL3.0"),
    ({"atr_sl_multiplier": 3.5}, "SL3.5"),
    # Wider trail tests
    ({"atr_trail_multiplier": 3.0}, "Trail3.0"),
    ({"atr_trail_multiplier": 3.5}, "Trail3.5"),
    # Higher BE
    ({"be_rr_ratio": 2.0}, "BE2.0"),
    ({"be_rr_ratio": 2.5}, "BE2.5"),
    # Higher TP targets
    ({"tp1_rr": 2.0, "tp2_rr": 4.0}, "TP2/4"),
    ({"tp1_rr": 2.5, "tp2_rr": 5.0}, "TP2.5/5"),
    # Combos: wide SL + wide trail (like stocks success)
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0}, "SL3+Trail3"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.5}, "SL3+Trail3.5"),
    ({"atr_sl_multiplier": 3.5, "atr_trail_multiplier": 3.5}, "SL3.5+Trail3.5"),
    # Combos: wide SL + higher BE + higher TP
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3+BE2+TP2.5/5"),
    ({"atr_sl_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3.5+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.5, "be_rr_ratio": 2.5, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3.5+BE2.5+TP2.5/5"),
    # Full combos: SL + Trail + BE + TP (stocks-like approach)
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3+T3+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3+T3+BE2+TP2.5/5"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3+T3.5+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3+T3.5+BE2+TP2.5/5"),
    ({"atr_sl_multiplier": 3.5, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3.5+T3.5+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.5, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3.5+T3.5+BE2+TP2.5/5"),
    ({"atr_sl_multiplier": 3.5, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.5, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3.5+T3.5+BE2.5+TP2.5/5"),
    # Wider PB zone combos
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "pb_atr_buffer": 3.0}, "SL3+T3+BE2+TP2/4+PB3"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0, "pb_atr_buffer": 3.0}, "SL3+T3+BE2+TP2.5/5+PB3"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "pb_atr_buffer": 3.5}, "SL3+T3+BE2+TP2/4+PB3.5"),
    # ADX relaxed combos
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "adx_threshold_context": 8.0, "adx_threshold_validation": 5.0}, "SL3+T3+BE2+TP2/4+ADXlow"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0, "adx_threshold_context": 8.0, "adx_threshold_validation": 5.0}, "SL3+T3+BE2+TP2.5/5+ADXlow"),
    # Momentum score relaxed
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "mom_score_min": 25}, "SL3+T3+BE2+TP2/4+Mom25"),
    # Long-only gold test
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "direction": "long"}, "SL3+T3+BE2+TP2/4+LONG"),
    # Extra: BBW percentile and Donchian tweaks
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "bbw_squeeze_percentile": 75.0, "donchian_period": 8}, "SL3+T3+BE2+TP2/4+BBW75+Don8"),
]

xau_results = test_configs("XAUUSD", XAUUSD_SYMBOLS, xau, xau_configs)
print_results(xau_results, 15, "XAUUSD TOP 15")


# ============================================================
# INDICES OPTIMIZATION
# ============================================================
print(f"\n{'='*90}")
print("  INDICES OPTIMIZATION (US100 + US500)")
print("=" * 90)

idx = get_indices_params()

idx_configs = [
    ({}, "BASELINE v4.1"),
    ({"atr_sl_multiplier": 2.5}, "SL2.5"),
    ({"atr_sl_multiplier": 3.0}, "SL3.0"),
    ({"atr_sl_multiplier": 3.5}, "SL3.5"),
    ({"atr_trail_multiplier": 3.0}, "Trail3.0"),
    ({"atr_trail_multiplier": 3.5}, "Trail3.5"),
    ({"be_rr_ratio": 2.0}, "BE2.0"),
    ({"be_rr_ratio": 2.5}, "BE2.5"),
    ({"tp1_rr": 2.0, "tp2_rr": 4.0}, "TP2/4"),
    ({"tp1_rr": 2.5, "tp2_rr": 5.0}, "TP2.5/5"),
    # Combos
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0}, "SL3+Trail3"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.5}, "SL3+Trail3.5"),
    ({"atr_sl_multiplier": 3.5, "atr_trail_multiplier": 3.5}, "SL3.5+Trail3.5"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3+BE2+TP2.5/5"),
    ({"atr_sl_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3.5+BE2+TP2/4"),
    # Full combos
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3+T3+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3+T3+BE2+TP2.5/5"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3+T3.5+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3+T3.5+BE2+TP2.5/5"),
    ({"atr_sl_multiplier": 3.5, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL3.5+T3.5+BE2+TP2/4"),
    ({"atr_sl_multiplier": 3.5, "atr_trail_multiplier": 3.5, "be_rr_ratio": 2.0, "tp1_rr": 2.5, "tp2_rr": 5.0}, "SL3.5+T3.5+BE2+TP2.5/5"),
    # PB buffer
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "pb_atr_buffer": 2.5}, "SL3+T3+BE2+TP2/4+PB2.5"),
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "pb_atr_buffer": 3.0}, "SL3+T3+BE2+TP2/4+PB3"),
    # ADX relaxed
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "adx_threshold_context": 8.0, "adx_threshold_validation": 5.0}, "SL3+T3+BE2+TP2/4+ADXlow"),
    # Direction tests
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "direction": "long"}, "SL3+T3+BE2+TP2/4+LONG"),
    # BBW + Donchian
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "bbw_squeeze_percentile": 75.0, "donchian_period": 8}, "SL3+T3+BE2+TP2/4+BBW75+Don8"),
    # Mom score relaxed
    ({"atr_sl_multiplier": 3.0, "atr_trail_multiplier": 3.0, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0, "mom_score_min": 25}, "SL3+T3+BE2+TP2/4+Mom25"),
]

idx_results = test_configs("INDICES", INDEX_SYMBOLS, idx, idx_configs)
print_results(idx_results, 15, "INDICES TOP 15")


# ============================================================
# STOCKS VERIFICATION
# ============================================================
print(f"\n{'='*90}")
print("  STOCKS VERIFICATION (v4.3)")
print("=" * 90)

r = run_test(STOCK_SYMBOLS, get_stocks_params(), {})
if r:
    print(f"  PnL: ${r['pnl']:,.0f} | PF: {r['pf']:.2f} | WR: {r['wr']:.1f}% | DD: {r['dd']:.1f}% | Trades: {r['trades']}")


# ============================================================
# FINAL SUMMARY
# ============================================================
print(f"\n{'='*90}")
print("  FINAL OPTIMIZED PRESETS")
print("=" * 90)

if xau_results:
    bx = xau_results[0]
    print(f"\n  XAUUSD BEST: {bx['label']}")
    print(f"    PnL: ${bx['pnl']:,.0f} | PF: {bx['pf']:.2f} | WR: {bx['wr']:.1f}% | DD: {bx['dd']:.1f}% | Trades: {bx['trades']}")
    print(f"    Overrides: {bx['overrides']}")

if idx_results:
    bi = idx_results[0]
    print(f"\n  INDICES BEST: {bi['label']}")
    print(f"    PnL: ${bi['pnl']:,.0f} | PF: {bi['pf']:.2f} | WR: {bi['wr']:.1f}% | DD: {bi['dd']:.1f}% | Trades: {bi['trades']}")
    print(f"    Overrides: {bi['overrides']}")
    for s, p in sorted(bi["sym_pnl"].items(), key=lambda x: x[1], reverse=True):
        print(f"      {s}: ${p:,.0f}")

if r:
    print(f"\n  STOCKS (v4.3): PnL=${r['pnl']:,.0f} PF={r['pf']:.2f} WR={r['wr']:.1f}% DD={r['dd']:.1f}%")
