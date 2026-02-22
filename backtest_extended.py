#!/usr/bin/env python3
"""
Erweiterte Analyse: Testet auch Breakout-Modus mit breiteren Parametern
und fokussiert auf Konfigurationen mit MEHR Trades (robuster).
"""

import csv
import math
import itertools
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional

# Reuse data loading and indicator code from backtest_optimizer
from backtest_optimizer import (
    load_data, Candle, StrategyParams, BacktestResult, Trade,
    run_backtest
)


def score_robust(r):
    """Score that favors more trades for robustness"""
    n = len(r.trades)
    if n < 2 or r.profit_factor <= 0 or r.total_pnl <= 0:
        return -999
    dd_penalty = 1.0 / (1.0 + r.max_drawdown / 100.0) if r.max_drawdown > 0 else 1.0
    trade_bonus = math.sqrt(n)  # More trades = more robust
    return r.profit_factor * r.expectancy * trade_bonus * dd_penalty


def run_extended_analysis(candles):
    """Breitere Suche mit Fokus auf mehr Trades"""

    print("=" * 80)
    print("ERWEITERTE ANALYSE: Alle Modi + breitere Parameter")
    print("=" * 80)

    # Expanded parameter grid
    configs = []

    cci_periods = [7, 10, 14, 20, 28, 35]
    atr_periods = [3, 5, 7, 10, 14]
    atr_mults = [0.5, 0.8, 1.0, 1.5, 2.0]
    bb_lengths = [7, 10, 14, 20, 30]
    bb_mults = [1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
    modes = ["breakout", "mean_reversion", "combined"]
    sl_types = ["atr", "bb_mid"]
    sl_atr_mults = [1.0, 1.5, 2.0, 2.5, 3.0]
    tp_rrs = [1.5, 2.0, 2.5, 3.0]

    # Smart reduction: test indicator params with multiple risk configs in one pass
    total = 0
    results_all = []

    # Prioritize combinations that are likely to produce more trades:
    # - Lower BB mult = more signals
    # - Combined mode = more signals
    # - No body filter = more signals

    print("Teste ausgewaehlte Kombinationen...")

    count = 0
    for cci, atr_p, atr_m, bb_l, bb_m, mode, mt_on in itertools.product(
        cci_periods, [3, 5, 7, 10], [0.5, 1.0, 1.5],
        bb_lengths, bb_mults, modes, [True, False]):

        for sl_t, sl_m, tp_r, body_f in itertools.product(
            ["atr"], [1.5, 2.0, 2.5], [1.5, 2.0, 2.5, 3.0], [True, False]):

            count += 1
            if count % 5000 == 0:
                print(f"  ... {count} getestet, {len(results_all)} gueltig")

            p = StrategyParams(
                cci_period=cci, atr_period=atr_p, atr_mult=atr_m,
                bb_length=bb_l, bb_mult=bb_m,
                mode=mode, need_mt=mt_on,
                body_filter=body_f, body_min_ratio=0.3,
                use_squeeze=False,
                sl_type=sl_t, sl_atr_mult=sl_m,
                tp_type="rr", tp_rr=tp_r,
                max_trades_per_session=5,
            )
            r = run_backtest(candles, p)
            if len(r.trades) >= 3 and r.total_pnl > 0:
                results_all.append(r)

            # Stop early if we have enough
            if count > 200000:
                break
        if count > 200000:
            break

    print(f"\nGetestet: {count} Kombinationen")
    print(f"Gueltig (>= 3 Trades, PnL > 0): {len(results_all)}")

    # Sort by robust score
    results_all.sort(key=score_robust, reverse=True)

    # Also find configs with most trades that are still profitable
    results_by_trades = sorted([r for r in results_all if r.win_rate >= 50],
                                key=lambda r: len(r.trades), reverse=True)

    print(f"\n{'=' * 80}")
    print("TOP 20 nach ROBUSTEM Score (bevorzugt mehr Trades):")
    print("=" * 80)
    print(f"{'#':>3} | {'CCI':>3} {'ATP':>3} {'ATM':>4} {'BBL':>3} {'BBM':>4} | {'Modus':<16} {'MT':>2} {'BF':>2} | {'SLM':>4} {'TPR':>4} | {'Tr':>3} {'WR':>5} {'PnL':>9} {'PF':>5} {'MDD':>7} {'Exp':>7} | {'Score':>7}")
    print("-" * 120)
    for idx, r in enumerate(results_all[:20]):
        p = r.params
        print(f"{idx+1:>3} | {p.cci_period:>3} {p.atr_period:>3} {p.atr_mult:>4.1f} {p.bb_length:>3} {p.bb_mult:>4.1f} | "
              f"{p.mode:<16} {'Y' if p.need_mt else 'N':>2} {'Y' if p.body_filter else 'N':>2} | "
              f"{p.sl_atr_mult:>4.1f} {p.tp_rr:>4.1f} | "
              f"{len(r.trades):>3} {r.win_rate:>4.0f}% {r.total_pnl:>+8.0f} {r.profit_factor:>5.1f} {r.max_drawdown:>6.0f} {r.expectancy:>+6.0f} | {score_robust(r):>7.0f}")

    print(f"\n{'=' * 80}")
    print("TOP 10 nach MEISTEN TRADES (mindestens 50% Winrate, profitabel):")
    print("=" * 80)
    print(f"{'#':>3} | {'CCI':>3} {'ATP':>3} {'ATM':>4} {'BBL':>3} {'BBM':>4} | {'Modus':<16} {'MT':>2} {'BF':>2} | {'SLM':>4} {'TPR':>4} | {'Tr':>3} {'WR':>5} {'PnL':>9} {'PF':>5} {'MDD':>7} {'Exp':>7}")
    print("-" * 110)
    for idx, r in enumerate(results_by_trades[:10]):
        p = r.params
        print(f"{idx+1:>3} | {p.cci_period:>3} {p.atr_period:>3} {p.atr_mult:>4.1f} {p.bb_length:>3} {p.bb_mult:>4.1f} | "
              f"{p.mode:<16} {'Y' if p.need_mt else 'N':>2} {'Y' if p.body_filter else 'N':>2} | "
              f"{p.sl_atr_mult:>4.1f} {p.tp_rr:>4.1f} | "
              f"{len(r.trades):>3} {r.win_rate:>4.0f}% {r.total_pnl:>+8.0f} {r.profit_factor:>5.1f} {r.max_drawdown:>6.0f} {r.expectancy:>+6.0f}")

    # Find the "sweet spot" - good balance of trades and performance
    sweet_spot = sorted(results_all, key=lambda r: (
        r.profit_factor * len(r.trades) * (r.win_rate / 100) / (1 + r.max_drawdown / 50)
    ), reverse=True)

    print(f"\n{'=' * 80}")
    print("TOP 10 SWEET SPOT (Balance aus Trades, PF, Winrate, Drawdown):")
    print("=" * 80)
    print(f"{'#':>3} | {'CCI':>3} {'ATP':>3} {'ATM':>4} {'BBL':>3} {'BBM':>4} | {'Modus':<16} {'MT':>2} {'BF':>2} | {'SLM':>4} {'TPR':>4} | {'Tr':>3} {'WR':>5} {'PnL':>9} {'PF':>5} {'MDD':>7} {'Exp':>7}")
    print("-" * 110)
    for idx, r in enumerate(sweet_spot[:10]):
        p = r.params
        print(f"{idx+1:>3} | {p.cci_period:>3} {p.atr_period:>3} {p.atr_mult:>4.1f} {p.bb_length:>3} {p.bb_mult:>4.1f} | "
              f"{p.mode:<16} {'Y' if p.need_mt else 'N':>2} {'Y' if p.body_filter else 'N':>2} | "
              f"{p.sl_atr_mult:>4.1f} {p.tp_rr:>4.1f} | "
              f"{len(r.trades):>3} {r.win_rate:>4.0f}% {r.total_pnl:>+8.0f} {r.profit_factor:>5.1f} {r.max_drawdown:>6.0f} {r.expectancy:>+6.0f}")

    # Detailed best results
    if sweet_spot:
        print(f"\n{'=' * 80}")
        print("DETAILANALYSE: Sweet Spot #1")
        print("=" * 80)
        best = sweet_spot[0]
        bp = best.params
        print(f"""
Magic Trend:  CCI={bp.cci_period}, ATR_P={bp.atr_period}, ATR_M={bp.atr_mult}
Bollinger BB: Len={bp.bb_length}, Mult={bp.bb_mult}
Modus:        {bp.mode} | MT={'Ja' if bp.need_mt else 'Nein'} | Body={'Ja' if bp.body_filter else 'Nein'}
Risiko:       SL_ATR={bp.sl_atr_mult} | TP_RR={bp.tp_rr}

Trades: {len(best.trades)} | WR: {best.win_rate:.1f}% | PnL: {best.total_pnl:+.1f} | PF: {best.profit_factor:.2f} | MDD: {best.max_drawdown:.1f} | Exp: {best.expectancy:+.1f}
""")
        print("Trades:")
        for i, t in enumerate(best.trades):
            print(f"  {i+1}. {t.direction:5s} @ {t.entry_price:.1f} -> {t.exit_price:.1f} | PnL: {t.pnl:+.1f} | {t.exit_reason} | {t.entry_time.strftime('%m-%d %H:%M')} -> {t.exit_time.strftime('%m-%d %H:%M') if t.exit_time else '?'}")

    # Also show #1 from robust score
    if results_all:
        print(f"\n{'=' * 80}")
        print("DETAILANALYSE: Robust Score #1")
        print("=" * 80)
        best = results_all[0]
        bp = best.params
        print(f"""
Magic Trend:  CCI={bp.cci_period}, ATR_P={bp.atr_period}, ATR_M={bp.atr_mult}
Bollinger BB: Len={bp.bb_length}, Mult={bp.bb_mult}
Modus:        {bp.mode} | MT={'Ja' if bp.need_mt else 'Nein'} | Body={'Ja' if bp.body_filter else 'Nein'}
Risiko:       SL_ATR={bp.sl_atr_mult} | TP_RR={bp.tp_rr}

Trades: {len(best.trades)} | WR: {best.win_rate:.1f}% | PnL: {best.total_pnl:+.1f} | PF: {best.profit_factor:.2f} | MDD: {best.max_drawdown:.1f} | Exp: {best.expectancy:+.1f}
""")
        print("Trades:")
        for i, t in enumerate(best.trades):
            print(f"  {i+1}. {t.direction:5s} @ {t.entry_price:.1f} -> {t.exit_price:.1f} | PnL: {t.pnl:+.1f} | {t.exit_reason} | {t.entry_time.strftime('%m-%d %H:%M')} -> {t.exit_time.strftime('%m-%d %H:%M') if t.exit_time else '?'}")

    # Also show highest-trade config detail
    if results_by_trades:
        print(f"\n{'=' * 80}")
        print("DETAILANALYSE: Meiste Trades #1")
        print("=" * 80)
        best = results_by_trades[0]
        bp = best.params
        print(f"""
Magic Trend:  CCI={bp.cci_period}, ATR_P={bp.atr_period}, ATR_M={bp.atr_mult}
Bollinger BB: Len={bp.bb_length}, Mult={bp.bb_mult}
Modus:        {bp.mode} | MT={'Ja' if bp.need_mt else 'Nein'} | Body={'Ja' if bp.body_filter else 'Nein'}
Risiko:       SL_ATR={bp.sl_atr_mult} | TP_RR={bp.tp_rr}

Trades: {len(best.trades)} | WR: {best.win_rate:.1f}% | PnL: {best.total_pnl:+.1f} | PF: {best.profit_factor:.2f} | MDD: {best.max_drawdown:.1f} | Exp: {best.expectancy:+.1f}
""")
        print("Trades:")
        for i, t in enumerate(best.trades):
            print(f"  {i+1}. {t.direction:5s} @ {t.entry_price:.1f} -> {t.exit_price:.1f} | PnL: {t.pnl:+.1f} | {t.exit_reason} | {t.entry_time.strftime('%m-%d %H:%M')} -> {t.exit_time.strftime('%m-%d %H:%M') if t.exit_time else '?'}")

    return results_all, results_by_trades, sweet_spot


if __name__ == "__main__":
    print("Lade Daten...")
    candles = load_data("/home/user/Robin/CAPITALCOM_US100, 1.csv")
    print(f"Geladen: {len(candles)} Kerzen ({candles[0].dt_berlin} bis {candles[-1].dt_berlin})")

    all_results, by_trades, sweet = run_extended_analysis(candles)
