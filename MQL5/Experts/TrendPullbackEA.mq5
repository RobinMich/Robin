//+------------------------------------------------------------------+
//|                                          TrendPullbackEA.mq5     |
//|        Multi-Timeframe Trend Follow Pullback Strategy             |
//|        Long-Only | High RRR | 1% Risk Per Trade                  |
//+------------------------------------------------------------------+
//| STRATEGY OVERVIEW:                                                |
//| - 3 Timeframes: Context (W1), Validation (D1), Entry (H4)       |
//| - Trend direction via EMA alignment + ADX filter                 |
//| - Pullback detection via EMA zone + BB Squeeze                   |
//| - Entry via Donchian breakout + Volume confirmation              |
//| - Risk: 1% per trade, BE at 1:1 or pullback breakout            |
//| - Trailing stop via ATR to let winners run                       |
//+------------------------------------------------------------------+
#property copyright "TrendPullbackEA"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| ENUMS                                                             |
//+------------------------------------------------------------------+
enum ENUM_BE_MODE
{
   BE_MODE_RR_BASED    = 0,  // Move SL to BE at 1:1 RR
   BE_MODE_PULLBACK_BO = 1   // Move SL to BE after mini-pullback breakout
};

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                  |
//+------------------------------------------------------------------+
// --- Timeframes ---
input group "=== Timeframe Settings ==="
input ENUM_TIMEFRAMES InpContextTF     = PERIOD_W1;    // Context Timeframe (Trend Direction)
input ENUM_TIMEFRAMES InpValidationTF  = PERIOD_D1;    // Validation Timeframe (Pullback Detection)
input ENUM_TIMEFRAMES InpEntryTF       = PERIOD_H4;    // Entry Timeframe (Precise Entry)

// --- EMA Settings ---
input group "=== EMA Settings ==="
input int    InpEMA_Fast   = 21;     // Fast EMA Period
input int    InpEMA_Mid    = 50;     // Mid EMA Period
input int    InpEMA_Slow   = 200;    // Slow EMA Period

// --- ADX/DMI Settings ---
input group "=== ADX/DMI Settings ==="
input int    InpADX_Period              = 14;    // ADX Period
input double InpADX_Threshold_Context   = 20.0;  // ADX Threshold Context TF (Trend On)
input double InpADX_Threshold_Validation = 15.0; // ADX Threshold Validation TF

// --- ATR Settings ---
input group "=== ATR Settings ==="
input int    InpATR_Period         = 14;    // ATR Period
input double InpATR_SL_Multiplier  = 1.5;   // ATR Stop Loss Multiplier
input double InpATR_Trail_Multi    = 2.5;   // ATR Trailing Stop Multiplier

// --- Bollinger Bands Squeeze ---
input group "=== BB Squeeze Settings ==="
input int    InpBB_Period          = 20;     // BB Period
input double InpBB_Deviation      = 2.0;    // BB Deviation
input int    InpBBW_Lookback      = 50;     // BBW Squeeze Lookback
input double InpBBW_Squeeze_Pctile = 25.0;  // BBW Squeeze Percentile (lower = tighter)

// --- Donchian Channel ---
input group "=== Donchian Channel Settings ==="
input int    InpDonchian_Period    = 20;     // Donchian Period (Entry TF Breakout)
input int    InpDonchian_PB_Period = 5;      // Mini Pullback Donchian (for BE mode 2)

// --- Volume Filter ---
input group "=== Volume Filter ==="
input int    InpVolume_Period      = 20;     // Volume MA Period
input double InpVolume_Multiplier  = 1.2;    // Volume Breakout Multiplier

// --- Risk Management ---
input group "=== Risk Management ==="
input double InpRisk_Percent       = 1.0;    // Risk % Per Trade
input ENUM_BE_MODE InpBE_Mode      = BE_MODE_RR_BASED; // Breakeven Mode
input double InpBE_RR_Ratio        = 1.0;    // RR Ratio for BE (Mode 1)
input double InpTrail_Start_RR     = 2.0;    // RR Ratio to Start Trailing
input int    InpMax_Positions      = 5;      // Max Concurrent Positions
input int    InpMagicNumber        = 20250301; // Magic Number
input double InpMaxSpreadATR       = 0.3;    // Max Spread as % of ATR

