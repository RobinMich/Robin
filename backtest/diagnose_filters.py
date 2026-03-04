#!/usr/bin/env python3
"""Diagnose why each symbol gets no/few trades - check each filter individually."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from backtester_v4 import (
    StrategyParams, Backtester, load_symbol_data, add_indicators,
    get_context_signal_long, get_validation_signal_long, get_entry_signal_long,
    check_rsi_filter, calculate_momentum_score, get_stocks_params,
    _safe_get, ALL_SYMBOLS
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def diagnose_symbol(symbol, params):
    data = load_symbol_data(symbol, DATA_DIR)
    if not data:
        return {"status": "NO_DATA"}

    for tf in data:
        data[tf] = add_indicators(data[tf], params)

    # Get timeframes (stocks: D1/H4/H1)
    ctx_df = data.get("D1")
    val_df = data.get("H4")
    entry_df = data.get("H1")

    if ctx_df is None or val_df is None or entry_df is None:
        return {"status": "MISSING_TF", "available": list(data.keys())}

    # Count how often each filter passes
    n_entry_bars = len(entry_df)
    ctx_pass = 0
    val_pass = 0
    entry_pass = 0
    rsi_pass = 0
    mom_pass = 0
    all_pass = 0

    # Also track sub-conditions
    ctx_ema_pass = 0
    ctx_adx_pass = 0
    ctx_di_pass = 0
    val_ema_pass = 0
    val_pb_pass = 0
    val_adx_pass = 0
    val_bbw_pass = 0
    ent_ema_pass = 0
    ent_di_pass = 0
    ent_donch_pass = 0
    ent_vol_pass = 0

    for i in range(50, len(entry_df)):
        ent_time = entry_df.index[i]

        # Find matching context bar
        ctx_mask = ctx_df.index <= ent_time
        if not ctx_mask.any():
            continue
        ctx_idx = ctx_df.index[ctx_mask][-1]
        ctx_row = ctx_df.loc[ctx_idx]

        # Find matching validation bar
        val_mask = val_df.index <= ent_time
        if not val_mask.any():
            continue
        val_idx = val_df.index[val_mask][-1]
        val_row = val_df.loc[val_idx]

        # --- Context sub-checks ---
        ema_f = _safe_get(ctx_row, "ema_fast")
        ema_m = _safe_get(ctx_row, "ema_mid")
        ema_s = _safe_get(ctx_row, "ema_slow")
        close_c = _safe_get(ctx_row, "close")
        adx_c = _safe_get(ctx_row, "adx")
        dip_c = _safe_get(ctx_row, "di_plus")
        dim_c = _safe_get(ctx_row, "di_minus")

        if not np.isnan(ema_f) and not np.isnan(ema_m) and not np.isnan(ema_s):
            if ema_f > ema_m > ema_s and close_c > ema_f:
                ctx_ema_pass += 1
        if not np.isnan(adx_c) and adx_c >= params.adx_threshold_context:
            ctx_adx_pass += 1
        if not np.isnan(dip_c) and not np.isnan(dim_c) and dip_c > dim_c:
            ctx_di_pass += 1

        ctx_ok = get_context_signal_long(ctx_row, params)
        if ctx_ok:
            ctx_pass += 1

        # --- Validation sub-checks ---
        vf = _safe_get(val_row, "ema_fast")
        vs = _safe_get(val_row, "ema_slow")
        vm = _safe_get(val_row, "ema_mid")
        vatr = _safe_get(val_row, "atr")
        vc = _safe_get(val_row, "close")
        vadx = _safe_get(val_row, "adx")
        vbbw = _safe_get(val_row, "bbw_pctile")

        if not np.isnan(vf) and not np.isnan(vs) and vf > vs:
            val_ema_pass += 1
            if not np.isnan(vatr) and not np.isnan(vm):
                ab = vatr * params.pb_atr_buffer
                if (vc >= vm and vc <= vf + ab) or (vf - ab <= vc <= vf + ab):
                    val_pb_pass += 1
        if not np.isnan(vadx) and vadx >= params.adx_threshold_validation:
            val_adx_pass += 1
        if not np.isnan(vbbw) and vbbw == 1.0:
            val_bbw_pass += 1

        val_ok = get_validation_signal_long(val_row, params)
        if val_ok:
            val_pass += 1

        # --- Entry sub-checks ---
        if i >= params.donchian_period + 1:
            erow = entry_df.iloc[i]
            e_ema = float(erow["ema_fast"]) if "ema_fast" in erow.index else np.nan
            e_close = float(erow["close"])
            e_dip = float(erow["di_plus"]) if "di_plus" in erow.index else np.nan
            e_dim = float(erow["di_minus"]) if "di_minus" in erow.index else np.nan
            e_vol = float(erow["volume"]) if "volume" in erow.index else 0
            e_vma = float(erow["volume_ma"]) if "volume_ma" in erow.index else np.nan

            if not np.isnan(e_ema) and e_close >= e_ema:
                ent_ema_pass += 1
            if not np.isnan(e_dip) and not np.isnan(e_dim) and e_dip > e_dim:
                ent_di_pass += 1

            ls = i - params.donchian_period - 1
            le = i - 1
            if ls >= 0:
                dh = entry_df.iloc[ls:le]["high"].max()
                if e_close > dh:
                    ent_donch_pass += 1

            if e_vol > 0 and not np.isnan(e_vma) and e_vma > 0:
                if e_vol >= e_vma * params.volume_multiplier:
                    ent_vol_pass += 1

        ent_ok = get_entry_signal_long(entry_df, i, params)
        if ent_ok:
            entry_pass += 1

        # RSI
        rsi_ok = check_rsi_filter(entry_df, i, params, True)
        if rsi_ok:
            rsi_pass += 1

        # Momentum score
        mom = calculate_momentum_score(entry_df, i, params)
        if mom >= params.mom_score_min:
            mom_pass += 1

        # All combined
        if ctx_ok and val_ok and ent_ok and rsi_ok and mom >= params.mom_score_min:
            all_pass += 1

    total = len(entry_df) - 50
    return {
        "status": "OK",
        "entry_bars": total,
        "ctx_pass": ctx_pass, "ctx_pct": round(100*ctx_pass/max(total,1), 1),
        "ctx_ema": round(100*ctx_ema_pass/max(total,1), 1),
        "ctx_adx": round(100*ctx_adx_pass/max(total,1), 1),
        "ctx_di": round(100*ctx_di_pass/max(total,1), 1),
        "val_pass": val_pass, "val_pct": round(100*val_pass/max(total,1), 1),
        "val_ema": round(100*val_ema_pass/max(total,1), 1),
        "val_pb": round(100*val_pb_pass/max(total,1), 1),
        "val_adx": round(100*val_adx_pass/max(total,1), 1),
        "val_bbw": round(100*val_bbw_pass/max(total,1), 1),
        "ent_pass": entry_pass, "ent_pct": round(100*entry_pass/max(total,1), 1),
        "ent_ema": round(100*ent_ema_pass/max(total,1), 1),
        "ent_di": round(100*ent_di_pass/max(total,1), 1),
        "ent_donch": round(100*ent_donch_pass/max(total,1), 1),
        "ent_vol": round(100*ent_vol_pass/max(total,1), 1),
        "rsi_pass": rsi_pass, "rsi_pct": round(100*rsi_pass/max(total,1), 1),
        "mom_pass": mom_pass, "mom_pct": round(100*mom_pass/max(total,1), 1),
        "all_pass": all_pass,
    }


params = get_stocks_params()
stocks = [s for s in ALL_SYMBOLS if s not in ("XAUUSD", "US100", "US500")]

print(f"{'Symbol':<8} {'Bars':>6} {'CTX%':>6} {'cEMA':>5} {'cADX':>5} {'cDI':>5} "
      f"{'VAL%':>6} {'vEMA':>5} {'vPB':>5} {'vADX':>5} {'vBBW':>5} "
      f"{'ENT%':>6} {'eDI':>5} {'eDnc':>5} {'eVol':>5} "
      f"{'RSI%':>5} {'MOM%':>5} {'ALL':>5}")
print("-" * 130)

for sym in sorted(stocks):
    r = diagnose_symbol(sym, params)
    if r["status"] != "OK":
        print(f"{sym:<8} {r['status']}")
        continue
    print(f"{sym:<8} {r['entry_bars']:>6} {r['ctx_pct']:>5.1f}% {r['ctx_ema']:>5.1f} {r['ctx_adx']:>5.1f} {r['ctx_di']:>5.1f} "
          f"{r['val_pct']:>5.1f}% {r['val_ema']:>5.1f} {r['val_pb']:>5.1f} {r['val_adx']:>5.1f} {r['val_bbw']:>5.1f} "
          f"{r['ent_pct']:>5.1f}% {r['ent_di']:>5.1f} {r['ent_donch']:>5.1f} {r['ent_vol']:>5.1f} "
          f"{r['rsi_pct']:>5.1f} {r['mom_pct']:>5.1f} {r['all_pass']:>5}")
