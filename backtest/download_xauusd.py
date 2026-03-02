#!/usr/bin/env python3
"""Download XAUUSD (Gold) historical data from multiple sources."""

import os
import sys
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    os.system(f"{sys.executable} -m pip install yfinance")
    import yfinance as yf

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)


def save_ohlcv(df, path):
    out = pd.DataFrame()
    out["time"] = df.index.astype(int) // 10**9
    out["open"] = df["Open"].values
    out["high"] = df["High"].values
    out["low"] = df["Low"].values
    out["close"] = df["Close"].values
    out["volume"] = df["Volume"].values
    out.to_csv(path, index=False)


def resample_to_h4(df):
    return df.resample("4h").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum"
    }).dropna()


# XAUUSD tickers to try (Yahoo Finance uses GC=F for gold futures, or use ETF GLD)
tickers = {
    "GC=F": "Gold Futures (XAUUSD proxy)",
    "GLD": "SPDR Gold ETF (backup)",
}

for ticker, desc in tickers.items():
    print(f"\nDownloading {desc} ({ticker})...")

    try:
        stock = yf.Ticker(ticker)

        # Daily - max history
        df_daily = stock.history(period="10y", interval="1d")
        if not df_daily.empty:
            path = os.path.join(DATA_DIR, f"XAUUSD_1D.csv")
            save_ohlcv(df_daily, path)
            print(f"  Daily: {len(df_daily)} bars -> {path}")

        # Weekly
        df_weekly = stock.history(period="10y", interval="1wk")
        if not df_weekly.empty:
            path = os.path.join(DATA_DIR, f"XAUUSD_1W.csv")
            save_ohlcv(df_weekly, path)
            print(f"  Weekly: {len(df_weekly)} bars -> {path}")

        # Hourly (max 730 days)
        df_hourly = stock.history(period="730d", interval="1h")
        if not df_hourly.empty:
            path = os.path.join(DATA_DIR, f"XAUUSD_1H.csv")
            save_ohlcv(df_hourly, path)
            print(f"  Hourly: {len(df_hourly)} bars -> {path}")

            # Resample to H4
            df_h4 = resample_to_h4(df_hourly)
            if not df_h4.empty:
                path = os.path.join(DATA_DIR, f"XAUUSD_H4.csv")
                save_ohlcv(df_h4, path)
                print(f"  H4: {len(df_h4)} bars -> {path}")

        if not df_daily.empty:
            print(f"\n  SUCCESS: Using {desc} as XAUUSD data")
            print(f"  Date range: {df_daily.index[0].date()} to {df_daily.index[-1].date()}")
            print(f"  Price range: ${df_daily['Low'].min():.2f} - ${df_daily['High'].max():.2f}")
            break

    except Exception as e:
        print(f"  ERROR: {e}")
        continue

print("\nDone!")
