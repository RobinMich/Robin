#!/usr/bin/env python3
"""
FAST H1 Optimization v2: Enhanced entry filters for >50% WR
=============================================================
Key insight: H1 Donchian breakouts are 4x noisier than H4.
Solution: Stronger entry filters + longer Donchian + ADX on entry TF.

Timeframes: W1 (context) -> D1 (validation) -> H1 (entry)
"""

import sys, os, json, itertools, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester import (
    StrategyParams, load_csv_data, add_indicators,
    resample_to_weekly, print_results, ALL_SYMBOLS,
)
from optimizer import monte_carlo_stress_test

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


# ============================================================
# EXTENDED STRATEGY PARAMS (H1-specific additions)
# ============================================================
class H1Params:
    """Extended params with H1-specific entry filters."""
    def __init__(self, **kwargs):
        # Standard params
        self.ema_fast = kwargs.get("ema_fast", 21)
        self.ema_mid = kwargs.get("ema_mid", 50)
        self.ema_slow = kwargs.get("ema_slow", 100)
        self.adx_period = kwargs.get("adx_period", 14)
        self.adx_threshold_context = kwargs.get("adx_threshold_context", 20)
        self.adx_threshold_validation = kwargs.get("adx_threshold_validation", 10)
        self.atr_period = kwargs.get("atr_period", 14)
        self.atr_sl_multiplier = kwargs.get("atr_sl_multiplier", 1.5)
        self.atr_trail_multiplier = kwargs.get("atr_trail_multiplier", 2.5)
        self.bb_period = kwargs.get("bb_period", 20)
        self.bb_deviation = kwargs.get("bb_deviation", 2.0)
        self.bbw_lookback = kwargs.get("bbw_lookback", 50)
        self.bbw_squeeze_percentile = kwargs.get("bbw_squeeze_percentile", 45)
        self.donchian_period = kwargs.get("donchian_period", 20)
        self.volume_period = kwargs.get("volume_period", 20)
        self.volume_multiplier = kwargs.get("volume_multiplier", 1.0)
        self.risk_percent = kwargs.get("risk_percent", 1.0)
        self.be_rr_ratio = kwargs.get("be_rr_ratio", 1.0)
        self.trail_start_rr = kwargs.get("trail_start_rr", 2.0)
        self.max_positions = kwargs.get("max_positions", 5)
        self.require_bullish_bar = kwargs.get("require_bullish_bar", True)
        self.pb_atr_buffer = kwargs.get("pb_atr_buffer", 1.0)
        self.be_mode = kwargs.get("be_mode", "pullback")
        self.commission = kwargs.get("commission", 0.0001)
        self.slippage_atr_frac = kwargs.get("slippage_atr_frac", 0.05)

        # H1-specific entry enhancements
        self.h1_donchian_period = kwargs.get("h1_donchian_period", 40)  # Longer for H1
        self.h1_adx_min = kwargs.get("h1_adx_min", 15)  # ADX filter on entry TF
        self.h1_breakout_margin = kwargs.get("h1_breakout_margin", 0.1)  # ATR fraction above DC
        self.h1_above_all_emas = kwargs.get("h1_above_all_emas", True)  # Require all EMAs
        self.h1_min_bar_body_pct = kwargs.get("h1_min_bar_body_pct", 0.4)  # Min body size

    def to_dict(self):
        return self.__dict__.copy()

    def to_strategy_params(self):
        """Convert to backtester StrategyParams."""
        sp = StrategyParams()
        for k in sp.__dataclass_fields__:
            if hasattr(self, k):
                setattr(sp, k, getattr(self, k))
        return sp


# ============================================================
# DATA LOADING
# ============================================================
def preload_data(symbols):
    print("  Loading data...")
    all_data = {}
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for symbol in symbols:
        data = {}
        for fp, tf in [
            (os.path.join(DATA_DIR, f"{symbol}_1W.csv"), "W1"),
            (os.path.join(DATA_DIR, f"{symbol}_1D.csv"), "D1"),
            (os.path.join(DATA_DIR, f"{symbol}_H4.csv"), "H4"),
            (os.path.join(DATA_DIR, f"{symbol}_1H.csv"), "H1"),
            (os.path.join(repo_root, f"BATS_{symbol}, 1W.csv"), "W1"),
            (os.path.join(repo_root, f"BATS_{symbol}, 1D.csv"), "D1"),
            (os.path.join(repo_root, f"BATS_{symbol}, 120.csv"), "H2"),
        ]:
            if os.path.exists(fp) and tf not in data:
                try:
                    df = load_csv_data(fp)
                    if len(df) > 50:
                        data[tf] = df
                except:
                    pass
        if data:
            all_data[symbol] = data
    print(f"  Loaded {len(all_data)} symbols")
    return all_data


