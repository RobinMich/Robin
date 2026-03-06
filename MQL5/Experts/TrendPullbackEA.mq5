//+------------------------------------------------------------------+
//|                                          TrendPullbackEA.mq5     |
//|    Multi-Strategy Profit-Maximized EA v5.0 - All Presets Opt     |
//|    Progressive Trailing + Asset Presets + 3-Tier TP               |
//+------------------------------------------------------------------+
//| STRATEGY OVERVIEW v5.0:                                          |
//| - Multi-Strategy Engine: Trend Pullback + Momentum Scoring       |
//| - 3 Timeframes: Context / Validation / Entry (asset-specific)    |
//| - 3 Optimized Presets: XAUUSD, Indices, Stocks                   |
//|                                                                   |
//| KEY v5.0 IMPROVEMENTS (over v4.3):                               |
//| 1. XAUUSD preset fully optimized: SL3.5x, BE2.5R, TP2.5/5R     |
//|    PF 1.98, 40% WR, -14% DD (was PF 1.39)                       |
//| 2. Indices preset fully optimized: SL3.5x, Trail3.5x, TP2.5/5R  |
//|    PF 2.61, 40% WR, -11% DD (was PF ~1.5)                       |
//| 3. Stocks preset (v4.3): SL3.0x, Trail3.0x, TP2.5/5R            |
//|    PF 2.79, 54% WR, -21% DD, 25/26 symbols profitable           |
//|                                                                   |
//| XAUUSD PRESET (auto-detected):                                   |
//|   TF: W1/D1/H1 | EMA: 13/34/89 | ATR SL: 3.5x, Trail: 2.5x    |
//|   PB Buffer: 2.5x | Both directions | BE: 2.5R | TP: 2.5/5R    |
//|                                                                   |
//| INDICES PRESET (auto-detected):                                   |
//|   TF: D1/H4/H1 | EMA: 21/50/100 | ATR SL: 3.5x, Trail: 3.5x   |
//|   PB Buffer: 2.0x | Both directions | BE: 2.0R | TP: 2.5/5R    |
//|                                                                   |
//| STOCKS PRESET (auto-detected):                                    |
//|   TF: D1/H4/H1 | EMA: 21/50/100 | ATR SL: 3.0x, Trail: 3.0x   |
//|   PB Buffer: 3.0x | Long-Only | BE: 2.0R | TP: 2.5/5R           |
//+------------------------------------------------------------------+
#property copyright "TrendPullbackEA v5.0 - All Presets Optimized"
#property version   "5.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| ENUMS                                                             |
//+------------------------------------------------------------------+
enum ENUM_BE_MODE
{
   BE_MODE_RR_BASED    = 0,  // Move SL to BE at specified RR
   BE_MODE_PULLBACK_BO = 1   // Move SL to BE after mini-pullback breakout
};

enum ENUM_TRADE_DIRECTION
{
   TRADE_LONG_ONLY  = 0,  // Long Only
   TRADE_SHORT_ONLY = 1,  // Short Only
   TRADE_BOTH       = 2   // Both Long and Short
};

enum ENUM_ASSET_PRESET
{
   PRESET_AUTO    = 0,   // Auto-detect (recommended)
   PRESET_GOLD    = 1,   // XAUUSD optimized
   PRESET_STOCKS  = 2,   // US Stocks
   PRESET_INDICES = 3,   // US100/US500
   PRESET_CUSTOM  = 4    // Use manual settings below
};

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
// --- Asset Preset ---
input group "=== Asset Preset ==="
input ENUM_ASSET_PRESET InpPreset = PRESET_AUTO; // Asset Preset (Auto-detect recommended)

// --- Timeframes ---
input group "=== Timeframe Settings ==="
input ENUM_TIMEFRAMES InpContextTF     = PERIOD_W1;    // Context Timeframe
input ENUM_TIMEFRAMES InpValidationTF  = PERIOD_D1;    // Validation Timeframe
input ENUM_TIMEFRAMES InpEntryTF       = PERIOD_H4;    // Entry Timeframe

// --- Direction ---
input group "=== Trade Direction ==="
input ENUM_TRADE_DIRECTION InpDirection = TRADE_BOTH;   // Trading Direction

// --- EMA Settings ---
input group "=== EMA Settings ==="
input int    InpEMA_Fast   = 21;     // Fast EMA Period
input int    InpEMA_Mid    = 50;     // Mid EMA Period
input int    InpEMA_Slow   = 100;    // Slow EMA Period

// --- ADX/DMI Settings ---
input group "=== ADX/DMI Settings ==="
input int    InpADX_Period              = 14;    // ADX Period
input double InpADX_Threshold_Context   = 15.0;  // ADX Threshold Context TF
input double InpADX_Threshold_Validation = 10.0; // ADX Threshold Validation TF

// --- RSI Filter (NEW v4.0) ---
input group "=== RSI Filter (v4.0) ==="
input bool   InpRSI_Enabled       = true;   // Enable RSI Confluence Filter
input int    InpRSI_Period        = 14;     // RSI Period
input double InpRSI_OB_Level     = 70.0;   // RSI Overbought Level
input double InpRSI_OS_Level     = 30.0;   // RSI Oversold Level
input double InpRSI_Long_Max     = 65.0;   // Max RSI for Long Entry (avoid overbought)
input double InpRSI_Short_Min    = 35.0;   // Min RSI for Short Entry (avoid oversold)

// --- Supertrend Filter (NEW v4.0) ---
input group "=== Supertrend Filter (v4.0) ==="
input bool   InpSupertrend_Enabled = true;  // Enable Supertrend Confirmation
input int    InpST_Period          = 10;    // Supertrend ATR Period
input double InpST_Multiplier     = 2.0;   // Supertrend ATR Multiplier

// --- Session Filter for XAUUSD (NEW v4.0) ---
input group "=== Session Filter (v4.0) ==="
input bool   InpSession_Enabled     = false;   // Enable Session Filter (for gold/forex)
input int    InpSession_London_Start = 7;     // London Session Start Hour (UTC)
input int    InpSession_London_End   = 11;    // London Session End Hour (UTC)
input int    InpSession_NY_Start     = 13;    // NY Session Start Hour (UTC)
input int    InpSession_NY_End       = 17;    // NY Session End Hour (UTC)

// --- ATR Settings ---
input group "=== ATR Settings ==="
input int    InpATR_Period         = 14;    // ATR Period
input double InpATR_SL_Multiplier  = 1.5;   // ATR Stop Loss Multiplier
input double InpATR_Trail_Multi    = 2.0;   // ATR Trailing Stop Multiplier

// --- Bollinger Bands Squeeze ---
input group "=== BB Squeeze Settings ==="
input int    InpBB_Period          = 20;     // BB Period
input double InpBB_Deviation      = 2.0;    // BB Deviation
input int    InpBBW_Lookback      = 50;     // BBW Squeeze Lookback
input double InpBBW_Squeeze_Pctile = 50.0;  // BBW Squeeze Percentile

// --- Donchian Channel ---
input group "=== Donchian Channel Settings ==="
input int    InpDonchian_Period    = 12;     // Donchian Period
input int    InpDonchian_PB_Period = 5;      // Mini Pullback Donchian

// --- Volume Filter ---
input group "=== Volume Filter ==="
input int    InpVolume_Period      = 20;     // Volume MA Period
input double InpVolume_Multiplier  = 1.0;    // Volume Breakout Multiplier

