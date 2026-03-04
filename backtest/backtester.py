#!/usr/bin/env python3
"""
Multi-Timeframe Trend-Follow Pullback Strategy Backtester v3.0
================================================================
Enhanced with:
- Bidirectional trading (long + short)
- Partial profit-taking (close 50% at target RR)
- Improved BE timing (delayed to prevent premature exits)
- Equity curve filter (pause trading during drawdowns)
- Better trailing stop management

Strategy:
- Context TF (W1): EMA alignment + ADX trend filter
- Validation TF (D1): Pullback zone + BB Squeeze
- Entry TF (H4/H2/H1): Donchian breakout + Volume filter
- Long & Short, 1% risk, partial TP, ATR trailing
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
# STRATEGY PARAMETERS (mirrors MQL5 inputs)
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
    be_rr_ratio: float = 1.5      # Delayed BE - move to BE at 1.5 RR instead of 1.0
    trail_start_rr: float = 1.5
    max_positions: int = 5
    require_bullish_bar: bool = False

    # Pullback zone
    pb_atr_buffer: float = 1.2

    # BE mode: 'rr' or 'pullback'
    be_mode: str = 'pullback'

    # Commission per trade (one-way, as fraction of trade value)
    commission: float = 0.0001  # 1 basis point

    # Slippage as fraction of ATR
    slippage_atr_frac: float = 0.05

    # === NEW v3.0 parameters ===

    # Direction: 'long', 'short', or 'both'
    direction: str = 'both'

    # Partial profit-taking: close this fraction at partial_tp_rr
    partial_tp_enabled: bool = True
    partial_tp_fraction: float = 0.5   # Close 50% of position
    partial_tp_rr: float = 2.0         # At 2:1 RR

    # Equity curve filter: pause trading when equity < EMA of equity
    equity_filter_enabled: bool = False  # Disabled by default, enable after tuning
    equity_filter_period: int = 200    # MA period for equity curve (long window)

    # Cooldown: bars to wait after a loss before re-entering
    cooldown_bars: int = 0

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================================
# TRADE RECORD
# ============================================================
@dataclass
class Trade:
    symbol: str
    direction: str  # 'long' or 'short'
    entry_time: pd.Timestamp
    entry_price: float
    sl_price: float
    lot_size: float
    initial_risk: float  # $ risk
    initial_lot_size: float = 0.0  # original lot size before partial TP
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    rr_achieved: Optional[float] = None
    exit_reason: str = ""
    high_since_entry: float = 0.0
    low_since_entry: float = float('inf')
    be_applied: bool = False
    trailing_active: bool = False
    partial_tp_taken: bool = False
    partial_tp_pnl: float = 0.0


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
    """Calculate ADX, DI+, DI-"""
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
    """Calculate Bollinger Bands and BBW"""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + deviation * std
    lower = mid - deviation * std
    bbw = (upper - lower) / mid
    return upper, lower, mid, bbw


def calc_donchian_upper(high, period):
    """Donchian Channel upper band (highest high of N periods)"""
    return high.rolling(period).max()


def calc_donchian_lower(low, period):
    """Donchian Channel lower band (lowest low of N periods)"""
    return low.rolling(period).min()


def calc_volume_ma(volume, period):
    return volume.rolling(period).mean()


# ============================================================
# DATA LOADING
# ============================================================
def load_csv_data(filepath):
    """Load CSV data and return DataFrame with datetime index."""
    df = pd.read_csv(filepath)

    # Handle timestamp column
    if "time" in df.columns:
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    elif "Date" in df.columns:
        df["datetime"] = pd.to_datetime(df["Date"])
    elif "Datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["Datetime"])

    df.set_index("datetime", inplace=True)
    df.sort_index(inplace=True)

    # Standardize column names
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl == "open":
            col_map[c] = "open"
        elif cl == "high":
            col_map[c] = "high"
        elif cl == "low":
            col_map[c] = "low"
        elif cl == "close":
            col_map[c] = "close"
        elif cl in ("volume", "vol"):
            col_map[c] = "volume"
    df.rename(columns=col_map, inplace=True)

    # Ensure required columns
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col} in {filepath}")

    if "volume" not in df.columns:
        df["volume"] = 0

    return df[["open", "high", "low", "close", "volume"]].dropna()


def load_symbol_data(symbol, data_dir):
    """Load all timeframes for a symbol. Returns dict of DataFrames."""
    data = {}

    # Try downloaded data first, then existing repo data
    search_patterns = [
        # Downloaded data
        (os.path.join(data_dir, f"{symbol}_1W.csv"), "W1"),
        (os.path.join(data_dir, f"{symbol}_1D.csv"), "D1"),
        (os.path.join(data_dir, f"{symbol}_H4.csv"), "H4"),
        (os.path.join(data_dir, f"{symbol}_1H.csv"), "H1"),
    ]

    # Also check repo root for existing BATS data
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
    """Resample daily data to weekly if no weekly data available."""
    return daily_df.resample("W").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()


def resample_to_h4(hourly_df):
    """Resample hourly data to H4."""
    return hourly_df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()


# ============================================================
# ADD INDICATORS TO DATAFRAME
# ============================================================
def add_indicators(df, params):
    """Add all strategy indicators to a DataFrame."""
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

    # BBW percentile (rolling)
    df["bbw_pctile"] = df["bbw"].rolling(params.bbw_lookback).apply(
        lambda x: (x.iloc[-1] <= np.percentile(x, params.bbw_squeeze_percentile)) * 1.0,
        raw=False
    )

    # Donchian Channel
    df["donchian_upper"] = calc_donchian_upper(df["high"], params.donchian_period)
    df["donchian_lower"] = calc_donchian_lower(df["low"], params.donchian_period)

    # Volume MA
    df["volume_ma"] = calc_volume_ma(df["volume"], params.volume_period)

    return df


# ============================================================
# MULTI-TIMEFRAME SIGNAL ALIGNMENT
# ============================================================
def _safe_get(row, key):
    """Safely get a scalar value from a Series row."""
    val = row.get(key)
    if val is None:
        return np.nan
    if hasattr(val, 'item'):
        return val.item()
    return val


def get_context_signal_long(ctx_row, params):
    """Check Context TF (W1) LONG conditions. Returns True if bullish trend."""
    ema_fast = _safe_get(ctx_row, "ema_fast")
    ema_mid = _safe_get(ctx_row, "ema_mid")
    ema_slow = _safe_get(ctx_row, "ema_slow")
    if np.isnan(ema_fast) or np.isnan(ema_mid) or np.isnan(ema_slow):
        return False

    # EMA alignment: fast > mid > slow
    if not (ema_fast > ema_mid > ema_slow):
        return False

    # Price above fast EMA
    close_val = _safe_get(ctx_row, "close")
    if np.isnan(close_val) or close_val < ema_fast:
        return False

    # ADX trending
    adx_val = _safe_get(ctx_row, "adx")
    if np.isnan(adx_val) or adx_val < params.adx_threshold_context:
        return False

    # Bullish direction
    di_plus = _safe_get(ctx_row, "di_plus")
    di_minus = _safe_get(ctx_row, "di_minus")
    if np.isnan(di_plus) or np.isnan(di_minus) or di_plus <= di_minus:
        return False

    return True


def get_context_signal_short(ctx_row, params):
    """Check Context TF (W1) SHORT conditions. Returns True if bearish trend."""
    ema_fast = _safe_get(ctx_row, "ema_fast")
    ema_mid = _safe_get(ctx_row, "ema_mid")
    ema_slow = _safe_get(ctx_row, "ema_slow")
    if np.isnan(ema_fast) or np.isnan(ema_mid) or np.isnan(ema_slow):
        return False

    # EMA alignment: fast < mid < slow (bearish structure)
    if not (ema_fast < ema_mid < ema_slow):
        return False

    # Price below fast EMA
    close_val = _safe_get(ctx_row, "close")
    if np.isnan(close_val) or close_val > ema_fast:
        return False

    # ADX trending
    adx_val = _safe_get(ctx_row, "adx")
    if np.isnan(adx_val) or adx_val < params.adx_threshold_context:
        return False

    # Bearish direction: DI- > DI+
    di_plus = _safe_get(ctx_row, "di_plus")
    di_minus = _safe_get(ctx_row, "di_minus")
    if np.isnan(di_plus) or np.isnan(di_minus) or di_minus <= di_plus:
        return False

    return True


def get_validation_signal_long(val_row, params):
    """Check Validation TF (D1) LONG conditions. Returns True if pullback detected."""
    ema_fast = _safe_get(val_row, "ema_fast")
    ema_mid = _safe_get(val_row, "ema_mid")
    ema_slow = _safe_get(val_row, "ema_slow")
    atr_val = _safe_get(val_row, "atr")
    close_val = _safe_get(val_row, "close")

    if np.isnan(ema_fast) or np.isnan(ema_slow) or np.isnan(atr_val):
        return False

    # EMA structure still bullish
    if ema_fast <= ema_slow:
        return False

    # Pullback zone detection
    atr_buffer = atr_val * params.pb_atr_buffer
    in_pullback = False

    if not np.isnan(ema_mid):
        # Zone A: Between fast and mid EMA
        if close_val >= ema_mid and close_val <= ema_fast + atr_buffer:
            in_pullback = True

    # Zone B: Near fast EMA
    if ema_fast - atr_buffer <= close_val <= ema_fast + atr_buffer:
        in_pullback = True

    if not in_pullback:
        return False

    # ADX still trending
    adx_val2 = _safe_get(val_row, "adx")
    if np.isnan(adx_val2) or adx_val2 < params.adx_threshold_validation:
        return False

    # BB Squeeze
    bbw_pctile = _safe_get(val_row, "bbw_pctile")
    if np.isnan(bbw_pctile) or bbw_pctile != 1.0:
        return False

    return True


def get_validation_signal_short(val_row, params):
    """Check Validation TF (D1) SHORT conditions. Returns True if bearish pullback."""
    ema_fast = _safe_get(val_row, "ema_fast")
    ema_mid = _safe_get(val_row, "ema_mid")
    ema_slow = _safe_get(val_row, "ema_slow")
    atr_val = _safe_get(val_row, "atr")
    close_val = _safe_get(val_row, "close")

    if np.isnan(ema_fast) or np.isnan(ema_slow) or np.isnan(atr_val):
        return False

    # EMA structure still bearish
    if ema_fast >= ema_slow:
        return False

    # Pullback zone detection (price rallied back toward EMAs from below)
    atr_buffer = atr_val * params.pb_atr_buffer
    in_pullback = False

    if not np.isnan(ema_mid):
        # Zone A: Between mid and fast EMA (price came up from below)
        if close_val <= ema_mid and close_val >= ema_fast - atr_buffer:
            in_pullback = True

    # Zone B: Near fast EMA (from below)
    if ema_fast - atr_buffer <= close_val <= ema_fast + atr_buffer:
        in_pullback = True

    if not in_pullback:
        return False

    # ADX still trending
    adx_val2 = _safe_get(val_row, "adx")
    if np.isnan(adx_val2) or adx_val2 < params.adx_threshold_validation:
        return False

    # BB Squeeze
    bbw_pctile = _safe_get(val_row, "bbw_pctile")
    if np.isnan(bbw_pctile) or bbw_pctile != 1.0:
        return False

    return True


def get_entry_signal_long(entry_df, bar_idx, params):
    """Check Entry TF (H4) LONG conditions at bar_idx."""
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

    # Price above fast EMA
    if close < ema_fast:
        return False

    # DI+ > DI-
    if np.isnan(di_plus) or np.isnan(di_minus) or di_plus <= di_minus:
        return False

    # Donchian breakout: current close > previous Donchian upper
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

    # Bullish bar
    if params.require_bullish_bar and close <= open_p:
        return False

    return True


def get_entry_signal_short(entry_df, bar_idx, params):
    """Check Entry TF (H4) SHORT conditions at bar_idx."""
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

    # Price below fast EMA
    if close > ema_fast:
        return False

    # DI- > DI+ (bearish momentum)
    if np.isnan(di_plus) or np.isnan(di_minus) or di_minus <= di_plus:
        return False

    # Donchian breakout DOWN: current close < previous Donchian lower
    lookback_start = bar_idx - params.donchian_period - 1
    lookback_end = bar_idx - 1
    if lookback_start < 0:
        return False

    donchian_lower = entry_df.iloc[lookback_start:lookback_end]["low"].min()
    if close >= donchian_lower:
        return False

    # Volume confirmation
    if vol > 0 and not np.isnan(vol_ma) and vol_ma > 0:
        if vol < vol_ma * params.volume_multiplier:
            return False

    # Bearish bar (optional)
    if params.require_bullish_bar and close >= open_p:
        return False

    return True


# ============================================================
# FIND MATCHING HIGHER-TF BAR
# ============================================================
def find_htf_bar(htf_df, entry_time):
    """Find the most recent completed bar on higher timeframe before entry_time."""
    mask = htf_df.index <= entry_time
    if mask.sum() == 0:
        return None
    idx = htf_df.index[mask][-1]
    result = htf_df.loc[idx]
    # If duplicate index, take last row
    if isinstance(result, pd.DataFrame):
        result = result.iloc[-1]
    return result


# ============================================================
# BACKTESTER ENGINE v3.0
# ============================================================
class Backtester:
    def __init__(self, params=None, initial_capital=100000.0):
        self.params = params or StrategyParams()
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.trades = []
        self.open_trades = []
        self.equity_curve = []
        self._equity_values = []  # for equity curve filter
        self._cooldown_until = {}  # symbol -> bar_idx cooldown

    def run(self, symbol, context_df, validation_df, entry_df):
        """Run backtest for a single symbol."""
        p = self.params

        # Add indicators to all timeframes
        ctx = add_indicators(context_df, p)
        val = add_indicators(validation_df, p)
        ent = add_indicators(entry_df, p)

        # Minimum bars needed
        min_bars = max(p.ema_slow, p.bbw_lookback + p.bb_period, p.donchian_period + 5)
        if len(ent) < min_bars:
            print(f"    Not enough entry bars ({len(ent)} < {min_bars})")
            return

        print(f"    Running backtest: {len(ent)} entry bars, "
              f"{len(val)} validation bars, {len(ctx)} context bars")

        # Iterate through entry timeframe bars
        for i in range(min_bars, len(ent)):
            current_time = ent.index[i]
            current_row = ent.iloc[i]

            # Record equity
            equity = self._calc_equity(current_row["close"], current_row.get("close", 0))
            self.equity_curve.append({
                "time": current_time,
                "equity": equity,
                "capital": self.capital
            })
            self._equity_values.append(equity)

            # --- Manage open trades ---
            self._manage_trades(ent, i)

            # --- Check for new entry ---
            if len(self.open_trades) >= p.max_positions:
                continue

            # Cooldown check
            cooldown_end = self._cooldown_until.get(symbol, 0)
            if i < cooldown_end:
                continue

            # Equity curve filter
            if p.equity_filter_enabled and len(self._equity_values) > p.equity_filter_period:
                eq_arr = np.array(self._equity_values[-p.equity_filter_period:])
                eq_ema = eq_arr.mean()  # Simple MA of equity
                if self._equity_values[-1] < eq_ema:
                    continue  # Skip trading when equity is below its MA

            # Get higher TF signals
            ctx_row = find_htf_bar(ctx, current_time)
            val_row = find_htf_bar(val, current_time)

            if ctx_row is None or val_row is None:
                continue

            # Check LONG conditions
            if p.direction in ('long', 'both'):
                if (get_context_signal_long(ctx_row, p) and
                    get_validation_signal_long(val_row, p) and
                    get_entry_signal_long(ent, i, p)):
                    self._open_trade(symbol, 'long', ent, i)
                    continue  # One entry per bar

            # Check SHORT conditions
            if p.direction in ('short', 'both'):
                if (get_context_signal_short(ctx_row, p) and
                    get_validation_signal_short(val_row, p) and
                    get_entry_signal_short(ent, i, p)):
                    self._open_trade(symbol, 'short', ent, i)

        # Close any remaining open trades at last bar
        for t in list(self.open_trades):
            last_row = ent.iloc[-1]
            self._close_trade(t, ent.index[-1], last_row["close"], "end_of_data")

        return self.trades

    def _open_trade(self, symbol, direction, entry_df, bar_idx):
        """Open a new trade (long or short)."""
        row = entry_df.iloc[bar_idx]
        p = self.params

        entry_price = row["close"]
        atr = row["atr"]

        if pd.isna(atr) or atr <= 0 or entry_price <= 0:
            return

        # Slippage (adverse direction)
        slippage = atr * p.slippage_atr_frac
        if direction == 'long':
            entry_price += slippage
        else:
            entry_price -= slippage

        # Stop loss: ATR-based
        if direction == 'long':
            sl_price = entry_price - atr * p.atr_sl_multiplier

            # Check swing low (Donchian lower)
            lookback_start = max(0, bar_idx - p.donchian_period)
            swing_low = entry_df.iloc[lookback_start:bar_idx]["low"].min()
            if swing_low > sl_price and swing_low < entry_price:
                sl_price = swing_low - entry_price * 0.001
        else:
            sl_price = entry_price + atr * p.atr_sl_multiplier

            # Check swing high (Donchian upper)
            lookback_start = max(0, bar_idx - p.donchian_period)
            swing_high = entry_df.iloc[lookback_start:bar_idx]["high"].max()
            if swing_high < sl_price and swing_high > entry_price:
                sl_price = swing_high + entry_price * 0.001

        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            return

        # Position size for 1% risk
        risk_amount = self.capital * p.risk_percent / 100.0
        lot_size = risk_amount / sl_distance

        # Commission
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
        )

        self.open_trades.append(trade)
        self.capital -= commission

    def _manage_trades(self, entry_df, bar_idx):
        """Manage open trades: SL check, BE, partial TP, trailing."""
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

        # Check stop loss hit
        if current_low <= trade.sl_price:
            exit_price = trade.sl_price
            reason = "stop_loss"
            if trade.be_applied and abs(trade.sl_price - trade.entry_price) < atr * 0.1:
                reason = "breakeven"
            self._close_trade(trade, entry_df.index[bar_idx], exit_price, reason)
            return

        # Update high since entry
        if current_high > trade.high_since_entry:
            trade.high_since_entry = current_high

        current_profit = current_close - trade.entry_price
        current_rr = current_profit / initial_risk_price if initial_risk_price > 0 else 0

        # --- Partial profit-taking ---
        if (p.partial_tp_enabled and not trade.partial_tp_taken and
                current_rr >= p.partial_tp_rr):
            partial_lots = trade.lot_size * p.partial_tp_fraction
            partial_pnl = (current_close - trade.entry_price) * partial_lots
            commission = current_close * partial_lots * p.commission
            partial_pnl -= commission
            self.capital += partial_pnl
            trade.partial_tp_pnl = partial_pnl
            trade.lot_size -= partial_lots
            trade.partial_tp_taken = True

        # --- Breakeven logic ---
        if not trade.be_applied:
            apply_be = False

            if p.be_mode == 'rr':
                apply_be = (current_rr >= p.be_rr_ratio)
            else:  # pullback breakout
                if trade.high_since_entry - trade.entry_price >= initial_risk_price * 0.5:
                    if bar_idx >= 5:
                        mini_donchian_upper = entry_df.iloc[bar_idx-5:bar_idx-1]["high"].max()
                        if current_close > mini_donchian_upper:
                            apply_be = True

            if apply_be:
                trade.sl_price = trade.entry_price + initial_risk_price * 0.01
                trade.be_applied = True

        # --- Trailing stop logic ---
        if current_rr >= p.trail_start_rr:
            trade.trailing_active = True

        if trade.trailing_active and atr > 0:
            trail_distance = atr * p.atr_trail_multiplier
            trail_sl = trade.high_since_entry - trail_distance

            if trail_sl > trade.sl_price and trail_sl < current_close:
                trade.sl_price = trail_sl

    def _manage_short_trade(self, trade, entry_df, bar_idx, current_low, current_high,
                            current_close, atr, initial_risk_price):
        p = self.params

        # Check stop loss hit (for shorts, SL is above entry)
        if current_high >= trade.sl_price:
            exit_price = trade.sl_price
            reason = "stop_loss"
            if trade.be_applied and abs(trade.sl_price - trade.entry_price) < atr * 0.1:
                reason = "breakeven"
            self._close_trade(trade, entry_df.index[bar_idx], exit_price, reason)
            return

        # Update low since entry (best price for short)
        if current_low < trade.low_since_entry:
            trade.low_since_entry = current_low

        current_profit = trade.entry_price - current_close  # Profit when price goes down
        current_rr = current_profit / initial_risk_price if initial_risk_price > 0 else 0

        # --- Partial profit-taking ---
        if (p.partial_tp_enabled and not trade.partial_tp_taken and
                current_rr >= p.partial_tp_rr):
            partial_lots = trade.lot_size * p.partial_tp_fraction
            partial_pnl = (trade.entry_price - current_close) * partial_lots
            commission = current_close * partial_lots * p.commission
            partial_pnl -= commission
            self.capital += partial_pnl
            trade.partial_tp_pnl = partial_pnl
            trade.lot_size -= partial_lots
            trade.partial_tp_taken = True

        # --- Breakeven logic ---
        if not trade.be_applied:
            apply_be = False

            if p.be_mode == 'rr':
                apply_be = (current_rr >= p.be_rr_ratio)
            else:  # pullback breakout
                if trade.entry_price - trade.low_since_entry >= initial_risk_price * 0.5:
                    if bar_idx >= 5:
                        mini_donchian_lower = entry_df.iloc[bar_idx-5:bar_idx-1]["low"].min()
                        if current_close < mini_donchian_lower:
                            apply_be = True

            if apply_be:
                trade.sl_price = trade.entry_price - initial_risk_price * 0.01
                trade.be_applied = True

        # --- Trailing stop logic ---
        if current_rr >= p.trail_start_rr:
            trade.trailing_active = True

        if trade.trailing_active and atr > 0:
            trail_distance = atr * p.atr_trail_multiplier
            trail_sl = trade.low_since_entry + trail_distance

            if trail_sl < trade.sl_price and trail_sl > current_close:
                trade.sl_price = trail_sl

    def _close_trade(self, trade, exit_time, exit_price, reason):
        """Close a trade and record results."""
        p = self.params

        # Slippage on exit
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

        # Commission
        commission = exit_price * trade.lot_size * p.commission
        remaining_pnl -= commission

        # Total pnl = partial TP profit + remaining position profit
        pnl = trade.partial_tp_pnl + remaining_pnl

        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.rr_achieved = rr
        trade.exit_reason = reason

        self.capital += remaining_pnl  # Only add remaining, partial was already added
        self.trades.append(trade)

        if trade in self.open_trades:
            self.open_trades.remove(trade)

        # Apply cooldown on loss
        if pnl < 0 and p.cooldown_bars > 0:
            # We don't have direct access to bar_idx here, so use trade count
            pass

    def _calc_equity(self, current_price_long, current_price_short=None):
        """Calculate current equity including open positions."""
        if current_price_short is None:
            current_price_short = current_price_long

        equity = self.capital
        for t in self.open_trades:
            if t.direction == 'long':
                unrealized = (current_price_long - t.entry_price) * t.lot_size
            else:
                unrealized = (t.entry_price - current_price_short) * t.lot_size
            equity += unrealized
        return equity

    def get_results(self):
        """Calculate comprehensive backtest statistics."""
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
            "partial_tp_taken": t.partial_tp_taken,
            "partial_tp_pnl": t.partial_tp_pnl,
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

        # Profit factor
        gross_profit = winners["pnl"].sum() if len(winners) > 0 else 0
        gross_loss = abs(losers["pnl"].sum()) if len(losers) > 0 else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Max drawdown from equity curve
        max_dd = 0
        max_dd_pct = 0
        if self.equity_curve:
            eq_df = pd.DataFrame(self.equity_curve)
            peak = eq_df["equity"].expanding().max()
            drawdown = eq_df["equity"] - peak
            max_dd = drawdown.min()
            dd_pct = (drawdown / peak * 100)
            max_dd_pct = dd_pct.min()

        # Expectancy
        expectancy = (win_rate / 100 * avg_win + (1 - win_rate / 100) * avg_loss) if total_trades > 0 else 0

        # Exit reason breakdown
        exit_reasons = trades_df["exit_reason"].value_counts().to_dict()

        # Direction breakdown
        long_trades = trades_df[trades_df["direction"] == "long"]
        short_trades = trades_df[trades_df["direction"] == "short"]

        # Average holding time
        if "entry_time" in trades_df.columns and "exit_time" in trades_df.columns:
            hold_times = (trades_df["exit_time"] - trades_df["entry_time"]).dt.total_seconds() / 3600
            avg_hold_hours = hold_times.mean()
        else:
            avg_hold_hours = 0

        # Consecutive wins/losses
        is_win = (trades_df["pnl"] > 0).astype(int)
        max_consec_wins = max_consecutive(is_win, 1)
        max_consec_losses = max_consecutive(is_win, 0)

        # Partial TP stats
        partial_tp_count = trades_df["partial_tp_taken"].sum() if "partial_tp_taken" in trades_df.columns else 0

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
            "partial_tp_count": int(partial_tp_count),
        }

        # Long/Short breakdown
        if len(long_trades) > 0:
            long_wr = (long_trades["pnl"] > 0).mean() * 100
            long_pnl = long_trades["pnl"].sum()
            results["long_win_rate"] = round(long_wr, 2)
            results["long_pnl"] = round(long_pnl, 2)

        if len(short_trades) > 0:
            short_wr = (short_trades["pnl"] > 0).mean() * 100
            short_pnl = short_trades["pnl"].sum()
            results["short_win_rate"] = round(short_wr, 2)
            results["short_pnl"] = round(short_pnl, 2)

        return results, trades_df


def max_consecutive(series, value):
    """Find max consecutive occurrences of value in series."""
    groups = (series != value).cumsum()
    filtered = series[series == value]
    if filtered.empty:
        return 0
    return filtered.groupby(groups[series == value]).count().max()


# ============================================================
# MULTI-SYMBOL BACKTEST RUNNER
# ============================================================
def run_multi_symbol_backtest(symbols, params=None, initial_capital=100000.0,
                              data_dir=None):
    """Run backtest across multiple symbols."""
    if params is None:
        params = StrategyParams()

    if data_dir is None:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    bt = Backtester(params=params, initial_capital=initial_capital)
    symbols_tested = []

    for symbol in symbols:
        print(f"\n  Processing {symbol}...")

        data = load_symbol_data(symbol, data_dir)

        # Determine available timeframes
        ctx_df = data.get("W1")
        val_df = data.get("D1")
        entry_df = data.get("H4")
        if entry_df is None:
            entry_df = data.get("H2")
        if entry_df is None:
            entry_df = data.get("H1")

        # Resample if needed
        if ctx_df is None and val_df is not None:
            ctx_df = resample_to_weekly(val_df)
            print(f"    Resampled D1 -> W1: {len(ctx_df)} bars")

        if entry_df is None and val_df is not None:
            entry_df = val_df
            print(f"    Using D1 as entry TF (no intraday data)")

        if ctx_df is None or val_df is None or entry_df is None:
            print(f"    SKIP: Missing required timeframes for {symbol}")
            continue

        bt.run(symbol, ctx_df, val_df, entry_df)
        symbols_tested.append(symbol)

    print(f"\n  Symbols tested: {len(symbols_tested)}")
    return bt, symbols_tested


# ============================================================
# PRETTY PRINT RESULTS
# ============================================================
def print_results(results, title="BACKTEST RESULTS"):
    """Print formatted backtest results."""
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
    print(f"  Partial TPs:        {results.get('partial_tp_count', 0)}")

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
    print("  TREND-FOLLOW PULLBACK STRATEGY BACKTESTER v3.0")
    print("  Multi-Timeframe | Long + Short | Partial TP | Equity Filter")
    print("=" * 65)

    params = StrategyParams()

    # Run multi-symbol backtest
    bt, symbols_tested = run_multi_symbol_backtest(
        ALL_SYMBOLS,
        params=params,
        initial_capital=100000.0
    )

    # Get and print results
    result = bt.get_results()
    if isinstance(result, tuple):
        results, trades_df = result

        print_results(results)

        # Per-symbol breakdown
        print("\n  PER-SYMBOL BREAKDOWN:")
        print("-" * 65)
        for sym in symbols_tested:
            sym_trades = trades_df[trades_df["symbol"] == sym]
            if len(sym_trades) > 0:
                sym_pnl = sym_trades["pnl"].sum()
                sym_wr = (sym_trades["pnl"] > 0).mean() * 100
                sym_rr = sym_trades["rr"].mean()
                n_long = len(sym_trades[sym_trades["direction"] == "long"])
                n_short = len(sym_trades[sym_trades["direction"] == "short"])
                print(f"  {sym:8s}: {len(sym_trades):3d} trades (L:{n_long} S:{n_short}) | "
                      f"WR: {sym_wr:5.1f}% | Avg RR: {sym_rr:+5.2f} | "
                      f"P&L: ${sym_pnl:>10,.2f}")

        # Save results
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
        os.makedirs(results_dir, exist_ok=True)

        trades_df.to_csv(os.path.join(results_dir, "trades.csv"), index=False)
        with open(os.path.join(results_dir, "results.json"), "w") as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n  Results saved to: {results_dir}")
    else:
        print(f"\n  {result}")


if __name__ == "__main__":
    main()