# ============================================================
# VECTORIZED BACKTESTER WITH ENHANCED H1 ENTRY
# ============================================================
class H1Backtester:
    def __init__(self, params, initial_capital=100000.0):
        self.p = params
        self.sp = params.to_strategy_params()
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.trades = []
        self.open_trades = []

    def _map_htf_signals(self, ctx_df, val_df, entry_df):
        """Pre-compute HTF signals using merge_asof."""
        p = self.p
        sp = self.sp

        ctx = add_indicators(ctx_df, sp)
        val = add_indicators(val_df, sp)
        ent = add_indicators(entry_df, sp)

        # Context signal (W1)
        ctx_sig = pd.DataFrame(index=ctx.index)
        ctx_sig["ctx_ok"] = (
            (ctx["ema_fast"] > ctx["ema_mid"]) &
            (ctx["ema_mid"] > ctx["ema_slow"]) &
            (ctx["close"] >= ctx["ema_fast"]) &
            (ctx["adx"] >= p.adx_threshold_context) &
            (ctx["di_plus"] > ctx["di_minus"])
        ).astype(int)

        # Validation signal (D1)
        atr_buf = val["atr"] * p.pb_atr_buffer
        zone_a = (val["close"] >= val["ema_mid"]) & (val["close"] <= val["ema_fast"] + atr_buf)
        zone_b = (val["close"] >= val["ema_fast"] - atr_buf) & (val["close"] <= val["ema_fast"] + atr_buf)

        val_sig = pd.DataFrame(index=val.index)
        val_sig["val_ok"] = (
            (val["ema_fast"] > val["ema_slow"]) &
            (zone_a | zone_b) &
            (val["adx"] >= p.adx_threshold_validation) &
            (val["bbw_pctile"] == 1.0)
        ).astype(int)

        # Map to entry bars
        ent_times = pd.DataFrame({"entry_time": ent.index}, index=ent.index)

        ctx_mapped = pd.merge_asof(
            ent_times.reset_index().rename(columns={"datetime": "ts"}),
            ctx_sig.reset_index().rename(columns={"datetime": "ctx_ts"}),
            left_on="entry_time", right_on="ctx_ts", direction="backward"
        )
        val_mapped = pd.merge_asof(
            ent_times.reset_index().rename(columns={"datetime": "ts"}),
            val_sig.reset_index().rename(columns={"datetime": "val_ts"}),
            left_on="entry_time", right_on="val_ts", direction="backward"
        )

        ent["ctx_ok"] = ctx_mapped["ctx_ok"].values
        ent["val_ok"] = val_mapped["val_ok"].values

        # Pre-compute H1 Donchian with extended period
        dc_period = p.h1_donchian_period
        ent["dc_upper_h1"] = ent["high"].rolling(dc_period).max().shift(1)

        return ent

    def run_symbol(self, symbol, ctx_df, val_df, entry_df):
        p = self.p
        sp = self.sp
        min_bars = max(sp.ema_slow, sp.bbw_lookback + sp.bb_period,
                       p.h1_donchian_period + 5, 60)

        if len(entry_df) < min_bars:
            return

        ent = self._map_htf_signals(ctx_df, val_df, entry_df)

        for i in range(min_bars, len(ent)):
            self._manage_trades(ent, i)

            if len(self.open_trades) >= p.max_positions:
                continue

            row = ent.iloc[i]

            # HTF check (pre-computed)
            ctx_ok = row.get("ctx_ok", 0)
            val_ok = row.get("val_ok", 0)
            if hasattr(ctx_ok, 'item'): ctx_ok = ctx_ok.item()
            if hasattr(val_ok, 'item'): val_ok = val_ok.item()
            if not ctx_ok or not val_ok:
                continue

            # === ENHANCED H1 ENTRY SIGNAL ===
            close = float(row["close"])
            open_p = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            ema_f = float(row["ema_fast"])
            ema_m = float(row["ema_mid"])
            ema_s = float(row["ema_slow"])
            adx = float(row["adx"])
            di_p = float(row["di_plus"])
            di_m = float(row["di_minus"])
            atr = float(row["atr"])
            dc_upper = row.get("dc_upper_h1", np.nan)
            if hasattr(dc_upper, 'item'): dc_upper = dc_upper.item()

            if np.isnan(ema_f) or np.isnan(adx) or np.isnan(atr) or np.isnan(dc_upper):
                continue
            if atr <= 0 or close <= 0:
                continue

            # 1. DI+ > DI- (trend direction on H1)
            if np.isnan(di_p) or np.isnan(di_m) or di_p <= di_m:
                continue

            # 2. ADX filter on H1 (NEW: require trending on entry TF)
            if adx < p.h1_adx_min:
                continue

            # 3. Price above all EMAs on H1 (NEW: stricter alignment)
            if p.h1_above_all_emas:
                if np.isnan(ema_m) or np.isnan(ema_s):
                    continue
                if close < ema_f or close < ema_m or close < ema_s:
                    continue
            else:
                if close < ema_f:
                    continue

            # 4. Donchian breakout with margin (NEW: must exceed by ATR fraction)
            breakout_margin = atr * p.h1_breakout_margin
            if close <= dc_upper + breakout_margin:
                continue

            # 5. Bullish bar with minimum body (ENHANCED)
            body = close - open_p
            bar_range = high - low
            if bar_range <= 0:
                continue
            if p.require_bullish_bar:
                if body <= 0:
                    continue
                if body / bar_range < p.h1_min_bar_body_pct:
                    continue

            # 6. Volume filter
            vol = float(row["volume"]) if "volume" in row.index else 0
            vol_ma = float(row["volume_ma"]) if "volume_ma" in row.index else np.nan
            if vol > 0 and not np.isnan(vol_ma) and vol_ma > 0:
                if vol < vol_ma * p.volume_multiplier:
                    continue

            # === OPEN TRADE ===
            entry_price = close + atr * p.slippage_atr_frac
            sl_price = entry_price - atr * p.atr_sl_multiplier

            # Swing low
            sw_start = max(0, i - p.h1_donchian_period)
            swing_low = ent.iloc[sw_start:i]["low"].min()
            if swing_low > sl_price and swing_low < entry_price:
                sl_price = swing_low - entry_price * 0.001

            sl_dist = entry_price - sl_price
            if sl_dist <= 0:
                continue

            risk_amt = self.capital * p.risk_percent / 100.0
            lot_size = risk_amt / sl_dist
            commission = entry_price * lot_size * p.commission

            self.open_trades.append({
                "symbol": symbol,
                "entry_time": ent.index[i],
                "entry_price": entry_price,
                "sl_price": sl_price,
                "lot_size": lot_size,
                "initial_risk": risk_amt,
                "irp": sl_dist,
                "high_since": entry_price,
                "be_applied": False,
                "trailing": False,
            })
            self.capital -= commission

        # Close remaining
        if self.open_trades:
            last = ent.iloc[-1]
            for t in list(self.open_trades):
                self._close(t, ent.index[-1], float(last["close"]), "end_of_data")

    def _manage_trades(self, ent, i):
        p = self.p
        row = ent.iloc[i]
        lo = float(row["low"])
        hi = float(row["high"])
        cl = float(row["close"])
        atr = float(row["atr"]) if not pd.isna(row["atr"]) else 0

        for t in list(self.open_trades):
            if lo <= t["sl_price"]:
                reason = "stop_loss"
                if t["be_applied"] and abs(t["sl_price"] - t["entry_price"]) < atr * 0.1:
                    reason = "breakeven"
                self._close(t, ent.index[i], t["sl_price"], reason)
                continue

            if hi > t["high_since"]:
                t["high_since"] = hi

            irp = t["irp"]
            cur_rr = (cl - t["entry_price"]) / irp if irp > 0 else 0

            # BE
            if not t["be_applied"]:
                apply_be = False
                if p.be_mode == "rr":
                    apply_be = cur_rr >= p.be_rr_ratio
                else:
                    if t["high_since"] - t["entry_price"] >= irp * 0.5:
                        if i >= 5:
                            mini_dc = ent.iloc[i-5:i-1]["high"].max()
                            if cl > mini_dc:
                                apply_be = True
                if apply_be:
                    t["sl_price"] = t["entry_price"] + irp * 0.01
                    t["be_applied"] = True

            # Trail
            if cur_rr >= p.trail_start_rr:
                t["trailing"] = True
            if t["trailing"] and atr > 0:
                trail_sl = t["high_since"] - atr * p.atr_trail_multiplier
                if trail_sl > t["sl_price"] and trail_sl < cl:
                    t["sl_price"] = trail_sl

    def _close(self, t, exit_time, exit_price, reason):
        if reason in ("stop_loss", "breakeven"):
            exit_price -= t["entry_price"] * 0.0001
        pnl = (exit_price - t["entry_price"]) * t["lot_size"]
        rr = (exit_price - t["entry_price"]) / t["irp"] if t["irp"] > 0 else 0
        pnl -= exit_price * t["lot_size"] * self.p.commission
        self.capital += pnl
        self.trades.append({
            "symbol": t["symbol"], "entry_time": t["entry_time"],
            "exit_time": exit_time, "entry_price": t["entry_price"],
            "exit_price": exit_price, "pnl": pnl, "rr": rr,
            "exit_reason": reason, "initial_risk": t["initial_risk"],
        })
        if t in self.open_trades:
            self.open_trades.remove(t)

    def get_results(self):
        if not self.trades:
            return None
        df = pd.DataFrame(self.trades)
        n = len(df)
        winners = df[df["pnl"] > 0]
        losers = df[df["pnl"] <= 0]
        wr = len(winners) / n * 100
        gp = winners["pnl"].sum() if len(winners) else 0
        gl = abs(losers["pnl"].sum()) if len(losers) else 1
        pf = gp / gl if gl > 0 else float("inf")
        avg_win = winners["pnl"].mean() if len(winners) else 0
        avg_loss = losers["pnl"].mean() if len(losers) else 0
        exp = wr/100 * avg_win + (1-wr/100) * avg_loss
        cum = df["pnl"].cumsum()
        pk = cum.cummax()
        dd = cum - pk
        max_dd = dd.min()
        max_dd_pct = max_dd / self.initial_capital * 100

        return {
            "total_trades": n, "winners": len(winners), "losers": len(losers),
            "win_rate": round(wr, 2), "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2), "avg_rr": round(df["rr"].mean(), 2),
            "median_rr": round(df["rr"].median(), 2),
            "best_trade_rr": round(df["rr"].max(), 2),
            "worst_trade_rr": round(df["rr"].min(), 2),
            "total_pnl": round(df["pnl"].sum(), 2),
            "total_return_pct": round(df["pnl"].sum() / self.initial_capital * 100, 2),
            "profit_factor": round(pf, 2), "expectancy": round(exp, 2),
            "max_drawdown": round(max_dd, 2), "max_drawdown_pct": round(max_dd_pct, 2),
            "initial_capital": self.initial_capital,
            "final_capital": round(self.capital, 2),
            "exit_reasons": df["exit_reason"].value_counts().to_dict(),
            "avg_hold_hours": 0, "max_consec_wins": 0, "max_consec_losses": 0,
        }, df


