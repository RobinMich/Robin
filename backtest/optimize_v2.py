#!/usr/bin/env python3
"""Round 2 optimization: Make ALL symbols profitable + stress test robust.
Focus on eliminating losing symbols (AMD, WDC, AXP) without hurting winners."""
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

def run_test(overrides, symbols=STOCK_SYMBOLS, capital=100000.0, label=""):
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
    sym_trades = {}
    for t in bt.trades:
        sym_pnl[t.symbol] = sym_pnl.get(t.symbol, 0) + t.pnl
        sym_trades[t.symbol] = sym_trades.get(t.symbol, 0) + 1

    losers = {s: p for s, p in sym_pnl.items() if p < 0}
    profitable = sum(1 for v in sym_pnl.values() if v > 0)

    return {
        "result": result,
        "sym_pnl": dict(sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)),
        "sym_trades": sym_trades,
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
# ROUND 2: Fine-tune to eliminate losers
# ============================================================
print("=" * 80)
print("ROUND 2: ELIMINATE LOSING SYMBOLS")
print("=" * 80)

# Current losers: AMD, WDC, AXP
# Strategy: vary params that affect trade management (SL, TP, BE, trail)
# since the entry filters are already good

test_configs = [
    # Baseline (current best)
    ({}, "BASELINE v4.2"),
    # Wider SL variations (key: reduces noise stops)
    ({"atr_sl_multiplier": 2.2}, "SL 2.2x ATR"),
    ({"atr_sl_multiplier": 2.5}, "SL 2.5x ATR"),
    ({"atr_sl_multiplier": 3.0}, "SL 3.0x ATR"),
    # BE mode off (breakeven stops often kill good trades)
    ({"be_mode": "none"}, "No breakeven"),
    ({"be_mode": "pullback", "be_rr_ratio": 2.0}, "BE at 2.0 RR"),
    ({"be_mode": "pullback", "be_rr_ratio": 2.5}, "BE at 2.5 RR"),
    # Trail adjustments
    ({"atr_trail_multiplier": 2.5}, "Trail 2.5x ATR"),
    ({"atr_trail_multiplier": 3.0}, "Trail 3.0x ATR"),
    ({"trail_start_rr": 2.0}, "Trail start 2.0 RR"),
    ({"trail_start_rr": 2.5}, "Trail start 2.5 RR"),
    # TP adjustments
    ({"tp1_rr": 2.0, "tp2_rr": 4.0}, "TP1=2.0 TP2=4.0"),
    ({"tp1_rr": 1.0, "tp2_rr": 2.0, "tp1_fraction": 0.5}, "TP1=1.0/50% TP2=2.0"),
    ({"partial_tp_enabled": False}, "No partial TP (full trail)"),
    # Chandelier adjustments
    ({"chandelier_tighten_after_tp2": 0.5}, "Tight chandelier 0.5"),
    ({"chandelier_tighten_after_tp2": 0.8}, "Loose chandelier 0.8"),
    # Combined: wider SL + adjusted BE
    ({"atr_sl_multiplier": 2.5, "be_rr_ratio": 2.0}, "SL 2.5 + BE 2.0"),
    ({"atr_sl_multiplier": 2.5, "be_mode": "none"}, "SL 2.5 + No BE"),
    ({"atr_sl_multiplier": 2.5, "atr_trail_multiplier": 2.5}, "SL 2.5 + Trail 2.5"),
    ({"atr_sl_multiplier": 2.5, "be_rr_ratio": 2.0, "atr_trail_multiplier": 2.5}, "SL2.5+BE2.0+Trail2.5"),
    ({"atr_sl_multiplier": 2.5, "be_rr_ratio": 2.0, "tp1_rr": 2.0, "tp2_rr": 4.0}, "SL2.5+BE2.0+TP2/4"),
    # More positions (compound faster)
    ({"atr_sl_multiplier": 2.5, "be_rr_ratio": 2.0, "max_positions": 8}, "SL2.5+BE2.0+8pos"),
    # Lower risk to reduce DD
    ({"atr_sl_multiplier": 2.5, "be_rr_ratio": 2.0, "risk_percent": 0.5}, "SL2.5+BE2.0+0.5%risk"),
    # Pullback buffer with wider SL
    ({"atr_sl_multiplier": 2.5, "pb_atr_buffer": 3.5}, "SL2.5+PB3.5"),
    ({"atr_sl_multiplier": 2.5, "pb_atr_buffer": 2.5}, "SL2.5+PB2.5"),
    # RSI adjustments
    ({"atr_sl_multiplier": 2.5, "rsi_long_max": 80.0}, "SL2.5+RSI80"),
    ({"atr_sl_multiplier": 2.5, "rsi_enabled": False}, "SL2.5+NoRSI"),
    # Dynamic risk tuning
    ({"atr_sl_multiplier": 2.5, "dyn_risk_max_multi": 2.0}, "SL2.5+DynMax2.0"),
    ({"atr_sl_multiplier": 2.5, "dyn_risk_enabled": False}, "SL2.5+NoDynRisk"),
]

