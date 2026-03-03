#!/usr/bin/env python3
"""XAUUSD (Gold) specific backtest and optimization."""

import sys, os, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtester import (
    StrategyParams, Backtester, run_multi_symbol_backtest,
    print_results, load_symbol_data, add_indicators, resample_to_weekly
)
from optimizer import monte_carlo_stress_test

# First download XAUUSD data
def download_gold():
    """Download XAUUSD data via yfinance (GC=F futures as proxy)."""
    try:
        import yfinance as yf
    except ImportError:
        os.system(f"{sys.executable} -m pip install yfinance")
        import yfinance as yf
    import pandas as pd

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)

    # Gold ticker on Yahoo: GC=F (futures) or use XAUUSD=X
    tickers = [("GC=F", "Gold Futures"), ("XAUUSD=X", "XAUUSD Spot")]

    for ticker, name in tickers:
        print(f"  Trying {name} ({ticker})...")
        try:
            stock = yf.Ticker(ticker)

            # Daily
            df_d = stock.history(period="10y", interval="1d")
            if df_d.empty:
                print(f"    No daily data for {ticker}")
                continue

            print(f"    Daily: {len(df_d)} bars")

            # Save daily
            out = pd.DataFrame()
            out["time"] = df_d.index.astype(int) // 10**9
            out["open"] = df_d["Open"].values
            out["high"] = df_d["High"].values
            out["low"] = df_d["Low"].values
            out["close"] = df_d["Close"].values
            out["volume"] = df_d["Volume"].values
            out.to_csv(os.path.join(data_dir, "XAUUSD_1D.csv"), index=False)

            # Weekly
            df_w = stock.history(period="10y", interval="1wk")
            if not df_w.empty:
                out_w = pd.DataFrame()
                out_w["time"] = df_w.index.astype(int) // 10**9
                out_w["open"] = df_w["Open"].values
                out_w["high"] = df_w["High"].values
                out_w["low"] = df_w["Low"].values
                out_w["close"] = df_w["Close"].values
                out_w["volume"] = df_w["Volume"].values
                out_w.to_csv(os.path.join(data_dir, "XAUUSD_1W.csv"), index=False)
                print(f"    Weekly: {len(df_w)} bars")

            # Hourly -> H4
            df_h = stock.history(period="730d", interval="1h")
            if not df_h.empty:
                out_h = pd.DataFrame()
                out_h["time"] = df_h.index.astype(int) // 10**9
                out_h["open"] = df_h["Open"].values
                out_h["high"] = df_h["High"].values
                out_h["low"] = df_h["Low"].values
                out_h["close"] = df_h["Close"].values
                out_h["volume"] = df_h["Volume"].values
                out_h.to_csv(os.path.join(data_dir, "XAUUSD_1H.csv"), index=False)
                print(f"    Hourly: {len(df_h)} bars")

                # Resample to H4
                df_h4 = df_h.resample("4h").agg({
                    "Open": "first", "High": "max", "Low": "min",
                    "Close": "last", "Volume": "sum"
                }).dropna()
                out_h4 = pd.DataFrame()
                out_h4["time"] = df_h4.index.astype(int) // 10**9
                out_h4["open"] = df_h4["Open"].values
                out_h4["high"] = df_h4["High"].values
                out_h4["low"] = df_h4["Low"].values
                out_h4["close"] = df_h4["Close"].values
                out_h4["volume"] = df_h4["Volume"].values
                out_h4.to_csv(os.path.join(data_dir, "XAUUSD_H4.csv"), index=False)
                print(f"    H4: {len(df_h4)} bars")

            return True
        except Exception as e:
            print(f"    Error: {e}")
            continue

    return False


# Parameter configs to test on Gold
gold_configs = {
    # Use stock-optimized params as baseline
    "Stock_Optimal": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.05, be_mode='pullback',
        trail_start_rr=1.5, pb_atr_buffer=1.0,
    ),
    # Gold tends to trend strongly - wider trailing
    "Gold_Wide_Trail": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=2.0, atr_trail_multiplier=3.0,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.0, be_mode='pullback',
        trail_start_rr=2.0, pb_atr_buffer=1.0,
    ),
    # Gold with faster EMAs (trends change faster)
    "Gold_Fast_EMA": StrategyParams(
        ema_fast=13, ema_mid=34, ema_slow=89,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.5,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.0, be_mode='pullback',
        trail_start_rr=1.5, pb_atr_buffer=1.0,
    ),
    # Gold relaxed - more entries
    "Gold_Relaxed": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=12.0, adx_threshold_validation=8.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        bbw_squeeze_percentile=55.0, donchian_period=12,
        volume_multiplier=1.0, be_mode='pullback',
        trail_start_rr=1.5, pb_atr_buffer=1.2,
        require_bullish_bar=False,
    ),
    # Gold RR-based BE instead of pullback
    "Gold_RR_BE": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=15.0, adx_threshold_validation=10.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.5,
        bbw_squeeze_percentile=45.0, donchian_period=15,
        volume_multiplier=1.0, be_mode='rr',
        trail_start_rr=2.0, pb_atr_buffer=1.0,
        be_rr_ratio=1.0,
    ),
    # Gold aggressive: fast EMA + relaxed filters + tight trail
    "Gold_Aggressive": StrategyParams(
        ema_fast=13, ema_mid=34, ema_slow=89,
        adx_threshold_context=10.0, adx_threshold_validation=8.0,
        atr_sl_multiplier=1.5, atr_trail_multiplier=2.0,
        bbw_squeeze_percentile=60.0, donchian_period=10,
        volume_multiplier=1.0, be_mode='pullback',
        trail_start_rr=1.2, pb_atr_buffer=2.0,
        require_bullish_bar=False,
    ),
    # Gold conservative: wider stops, strict filters
    "Gold_Conservative": StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=20.0, adx_threshold_validation=15.0,
        atr_sl_multiplier=2.0, atr_trail_multiplier=3.0,
        bbw_squeeze_percentile=35.0, donchian_period=20,
        volume_multiplier=1.0, be_mode='pullback',
        trail_start_rr=2.0, pb_atr_buffer=0.8,
    ),
}