def run_bt(all_data, symbols, params, cap=100000.0):
    bt = H1Backtester(params, cap)
    tested = []
    for sym in symbols:
        raw = all_data.get(sym)
        if raw is None:
            continue
        ctx = raw.get("W1")
        val = raw.get("D1")
        ent = raw.get("H1")
        if ent is None: ent = raw.get("H4")
        if ent is None: ent = raw.get("H2")
        if ctx is None and val is not None:
            ctx = resample_to_weekly(val)
        if ent is None: ent = val
        if ctx is None or val is None or ent is None:
            continue
        bt.run_symbol(sym, ctx, val, ent)
        tested.append(sym)
    return bt, tested


def calc_score(stats, n_syms):
    if stats["win_rate"] < 50:
        return 0
    return (stats["profit_factor"] *
            np.sqrt(stats["total_trades"]) *
            (1 - abs(stats["max_drawdown_pct"]) / 100) *
            max(stats["avg_rr"], 0.1) *
            np.sqrt(n_syms))


# ============================================================
# PHASE 1: Grid search with enhanced H1 params
# ============================================================
def phase1(all_data, symbols):
    print("=" * 70)
    print("  PHASE 1: ENHANCED H1 GRID SEARCH")
    print("  Extra filters: H1 ADX, longer Donchian, breakout margin,")
    print("  all-EMA alignment, min body size")
    print("=" * 70)

    grid = {
        # Standard params
        "ema_fast": [13, 21],
        "ema_mid": [34, 50],
        "ema_slow": [89, 100],
        "adx_threshold_context": [15, 20],
        "adx_threshold_validation": [8, 10],
        "atr_sl_multiplier": [1.5, 2.0],
        "atr_trail_multiplier": [2.0, 2.5, 3.0],
        "bbw_squeeze_percentile": [35, 45, 55],
        "pb_atr_buffer": [0.5, 0.8, 1.0, 1.5],
        "volume_multiplier": [0.9, 1.0],
        "trail_start_rr": [1.5, 2.0],
        "be_mode": ["pullback"],
        # H1-specific enhanced params
        "h1_donchian_period": [30, 40, 60],       # Longer DC for H1
        "h1_adx_min": [10, 15, 20],               # H1 ADX filter
        "h1_breakout_margin": [0.0, 0.1, 0.2],    # ATR fraction above DC
        "h1_above_all_emas": [True, False],        # Require all EMAs
        "require_bullish_bar": [True],             # Always require bullish
        "h1_min_bar_body_pct": [0.3, 0.5],        # Min bar body
    }

    keys = list(grid.keys())
    all_c = list(itertools.product(*[grid[k] for k in keys]))
    print(f"  Total combos: {len(all_c)}")

    np.random.seed(42)
    N = 80
    if len(all_c) > N:
        idx = np.random.choice(len(all_c), N, replace=False)
        combos = [all_c[i] for i in sorted(idx)]
    else:
        combos = all_c
    print(f"  Sampling: {len(combos)}\n")

    results = []
    t0 = time.time()

    for ci, combo in enumerate(combos):
        kv = {keys[i]: combo[i] for i in range(len(keys))}
        params = H1Params(**kv)

        bt, tested = run_bt(all_data, symbols, params)
        res = bt.get_results()

        if res is not None:
            stats, tdf = res
            if stats["total_trades"] >= 5:
                ns = tdf["symbol"].nunique()
                d = kv.copy()
                d.update({
                    "total_trades": stats["total_trades"],
                    "win_rate": stats["win_rate"],
                    "profit_factor": stats["profit_factor"],
                    "avg_rr": stats["avg_rr"],
                    "max_dd_pct": stats["max_drawdown_pct"],
                    "total_return_pct": stats["total_return_pct"],
                    "n_symbols": ns,
                    "score": round(calc_score(stats, ns), 4),
                })
                results.append(d)

        if (ci + 1) % 5 == 0:
            el = time.time() - t0
            rate = (ci + 1) / el
            eta = (len(combos) - ci - 1) / rate
            ng = sum(1 for r in results if r["score"] > 0)
            print(f"  [{ci+1:>3}/{len(combos)}] {el:.0f}s ETA={eta:.0f}s | "
                  f"{ng} >50%WR | {len(results)} valid")

    good = [r for r in results if r["score"] > 0]
    good.sort(key=lambda x: x["score"], reverse=True)

    # Also sort all by WR for debugging
    all_by_wr = sorted(results, key=lambda x: x.get("win_rate", 0), reverse=True)

    print(f"\n  Phase 1: {time.time()-t0:.0f}s")
    print(f"  {len(good)}/{len(results)} >50%WR")

    if good:
        print(f"\n  TOP 20 (>50%WR):")
        for i, r in enumerate(good[:20]):
            ema = f"{r['ema_fast']}/{r['ema_mid']}/{r['ema_slow']}"
            print(f"  {i+1:>3} {ema} DC={r['h1_donchian_period']} "
                  f"ADXe={r['h1_adx_min']} Mrg={r['h1_breakout_margin']} "
                  f"Body={r['h1_min_bar_body_pct']} AllEMA={r['h1_above_all_emas']} "
                  f"| N={r['total_trades']:>3} S={r['n_symbols']} "
                  f"WR={r['win_rate']:>5.1f}% PF={r['profit_factor']:>4.2f} "
                  f"RR={r['avg_rr']:>+4.2f} DD={r['max_dd_pct']:>5.1f}% "
                  f"Ret={r['total_return_pct']:>7.1f}%")

    # Always show best by WR
    print(f"\n  TOP 10 BY WIN RATE (any):")
    for i, r in enumerate(all_by_wr[:10]):
        ema = f"{r['ema_fast']}/{r['ema_mid']}/{r['ema_slow']}"
        print(f"  {i+1:>3} {ema} DC={r['h1_donchian_period']} "
              f"ADXe={r['h1_adx_min']} Mrg={r['h1_breakout_margin']} "
              f"| N={r['total_trades']:>3} S={r['n_symbols']} "
              f"WR={r['win_rate']:>5.1f}% PF={r['profit_factor']:>4.2f} "
              f"RR={r['avg_rr']:>+4.2f}")

    return good, results


