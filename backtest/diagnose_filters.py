#!/usr/bin/env python3
"""Diagnose why each symbol gets no/few trades - uses backtester's own logic."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from backtester_v4 import (
    StrategyParams, Backtester, load_symbol_data, add_indicators,
    get_context_signal_long, get_validation_signal_long, get_entry_signal_long,
    check_rsi_filter, check_supertrend_filter, calculate_momentum_score,
    find_htf_bar, get_stocks_params, ALL_SYMBOLS, check_session_filter
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def diagnose_symbol(symbol, params):
    data = load_symbol_data(symbol, DATA_DIR)
    if not data:
        return {"status": "NO_DATA"}

    # Use same TF selection as backtester for stocks
    ctx_df = data.get("D1", data.get("W1"))
    val_df = data.get("H4", data.get("D1"))
    entry_df = data.get("H1", data.get("H4", data.get("H2")))

    if ctx_df is None or val_df is None or entry_df is None:
        return {"status": "MISSING_TF"}

    ctx = add_indicators(ctx_df, params)
    val = add_indicators(val_df, params)
    ent = add_indicators(entry_df, params)

    min_bars = max(params.ema_slow, params.bbw_lookback + params.bb_period,
                   params.donchian_period + 5)
    if len(ent) < min_bars:
        return {"status": f"TOO_FEW_BARS ({len(ent)})"}

    total = len(ent) - min_bars
    counts = {
        "mom_pass": 0, "ctx_found": 0, "val_found": 0,
        "ctx_pass": 0, "val_pass": 0, "ent_pass": 0,
        "rsi_pass": 0, "all_pass": 0,
        # Sub-conditions
        "ctx_ema": 0, "ctx_close_above": 0, "ctx_adx": 0, "ctx_di": 0,
        "val_ema": 0, "val_pb": 0, "val_adx": 0, "val_bbw": 0,
        "ent_ema": 0, "ent_di": 0, "ent_donch": 0, "ent_vol": 0,
    }

    from backtester_v4 import _safe_get

    for i in range(min_bars, len(ent)):
        current_time = ent.index[i]

        # Momentum score (checked before ctx/val in backtester)
        mom = calculate_momentum_score(ent, i, params)
        if mom < params.mom_score_min:
            continue
        counts["mom_pass"] += 1

        ctx_row = find_htf_bar(ctx, current_time)
        val_row = find_htf_bar(val, current_time)

        if ctx_row is not None:
            counts["ctx_found"] += 1
        if val_row is not None:
            counts["val_found"] += 1
        if ctx_row is None or val_row is None:
            continue

        # --- Context sub-checks ---
        ema_f = _safe_get(ctx_row, "ema_fast")
        ema_m = _safe_get(ctx_row, "ema_mid")
        ema_s = _safe_get(ctx_row, "ema_slow")
        close_c = _safe_get(ctx_row, "close")
        adx_c = _safe_get(ctx_row, "adx")
        dip_c = _safe_get(ctx_row, "di_plus")
        dim_c = _safe_get(ctx_row, "di_minus")

        if not (np.isnan(ema_f) or np.isnan(ema_m) or np.isnan(ema_s)):
            if ema_f > ema_m > ema_s:
                counts["ctx_ema"] += 1
                if not np.isnan(close_c) and close_c >= ema_f:
                    counts["ctx_close_above"] += 1
        if not np.isnan(adx_c) and adx_c >= params.adx_threshold_context:
            counts["ctx_adx"] += 1
        if not np.isnan(dip_c) and not np.isnan(dim_c) and dip_c > dim_c:
            counts["ctx_di"] += 1

        ctx_ok = get_context_signal_long(ctx_row, params)
        if ctx_ok:
            counts["ctx_pass"] += 1

        # --- Validation sub-checks ---
        vf = _safe_get(val_row, "ema_fast")
        vs = _safe_get(val_row, "ema_slow")
        vm = _safe_get(val_row, "ema_mid")
        vatr = _safe_get(val_row, "atr")
        vc = _safe_get(val_row, "close")
        vadx = _safe_get(val_row, "adx")
        vbbw = _safe_get(val_row, "bbw_pctile")

        if not np.isnan(vf) and not np.isnan(vs) and vf > vs:
            counts["val_ema"] += 1
            if not np.isnan(vatr) and not np.isnan(vm):
                ab = vatr * params.pb_atr_buffer
                if (vc >= vm and vc <= vf + ab) or (vf - ab <= vc <= vf + ab):
                    counts["val_pb"] += 1
        if not np.isnan(vadx) and vadx >= params.adx_threshold_validation:
            counts["val_adx"] += 1
        if not np.isnan(vbbw) and vbbw == 1.0:
            counts["val_bbw"] += 1

        val_ok = get_validation_signal_long(val_row, params)
        if val_ok:
            counts["val_pass"] += 1

        # --- Entry checks ---
        if i >= params.donchian_period + 1:
            erow = ent.iloc[i]
            e_ema = float(erow["ema_fast"]) if "ema_fast" in erow.index else np.nan
            e_close = float(erow["close"])
            e_dip = float(erow["di_plus"]) if "di_plus" in erow.index else np.nan
            e_dim = float(erow["di_minus"]) if "di_minus" in erow.index else np.nan
            e_vol = float(erow["volume"]) if "volume" in erow.index else 0
            e_vma = float(erow["volume_ma"]) if "volume_ma" in erow.index else np.nan

            if not np.isnan(e_ema) and e_close >= e_ema:
                counts["ent_ema"] += 1
            if not np.isnan(e_dip) and not np.isnan(e_dim) and e_dip > e_dim:
                counts["ent_di"] += 1
            ls = i - params.donchian_period - 1
            le = i - 1
            if ls >= 0:
                dh = ent.iloc[ls:le]["high"].max()
                if e_close > dh:
                    counts["ent_donch"] += 1
            if e_vol > 0 and not np.isnan(e_vma) and e_vma > 0:
                if e_vol >= e_vma * params.volume_multiplier:
                    counts["ent_vol"] += 1

        ent_ok = get_entry_signal_long(ent, i, params)
        if ent_ok:
            counts["ent_pass"] += 1

        rsi_ok = check_rsi_filter(ent, i, params, True)
        if rsi_ok:
            counts["rsi_pass"] += 1

        if ctx_ok and val_ok and ent_ok and rsi_ok:
            counts["all_pass"] += 1

    counts["total"] = total
    counts["status"] = "OK"
    return counts


params = get_stocks_params()
stocks = [s for s in ALL_SYMBOLS if s not in ("XAUUSD", "US100", "US500")]

def pct(n, t):
    return f"{100*n/max(t,1):.1f}%"

print(f"\n{'Sym':<7} {'Bars':>5} {'Mom':>6} {'CTX':>6} {'cEMA':>5} {'cClA':>5} {'cADX':>5} {'cDI':>5} "
      f"{'VAL':>6} {'vEMA':>5} {'vPB':>5} {'vADX':>5} {'vBBW':>5} "
      f"{'ENT':>6} {'eEMA':>5} {'eDI':>5} {'eDnc':>5} {'eVol':>5} "
      f"{'RSI':>5} {'ALL':>5}")
print("-" * 140)

for sym in sorted(stocks):
    r = diagnose_symbol(sym, params)
    if r["status"] != "OK":
        print(f"{sym:<7} {r['status']}")
        continue
    t = r["total"]
    m = r["mom_pass"]
    print(f"{sym:<7} {t:>5} {pct(m,t):>6} {pct(r['ctx_pass'],m):>6} "
          f"{pct(r['ctx_ema'],m):>5} {pct(r['ctx_close_above'],m):>5} {pct(r['ctx_adx'],m):>5} {pct(r['ctx_di'],m):>5} "
          f"{pct(r['val_pass'],m):>6} {pct(r['val_ema'],m):>5} {pct(r['val_pb'],m):>5} {pct(r['val_adx'],m):>5} {pct(r['val_bbw'],m):>5} "
          f"{pct(r['ent_pass'],m):>6} {pct(r['ent_ema'],m):>5} {pct(r['ent_di'],m):>5} {pct(r['ent_donch'],m):>5} {pct(r['ent_vol'],m):>5} "
          f"{pct(r['rsi_pass'],m):>5} {r['all_pass']:>5}")
