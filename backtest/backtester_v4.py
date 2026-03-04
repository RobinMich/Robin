#!/usr/bin/env python3
"""
Multi-Strategy Profit-Maximized Backtester v4.0
=================================================
Mirrors TrendPullbackEA v4.0 MQL5 EA with all new features:

1. RSI Confluence Filter - avoid overbought/oversold entries
2. Supertrend Confirmation - additional trend validation
3. Session Filter for XAUUSD (London/NY)
4. 3-Tier Partial Profit Taking (40% at 1.5R, 30% at 3R, trail rest)
5. Dynamic Risk Scaling (reduce in drawdown, scale with equity)
6. Momentum Scoring System (0-100 entry quality)
7. Chandelier Exit trailing (tighter after TP2)
8. Asset-specific presets (XAUUSD, Stocks, Indices)
"""

import os
import sys
import json
import warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ============================================================
# STRATEGY PARAMETERS v4.0
# ============================================================
@dataclass
class StrategyParams:
    # EMA
    ema_fast: int = 21
    ema_mid: int = 50
    ema_slow: int = 100

    # ADX
    adx_period: int = 14
    adx_threshold_context: float = 15.0
    adx_threshold_validation: float = 10.0

    # ATR
    atr_period: int = 14
    atr_sl_multiplier: float = 1.5
    atr_trail_multiplier: float = 2.0

    # BB Squeeze
    bb_period: int = 20
    bb_deviation: float = 2.0
    bbw_lookback: int = 50
    bbw_squeeze_percentile: float = 50.0

    # Donchian
    donchian_period: int = 12

    # Volume
    volume_period: int = 20
    volume_multiplier: float = 1.0

    # Risk Management
    risk_percent: float = 1.0
    be_rr_ratio: float = 1.5
    trail_start_rr: float = 1.5
    max_positions: int = 5
    require_bullish_bar: bool = False
    pb_atr_buffer: float = 1.2
    be_mode: str = 'pullback'
    commission: float = 0.0001
    slippage_atr_frac: float = 0.05
    direction: str = 'both'

    # === v4.0 features ===

    # RSI Filter
    rsi_enabled: bool = True
    rsi_period: int = 14
    rsi_ob_level: float = 70.0
    rsi_os_level: float = 30.0
    rsi_long_max: float = 65.0
    rsi_short_min: float = 35.0

    # Supertrend
    supertrend_enabled: bool = True
    st_period: int = 10
    st_multiplier: float = 2.0

    # Session filter (for forex/gold)
    session_enabled: bool = False
    session_london_start: int = 7
    session_london_end: int = 11
    session_ny_start: int = 13
    session_ny_end: int = 17

    # 3-Tier Partial TP
    partial_tp_enabled: bool = True
    tp1_fraction: float = 0.4   # 40% at tier 1
    tp1_rr: float = 1.5        # at 1.5:1 RR
    tp2_fraction: float = 0.3  # 30% at tier 2
    tp2_rr: float = 3.0        # at 3:1 RR
    # Remaining 30% trails with Chandelier Exit

    # Dynamic Risk
    dyn_risk_enabled: bool = True
    dyn_risk_max_multi: float = 1.5
    dyn_risk_min_multi: float = 0.5
    dd_reduce_start: float = 10.0
    dd_reduce_full: float = 25.0

    # Momentum Scoring
    mom_score_enabled: bool = True
    mom_score_min: int = 60

    # Equity curve filter
    equity_filter_enabled: bool = True
    equity_filter_period: int = 50

    # Chandelier tighten after TP2
    chandelier_tighten_after_tp2: float = 0.7

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================================
# ASSET PRESETS
# ============================================================
def get_xauusd_params():
    """Optimized parameters for XAUUSD (Gold)."""
    return StrategyParams(
        ema_fast=13, ema_mid=34, ema_slow=89,
        adx_threshold_context=12.0,
        adx_threshold_validation=8.0,
        atr_sl_multiplier=2.0,
        atr_trail_multiplier=2.5,
        bbw_squeeze_percentile=55.0,
        donchian_period=10,
        pb_atr_buffer=2.0,
        be_mode='pullback',
        be_rr_ratio=1.5,
        trail_start_rr=1.5,
        max_positions=3,
        require_bullish_bar=False,
        direction='both',
        rsi_enabled=True,
        rsi_long_max=60.0,
        rsi_short_min=40.0,
        supertrend_enabled=True,
        st_period=10,
        st_multiplier=2.0,
        session_enabled=True,
        partial_tp_enabled=True,
        tp1_fraction=0.4, tp1_rr=1.5,
        tp2_fraction=0.3, tp2_rr=3.0,
        dyn_risk_enabled=True,
        mom_score_enabled=True,
        mom_score_min=55,
        equity_filter_enabled=True,
        equity_filter_period=50,
    )


def get_stocks_params():
    """Optimized parameters for US Stocks."""
    return StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=12.0,
        adx_threshold_validation=8.0,
        atr_sl_multiplier=1.5,
        atr_trail_multiplier=2.5,
        bbw_squeeze_percentile=60.0,
        donchian_period=10,
        pb_atr_buffer=1.5,
        be_mode='pullback',
        be_rr_ratio=1.5,
        trail_start_rr=1.5,
        max_positions=5,
        require_bullish_bar=False,
        direction='both',
        rsi_enabled=True,
        rsi_long_max=65.0,
        rsi_short_min=35.0,
        supertrend_enabled=True,
        st_period=12,
        st_multiplier=2.5,
        session_enabled=False,
        partial_tp_enabled=True,
        tp1_fraction=0.4, tp1_rr=1.5,
        tp2_fraction=0.3, tp2_rr=3.0,
        dyn_risk_enabled=True,
        mom_score_enabled=True,
        mom_score_min=60,
        equity_filter_enabled=True,
        equity_filter_period=50,
    )


def get_indices_params():
    """Optimized parameters for Indices (US100, US500)."""
    return StrategyParams(
        ema_fast=21, ema_mid=50, ema_slow=100,
        adx_threshold_context=13.0,
        adx_threshold_validation=9.0,
        atr_sl_multiplier=1.8,
        atr_trail_multiplier=2.2,
        bbw_squeeze_percentile=50.0,
        donchian_period=12,
        pb_atr_buffer=1.5,
        be_mode='pullback',
        be_rr_ratio=1.5,
        trail_start_rr=1.5,
        max_positions=4,
        require_bullish_bar=False,
        direction='both',
        rsi_enabled=True,
        rsi_long_max=65.0,
        rsi_short_min=35.0,
        supertrend_enabled=True,
        st_period=12,
        st_multiplier=2.5,
        session_enabled=False,
        partial_tp_enabled=True,
        tp1_fraction=0.4, tp1_rr=1.5,
        tp2_fraction=0.3, tp2_rr=3.0,
        dyn_risk_enabled=True,
        mom_score_enabled=True,
        mom_score_min=60,
        equity_filter_enabled=True,
        equity_filter_period=50,
    )


