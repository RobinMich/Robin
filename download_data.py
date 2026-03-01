#!/usr/bin/env python3
"""
Download historical data for all target instruments from Yahoo Finance.
Instruments: US100 (^NDX), NVDA, NFLX, PLTR, DELL, AVGO, LLY, MSFT, AAPL, JPM, TPL
Downloads daily and intraday data where available.
"""

import yfinance as yf
import pandas as pd
import os
import time

DATA_DIR = '/home/user/Robin/market_data'
os.makedirs(DATA_DIR, exist_ok=True)

SYMBOLS = {
    'US100': '^NDX',      # Nasdaq 100 Index
    'NVDA': 'NVDA',       # NVIDIA
    'NFLX': 'NFLX',       # Netflix
    'PLTR': 'PLTR',       # Palantir Technologies
    'DELL': 'DELL',       # Dell Technologies
    'AVGO': 'AVGO',       # Broadcom
    'LLY': 'LLY',         # Eli Lilly
    'MSFT': 'MSFT',       # Microsoft
    'AAPL': 'AAPL',       # Apple
    'JPM': 'JPM',         # JPMorgan Chase
    'TPL': 'TPL',         # Texas Pacific Land Corp
}

def download_symbol(name, ticker):
    """Download daily and intraday data for a symbol."""
    print(f"\n{'='*60}")
    print(f"Downloading: {name} ({ticker})")
    print(f"{'='*60}")

    # 1. Daily data - max period (usually ~20 years)
    try:
        print(f"  Fetching daily data (max period)...")
        daily = yf.download(ticker, period='2y', interval='1d', progress=False, auto_adjust=True)
        if daily is not None and len(daily) > 0:
            # Flatten MultiIndex columns if present
            if isinstance(daily.columns, pd.MultiIndex):
                daily.columns = daily.columns.get_level_values(0)
            filepath = os.path.join(DATA_DIR, f'{name}_daily.csv')
            daily.to_csv(filepath)
            print(f"  Daily: {len(daily)} bars saved to {filepath}")
            print(f"    Range: {daily.index[0]} to {daily.index[-1]}")
            print(f"    Price: {daily['Close'].iloc[0]:.2f} -> {daily['Close'].iloc[-1]:.2f}")
        else:
            print(f"  Daily: No data returned")
    except Exception as e:
        print(f"  Daily ERROR: {e}")

    # 2. Intraday 1-hour data (60 days max from Yahoo)
    try:
        print(f"  Fetching 1h intraday data (60 days)...")
        hourly = yf.download(ticker, period='60d', interval='1h', progress=False, auto_adjust=True)
        if hourly is not None and len(hourly) > 0:
            if isinstance(hourly.columns, pd.MultiIndex):
                hourly.columns = hourly.columns.get_level_values(0)
            filepath = os.path.join(DATA_DIR, f'{name}_1h.csv')
            hourly.to_csv(filepath)
            print(f"  1h: {len(hourly)} bars saved to {filepath}")
            print(f"    Range: {hourly.index[0]} to {hourly.index[-1]}")
        else:
            print(f"  1h: No data returned")
    except Exception as e:
        print(f"  1h ERROR: {e}")

    # 3. Intraday 5-min data (60 days max from Yahoo)
    try:
        print(f"  Fetching 5m intraday data (60 days)...")
        m5 = yf.download(ticker, period='60d', interval='5m', progress=False, auto_adjust=True)
        if m5 is not None and len(m5) > 0:
            if isinstance(m5.columns, pd.MultiIndex):
                m5.columns = m5.columns.get_level_values(0)
            filepath = os.path.join(DATA_DIR, f'{name}_5m.csv')
            m5.to_csv(filepath)
            print(f"  5m: {len(m5)} bars saved to {filepath}")
            print(f"    Range: {m5.index[0]} to {m5.index[-1]}")
        else:
            print(f"  5m: No data returned")
    except Exception as e:
        print(f"  5m ERROR: {e}")

    # 4. Intraday 15-min data (60 days max)
    try:
        print(f"  Fetching 15m intraday data (60 days)...")
        m15 = yf.download(ticker, period='60d', interval='15m', progress=False, auto_adjust=True)
        if m15 is not None and len(m15) > 0:
            if isinstance(m15.columns, pd.MultiIndex):
                m15.columns = m15.columns.get_level_values(0)
            filepath = os.path.join(DATA_DIR, f'{name}_15m.csv')
            m15.to_csv(filepath)
            print(f"  15m: {len(m15)} bars saved to {filepath}")
        else:
            print(f"  15m: No data returned")
    except Exception as e:
        print(f"  15m ERROR: {e}")

    time.sleep(1)  # rate limiting

if __name__ == "__main__":
    print("="*60)
    print("MARKET DATA DOWNLOADER")
    print("="*60)

    for name, ticker in SYMBOLS.items():
        download_symbol(name, ticker)

    # Summary
    print(f"\n{'='*60}")
    print("DOWNLOAD SUMMARY")
    print(f"{'='*60}")

    for f in sorted(os.listdir(DATA_DIR)):
        if f.endswith('.csv'):
            filepath = os.path.join(DATA_DIR, f)
            df = pd.read_csv(filepath)
            print(f"  {f:>25}: {len(df):>6} rows")

    print(f"\nAll data saved to: {DATA_DIR}")