// --- Risk Management ---
input group "=== Risk Management ==="
input double InpRisk_Percent       = 1.0;    // Base Risk % Per Trade
input ENUM_BE_MODE InpBE_Mode      = BE_MODE_PULLBACK_BO; // Breakeven Mode
input double InpBE_RR_Ratio        = 2.0;    // RR Ratio for BE (v5.0: 2.0-2.5)
input double InpTrail_Start_RR     = 1.5;    // RR Ratio to Start Trailing
input int    InpMax_Positions      = 5;      // Max Concurrent Positions
input int    InpMagicNumber        = 20250305; // Magic Number
input double InpMaxSpreadATR       = 0.3;    // Max Spread as % of ATR

// --- 3-Tier Partial Profit Taking (v4.0) ---
input group "=== 3-Tier Profit Taking (v4.0) ==="
input bool   InpPartialTP_Enabled  = true;   // Enable Partial TP
input double InpTP1_Fraction       = 0.4;    // Tier 1: Fraction to close (40%)
input double InpTP1_RR             = 2.5;    // Tier 1: RR level (v5.0: 2.5:1)
input double InpTP2_Fraction       = 0.3;    // Tier 2: Fraction to close (30%)
input double InpTP2_RR             = 5.0;    // Tier 2: RR level (v5.0: 5:1)
// Remaining 30% trails with Chandelier Exit

// --- Dynamic Risk Scaling (v4.0) ---
input group "=== Dynamic Risk (v4.0) ==="
input bool   InpDynRisk_Enabled    = true;   // Enable Dynamic Risk Scaling
input double InpDynRisk_MaxMulti   = 1.5;    // Max risk multiplier (equity growing)
input double InpDynRisk_MinMulti   = 0.5;    // Min risk multiplier (in drawdown)
input double InpDD_Reduce_Start    = 10.0;   // Start reducing risk at this DD%
input double InpDD_Reduce_Full     = 25.0;   // Full reduction at this DD%

// --- Scale-In to Winners (v4.0) ---
input group "=== Scale-In (v4.0) ==="
input bool   InpScaleIn_Enabled    = false;  // Enable Scale-In to Winners
input double InpScaleIn_RR         = 1.0;    // Add at this RR level
input double InpScaleIn_Fraction   = 0.5;    // Size as fraction of original

// --- Momentum Score (v4.0) ---
input group "=== Momentum Score (v4.0) ==="
input bool   InpMomScore_Enabled   = true;   // Enable Momentum Scoring
input int    InpMomScore_MinScore  = 60;     // Minimum score to trade (0-100)

// --- Equity Curve Filter ---
input group "=== Equity Filter ==="
input bool   InpEquityFilter       = true;   // Enable Equity Curve Filter
input int    InpEquityFilter_Period = 50;    // Equity MA Period

// --- Pullback Zone ---
input group "=== Pullback Zone ==="
input double InpPB_ATR_Buffer      = 1.2;    // ATR buffer above/below EMA zone
input bool   InpRequireBullishBar  = false;  // Require trend-aligned bar on entry TF

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                  |
//+------------------------------------------------------------------+
CTrade         trade;
CPositionInfo  posInfo;
CSymbolInfo    symInfo;

// Effective parameters (may be overridden by preset)
ENUM_TIMEFRAMES g_ContextTF;
ENUM_TIMEFRAMES g_ValidationTF;
ENUM_TIMEFRAMES g_EntryTF;
int    g_EMA_Fast, g_EMA_Mid, g_EMA_Slow;
double g_ADX_Threshold_Ctx, g_ADX_Threshold_Val;
double g_ATR_SL_Multi, g_ATR_Trail_Multi;
double g_BBW_Squeeze_Pctile;
int    g_Donchian_Period;
double g_PB_ATR_Buffer;
bool   g_SessionEnabled;
double g_RSI_Long_Max, g_RSI_Short_Min;
int    g_ST_Period;
double g_ST_Multiplier;
double g_BE_RR_Ratio;
double g_TP1_RR, g_TP2_RR;

// --- Indicator Handles: Context TF ---
int h_EMA_Fast_Ctx, h_EMA_Mid_Ctx, h_EMA_Slow_Ctx;
int h_ADX_Ctx, h_ATR_Ctx;

// --- Indicator Handles: Validation TF ---
int h_EMA_Fast_Val, h_EMA_Mid_Val, h_EMA_Slow_Val;
int h_ADX_Val, h_ATR_Val, h_BB_Val;
int h_RSI_Val;

// --- Indicator Handles: Entry TF ---
int h_EMA_Fast_Ent, h_EMA_Mid_Ent;
int h_ADX_Ent, h_ATR_Ent, h_BB_Ent;
int h_RSI_Ent;

// --- Supertrend state ---
double g_ST_Upper[], g_ST_Lower[];
bool   g_ST_IsUptrend[];

// --- Trade state tracking ---
struct TradeState
{
   ulong  ticket;
   int    direction;       // 0 = long, 1 = short
   double entryPrice;
   double initialSL;
   double initialTP_target;
   double highSinceEntry;
   double lowSinceEntry;
   double initialLotSize;
   double currentLotSize;
   bool   beApplied;
   bool   trailingActive;
   bool   tp1Taken;        // Tier 1 partial TP
   bool   tp2Taken;        // Tier 2 partial TP
   bool   scaleInDone;     // Scale-in added
   double tp1Pnl;
   double tp2Pnl;
   int    momScore;        // Entry momentum score
};

TradeState g_tradeStates[];
datetime   g_lastBarTime;

// Equity curve tracking
double g_equityHistory[];
int    g_equityCount;
double g_peakEquity;

// Win/loss streak tracking
int    g_consecutiveWins;
int    g_consecutiveLosses;
int    g_totalTradesForDay;