// --- Pullback Zone ---
input group "=== Pullback Zone ==="
input double InpPB_ATR_Buffer      = 0.5;    // ATR buffer above/below EMA zone
input bool   InpRequireBullishBar  = true;   // Require bullish bar on entry TF

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

// --- State tracking for BE mode 2 ---
struct TradeState
{
   ulong  ticket;
   double entryPrice;
   double initialSL;
   double initialTP_target; // not used as TP, just for RR calc
   double highSinceEntry;
   bool   beApplied;
   bool   trailingActive;
};

TradeState g_tradeStates[];
datetime   g_lastBarTime;

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

   Print("TrendPullbackEA initialized successfully");
   Print("Context TF: ", EnumToString(InpContextTF),
         " | Validation TF: ", EnumToString(InpValidationTF),
         " | Entry TF: ", EnumToString(InpEntryTF));

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

   Print("TrendPullbackEA deinitialized");
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

   // --- Check all entry conditions ---
   if(CheckContextConditions() &&
      CheckValidationConditions() &&
      CheckEntryConditions())
   {
      ExecuteBuyEntry();
   }
}

//+------------------------------------------------------------------+
//| CHECK CONTEXT CONDITIONS (Weekly)                                 |
//| - EMA alignment: Fast > Mid > Slow (strong uptrend)              |
//| - Price above Fast EMA                                           |
//| - ADX > threshold (trend active)                                 |
//| - DI+ > DI- (bullish)                                           |
//+------------------------------------------------------------------+
bool CheckContextConditions()
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

   // Condition 1: EMA alignment (bullish structure)
   if(!(emaFast[0] > emaMid[0] && emaMid[0] > emaSlow[0]))
      return false;

   // Condition 2: Price above fast EMA
   if(closeCtx[0] < emaFast[0])
      return false;

   // Condition 3: ADX trending
   if(adxMain[0] < InpADX_Threshold_Context)
      return false;

   // Condition 4: Bullish direction
   if(diPlus[0] <= diMinus[0])
      return false;

   return true;
}

//+------------------------------------------------------------------+
//| CHECK VALIDATION CONDITIONS (Daily)                               |
//| - Price pulled back into EMA zone (between Fast and Mid EMA)     |
//| - OR price near Fast EMA (within ATR buffer)                     |
//| - BB Squeeze detected (compression -> breakout imminent)         |
//| - ADX still shows trending                                       |
//+------------------------------------------------------------------+
bool CheckValidationConditions()
{
   double emaFast[], emaMid[], emaSlow[];
   double adxMain[], diPlus[], diMinus[];
   double atrVal[];
   double bbUpper[], bbLower[], bbMid[];

   if(CopyBuffer(h_EMA_Fast_Val, 0, 1, 1, emaFast) < 1) return false;
   if(CopyBuffer(h_EMA_Mid_Val,  0, 1, 1, emaMid)  < 1) return false;
   if(CopyBuffer(h_EMA_Slow_Val, 0, 1, 1, emaSlow) < 1) return false;
   if(CopyBuffer(h_ADX_Val, 0, 1, 1, adxMain)       < 1) return false;
   if(CopyBuffer(h_ADX_Val, 1, 1, 1, diPlus)         < 1) return false;
   if(CopyBuffer(h_ADX_Val, 2, 1, 1, diMinus)        < 1) return false;
   if(CopyBuffer(h_ATR_Val, 0, 1, 1, atrVal)         < 1) return false;

   double closeVal[];
   if(CopyClose(_Symbol, InpValidationTF, 1, 1, closeVal) < 1) return false;

   // Condition 1: EMA structure still bullish on daily
   if(emaFast[0] <= emaSlow[0])
      return false;

   // Condition 2: Price in pullback zone
   // Either: between Fast and Mid EMA, or within ATR buffer of Fast EMA
   double atrBuffer = atrVal[0] * InpPB_ATR_Buffer;
   bool inPullbackZone = false;

   // Zone A: Price between Fast and Mid EMA (classic pullback)
   if(closeVal[0] >= emaMid[0] && closeVal[0] <= emaFast[0] + atrBuffer)
      inPullbackZone = true;

   // Zone B: Price just touched Fast EMA from above (shallow pullback)
   if(closeVal[0] >= emaFast[0] - atrBuffer && closeVal[0] <= emaFast[0] + atrBuffer)
      inPullbackZone = true;

   if(!inPullbackZone)
      return false;

   // Condition 3: ADX still shows some trend
   if(adxMain[0] < InpADX_Threshold_Validation)
      return false;

   // Condition 4: BB Squeeze detection
   if(!IsBBSqueeze(InpValidationTF, h_BB_Val))
      return false;

   return true;
}