best_score = -999999
best_config = None
best_result = None

for overrides, label in test_configs:
    _real_stdout.write(f"\r  Testing: {label:<50}")
    _real_stdout.flush()

    r = run_test(overrides)
    if r is None:
        print(f" -> NO TRADES")
        continue

    n_losers = len(r["losers"])
    max_loss = min(r["losers"].values()) if r["losers"] else 0

    print(f" -> PnL: ${r['pnl']:>12,.0f} | PF: {r['pf']:.2f} | WR: {r['wr']:.1f}% | "
          f"DD: {r['dd']:.1f}% | Prof: {r['profitable']}/{r['total_syms']} | "
          f"Losers: {n_losers} (max: ${max_loss:,.0f})")

    # Score: maximize PnL * PF, heavily penalize losing symbols
    score = r["pnl"] * min(r["pf"], 3.0)
    # Bonus for fewer losers
    score *= (1.0 + 0.1 * r["profitable"])
    # Penalty for each losing symbol
    score *= (1.0 - 0.15 * n_losers)
    # Penalty for extreme drawdown
    if r["dd"] < -30:
        score *= 0.7
    # Penalty for large individual losses
    if max_loss < -100000:
        score *= 0.8

    if score > best_score:
        best_score = score
        best_config = (overrides, label)
        best_result = r

print(f"\n\n{'='*80}")
print(f"BEST CONFIG: {best_config[1]}")
print(f"  Overrides: {best_config[0]}")
print(f"  PnL: ${best_result['pnl']:,.0f} | PF: {best_result['pf']:.2f} | WR: {best_result['wr']:.1f}%")
print(f"  DD: {best_result['dd']:.1f}% | Profitable: {best_result['profitable']}/{best_result['total_syms']}")
print(f"\n  Per-Symbol:")
for s, p in best_result["sym_pnl"].items():
    t = best_result["sym_trades"].get(s, 0)
    marker = "+" if p > 0 else "-"
    print(f"    {s:<8} {marker}${abs(p):>12,.2f}  ({t} trades)")

# ============================================================
# STRESS TESTS with best config
# ============================================================
print(f"\n\n{'='*80}")
print(f"STRESS TESTS (using best config: {best_config[1]})")
print(f"{'='*80}")

stress_tests = [
    ("Normal (baseline)", {}),
    ("High commission (0.05%)", {"commission": 0.0005}),
    ("High slippage (0.15 ATR)", {"slippage_atr_frac": 0.15}),
    ("Both high costs", {"commission": 0.0005, "slippage_atr_frac": 0.15}),
    ("Max positions = 3", {"max_positions": 3}),
    ("Risk 0.5%", {"risk_percent": 0.5}),
    ("Risk 2.0%", {"risk_percent": 2.0}),
    ("No dynamic risk", {"dyn_risk_enabled": False}),
]

for st_label, st_overrides in stress_tests:
    combined = {**best_config[0], **st_overrides}
    _real_stdout.write(f"\r  Stress: {st_label:<45}")
    _real_stdout.flush()

    r = run_test(combined)
    if r is None:
        print(f" -> NO TRADES")
        continue

    n_losers = len(r["losers"])
    print(f" -> PnL: ${r['pnl']:>12,.0f} | PF: {r['pf']:.2f} | WR: {r['wr']:.1f}% | "
          f"DD: {r['dd']:.1f}% | Prof: {r['profitable']}/{r['total_syms']} | Losers: {n_losers}")
    if r["losers"]:
        for s, lp in sorted(r["losers"].items(), key=lambda x: x[1]):
            _real_stdout.write(f"          Loser: {s} ${lp:,.0f}\n")
