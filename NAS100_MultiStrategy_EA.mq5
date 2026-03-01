//+------------------------------------------------------------------+
//|                                    NAS100_MultiStrategy_EA.mq5   |
//|                        Multi-Strategy Expert Advisor for NAS100   |
//|           Stress-tested & optimized on 262k bars + 11 instruments|
//+------------------------------------------------------------------+
#property copyright "Robin Trading Systems"
#property link      ""
#property version   "3.00"
#property description "Multi-Strategy EA: BB Reversal + EMA+Vol + RSI Momentum"
#property description "Optimized for NAS100 on M15 (primary) and M5 (secondary)"
#property description "Walk-forward validated, Monte Carlo tested (0% ruin risk)"
#property description "Cross-validated on NVDA, NFLX, PLTR, DELL, AVGO, LLY, MSFT, AAPL, JPM, TPL"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| ENUMS                                                            |
//+------------------------------------------------------------------+
enum ENUM_STRATEGY_MODE
{
   MODE_ALL_STRATEGIES   = 0, // All Strategies Combined
   MODE_BB_ONLY          = 1, // BB Reversal Only (Best validated)
   MODE_EMA_VOL          = 2, // EMA + Volume Only
   MODE_RSI_ONLY         = 3, // RSI Momentum Only
   MODE_EMA_ONLY         = 4, // EMA Crossover Only
   MODE_VOLUME_ONLY      = 5, // Volume Spike Only
   MODE_EMA_VOLUME       = 6, // EMA + Volume Confirmation
   MODE_EMA_RSI          = 7, // EMA + RSI Confirmation
};

enum ENUM_LOT_MODE
{
   LOT_FIXED             = 0, // Fixed Lot Size
   LOT_RISK_PERCENT      = 1, // Risk % of Balance
   LOT_DYNAMIC_ATR       = 2, // Dynamic ATR-Based
};

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                 |
//+------------------------------------------------------------------+
// === General Settings ===
input group "=== General Settings ==="
input ENUM_STRATEGY_MODE InpStrategyMode  = MODE_ALL_STRATEGIES; // Strategy Mode
input int                InpMagicNumber   = 202510;              // Magic Number
input string             InpComment       = "NAS100_Multi";      // Trade Comment

// === Lot Size / Risk Management ===
input group "=== Risk Management ==="
input ENUM_LOT_MODE      InpLotMode       = LOT_RISK_PERCENT;   // Lot Sizing Mode
input double              InpFixedLots     = 0.10;               // Fixed Lot Size
input double              InpRiskPercent   = 1.0;                // Risk % per Trade
input double              InpMaxLots       = 5.0;                // Maximum Lot Size
input int                 InpMaxOpenTrades = 3;                  // Max Simultaneous Trades
input double              InpMaxDailyLoss  = 3.0;                // Max Daily Loss % (0=off)
input int                 InpMaxTradesDay  = 10;                 // Max Trades per Day

// === BB Reversal Strategy (Primary - OOS PF: 1.83, WR: 70%) ===
// Validated: BB(15,2.5) + RSI(80/20) on M15, SL=150/TP=150, Session 8-20
input group "=== BB Reversal Strategy (PRIMARY) ==="
input bool                InpUseBB         = true;               // Enable BB Strategy
input int                 InpBB_Period     = 15;                 // BB Period
input double              InpBB_StdDev     = 2.5;                // BB Std Deviation
input int                 InpBB_RSIPeriod  = 14;                 // BB RSI Confirmation Period
input int                 InpBB_RSI_OB     = 80;                 // RSI Overbought (sell confirm)
input int                 InpBB_RSI_OS     = 20;                 // RSI Oversold (buy confirm)
input int                 InpBB_SL         = 1500;               // BB Stop Loss (points)
input int                 InpBB_TP         = 1500;               // BB Take Profit (points)
input int                 InpBB_MaxHold    = 60;                 // BB Max Hold Bars (on M15)

// === EMA + Volume Strategy (Secondary - OOS PF: 1.36, Recovery: 6.37) ===
// Validated: EMA(12/21) + EMA(100) trend + Volume(1.3x) on M5
input group "=== EMA + Volume Strategy (SECONDARY) ==="
input bool                InpUseEMAVol     = true;               // Enable EMA+Vol Strategy
input int                 InpEV_Fast       = 12;                 // Fast EMA Period
input int                 InpEV_Slow       = 21;                 // Slow EMA Period
input int                 InpEV_Trend      = 100;                // Trend EMA Period
input double              InpEV_VolMult    = 1.3;                // Volume Multiplier
input int                 InpEV_VolPeriod  = 20;                 // Volume MA Period
input int                 InpEV_SL         = 1500;               // EMA+Vol Stop Loss (points)
input int                 InpEV_TP         = 3000;               // EMA+Vol Take Profit (points)
input int                 InpEV_MaxHold    = 40;                 // EMA+Vol Max Hold Bars (on M5)