//+------------------------------------------------------------------+
//| CHECK ENTRY CONDITIONS (H4)                                       |
//| - Donchian Channel breakout (close > previous upper)             |
//| - Volume above average (confirms breakout quality)               |
//| - Price above Fast EMA (local trend up)                          |
//| - ADX rising or DI+ > DI- on entry TF                           |
//| - Optional: bullish bar (close > open)                           |
//+------------------------------------------------------------------+
bool CheckEntryConditions()
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

   // Condition 1: Price above fast EMA (local trend up)
   if(closeEnt[0] < emaFast[0])
      return false;

   // Condition 2: DI+ > DI- on entry TF
   if(diPlus[0] <= diMinus[0])
      return false;

   // Condition 3: Donchian breakout
   if(!IsDonchianBreakout(InpEntryTF))
      return false;

   // Condition 4: Volume confirmation
   if(!IsVolumeConfirmed(InpEntryTF))
      return false;

   // Condition 5: Optional bullish bar
   if(InpRequireBullishBar && closeEnt[0] <= openEnt[0])
      return false;

   return true;
}

//+------------------------------------------------------------------+
//| BB SQUEEZE DETECTION                                              |
//| BBW = (Upper - Lower) / Middle                                   |
//| Squeeze = BBW in lowest N-th percentile of lookback              |
//+------------------------------------------------------------------+
bool IsBBSqueeze(ENUM_TIMEFRAMES tf, int bbHandle)
{
   int lookback = InpBBW_Lookback + 1; // +1 for current bar
   double bbUpper[], bbLower[], bbMid[];

   ArraySetAsSeries(bbUpper, true);
   ArraySetAsSeries(bbLower, true);
   ArraySetAsSeries(bbMid, true);

   if(CopyBuffer(bbHandle, 1, 1, lookback, bbUpper) < lookback) return false;
   if(CopyBuffer(bbHandle, 2, 1, lookback, bbLower) < lookback) return false;
   if(CopyBuffer(bbHandle, 0, 1, lookback, bbMid)   < lookback) return false;

   // Calculate BBW for all bars
   double bbwValues[];
   ArrayResize(bbwValues, lookback);
   for(int i = 0; i < lookback; i++)
   {
      if(bbMid[i] > 0)
         bbwValues[i] = (bbUpper[i] - bbLower[i]) / bbMid[i];
      else
         bbwValues[i] = 0;
   }

   // Current BBW is index 0 (most recent completed bar)
   double currentBBW = bbwValues[0];

   // Sort to find percentile threshold
   double sorted[];
   ArrayCopy(sorted, bbwValues);
   ArraySort(sorted);

   int percentileIndex = (int)MathFloor(lookback * InpBBW_Squeeze_Pctile / 100.0);
   if(percentileIndex >= lookback) percentileIndex = lookback - 1;

   double threshold = sorted[percentileIndex];

   return (currentBBW <= threshold);
}

