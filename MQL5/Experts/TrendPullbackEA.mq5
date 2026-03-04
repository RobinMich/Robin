//+------------------------------------------------------------------+
//|                                          TrendPullbackEA.mq5     |
//|        Multi-Timeframe Trend Follow Pullback Strategy v3.0       |
//|        Long + Short | Partial TP | Equity Filter | 1% Risk       |
//+------------------------------------------------------------------+
//| STRATEGY OVERVIEW v3.0:                                          |
//| - 3 Timeframes: Context (W1), Validation (D1), Entry (H4)       |
//| - Bidirectional: Long in uptrends, Short in downtrends           |
//| - Trend direction via EMA alignment + ADX filter                 |
//| - Pullback detection via EMA zone + BB Squeeze                   |
//| - Entry via Donchian breakout + Volume confirmation              |
//| - Risk: 1% per trade, BE after pullback breakout (optimized)     |
//| - Partial profit-taking: close 50% at 2:1 RR                    |
//| - Trailing stop via ATR (2.0x) starting at 1.5 RR               |
//| - Equity curve filter: pause when equity < MA                    |
//|                                                                   |
//| BACKTEST RESULTS v3.0 (both directions, 28 symbols, ~2 years):  |
//|   Includes short selling + partial TP + equity filter             |
//|   Improved drawdown management and higher profit capture          |
//|                                                                   |
//| XAUUSD (Gold) - use these overrides on the XAUUSD chart:        |
//|   EMA: 13/34/89 | ADX: 10/8 | BBW: 60% | Donchian: 10          |
//|   PB Buffer: 2.0 ATR | Volume: 1.0 | BullishBar: false          |
//|   Trail Start: 1.2 RR | Max Pos: 3                              |
//+------------------------------------------------------------------+
#property copyright "TrendPullbackEA v3.0"
#property version   "3.00"
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

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
// --- Timeframes ---
input group "=== Timeframe Settings ==="
input ENUM_TIMEFRAMES InpContextTF     = PERIOD_W1;    // Context Timeframe (Trend Direction)
input ENUM_TIMEFRAMES InpValidationTF  = PERIOD_D1;    // Validation Timeframe (Pullback Detection)
input ENUM_TIMEFRAMES InpEntryTF       = PERIOD_H4;    // Entry Timeframe (Precise Entry)

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
input int    InpDonchian_PB_Period = 5;      // Mini Pullback Donchian (for BE mode 2)

// --- Volume Filter ---
input group "=== Volume Filter ==="
input int    InpVolume_Period      = 20;     // Volume MA Period
input double InpVolume_Multiplier  = 1.0;    // Volume Breakout Multiplier

// --- Risk Management ---
input group "=== Risk Management ==="
input double InpRisk_Percent       = 1.0;    // Risk % Per Trade
input ENUM_BE_MODE InpBE_Mode      = BE_MODE_PULLBACK_BO; // Breakeven Mode
input double InpBE_RR_Ratio        = 1.5;    // RR Ratio for BE (delayed to 1.5)
input double InpTrail_Start_RR     = 1.5;    // RR Ratio to Start Trailing
input int    InpMax_Positions      = 5;      // Max Concurrent Positions
input int    InpMagicNumber        = 20250301; // Magic Number
input double InpMaxSpreadATR       = 0.3;    // Max Spread as % of ATR

// --- Partial Profit Taking ---
input group "=== Partial Profit Taking ==="
input bool   InpPartialTP_Enabled  = true;   // Enable Partial TP
input double InpPartialTP_Fraction = 0.5;    // Fraction to close (0.5 = 50%)
input double InpPartialTP_RR       = 2.0;    // RR level for partial TP

// --- Equity Curve Filter ---
input group "=== Equity Filter ==="
input bool   InpEquityFilter       = true;   // Enable Equity Curve Filter
input int    InpEquityFilter_Period = 50;    // Equity MA Period (in bars)

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

// --- Indicator Handles: Context TF (W1) ---
int h_EMA_Fast_Ctx, h_EMA_Mid_Ctx, h_EMA_Slow_Ctx;
int h_ADX_Ctx;
int h_ATR_Ctx;