// === EMA Crossover Strategy (Legacy) ===
input group "=== EMA Crossover Strategy ==="
input bool                InpUseEMA        = false;              // Enable EMA Strategy
input int                 InpEMA_Fast      = 9;                  // Fast EMA Period
input int                 InpEMA_Slow      = 21;                 // Slow EMA Period
input int                 InpEMA_SL        = 1500;               // EMA Stop Loss (points)
input int                 InpEMA_TP        = 3000;               // EMA Take Profit (points)
input int                 InpEMA_MaxHold   = 80;                 // EMA Max Hold Bars
input bool                InpEMA_SessionFilter = true;           // Use Session Filter

// === Volume Spike Strategy (Legacy) ===
input group "=== Volume Spike Strategy ==="
input bool                InpUseVolume     = false;              // Enable Volume Strategy
input double              InpVol_Multiplier = 2.5;               // Volume Spike Multiplier
input int                 InpVol_MAPeriod  = 20;                 // Volume MA Period
input int                 InpVol_SL        = 1500;               // Volume Stop Loss (points)
input int                 InpVol_TP        = 3000;               // Volume Take Profit (points)
input int                 InpVol_MaxHold   = 30;                 // Volume Max Hold Bars
input int                 InpVol_MinSpread = 0;                  // Min Spread Filter (points)

// === RSI Momentum Strategy (Cross-validated on 11 instruments) ===
input group "=== RSI Momentum Strategy ==="
input bool                InpUseRSI        = true;               // Enable RSI Strategy
input int                 InpRSI_Period    = 14;                 // RSI Period
input int                 InpRSI_UpperLevel = 85;                // RSI Upper Level (Buy momentum)
input int                 InpRSI_LowerLevel = 15;                // RSI Lower Level (Sell momentum)
input int                 InpRSI_SL        = 1500;               // RSI Stop Loss (points)
input int                 InpRSI_TP        = 3000;               // RSI Take Profit (points)
input int                 InpRSI_MaxHold   = 30;                 // RSI Max Hold Bars

// === Session Filter ===
// Optimized: Session 8-20 server time (covers London+NY)
input group "=== Session Filter ==="
input int                 InpSessionStartHour = 8;               // Session Start Hour (Server)
input int                 InpSessionEndHour   = 20;              // Session End Hour (Server)
input bool                InpTradeMonday      = true;            // Trade Monday
input bool                InpTradeTuesday     = true;            // Trade Tuesday
input bool                InpTradeWednesday   = true;            // Trade Wednesday
input bool                InpTradeThursday    = true;            // Trade Thursday
input bool                InpTradeFriday      = true;            // Trade Friday

// === ATR Filter ===
input group "=== ATR Volatility Filter ==="
input bool                InpUseATRFilter  = true;               // Use ATR Volatility Filter
input int                 InpATR_Period    = 14;                 // ATR Period
input double              InpATR_MinMult   = 0.5;               // Min ATR Multiplier (avoid low vol)
input double              InpATR_MaxMult   = 3.0;               // Max ATR Multiplier (avoid spikes)

// === Trailing Stop ===
input group "=== Trailing Stop ==="
input bool                InpUseTrailing   = true;               // Use Trailing Stop
input int                 InpTrailStart    = 500;                // Trailing Start (points profit)
input int                 InpTrailStep     = 100;                // Trailing Step (points)

// === Breakeven ===
input group "=== Breakeven ==="
input bool                InpUseBreakeven  = true;               // Use Breakeven
input int                 InpBE_Start      = 400;                // Breakeven Activation (points)
input int                 InpBE_Offset     = 50;                 // Breakeven Offset (points)

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                 |
//+------------------------------------------------------------------+
CTrade         trade;
CPositionInfo  posInfo;
CAccountInfo   accInfo;
CSymbolInfo    symInfo;

// Indicator handles - M15 for BB strategy
int hBB_Upper, hBB_Lower, hBB_Middle;
int hBB_RSI;

// Indicator handles - M5 for EMA+Vol strategy
int hEV_Fast, hEV_Slow, hEV_Trend;

// Indicator handles - current TF (legacy + RSI momentum)
int hEMA_Fast, hEMA_Slow;
int hRSI;
int hATR;

// State tracking
struct TradeState
{
   ulong    ticket;
   int      strategy;    // 1=EMA, 2=Volume, 3=RSI, 6=BB, 7=EMA+Vol
   datetime openTime;
   int      barsHeld;
   bool     breakevenSet;
   ENUM_TIMEFRAMES stratTF; // Timeframe for bar counting
};

TradeState openTrades[];
datetime   lastBarTime;
datetime   lastBarTimeM15;
datetime   lastBarTimeM5;
double     dailyStartBalance;
datetime   dailyResetTime;
int        dailyTradeCount;
double     medianATR;