//+------------------------------------------------------------------+
//| DONCHIAN BREAKOUT DETECTION                                       |
//| Close > Previous Donchian Upper (highest high of N periods)      |
//+------------------------------------------------------------------+
bool IsDonchianBreakout(ENUM_TIMEFRAMES tf)
{
   double closeEnt[];
   double highData[];

   // Get the close of the last completed bar
   if(CopyClose(_Symbol, tf, 1, 1, closeEnt) < 1) return false;

   // Get highs for Donchian calculation (shift 2 to N+1, excluding the breakout bar)
   if(CopyHigh(_Symbol, tf, 2, InpDonchian_Period, highData) < InpDonchian_Period) return false;

   // Find the highest high
   double donchianUpper = highData[ArrayMaximum(highData)];

   // Breakout: close above previous Donchian upper
   return (closeEnt[0] > donchianUpper);
}

//+------------------------------------------------------------------+
//| VOLUME CONFIRMATION                                               |
//| Current volume > Multiplier * Average volume                     |
//+------------------------------------------------------------------+
bool IsVolumeConfirmed(ENUM_TIMEFRAMES tf)
{
   long volData[];

   // Get volume for lookback + current bar
   if(CopyTickVolume(_Symbol, tf, 1, InpVolume_Period + 1, volData) < InpVolume_Period + 1)
      return true; // If volume data unavailable, don't filter

   // Current bar volume (most recent completed)
   long currentVol = volData[InpVolume_Period];

   // Calculate average of previous bars
   double avgVol = 0;
   for(int i = 0; i < InpVolume_Period; i++)
      avgVol += (double)volData[i];
   avgVol /= InpVolume_Period;

   if(avgVol <= 0)
      return true; // No volume data, skip filter

   return ((double)currentVol >= avgVol * InpVolume_Multiplier);
}

