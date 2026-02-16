#!/usr/bin/env python3
"""
Backtest: EMA Fractal Expert Advisor v3.0
==========================================
Neue Features:
1. 4 Trailing-SL-Methoden: Fractal, ATR, Chandelier, EMA-Trail
2. Neues Partial-TP: 50% bei Trailing-SL-Hit, Rest bei Fractal-Break
3. Konfigurierbares Risiko (1% Standard)
4. Range-Filter (Seitwärtsphasen erkennen und filtern)
5. Vergleich aller Kombinationen
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # EMA
    ema_fast: int = 10
    ema_mid: int = 20
    ema_slow: int = 50
    # Fractal
    fractal_lookback: int = 2
    max_candles_fractal: int = 10
    # Filter
    use_distance_filter: bool = True
    max_distance_pct: float = 0.5
    # SL
    sl_mode: str = "half"
    # Trailing Modus: "fractal", "atr", "chandelier", "ema_trail"
    trail_mode: str = "fractal"
    atr_period: int = 14
    atr_multiplier: float = 2.0          # ATR & Chandelier Multiplikator
    ema_trail_period: int = 10           # EMA-Trail Periode
    # Breakeven & Partial TP
    use_breakeven: bool = True
    # Partial-TP Modus: "breakeven" (v2), "trail_hit" (NEU: 50% bei Trail-SL-Hit)
    partial_mode: str = "breakeven"
    partial_tp_pct: float = 50.0
    # Fractal-Break Exit: Rest bei Fractal-Durchbruch nach Stagnation
    use_fractal_break_exit: bool = False
    fractal_stale_bars: int = 15          # Kerzen bis Fractal als "stale" gilt
    # Session
    use_session_filter: bool = True
    session_start: int = 8
    session_end: int = 20
    # Richtung
    trade_long: bool = True
    trade_short: bool = True
    # Range-Filter
    use_range_filter: bool = False
    range_lookback: int = 30             # Kerzen Lookback für Range-Erkennung
    range_atr_threshold: float = 0.6     # Range wenn ATR/Preis < threshold * avg
    range_min_bars: int = 10             # Min Kerzen in Range
    # Risiko
    initial_capital: float = 10000.0
    risk_per_trade_pct: float = 1.0      # NEU: 1% Standard
    commission_pct: float = 0.01


def load_data(filepath):
    df = pd.read_csv(filepath)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    return df


def compute_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def compute_atr(h, l, c, period=14):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
    return atr


def detect_fractals(df, lookback=2):
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    fh = np.zeros(n, dtype=bool)
    fl = np.zeros(n, dtype=bool)
    fhp = np.full(n, np.nan)
    flp = np.full(n, np.nan)
    for i in range(lookback, n - lookback):
        is_fh = True
        for j in range(1, lookback + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_fh = False
                break
        if is_fh:
            fh[i] = True
            fhp[i] = highs[i]
        is_fl = True
        for j in range(1, lookback + 1):
            if lows[i] <= lows[i - j] or lows[i] <= lows[i + j]:
                is_fl = False
                break
        if is_fl:
            fl[i] = True
            flp[i] = lows[i]
    df['fractal_high'] = fh
    df['fractal_low'] = fl
    df['fractal_high_price'] = fhp
    df['fractal_low_price'] = flp
    return df


def detect_range(atr_vals, close_vals, lookback, threshold, min_bars, i):
    """Range erkennen: ATR relativ zum Preis ist klein über mehrere Kerzen."""
    if i < lookback:
        return False
    recent_atr = atr_vals[i - lookback:i]
    recent_close = close_vals[i - lookback:i]
    if len(recent_atr) < lookback:
        return False
    avg_atr_pct = np.mean(recent_atr / recent_close) * 100
    long_atr_pct = np.mean(atr_vals[max(0, i - lookback * 3):i] / close_vals[max(0, i - lookback * 3):i]) * 100
    if long_atr_pct == 0:
        return False
    ratio = avg_atr_pct / long_atr_pct
    # Preisspanne in Lookback
    price_range = np.max(recent_close) - np.min(recent_close)
    avg_price = np.mean(recent_close)
    range_pct = price_range / avg_price * 100 if avg_price > 0 else 999
    # Range: niedrige Volatilität UND enge Preisspanne
    return ratio < threshold and range_pct < 2.0


@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    sl_price: float
    direction: int
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    position_size: float = 0.0
    breakeven_activated: bool = False
    partial_tp_done: bool = False
    partial_pnl: float = 0.0
    max_favorable: float = 0.0
    max_adverse: float = 0.0


class Backtester:
    def __init__(self, config):
        self.config = config
        self.trades = []
        self.equity = config.initial_capital
        self.peak_equity = config.initial_capital

    def _close_trade(self, trade, ts, exit_price, reason, remaining_factor):
        cfg = self.config
        td = trade.direction
        if td == 1:
            pnl = (exit_price - trade.entry_price) * trade.position_size * remaining_factor
        else:
            pnl = (trade.entry_price - exit_price) * trade.position_size * remaining_factor
        comm = abs(exit_price * trade.position_size * remaining_factor * cfg.commission_pct / 100)
        trade.exit_time = ts
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.pnl = trade.partial_pnl + pnl - comm
        trade.pnl_pct = trade.pnl / max(self.equity, 1) * 100
        self.equity += trade.pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        self.trades.append(trade)

    def run(self, h2, daily, weekly):
        cfg = self.config

        h2['ema10'] = compute_ema(h2['close'], cfg.ema_fast)
        h2['ema20'] = compute_ema(h2['close'], cfg.ema_mid)
        h2['ema_trail'] = compute_ema(h2['close'], cfg.ema_trail_period)

        daily['ema10'] = compute_ema(daily['close'], cfg.ema_fast)
        daily['ema20'] = compute_ema(daily['close'], cfg.ema_mid)

        weekly['ema10'] = compute_ema(weekly['close'], cfg.ema_fast)
        weekly['ema20'] = compute_ema(weekly['close'], cfg.ema_mid)
        weekly['ema50'] = compute_ema(weekly['close'], cfg.ema_slow)

        h2 = detect_fractals(h2, cfg.fractal_lookback)
        h2_arr = h2.reset_index()

        # ATR vorberechnen
        atr_vals = compute_atr(h2_arr['high'].values, h2_arr['low'].values,
                               h2_arr['close'].values, cfg.atr_period)
        h2_arr['atr'] = atr_vals

        weekly_bull = (weekly['ema10'] > weekly['ema20']) & (weekly['ema20'] > weekly['ema50'])
        weekly_bear = (weekly['ema10'] < weekly['ema20']) & (weekly['ema20'] < weekly['ema50'])
        daily_bull = daily['ema10'] > daily['ema20']
        daily_bear = daily['ema10'] < daily['ema20']

        n = len(h2_arr)
        close_vals = h2_arr['close'].values
        ema_trail_vals = h2_arr['ema_trail'].values

        # Zustandsmaschine
        waiting = False
        bars_setup = 0
        setup_dir = 0
        in_pos = False
        trade = None
        order_pend = False
        order_dir = 0
        pend_entry = 0.0
        pend_sl = 0.0
        last_fl = np.nan
        last_fh = np.nan
        trail_sl = np.nan
        be_done = False
        partial_done = False
        remain = 1.0
        # Fractal-Break Tracking
        last_trail_fractal_price = np.nan
        bars_since_fractal = 0
        first_trail_hit = False  # Für partial_mode="trail_hit"

        for i in range(max(cfg.fractal_lookback + 1, cfg.atr_period + 1), n):
            row = h2_arr.iloc[i]
            ts = row['time']
            o, hi, lo, c = row['open'], row['high'], row['low'], row['close']
            e10 = row['ema10']
            e20 = row['ema20']
            atr = row['atr']
            ema_t = row['ema_trail']

            if pd.isna(e10) or pd.isna(e20) or pd.isna(atr):
                continue

            # Session
            in_sess = True
            if cfg.use_session_filter:
                h_utc = ts.hour
                if h_utc < cfg.session_start or h_utc >= cfg.session_end:
                    in_sess = False

            # HTF
            wm = weekly.index <= ts
            dm = daily.index <= ts
            if not wm.any() or not dm.any():
                continue
            htf_bull = weekly_bull.loc[wm].iloc[-1] and daily_bull.loc[dm].iloc[-1]
            htf_bear = weekly_bear.loc[wm].iloc[-1] and daily_bear.loc[dm].iloc[-1]

            # Range-Filter
            in_range = False
            if cfg.use_range_filter:
                in_range = detect_range(atr_vals, close_vals, cfg.range_lookback,
                                       cfg.range_atr_threshold, cfg.range_min_bars, i)

            # Fractal Tracking
            if row['fractal_low']:
                last_fl = row['fractal_low_price']
            if row['fractal_high']:
                last_fh = row['fractal_high_price']

            # ==========================================================
            # POSITION MANAGEMENT
            # ==========================================================
            if in_pos and trade is not None:
                td = trade.direction

                if td == 1:
                    trade.max_favorable = max(trade.max_favorable, hi - trade.entry_price)
                    trade.max_adverse = max(trade.max_adverse, trade.entry_price - lo)
                else:
                    trade.max_favorable = max(trade.max_favorable, trade.entry_price - lo)
                    trade.max_adverse = max(trade.max_adverse, hi - trade.entry_price)

                # --- SL Check ---
                sl_hit = (td == 1 and lo <= trail_sl) or (td == -1 and hi >= trail_sl)

                if sl_hit:
                    # Partial-TP bei Trail-Hit (neues System)
                    if cfg.partial_mode == "trail_hit" and not partial_done and be_done:
                        # 50% schließen beim Trail-Hit, Rest weiter
                        close_frac = cfg.partial_tp_pct / 100.0
                        if td == 1:
                            pp = (trail_sl - trade.entry_price) * trade.position_size * close_frac
                        else:
                            pp = (trade.entry_price - trail_sl) * trade.position_size * close_frac
                        pc = abs(trail_sl * trade.position_size * close_frac * cfg.commission_pct / 100)
                        trade.partial_pnl += pp - pc
                        remain = 1.0 - close_frac
                        partial_done = True
                        trade.partial_tp_done = True
                        self.equity += pp - pc
                        # SL zurücksetzen auf Entry (Breakeven für Rest)
                        trail_sl = trade.entry_price
                        first_trail_hit = True
                    else:
                        reason = "Trailing SL" if be_done else "Initial SL"
                        trade.breakeven_activated = be_done
                        trade.partial_tp_done = partial_done
                        self._close_trade(trade, ts, trail_sl, reason, remain)
                        in_pos = False; trade = None; trail_sl = np.nan
                        be_done = False; partial_done = False; remain = 1.0
                        first_trail_hit = False
                        continue

                # --- Trailing SL Update ---
                if cfg.trail_mode == "fractal":
                    if td == 1 and row['fractal_low'] and not pd.isna(row['fractal_low_price']):
                        if row['fractal_low_price'] > trail_sl:
                            trail_sl = row['fractal_low_price']
                            last_trail_fractal_price = trail_sl
                            bars_since_fractal = 0
                    elif td == -1 and row['fractal_high'] and not pd.isna(row['fractal_high_price']):
                        if row['fractal_high_price'] < trail_sl:
                            trail_sl = row['fractal_high_price']
                            last_trail_fractal_price = trail_sl
                            bars_since_fractal = 0

                elif cfg.trail_mode == "atr":
                    if td == 1:
                        new_sl = c - atr * cfg.atr_multiplier
                        if new_sl > trail_sl:
                            trail_sl = new_sl
                    else:
                        new_sl = c + atr * cfg.atr_multiplier
                        if new_sl < trail_sl:
                            trail_sl = new_sl

                elif cfg.trail_mode == "chandelier":
                    # Chandelier: Höchstes High/Tiefstes Low der letzten N Kerzen - ATR*mult
                    lb = min(cfg.atr_period, i)
                    if td == 1:
                        highest = np.max(h2_arr['high'].values[i - lb:i + 1])
                        new_sl = highest - atr * cfg.atr_multiplier
                        if new_sl > trail_sl:
                            trail_sl = new_sl
                    else:
                        lowest = np.min(h2_arr['low'].values[i - lb:i + 1])
                        new_sl = lowest + atr * cfg.atr_multiplier
                        if new_sl < trail_sl:
                            trail_sl = new_sl

                elif cfg.trail_mode == "ema_trail":
                    if not pd.isna(ema_t):
                        if td == 1 and ema_t > trail_sl:
                            trail_sl = ema_t
                        elif td == -1 and ema_t < trail_sl:
                            trail_sl = ema_t

                # Fractal-Break Exit für Rest-Position
                bars_since_fractal += 1
                if cfg.use_fractal_break_exit and partial_done and not np.isnan(last_trail_fractal_price):
                    if bars_since_fractal >= cfg.fractal_stale_bars:
                        fractal_broken = False
                        if td == 1 and lo < last_trail_fractal_price:
                            fractal_broken = True
                        elif td == -1 and hi > last_trail_fractal_price:
                            fractal_broken = True
                        if fractal_broken:
                            trade.breakeven_activated = be_done
                            trade.partial_tp_done = True
                            self._close_trade(trade, ts, last_trail_fractal_price, "Fractal Break Exit", remain)
                            in_pos = False; trade = None; trail_sl = np.nan
                            be_done = False; partial_done = False; remain = 1.0
                            first_trail_hit = False
                            continue

                # Breakeven (für partial_mode="breakeven")
                if cfg.use_breakeven and not be_done:
                    be_trig = (td == 1 and c > trade.entry_price) or (td == -1 and c < trade.entry_price)
                    if be_trig:
                        be_done = True
                        if td == 1 and trade.entry_price > trail_sl:
                            trail_sl = trade.entry_price
                        elif td == -1 and trade.entry_price < trail_sl:
                            trail_sl = trade.entry_price
                        # v2 Partial bei Breakeven
                        if cfg.partial_mode == "breakeven" and not partial_done:
                            cf = cfg.partial_tp_pct / 100.0
                            if td == 1:
                                pp = (c - trade.entry_price) * trade.position_size * cf
                            else:
                                pp = (trade.entry_price - c) * trade.position_size * cf
                            pc = abs(c * trade.position_size * cf * cfg.commission_pct / 100)
                            trade.partial_pnl += pp - pc
                            remain = 1.0 - cf
                            partial_done = True
                            trade.partial_tp_done = True
                            self.equity += pp - pc

                continue

            # ==========================================================
            # PENDING ORDER
            # ==========================================================
            if order_pend:
                cancel = (order_dir == 1 and not htf_bull) or (order_dir == -1 and not htf_bear)
                if cancel:
                    order_pend = False; order_dir = 0; continue

                filled = (order_dir == 1 and hi >= pend_entry) or (order_dir == -1 and lo <= pend_entry)
                if filled:
                    risk = self.equity * cfg.risk_per_trade_pct / 100
                    rpu = abs(pend_entry - pend_sl)
                    if rpu <= 0:
                        order_pend = False; order_dir = 0; continue
                    ps = risk / rpu
                    trade = Trade(entry_time=ts, entry_price=pend_entry, sl_price=pend_sl,
                                 direction=order_dir, position_size=ps)
                    trail_sl = pend_sl
                    in_pos = True; order_pend = False
                    be_done = False; partial_done = False; remain = 1.0
                    first_trail_hit = False
                    last_trail_fractal_price = np.nan; bars_since_fractal = 0
                    continue

            # ==========================================================
            # SETUP SIGNAL
            # ==========================================================
            if not waiting and not in_pos and not order_pend and in_sess:
                if in_range:
                    continue  # Range-Filter: kein Setup in Seitwärtsphase

                if i > 0:
                    pc = h2_arr.iloc[i - 1]['close']
                    pe = h2_arr.iloc[i - 1]['ema20']

                    if cfg.trade_long and htf_bull and e10 < e20:
                        if c > e20 and pc <= pe:
                            waiting = True; bars_setup = 0; setup_dir = 1

                    if not waiting and cfg.trade_short and htf_bear and e10 > e20:
                        if c < e20 and pc >= pe:
                            waiting = True; bars_setup = 0; setup_dir = -1

            # ==========================================================
            # WARTEN AUF FRACTAL
            # ==========================================================
            if waiting:
                bars_setup += 1
                if bars_setup > cfg.max_candles_fractal:
                    waiting = False; bars_setup = 0; setup_dir = 0; continue

                if setup_dir == 1 and row['fractal_high']:
                    fp = row['fractal_high_price']
                    if cfg.use_distance_filter:
                        dp = abs(fp - e20) / e20 * 100
                        if dp > cfg.max_distance_pct:
                            continue
                    pend_entry = fp
                    if cfg.sl_mode == "full":
                        pend_sl = last_fl if not np.isnan(last_fl) else lo
                    else:
                        fl_v = last_fl if not np.isnan(last_fl) else lo
                        pend_sl = fp - (fp - fl_v) / 2
                    if pend_sl >= pend_entry:
                        waiting = False; setup_dir = 0; continue
                    order_pend = True; order_dir = 1; waiting = False; bars_setup = 0

                elif setup_dir == -1 and row['fractal_low']:
                    fp = row['fractal_low_price']
                    if cfg.use_distance_filter:
                        dp = abs(fp - e20) / e20 * 100
                        if dp > cfg.max_distance_pct:
                            continue
                    pend_entry = fp
                    if cfg.sl_mode == "full":
                        pend_sl = last_fh if not np.isnan(last_fh) else hi
                    else:
                        fh_v = last_fh if not np.isnan(last_fh) else hi
                        pend_sl = fp + (fh_v - fp) / 2
                    if pend_sl <= pend_entry:
                        waiting = False; setup_dir = 0; continue
                    order_pend = True; order_dir = -1; waiting = False; bars_setup = 0

        if in_pos and trade is not None:
            lr = h2_arr.iloc[-1]
            self._close_trade(trade, lr['time'], lr['close'], "End of Data", remain)

    def report(self, label=""):
        if not self.trades:
            print("  Keine Trades.")
            return None
        total = len(self.trades)
        longs = [t for t in self.trades if t.direction == 1]
        shorts = [t for t in self.trades if t.direction == -1]
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        wr = len(wins) / total * 100
        tp = sum(t.pnl for t in self.trades)
        gp = sum(t.pnl for t in wins)
        gl = sum(t.pnl for t in losses)
        pf = abs(gp / gl) if gl != 0 else float('inf')
        aw = np.mean([t.pnl for t in wins]) if wins else 0
        al = np.mean([t.pnl for t in losses]) if losses else 0

        eq = [self.config.initial_capital]
        for t in self.trades:
            eq.append(eq[-1] + t.pnl)
        ea = np.array(eq)
        pk = np.maximum.accumulate(ea)
        dd = (pk - ea) / pk * 100
        mdd = np.max(dd)

        durs = [(t.exit_time - t.entry_time).total_seconds() / 3600
                for t in self.trades if t.exit_time and t.entry_time]
        ad = np.mean(durs) if durs else 0

        lp = sum(t.pnl for t in longs)
        sp = sum(t.pnl for t in shorts)

        print("=" * 70)
        print(f"  {label}")
        print("=" * 70)
        print(f"  Kapital:  ${self.config.initial_capital:,.0f} -> ${self.equity:,.0f}  |  P/L: ${tp:,.0f} ({tp/self.config.initial_capital*100:.0f}%)")
        print(f"  Trades:   {total} (L:{len(longs)} S:{len(shorts)})  |  Win: {wr:.1f}%  |  PF: {pf:.2f}  |  MaxDD: {mdd:.1f}%")
        print(f"  Ø Win/Loss: ${aw:,.0f} / ${al:,.0f}  |  Ø Dauer: {ad:.1f}h  |  Risk: {self.config.risk_per_trade_pct}%")
        print(f"  Long: ${lp:,.0f}  |  Short: ${sp:,.0f}")
        print("-" * 70)

        return {"total_trades": total, "long_trades": len(longs), "short_trades": len(shorts),
                "win_rate": wr, "profit_factor": pf, "total_pnl": tp, "long_pnl": lp,
                "short_pnl": sp, "max_drawdown": mdd, "avg_duration_hrs": ad,
                "equity": self.equity, "avg_win": aw, "avg_loss": al}


def main():
    print("Lade Daten...")
    h2 = load_data("PEPPERSTONE_XAUUSD, 120.csv")
    daily = load_data("PEPPERSTONE_XAUUSD, 1D.csv")
    weekly = load_data("PEPPERSTONE_XAUUSD, 1W.csv")
    print(f"  H2: {len(h2)} | Daily: {len(daily)} | Weekly: {len(weekly)}")
    print(f"  Zeitraum: {h2.index[0].date()} - {h2.index[-1].date()}")

    tests = []

    # ============================================================
    # GRUPPE A: TRAILING-METHODEN VERGLEICH (1% Risiko)
    # ============================================================
    print("\n" + "=" * 70)
    print("  GRUPPE A: TRAILING-METHODEN VERGLEICH (1% Risiko)")
    print("=" * 70)

    for tm, label in [
        ("fractal", "A1: Fractal Trail (bisherig)"),
        ("atr", "A2: ATR Trail (2.0x)"),
        ("chandelier", "A3: Chandelier Exit (2.0x)"),
        ("ema_trail", "A4: EMA-10 Trail"),
    ]:
        cfg = Config(trail_mode=tm, partial_mode="breakeven")
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # ATR Varianten
    for mult in [1.5, 2.5, 3.0]:
        label = f"A5: ATR Trail ({mult}x)"
        cfg = Config(trail_mode="atr", atr_multiplier=mult, partial_mode="breakeven")
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # Chandelier Varianten
    for mult in [1.5, 2.5, 3.0]:
        label = f"A6: Chandelier ({mult}x)"
        cfg = Config(trail_mode="chandelier", atr_multiplier=mult, partial_mode="breakeven")
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # EMA Trail Varianten
    for p in [5, 8, 15, 20]:
        label = f"A7: EMA-{p} Trail"
        cfg = Config(trail_mode="ema_trail", ema_trail_period=p, partial_mode="breakeven")
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # ============================================================
    # GRUPPE B: PARTIAL-TP MODUS VERGLEICH
    # ============================================================
    print("\n" + "=" * 70)
    print("  GRUPPE B: PARTIAL-TP MODI")
    print("=" * 70)

    for pm, fbe, label in [
        ("breakeven", False, "B1: Partial bei Breakeven (v2)"),
        ("trail_hit", False, "B2: Partial bei Trail-Hit (NEU)"),
        ("trail_hit", True, "B3: Trail-Hit + Fractal-Break Exit"),
    ]:
        cfg = Config(partial_mode=pm, use_fractal_break_exit=fbe)
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # ============================================================
    # GRUPPE C: RISIKO 1% vs 2% vs 0.5%
    # ============================================================
    print("\n" + "=" * 70)
    print("  GRUPPE C: RISIKO PRO TRADE")
    print("=" * 70)

    for rsk, label in [
        (0.5, "C1: 0.5% Risiko"),
        (1.0, "C2: 1.0% Risiko (Standard)"),
        (1.5, "C3: 1.5% Risiko"),
        (2.0, "C4: 2.0% Risiko (v2)"),
    ]:
        cfg = Config(risk_per_trade_pct=rsk)
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # ============================================================
    # GRUPPE D: RANGE-FILTER
    # ============================================================
    print("\n" + "=" * 70)
    print("  GRUPPE D: RANGE-FILTER")
    print("=" * 70)

    for use_rf, lookback, thresh, label in [
        (False, 30, 0.6, "D1: Ohne Range-Filter"),
        (True, 20, 0.6, "D2: Range 20 Kerzen, 0.6"),
        (True, 30, 0.6, "D3: Range 30 Kerzen, 0.6"),
        (True, 30, 0.5, "D4: Range 30 Kerzen, 0.5 (streng)"),
        (True, 40, 0.7, "D5: Range 40 Kerzen, 0.7 (locker)"),
    ]:
        cfg = Config(use_range_filter=use_rf, range_lookback=lookback, range_atr_threshold=thresh)
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # ============================================================
    # GRUPPE E: BESTE KOMBINATION vs V2
    # ============================================================
    print("\n" + "=" * 70)
    print("  GRUPPE E: BESTE KOMBINATIONEN")
    print("=" * 70)

    # v2 Referenz (2% Risiko, Fractal Trail, Partial@BE)
    cfg_v2 = Config(risk_per_trade_pct=2.0, trail_mode="fractal",
                    partial_mode="breakeven", use_range_filter=False)
    bt_v2 = Backtester(cfg_v2)
    bt_v2.run(h2.copy(), daily.copy(), weekly.copy())
    r_v2 = bt_v2.report("E0: v2 Referenz (2% Risk, Fractal, BE-Partial)")
    tests.append(("E0: v2 Referenz", r_v2))

    # Beste Trailing + 1% Risiko
    for tm, mult, pm, fbe, rf, rsk, label in [
        ("chandelier", 2.0, "breakeven", False, False, 1.0,
         "E1: Chandelier 2x + 1% + BE-Partial"),
        ("chandelier", 2.0, "trail_hit", True, False, 1.0,
         "E2: Chandelier 2x + 1% + Trail-Hit-Partial + FB-Exit"),
        ("chandelier", 2.0, "breakeven", False, True, 1.0,
         "E3: Chandelier 2x + 1% + Range-Filter"),
        ("atr", 2.0, "breakeven", False, False, 1.0,
         "E4: ATR 2x + 1% + BE-Partial"),
        ("atr", 2.0, "trail_hit", True, False, 1.0,
         "E5: ATR 2x + 1% + Trail-Hit + FB-Exit"),
        ("fractal", 2.0, "trail_hit", True, False, 1.0,
         "E6: Fractal + 1% + Trail-Hit + FB-Exit"),
        ("fractal", 2.0, "breakeven", False, True, 1.0,
         "E7: Fractal + 1% + Range-Filter"),
        ("chandelier", 2.5, "breakeven", False, True, 1.0,
         "E8: Chandelier 2.5x + 1% + Range-Filter"),
        ("chandelier", 2.0, "trail_hit", True, True, 1.0,
         "E9: ALLES KOMBINIERT (Chandelier+TrailHit+Range+1%)"),
    ]:
        cfg = Config(trail_mode=tm, atr_multiplier=mult, partial_mode=pm,
                     use_fractal_break_exit=fbe, use_range_filter=rf,
                     risk_per_trade_pct=rsk, range_lookback=30, range_atr_threshold=0.6)
        bt = Backtester(cfg)
        bt.run(h2.copy(), daily.copy(), weekly.copy())
        r = bt.report(label)
        tests.append((label, r))

    # ============================================================
    # GESAMTVERGLEICH
    # ============================================================
    print("\n" + "=" * 100)
    print("  GESAMTVERGLEICH ALLER VARIANTEN")
    print("=" * 100)
    print(f"{'Variante':<52} | {'Trd':>4} | {'Win%':>5} | {'PF':>5} | {'P/L':>10} | {'DD':>5} | {'Ø Win':>7} | {'Ø Loss':>7}")
    print("-" * 100)
    for name, r in tests:
        if r:
            print(f"{name:<52} | {r['total_trades']:>4} | {r['win_rate']:>4.1f}% | {r['profit_factor']:>4.2f} | ${r['total_pnl']:>+8.0f} | {r['max_drawdown']:>4.1f}% | ${r['avg_win']:>6.0f} | ${r['avg_loss']:>6.0f}")


if __name__ == "__main__":
    main()