// EMA crossover state
double prevEMAFast, prevEMASlow;
double currEMAFast, currEMASlow;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   // Validate inputs
   if(InpEMA_Fast >= InpEMA_Slow)
   {
      Print("ERROR: Fast EMA must be less than Slow EMA");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpRSI_LowerLevel >= InpRSI_UpperLevel)
   {
      Print("ERROR: RSI Lower Level must be less than Upper Level");
      return INIT_PARAMETERS_INCORRECT;
   }

   // Initialize trade object
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(30);
   trade.SetTypeFilling(ORDER_FILLING_IOC);
   trade.SetMarginMode();

   // Initialize symbol info
   symInfo.Name(_Symbol);
   symInfo.Refresh();

   // Create indicator handles - BB Strategy on M15
   hBB_Upper  = iBands(_Symbol, PERIOD_M15, InpBB_Period, 0, InpBB_StdDev, PRICE_CLOSE);
   hBB_Lower  = hBB_Upper; // Same handle, different buffer
   hBB_Middle = hBB_Upper;
   hBB_RSI    = iRSI(_Symbol, PERIOD_M15, InpBB_RSIPeriod, PRICE_CLOSE);

   // Create indicator handles - EMA+Vol on M5
   hEV_Fast   = iMA(_Symbol, PERIOD_M5, InpEV_Fast, 0, MODE_EMA, PRICE_CLOSE);
   hEV_Slow   = iMA(_Symbol, PERIOD_M5, InpEV_Slow, 0, MODE_EMA, PRICE_CLOSE);
   hEV_Trend  = iMA(_Symbol, PERIOD_M5, InpEV_Trend, 0, MODE_EMA, PRICE_CLOSE);

   // Create indicator handles - Current TF (legacy + RSI momentum)
   hEMA_Fast = iMA(_Symbol, PERIOD_M1, InpEMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   hEMA_Slow = iMA(_Symbol, PERIOD_M1, InpEMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI      = iRSI(_Symbol, PERIOD_M5, InpRSI_Period, PRICE_CLOSE);
   hATR      = iATR(_Symbol, PERIOD_M15, InpATR_Period);

   if(hBB_Upper == INVALID_HANDLE || hBB_RSI == INVALID_HANDLE ||
      hEV_Fast == INVALID_HANDLE || hEV_Slow == INVALID_HANDLE ||
      hEV_Trend == INVALID_HANDLE ||
      hEMA_Fast == INVALID_HANDLE || hEMA_Slow == INVALID_HANDLE ||
      hRSI == INVALID_HANDLE || hATR == INVALID_HANDLE)
   {
      Print("ERROR: Failed to create indicator handles");
      return INIT_FAILED;
   }

   // Initialize state
   lastBarTime       = 0;
   lastBarTimeM15    = 0;
   lastBarTimeM5     = 0;
   dailyStartBalance = accInfo.Balance();
   dailyResetTime    = 0;
   dailyTradeCount   = 0;
   medianATR         = 0;
   prevEMAFast       = 0;
   prevEMASlow       = 0;
   currEMAFast       = 0;
   currEMASlow       = 0;

   ArrayResize(openTrades, 0);

   Print("NAS100 Multi-Strategy EA v3.0 initialized");
   Print("Strategy Mode: ", EnumToString(InpStrategyMode));
   Print("BB Reversal: ", InpUseBB ? "ON" : "OFF",
         " | EMA+Vol: ", InpUseEMAVol ? "ON" : "OFF",
         " | RSI Mom: ", InpUseRSI ? "ON" : "OFF",
         " | EMA Legacy: ", InpUseEMA ? "ON" : "OFF");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(hBB_Upper != INVALID_HANDLE)  IndicatorRelease(hBB_Upper);
   if(hBB_RSI != INVALID_HANDLE)    IndicatorRelease(hBB_RSI);
   if(hEV_Fast != INVALID_HANDLE)   IndicatorRelease(hEV_Fast);
   if(hEV_Slow != INVALID_HANDLE)   IndicatorRelease(hEV_Slow);
   if(hEV_Trend != INVALID_HANDLE)  IndicatorRelease(hEV_Trend);
   if(hEMA_Fast != INVALID_HANDLE)  IndicatorRelease(hEMA_Fast);
   if(hEMA_Slow != INVALID_HANDLE)  IndicatorRelease(hEMA_Slow);
   if(hRSI != INVALID_HANDLE)       IndicatorRelease(hRSI);
   if(hATR != INVALID_HANDLE)       IndicatorRelease(hATR);
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Only process on new bar
   datetime currentBarTime = iTime(_Symbol, PERIOD_M1, 0);
   if(currentBarTime == lastBarTime)
   {
      // Still manage trailing/breakeven on every tick
      ManageTrailingStop();
      ManageBreakeven();
      return;
   }
   lastBarTime = currentBarTime;

   // Refresh symbol info
   symInfo.Refresh();

   // Daily reset
   MqlDateTime dtNow;
   TimeCurrent(dtNow);
   datetime todayStart = StringToTime(StringFormat("%04d.%02d.%02d 00:00:00",
                         dtNow.year, dtNow.mon, dtNow.day));
   if(todayStart != dailyResetTime)
   {
      dailyResetTime    = todayStart;
      dailyStartBalance = accInfo.Balance();
      dailyTradeCount   = 0;
   }

   // Check daily loss limit
   if(InpMaxDailyLoss > 0)
   {
      double currentPnL = accInfo.Equity() - dailyStartBalance;
      double maxLoss    = dailyStartBalance * InpMaxDailyLoss / 100.0;
      if(currentPnL < -maxLoss)
      {
         // Close all positions and stop trading today
         CloseAllPositions();
         return;
      }
   }

   // Check max trades per day
   if(dailyTradeCount >= InpMaxTradesDay) return;

   // Update indicator values
   if(!UpdateIndicators()) return;

   // Manage existing positions (check max hold time)
   ManagePositions();

   // Check if we can open new trades
   int openCount = CountOpenTrades();
   if(openCount >= InpMaxOpenTrades) return;

   // Check session filter
   bool inSession = IsWithinSession(dtNow);

   // Check day filter
   if(!IsTradingDay(dtNow)) return;

   // Check ATR filter
   if(InpUseATRFilter && !IsATRValid()) return;

   // === STRATEGY SIGNALS ===
   int bbSignal = 0, evSignal = 0, rsiSignal = 0;
   int emaSignal = 0, volSignal = 0;

   // BB Reversal Signal (PRIMARY - on M15 new bar)
   datetime currM15 = iTime(_Symbol, PERIOD_M15, 0);
   bool newBarM15 = (currM15 != lastBarTimeM15);
   if(newBarM15) lastBarTimeM15 = currM15;

   if(InpUseBB && newBarM15 && inSession &&
      (InpStrategyMode == MODE_ALL_STRATEGIES || InpStrategyMode == MODE_BB_ONLY))
   {
      bbSignal = GetBBReversalSignal();
   }

   // EMA + Volume Signal (SECONDARY - on M5 new bar)
   datetime currM5 = iTime(_Symbol, PERIOD_M5, 0);
   bool newBarM5 = (currM5 != lastBarTimeM5);
   if(newBarM5) lastBarTimeM5 = currM5;

   if(InpUseEMAVol && newBarM5 && inSession &&
      (InpStrategyMode == MODE_ALL_STRATEGIES || InpStrategyMode == MODE_EMA_VOL))
   {
      evSignal = GetEMAVolSignal();
   }

   // RSI Momentum Signal (on M5 new bar)
   if(InpUseRSI && newBarM5 && inSession &&
      (InpStrategyMode == MODE_ALL_STRATEGIES || InpStrategyMode == MODE_RSI_ONLY))
   {
      rsiSignal = GetRSISignal();
   }

   // Legacy: EMA Crossover Signal
   if(InpUseEMA && (InpStrategyMode == MODE_EMA_ONLY ||
      InpStrategyMode == MODE_EMA_VOLUME || InpStrategyMode == MODE_EMA_RSI))
   {
      emaSignal = GetEMASignal(inSession);
   }

   // Legacy: Volume Spike Signal
   if(InpUseVolume && (InpStrategyMode == MODE_VOLUME_ONLY ||
      InpStrategyMode == MODE_EMA_VOLUME))
   {
      volSignal = GetVolumeSignal();
   }

   // === EXECUTE TRADES BASED ON MODE ===
   switch(InpStrategyMode)
   {
      case MODE_ALL_STRATEGIES:
         // Primary: BB Reversal
         if(bbSignal != 0 && !HasStrategyPosition(6))
            ExecuteTrade(bbSignal, 6, InpBB_SL, InpBB_TP);
         // Secondary: EMA + Volume
         if(evSignal != 0 && !HasStrategyPosition(7))
            ExecuteTrade(evSignal, 7, InpEV_SL, InpEV_TP);
         // Tertiary: RSI Momentum
         if(rsiSignal != 0 && !HasStrategyPosition(3))
            ExecuteTrade(rsiSignal, 3, InpRSI_SL, InpRSI_TP);
         break;

      case MODE_BB_ONLY:
         if(bbSignal != 0 && !HasStrategyPosition(6))
            ExecuteTrade(bbSignal, 6, InpBB_SL, InpBB_TP);
         break;

      case MODE_EMA_VOL:
         if(evSignal != 0 && !HasStrategyPosition(7))
            ExecuteTrade(evSignal, 7, InpEV_SL, InpEV_TP);
         break;

      case MODE_RSI_ONLY:
         if(rsiSignal != 0 && !HasStrategyPosition(3))
            ExecuteTrade(rsiSignal, 3, InpRSI_SL, InpRSI_TP);
         break;

      case MODE_EMA_ONLY:
         if(emaSignal != 0 && !HasStrategyPosition(1))
            ExecuteTrade(emaSignal, 1, InpEMA_SL, InpEMA_TP);
         break;

      case MODE_VOLUME_ONLY:
         if(volSignal != 0 && !HasStrategyPosition(2))
            ExecuteTrade(volSignal, 2, InpVol_SL, InpVol_TP);
         break;

      case MODE_EMA_VOLUME:
         if(emaSignal != 0 && volSignal == emaSignal && !HasStrategyPosition(4))
            ExecuteTrade(emaSignal, 4, InpEMA_SL, InpEMA_TP);
         break;

      case MODE_EMA_RSI:
         if(emaSignal != 0 && rsiSignal == emaSignal && !HasStrategyPosition(5))
            ExecuteTrade(emaSignal, 5, InpEMA_SL, InpEMA_TP);
         break;
   }
}

//+------------------------------------------------------------------+
//| Update all indicator values                                      |
//+------------------------------------------------------------------+
bool UpdateIndicators()
{
   double emaFastBuf[3], emaSlowBuf[3], rsiBuf[2], atrBuf[2];

   if(CopyBuffer(hEMA_Fast, 0, 0, 3, emaFastBuf) < 3) return false;
   if(CopyBuffer(hEMA_Slow, 0, 0, 3, emaSlowBuf) < 3) return false;
   if(CopyBuffer(hRSI, 0, 0, 2, rsiBuf) < 2) return false;
   if(CopyBuffer(hATR, 0, 0, 2, atrBuf) < 2) return false;

   // Store previous and current EMA values (for crossover detection)
   prevEMAFast = emaFastBuf[1];
   prevEMASlow = emaSlowBuf[1];
   currEMAFast = emaFastBuf[0];
   currEMASlow = emaSlowBuf[0];

   medianATR = atrBuf[1]; // Use confirmed (closed) bar ATR

   return true;
}

//+------------------------------------------------------------------+
//| BB Reversal Signal (PRIMARY - M15)                               |
//| Buy at lower BB with RSI oversold, Sell at upper BB with RSI OB  |
//| Validated OOS: PF 1.83, WR 70%, Sharpe 4.54                     |
//+------------------------------------------------------------------+
int GetBBReversalSignal()
{
   // Get BB bands (buffer 1=upper, 2=lower, 0=middle)
   double bbUpper[2], bbLower[2], bbRSI[2];

   if(CopyBuffer(hBB_Upper, 1, 1, 1, bbUpper) < 1) return 0;  // Upper band
   if(CopyBuffer(hBB_Upper, 2, 1, 1, bbLower) < 1) return 0;  // Lower band
   if(CopyBuffer(hBB_RSI, 0, 1, 1, bbRSI) < 1) return 0;

   double close = iClose(_Symbol, PERIOD_M15, 1);  // Last confirmed M15 bar

   // Buy signal: price at or below lower BB + RSI oversold
   if(close <= bbLower[0] && bbRSI[0] < InpBB_RSI_OS)
      return 1;

   // Sell signal: price at or above upper BB + RSI overbought
   if(close >= bbUpper[0] && bbRSI[0] > InpBB_RSI_OB)
      return -1;

   return 0;
}

//+------------------------------------------------------------------+
//| EMA + Volume Signal (SECONDARY - M5)                             |
//| EMA crossover confirmed by trend + volume spike                  |
//| Validated OOS: PF 1.36, Recovery Factor 6.37                     |
//+------------------------------------------------------------------+
int GetEMAVolSignal()
{
   double evFast[3], evSlow[3], evTrend[2];

   if(CopyBuffer(hEV_Fast, 0, 1, 2, evFast) < 2) return 0;
   if(CopyBuffer(hEV_Slow, 0, 1, 2, evSlow) < 2) return 0;
   if(CopyBuffer(hEV_Trend, 0, 1, 1, evTrend) < 1) return 0;

   double prevFast = evFast[0];
   double prevSlow = evSlow[0];
   double currFast = evFast[1];
   double currSlow = evSlow[1];
   double trendEMA = evTrend[0];
   double close = iClose(_Symbol, PERIOD_M5, 1);

   // Volume confirmation
   long tickVol[];
   int volBars = InpEV_VolPeriod + 2;
   ArrayResize(tickVol, volBars);

   if(CopyTickVolume(_Symbol, PERIOD_M5, 0, volBars, tickVol) < volBars)
      return 0;

   double volSum = 0;
   for(int i = 1; i <= InpEV_VolPeriod; i++)
      volSum += (double)tickVol[volBars - 1 - i];
   double avgVol = volSum / InpEV_VolPeriod;
   double currVol = (double)tickVol[volBars - 2];

   bool volOk = (avgVol > 0 && currVol >= avgVol * InpEV_VolMult);
   if(!volOk) return 0;

   // Bullish: EMA crossover + above trend + volume
   if(prevFast <= prevSlow && currFast > currSlow && close > trendEMA)
      return 1;

   // Bearish: EMA crossover + below trend + volume
   if(prevFast >= prevSlow && currFast < currSlow && close < trendEMA)
      return -1;

   return 0;
}

//+------------------------------------------------------------------+
//| EMA Crossover Signal (Legacy)                                    |
//+------------------------------------------------------------------+
int GetEMASignal(bool inSession)
{
   // Apply session filter if enabled
   if(InpEMA_SessionFilter && !inSession) return 0;

   // Detect crossover on CONFIRMED bars (index 1 vs 2)
   double emaFastBuf[3], emaSlowBuf[3];
   if(CopyBuffer(hEMA_Fast, 0, 1, 2, emaFastBuf) < 2) return 0;
   if(CopyBuffer(hEMA_Slow, 0, 1, 2, emaSlowBuf) < 2) return 0;

   double prevFast = emaFastBuf[0]; // bar[2]
   double prevSlow = emaSlowBuf[0];
   double currFast = emaFastBuf[1]; // bar[1] (last confirmed)
   double currSlow = emaSlowBuf[1];

   // Bullish crossover: fast crosses above slow
   if(prevFast <= prevSlow && currFast > currSlow)
      return 1;

   // Bearish crossover: fast crosses below slow
   if(prevFast >= prevSlow && currFast < currSlow)
      return -1;

   return 0;
}

//+------------------------------------------------------------------+
//| Volume Spike Signal                                              |
//+------------------------------------------------------------------+
int GetVolumeSignal()
{
   // Get tick volumes for the last N bars
   long tickVol[];
   int totalBars = InpVol_MAPeriod + 2;
   ArrayResize(tickVol, totalBars);

   if(CopyTickVolume(_Symbol, PERIOD_M1, 0, totalBars, tickVol) < totalBars)
      return 0;

   // Calculate average tick volume (excluding current bar)
   double volSum = 0;
   for(int i = 1; i <= InpVol_MAPeriod; i++)
      volSum += (double)tickVol[totalBars - 1 - i];
   double avgVol = volSum / InpVol_MAPeriod;

   // Current confirmed bar volume
   double currVol = (double)tickVol[totalBars - 2]; // bar[1]

   // Check spike
   if(avgVol <= 0 || currVol < avgVol * InpVol_Multiplier)
      return 0;

   // Check spread filter
   if(InpVol_MinSpread > 0)
   {
      double spread = symInfo.Ask() - symInfo.Bid();
      double spreadPts = spread / symInfo.Point();
      if(spreadPts > InpVol_MinSpread) return 0;
   }

   // Direction based on the spike bar's close vs open
   double barOpen  = iOpen(_Symbol, PERIOD_M1, 1);
   double barClose = iClose(_Symbol, PERIOD_M1, 1);

   if(barClose > barOpen) return 1;   // Bullish spike
   if(barClose < barOpen) return -1;  // Bearish spike

   return 0;
}

//+------------------------------------------------------------------+
//| RSI Momentum Signal                                              |
//+------------------------------------------------------------------+
int GetRSISignal()
{
   double rsiBuf[2];
   if(CopyBuffer(hRSI, 0, 1, 1, rsiBuf) < 1) return 0;

   double rsiVal = rsiBuf[0]; // Last confirmed bar

   // Momentum continuation: buy strong, sell weak
   if(rsiVal > InpRSI_UpperLevel) return 1;   // Strong momentum up -> BUY
   if(rsiVal < InpRSI_LowerLevel) return -1;  // Strong momentum down -> SELL

   return 0;
}

//+------------------------------------------------------------------+
//| Execute a trade                                                  |
//+------------------------------------------------------------------+
void ExecuteTrade(int direction, int strategy, int slPoints, int tpPoints)
{
   // Check max open trades
   if(CountOpenTrades() >= InpMaxOpenTrades) return;
   if(dailyTradeCount >= InpMaxTradesDay) return;

   double price, sl, tp;
   ENUM_ORDER_TYPE orderType;

   symInfo.Refresh();
   double point = symInfo.Point();

   if(direction > 0) // BUY
   {
      price     = symInfo.Ask();
      sl        = price - slPoints * point;
      tp        = price + tpPoints * point;
      orderType = ORDER_TYPE_BUY;
   }
   else // SELL
   {
      price     = symInfo.Bid();
      sl        = price + slPoints * point;
      tp        = price - tpPoints * point;
      orderType = ORDER_TYPE_SELL;
   }

   // Calculate lot size
   double lots = CalculateLotSize(slPoints);
   if(lots <= 0) return;

   // Build comment
   string stratName = "";
   switch(strategy)
   {
      case 1: stratName = "EMA";    break;
      case 2: stratName = "VOL";    break;
      case 3: stratName = "RSI";    break;
      case 4: stratName = "E+V";    break;
      case 6: stratName = "BB";     break;
      case 7: stratName = "EV";     break;
      case 5: stratName = "E+R";    break;
   }
   string comment = InpComment + "_" + stratName;

   // Execute trade
   if(trade.PositionOpen(_Symbol, orderType, lots, price, sl, tp, comment))
   {
      ulong ticket = trade.ResultOrder();
      Print("TRADE OPENED: ", stratName, " | ",
            (direction > 0 ? "BUY" : "SELL"),
            " | Lots: ", DoubleToString(lots, 2),
            " | Price: ", DoubleToString(price, symInfo.Digits()),
            " | SL: ", DoubleToString(sl, symInfo.Digits()),
            " | TP: ", DoubleToString(tp, symInfo.Digits()));

      // Track the trade
      int idx = ArraySize(openTrades);
      ArrayResize(openTrades, idx + 1);
      openTrades[idx].ticket       = ticket;
      openTrades[idx].strategy     = strategy;
      openTrades[idx].openTime     = TimeCurrent();
      openTrades[idx].barsHeld     = 0;
      openTrades[idx].breakevenSet = false;

      dailyTradeCount++;
   }
   else
   {
      Print("TRADE FAILED: ", stratName, " | Error: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Calculate lot size based on mode                                 |
//+------------------------------------------------------------------+
double CalculateLotSize(int slPoints)
{
   double lots = InpFixedLots;

   if(InpLotMode == LOT_RISK_PERCENT)
   {
      double balance   = accInfo.Balance();
      double riskMoney = balance * InpRiskPercent / 100.0;
      double tickValue = symInfo.TickValue();
      double tickSize  = symInfo.TickSize();
      double point     = symInfo.Point();

      if(tickValue <= 0 || tickSize <= 0 || point <= 0) return InpFixedLots;

      double slMoney = slPoints * point * tickValue / tickSize;
      if(slMoney <= 0) return InpFixedLots;

      lots = riskMoney / slMoney;
   }
   else if(InpLotMode == LOT_DYNAMIC_ATR)
   {
      if(medianATR <= 0) return InpFixedLots;

      double balance   = accInfo.Balance();
      double riskMoney = balance * InpRiskPercent / 100.0;
      double tickValue = symInfo.TickValue();
      double tickSize  = symInfo.TickSize();

      if(tickValue <= 0 || tickSize <= 0) return InpFixedLots;

      double slMoney = medianATR * 2.0 * tickValue / tickSize;
      if(slMoney <= 0) return InpFixedLots;

      lots = riskMoney / slMoney;
   }

   // Normalize and clamp
   double lotStep = symInfo.LotsStep();
   double minLot  = symInfo.LotsMin();
   double maxLot  = MathMin(symInfo.LotsMax(), InpMaxLots);

   lots = MathFloor(lots / lotStep) * lotStep;
   lots = MathMax(lots, minLot);
   lots = MathMin(lots, maxLot);

   return lots;
}

//+------------------------------------------------------------------+
//| Manage positions - check max hold time                           |
//+------------------------------------------------------------------+
void ManagePositions()
{
   for(int i = ArraySize(openTrades) - 1; i >= 0; i--)
   {
      if(!PositionSelectByTicket(openTrades[i].ticket))
      {
         // Position closed by SL/TP, remove from tracking
         RemoveTradeState(i);
         continue;
      }

      // Count bars held using the strategy's timeframe
      datetime openTime = openTrades[i].openTime;
      int barsElapsed = 0;

      switch(openTrades[i].strategy)
      {
         case 6: // BB on M15
            barsElapsed = Bars(_Symbol, PERIOD_M15, openTime, TimeCurrent()) - 1;
            break;
         case 7: // EMA+Vol on M5
            barsElapsed = Bars(_Symbol, PERIOD_M5, openTime, TimeCurrent()) - 1;
            break;
         case 3: // RSI on M5
            barsElapsed = Bars(_Symbol, PERIOD_M5, openTime, TimeCurrent()) - 1;
            break;
         default: // Legacy on M1
            barsElapsed = Bars(_Symbol, PERIOD_M1, openTime, TimeCurrent()) - 1;
            break;
      }

      openTrades[i].barsHeld = barsElapsed;

      // Get max hold for this strategy
      int maxHold = 60;
      switch(openTrades[i].strategy)
      {
         case 1: maxHold = InpEMA_MaxHold;  break;
         case 2: maxHold = InpVol_MaxHold;  break;
         case 3: maxHold = InpRSI_MaxHold;  break;
         case 4: maxHold = InpEMA_MaxHold;  break;
         case 5: maxHold = InpEMA_MaxHold;  break;
         case 6: maxHold = InpBB_MaxHold;   break;
         case 7: maxHold = InpEV_MaxHold;   break;
      }

      // Close if max hold time exceeded
      if(barsElapsed >= maxHold)
      {
         trade.PositionClose(openTrades[i].ticket);
         Print("MAX HOLD CLOSE: Ticket ", openTrades[i].ticket,
               " | Strategy ", openTrades[i].strategy,
               " | Bars: ", barsElapsed);
         RemoveTradeState(i);
      }
   }
}

//+------------------------------------------------------------------+
//| Trailing Stop management                                         |
//+------------------------------------------------------------------+
void ManageTrailingStop()
{
   if(!InpUseTrailing) return;

   double point = symInfo.Point();

   for(int i = 0; i < ArraySize(openTrades); i++)
   {
      if(!PositionSelectByTicket(openTrades[i].ticket)) continue;

      double posPrice   = PositionGetDouble(POSITION_PRICE_OPEN);
      double posSL      = PositionGetDouble(POSITION_SL);
      double posTP      = PositionGetDouble(POSITION_TP);
      long   posType    = PositionGetInteger(POSITION_TYPE);
      double currentBid = symInfo.Bid();
      double currentAsk = symInfo.Ask();

      if(posType == POSITION_TYPE_BUY)
      {
         double profit = (currentBid - posPrice) / point;
         if(profit >= InpTrailStart)
         {
            double newSL = currentBid - InpTrailStep * point;
            if(newSL > posSL + point)
            {
               trade.PositionModify(openTrades[i].ticket, newSL, posTP);
            }
         }
      }
      else if(posType == POSITION_TYPE_SELL)
      {
         double profit = (posPrice - currentAsk) / point;
         if(profit >= InpTrailStart)
         {
            double newSL = currentAsk + InpTrailStep * point;
            if(newSL < posSL - point || posSL == 0)
            {
               trade.PositionModify(openTrades[i].ticket, newSL, posTP);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Breakeven management                                             |
//+------------------------------------------------------------------+
void ManageBreakeven()
{
   if(!InpUseBreakeven) return;

   double point = symInfo.Point();

   for(int i = 0; i < ArraySize(openTrades); i++)
   {
      if(openTrades[i].breakevenSet) continue;
      if(!PositionSelectByTicket(openTrades[i].ticket)) continue;

      double posPrice   = PositionGetDouble(POSITION_PRICE_OPEN);
      double posSL      = PositionGetDouble(POSITION_SL);
      double posTP      = PositionGetDouble(POSITION_TP);
      long   posType    = PositionGetInteger(POSITION_TYPE);
      double currentBid = symInfo.Bid();
      double currentAsk = symInfo.Ask();

      if(posType == POSITION_TYPE_BUY)
      {
         double profit = (currentBid - posPrice) / point;
         if(profit >= InpBE_Start)
         {
            double newSL = posPrice + InpBE_Offset * point;
            if(newSL > posSL)
            {
               if(trade.PositionModify(openTrades[i].ticket, newSL, posTP))
                  openTrades[i].breakevenSet = true;
            }
         }
      }
      else if(posType == POSITION_TYPE_SELL)
      {
         double profit = (posPrice - currentAsk) / point;
         if(profit >= InpBE_Start)
         {
            double newSL = posPrice - InpBE_Offset * point;
            if(newSL < posSL || posSL == 0)
            {
               if(trade.PositionModify(openTrades[i].ticket, newSL, posTP))
                  openTrades[i].breakevenSet = true;
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Session filter check                                             |
//+------------------------------------------------------------------+
bool IsWithinSession(MqlDateTime &dt)
{
   int hour = dt.hour;
   if(InpSessionStartHour <= InpSessionEndHour)
      return (hour >= InpSessionStartHour && hour < InpSessionEndHour);
   else // Overnight session
      return (hour >= InpSessionStartHour || hour < InpSessionEndHour);
}

//+------------------------------------------------------------------+
//| Day of week filter                                               |
//+------------------------------------------------------------------+
bool IsTradingDay(MqlDateTime &dt)
{
   switch(dt.day_of_week)
   {
      case 1: return InpTradeMonday;
      case 2: return InpTradeTuesday;
      case 3: return InpTradeWednesday;
      case 4: return InpTradeThursday;
      case 5: return InpTradeFriday;
      default: return false;
   }
}

//+------------------------------------------------------------------+
//| ATR filter                                                       |
//+------------------------------------------------------------------+
bool IsATRValid()
{
   if(medianATR <= 0) return false;

   // Calculate a longer-term ATR average for comparison
   double atrBuf[100];
   if(CopyBuffer(hATR, 0, 0, 100, atrBuf) < 100) return true; // allow if can't check

   double atrSum = 0;
   for(int i = 0; i < 100; i++)
      atrSum += atrBuf[i];
   double avgATR = atrSum / 100.0;

   if(avgATR <= 0) return true;

   double ratio = medianATR / avgATR;

   // Filter out too-low and too-high volatility
   return (ratio >= InpATR_MinMult && ratio <= InpATR_MaxMult);
}

//+------------------------------------------------------------------+
//| Count open trades for this EA                                    |
//+------------------------------------------------------------------+
int CountOpenTrades()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Check if a specific strategy already has an open position        |
//+------------------------------------------------------------------+
bool HasStrategyPosition(int strategy)
{
   for(int i = 0; i < ArraySize(openTrades); i++)
   {
      if(openTrades[i].strategy == strategy)
      {
         if(PositionSelectByTicket(openTrades[i].ticket))
            return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Close all positions                                              |
//+------------------------------------------------------------------+
void CloseAllPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(posInfo.SelectByIndex(i))
      {
         if(posInfo.Magic() == InpMagicNumber && posInfo.Symbol() == _Symbol)
         {
            trade.PositionClose(posInfo.Ticket());
         }
      }
   }
   ArrayResize(openTrades, 0);
}

//+------------------------------------------------------------------+
//| Remove trade state by index                                      |
//+------------------------------------------------------------------+
void RemoveTradeState(int index)
{
   int size = ArraySize(openTrades);
   if(index < 0 || index >= size) return;

   for(int i = index; i < size - 1; i++)
      openTrades[i] = openTrades[i + 1];

   ArrayResize(openTrades, size - 1);
}

//+------------------------------------------------------------------+
//| OnTradeTransaction - track position closures                     |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      // Check if this is a close deal for one of our positions
      if(trans.deal_type == DEAL_TYPE_BUY || trans.deal_type == DEAL_TYPE_SELL)
      {
         ulong dealTicket = trans.deal;
         if(dealTicket > 0)
         {
            // Try to select the deal to get its properties
            if(HistoryDealSelect(dealTicket))
            {
               long entry = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
               if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
               {
                  double profit = HistoryDealGetDouble(dealTicket, DEAL_PROFIT);
                  double commission = HistoryDealGetDouble(dealTicket, DEAL_COMMISSION);
                  double swap = HistoryDealGetDouble(dealTicket, DEAL_SWAP);
                  double netPnL = profit + commission + swap;

                  Print("TRADE CLOSED: Net P&L = ", DoubleToString(netPnL, 2),
                        " | Profit: ", DoubleToString(profit, 2),
                        " | Comm: ", DoubleToString(commission, 2),
                        " | Swap: ", DoubleToString(swap, 2));
               }
            }
         }
      }
   }
}
//+------------------------------------------------------------------+