//+------------------------------------------------------------------+
//| EXECUTE BUY ENTRY                                                 |
//| Calculate position size for 1% risk                              |
//| Set SL below swing low or ATR-based                              |
//+------------------------------------------------------------------+
void ExecuteBuyEntry()
{
   symInfo.RefreshRates();
   double ask = symInfo.Ask();

   if(ask <= 0) return;

   // Calculate stop loss
   double atrEnt[];
   if(CopyBuffer(h_ATR_Ent, 0, 1, 1, atrEnt) < 1) return;

   // Method 1: ATR-based SL
   double slATR = ask - atrEnt[0] * InpATR_SL_Multiplier;

   // Method 2: Swing low (Donchian lower on entry TF)
   double lowData[];
   if(CopyLow(_Symbol, InpEntryTF, 1, InpDonchian_Period, lowData) >= InpDonchian_Period)
   {
      double swingLow = lowData[ArrayMinimum(lowData)];
      // Use the tighter of ATR-SL and swing low, but SL must be below current price
      if(swingLow < ask && swingLow > slATR)
         slATR = swingLow - symInfo.Point() * 10; // Small buffer below swing low
   }

   double slDistance = ask - slATR;
   if(slDistance <= 0) return;

   // Normalize SL
   slATR = NormalizeDouble(slATR, symInfo.Digits());

   // Calculate position size for 1% risk
   double lotSize = CalculateLotSize(slDistance);
   if(lotSize <= 0) return;

   // No TP - we trail the stop
   double tp = 0;

   string comment = StringFormat("TPB|SL:%.5f|R:%.2f", slATR, slDistance);

   if(trade.Buy(lotSize, _Symbol, ask, slATR, tp, comment))
   {
      Print("BUY opened: Price=", ask, " SL=", slATR,
            " Lots=", lotSize, " Risk$=", slDistance * lotSize * GetPointValue());

      // Track trade state
      TradeState state;
      state.ticket = trade.ResultOrder();
      state.entryPrice = ask;
      state.initialSL = slATR;
      state.initialTP_target = ask + slDistance * InpBE_RR_Ratio; // 1:1 level
      state.highSinceEntry = ask;
      state.beApplied = false;
      state.trailingActive = false;

      int size = ArraySize(g_tradeStates);
      ArrayResize(g_tradeStates, size + 1);
      g_tradeStates[size] = state;
   }
   else
   {
      Print("Buy order failed: ", trade.ResultRetcodeDescription());
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

   // Lot size = Risk Amount / (SL in ticks * tick value)
   double slTicks = slDistancePrice / tickSize;
   double lotSize = riskAmount / (slTicks * tickValue);

   // Round to lot step
   lotSize = MathFloor(lotSize / lotStep) * lotStep;

   // Clamp
   if(lotSize < minLot) lotSize = minLot;
   if(lotSize > maxLot) lotSize = maxLot;

   return NormalizeDouble(lotSize, 2);
}

//+------------------------------------------------------------------+
//| GET POINT VALUE (for P&L calculation)                             |
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
//| - Move SL to breakeven                                           |
//| - Trail stop via ATR                                             |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   for(int i = ArraySize(g_tradeStates) - 1; i >= 0; i--)
   {
      ulong ticket = g_tradeStates[i].ticket;

      if(!PositionSelectByTicket(ticket))
      {
         // Position closed, remove from tracking
         RemoveTradeState(i);
         continue;
      }

      // Only manage our positions
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;

      if(PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_BUY)
         continue;

      double currentPrice = symInfo.Bid();
      double openPrice    = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL    = PositionGetDouble(POSITION_SL);
      double initialRisk  = g_tradeStates[i].entryPrice - g_tradeStates[i].initialSL;

      if(initialRisk <= 0) continue;

      // Update high since entry
      if(currentPrice > g_tradeStates[i].highSinceEntry)
         g_tradeStates[i].highSinceEntry = currentPrice;

      double currentProfit = currentPrice - openPrice;
      double currentRR = currentProfit / initialRisk;

      // --- BREAKEVEN LOGIC ---
      if(!g_tradeStates[i].beApplied)
      {
         bool applyBE = false;

         if(InpBE_Mode == BE_MODE_RR_BASED)
         {
            // Mode 1: Move SL to BE at specified RR ratio
            applyBE = (currentRR >= InpBE_RR_Ratio);
         }
         else // BE_MODE_PULLBACK_BO
         {
            // Mode 2: After mini-pullback breakout
            applyBE = IsMiniPullbackBreakout(openPrice, g_tradeStates[i].highSinceEntry);
         }

         if(applyBE)
         {
            double newSL = openPrice + symInfo.Spread() * symInfo.Point();
            newSL = NormalizeDouble(newSL, symInfo.Digits());

            if(newSL > currentSL)
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
            double trailSL = g_tradeStates[i].highSinceEntry - trailDistance;
            trailSL = NormalizeDouble(trailSL, symInfo.Digits());

            // Only move SL up, never down
            if(trailSL > currentSL && trailSL < currentPrice)
            {
               if(trade.PositionModify(ticket, trailSL, 0))
               {
                  Print("Trail SL: Ticket=", ticket, " New SL=", trailSL,
                        " High=", g_tradeStates[i].highSinceEntry);
               }
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| MINI PULLBACK BREAKOUT (for BE Mode 2)                           |
//| After price rallied from entry, pulled back, then broke above    |
//| the mini Donchian channel -> move to BE                          |
//+------------------------------------------------------------------+
bool IsMiniPullbackBreakout(double entryPrice, double highSinceEntry)
{
   double closeEnt[];
   double highData[], lowData[];

   if(CopyClose(_Symbol, InpEntryTF, 1, 1, closeEnt) < 1) return false;

   // Must have moved up at least 0.5:1 RR first
   double initialRisk = entryPrice - PositionGetDouble(POSITION_SL);
   if(initialRisk <= 0) return false;
   if(highSinceEntry - entryPrice < initialRisk * 0.5) return false;

   // Check mini Donchian breakout
   if(CopyHigh(_Symbol, InpEntryTF, 2, InpDonchian_PB_Period, highData) < InpDonchian_PB_Period)
      return false;

   double miniDonchianUpper = highData[ArrayMaximum(highData)];

   return (closeEnt[0] > miniDonchianUpper);
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
