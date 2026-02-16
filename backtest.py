#!/usr/bin/env python3
"""
Backtest: EMA Fractal Expert Advisor
=====================================
Simuliert die PineScript-Strategie anhand der bereitgestellten XAUUSD CSV-Daten.
Verwendet H2 (120min), Daily und Weekly Daten mit EMA + Fractal Logik.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import sys

# ============================================================================
# KONFIGURATION
# ============================================================================

@dataclass
class Config:
    ema_fast: int = 10
    ema_mid: int = 20
    ema_slow: int = 50
    fractal_lookback: int = 2
    max_candles_fractal: int = 10
    use_distance_filter: bool = True
    max_distance_pct: float = 0.5      # Max Abstand Fractal zu EMA20 in %
    sl_mode: str = "full"               # "full" oder "half"
    use_breakeven: bool = True
    initial_capital: float = 10000.0
    risk_per_trade_pct: float = 2.0     # Risiko pro Trade in %
    commission_pct: float = 0.01        # Kommission in %


# ============================================================================
# DATEN LADEN
# ============================================================================

def load_data(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    return df


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def detect_fractals(df: pd.DataFrame, lookback: int = 2):
    """Williams Fractals erkennen."""
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    fractal_high = np.zeros(n, dtype=bool)
    fractal_low = np.zeros(n, dtype=bool)
    fractal_high_price = np.full(n, np.nan)
    fractal_low_price = np.full(n, np.nan)

    for i in range(lookback, n - lookback):
        # Fractal High
        is_fh = True
        for j in range(1, lookback + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_fh = False
                break
        if is_fh:
            fractal_high[i] = True
            fractal_high_price[i] = highs[i]

        # Fractal Low
        is_fl = True
        for j in range(1, lookback + 1):
            if lows[i] <= lows[i - j] or lows[i] <= lows[i + j]:
                is_fl = False
                break
        if is_fl:
            fractal_low[i] = True
            fractal_low_price[i] = lows[i]

    df['fractal_high'] = fractal_high
    df['fractal_low'] = fractal_low
    df['fractal_high_price'] = fractal_high_price
    df['fractal_low_price'] = fractal_low_price
    return df


# ============================================================================
# TRADE ERGEBNIS
# ============================================================================

@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    sl_price: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    position_size: float = 0.0
    breakeven_activated: bool = False
    max_favorable: float = 0.0
    max_adverse: float = 0.0


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

class Backtester:
    def __init__(self, config: Config):
        self.config = config
        self.trades: list[Trade] = []
        self.equity = config.initial_capital
        self.peak_equity = config.initial_capital

    def run(self, h2: pd.DataFrame, daily: pd.DataFrame, weekly: pd.DataFrame):
        cfg = self.config

        # EMAs berechnen
        h2['ema10'] = compute_ema(h2['close'], cfg.ema_fast)
        h2['ema20'] = compute_ema(h2['close'], cfg.ema_mid)

        daily['ema10'] = compute_ema(daily['close'], cfg.ema_fast)
        daily['ema20'] = compute_ema(daily['close'], cfg.ema_mid)

        weekly['ema10'] = compute_ema(weekly['close'], cfg.ema_fast)
        weekly['ema20'] = compute_ema(weekly['close'], cfg.ema_mid)
        weekly['ema50'] = compute_ema(weekly['close'], cfg.ema_slow)

        # Fractals auf H2
        h2 = detect_fractals(h2, cfg.fractal_lookback)

        # Indizierte Arrays für schnellen Zugriff
        h2_arr = h2.reset_index()

        # Weekly/Daily Bedingungen als Zeitreihe auf H2 mappen
        # Für jede H2-Kerze: finde die letzte abgeschlossene W/D Kerze
        weekly_cond = (weekly['ema10'] > weekly['ema20']) & (weekly['ema20'] > weekly['ema50'])
        daily_cond = daily['ema10'] > daily['ema20']

        n = len(h2_arr)

        # Zustandsmaschine
        waiting_for_fractal = False
        bars_since_setup = 0
        in_position = False
        current_trade: Optional[Trade] = None
        order_pending = False
        pending_entry_price = 0.0
        pending_sl_price = 0.0
        last_fractal_low_val = np.nan
        trailing_sl = np.nan
        breakeven_done = False

        for i in range(cfg.fractal_lookback + 1, n):
            row = h2_arr.iloc[i]
            ts = row['time']
            o, h_val, l_val, c = row['open'], row['high'], row['low'], row['close']
            ema10_val = row['ema10']
            ema20_val = row['ema20']

            if pd.isna(ema10_val) or pd.isna(ema20_val):
                continue

            # HTF Bedingungen prüfen
            w_mask = weekly.index <= ts
            d_mask = daily.index <= ts

            if not w_mask.any() or not d_mask.any():
                continue

            w_ok = weekly_cond.loc[w_mask].iloc[-1] if w_mask.any() else False
            d_ok = daily_cond.loc[d_mask].iloc[-1] if d_mask.any() else False

            # Fractal Low tracken
            if row['fractal_low']:
                last_fractal_low_val = row['fractal_low_price']

            # --- Position Management ---
            if in_position and current_trade is not None:
                # Max favorable / adverse excursion
                current_trade.max_favorable = max(current_trade.max_favorable, h_val - current_trade.entry_price)
                current_trade.max_adverse = max(current_trade.max_adverse, current_trade.entry_price - l_val)

                # SL getroffen?
                if l_val <= trailing_sl:
                    current_trade.exit_time = ts
                    current_trade.exit_price = trailing_sl
                    current_trade.exit_reason = "Trailing SL" if breakeven_done else "Initial SL"
                    pnl = (current_trade.exit_price - current_trade.entry_price) * current_trade.position_size
                    commission = current_trade.exit_price * current_trade.position_size * cfg.commission_pct / 100
                    current_trade.pnl = pnl - commission
                    current_trade.pnl_pct = current_trade.pnl / self.equity * 100
                    current_trade.breakeven_activated = breakeven_done
                    self.equity += current_trade.pnl
                    self.peak_equity = max(self.peak_equity, self.equity)
                    self.trades.append(current_trade)
                    in_position = False
                    current_trade = None
                    trailing_sl = np.nan
                    breakeven_done = False
                    continue

                # Trailing SL: Neues Fractal Low höher als aktueller SL → nachziehen
                if row['fractal_low'] and not pd.isna(row['fractal_low_price']):
                    new_sl = row['fractal_low_price']
                    if new_sl > trailing_sl:
                        trailing_sl = new_sl

                # Breakeven: Nach erstem Close über Entry
                if cfg.use_breakeven and not breakeven_done:
                    if c > current_trade.entry_price:
                        breakeven_done = True
                        if current_trade.entry_price > trailing_sl:
                            trailing_sl = current_trade.entry_price

                continue

            # --- Pending Order Check ---
            if order_pending:
                # HTF nicht mehr bullish → Order canceln
                if not w_ok or not d_ok:
                    order_pending = False
                    pending_entry_price = 0.0
                    pending_sl_price = 0.0
                    continue

                # Buystop: Preis durchbricht Entry Level
                if h_val >= pending_entry_price:
                    risk_amount = self.equity * cfg.risk_per_trade_pct / 100
                    risk_per_unit = pending_entry_price - pending_sl_price
                    if risk_per_unit <= 0:
                        order_pending = False
                        continue
                    pos_size = risk_amount / risk_per_unit
                    commission = pending_entry_price * pos_size * cfg.commission_pct / 100

                    current_trade = Trade(
                        entry_time=ts,
                        entry_price=pending_entry_price,
                        sl_price=pending_sl_price,
                        position_size=pos_size
                    )
                    trailing_sl = pending_sl_price
                    in_position = True
                    order_pending = False
                    breakeven_done = False
                    continue

            # --- Setup Signal erkennen ---
            if not waiting_for_fractal and not in_position and not order_pending:
                # H2: EMA10 < EMA20 (Pullback)
                h2_pullback = ema10_val < ema20_val

                # Cross above EMA20
                if i > 0:
                    prev_close = h2_arr.iloc[i - 1]['close']
                    prev_ema20 = h2_arr.iloc[i - 1]['ema20']
                    cross_above = c > ema20_val and prev_close <= prev_ema20
                else:
                    cross_above = False

                if w_ok and d_ok and h2_pullback and cross_above:
                    waiting_for_fractal = True
                    bars_since_setup = 0

            # --- Warten auf Fractal ---
            if waiting_for_fractal:
                bars_since_setup += 1

                if bars_since_setup > cfg.max_candles_fractal:
                    waiting_for_fractal = False
                    bars_since_setup = 0
                    continue

                if row['fractal_high']:
                    fh_price = row['fractal_high_price']

                    # Abstandsfilter
                    if cfg.use_distance_filter:
                        dist_pct = abs(fh_price - ema20_val) / ema20_val * 100
                        if dist_pct > cfg.max_distance_pct:
                            continue  # Weiter warten

                    # Buystop Order setzen
                    pending_entry_price = fh_price

                    if cfg.sl_mode == "full":
                        pending_sl_price = last_fractal_low_val if not pd.isna(last_fractal_low_val) else l_val
                    else:
                        fl = last_fractal_low_val if not pd.isna(last_fractal_low_val) else l_val
                        pending_sl_price = fh_price - (fh_price - fl) / 2

                    if pending_sl_price >= pending_entry_price:
                        # Ungültiger SL
                        waiting_for_fractal = False
                        continue

                    order_pending = True
                    waiting_for_fractal = False
                    bars_since_setup = 0

        # Offene Position am Ende schließen
        if in_position and current_trade is not None:
            last_row = h2_arr.iloc[-1]
            current_trade.exit_time = last_row['time']
            current_trade.exit_price = last_row['close']
            current_trade.exit_reason = "End of Data"
            pnl = (current_trade.exit_price - current_trade.entry_price) * current_trade.position_size
            commission = current_trade.exit_price * current_trade.position_size * cfg.commission_pct / 100
            current_trade.pnl = pnl - commission
            current_trade.pnl_pct = current_trade.pnl / self.equity * 100
            self.equity += current_trade.pnl
            self.trades.append(current_trade)

    def report(self):
        if not self.trades:
            print("Keine Trades gefunden.")
            return

        total = len(self.trades)
        winners = [t for t in self.trades if t.pnl > 0]
        losers = [t for t in self.trades if t.pnl <= 0]
        win_rate = len(winners) / total * 100

        total_pnl = sum(t.pnl for t in self.trades)
        avg_win = np.mean([t.pnl for t in winners]) if winners else 0
        avg_loss = np.mean([t.pnl for t in losers]) if losers else 0

        profit_factor = abs(sum(t.pnl for t in winners) / sum(t.pnl for t in losers)) if losers and sum(t.pnl for t in losers) != 0 else float('inf')

        # Max Drawdown
        equity_curve = [self.config.initial_capital]
        for t in self.trades:
            equity_curve.append(equity_curve[-1] + t.pnl)
        equity_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(equity_arr)
        dd = (peak - equity_arr) / peak * 100
        max_dd = np.max(dd)

        # Durchschnittliche Haltedauer
        durations = []
        for t in self.trades:
            if t.exit_time and t.entry_time:
                dur = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(dur)
        avg_duration = np.mean(durations) if durations else 0

        # Breakeven Stats
        be_trades = [t for t in self.trades if t.breakeven_activated]

        print("=" * 70)
        print("        BACKTEST ERGEBNIS: EMA Fractal EA - XAUUSD H2")
        print("=" * 70)
        print(f"  Zeitraum:            {self.trades[0].entry_time.date()} bis {self.trades[-1].exit_time.date() if self.trades[-1].exit_time else 'offen'}")
        print(f"  Startkapital:        ${self.config.initial_capital:,.2f}")
        print(f"  Endkapital:          ${self.equity:,.2f}")
        print(f"  Netto P/L:           ${total_pnl:,.2f} ({total_pnl / self.config.initial_capital * 100:.1f}%)")
        print("-" * 70)
        print(f"  Anzahl Trades:       {total}")
        print(f"  Gewinner:            {len(winners)} ({win_rate:.1f}%)")
        print(f"  Verlierer:           {len(losers)} ({100 - win_rate:.1f}%)")
        print(f"  Profit Factor:       {profit_factor:.2f}")
        print("-" * 70)
        print(f"  Ø Gewinn:            ${avg_win:,.2f}")
        print(f"  Ø Verlust:           ${avg_loss:,.2f}")
        print(f"  Ø Haltedauer:        {avg_duration:.1f} Stunden")
        print(f"  Max Drawdown:        {max_dd:.1f}%")
        print("-" * 70)
        print(f"  Breakeven aktiviert: {len(be_trades)} von {total} ({len(be_trades)/total*100:.1f}%)")
        print("=" * 70)

        # Einzelne Trades
        print("\n--- Trade Log (erste 30 Trades) ---")
        print(f"{'#':>3} | {'Entry Datum':>19} | {'Entry':>10} | {'Exit':>10} | {'SL':>10} | {'P/L':>10} | {'Grund':>15}")
        print("-" * 95)
        for i, t in enumerate(self.trades[:30], 1):
            exit_p = f"{t.exit_price:>10.2f}" if t.exit_price else "     offen"
            print(f"{i:>3} | {str(t.entry_time):>19} | {t.entry_price:>10.2f} | {exit_p} | {t.sl_price:>10.2f} | {t.pnl:>+10.2f} | {t.exit_reason:>15}")

        # Jahresweise Aufschlüsselung
        print("\n--- Jahresweise Performance ---")
        yearly = {}
        for t in self.trades:
            year = t.entry_time.year
            if year not in yearly:
                yearly[year] = {"trades": 0, "pnl": 0.0, "wins": 0}
            yearly[year]["trades"] += 1
            yearly[year]["pnl"] += t.pnl
            if t.pnl > 0:
                yearly[year]["wins"] += 1

        print(f"{'Jahr':>6} | {'Trades':>6} | {'Win%':>6} | {'P/L':>12}")
        print("-" * 40)
        for year in sorted(yearly.keys()):
            y = yearly[year]
            wr = y["wins"] / y["trades"] * 100 if y["trades"] > 0 else 0
            print(f"{year:>6} | {y['trades']:>6} | {wr:>5.1f}% | ${y['pnl']:>+11.2f}")

        return {
            "total_trades": total,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "max_drawdown": max_dd,
            "avg_duration_hrs": avg_duration,
            "equity": self.equity
        }


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Lade Daten...")
    h2 = load_data("PEPPERSTONE_XAUUSD, 120.csv")
    daily = load_data("PEPPERSTONE_XAUUSD, 1D.csv")
    weekly = load_data("PEPPERSTONE_XAUUSD, 1W.csv")

    print(f"  H2:     {len(h2)} Kerzen ({h2.index[0].date()} - {h2.index[-1].date()})")
    print(f"  Daily:  {len(daily)} Kerzen ({daily.index[0].date()} - {daily.index[-1].date()})")
    print(f"  Weekly: {len(weekly)} Kerzen ({weekly.index[0].date()} - {weekly.index[-1].date()})")

    # --- Standard Konfiguration ---
    print("\n" + "=" * 70)
    print("  TEST 1: Standard-Konfiguration")
    print("=" * 70)
    cfg1 = Config()
    bt1 = Backtester(cfg1)
    bt1.run(h2.copy(), daily.copy(), weekly.copy())
    r1 = bt1.report()

    # --- Variante 2: Halber SL ---
    print("\n" + "=" * 70)
    print("  TEST 2: Halber SL-Abstand")
    print("=" * 70)
    cfg2 = Config(sl_mode="half")
    bt2 = Backtester(cfg2)
    bt2.run(h2.copy(), daily.copy(), weekly.copy())
    r2 = bt2.report()

    # --- Variante 3: Größerer Abstandsfilter ---
    print("\n" + "=" * 70)
    print("  TEST 3: Abstandsfilter 1.0%")
    print("=" * 70)
    cfg3 = Config(max_distance_pct=1.0)
    bt3 = Backtester(cfg3)
    bt3.run(h2.copy(), daily.copy(), weekly.copy())
    r3 = bt3.report()

    # --- Variante 4: Ohne Abstandsfilter ---
    print("\n" + "=" * 70)
    print("  TEST 4: Ohne Abstandsfilter")
    print("=" * 70)
    cfg4 = Config(use_distance_filter=False)
    bt4 = Backtester(cfg4)
    bt4.run(h2.copy(), daily.copy(), weekly.copy())
    r4 = bt4.report()

    # --- Variante 5: Max 5 Kerzen statt 10 ---
    print("\n" + "=" * 70)
    print("  TEST 5: Max 5 Kerzen für Fractal")
    print("=" * 70)
    cfg5 = Config(max_candles_fractal=5)
    bt5 = Backtester(cfg5)
    bt5.run(h2.copy(), daily.copy(), weekly.copy())
    r5 = bt5.report()

    # --- Zusammenfassung ---
    print("\n" + "=" * 70)
    print("  VERGLEICH ALLER VARIANTEN")
    print("=" * 70)
    results = [
        ("Standard (SL full, dist 0.5%)", r1),
        ("Halber SL", r2),
        ("Abstandsfilter 1.0%", r3),
        ("Ohne Abstandsfilter", r4),
        ("Max 5 Kerzen", r5),
    ]
    print(f"{'Variante':<35} | {'Trades':>6} | {'Win%':>6} | {'PF':>6} | {'P/L':>12} | {'MaxDD':>6}")
    print("-" * 85)
    for name, r in results:
        if r:
            print(f"{name:<35} | {r['total_trades']:>6} | {r['win_rate']:>5.1f}% | {r['profit_factor']:>5.2f} | ${r['total_pnl']:>+11.2f} | {r['max_drawdown']:>5.1f}%")
        else:
            print(f"{name:<35} | {'N/A':>6} | {'N/A':>6} | {'N/A':>6} | {'N/A':>12} | {'N/A':>6}")


if __name__ == "__main__":
    main()