# ============================================================
# TRADE RECORD v4.0
# ============================================================
@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    sl_price: float
    lot_size: float
    initial_risk: float
    initial_lot_size: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    rr_achieved: Optional[float] = None
    exit_reason: str = ""
    high_since_entry: float = 0.0
    low_since_entry: float = float('inf')
    be_applied: bool = False
    trailing_active: bool = False
    tp1_taken: bool = False
    tp2_taken: bool = False
    tp1_pnl: float = 0.0
    tp2_pnl: float = 0.0
    mom_score: int = 0
    risk_pct_used: float = 1.0


# ============================================================
# INDICATOR CALCULATIONS
# ============================================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_atr(high, low, close, period):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_adx(high, low, close, period=14):
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0),
                        index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0),
                         index=high.index)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_smooth = tr.ewm(span=period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(span=period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(span=period, adjust=False).mean()

    plus_di = 100 * plus_dm_smooth / atr_smooth
    minus_di = 100 * minus_dm_smooth / atr_smooth

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(span=period, adjust=False).mean()

    return adx, plus_di, minus_di


def calc_bollinger(close, period, deviation):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + deviation * std
    lower = mid - deviation * std
    bbw = (upper - lower) / mid
    return upper, lower, mid, bbw


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_supertrend(high, low, close, atr, period=10, multiplier=2.0):
    """Calculate Supertrend indicator. Returns (supertrend_value, is_uptrend)."""
    hl2 = (high + low) / 2.0
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=close.index, dtype=float)
    is_uptrend = pd.Series(index=close.index, dtype=bool)

    # Initialize
    supertrend.iloc[0] = upper_band.iloc[0]
    is_uptrend.iloc[0] = True

    for i in range(1, len(close)):
        if pd.isna(upper_band.iloc[i]) or pd.isna(lower_band.iloc[i]):
            supertrend.iloc[i] = supertrend.iloc[i-1]
            is_uptrend.iloc[i] = is_uptrend.iloc[i-1]
            continue

        # Final upper/lower band (adjust based on previous)
        if lower_band.iloc[i] > lower_band.iloc[i-1] or close.iloc[i-1] < lower_band.iloc[i-1]:
            final_lower = lower_band.iloc[i]
        else:
            final_lower = lower_band.iloc[i-1]

        if upper_band.iloc[i] < upper_band.iloc[i-1] or close.iloc[i-1] > upper_band.iloc[i-1]:
            final_upper = upper_band.iloc[i]
        else:
            final_upper = upper_band.iloc[i-1]

        if is_uptrend.iloc[i-1]:
            if close.iloc[i] < final_lower:
                is_uptrend.iloc[i] = False
                supertrend.iloc[i] = final_upper
            else:
                is_uptrend.iloc[i] = True
                supertrend.iloc[i] = final_lower
        else:
            if close.iloc[i] > final_upper:
                is_uptrend.iloc[i] = True
                supertrend.iloc[i] = final_lower
            else:
                is_uptrend.iloc[i] = False
                supertrend.iloc[i] = final_upper

    return supertrend, is_uptrend


def calc_donchian_upper(high, period):
    return high.rolling(period).max()


def calc_donchian_lower(low, period):
    return low.rolling(period).min()


def calc_volume_ma(volume, period):
    return volume.rolling(period).mean()


# ============================================================
# DATA LOADING
# ============================================================
def load_csv_data(filepath):
    df = pd.read_csv(filepath)

    if "time" in df.columns:
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    elif "Date" in df.columns:
        df["datetime"] = pd.to_datetime(df["Date"])
    elif "Datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["Datetime"])

    df.set_index("datetime", inplace=True)
    df.sort_index(inplace=True)

    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl == "open": col_map[c] = "open"
        elif cl == "high": col_map[c] = "high"
        elif cl == "low": col_map[c] = "low"
        elif cl == "close": col_map[c] = "close"
        elif cl in ("volume", "vol"): col_map[c] = "volume"
    df.rename(columns=col_map, inplace=True)

    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col} in {filepath}")

    if "volume" not in df.columns:
        df["volume"] = 0

    return df[["open", "high", "low", "close", "volume"]].dropna()


def load_symbol_data(symbol, data_dir):
    data = {}
    search_patterns = [
        (os.path.join(data_dir, f"{symbol}_1W.csv"), "W1"),
        (os.path.join(data_dir, f"{symbol}_1D.csv"), "D1"),
        (os.path.join(data_dir, f"{symbol}_H4.csv"), "H4"),
        (os.path.join(data_dir, f"{symbol}_1H.csv"), "H1"),
    ]

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    existing_patterns = [
        (os.path.join(repo_root, f"BATS_{symbol}, 1W.csv"), "W1"),
        (os.path.join(repo_root, f"BATS_{symbol}, 1D.csv"), "D1"),
        (os.path.join(repo_root, f"BATS_{symbol}, 120.csv"), "H2"),
    ]

    for filepath, tf_name in search_patterns + existing_patterns:
        if os.path.exists(filepath) and tf_name not in data:
            try:
                df = load_csv_data(filepath)
                if len(df) > 50:
                    data[tf_name] = df
                    print(f"    Loaded {tf_name}: {len(df)} bars from {os.path.basename(filepath)}")
            except Exception as e:
                print(f"    Warning: Could not load {filepath}: {e}")

    return data


