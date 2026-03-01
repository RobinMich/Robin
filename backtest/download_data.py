#!/usr/bin/env python3
"""
Download historical data for all strategy symbols using yfinance.
Saves data in CSV format compatible with the backtester.
"""

import os
import sys
import time
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("Installing yfinance...")
    os.system(f"{sys.executable} -m pip install yfinance")
    import yfinance as yf

# Symbol mapping: Strategy name -> Yahoo Finance ticker
SYMBOL_MAP = {
    # Indices
    "US100": "^NDX",
    "US500": "^GSPC",
    # Tech
    "META": "META",
    "NVDA": "NVDA",
    "GOOG": "GOOG",
    "AAPL": "AAPL",
    "TSLA": "TSLA",
    "AMD": "AMD",
    "CSCO": "CSCO",
    "MU": "MU",
    "PLTR": "PLTR",
    "AVGO": "AVGO",
    "MSFT": "MSFT",
    "AMZN": "AMZN",
    # Consumer / Retail
    "WMT": "WMT",
    "COST": "COST",
    "TJX": "TJX",
    # Industrial / Defense
    "CAT": "CAT",
    "SAP": "SAP",
    "RHM": "RNMBY",     # Rheinmetall OTC
    "SIEGY": "SIEGY",    # Siemens ADR
    # Storage / Semiconductors
    "WDC": "WDC",
    "STX": "STX",
    # Finance
    "BAC": "BAC",
    "GS": "GS",
    "AXP": "AXP",
    # Pharma / Energy
    "LLY": "LLY",
    "XOM": "XOM",
}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def download_symbol(name, ticker, period="10y"):
    """Download daily and weekly data for a symbol."""
    print(f"  Downloading {name} ({ticker})...")

    try:
        stock = yf.Ticker(ticker)

        # Daily data
        df_daily = stock.history(period=period, interval="1d")
        if df_daily.empty:
            print(f"    WARNING: No daily data for {name}")
            return False

        # Weekly data
        df_weekly = stock.history(period=period, interval="1wk")

        # Hourly data (limited to 730 days by Yahoo)
        df_hourly = stock.history(period="730d", interval="1h")

        # Save daily
        path_daily = os.path.join(DATA_DIR, f"{name}_1D.csv")
        save_ohlcv(df_daily, path_daily)
        print(f"    Daily: {len(df_daily)} bars -> {path_daily}")

        # Save weekly
        if not df_weekly.empty:
            path_weekly = os.path.join(DATA_DIR, f"{name}_1W.csv")
            save_ohlcv(df_weekly, path_weekly)
            print(f"    Weekly: {len(df_weekly)} bars -> {path_weekly}")

        # Save hourly (will be used as proxy for H4 by resampling)
        if not df_hourly.empty:
            path_hourly = os.path.join(DATA_DIR, f"{name}_1H.csv")
            save_ohlcv(df_hourly, path_hourly)
            print(f"    Hourly: {len(df_hourly)} bars -> {path_hourly}")

            # Resample to H4
            df_h4 = resample_to_h4(df_hourly)
            if not df_h4.empty:
                path_h4 = os.path.join(DATA_DIR, f"{name}_H4.csv")
                save_ohlcv(df_h4, path_h4)
                print(f"    H4: {len(df_h4)} bars -> {path_h4}")

        return True

    except Exception as e:
        print(f"    ERROR downloading {name}: {e}")
        return False


def save_ohlcv(df, path):
    """Save DataFrame in standard OHLCV format."""
    out = pd.DataFrame()
    out["time"] = df.index.astype(int) // 10**9  # Unix timestamp
    out["open"] = df["Open"].values
    out["high"] = df["High"].values
    out["low"] = df["Low"].values
    out["close"] = df["Close"].values
    out["volume"] = df["Volume"].values
    out.to_csv(path, index=False)


def resample_to_h4(df_hourly):
    """Resample hourly data to 4-hour bars."""
    if df_hourly.empty:
        return pd.DataFrame()

    df = df_hourly.copy()
    df_h4 = df.resample("4h").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()

    return df_h4


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 60)
    print("DOWNLOADING HISTORICAL DATA FOR STRATEGY BACKTESTING")
    print("=" * 60)

    success = 0
    failed = 0

    for name, ticker in SYMBOL_MAP.items():
        ok = download_symbol(name, ticker)
        if ok:
            success += 1
        else:
            failed += 1
        time.sleep(0.5)  # Rate limiting

    print("\n" + "=" * 60)
    print(f"DOWNLOAD COMPLETE: {success} success, {failed} failed")
    print(f"Data saved to: {DATA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