def main():
    print("=" * 70)
    print("  XAUUSD (GOLD) STRATEGY BACKTEST & OPTIMIZATION")
    print("=" * 70)

    # Download gold data
    print("\n  DOWNLOADING XAUUSD DATA...")
    download_gold()

    # Run all configs
    results = {}
    for name, params in gold_configs.items():
        print(f"\n{'='*70}\n  CONFIG: {name}\n{'='*70}")

        bt, tested = run_multi_symbol_backtest(
            ["XAUUSD"], params, initial_capital=100000.0
        )
        result = bt.get_results()

        if isinstance(result, tuple):
            stats, trades_df = result
            results[name] = {"stats": stats, "trades_df": trades_df, "params": params}
            print(f"\n  >> {name}: {stats['total_trades']} trades | "
                  f"WR={stats['win_rate']:.1f}% | PF={stats['profit_factor']:.2f} | "
                  f"AvgRR={stats['avg_rr']:+.2f} | Return={stats['total_return_pct']:.1f}% | "
                  f"MaxDD={stats['max_drawdown_pct']:.1f}%")
        else:
            print(f"\n  >> {name}: {result}")

    # Summary
    print(f"\n\n{'='*70}")
    print("  XAUUSD PARAMETER COMPARISON")
    print(f"{'='*70}")
    print(f"  {'Config':<22s} {'Trades':>6s} {'WR%':>6s} {'PF':>6s} {'AvgRR':>6s} {'Return%':>8s} {'MaxDD%':>7s}")
    print(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*7}")

    best_name = None
    best_score = -999

    for name, r in results.items():
        s = r["stats"]
        # Score favoring PF, WR, reasonable DD, and enough trades
        trades_n = s["total_trades"]
        if trades_n < 5:
            score = -999
        else:
            score = (s["profit_factor"] * np.sqrt(trades_n) *
                     (1 - abs(s["max_drawdown_pct"]) / 100) *
                     (s["win_rate"] / 50))

        if score > best_score:
            best_score = score
            best_name = name

        print(f"  {name:<22s} {trades_n:>6d} {s['win_rate']:>5.1f}% "
              f"{s['profit_factor']:>5.2f} {s['avg_rr']:>+5.2f} "
              f"{s['total_return_pct']:>7.1f}% {s['max_drawdown_pct']:>6.1f}%")

    if best_name and best_name in results:
        best = results[best_name]
        print(f"\n  BEST GOLD CONFIG: {best_name} (score: {best_score:.2f})")
        print_results(best["stats"], f"XAUUSD OPTIMAL: {best_name}")

        # Monte Carlo
        if len(best["trades_df"]) > 0:
            mc = monte_carlo_stress_test(best["trades_df"], n_simulations=2000)

        # Parameters
        print(f"\n  OPTIMAL XAUUSD PARAMETERS:")
        for k, v in best["params"].to_dict().items():
            if k not in ["commission", "slippage_atr_frac"]:
                print(f"    {k}: {v}")

        # Save
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
        os.makedirs(results_dir, exist_ok=True)

        gold_output = {
            "symbol": "XAUUSD",
            "best_config": best_name,
            "parameters": best["params"].to_dict(),
            "performance": best["stats"],
            "monte_carlo": mc if 'mc' in dir() else None,
        }
        with open(os.path.join(results_dir, "xauusd_optimized.json"), "w") as f:
            json.dump(gold_output, f, indent=2, default=str)

        best["trades_df"].to_csv(os.path.join(results_dir, "xauusd_trades.csv"), index=False)
        print(f"\n  Results saved to: {results_dir}/xauusd_optimized.json")
    else:
        print("\n  No valid configurations found for XAUUSD.")
        print("  Gold may need a different strategy approach or more data.")


if __name__ == "__main__":
    main()