# ============================================================
# PHASE 2: Fine-tune top configs
# ============================================================
def phase2(all_data, symbols, top_configs):
    print(f"\n{'='*70}")
    print("  PHASE 2: FINE-TUNING")
    print(f"{'='*70}")

    if not top_configs:
        return []

    refined = []
    t0 = time.time()

    for rank, base in enumerate(top_configs[:5]):
        print(f"\n  #{rank+1} (WR={base['win_rate']:.1f}% PF={base['profit_factor']:.2f})...")

        seen = set()
        variations = []

        for sl_d in [-0.25, 0, 0.25]:
            for tr_d in [-0.5, 0, 0.5]:
                for ts in [1.0, 1.5, 2.0]:
                    for pb_d in [-0.2, 0, 0.3]:
                        for bbw_d in [-5, 0, 5]:
                            for dc_d in [-10, 0, 10]:
                                for adx_d in [-5, 0, 5]:
                                    sl = round(base["atr_sl_multiplier"] + sl_d, 2)
                                    tr = round(base["atr_trail_multiplier"] + tr_d, 2)
                                    pb = round(base["pb_atr_buffer"] + pb_d, 2)
                                    bbw = base["bbw_squeeze_percentile"] + bbw_d
                                    dc = base["h1_donchian_period"] + dc_d
                                    adxe = base["h1_adx_min"] + adx_d

                                    if (sl < 0.75 or tr < 1.0 or pb < 0.1 or
                                        bbw < 20 or bbw > 70 or dc < 15 or adxe < 5):
                                        continue
                                    key = (sl, tr, ts, pb, bbw, dc, adxe)
                                    if key in seen:
                                        continue
                                    seen.add(key)

                                    kv = base.copy()
                                    kv["atr_sl_multiplier"] = sl
                                    kv["atr_trail_multiplier"] = tr
                                    kv["trail_start_rr"] = ts
                                    kv["pb_atr_buffer"] = pb
                                    kv["bbw_squeeze_percentile"] = bbw
                                    kv["h1_donchian_period"] = dc
                                    kv["h1_adx_min"] = adxe
                                    # Remove non-param keys
                                    for rm in ["total_trades", "win_rate", "profit_factor",
                                                "avg_rr", "max_dd_pct", "total_return_pct",
                                                "n_symbols", "score"]:
                                        kv.pop(rm, None)
                                    variations.append(kv)

        print(f"    {len(variations)} variations...")

        for vi, kv in enumerate(variations):
            params = H1Params(**kv)
            bt, tested = run_bt(all_data, symbols, params)
            res = bt.get_results()

            if res is not None:
                stats, tdf = res
                if stats["total_trades"] >= 5 and stats["win_rate"] >= 50:
                    ns = tdf["symbol"].nunique()
                    refined.append({
                        "params": params, "stats": stats, "trades_df": tdf,
                        "n_syms": ns,
                        "sym_list": sorted(tdf["symbol"].unique().tolist()),
                        "score": calc_score(stats, ns),
                    })

            if (vi + 1) % 100 == 0:
                print(f"      [{vi+1}/{len(variations)}] {len(refined)} good")

    refined.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n  Phase 2: {time.time()-t0:.0f}s | {len(refined)} configs >50%WR")

    if refined:
        print(f"\n  TOP 10:")
        for i, r in enumerate(refined[:10]):
            s = r["stats"]
            print(f"  {i+1:>3} N={s['total_trades']:>4} S={r['n_syms']} "
                  f"WR={s['win_rate']:>5.1f}% PF={s['profit_factor']:>4.2f} "
                  f"RR={s['avg_rr']:>+4.2f} DD={s['max_drawdown_pct']:>5.1f}% "
                  f"Ret={s['total_return_pct']:>7.1f}%")

    return refined


