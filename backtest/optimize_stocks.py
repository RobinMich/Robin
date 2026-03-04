#!/usr/bin/env python3
"""Optimize stock preset parameters to maximize profit across ALL stock symbols."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from itertools import product
from backtester_v4 import (
    StrategyParams, Backtester, run_multi_symbol_backtest, ALL_SYMBOLS,
    get_stocks_params, get_xauusd_params, get_indices_params
)

# Only test stock symbols
STOCK_SYMBOLS = [s for s in ALL_SYMBOLS if s not in ("XAUUSD", "US100", "US500")]

# Parameter grid to test
param_grid = {
    "ema_fast": [13, 21],
    "ema_mid": [34, 50],
    "ema_slow": [89, 100],
    "adx_threshold_context": [8.0, 10.0, 12.0],
    "adx_threshold_validation": [5.0, 8.0],
    "bbw_squeeze_percentile": [50.0, 65.0, 75.0],
    "pb_atr_buffer": [2.0, 2.5, 3.0],
    "mom_score_min": [40, 50],
    "donchian_period": [8, 10],
    "atr_sl_multiplier": [1.5, 2.0],
    "rsi_long_max": [78.0, 85.0],
}

# Test key combos - not full grid (too large), but targeted tests
base = get_stocks_params()

best_pnl = -999999
best_pf = 0
best_params = None
best_result = None

# Focused tests: vary the most impactful params
test_configs = [
    # baseline
    {},
    # Relax context ADX
    {"adx_threshold_context": 8.0},
    {"adx_threshold_context": 10.0},
    # Relax validation ADX
    {"adx_threshold_validation": 5.0},
    # Relax BBW squeeze
    {"bbw_squeeze_percentile": 50.0},
    {"bbw_squeeze_percentile": 70.0},
    {"bbw_squeeze_percentile": 75.0},
    # Wider pullback zone
    {"pb_atr_buffer": 2.5},
    {"pb_atr_buffer": 3.0},
    # Lower momentum threshold
    {"mom_score_min": 40},
    {"mom_score_min": 35},
    # Relax RSI
    {"rsi_long_max": 85.0},
    {"rsi_enabled": False},
    # Shorter EMAs (more responsive)
    {"ema_fast": 13, "ema_mid": 34, "ema_slow": 89},
    # Wider SL
    {"atr_sl_multiplier": 2.0},
    {"atr_sl_multiplier": 2.5},
    # Shorter donchian
    {"donchian_period": 8},
    # Combined relaxed
    {"adx_threshold_context": 10.0, "bbw_squeeze_percentile": 70.0, "pb_atr_buffer": 2.5},
    {"adx_threshold_context": 8.0, "bbw_squeeze_percentile": 70.0, "pb_atr_buffer": 3.0, "mom_score_min": 40},
    {"adx_threshold_context": 10.0, "pb_atr_buffer": 2.5, "rsi_long_max": 85.0, "atr_sl_multiplier": 2.0},
    {"ema_fast": 13, "ema_mid": 34, "ema_slow": 89, "adx_threshold_context": 10.0, "bbw_squeeze_percentile": 65.0},
    # Best combo attempts
    {"adx_threshold_context": 10.0, "adx_threshold_validation": 5.0, "bbw_squeeze_percentile": 70.0,
     "pb_atr_buffer": 2.5, "mom_score_min": 40, "rsi_long_max": 85.0, "atr_sl_multiplier": 2.0},
    {"adx_threshold_context": 8.0, "adx_threshold_validation": 5.0, "bbw_squeeze_percentile": 75.0,
     "pb_atr_buffer": 3.0, "mom_score_min": 35, "rsi_long_max": 85.0, "atr_sl_multiplier": 2.0,
     "donchian_period": 8},
    # TP optimization
    {"tp1_rr": 2.0, "tp2_rr": 4.0},
    {"tp1_rr": 1.0, "tp2_rr": 2.5},
    {"tp1_fraction": 0.5, "tp1_rr": 1.5, "tp2_fraction": 0.3, "tp2_rr": 2.5},
    # Trail optimization
    {"trail_start_rr": 1.0, "atr_trail_multiplier": 1.5},
    {"trail_start_rr": 2.0, "atr_trail_multiplier": 2.5},
    {"chandelier_tighten_after_tp2": 0.5},
    # BE optimization
    {"be_rr_ratio": 1.0},
    {"be_rr_ratio": 2.0},
    # Max positions
    {"max_positions": 3},
    {"max_positions": 8},
]

import warnings
warnings.filterwarnings("ignore")

# Suppress print output during optimization
import io
_real_stdout = sys.stdout

for idx, overrides in enumerate(test_configs):
    # Build params
    p_dict = base.to_dict()
    p_dict.update(overrides)
    p = StrategyParams.from_dict(p_dict)

    _real_stdout.write(f"\r[{idx+1}/{len(test_configs)}] Testing: {str(overrides or 'BASELINE')[:60]:<60}")
    _real_stdout.flush()

    sys.stdout = io.StringIO()  # Suppress backtest output
    bt, symbols_tested = run_multi_symbol_backtest(
        STOCK_SYMBOLS, params=p, initial_capital=100000.0, use_preset=False
    )
    sys.stdout = _real_stdout
    if not bt.trades:
        print(f"\n  -> NO TRADES")
        continue
    result, _ = bt.get_results()

    trades = result.get("total_trades", 0)
    pnl = result.get("total_pnl", 0)
    pf = result.get("profit_factor", 0)
    dd = result.get("max_drawdown_pct", -100)
    wr = result.get("win_rate", 0)

    # Count profitable symbols
    sym_pnl = {}
    for t in bt.trades:
        s = t.symbol
        sym_pnl[s] = sym_pnl.get(s, 0) + t.pnl
    profitable_syms = sum(1 for v in sym_pnl.values() if v > 0)
    total_syms = len(sym_pnl)

    print(f"  -> Trades: {trades} | PnL: ${pnl:,.0f} | PF: {pf:.2f} | WR: {wr:.1f}% | "
          f"DD: {dd:.1f}% | Prof Syms: {profitable_syms}/{total_syms}")

    # Score: balance between PnL, PF, and number of profitable symbols
    score = pnl * min(pf, 3.0) * (profitable_syms / max(total_syms, 1))
    if dd < -40:
        score *= 0.5  # Penalize extreme drawdown

    if score > best_pnl:
        best_pnl = score
        best_pf = pf
        best_params = overrides
        best_result = {
            "trades": trades, "pnl": pnl, "pf": pf, "wr": wr,
            "dd": dd, "prof_syms": profitable_syms, "total_syms": total_syms,
            "sym_pnl": dict(sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True))
        }

print("\n" + "=" * 80)
print("BEST CONFIGURATION:")
print(f"  Overrides: {best_params}")
print(f"  Score: {best_pnl:,.0f}")
print(f"  Trades: {best_result['trades']} | PnL: ${best_result['pnl']:,.0f} | PF: {best_result['pf']:.2f}")
print(f"  WR: {best_result['wr']:.1f}% | DD: {best_result['dd']:.1f}%")
print(f"  Profitable Syms: {best_result['prof_syms']}/{best_result['total_syms']}")
print(f"\n  Per-Symbol PnL:")
for s, p in best_result["sym_pnl"].items():
    marker = "+" if p > 0 else "-"
    print(f"    {s:<8} {marker}${abs(p):>12,.2f}")