// --- Indicator Handles: Validation TF (D1) ---
int h_EMA_Fast_Val, h_EMA_Mid_Val, h_EMA_Slow_Val;
int h_ADX_Val;
int h_ATR_Val;
int h_BB_Val;

// --- Indicator Handles: Entry TF (H4) ---
int h_EMA_Fast_Ent, h_EMA_Mid_Ent;
int h_ADX_Ent;
int h_ATR_Ent;
int h_BB_Ent;

// --- State tracking for trades ---
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
   bool   beApplied;
   bool   trailingActive;
   bool   partialTPTaken;
};

TradeState g_tradeStates[];
datetime   g_lastBarTime;

// Equity curve tracking
double g_equityHistory[];
int    g_equityCount;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   // Initialize trade object
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(10);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   if(!symInfo.Name(_Symbol))
   {
      Print("Error initializing symbol info");
      return INIT_FAILED;
   }

   // --- Context TF Indicators ---
   h_EMA_Fast_Ctx = iMA(_Symbol, InpContextTF, InpEMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Mid_Ctx  = iMA(_Symbol, InpContextTF, InpEMA_Mid,  0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Slow_Ctx = iMA(_Symbol, InpContextTF, InpEMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   h_ADX_Ctx      = iADX(_Symbol, InpContextTF, InpADX_Period);
   h_ATR_Ctx      = iATR(_Symbol, InpContextTF, InpATR_Period);

   // --- Validation TF Indicators ---
   h_EMA_Fast_Val = iMA(_Symbol, InpValidationTF, InpEMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Mid_Val  = iMA(_Symbol, InpValidationTF, InpEMA_Mid,  0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Slow_Val = iMA(_Symbol, InpValidationTF, InpEMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   h_ADX_Val      = iADX(_Symbol, InpValidationTF, InpADX_Period);
   h_ATR_Val      = iATR(_Symbol, InpValidationTF, InpATR_Period);
   h_BB_Val       = iBands(_Symbol, InpValidationTF, InpBB_Period, 0, InpBB_Deviation, PRICE_CLOSE);

   // --- Entry TF Indicators ---
   h_EMA_Fast_Ent = iMA(_Symbol, InpEntryTF, InpEMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   h_EMA_Mid_Ent  = iMA(_Symbol, InpEntryTF, InpEMA_Mid,  0, MODE_EMA, PRICE_CLOSE);
   h_ADX_Ent      = iADX(_Symbol, InpEntryTF, InpADX_Period);
   h_ATR_Ent      = iATR(_Symbol, InpEntryTF, InpATR_Period);
   h_BB_Ent       = iBands(_Symbol, InpEntryTF, InpBB_Period, 0, InpBB_Deviation, PRICE_CLOSE);

   // Validate handles
   if(h_EMA_Fast_Ctx == INVALID_HANDLE || h_EMA_Mid_Ctx == INVALID_HANDLE ||
      h_EMA_Slow_Ctx == INVALID_HANDLE || h_ADX_Ctx == INVALID_HANDLE ||
      h_ATR_Ctx == INVALID_HANDLE || h_EMA_Fast_Val == INVALID_HANDLE ||
      h_EMA_Mid_Val == INVALID_HANDLE || h_EMA_Slow_Val == INVALID_HANDLE ||
      h_ADX_Val == INVALID_HANDLE || h_ATR_Val == INVALID_HANDLE ||
      h_BB_Val == INVALID_HANDLE || h_EMA_Fast_Ent == INVALID_HANDLE ||
      h_EMA_Mid_Ent == INVALID_HANDLE || h_ADX_Ent == INVALID_HANDLE ||
      h_ATR_Ent == INVALID_HANDLE || h_BB_Ent == INVALID_HANDLE)
   {
      Print("Error creating indicator handles");
      return INIT_FAILED;
   }

   g_lastBarTime = 0;
   ArrayResize(g_tradeStates, 0);
   ArrayResize(g_equityHistory, 0);
   g_equityCount = 0;

   Print("TrendPullbackEA v3.0 initialized successfully");
   Print("Context TF: ", EnumToString(InpContextTF),
         " | Validation TF: ", EnumToString(InpValidationTF),
         " | Entry TF: ", EnumToString(InpEntryTF));
   Print("Direction: ", EnumToString(InpDirection),
         " | Partial TP: ", InpPartialTP_Enabled ? "ON" : "OFF",
         " | Equity Filter: ", InpEquityFilter ? "ON" : "OFF");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                   |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // Release indicator handles
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

   IndicatorRelease(h_EMA_Fast_Ent);
   IndicatorRelease(h_EMA_Mid_Ent);
   IndicatorRelease(h_ADX_Ent);
   IndicatorRelease(h_ATR_Ent);
   IndicatorRelease(h_BB_Ent);

   Print("TrendPullbackEA v3.0 deinitialized");
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Only process on new bar of entry timeframe
   if(!IsNewBar(InpEntryTF))
      return;

   symInfo.RefreshRates();

   // Track equity for equity curve filter
   TrackEquity();

   // --- Manage existing positions first ---
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

   // --- Equity curve filter ---
   if(InpEquityFilter && !PassesEquityFilter())
      return;

   // --- Check LONG entry conditions ---
   if(InpDirection == TRADE_LONG_ONLY || InpDirection == TRADE_BOTH)
   {
      if(CheckContextConditions(true) &&
         CheckValidationConditions(true) &&
         CheckEntryConditions(true))
      {
         ExecuteEntry(true);  // Long
         return;  // One entry per bar
      }
   }

   // --- Check SHORT entry conditions ---
   if(InpDirection == TRADE_SHORT_ONLY || InpDirection == TRADE_BOTH)
   {
      if(CheckContextConditions(false) &&
         CheckValidationConditions(false) &&
         CheckEntryConditions(false))
      {
         ExecuteEntry(false);  // Short
      }
   }
}

//+------------------------------------------------------------------+
//| CHECK CONTEXT CONDITIONS (Weekly)                                 |
//| isLong=true: Bullish conditions                                   |
//| isLong=false: Bearish conditions                                  |
//+------------------------------------------------------------------+
bool CheckContextConditions(bool isLong)
{
   double emaFast[], emaMid[], emaSlow[];
   double adxMain[], diPlus[], diMinus[];

   // Copy last completed bar (shift 1)
   if(CopyBuffer(h_EMA_Fast_Ctx, 0, 1, 1, emaFast) < 1) return false;
   if(CopyBuffer(h_EMA_Mid_Ctx,  0, 1, 1, emaMid)  < 1) return false;
   if(CopyBuffer(h_EMA_Slow_Ctx, 0, 1, 1, emaSlow) < 1) return false;
   if(CopyBuffer(h_ADX_Ctx, 0, 1, 1, adxMain)       < 1) return false;
   if(CopyBuffer(h_ADX_Ctx, 1, 1, 1, diPlus)         < 1) return false;
   if(CopyBuffer(h_ADX_Ctx, 2, 1, 1, diMinus)        < 1) return false;

   // Get weekly close
   double closeCtx[];
   if(CopyClose(_Symbol, InpContextTF, 1, 1, closeCtx) < 1) return false;

   // ADX trending
   if(adxMain[0] < InpADX_Threshold_Context)
      return false;

   if(isLong)
   {
      // EMA alignment (bullish): fast > mid > slow
      if(!(emaFast[0] > emaMid[0] && emaMid[0] > emaSlow[0]))
         return false;

      // Price above fast EMA
      if(closeCtx[0] < emaFast[0])
         return false;

      // Bullish direction: DI+ > DI-
      if(diPlus[0] <= diMinus[0])
         return false;
   }
   else
   {
      // EMA alignment (bearish): fast < mid < slow
      if(!(emaFast[0] < emaMid[0] && emaMid[0] < emaSlow[0]))
         return false;

      // Price below fast EMA
      if(closeCtx[0] > emaFast[0])
         return false;

      // Bearish direction: DI- > DI+
      if(diMinus[0] <= diPlus[0])
         return false;
   }

   return true;
}

//+------------------------------------------------------------------+
//| CHECK VALIDATION CONDITIONS (Daily)                               |
//| isLong=true: Bullish pullback                                     |
//| isLong=false: Bearish pullback (rally into resistance)            |
//+------------------------------------------------------------------+
bool CheckValidationConditions(bool isLong)
{
   double emaFast[], emaMid[], emaSlow[];
   double adxMain[], diPlus[], diMinus[];
   double atrVal[];

   if(CopyBuffer(h_EMA_Fast_Val, 0, 1, 1, emaFast) < 1) return false;
   if(CopyBuffer(h_EMA_Mid_Val,  0, 1, 1, emaMid)  < 1) return false;
   if(CopyBuffer(h_EMA_Slow_Val, 0, 1, 1, emaSlow) < 1) return false;
   if(CopyBuffer(h_ADX_Val, 0, 1, 1, adxMain)       < 1) return false;
   if(CopyBuffer(h_ATR_Val, 0, 1, 1, atrVal)         < 1) return false;

   double closeVal[];
   if(CopyClose(_Symbol, InpValidationTF, 1, 1, closeVal) < 1) return false;

   double atrBuffer = atrVal[0] * InpPB_ATR_Buffer;

   // ADX still shows some trend
   if(adxMain[0] < InpADX_Threshold_Validation)
      return false;

   // BB Squeeze detection
   if(!IsBBSqueeze(InpValidationTF, h_BB_Val))
      return false;

   if(isLong)
   {
      // EMA structure still bullish on daily
      if(emaFast[0] <= emaSlow[0])
         return false;

      // Pullback zone: price between Fast and Mid EMA, or near Fast EMA
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
      // EMA structure still bearish on daily
      if(emaFast[0] >= emaSlow[0])
         return false;

      // Pullback zone: price rallied back toward EMAs from below
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
//| CHECK ENTRY CONDITIONS (H4)                                       |
//| isLong=true: Donchian breakout UP                                 |
//| isLong=false: Donchian breakout DOWN                              |
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
   if(CopyClose(_Symbol, InpEntryTF, 1, 1, closeEnt) < 1) return false;
   if(CopyOpen(_Symbol, InpEntryTF, 1, 1, openEnt)   < 1) return false;

   if(isLong)
   {
      // Price above fast EMA
      if(closeEnt[0] < emaFast[0])
         return false;

      // DI+ > DI-
      if(diPlus[0] <= diMinus[0])
         return false;

      // Donchian breakout UP
      if(!IsDonchianBreakout(InpEntryTF, true))
         return false;

      // Bullish bar (optional)
      if(InpRequireBullishBar && closeEnt[0] <= openEnt[0])
         return false;
   }
   else
   {
      // Price below fast EMA
      if(closeEnt[0] > emaFast[0])
         return false;

      // DI- > DI+
      if(diMinus[0] <= diPlus[0])
         return false;

      // Donchian breakout DOWN
      if(!IsDonchianBreakout(InpEntryTF, false))
         return false;

      // Bearish bar (optional)
      if(InpRequireBullishBar && closeEnt[0] >= openEnt[0])
         return false;
   }

   // Volume confirmation
   if(!IsVolumeConfirmed(InpEntryTF))
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

   int percentileIndex = (int)MathFloor(lookback * InpBBW_Squeeze_Pctile / 100.0);
   if(percentileIndex >= lookback) percentileIndex = lookback - 1;

   double threshold = sorted[percentileIndex];

   return (currentBBW <= threshold);
}

//+------------------------------------------------------------------+
//| DONCHIAN BREAKOUT DETECTION (Bidirectional)                       |
//+------------------------------------------------------------------+
bool IsDonchianBreakout(ENUM_TIMEFRAMES tf, bool isLong)
{
   double closeEnt[];

   if(CopyClose(_Symbol, tf, 1, 1, closeEnt) < 1) return false;

   if(isLong)
   {
      double highData[];
      if(CopyHigh(_Symbol, tf, 2, InpDonchian_Period, highData) < InpDonchian_Period) return false;
      double donchianUpper = highData[ArrayMaximum(highData)];
      return (closeEnt[0] > donchianUpper);
   }
   else
   {
      double lowData[];
      if(CopyLow(_Symbol, tf, 2, InpDonchian_Period, lowData) < InpDonchian_Period) return false;
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
//| EXECUTE ENTRY (Long or Short)                                     |
//+------------------------------------------------------------------+
void ExecuteEntry(bool isLong)
{
   symInfo.RefreshRates();
   double entryPrice = isLong ? symInfo.Ask() : symInfo.Bid();

   if(entryPrice <= 0) return;

   // Calculate stop loss
   double atrEnt[];
   if(CopyBuffer(h_ATR_Ent, 0, 1, 1, atrEnt) < 1) return;

   double slPrice;

   if(isLong)
   {
      // ATR-based SL below entry
      slPrice = entryPrice - atrEnt[0] * InpATR_SL_Multiplier;

      // Swing low verification
      double lowData[];
      if(CopyLow(_Symbol, InpEntryTF, 1, InpDonchian_Period, lowData) >= InpDonchian_Period)
      {
         double swingLow = lowData[ArrayMinimum(lowData)];
         if(swingLow < entryPrice && swingLow > slPrice)
            slPrice = swingLow - symInfo.Point() * 10;
      }
   }
   else
   {
      // ATR-based SL above entry
      slPrice = entryPrice + atrEnt[0] * InpATR_SL_Multiplier;

      // Swing high verification
      double highData[];
      if(CopyHigh(_Symbol, InpEntryTF, 1, InpDonchian_Period, highData) >= InpDonchian_Period)
      {
         double swingHigh = highData[ArrayMaximum(highData)];
         if(swingHigh > entryPrice && swingHigh < slPrice)
            slPrice = swingHigh + symInfo.Point() * 10;
      }
   }

   double slDistance = MathAbs(entryPrice - slPrice);
   if(slDistance <= 0) return;

   slPrice = NormalizeDouble(slPrice, symInfo.Digits());

   // Calculate position size for 1% risk
   double lotSize = CalculateLotSize(slDistance);
   if(lotSize <= 0) return;

   double tp = 0;  // No TP - we trail the stop
   string comment = StringFormat("TPB%s|SL:%.5f|R:%.2f",
                                 isLong ? "L" : "S", slPrice, slDistance);

   bool success;
   if(isLong)
      success = trade.Buy(lotSize, _Symbol, entryPrice, slPrice, tp, comment);
   else
      success = trade.Sell(lotSize, _Symbol, entryPrice, slPrice, tp, comment);

   if(success)
   {
      Print(isLong ? "BUY" : "SELL", " opened: Price=", entryPrice, " SL=", slPrice,
            " Lots=", lotSize, " Risk$=", slDistance * lotSize * GetPointValue());

      // Track trade state
      TradeState state;
      state.ticket = trade.ResultOrder();
      state.direction = isLong ? 0 : 1;
      state.entryPrice = entryPrice;
      state.initialSL = slPrice;
      state.initialTP_target = isLong ?
         (entryPrice + slDistance * InpBE_RR_Ratio) :
         (entryPrice - slDistance * InpBE_RR_Ratio);
      state.highSinceEntry = entryPrice;
      state.lowSinceEntry = entryPrice;
      state.initialLotSize = lotSize;
      state.beApplied = false;
      state.trailingActive = false;
      state.partialTPTaken = false;

      int size = ArraySize(g_tradeStates);
      ArrayResize(g_tradeStates, size + 1);
      g_tradeStates[size] = state;
   }
   else
   {
      Print(isLong ? "Buy" : "Sell", " order failed: ", trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//| CALCULATE LOT SIZE FOR 1% RISK                                   |
//+------------------------------------------------------------------+
double CalculateLotSize(double slDistancePrice)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskAmount = balance * InpRisk_Percent / 100.0;

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
//| MANAGE OPEN POSITIONS                                             |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   for(int i = ArraySize(g_tradeStates) - 1; i >= 0; i--)
   {
      ulong ticket = g_tradeStates[i].ticket;

      if(!PositionSelectByTicket(ticket))
      {
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

      // --- PARTIAL PROFIT TAKING ---
      if(InpPartialTP_Enabled && !g_tradeStates[i].partialTPTaken && currentRR >= InpPartialTP_RR)
      {
         double currentLots = PositionGetDouble(POSITION_VOLUME);
         double closeLots = NormalizeDouble(currentLots * InpPartialTP_Fraction, 2);

         if(closeLots >= symInfo.LotsMin())
         {
            bool closeSuccess;
            if(isLong)
               closeSuccess = trade.Sell(closeLots, _Symbol, currentPrice, 0, 0,
                                         "Partial TP");
            else
               closeSuccess = trade.Buy(closeLots, _Symbol, currentPrice, 0, 0,
                                        "Partial TP");

            if(closeSuccess)
            {
               g_tradeStates[i].partialTPTaken = true;
               Print("Partial TP: Closed ", closeLots, " lots at ", currentPrice,
                     " RR=", currentRR);
            }
         }
      }

      // --- BREAKEVEN LOGIC ---
      if(!g_tradeStates[i].beApplied)
      {
         bool applyBE = false;

         if(InpBE_Mode == BE_MODE_RR_BASED)
         {
            applyBE = (currentRR >= InpBE_RR_Ratio);
         }
         else // BE_MODE_PULLBACK_BO
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

      // --- TRAILING STOP LOGIC ---
      if(currentRR >= InpTrail_Start_RR)
      {
         g_tradeStates[i].trailingActive = true;
      }

      if(g_tradeStates[i].trailingActive)
      {
         double atrEnt[];
         if(CopyBuffer(h_ATR_Ent, 0, 1, 1, atrEnt) >= 1)
         {
            double trailDistance = atrEnt[0] * InpATR_Trail_Multi;
            double trailSL;

            if(isLong)
            {
               trailSL = g_tradeStates[i].highSinceEntry - trailDistance;
               trailSL = NormalizeDouble(trailSL, symInfo.Digits());

               if(trailSL > currentSL && trailSL < currentPrice)
               {
                  if(trade.PositionModify(ticket, trailSL, 0))
                  {
                     Print("Trail SL (Long): Ticket=", ticket, " New SL=", trailSL,
                           " High=", g_tradeStates[i].highSinceEntry);
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
                     Print("Trail SL (Short): Ticket=", ticket, " New SL=", trailSL,
                           " Low=", g_tradeStates[i].lowSinceEntry);
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

   if(CopyClose(_Symbol, InpEntryTF, 1, 1, closeEnt) < 1) return false;

   // Must have moved up at least 0.5:1 RR first
   double initialRisk = entryPrice - PositionGetDouble(POSITION_SL);
   if(initialRisk <= 0) return false;
   if(highSinceEntry - entryPrice < initialRisk * 0.5) return false;

   if(CopyHigh(_Symbol, InpEntryTF, 2, InpDonchian_PB_Period, highData) < InpDonchian_PB_Period)
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

   if(CopyClose(_Symbol, InpEntryTF, 1, 1, closeEnt) < 1) return false;

   // Must have moved down at least 0.5:1 RR first
   double initialRisk = PositionGetDouble(POSITION_SL) - entryPrice;
   if(initialRisk <= 0) return false;
   if(entryPrice - lowSinceEntry < initialRisk * 0.5) return false;

   if(CopyLow(_Symbol, InpEntryTF, 2, InpDonchian_PB_Period, lowData) < InpDonchian_PB_Period)
      return false;

   double miniDonchianLower = lowData[ArrayMinimum(lowData)];
   return (closeEnt[0] < miniDonchianLower);
}

//+------------------------------------------------------------------+
//| EQUITY CURVE FILTER                                               |
//| Only trade when equity > MA of equity (trend-following equity)    |
//+------------------------------------------------------------------+
void TrackEquity()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_equityCount++;
   int size = ArraySize(g_equityHistory);
   ArrayResize(g_equityHistory, size + 1);
   g_equityHistory[size] = equity;
}

bool PassesEquityFilter()
{
   int size = ArraySize(g_equityHistory);
   if(size < InpEquityFilter_Period)
      return true;  // Not enough data, allow trading

   // Calculate simple MA of equity
   double sum = 0;
   for(int i = size - InpEquityFilter_Period; i < size; i++)
      sum += g_equityHistory[i];

   double equityMA = sum / InpEquityFilter_Period;

   // Only trade when current equity is above its MA
   return (g_equityHistory[size - 1] >= equityMA);
}

//+------------------------------------------------------------------+
//| HELPER: Remove trade state by index                               |
//+------------------------------------------------------------------+
void RemoveTradeState(int index)
{
   int total = ArraySize(g_tradeStates);
   if(index < 0 || index >= total) return;

   for(int i = index; i < total - 1; i++)
      g_tradeStates[i] = g_tradeStates[i + 1];

   ArrayResize(g_tradeStates, total - 1);
}

//+------------------------------------------------------------------+
//| HELPER: Count our open positions                                  |
//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
//| HELPER: Check for new bar                                         |
//+------------------------------------------------------------------+
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