# ============================================================
# PHASE 2B: Fallback relaxed search
# ============================================================
def phase2b(all_data, symbols, all_results):
    """If no >50% WR in Phase 1, use best available and refine."""
    print(f"\n{'='*70}")
    print("  PHASE 2B: REFINING BEST AVAILABLE CONFIGS")
    print(f"{'='*70}")

    # Sort by WR descending, then PF
    best_wr = sorted(all_results,
                     key=lambda x: (x.get("win_rate", 0), x.get("profit_factor", 0)),
                     reverse=True)

    if not best_wr:
        return []

    refined = []
    t0 = time.time()

    for rank, base in enumerate(best_wr[:3]):
        print(f"\n  Refining #{rank+1} (WR={base['win_rate']:.1f}%)...")

        seen = set()
        variations = []

        # Try different H1 filter combinations to boost WR
        for dc in [30, 40, 50, 60, 80]:
            for adxe in [15, 20, 25, 30]:
                for margin in [0.1, 0.2, 0.3, 0.5]:
                    for body in [0.3, 0.5, 0.6]:
                        for sl in [1.5, 2.0, 2.5]:
                            for tr in [2.0, 3.0, 4.0]:
                                key = (dc, adxe, margin, body, sl, tr)
                                if key in seen:
                                    continue
                                seen.add(key)

                                kv = {k: v for k, v in base.items()
                                      if k not in ["total_trades", "win_rate",
                                                    "profit_factor", "avg_rr",
                                                    "max_dd_pct", "total_return_pct",
                                                    "n_symbols", "score"]}
                                kv["h1_donchian_period"] = dc
                                kv["h1_adx_min"] = adxe
                                kv["h1_breakout_margin"] = margin
                                kv["h1_min_bar_body_pct"] = body
                                kv["atr_sl_multiplier"] = sl
                                kv["atr_trail_multiplier"] = tr
                                kv["h1_above_all_emas"] = True
                                kv["require_bullish_bar"] = True
                                variations.append(kv)

        # Sample if too many
        if len(variations) > 300:
            np.random.seed(rank)
            idx = np.random.choice(len(variations), 300, replace=False)
            variations = [variations[i] for i in idx]

        print(f"    Testing {len(variations)} aggressive filter combos...")

        for vi, kv in enumerate(variations):
            params = H1Params(**kv)
            bt, tested = run_bt(all_data, symbols, params)
            res = bt.get_results()

            if res is not None:
                stats, tdf = res
                if stats["total_trades"] >= 5 and stats["win_rate"] >= 48:
                    ns = tdf["symbol"].nunique()
                    sc = calc_score(stats, ns)
                    if stats["win_rate"] < 50:
                        sc = sc * (stats["win_rate"] / 50)  # Penalize slightly
                    refined.append({
                        "params": params, "stats": stats, "trades_df": tdf,
                        "n_syms": ns,
                        "sym_list": sorted(tdf["symbol"].unique().tolist()),
                        "score": sc,
                    })

            if (vi + 1) % 50 == 0:
                print(f"      [{vi+1}/{len(variations)}] {len(refined)} found")

    refined.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n  Phase 2B: {time.time()-t0:.0f}s | {len(refined)} configs")

    if refined:
        print(f"\n  TOP 10:")
        for i, r in enumerate(refined[:10]):
            s = r["stats"]
            p = r["params"]
            print(f"  {i+1:>3} DC={p.h1_donchian_period} ADX={p.h1_adx_min} "
                  f"Mrg={p.h1_breakout_margin} Body={p.h1_min_bar_body_pct} "
                  f"| N={s['total_trades']:>3} S={r['n_syms']} "
                  f"WR={s['win_rate']:>5.1f}% PF={s['profit_factor']:>4.2f} "
                  f"RR={s['avg_rr']:>+4.2f}")

    return refined