def resample_to_weekly(daily_df):
    return daily_df.resample("W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()


def resample_to_h4(hourly_df):
    return hourly_df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna()


# ============================================================
# ADD INDICATORS TO DATAFRAME (v4.0 - includes RSI + Supertrend)
# ============================================================
def add_indicators(df, params):
    df = df.copy()

    # EMAs
    df["ema_fast"] = calc_ema(df["close"], params.ema_fast)
    df["ema_mid"] = calc_ema(df["close"], params.ema_mid)
    df["ema_slow"] = calc_ema(df["close"], params.ema_slow)

    # ADX / DMI
    df["adx"], df["di_plus"], df["di_minus"] = calc_adx(
        df["high"], df["low"], df["close"], params.adx_period
    )

    # ATR
    df["atr"] = calc_atr(df["high"], df["low"], df["close"], params.atr_period)

    # Bollinger Bands
    df["bb_upper"], df["bb_lower"], df["bb_mid"], df["bbw"] = calc_bollinger(
        df["close"], params.bb_period, params.bb_deviation
    )

    # BBW percentile
    df["bbw_pctile"] = df["bbw"].rolling(params.bbw_lookback).apply(
        lambda x: (x.iloc[-1] <= np.percentile(x, params.bbw_squeeze_percentile)) * 1.0,
        raw=False
    )

    # Donchian Channel
    df["donchian_upper"] = calc_donchian_upper(df["high"], params.donchian_period)
    df["donchian_lower"] = calc_donchian_lower(df["low"], params.donchian_period)

    # Volume MA
    df["volume_ma"] = calc_volume_ma(df["volume"], params.volume_period)

    # RSI (v4.0)
    if params.rsi_enabled:
        df["rsi"] = calc_rsi(df["close"], params.rsi_period)

    # Supertrend (v4.0)
    if params.supertrend_enabled:
        df["supertrend"], df["st_uptrend"] = calc_supertrend(
            df["high"], df["low"], df["close"], df["atr"],
            params.st_period, params.st_multiplier
        )

    return df


# ============================================================
# SIGNAL FUNCTIONS
# ============================================================
def _safe_get(row, key):
    val = row.get(key)
    if val is None:
        return np.nan
    if hasattr(val, 'item'):
        return val.item()
    return val


def get_context_signal_long(ctx_row, params):
    ema_fast = _safe_get(ctx_row, "ema_fast")
    ema_mid = _safe_get(ctx_row, "ema_mid")
    ema_slow = _safe_get(ctx_row, "ema_slow")
    if np.isnan(ema_fast) or np.isnan(ema_mid) or np.isnan(ema_slow):
        return False

    if not (ema_fast > ema_mid > ema_slow):
        return False

    close_val = _safe_get(ctx_row, "close")
    if np.isnan(close_val) or close_val < ema_fast:
        return False

    adx_val = _safe_get(ctx_row, "adx")
    if np.isnan(adx_val) or adx_val < params.adx_threshold_context:
        return False

    di_plus = _safe_get(ctx_row, "di_plus")
    di_minus = _safe_get(ctx_row, "di_minus")
    if np.isnan(di_plus) or np.isnan(di_minus) or di_plus <= di_minus:
        return False

    return True


def get_context_signal_short(ctx_row, params):
    ema_fast = _safe_get(ctx_row, "ema_fast")
    ema_mid = _safe_get(ctx_row, "ema_mid")
    ema_slow = _safe_get(ctx_row, "ema_slow")
    if np.isnan(ema_fast) or np.isnan(ema_mid) or np.isnan(ema_slow):
        return False

    if not (ema_fast < ema_mid < ema_slow):
        return False

    close_val = _safe_get(ctx_row, "close")
    if np.isnan(close_val) or close_val > ema_fast:
        return False

    adx_val = _safe_get(ctx_row, "adx")
    if np.isnan(adx_val) or adx_val < params.adx_threshold_context:
        return False

    di_plus = _safe_get(ctx_row, "di_plus")
    di_minus = _safe_get(ctx_row, "di_minus")
    if np.isnan(di_plus) or np.isnan(di_minus) or di_minus <= di_plus:
        return False

    return True


def get_validation_signal_long(val_row, params):
    ema_fast = _safe_get(val_row, "ema_fast")
    ema_mid = _safe_get(val_row, "ema_mid")
    ema_slow = _safe_get(val_row, "ema_slow")
    atr_val = _safe_get(val_row, "atr")
    close_val = _safe_get(val_row, "close")

    if np.isnan(ema_fast) or np.isnan(ema_slow) or np.isnan(atr_val):
        return False

    if ema_fast <= ema_slow:
        return False

    atr_buffer = atr_val * params.pb_atr_buffer
    in_pullback = False

    if not np.isnan(ema_mid):
        if close_val >= ema_mid and close_val <= ema_fast + atr_buffer:
            in_pullback = True

    if ema_fast - atr_buffer <= close_val <= ema_fast + atr_buffer:
        in_pullback = True

    if not in_pullback:
        return False

    adx_val2 = _safe_get(val_row, "adx")
    if np.isnan(adx_val2) or adx_val2 < params.adx_threshold_validation:
        return False

    bbw_pctile = _safe_get(val_row, "bbw_pctile")
    if np.isnan(bbw_pctile) or bbw_pctile != 1.0:
        return False

    return True


def get_validation_signal_short(val_row, params):
    ema_fast = _safe_get(val_row, "ema_fast")
    ema_mid = _safe_get(val_row, "ema_mid")
    ema_slow = _safe_get(val_row, "ema_slow")
    atr_val = _safe_get(val_row, "atr")
    close_val = _safe_get(val_row, "close")

    if np.isnan(ema_fast) or np.isnan(ema_slow) or np.isnan(atr_val):
        return False

    if ema_fast >= ema_slow:
        return False

    atr_buffer = atr_val * params.pb_atr_buffer
    in_pullback = False

    if not np.isnan(ema_mid):
        if close_val <= ema_mid and close_val >= ema_fast - atr_buffer:
            in_pullback = True

    if ema_fast - atr_buffer <= close_val <= ema_fast + atr_buffer:
        in_pullback = True

    if not in_pullback:
        return False

    adx_val2 = _safe_get(val_row, "adx")
    if np.isnan(adx_val2) or adx_val2 < params.adx_threshold_validation:
        return False

    bbw_pctile = _safe_get(val_row, "bbw_pctile")
    if np.isnan(bbw_pctile) or bbw_pctile != 1.0:
        return False

    return True


def get_entry_signal_long(entry_df, bar_idx, params):
    if bar_idx < params.donchian_period + 1:
        return False

    row = entry_df.iloc[bar_idx]

    ema_fast = float(row["ema_fast"]) if "ema_fast" in row.index else np.nan
    close = float(row["close"])
    open_p = float(row["open"])
    di_plus = float(row["di_plus"]) if "di_plus" in row.index else np.nan
    di_minus = float(row["di_minus"]) if "di_minus" in row.index else np.nan
    vol = float(row["volume"]) if "volume" in row.index else 0
    vol_ma = float(row["volume_ma"]) if "volume_ma" in row.index else np.nan

    if np.isnan(ema_fast):
        return False
    if close < ema_fast:
        return False
    if np.isnan(di_plus) or np.isnan(di_minus) or di_plus <= di_minus:
        return False

    # Donchian breakout
    lookback_start = bar_idx - params.donchian_period - 1
    lookback_end = bar_idx - 1
    if lookback_start < 0:
        return False

    donchian_upper = entry_df.iloc[lookback_start:lookback_end]["high"].max()
    if close <= donchian_upper:
        return False

    # Volume confirmation
    if vol > 0 and not np.isnan(vol_ma) and vol_ma > 0:
        if vol < vol_ma * params.volume_multiplier:
            return False

    if params.require_bullish_bar and close <= open_p:
        return False

    return True


def get_entry_signal_short(entry_df, bar_idx, params):
    if bar_idx < params.donchian_period + 1:
        return False

    row = entry_df.iloc[bar_idx]

    ema_fast = float(row["ema_fast"]) if "ema_fast" in row.index else np.nan
    close = float(row["close"])
    open_p = float(row["open"])
    di_plus = float(row["di_plus"]) if "di_plus" in row.index else np.nan
    di_minus = float(row["di_minus"]) if "di_minus" in row.index else np.nan
    vol = float(row["volume"]) if "volume" in row.index else 0
    vol_ma = float(row["volume_ma"]) if "volume_ma" in row.index else np.nan

    if np.isnan(ema_fast):
        return False
    if close > ema_fast:
        return False
    if np.isnan(di_plus) or np.isnan(di_minus) or di_minus <= di_plus:
        return False

    lookback_start = bar_idx - params.donchian_period - 1
    lookback_end = bar_idx - 1
    if lookback_start < 0:
        return False

    donchian_lower = entry_df.iloc[lookback_start:lookback_end]["low"].min()
    if close >= donchian_lower:
        return False

    if vol > 0 and not np.isnan(vol_ma) and vol_ma > 0:
        if vol < vol_ma * params.volume_multiplier:
            return False

    if params.require_bullish_bar and close >= open_p:
        return False

    return True


def check_rsi_filter(entry_df, bar_idx, params, is_long):
    """RSI confluence filter - avoid overbought/oversold entries."""
    if not params.rsi_enabled:
        return True
    if "rsi" not in entry_df.columns:
        return True

    rsi_val = float(entry_df.iloc[bar_idx]["rsi"])
    if np.isnan(rsi_val):
        return True

    if is_long:
        if rsi_val > params.rsi_long_max:
            return False
        if rsi_val < params.rsi_os_level:
            return False
    else:
        if rsi_val < params.rsi_short_min:
            return False
        if rsi_val > params.rsi_ob_level:
            return False

    return True


def check_supertrend_filter(entry_df, bar_idx, params, is_long):
    """Supertrend confirmation filter."""
    if not params.supertrend_enabled:
        return True
    if "st_uptrend" not in entry_df.columns:
        return True

    st_uptrend = entry_df.iloc[bar_idx]["st_uptrend"]
    if pd.isna(st_uptrend):
        return True

    if is_long:
        return bool(st_uptrend)
    else:
        return not bool(st_uptrend)


def check_session_filter(entry_df, bar_idx, params):
    """Session filter - only trade during London/NY for forex/gold."""
    if not params.session_enabled:
        return True

    ts = entry_df.index[bar_idx]
    hour = ts.hour

    # London session
    if params.session_london_start <= hour <= params.session_london_end:
        return True
    # NY session
    if params.session_ny_start <= hour <= params.session_ny_end:
        return True

    return False


def calculate_momentum_score(entry_df, bar_idx, params):
    """Calculate momentum quality score (0-100)."""
    if not params.mom_score_enabled:
        return 100

    score = 0
    row = entry_df.iloc[bar_idx]

    # ADX strength (0-30 points)
    adx_val = float(row.get("adx", 0))
    if not np.isnan(adx_val):
        if adx_val >= 30: score += 30
        elif adx_val >= 25: score += 25
        elif adx_val >= 20: score += 20
        elif adx_val >= 15: score += 15
        else: score += 10

    # RSI position (0-25 points)
    if "rsi" in row.index:
        rsi = float(row["rsi"])
        if not np.isnan(rsi):
            if 40 <= rsi <= 60: score += 25
            elif 35 <= rsi <= 65: score += 20
            elif 30 <= rsi <= 70: score += 15
            else: score += 5

    # Volume confirmation (0-25 points)
    vol = float(row.get("volume", 0))
    vol_ma = float(row.get("volume_ma", 0))
    if vol > 0 and not np.isnan(vol_ma) and vol_ma > 0:
        vol_ratio = vol / vol_ma
        if vol_ratio >= 2.0: score += 25
        elif vol_ratio >= 1.5: score += 20
        elif vol_ratio >= 1.2: score += 15
        elif vol_ratio >= 1.0: score += 10
        else: score += 5

    # Price action quality (0-20 points)
    open_p = float(row["open"])
    close_p = float(row["close"])
    high_p = float(row["high"])
    low_p = float(row["low"])
    body = abs(close_p - open_p)
    range_p = high_p - low_p
    if range_p > 0:
        body_ratio = body / range_p
        if body_ratio >= 0.7: score += 20
        elif body_ratio >= 0.5: score += 15
        elif body_ratio >= 0.3: score += 10
        else: score += 5

    return score


# ============================================================
# FIND MATCHING HIGHER-TF BAR
# ============================================================
def find_htf_bar(htf_df, entry_time):
    mask = htf_df.index <= entry_time
    if mask.sum() == 0:
        return None
    idx = htf_df.index[mask][-1]
    result = htf_df.loc[idx]
    if isinstance(result, pd.DataFrame):
        result = result.iloc[-1]
    return result


# ============================================================
# BACKTESTER ENGINE v4.0
# ============================================================
class Backtester:
    def __init__(self, params=None, initial_capital=100000.0):
        self.params = params or StrategyParams()
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.trades = []
        self.open_trades = []
        self.equity_curve = []
        self._equity_values = []
        self._peak_equity = initial_capital
        self._consecutive_wins = 0
        self._consecutive_losses = 0

    def run(self, symbol, context_df, validation_df, entry_df):
        p = self.params

        ctx = add_indicators(context_df, p)
        val = add_indicators(validation_df, p)
        ent = add_indicators(entry_df, p)

        min_bars = max(p.ema_slow, p.bbw_lookback + p.bb_period,
                       p.donchian_period + 5, p.st_period + 5 if p.supertrend_enabled else 0)
        if len(ent) < min_bars:
            print(f"    Not enough entry bars ({len(ent)} < {min_bars})")
            return

        print(f"    Running v4.0 backtest: {len(ent)} entry bars, "
              f"{len(val)} validation bars, {len(ctx)} context bars")

        for i in range(min_bars, len(ent)):
            current_time = ent.index[i]
            current_row = ent.iloc[i]

            equity = self._calc_equity(current_row["close"])
            self.equity_curve.append({
                "time": current_time,
                "equity": equity,
                "capital": self.capital
            })
            self._equity_values.append(equity)

            if equity > self._peak_equity:
                self._peak_equity = equity

            # Manage open trades
            self._manage_trades(ent, i)

            # Check for new entries
            if len(self.open_trades) >= p.max_positions:
                continue

            # Session filter
            if not check_session_filter(ent, i, p):
                continue

            # Equity curve filter
            if p.equity_filter_enabled and len(self._equity_values) > p.equity_filter_period:
                eq_arr = np.array(self._equity_values[-p.equity_filter_period:])
                eq_ma = eq_arr.mean()
                if self._equity_values[-1] < eq_ma:
                    continue

            # Momentum score
            mom_score = calculate_momentum_score(ent, i, p)
            if mom_score < p.mom_score_min:
                continue

            ctx_row = find_htf_bar(ctx, current_time)
            val_row = find_htf_bar(val, current_time)
            if ctx_row is None or val_row is None:
                continue

            # LONG
            if p.direction in ('long', 'both'):
                if (get_context_signal_long(ctx_row, p) and
                    get_validation_signal_long(val_row, p) and
                    get_entry_signal_long(ent, i, p) and
                    check_rsi_filter(ent, i, p, True) and
                    check_supertrend_filter(ent, i, p, True)):
                    self._open_trade(symbol, 'long', ent, i, mom_score)
                    continue

            # SHORT
            if p.direction in ('short', 'both'):
                if (get_context_signal_short(ctx_row, p) and
                    get_validation_signal_short(val_row, p) and
                    get_entry_signal_short(ent, i, p) and
                    check_rsi_filter(ent, i, p, False) and
                    check_supertrend_filter(ent, i, p, False)):
                    self._open_trade(symbol, 'short', ent, i, mom_score)

        # Close remaining
        for t in list(self.open_trades):
            last_row = ent.iloc[-1]
            self._close_trade(t, ent.index[-1], last_row["close"], "end_of_data")

        return self.trades

    def _get_dynamic_risk(self):
        """Dynamic risk based on equity curve."""
        p = self.params
        if not p.dyn_risk_enabled:
            return p.risk_percent

        equity = self.capital
        dd_pct = 0
        if self._peak_equity > 0:
            dd_pct = (self._peak_equity - equity) / self._peak_equity * 100.0

        risk_multi = 1.0

        if dd_pct >= p.dd_reduce_full:
            risk_multi = p.dyn_risk_min_multi
        elif dd_pct >= p.dd_reduce_start:
            dd_range = p.dd_reduce_full - p.dd_reduce_start
            dd_progress = (dd_pct - p.dd_reduce_start) / dd_range
            risk_multi = p.dyn_risk_max_multi - dd_progress * (p.dyn_risk_max_multi - p.dyn_risk_min_multi)
        else:
            if self._consecutive_wins >= 3:
                risk_multi = min(p.dyn_risk_max_multi, 1.0 + self._consecutive_wins * 0.1)

        return p.risk_percent * risk_multi

    def _open_trade(self, symbol, direction, entry_df, bar_idx, mom_score=100):
        row = entry_df.iloc[bar_idx]
        p = self.params

        entry_price = row["close"]
        atr = row["atr"]

        if pd.isna(atr) or atr <= 0 or entry_price <= 0:
            return

        slippage = atr * p.slippage_atr_frac
        if direction == 'long':
            entry_price += slippage
        else:
            entry_price -= slippage

        # Stop loss
        if direction == 'long':
            sl_price = entry_price - atr * p.atr_sl_multiplier

            lookback_start = max(0, bar_idx - p.donchian_period)
            swing_low = entry_df.iloc[lookback_start:bar_idx]["low"].min()
            if swing_low > sl_price and swing_low < entry_price:
                sl_price = swing_low - entry_price * 0.001
        else:
            sl_price = entry_price + atr * p.atr_sl_multiplier

            lookback_start = max(0, bar_idx - p.donchian_period)
            swing_high = entry_df.iloc[lookback_start:bar_idx]["high"].max()
            if swing_high < sl_price and swing_high > entry_price:
                sl_price = swing_high + entry_price * 0.001

        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            return

        # Dynamic risk
        risk_pct = self._get_dynamic_risk()

        # Bonus for A+ setups
        if p.mom_score_enabled and mom_score >= 85:
            risk_pct *= 1.2

        risk_amount = self.capital * risk_pct / 100.0
        lot_size = risk_amount / sl_distance

        commission = entry_price * lot_size * p.commission

        trade = Trade(
            symbol=symbol,
            direction=direction,
            entry_time=entry_df.index[bar_idx],
            entry_price=entry_price,
            sl_price=sl_price,
            lot_size=lot_size,
            initial_lot_size=lot_size,
            initial_risk=risk_amount,
            high_since_entry=entry_price if direction == 'long' else 0.0,
            low_since_entry=entry_price if direction == 'short' else float('inf'),
            mom_score=mom_score,
            risk_pct_used=risk_pct,
        )

        self.open_trades.append(trade)
        self.capital -= commission

    def _manage_trades(self, entry_df, bar_idx):
        p = self.params
        row = entry_df.iloc[bar_idx]
        current_low = row["low"]
        current_high = row["high"]
        current_close = row["close"]
        atr = row["atr"] if not pd.isna(row["atr"]) else 0

        for trade in list(self.open_trades):
            initial_risk_price = trade.initial_risk / trade.initial_lot_size if trade.initial_lot_size > 0 else 1

            if trade.direction == 'long':
                self._manage_long_trade(trade, entry_df, bar_idx, current_low, current_high,
                                        current_close, atr, initial_risk_price)
            else:
                self._manage_short_trade(trade, entry_df, bar_idx, current_low, current_high,
                                         current_close, atr, initial_risk_price)

    def _manage_long_trade(self, trade, entry_df, bar_idx, current_low, current_high,
                           current_close, atr, initial_risk_price):
        p = self.params

        if current_low <= trade.sl_price:
            exit_price = trade.sl_price
            reason = "stop_loss"
            if trade.be_applied and abs(trade.sl_price - trade.entry_price) < atr * 0.1:
                reason = "breakeven"
            self._close_trade(trade, entry_df.index[bar_idx], exit_price, reason)
            return

        if current_high > trade.high_since_entry:
            trade.high_since_entry = current_high

        current_profit = current_close - trade.entry_price
        current_rr = current_profit / initial_risk_price if initial_risk_price > 0 else 0

        # === TIER 1 TP (40%) ===
        if (p.partial_tp_enabled and not trade.tp1_taken and current_rr >= p.tp1_rr):
            partial_lots = trade.initial_lot_size * p.tp1_fraction
            partial_pnl = (current_close - trade.entry_price) * partial_lots
            commission = current_close * partial_lots * p.commission
            partial_pnl -= commission
            self.capital += partial_pnl
            trade.tp1_pnl = partial_pnl
            trade.lot_size -= partial_lots
            trade.tp1_taken = True

        # === TIER 2 TP (30%) ===
        if (p.partial_tp_enabled and trade.tp1_taken and not trade.tp2_taken and current_rr >= p.tp2_rr):
            partial_lots = trade.initial_lot_size * p.tp2_fraction
            if partial_lots > trade.lot_size:
                partial_lots = trade.lot_size
            partial_pnl = (current_close - trade.entry_price) * partial_lots
            commission = current_close * partial_lots * p.commission
            partial_pnl -= commission
            self.capital += partial_pnl
            trade.tp2_pnl = partial_pnl
            trade.lot_size -= partial_lots
            trade.tp2_taken = True

        # Breakeven logic
        if not trade.be_applied:
            apply_be = False
            if p.be_mode == 'rr':
                apply_be = (current_rr >= p.be_rr_ratio)
            else:
                if trade.high_since_entry - trade.entry_price >= initial_risk_price * 0.5:
                    if bar_idx >= 5:
                        mini_donchian_upper = entry_df.iloc[bar_idx-5:bar_idx-1]["high"].max()
                        if current_close > mini_donchian_upper:
                            apply_be = True

            if apply_be:
                trade.sl_price = trade.entry_price + initial_risk_price * 0.01
                trade.be_applied = True

        # Chandelier trailing
        if current_rr >= p.trail_start_rr:
            trade.trailing_active = True

        if trade.trailing_active and atr > 0:
            trail_distance = atr * p.atr_trail_multiplier
            # Tighter trailing after TP2 taken
            if trade.tp2_taken:
                trail_distance *= p.chandelier_tighten_after_tp2

            trail_sl = trade.high_since_entry - trail_distance
            if trail_sl > trade.sl_price and trail_sl < current_close:
                trade.sl_price = trail_sl

    def _manage_short_trade(self, trade, entry_df, bar_idx, current_low, current_high,
                            current_close, atr, initial_risk_price):
        p = self.params

        if current_high >= trade.sl_price:
            exit_price = trade.sl_price
            reason = "stop_loss"
            if trade.be_applied and abs(trade.sl_price - trade.entry_price) < atr * 0.1:
                reason = "breakeven"
            self._close_trade(trade, entry_df.index[bar_idx], exit_price, reason)
            return

        if current_low < trade.low_since_entry:
            trade.low_since_entry = current_low

        current_profit = trade.entry_price - current_close
        current_rr = current_profit / initial_risk_price if initial_risk_price > 0 else 0

        # === TIER 1 TP (40%) ===
        if (p.partial_tp_enabled and not trade.tp1_taken and current_rr >= p.tp1_rr):
            partial_lots = trade.initial_lot_size * p.tp1_fraction
            partial_pnl = (trade.entry_price - current_close) * partial_lots
            commission = current_close * partial_lots * p.commission
            partial_pnl -= commission
            self.capital += partial_pnl
            trade.tp1_pnl = partial_pnl
            trade.lot_size -= partial_lots
            trade.tp1_taken = True

        # === TIER 2 TP (30%) ===
        if (p.partial_tp_enabled and trade.tp1_taken and not trade.tp2_taken and current_rr >= p.tp2_rr):
            partial_lots = trade.initial_lot_size * p.tp2_fraction
            if partial_lots > trade.lot_size:
                partial_lots = trade.lot_size
            partial_pnl = (trade.entry_price - current_close) * partial_lots
            commission = current_close * partial_lots * p.commission
            partial_pnl -= commission
            self.capital += partial_pnl
            trade.tp2_pnl = partial_pnl
            trade.lot_size -= partial_lots
            trade.tp2_taken = True

        # Breakeven
        if not trade.be_applied:
            apply_be = False
            if p.be_mode == 'rr':
                apply_be = (current_rr >= p.be_rr_ratio)
            else:
                if trade.entry_price - trade.low_since_entry >= initial_risk_price * 0.5:
                    if bar_idx >= 5:
                        mini_donchian_lower = entry_df.iloc[bar_idx-5:bar_idx-1]["low"].min()
                        if current_close < mini_donchian_lower:
                            apply_be = True

            if apply_be:
                trade.sl_price = trade.entry_price - initial_risk_price * 0.01
                trade.be_applied = True

        # Chandelier trailing
        if current_rr >= p.trail_start_rr:
            trade.trailing_active = True

        if trade.trailing_active and atr > 0:
            trail_distance = atr * p.atr_trail_multiplier
            if trade.tp2_taken:
                trail_distance *= p.chandelier_tighten_after_tp2

            trail_sl = trade.low_since_entry + trail_distance
            if trail_sl < trade.sl_price and trail_sl > current_close:
                trade.sl_price = trail_sl

    def _close_trade(self, trade, exit_time, exit_price, reason):
        p = self.params

        if reason in ("stop_loss", "breakeven"):
            if trade.direction == 'long':
                exit_price -= trade.entry_price * 0.0001
            else:
                exit_price += trade.entry_price * 0.0001

        if trade.direction == 'long':
            remaining_pnl = (exit_price - trade.entry_price) * trade.lot_size
        else:
            remaining_pnl = (trade.entry_price - exit_price) * trade.lot_size

        initial_risk_price = trade.initial_risk / trade.initial_lot_size if trade.initial_lot_size > 0 else 1
        if trade.direction == 'long':
            rr = (exit_price - trade.entry_price) / initial_risk_price if initial_risk_price > 0 else 0
        else:
            rr = (trade.entry_price - exit_price) / initial_risk_price if initial_risk_price > 0 else 0

        commission = exit_price * trade.lot_size * p.commission
        remaining_pnl -= commission

        pnl = trade.tp1_pnl + trade.tp2_pnl + remaining_pnl

        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.rr_achieved = rr
        trade.exit_reason = reason

        self.capital += remaining_pnl

        # Track win/loss streaks for dynamic risk
        if pnl > 0:
            self._consecutive_wins += 1
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            self._consecutive_wins = 0

        self.trades.append(trade)

        if trade in self.open_trades:
            self.open_trades.remove(trade)

    def _calc_equity(self, current_price):
        equity = self.capital
        for t in self.open_trades:
            if t.direction == 'long':
                unrealized = (current_price - t.entry_price) * t.lot_size
            else:
                unrealized = (t.entry_price - current_price) * t.lot_size
            equity += unrealized
        return equity

    def get_results(self):
        if not self.trades:
            return {"error": "No trades executed"}

        trades_df = pd.DataFrame([{
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "sl_price": t.sl_price,
            "lot_size": t.lot_size,
            "initial_lot_size": t.initial_lot_size,
            "pnl": t.pnl,
            "rr": t.rr_achieved,
            "exit_reason": t.exit_reason,
            "initial_risk": t.initial_risk,
            "tp1_taken": t.tp1_taken,
            "tp2_taken": t.tp2_taken,
            "tp1_pnl": t.tp1_pnl,
            "tp2_pnl": t.tp2_pnl,
            "mom_score": t.mom_score,
            "risk_pct_used": t.risk_pct_used,
        } for t in self.trades])

        total_trades = len(trades_df)
        winners = trades_df[trades_df["pnl"] > 0]
        losers = trades_df[trades_df["pnl"] <= 0]

        win_rate = len(winners) / total_trades * 100 if total_trades > 0 else 0
        avg_win = winners["pnl"].mean() if len(winners) > 0 else 0
        avg_loss = losers["pnl"].mean() if len(losers) > 0 else 0
        avg_rr = trades_df["rr"].mean()

        total_pnl = trades_df["pnl"].sum()
        total_return = total_pnl / self.initial_capital * 100

        gross_profit = winners["pnl"].sum() if len(winners) > 0 else 0
        gross_loss = abs(losers["pnl"].sum()) if len(losers) > 0 else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        max_dd = 0
        max_dd_pct = 0
        if self.equity_curve:
            eq_df = pd.DataFrame(self.equity_curve)
            peak = eq_df["equity"].expanding().max()
            drawdown = eq_df["equity"] - peak
            max_dd = drawdown.min()
            dd_pct = (drawdown / peak * 100)
            max_dd_pct = dd_pct.min()

        expectancy = (win_rate / 100 * avg_win + (1 - win_rate / 100) * avg_loss)

        exit_reasons = trades_df["exit_reason"].value_counts().to_dict()

        long_trades = trades_df[trades_df["direction"] == "long"]
        short_trades = trades_df[trades_df["direction"] == "short"]

        if "entry_time" in trades_df.columns and "exit_time" in trades_df.columns:
            hold_times = (trades_df["exit_time"] - trades_df["entry_time"]).dt.total_seconds() / 3600
            avg_hold_hours = hold_times.mean()
        else:
            avg_hold_hours = 0

        is_win = (trades_df["pnl"] > 0).astype(int)
        max_consec_wins = max_consecutive(is_win, 1)
        max_consec_losses = max_consecutive(is_win, 0)

        tp1_count = int(trades_df["tp1_taken"].sum())
        tp2_count = int(trades_df["tp2_taken"].sum())
        avg_mom_score = trades_df["mom_score"].mean()

        results = {
            "total_trades": total_trades,
            "long_trades": len(long_trades),
            "short_trades": len(short_trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(win_rate, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_rr": round(avg_rr, 2),
            "median_rr": round(trades_df["rr"].median(), 2),
            "best_trade_rr": round(trades_df["rr"].max(), 2),
            "worst_trade_rr": round(trades_df["rr"].min(), 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "initial_capital": self.initial_capital,
            "final_capital": round(self.capital, 2),
            "avg_hold_hours": round(avg_hold_hours, 1),
            "max_consec_wins": max_consec_wins,
            "max_consec_losses": max_consec_losses,
            "exit_reasons": exit_reasons,
            "tp1_count": tp1_count,
            "tp2_count": tp2_count,
            "avg_momentum_score": round(avg_mom_score, 1),
        }

        if len(long_trades) > 0:
            results["long_win_rate"] = round((long_trades["pnl"] > 0).mean() * 100, 2)
            results["long_pnl"] = round(long_trades["pnl"].sum(), 2)
        if len(short_trades) > 0:
            results["short_win_rate"] = round((short_trades["pnl"] > 0).mean() * 100, 2)
            results["short_pnl"] = round(short_trades["pnl"].sum(), 2)

        return results, trades_df


def max_consecutive(series, value):
    groups = (series != value).cumsum()
    filtered = series[series == value]
    if filtered.empty:
        return 0
    return filtered.groupby(groups[series == value]).count().max()


# ============================================================
# MULTI-SYMBOL BACKTEST RUNNER v4.0
# ============================================================
def run_multi_symbol_backtest(symbols, params=None, initial_capital=100000.0,
                              data_dir=None, use_preset=True):
    """Run backtest across multiple symbols with asset-specific presets."""
    if params is None:
        params = StrategyParams()

    if data_dir is None:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    bt = Backtester(params=params, initial_capital=initial_capital)
    symbols_tested = []

    for symbol in symbols:
        print(f"\n  Processing {symbol}...")

        # Auto-detect preset
        if use_preset:
            if "XAU" in symbol or "GOLD" in symbol:
                p = get_xauusd_params()
                bt_sym = Backtester(params=p, initial_capital=bt.capital)
                print(f"    Using XAUUSD preset")
            elif symbol in ("US100", "US500"):
                p = get_indices_params()
                bt_sym = Backtester(params=p, initial_capital=bt.capital)
                print(f"    Using INDICES preset")
            else:
                p = params
                bt_sym = Backtester(params=p, initial_capital=bt.capital)
        else:
            p = params
            bt_sym = Backtester(params=p, initial_capital=bt.capital)

        data = load_symbol_data(symbol, data_dir)

        # Determine timeframes based on preset
        is_gold = "XAU" in symbol or "GOLD" in symbol
        is_index = symbol in ("US100", "US500")

        if is_gold or is_index:
            ctx_df = data.get("D1")
            val_df = data.get("H4")
            entry_df = data.get("H1")

            if ctx_df is None and "W1" in data:
                ctx_df = data["W1"]
            if val_df is None and "D1" in data:
                val_df = data["D1"]
            if entry_df is None and "H4" in data:
                entry_df = data["H4"]
        else:
            ctx_df = data.get("W1")
            val_df = data.get("D1")
            entry_df = data.get("H4")
            if entry_df is None:
                entry_df = data.get("H2")
            if entry_df is None:
                entry_df = data.get("H1")

        if ctx_df is None and val_df is not None:
            ctx_df = resample_to_weekly(val_df)
            print(f"    Resampled D1 -> W1: {len(ctx_df)} bars")

        if entry_df is None and val_df is not None:
            entry_df = val_df
            print(f"    Using D1 as entry TF")

        if ctx_df is None or val_df is None or entry_df is None:
            print(f"    SKIP: Missing required timeframes for {symbol}")
            continue

        bt_sym.run(symbol, ctx_df, val_df, entry_df)

        # Merge trades back
        for t in bt_sym.trades:
            bt.trades.append(t)
        bt.capital = bt_sym.capital
        bt._peak_equity = max(bt._peak_equity, bt_sym._peak_equity)
        bt.equity_curve.extend(bt_sym.equity_curve)
        bt._equity_values.extend(bt_sym._equity_values)
        bt._consecutive_wins = bt_sym._consecutive_wins
        bt._consecutive_losses = bt_sym._consecutive_losses

        symbols_tested.append(symbol)

    print(f"\n  Symbols tested: {len(symbols_tested)}")
    return bt, symbols_tested


# ============================================================
# PRETTY PRINT RESULTS
# ============================================================
def print_results(results, title="BACKTEST RESULTS v4.0"):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)

    if "error" in results:
        print(f"  {results['error']}")
        return

    print(f"  Total Trades:       {results['total_trades']}")
    print(f"    Long:             {results.get('long_trades', 'N/A')}")
    print(f"    Short:            {results.get('short_trades', 'N/A')}")
    print(f"  Winners:            {results['winners']} ({results['win_rate']}%)")
    print(f"  Losers:             {results['losers']}")
    print(f"  Avg Win:           ${results['avg_win']:,.2f}")
    print(f"  Avg Loss:          ${results['avg_loss']:,.2f}")
    print(f"  Avg RR:             {results['avg_rr']:.2f}")
    print(f"  Median RR:          {results['median_rr']:.2f}")
    print(f"  Best Trade RR:      {results['best_trade_rr']:.2f}")
    print(f"  Worst Trade RR:     {results['worst_trade_rr']:.2f}")
    print("-" * 65)
    print(f"  Total P&L:         ${results['total_pnl']:,.2f}")
    print(f"  Total Return:       {results['total_return_pct']:.2f}%")
    print(f"  Profit Factor:      {results['profit_factor']:.2f}")
    print(f"  Expectancy:        ${results['expectancy']:,.2f}")
    print(f"  Max Drawdown:      ${results['max_drawdown']:,.2f} ({results['max_drawdown_pct']:.2f}%)")
    print("-" * 65)
    print(f"  Initial Capital:   ${results['initial_capital']:,.2f}")
    print(f"  Final Capital:     ${results['final_capital']:,.2f}")
    print(f"  Avg Hold Time:      {results['avg_hold_hours']:.1f} hours")
    print(f"  Max Consec Wins:    {results['max_consec_wins']}")
    print(f"  Max Consec Losses:  {results['max_consec_losses']}")
    print(f"  Tier 1 TPs:         {results.get('tp1_count', 0)}")
    print(f"  Tier 2 TPs:         {results.get('tp2_count', 0)}")
    print(f"  Avg Mom Score:      {results.get('avg_momentum_score', 0)}")

    if "long_win_rate" in results:
        print(f"  Long WR:            {results['long_win_rate']}% | P&L: ${results.get('long_pnl', 0):,.2f}")
    if "short_win_rate" in results:
        print(f"  Short WR:           {results['short_win_rate']}% | P&L: ${results.get('short_pnl', 0):,.2f}")

    print("-" * 65)
    print(f"  Exit Reasons:")
    for reason, count in results.get("exit_reasons", {}).items():
        print(f"    {reason}: {count}")
    print("=" * 65)


# ============================================================
# MAIN
# ============================================================
ALL_SYMBOLS = [
    "AAPL", "AMD", "AMZN", "AVGO", "GOOG", "META", "MSFT", "NVDA", "TSLA",
    "US100", "US500", "WMT", "WDC", "MU", "PLTR", "SAP", "RHM", "STX",
    "BAC", "GS", "AXP", "LLY", "COST", "XOM", "CAT", "CSCO", "SIEGY", "TJX",
    "XAUUSD"
]


def main():
    print("=" * 65)
    print("  TREND-FOLLOW PULLBACK STRATEGY v4.0 - PROFIT MAXIMIZED")
    print("  RSI + Supertrend + 3-Tier TP + Dynamic Risk + Mom Score")
    print("=" * 65)

    params = get_stocks_params()

    bt, symbols_tested = run_multi_symbol_backtest(
        ALL_SYMBOLS, params=params, initial_capital=100000.0, use_preset=True
    )

    result = bt.get_results()
    if isinstance(result, tuple):
        results, trades_df = result

        print_results(results, "v4.0 FINAL RESULTS (Profit Maximized)")

        # Per-symbol breakdown
        print("\n  PER-SYMBOL BREAKDOWN:")
        print("-" * 90)
        print(f"  {'Symbol':<8s} {'Trades':>6s} {'Long':>5s} {'Short':>5s} "
              f"{'WR%':>6s} {'AvgRR':>6s} {'PnL':>12s} {'TP1':>4s} {'TP2':>4s} {'AvgM':>5s}")
        print("-" * 90)

        for sym in symbols_tested:
            sym_trades = trades_df[trades_df["symbol"] == sym]
            if len(sym_trades) > 0:
                sym_pnl = sym_trades["pnl"].sum()
                sym_wr = (sym_trades["pnl"] > 0).mean() * 100
                sym_rr = sym_trades["rr"].mean()
                n_long = len(sym_trades[sym_trades["direction"] == "long"])
                n_short = len(sym_trades[sym_trades["direction"] == "short"])
                n_tp1 = int(sym_trades["tp1_taken"].sum())
                n_tp2 = int(sym_trades["tp2_taken"].sum())
                avg_m = sym_trades["mom_score"].mean()
                print(f"  {sym:<8s} {len(sym_trades):>6d} {n_long:>5d} {n_short:>5d} "
                      f"{sym_wr:>5.1f}% {sym_rr:>+5.2f} ${sym_pnl:>11,.2f} {n_tp1:>4d} {n_tp2:>4d} {avg_m:>5.0f}")

        # Save results
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
        os.makedirs(results_dir, exist_ok=True)

        trades_df.to_csv(os.path.join(results_dir, "v4_trades.csv"), index=False)

        with open(os.path.join(results_dir, "v4_results.json"), "w") as f:
            json.dump({
                "strategy_name": "TrendPullbackEA",
                "version": "4.0_PROFIT_MAXIMIZED",
                "performance": results,
                "symbols_trading": [sym for sym in symbols_tested
                                   if len(trades_df[trades_df["symbol"] == sym]) > 0],
            }, f, indent=2, default=str)

        print(f"\n  Results saved to: {results_dir}")
    else:
        print(f"\n  {result}")


if __name__ == "__main__":
    main()