//+------------------------------------------------------------------+
//| Detect broker-supported order fill mode                           |
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING DetectFillMode(string symbol)
{
   // Query the broker's supported filling modes for this symbol
   long fillMode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);

   // Try FOK first (most common for market orders)
   if((fillMode & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      return ORDER_FILLING_FOK;

   // Try IOC next
   if((fillMode & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      return ORDER_FILLING_IOC;

   // Fallback: ORDER_FILLING_RETURN (exchange-style, always supported as last resort)
   return ORDER_FILLING_RETURN;
}

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(10);

   // Auto-detect broker's supported fill mode to avoid order fill errors
   ENUM_ORDER_TYPE_FILLING fillMode = DetectFillMode(_Symbol);
   trade.SetTypeFilling(fillMode);
   Print("Fill mode set to: ", EnumToString(fillMode));

   if(!symInfo.Name(_Symbol))
   {
      Print("Error initializing symbol info");
      return INIT_FAILED;
   }

   // Apply asset preset
   ApplyPreset();

   // --- Context TF Indicators ---
   h_EMA_Fast_Ctx = iMA(_Symbol, g_ContextTF, g_EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Mid_Ctx  = iMA(_Symbol, g_ContextTF, g_EMA_Mid,  0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Slow_Ctx = iMA(_Symbol, g_ContextTF, g_EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   h_ADX_Ctx      = iADX(_Symbol, g_ContextTF, InpADX_Period);
   h_ATR_Ctx      = iATR(_Symbol, g_ContextTF, InpATR_Period);

   // --- Validation TF Indicators ---
   h_EMA_Fast_Val = iMA(_Symbol, g_ValidationTF, g_EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Mid_Val  = iMA(_Symbol, g_ValidationTF, g_EMA_Mid,  0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Slow_Val = iMA(_Symbol, g_ValidationTF, g_EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   h_ADX_Val      = iADX(_Symbol, g_ValidationTF, InpADX_Period);
   h_ATR_Val      = iATR(_Symbol, g_ValidationTF, InpATR_Period);
   h_BB_Val       = iBands(_Symbol, g_ValidationTF, InpBB_Period, 0, InpBB_Deviation, PRICE_CLOSE);
   h_RSI_Val      = iRSI(_Symbol, g_ValidationTF, InpRSI_Period, PRICE_CLOSE);

   // --- Entry TF Indicators ---
   h_EMA_Fast_Ent = iMA(_Symbol, g_EntryTF, g_EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Mid_Ent  = iMA(_Symbol, g_EntryTF, g_EMA_Mid,  0, MODE_EMA, PRICE_CLOSE);
   h_ADX_Ent      = iADX(_Symbol, g_EntryTF, InpADX_Period);
   h_ATR_Ent      = iATR(_Symbol, g_EntryTF, InpATR_Period);
   h_BB_Ent       = iBands(_Symbol, g_EntryTF, InpBB_Period, 0, InpBB_Deviation, PRICE_CLOSE);
   h_RSI_Ent      = iRSI(_Symbol, g_EntryTF, InpRSI_Period, PRICE_CLOSE);

   // Validate handles
   if(h_EMA_Fast_Ctx == INVALID_HANDLE || h_EMA_Mid_Ctx == INVALID_HANDLE ||
      h_EMA_Slow_Ctx == INVALID_HANDLE || h_ADX_Ctx == INVALID_HANDLE ||
      h_ATR_Ctx == INVALID_HANDLE || h_EMA_Fast_Val == INVALID_HANDLE ||
      h_EMA_Mid_Val == INVALID_HANDLE || h_EMA_Slow_Val == INVALID_HANDLE ||
      h_ADX_Val == INVALID_HANDLE || h_ATR_Val == INVALID_HANDLE ||
      h_BB_Val == INVALID_HANDLE || h_RSI_Val == INVALID_HANDLE ||
      h_EMA_Fast_Ent == INVALID_HANDLE || h_EMA_Mid_Ent == INVALID_HANDLE ||
      h_ADX_Ent == INVALID_HANDLE || h_ATR_Ent == INVALID_HANDLE ||
      h_BB_Ent == INVALID_HANDLE || h_RSI_Ent == INVALID_HANDLE)
   {
      Print("Error creating indicator handles");
      return INIT_FAILED;
   }

   g_lastBarTime = 0;
   ArrayResize(g_tradeStates, 0);
   ArrayResize(g_equityHistory, 0);
   g_equityCount = 0;
   g_peakEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_consecutiveWins = 0;
   g_consecutiveLosses = 0;
   g_totalTradesForDay = 0;

   Print("TrendPullbackEA v5.0 ALL-PRESETS-OPTIMIZED initialized");
   Print("Preset: ", EnumToString(InpPreset));
   Print("Context TF: ", EnumToString(g_ContextTF),
         " | Validation TF: ", EnumToString(g_ValidationTF),
         " | Entry TF: ", EnumToString(g_EntryTF));
   Print("EMA: ", g_EMA_Fast, "/", g_EMA_Mid, "/", g_EMA_Slow);
   Print("RSI Filter: ", InpRSI_Enabled ? "ON" : "OFF",
         " | Supertrend: ", InpSupertrend_Enabled ? "ON" : "OFF",
         " | Session: ", g_SessionEnabled ? "ON" : "OFF");
   Print("3-Tier TP: ", InpPartialTP_Enabled ? "ON" : "OFF",
         " | Dynamic Risk: ", InpDynRisk_Enabled ? "ON" : "OFF",
         " | Mom Score: ", InpMomScore_Enabled ? "ON" : "OFF");
   Print("SL: ", g_ATR_SL_Multi, "x ATR | Trail: ", g_ATR_Trail_Multi,
         "x | BE: ", g_BE_RR_Ratio, "R | TP1: ", g_TP1_RR, "R | TP2: ", g_TP2_RR, "R");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Apply asset-specific preset                                       |
//+------------------------------------------------------------------+
void ApplyPreset()
{
   ENUM_ASSET_PRESET preset = InpPreset;

   // Auto-detect
   if(preset == PRESET_AUTO)
   {
      string sym = _Symbol;
      if(StringFind(sym, "XAU") >= 0 || StringFind(sym, "GOLD") >= 0)
         preset = PRESET_GOLD;
      else if(StringFind(sym, "US100") >= 0 || StringFind(sym, "US500") >= 0 ||
              StringFind(sym, "NAS") >= 0 || StringFind(sym, "SPX") >= 0)
         preset = PRESET_INDICES;
      else
         preset = PRESET_STOCKS;
   }

   switch(preset)
   {
      case PRESET_GOLD:
         g_ContextTF       = PERIOD_W1;
         g_ValidationTF    = PERIOD_D1;
         g_EntryTF         = PERIOD_H1;
         g_EMA_Fast        = 13;
         g_EMA_Mid         = 34;
         g_EMA_Slow        = 89;
         g_ADX_Threshold_Ctx = 10.0;
         g_ADX_Threshold_Val = 8.0;
         g_ATR_SL_Multi    = 3.5;   // v5.0: Very wide SL for gold volatility
         g_ATR_Trail_Multi = 2.5;
         g_BBW_Squeeze_Pctile = 60.0;
         g_Donchian_Period = 10;
         g_PB_ATR_Buffer   = 2.5;
         g_SessionEnabled  = false;
         g_RSI_Long_Max    = 78.0;
         g_RSI_Short_Min   = 22.0;
         g_ST_Period        = 10;
         g_ST_Multiplier    = 2.0;
         g_BE_RR_Ratio      = 2.5;   // v5.0: High BE protects on volatile reversals
         g_TP1_RR           = 2.5;   // v5.0: Higher TP1 for big R multiples
         g_TP2_RR           = 5.0;   // v5.0: Higher TP2 for runners
         Print("PRESET: XAUUSD (Gold) v5.0 - W1/D1/H1, SL3.5x, BE2.5R, TP2.5/5R");
         break;

      case PRESET_INDICES:
         g_ContextTF       = PERIOD_D1;
         g_ValidationTF    = PERIOD_H4;
         g_EntryTF         = PERIOD_H1;
         g_EMA_Fast        = 21;
         g_EMA_Mid         = 50;
         g_EMA_Slow        = 100;
         g_ADX_Threshold_Ctx = 12.0;
         g_ADX_Threshold_Val = 8.0;
         g_ATR_SL_Multi    = 3.5;   // v5.0: Very wide SL for index noise
         g_ATR_Trail_Multi = 3.5;   // v5.0: Very wide trail - let winners run
         g_BBW_Squeeze_Pctile = 60.0;
         g_Donchian_Period = 10;
         g_PB_ATR_Buffer   = 2.0;
         g_SessionEnabled  = false;
         g_RSI_Long_Max    = 78.0;
         g_RSI_Short_Min   = 22.0;
         g_ST_Period        = 12;
         g_ST_Multiplier    = 2.5;
         g_BE_RR_Ratio      = 2.0;   // v5.0: BE at 2R
         g_TP1_RR           = 2.5;   // v5.0: Higher TP1
         g_TP2_RR           = 5.0;   // v5.0: Higher TP2
         Print("PRESET: INDICES v5.0 - D1/H4/H1, SL3.5x, T3.5x, BE2.0R, TP2.5/5R");
         break;

      case PRESET_STOCKS:
         g_ContextTF       = PERIOD_D1;
         g_ValidationTF    = PERIOD_H4;
         g_EntryTF         = PERIOD_H1;
         g_EMA_Fast        = 21;
         g_EMA_Mid         = 50;
         g_EMA_Slow        = 100;
         g_ADX_Threshold_Ctx = 8.0;   // v4.3: Relaxed - catch moderate trends
         g_ADX_Threshold_Val = 5.0;   // v4.3: Relaxed
         g_ATR_SL_Multi    = 3.0;    // v4.3: Wide SL absorbs stock noise
         g_ATR_Trail_Multi = 3.0;    // v4.3: Wide trail lets winners run
         g_BBW_Squeeze_Pctile = 75.0; // v4.3: Relaxed
         g_Donchian_Period = 8;       // v4.3: Fast breakout detection
         g_PB_ATR_Buffer   = 3.0;    // v4.3: Wide pullback zone
         g_SessionEnabled  = false;
         g_RSI_Long_Max    = 85.0;   // v4.3: Don't cut momentum entries
         g_RSI_Short_Min   = 22.0;
         g_ST_Period        = 12;
         g_ST_Multiplier    = 2.5;
         g_BE_RR_Ratio      = 2.0;   // v4.3: BE at 2R
         g_TP1_RR           = 2.5;   // v4.3: Higher TP1
         g_TP2_RR           = 5.0;   // v4.3: Higher TP2
         Print("PRESET: STOCKS v4.3 - D1/H4/H1, SL3.0x, T3.0x, BE2.0R, TP2.5/5R");
         break;

      default: // PRESET_CUSTOM
         g_ContextTF       = InpContextTF;
         g_ValidationTF    = InpValidationTF;
         g_EntryTF         = InpEntryTF;
         g_EMA_Fast        = InpEMA_Fast;
         g_EMA_Mid         = InpEMA_Mid;
         g_EMA_Slow        = InpEMA_Slow;
         g_ADX_Threshold_Ctx = InpADX_Threshold_Context;
         g_ADX_Threshold_Val = InpADX_Threshold_Validation;
         g_ATR_SL_Multi    = InpATR_SL_Multiplier;
         g_ATR_Trail_Multi = InpATR_Trail_Multi;
         g_BBW_Squeeze_Pctile = InpBBW_Squeeze_Pctile;
         g_Donchian_Period = InpDonchian_Period;
         g_PB_ATR_Buffer   = InpPB_ATR_Buffer;
         g_SessionEnabled  = InpSession_Enabled;
         g_RSI_Long_Max    = InpRSI_Long_Max;
         g_RSI_Short_Min   = InpRSI_Short_Min;
         g_ST_Period        = InpST_Period;
         g_ST_Multiplier    = InpST_Multiplier;
         g_BE_RR_Ratio      = InpBE_RR_Ratio;
         g_TP1_RR           = InpTP1_RR;
         g_TP2_RR           = InpTP2_RR;
         Print("PRESET: CUSTOM");
         break;
   }
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                   |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(h_EMA_Fast_Ctx);
   IndicatorRelease(h_EMA_Mid_Ctx);
   IndicatorRelease(h_EMA_Slow_Ctx);
   IndicatorRelease(h_ADX_Ctx);
   IndicatorRelease(h_ATR_Ctx);

   IndicatorRelease(h_EMA_Fast_Val);
   IndicatorRelease(h_EMA_Mid_Val);
   IndicatorRelease(h_EMA_Slow_Val);
   IndicatorRelease(h_ADX_Val);
   IndicatorRelease(h_ATR_Val);
   IndicatorRelease(h_BB_Val);
   IndicatorRelease(h_RSI_Val);

   IndicatorRelease(h_EMA_Fast_Ent);
   IndicatorRelease(h_EMA_Mid_Ent);
   IndicatorRelease(h_ADX_Ent);
   IndicatorRelease(h_ATR_Ent);
   IndicatorRelease(h_BB_Ent);
   IndicatorRelease(h_RSI_Ent);

   Print("TrendPullbackEA v5.0 deinitialized");
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!IsNewBar(g_EntryTF))
      return;

   symInfo.RefreshRates();
   TrackEquity();

   // --- Manage existing positions ---
   ManageOpenPositions();

   // --- Check if we can open new positions ---
   if(CountOurPositions() >= InpMax_Positions)
      return;

   // --- Spread filter ---
   double atrEntry[];
   if(CopyBuffer(h_ATR_Ent, 0, 1, 1, atrEntry) < 1) return;
   double spread = symInfo.Ask() - symInfo.Bid();
   if(spread > atrEntry[0] * InpMaxSpreadATR)
      return;

   // --- Session filter ---
   if(g_SessionEnabled && !IsInTradingSession())
      return;

   // --- Equity curve filter ---
   if(InpEquityFilter && !PassesEquityFilter())
      return;

   // --- Calculate momentum score ---
   int momScore = 100;  // Default max if scoring disabled
   if(InpMomScore_Enabled)
   {
      momScore = CalculateMomentumScore();
      if(momScore < InpMomScore_MinScore)
         return;
   }

   // --- Check LONG entry conditions ---
   if(InpDirection == TRADE_LONG_ONLY || InpDirection == TRADE_BOTH)
   {
      if(CheckContextConditions(true) &&
         CheckValidationConditions(true) &&
         CheckEntryConditions(true) &&
         CheckRSIFilter(true) &&
         CheckSupertrendFilter(true))
      {
         ExecuteEntry(true, momScore);
         return;
      }
   }

   // --- Check SHORT entry conditions ---
   if(InpDirection == TRADE_SHORT_ONLY || InpDirection == TRADE_BOTH)
   {
      if(CheckContextConditions(false) &&
         CheckValidationConditions(false) &&
         CheckEntryConditions(false) &&
         CheckRSIFilter(false) &&
         CheckSupertrendFilter(false))
      {
         ExecuteEntry(false, momScore);
      }
   }
}

//+------------------------------------------------------------------+
//| SESSION FILTER - London & NY sessions                             |
//+------------------------------------------------------------------+
bool IsInTradingSession()
{
   MqlDateTime dt;
   TimeCurrent(dt);
   int hour = dt.hour;

   // London session
   if(hour >= InpSession_London_Start && hour <= InpSession_London_End)
      return true;

   // NY session
   if(hour >= InpSession_NY_Start && hour <= InpSession_NY_End)
      return true;

   return false;
}

//+------------------------------------------------------------------+
//| RSI FILTER - Avoid trading into overbought/oversold               |
//+------------------------------------------------------------------+
bool CheckRSIFilter(bool isLong)
{
   if(!InpRSI_Enabled)
      return true;

   double rsiEnt[];
   if(CopyBuffer(h_RSI_Ent, 0, 1, 1, rsiEnt) < 1) return true;

   if(isLong)
   {
      // Don't buy when already overbought
      if(rsiEnt[0] > g_RSI_Long_Max)
         return false;
      // Prefer buying when RSI shows room to run
      if(rsiEnt[0] < InpRSI_OS_Level)
         return false;  // Too oversold, trend might reverse
   }
   else
   {
      // Don't sell when already oversold
      if(rsiEnt[0] < g_RSI_Short_Min)
         return false;
      // Prefer selling when RSI shows room to fall
      if(rsiEnt[0] > InpRSI_OB_Level)
         return false;  // Too overbought, trend might reverse
   }

   return true;
}

//+------------------------------------------------------------------+
//| SUPERTREND FILTER                                                 |
//+------------------------------------------------------------------+
bool CheckSupertrendFilter(bool isLong)
{
   if(!InpSupertrend_Enabled)
      return true;

   // Calculate Supertrend manually using ATR
   double atrST[];
   double closeST[], highST[], lowST[];

   int barsNeeded = g_ST_Period + 5;
   if(CopyBuffer(h_ATR_Ent, 0, 1, barsNeeded, atrST) < barsNeeded) return true;
   if(CopyClose(_Symbol, g_EntryTF, 1, barsNeeded, closeST) < barsNeeded) return true;
   if(CopyHigh(_Symbol, g_EntryTF, 1, barsNeeded, highST) < barsNeeded) return true;
   if(CopyLow(_Symbol, g_EntryTF, 1, barsNeeded, lowST) < barsNeeded) return true;

   // Latest complete bar
   int last = barsNeeded - 1;
   int prev = barsNeeded - 2;

   double hl2_cur = (highST[last] + lowST[last]) / 2.0;
   double hl2_prev = (highST[prev] + lowST[prev]) / 2.0;

   double upperBand = hl2_cur + g_ST_Multiplier * atrST[last];
   double lowerBand = hl2_cur - g_ST_Multiplier * atrST[last];

   double upperBandPrev = hl2_prev + g_ST_Multiplier * atrST[prev];
   double lowerBandPrev = hl2_prev - g_ST_Multiplier * atrST[prev];

   // Simplified Supertrend logic
   bool isUptrend;
   if(closeST[prev] > upperBandPrev)
      isUptrend = true;
   else if(closeST[prev] < lowerBandPrev)
      isUptrend = false;
   else
      isUptrend = closeST[last] > (upperBand + lowerBand) / 2.0;

   if(isLong)
      return isUptrend;
   else
      return !isUptrend;
}

//+------------------------------------------------------------------+
//| MOMENTUM SCORE (0-100)                                            |
//| Combines ADX strength, RSI position, volume, price action         |
//+------------------------------------------------------------------+
int CalculateMomentumScore()
{
   int score = 0;

   // ADX strength (0-30 points)
   double adxEnt[];
   if(CopyBuffer(h_ADX_Ent, 0, 1, 1, adxEnt) >= 1)
   {
      if(adxEnt[0] >= 30) score += 30;
      else if(adxEnt[0] >= 25) score += 25;
      else if(adxEnt[0] >= 20) score += 20;
      else if(adxEnt[0] >= 15) score += 15;
      else score += 10;
   }

   // RSI position (0-25 points) - ideal range 40-60
   double rsiEnt[];
   if(CopyBuffer(h_RSI_Ent, 0, 1, 1, rsiEnt) >= 1)
   {
      double rsi = rsiEnt[0];
      if(rsi >= 40 && rsi <= 60) score += 25;       // Perfect zone
      else if(rsi >= 35 && rsi <= 65) score += 20;  // Good zone
      else if(rsi >= 30 && rsi <= 70) score += 15;  // Acceptable
      else score += 5;                               // Risky
   }

   // Volume confirmation (0-25 points)
   long volData[];
   if(CopyTickVolume(_Symbol, g_EntryTF, 1, InpVolume_Period + 1, volData) >= InpVolume_Period + 1)
   {
      long currentVol = volData[InpVolume_Period];
      double avgVol = 0;
      for(int i = 0; i < InpVolume_Period; i++)
         avgVol += (double)volData[i];
      avgVol /= InpVolume_Period;

      if(avgVol > 0)
      {
         double volRatio = (double)currentVol / avgVol;
         if(volRatio >= 2.0) score += 25;
         else if(volRatio >= 1.5) score += 20;
         else if(volRatio >= 1.2) score += 15;
         else if(volRatio >= 1.0) score += 10;
         else score += 5;
      }
   }

   // Price action quality (0-20 points) - strong candle body
   double closeEnt[], openEnt[], highEnt[], lowEnt[];
   if(CopyClose(_Symbol, g_EntryTF, 1, 1, closeEnt) >= 1 &&
      CopyOpen(_Symbol, g_EntryTF, 1, 1, openEnt) >= 1 &&
      CopyHigh(_Symbol, g_EntryTF, 1, 1, highEnt) >= 1 &&
      CopyLow(_Symbol, g_EntryTF, 1, 1, lowEnt) >= 1)
   {
      double body = MathAbs(closeEnt[0] - openEnt[0]);
      double range = highEnt[0] - lowEnt[0];
      if(range > 0)
      {
         double bodyRatio = body / range;
         if(bodyRatio >= 0.7) score += 20;       // Strong candle
         else if(bodyRatio >= 0.5) score += 15;  // Decent candle
         else if(bodyRatio >= 0.3) score += 10;  // Neutral
         else score += 5;                         // Weak/doji
      }
   }

   return score;
}

//+------------------------------------------------------------------+
//| DYNAMIC RISK - Adjust risk based on equity curve                  |
//+------------------------------------------------------------------+
double GetDynamicRisk()
{
   double baseRisk = InpRisk_Percent;

   if(!InpDynRisk_Enabled)
      return baseRisk;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);

   // Track peak equity
   if(equity > g_peakEquity)
      g_peakEquity = equity;

   // Calculate current drawdown
   double drawdownPct = 0;
   if(g_peakEquity > 0)
      drawdownPct = (g_peakEquity - equity) / g_peakEquity * 100.0;

   double riskMulti = 1.0;

   if(drawdownPct >= InpDD_Reduce_Full)
   {
      riskMulti = InpDynRisk_MinMulti;
   }
   else if(drawdownPct >= InpDD_Reduce_Start)
   {
      // Linear interpolation between max and min
      double ddRange = InpDD_Reduce_Full - InpDD_Reduce_Start;
      double ddProgress = (drawdownPct - InpDD_Reduce_Start) / ddRange;
      riskMulti = InpDynRisk_MaxMulti - ddProgress * (InpDynRisk_MaxMulti - InpDynRisk_MinMulti);
   }
   else
   {
      // Equity growing - can scale up slightly based on winning streak
      if(g_consecutiveWins >= 3)
         riskMulti = MathMin(InpDynRisk_MaxMulti, 1.0 + g_consecutiveWins * 0.1);
      else
         riskMulti = 1.0;
   }

   return baseRisk * riskMulti;
}

//+------------------------------------------------------------------+
//| CHECK CONTEXT CONDITIONS (Weekly/Daily)                           |
//+------------------------------------------------------------------+
bool CheckContextConditions(bool isLong)
{
   double emaFast[], emaMid[], emaSlow[];
   double adxMain[], diPlus[], diMinus[];

   if(CopyBuffer(h_EMA_Fast_Ctx, 0, 1, 1, emaFast) < 1) return false;
   if(CopyBuffer(h_EMA_Mid_Ctx,  0, 1, 1, emaMid)  < 1) return false;
   if(CopyBuffer(h_EMA_Slow_Ctx, 0, 1, 1, emaSlow) < 1) return false;
   if(CopyBuffer(h_ADX_Ctx, 0, 1, 1, adxMain)       < 1) return false;
   if(CopyBuffer(h_ADX_Ctx, 1, 1, 1, diPlus)         < 1) return false;
   if(CopyBuffer(h_ADX_Ctx, 2, 1, 1, diMinus)        < 1) return false;

   double closeCtx[];
   if(CopyClose(_Symbol, g_ContextTF, 1, 1, closeCtx) < 1) return false;

   if(adxMain[0] < g_ADX_Threshold_Ctx)
      return false;

   if(isLong)
   {
      if(!(emaFast[0] > emaMid[0] && emaMid[0] > emaSlow[0]))
         return false;
      if(closeCtx[0] < emaFast[0])
         return false;
      if(diPlus[0] <= diMinus[0])
         return false;
   }
   else
   {
      if(!(emaFast[0] < emaMid[0] && emaMid[0] < emaSlow[0]))
         return false;
      if(closeCtx[0] > emaFast[0])
         return false;
      if(diMinus[0] <= diPlus[0])
         return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| CHECK VALIDATION CONDITIONS (Daily/H4)                            |
//+------------------------------------------------------------------+
bool CheckValidationConditions(bool isLong)
{
   double emaFast[], emaMid[], emaSlow[];
   double adxMain[];
   double atrVal[];

   if(CopyBuffer(h_EMA_Fast_Val, 0, 1, 1, emaFast) < 1) return false;
   if(CopyBuffer(h_EMA_Mid_Val,  0, 1, 1, emaMid)  < 1) return false;
   if(CopyBuffer(h_EMA_Slow_Val, 0, 1, 1, emaSlow) < 1) return false;
   if(CopyBuffer(h_ADX_Val, 0, 1, 1, adxMain)       < 1) return false;
   if(CopyBuffer(h_ATR_Val, 0, 1, 1, atrVal)         < 1) return false;

   double closeVal[];
   if(CopyClose(_Symbol, g_ValidationTF, 1, 1, closeVal) < 1) return false;

   double atrBuffer = atrVal[0] * g_PB_ATR_Buffer;

   if(adxMain[0] < g_ADX_Threshold_Val)
      return false;

   if(!IsBBSqueeze(g_ValidationTF, h_BB_Val))
      return false;

   if(isLong)
   {
      if(emaFast[0] <= emaSlow[0])
         return false;

      bool inPullbackZone = false;
      if(closeVal[0] >= emaMid[0] && closeVal[0] <= emaFast[0] + atrBuffer)
         inPullbackZone = true;
      if(closeVal[0] >= emaFast[0] - atrBuffer && closeVal[0] <= emaFast[0] + atrBuffer)
         inPullbackZone = true;

      if(!inPullbackZone)
         return false;
   }
   else
   {
      if(emaFast[0] >= emaSlow[0])
         return false;

      bool inPullbackZone = false;
      if(closeVal[0] <= emaMid[0] && closeVal[0] >= emaFast[0] - atrBuffer)
         inPullbackZone = true;
      if(closeVal[0] >= emaFast[0] - atrBuffer && closeVal[0] <= emaFast[0] + atrBuffer)
         inPullbackZone = true;

      if(!inPullbackZone)
         return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| CHECK ENTRY CONDITIONS (H4/H1)                                    |
//+------------------------------------------------------------------+
bool CheckEntryConditions(bool isLong)
{
   double emaFast[];
   double adxMain[], diPlus[], diMinus[];

   if(CopyBuffer(h_EMA_Fast_Ent, 0, 1, 1, emaFast) < 1) return false;
   if(CopyBuffer(h_ADX_Ent, 0, 1, 1, adxMain)       < 1) return false;
   if(CopyBuffer(h_ADX_Ent, 1, 1, 1, diPlus)         < 1) return false;
   if(CopyBuffer(h_ADX_Ent, 2, 1, 1, diMinus)        < 1) return false;

   double closeEnt[], openEnt[];
   if(CopyClose(_Symbol, g_EntryTF, 1, 1, closeEnt) < 1) return false;
   if(CopyOpen(_Symbol, g_EntryTF, 1, 1, openEnt)   < 1) return false;

   if(isLong)
   {
      if(closeEnt[0] < emaFast[0])
         return false;
      if(diPlus[0] <= diMinus[0])
         return false;
      if(!IsDonchianBreakout(g_EntryTF, true))
         return false;
      if(InpRequireBullishBar && closeEnt[0] <= openEnt[0])
         return false;
   }
   else
   {
      if(closeEnt[0] > emaFast[0])
         return false;
      if(diMinus[0] <= diPlus[0])
         return false;
      if(!IsDonchianBreakout(g_EntryTF, false))
         return false;
      if(InpRequireBullishBar && closeEnt[0] >= openEnt[0])
         return false;
   }

   // Volume confirmation
   if(!IsVolumeConfirmed(g_EntryTF))
      return false;

   return true;
}

//+------------------------------------------------------------------+
//| BB SQUEEZE DETECTION                                              |
//+------------------------------------------------------------------+
bool IsBBSqueeze(ENUM_TIMEFRAMES tf, int bbHandle)
{
   int lookback = InpBBW_Lookback + 1;
   double bbUpper[], bbLower[], bbMid[];

   ArraySetAsSeries(bbUpper, true);
   ArraySetAsSeries(bbLower, true);
   ArraySetAsSeries(bbMid, true);

   if(CopyBuffer(bbHandle, 1, 1, lookback, bbUpper) < lookback) return false;
   if(CopyBuffer(bbHandle, 2, 1, lookback, bbLower) < lookback) return false;
   if(CopyBuffer(bbHandle, 0, 1, lookback, bbMid)   < lookback) return false;

   double bbwValues[];
   ArrayResize(bbwValues, lookback);
   for(int i = 0; i < lookback; i++)
   {
      if(bbMid[i] > 0)
         bbwValues[i] = (bbUpper[i] - bbLower[i]) / bbMid[i];
      else
         bbwValues[i] = 0;
   }

   double currentBBW = bbwValues[0];

   double sorted[];
   ArrayCopy(sorted, bbwValues);
   ArraySort(sorted);

   int percentileIndex = (int)MathFloor(lookback * g_BBW_Squeeze_Pctile / 100.0);
   if(percentileIndex >= lookback) percentileIndex = lookback - 1;

   double threshold = sorted[percentileIndex];

   return (currentBBW <= threshold);
}

//+------------------------------------------------------------------+
//| DONCHIAN BREAKOUT DETECTION                                       |
//+------------------------------------------------------------------+
bool IsDonchianBreakout(ENUM_TIMEFRAMES tf, bool isLong)
{
   double closeEnt[];
   if(CopyClose(_Symbol, tf, 1, 1, closeEnt) < 1) return false;

   if(isLong)
   {
      double highData[];
      if(CopyHigh(_Symbol, tf, 2, g_Donchian_Period, highData) < g_Donchian_Period) return false;
      double donchianUpper = highData[ArrayMaximum(highData)];
      return (closeEnt[0] > donchianUpper);
   }
   else
   {
      double lowData[];
      if(CopyLow(_Symbol, tf, 2, g_Donchian_Period, lowData) < g_Donchian_Period) return false;
      double donchianLower = lowData[ArrayMinimum(lowData)];
      return (closeEnt[0] < donchianLower);
   }
}

//+------------------------------------------------------------------+
//| VOLUME CONFIRMATION                                               |
//+------------------------------------------------------------------+
bool IsVolumeConfirmed(ENUM_TIMEFRAMES tf)
{
   long volData[];
   if(CopyTickVolume(_Symbol, tf, 1, InpVolume_Period + 1, volData) < InpVolume_Period + 1)
      return true;

   long currentVol = volData[InpVolume_Period];
   double avgVol = 0;
   for(int i = 0; i < InpVolume_Period; i++)
      avgVol += (double)volData[i];
   avgVol /= InpVolume_Period;

   if(avgVol <= 0)
      return true;

   return ((double)currentVol >= avgVol * InpVolume_Multiplier);
}

//+------------------------------------------------------------------+
//| EXECUTE ENTRY with Dynamic Risk and Momentum Score                |
//+------------------------------------------------------------------+
void ExecuteEntry(bool isLong, int momScore)
{
   symInfo.RefreshRates();
   double entryPrice = isLong ? symInfo.Ask() : symInfo.Bid();
   if(entryPrice <= 0) return;

   double atrEnt[];
   if(CopyBuffer(h_ATR_Ent, 0, 1, 1, atrEnt) < 1) return;

   // Calculate stop loss
   double slPrice;

   if(isLong)
   {
      slPrice = entryPrice - atrEnt[0] * g_ATR_SL_Multi;

      // Swing low verification
      double lowData[];
      if(CopyLow(_Symbol, g_EntryTF, 1, g_Donchian_Period, lowData) >= g_Donchian_Period)
      {
         double swingLow = lowData[ArrayMinimum(lowData)];
         if(swingLow < entryPrice && swingLow > slPrice)
            slPrice = swingLow - symInfo.Point() * 10;
      }
   }
   else
   {
      slPrice = entryPrice + atrEnt[0] * g_ATR_SL_Multi;

      double highData[];
      if(CopyHigh(_Symbol, g_EntryTF, 1, g_Donchian_Period, highData) >= g_Donchian_Period)
      {
         double swingHigh = highData[ArrayMaximum(highData)];
         if(swingHigh > entryPrice && swingHigh < slPrice)
            slPrice = swingHigh + symInfo.Point() * 10;
      }
   }

   double slDistance = MathAbs(entryPrice - slPrice);
   if(slDistance <= 0) return;

   slPrice = NormalizeDouble(slPrice, symInfo.Digits());

   // Dynamic risk calculation
   double riskPct = GetDynamicRisk();

   // Bonus risk for high momentum scores
   if(InpMomScore_Enabled && momScore >= 85)
      riskPct *= 1.2;  // 20% bonus for A+ setups

   double lotSize = CalculateLotSize(slDistance, riskPct);
   if(lotSize <= 0) return;

   double tp = 0;
   string comment = StringFormat("TPBv4|%s|M:%d|R:%.1f",
                                 isLong ? "L" : "S", momScore, riskPct);

   bool success;
   if(isLong)
      success = trade.Buy(lotSize, _Symbol, entryPrice, slPrice, tp, comment);
   else
      success = trade.Sell(lotSize, _Symbol, entryPrice, slPrice, tp, comment);

   if(success)
   {
      Print(isLong ? "BUY" : "SELL", " v4.0: Price=", entryPrice,
            " SL=", slPrice, " Lots=", lotSize,
            " Risk%=", riskPct, " MomScore=", momScore);

      TradeState state;
      state.ticket = trade.ResultOrder();
      state.direction = isLong ? 0 : 1;
      state.entryPrice = entryPrice;
      state.initialSL = slPrice;
      state.initialTP_target = isLong ?
         (entryPrice + slDistance * g_BE_RR_Ratio) :
         (entryPrice - slDistance * g_BE_RR_Ratio);
      state.highSinceEntry = entryPrice;
      state.lowSinceEntry = entryPrice;
      state.initialLotSize = lotSize;
      state.currentLotSize = lotSize;
      state.beApplied = false;
      state.trailingActive = false;
      state.tp1Taken = false;
      state.tp2Taken = false;
      state.scaleInDone = false;
      state.tp1Pnl = 0;
      state.tp2Pnl = 0;
      state.momScore = momScore;

      int size = ArraySize(g_tradeStates);
      ArrayResize(g_tradeStates, size + 1);
      g_tradeStates[size] = state;
   }
   else
   {
      Print("Order failed: ", trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| CALCULATE LOT SIZE with dynamic risk                              |
//+------------------------------------------------------------------+
double CalculateLotSize(double slDistancePrice, double riskPct)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount = balance * riskPct / 100.0;

   double tickSize = symInfo.TickSize();
   double tickValue = symInfo.TickValue();
   double lotStep = symInfo.LotsStep();
   double minLot = symInfo.LotsMin();
   double maxLot = symInfo.LotsMax();

   if(tickSize <= 0 || tickValue <= 0)
      return 0;

   double slTicks = slDistancePrice / tickSize;
   double lotSize = riskAmount / (slTicks * tickValue);

   lotSize = MathFloor(lotSize / lotStep) * lotStep;

   if(lotSize < minLot) lotSize = minLot;
   if(lotSize > maxLot) lotSize = maxLot;

   return NormalizeDouble(lotSize, 2);
}

//+------------------------------------------------------------------+
//| GET POINT VALUE                                                   |
//+------------------------------------------------------------------+
double GetPointValue()
{
   double tickValue = symInfo.TickValue();
   double tickSize  = symInfo.TickSize();
   double point     = symInfo.Point();
   if(tickSize <= 0) return 0;
   return tickValue * point / tickSize;
}

//+------------------------------------------------------------------+
//| MANAGE OPEN POSITIONS - 3-Tier TP + Chandelier Trail              |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   for(int i = ArraySize(g_tradeStates) - 1; i >= 0; i--)
   {
      ulong ticket = g_tradeStates[i].ticket;

      if(!PositionSelectByTicket(ticket))
      {
         // Position closed externally - track streak
         RemoveTradeState(i);
         continue;
      }

      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;

      bool isLong = (g_tradeStates[i].direction == 0);
      double currentPrice = isLong ? symInfo.Bid() : symInfo.Ask();
      double openPrice    = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL    = PositionGetDouble(POSITION_SL);
      double initialRisk  = MathAbs(g_tradeStates[i].entryPrice - g_tradeStates[i].initialSL);

      if(initialRisk <= 0) continue;

      // Update extremes
      if(currentPrice > g_tradeStates[i].highSinceEntry)
         g_tradeStates[i].highSinceEntry = currentPrice;
      if(currentPrice < g_tradeStates[i].lowSinceEntry)
         g_tradeStates[i].lowSinceEntry = currentPrice;

      double currentProfit, currentRR;
      if(isLong)
      {
         currentProfit = currentPrice - openPrice;
         currentRR = currentProfit / initialRisk;
      }
      else
      {
         currentProfit = openPrice - currentPrice;
         currentRR = currentProfit / initialRisk;
      }

      // === TIER 1 PARTIAL PROFIT TAKING ===
      if(InpPartialTP_Enabled && !g_tradeStates[i].tp1Taken && currentRR >= g_TP1_RR)
      {
         double currentLots = PositionGetDouble(POSITION_VOLUME);
         double closeLots = NormalizeDouble(g_tradeStates[i].initialLotSize * InpTP1_Fraction, 2);
         if(closeLots > currentLots) closeLots = currentLots;

         if(closeLots >= symInfo.LotsMin())
         {
            bool closeOk;
            if(isLong)
               closeOk = trade.Sell(closeLots, _Symbol, currentPrice, 0, 0, "TP1 40%");
            else
               closeOk = trade.Buy(closeLots, _Symbol, currentPrice, 0, 0, "TP1 40%");

            if(closeOk)
            {
               g_tradeStates[i].tp1Taken = true;
               g_tradeStates[i].currentLotSize -= closeLots;
               Print("TP1 (40%): Closed ", closeLots, " lots at RR=", NormalizeDouble(currentRR, 2));
            }
         }
      }

      // === TIER 2 PARTIAL PROFIT TAKING ===
      if(InpPartialTP_Enabled && g_tradeStates[i].tp1Taken &&
         !g_tradeStates[i].tp2Taken && currentRR >= g_TP2_RR)
      {
         double currentLots = PositionGetDouble(POSITION_VOLUME);
         double closeLots = NormalizeDouble(g_tradeStates[i].initialLotSize * InpTP2_Fraction, 2);
         if(closeLots > currentLots) closeLots = currentLots;

         if(closeLots >= symInfo.LotsMin())
         {
            bool closeOk;
            if(isLong)
               closeOk = trade.Sell(closeLots, _Symbol, currentPrice, 0, 0, "TP2 30%");
            else
               closeOk = trade.Buy(closeLots, _Symbol, currentPrice, 0, 0, "TP2 30%");

            if(closeOk)
            {
               g_tradeStates[i].tp2Taken = true;
               g_tradeStates[i].currentLotSize -= closeLots;
               Print("TP2 (30%): Closed ", closeLots, " lots at RR=", NormalizeDouble(currentRR, 2));
            }
         }
      }

      // === SCALE-IN TO WINNERS ===
      if(InpScaleIn_Enabled && !g_tradeStates[i].scaleInDone && currentRR >= InpScaleIn_RR)
      {
         double scaleInLots = NormalizeDouble(g_tradeStates[i].initialLotSize * InpScaleIn_Fraction, 2);
         if(scaleInLots >= symInfo.LotsMin())
         {
            // Set tight SL for scale-in (BE of original trade)
            double scaleInSL = isLong ?
               (openPrice + initialRisk * 0.1) :
               (openPrice - initialRisk * 0.1);
            scaleInSL = NormalizeDouble(scaleInSL, symInfo.Digits());

            bool scaleOk;
            if(isLong)
               scaleOk = trade.Buy(scaleInLots, _Symbol, currentPrice, scaleInSL, 0, "ScaleIn");
            else
               scaleOk = trade.Sell(scaleInLots, _Symbol, currentPrice, scaleInSL, 0, "ScaleIn");

            if(scaleOk)
            {
               g_tradeStates[i].scaleInDone = true;
               Print("Scale-In: Added ", scaleInLots, " lots at RR=", NormalizeDouble(currentRR, 2));
            }
         }
      }

      // === BREAKEVEN LOGIC ===
      if(!g_tradeStates[i].beApplied)
      {
         bool applyBE = false;

         if(InpBE_Mode == BE_MODE_RR_BASED)
         {
            applyBE = (currentRR >= g_BE_RR_Ratio);
         }
         else
         {
            if(isLong)
               applyBE = IsMiniPullbackBreakoutLong(openPrice, g_tradeStates[i].highSinceEntry);
            else
               applyBE = IsMiniPullbackBreakoutShort(openPrice, g_tradeStates[i].lowSinceEntry);
         }

         if(applyBE)
         {
            double newSL;
            if(isLong)
               newSL = openPrice + symInfo.Spread() * symInfo.Point();
            else
               newSL = openPrice - symInfo.Spread() * symInfo.Point();

            newSL = NormalizeDouble(newSL, symInfo.Digits());

            bool modifySL = isLong ? (newSL > currentSL) : (newSL < currentSL);
            if(modifySL)
            {
               if(trade.PositionModify(ticket, newSL, 0))
               {
                  g_tradeStates[i].beApplied = true;
                  Print("BE applied: Ticket=", ticket, " New SL=", newSL);
               }
            }
         }
      }

      // === CHANDELIER EXIT TRAILING STOP ===
      if(currentRR >= InpTrail_Start_RR)
         g_tradeStates[i].trailingActive = true;

      if(g_tradeStates[i].trailingActive)
      {
         double atrEnt[];
         if(CopyBuffer(h_ATR_Ent, 0, 1, 1, atrEnt) >= 1)
         {
            // Chandelier Exit: trail from highest high/lowest low
            double trailDistance = atrEnt[0] * g_ATR_Trail_Multi;

            // Progressive trail tightening based on profit level
            if(g_tradeStates[i].tp2Taken)
               trailDistance *= 0.65;  // Tight after TP2 (only 30% left)
            else if(g_tradeStates[i].tp1Taken)
               trailDistance *= 0.85;  // Slightly tighter after TP1

            // Extra tightening at high RR to lock in big winners
            if(currentRR >= 5.0)
               trailDistance *= 0.75;  // Very tight at 5R+
            else if(currentRR >= 3.0)
               trailDistance *= 0.85;  // Tight at 3R+

            double trailSL;

            if(isLong)
            {
               trailSL = g_tradeStates[i].highSinceEntry - trailDistance;
               trailSL = NormalizeDouble(trailSL, symInfo.Digits());

               if(trailSL > currentSL && trailSL < currentPrice)
               {
                  if(trade.PositionModify(ticket, trailSL, 0))
                  {
                     Print("Trail (Chandelier): Ticket=", ticket,
                           " SL=", trailSL, " High=", g_tradeStates[i].highSinceEntry);
                  }
               }
            }
            else
            {
               trailSL = g_tradeStates[i].lowSinceEntry + trailDistance;
               trailSL = NormalizeDouble(trailSL, symInfo.Digits());

               if(trailSL < currentSL && trailSL > currentPrice)
               {
                  if(trade.PositionModify(ticket, trailSL, 0))
                  {
                     Print("Trail (Chandelier): Ticket=", ticket,
                           " SL=", trailSL, " Low=", g_tradeStates[i].lowSinceEntry);
                  }
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| MINI PULLBACK BREAKOUT LONG (for BE Mode 2)                      |
//+------------------------------------------------------------------+
bool IsMiniPullbackBreakoutLong(double entryPrice, double highSinceEntry)
{
   double closeEnt[];
   double highData[];

   if(CopyClose(_Symbol, g_EntryTF, 1, 1, closeEnt) < 1) return false;

   double initialRisk = entryPrice - PositionGetDouble(POSITION_SL);
   if(initialRisk <= 0) return false;
   if(highSinceEntry - entryPrice < initialRisk * 0.5) return false;

   if(CopyHigh(_Symbol, g_EntryTF, 2, InpDonchian_PB_Period, highData) < InpDonchian_PB_Period)
      return false;

   double miniDonchianUpper = highData[ArrayMaximum(highData)];
   return (closeEnt[0] > miniDonchianUpper);
}

//+------------------------------------------------------------------+
//| MINI PULLBACK BREAKOUT SHORT (for BE Mode 2)                     |
//+------------------------------------------------------------------+
bool IsMiniPullbackBreakoutShort(double entryPrice, double lowSinceEntry)
{
   double closeEnt[];
   double lowData[];

   if(CopyClose(_Symbol, g_EntryTF, 1, 1, closeEnt) < 1) return false;

   double initialRisk = PositionGetDouble(POSITION_SL) - entryPrice;
   if(initialRisk <= 0) return false;
   if(entryPrice - lowSinceEntry < initialRisk * 0.5) return false;

   if(CopyLow(_Symbol, g_EntryTF, 2, InpDonchian_PB_Period, lowData) < InpDonchian_PB_Period)
      return false;

   double miniDonchianLower = lowData[ArrayMinimum(lowData)];
   return (closeEnt[0] < miniDonchianLower);
}

//+------------------------------------------------------------------+
//| EQUITY CURVE FILTER                                               |
//+------------------------------------------------------------------+
void TrackEquity()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_equityCount++;
   int size = ArraySize(g_equityHistory);
   ArrayResize(g_equityHistory, size + 1);
   g_equityHistory[size] = equity;

   if(equity > g_peakEquity)
      g_peakEquity = equity;
}

bool PassesEquityFilter()
{
   int size = ArraySize(g_equityHistory);
   if(size < InpEquityFilter_Period)
      return true;

   double sum = 0;
   for(int i = size - InpEquityFilter_Period; i < size; i++)
      sum += g_equityHistory[i];

   double equityMA = sum / InpEquityFilter_Period;
   return (g_equityHistory[size - 1] >= equityMA);
}

//+------------------------------------------------------------------+
//| HELPER FUNCTIONS                                                  |
//+------------------------------------------------------------------+
void RemoveTradeState(int index)
{
   int total = ArraySize(g_tradeStates);
   if(index < 0 || index >= total) return;

   for(int i = index; i < total - 1; i++)
      g_tradeStates[i] = g_tradeStates[i + 1];

   ArrayResize(g_tradeStates, total - 1);
}

int CountOurPositions()
{
   int count = 0;
   int total = PositionsTotal();

   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket <= 0) continue;

      if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         count++;
   }

   return count;
}

bool IsNewBar(ENUM_TIMEFRAMES tf)
{
   datetime currentBarTime = iTime(_Symbol, tf, 0);

   if(currentBarTime != g_lastBarTime)
   {
      g_lastBarTime = currentBarTime;
      return true;
   }

   return false;
}
//+------------------------------------------------------------------+