# ============================================================
# PHASE 3: Final validation
# ============================================================
def phase3(best):
    print(f"\n{'='*70}")
    print("  PHASE 3: FINAL VALIDATION")
    print(f"{'='*70}")

    stats = best["stats"]
    tdf = best["trades_df"]

    print_results(stats, "FINAL H1 OPTIMIZED")
    print(f"\n  Symbols: {best['sym_list']}")

    print(f"\n  PER-SYMBOL:")
    print(f"  {'Sym':<8} {'N':>5} {'WR%':>6} {'RR':>6} {'Best':>6} {'PF':>5} {'PnL':>10}")
    print(f"  {'-'*52}")
    for sym in best["sym_list"]:
        st = tdf[tdf["symbol"] == sym]
        wr = (st["pnl"] > 0).mean() * 100
        wins_sum = st[st["pnl"] > 0]["pnl"].sum()
        loss_sum = abs(st[st["pnl"] <= 0]["pnl"].sum())
        pf = wins_sum / loss_sum if loss_sum > 0 else float("inf")
        print(f"  {sym:<8} {len(st):>5} {wr:>5.1f}% {st['rr'].mean():>+5.2f} "
              f"{st['rr'].max():>+5.2f} {pf:>4.2f} ${st['pnl'].sum():>9,.0f}")

    print(f"\n  RR DISTRIBUTION:")
    for lo, hi in [(-99,-0.5),(-0.5,0),(0,0.5),(0.5,1),(1,2),(2,3),(3,5),(5,99)]:
        c = ((tdf["rr"] >= lo) & (tdf["rr"] < hi)).sum()
        pct = c / len(tdf) * 100
        print(f"    {lo:>+5.1f} to {hi:>+5.1f}: {c:>4} ({pct:>5.1f}%) {'#'*int(pct/2)}")

    print("\n  Monte Carlo (2000 sims)...")
    mc = monte_carlo_stress_test(tdf, n_simulations=2000)
    return mc


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=" * 70)
    print("  H1 OPTIMIZATION v2 - ENHANCED ENTRY FILTERS")
    print("  W1 context -> D1 validation -> H1 entry")
    print("  Extra: H1 ADX, long Donchian, breakout margin, body filter")
    print("=" * 70)

    T0 = time.time()
    data = preload_data(ALL_SYMBOLS)

    good, all_res = phase1(data, ALL_SYMBOLS)

    if good:
        refined = phase2(data, ALL_SYMBOLS, good)
    else:
        refined = phase2b(data, ALL_SYMBOLS, all_res)

    if refined:
        best = refined[0]
        mc = phase3(best)

        p = best["params"]
        out = {
            "strategy": "TrendPullbackEA v3.0 H1 Enhanced",
            "timeframes": {"context": "W1", "validation": "D1", "entry": "H1"},
            "parameters": p.to_dict(),
            "performance": best["stats"],
            "monte_carlo": mc,
            "symbols": best["sym_list"],
            "mql5_inputs": {
                "InpContextTF": "PERIOD_W1",
                "InpValidationTF": "PERIOD_D1",
                "InpEntryTF": "PERIOD_H1",
                "InpEMA_Fast": p.ema_fast,
                "InpEMA_Mid": p.ema_mid,
                "InpEMA_Slow": p.ema_slow,
                "InpADX_Period": p.adx_period,
                "InpADX_Context": p.adx_threshold_context,
                "InpADX_Validation": p.adx_threshold_validation,
                "InpATR_SL_Multi": p.atr_sl_multiplier,
                "InpATR_Trail_Multi": p.atr_trail_multiplier,
                "InpDonchian": p.h1_donchian_period,
                "InpBBW_Squeeze": p.bbw_squeeze_percentile,
                "InpVolume_Multi": p.volume_multiplier,
                "InpBE_Mode": "PULLBACK_BO",
                "InpTrail_Start_RR": p.trail_start_rr,
                "InpPB_Buffer": p.pb_atr_buffer,
                "InpBullishBar": p.require_bullish_bar,
                "InpH1_ADX_Min": p.h1_adx_min,
                "InpH1_Breakout_Margin": p.h1_breakout_margin,
                "InpH1_Above_All_EMAs": p.h1_above_all_emas,
                "InpH1_Min_Body_Pct": p.h1_min_bar_body_pct,
            },
        }

        with open(os.path.join(RESULTS_DIR, "h1_optimized.json"), "w") as f:
            json.dump(out, f, indent=2, default=str)
        best["trades_df"].to_csv(os.path.join(RESULTS_DIR, "h1_trades.csv"), index=False)

        el = time.time() - T0
        print(f"\n{'='*70}")
        print(f"  DONE in {el:.0f}s ({el/60:.1f}min)")
        print(f"{'='*70}")
        print(f"  EMA: {p.ema_fast}/{p.ema_mid}/{p.ema_slow}")
        print(f"  ADX: ctx={p.adx_threshold_context} val={p.adx_threshold_validation}")
        print(f"  H1 ADX: {p.h1_adx_min} Donchian: {p.h1_donchian_period}")
        print(f"  Breakout margin: {p.h1_breakout_margin} ATR")
        print(f"  All EMAs: {p.h1_above_all_emas} Body: {p.h1_min_bar_body_pct}")
        print(f"  ATR: SL={p.atr_sl_multiplier}x Trail={p.atr_trail_multiplier}x")
        print(f"  Trail start: {p.trail_start_rr} RR")
        print(f"  PB buffer: {p.pb_atr_buffer} BBW: {p.bbw_squeeze_percentile}%")
        print(f"  BE: {p.be_mode} Vol: {p.volume_multiplier}x")
        print(f"  WR={best['stats']['win_rate']}% PF={best['stats']['profit_factor']}")
        print(f"  RR={best['stats']['avg_rr']} Ret={best['stats']['total_return_pct']}%")
        print(f"  DD={best['stats']['max_drawdown_pct']}%")
        print(f"  Trades={best['stats']['total_trades']} Syms={len(best['sym_list'])}")
        print(f"  -> {RESULTS_DIR}/h1_optimized.json")
    else:
        print("\n  NO VALID CONFIGS. Strategy needs fundamental changes.")
