//+------------------------------------------------------------------+
//| MultiStrategy_EA.mq5                                              |
//| Multi-Strategy Expert Advisor for MetaTrader 5                     |
//| 6 Selectable Trading Strategies                                    |
//+------------------------------------------------------------------+
#property copyright "Robin"
#property version   "1.00"
#property description "Multi-Strategy EA with 6 selectable strategies"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| Enumerations                                                       |
//+------------------------------------------------------------------+
enum ENUM_STRATEGY
  {
   STRAT_MTBB_SINGLE   = 0, // 1: MT+BB Single Trade
   STRAT_MTBB_PRESETS   = 1, // 2: MT+BB Presets+Adds
   STRAT_USOPEN_MTBB    = 2, // 3: US Open MT+BB
   STRAT_DEEP_WEEKLY_PB = 3, // 4: Deep Weekly Pullback
   STRAT_TREND_RIDE     = 4, // 5: Trend Ride v3.4
   STRAT_EMA_FRACTAL    = 5  // 6: EMA Fractal v4
  };

enum ENUM_MTBB_ENTRY
  {
   ENTRY_BREAKOUT  = 0, // Breakout
   ENTRY_MEAN_REV  = 1, // Mean Reversion
   ENTRY_COMBINED  = 2  // Combined
  };

enum ENUM_SL_TYPE
  {
   SL_ATR    = 0, // ATR
   SL_FIXED  = 1, // Fixed Points
   SL_BB_MID = 2  // BB Middle
  };

enum ENUM_TP_TYPE
  {
   TP_RR     = 0, // RR Ratio
   TP_FIXED  = 1, // Fixed Points
   TP_BB_OPP = 2  // Opposite BB
  };

enum ENUM_PRESET_MTBB
  {
   PRE_ESH_MAX   = 0, // ESH Max Profit
   PRE_ESH_BAL   = 1, // ESH Balanced
   PRE_ESH_TIGHT = 2, // ESH Ultra-tight
   PRE_ESH_FULL  = 3, // ESH Full Hour
   PRE_CUSTOM_2  = 4  // Custom
  };

enum ENUM_PRESET_USOPEN
  {
   PRE_MAXNET   = 0, // MaxNet
   PRE_BESTPF   = 1, // BestPF
   PRE_LOWDD    = 2, // LowDD
   PRE_CUSTOM_3 = 3  // Custom
  };

enum ENUM_TREND_ENTRY
  {
   TENT_BOTH    = 0, // Both
   TENT_PBD_BO  = 1, // PBD+Breakout
   TENT_PBD_REC = 2  // PBD+Reclaim
  };

enum ENUM_SL_MODE_FRAC
  {
   SLM_FULL = 0, // Full Fractal
   SLM_HALF = 1  // Half Distance
  };

enum ENUM_TRAIL_MODE
  {
   TRL_FRACTAL    = 0, // Fractal
   TRL_ATR        = 1, // ATR
   TRL_CHANDELIER = 2, // Chandelier
   TRL_EMA        = 3  // EMA
  };

enum ENUM_PARTIAL_MODE
  {
   PRT_BE    = 0, // At Breakeven
   PRT_TRAIL = 1  // At Trail Hit
  };

//+------------------------------------------------------------------+
//| Input Parameters                                                   |
//+------------------------------------------------------------------+

//--- Common
input group "=== Strategy Selection ==="
input ENUM_STRATEGY   InpStrategy    = STRAT_MTBB_SINGLE; // Strategy
input int              InpMagicNumber = 123456;             // Magic Number
input double           InpDefaultLot  = 0.1;               // Default Lot Size

//--- Strategy 1: MT+BB Single Trade
input group "=== 1: MT+BB Single Trade ==="
input int              Inp1_TimeOffset   = 1;              // Server to Berlin hours offset
input int              Inp1_StartHour    = 15;             // Session Start Hour
input int              Inp1_StartMin     = 30;             // Session Start Minute
input int              Inp1_EndHour      = 18;             // Session End Hour
input int              Inp1_EndMin       = 20;             // Session End Minute
input bool             Inp1_CloseAtEnd   = true;           // Close at Session End
input int              Inp1_CCIPeriod    = 28;             // CCI Period
input int              Inp1_ATRPeriod    = 7;              // ATR Period
input double           Inp1_ATRMult      = 0.5;            // ATR Multiplier (Magic Trend)
input int              Inp1_BBLength     = 7;              // Bollinger Bands Length
input double           Inp1_BBDev        = 1.0;            // Bollinger Bands Deviation
input ENUM_MTBB_ENTRY  Inp1_EntryMode    = ENTRY_BREAKOUT; // Entry Mode
input bool             Inp1_NeedMT       = false;          // Require Magic Trend Confirm
input bool             Inp1_BodyFilter   = false;          // Body Filter
input double           Inp1_BodyMinRatio = 0.3;            // Body Min Ratio
input bool             Inp1_SqueezeFilter = false;         // Squeeze Filter
input int              Inp1_SqueezeLen   = 50;             // Squeeze Lookback Length
input ENUM_SL_TYPE     Inp1_SLType       = SL_ATR;         // Stop Loss Type
input double           Inp1_SL_ATRMult   = 2.0;            // SL ATR Multiplier
input double           Inp1_SL_FixedPts  = 50.0;           // SL Fixed Points
input ENUM_TP_TYPE     Inp1_TPType       = TP_RR;          // Take Profit Type
input double           Inp1_TP_RR        = 10.4;           // TP Risk:Reward Ratio
input double           Inp1_TP_FixedPts  = 72.0;           // TP Fixed Points
input int              Inp1_MaxTrades    = 1;              // Max Trades per Session
input bool             Inp1_AllowLong    = true;           // Allow Long
input bool             Inp1_AllowShort   = false;          // Allow Short

//--- Strategy 2: MT+BB Presets
input group "=== 2: MT+BB Presets ==="
input int              Inp2_TimeOffset = 1;                // Server to Berlin hours offset
input bool             Inp2_Only1M     = true;             // Only on 1-Minute Chart
input bool             Inp2_AllowLong  = true;             // Allow Long
input bool             Inp2_AllowShort = true;             // Allow Short
input double           Inp2_Qty        = 0.1;              // Lot Size
input ENUM_PRESET_MTBB Inp2_Preset     = PRE_ESH_MAX;      // Preset
input int              Inp2_CCILen     = 20;               // CCI Length
input int              Inp2_ATRLen     = 10;               // ATR Length
input double           Inp2_ATRMult    = 1.2;              // ATR Multiplier
input int              Inp2_BBLen      = 50;               // BB Length
input double           Inp2_BBMult     = 1.8;              // BB Multiplier
input double           Inp2_SL_ATR     = 1.5;              // SL ATR Multiplier
input double           Inp2_TP_ATR     = 4.0;              // TP ATR Multiplier
input int              Inp2_MaxAdds    = 1;                // Max Add-on Entries

//--- Strategy 3: US Open MT+BB
input group "=== 3: US Open MT+BB ==="
input int              Inp3_TimeOffset   = 1;              // Server to Berlin hours offset
input bool             Inp3_Only1M       = true;           // Only on 1-Minute Chart
input bool             Inp3_AllowLong    = true;           // Allow Long
input bool             Inp3_AllowShort   = true;           // Allow Short
input double           Inp3_Qty          = 0.1;            // Lot Size
input ENUM_PRESET_USOPEN Inp3_Preset     = PRE_MAXNET;     // Preset
input int              Inp3_CCILen       = 20;             // CCI Length
input int              Inp3_ATRLen       = 5;              // ATR Length
input double           Inp3_ATRMult      = 1.0;            // ATR Multiplier
input int              Inp3_BBLen        = 20;             // BB Length
input double           Inp3_BBMult       = 2.0;            // BB Multiplier
input double           Inp3_SL_ATR       = 1.0;            // SL ATR Multiplier
input double           Inp3_TP_ATR       = 2.0;            // TP ATR Multiplier

//--- Strategy 4: Deep Weekly Pullback
input group "=== 4: Deep Weekly Pullback ==="
input ENUM_TIMEFRAMES  Inp4_TF_Exec       = PERIOD_H2;     // Execution Timeframe
input ENUM_TIMEFRAMES  Inp4_TF_Daily      = PERIOD_D1;     // Daily Timeframe
input ENUM_TIMEFRAMES  Inp4_TF_Weekly     = PERIOD_W1;     // Weekly Timeframe
input int              Inp4_W_ATRLen      = 14;            // Weekly ATR Length
input int              Inp4_W_EMALen      = 50;            // Weekly EMA Length
input bool             Inp4_UseWeeklyTrend = true;         // Use Weekly Trend Filter
input double           Inp4_DeepDDPct     = 10.0;          // Deep Drawdown %
input double           Inp4_DeepATRMult   = 1.0;           // Deep ATR Multiplier
input int              Inp4_D_FastLen     = 10;            // Daily Fast EMA Length
input int              Inp4_D_SlowLen     = 20;            // Daily Slow EMA Length
input int              Inp4_CrossLookback = 25;            // Cross Lookback Bars
input bool             Inp4_PBNeedTouch   = true;          // Pullback Needs Touch
input int              Inp4_PBMaxDays     = 30;            // Pullback Max Days
input bool             Inp4_ReqDailyAbove20 = true;        // Require Daily Above 20 EMA
input int              Inp4_H2_EMALen     = 20;            // H2 EMA Length
input int              Inp4_H2_ATRLen     = 14;            // H2 ATR Length
input double           Inp4_EntryBufATR   = 0.06;          // Entry Buffer (ATR mult)
input int              Inp4_PivotLen      = 8;             // Pivot Length
input double           Inp4_StopPadATR    = 0.25;          // Stop Padding (ATR mult)
input double           Inp4_BE_R          = 1.0;           // Breakeven at R
input double           Inp4_BE_PlusR      = 0.0;           // Breakeven Plus R
input bool             Inp4_BEOnPBBreak   = true;          // BE on Pullback Break
input double           Inp4_TrailStartR   = 2.8;           // Trail Start at R
input double           Inp4_TrailATR      = 3.6;           // Trail ATR Distance
input double           Inp4_NearATHPct    = 2.0;           // Near ATH %
input double           Inp4_TightTrailATR = 2.6;           // Tight Trail ATR
input int              Inp4_TimeStopBars  = 90;            // Time Stop (Bars)
input double           Inp4_RiskPct       = 10.0;          // Risk %
input double           Inp4_MinQty        = 0.0;           // Min Quantity

//--- Strategy 5: Trend Ride v3.4
input group "=== 5: Trend Ride v3.4 ==="
input ENUM_TIMEFRAMES  Inp5_TF_Exec       = PERIOD_H2;     // Execution Timeframe
input ENUM_TIMEFRAMES  Inp5_TF_Daily      = PERIOD_D1;     // Daily Timeframe
input ENUM_TIMEFRAMES  Inp5_TF_Weekly     = PERIOD_W1;     // Weekly Timeframe
input int              Inp5_W_EMAFast     = 5;             // Weekly Fast EMA
input int              Inp5_W_EMASlow     = 50;            // Weekly Slow EMA
input int              Inp5_D_EMAFast     = 10;            // Daily Fast EMA
input int              Inp5_D_EMASlow     = 20;            // Daily Slow EMA
input ENUM_TREND_ENTRY Inp5_EntryMode     = TENT_BOTH;     // Entry Mode
input int              Inp5_PBDDays       = 7;             // Pullback Days
input int              Inp5_EntryLookback = 7;             // Entry Lookback Bars
input bool             Inp5_RequireReclaim = true;         // Require Reclaim
input bool             Inp5_UseEMAZone    = true;          // Use EMA Zone
input double           Inp5_MaxExtATR     = 2.0;           // Max Extension (ATR)
input int              Inp5_ATRLen        = 14;            // ATR Length
input int              Inp5_ADXLen        = 14;            // ADX Length
input bool             Inp5_ADXRising     = false;         // Require ADX Rising
input double           Inp5_ADXMinBase    = 20.0;          // ADX Min Base
input double           Inp5_ADXMinStrong  = 16.0;          // ADX Min Strong
input double           Inp5_StopATR       = 1.5;           // Stop ATR Distance
input double           Inp5_BE_R          = 1.0;           // Breakeven at R
input double           Inp5_BE_PlusR      = 0.0;           // Breakeven Plus R
input double           Inp5_TrailR        = 3.5;           // Trail Start at R
input double           Inp5_TrailATR      = 2.6;           // Trail ATR Distance
input int              Inp5_TimeStopBars  = 60;            // Time Stop (Bars)
input double           Inp5_StarterPct    = 7.0;           // Starter Risk %
input double           Inp5_Addon1Pct     = 10.0;          // Add-on 1 Risk %
input double           Inp5_Addon2Pct     = 6.0;           // Add-on 2 Risk %
input bool             Inp5_Add2OnlyStrong = true;         // Add-on 2 Only Strong
input bool             Inp5_LockOnAdd1    = true;          // Lock on Add-on 1
input double           Inp5_LockBEExtraR  = 0.0;           // Lock BE Extra R
input double           Inp5_MinQty        = 0.0;           // Min Quantity
input double           Inp5_RegimeBoost   = 1.3;           // Regime Boost Multiplier
input double           Inp5_WGapATRMin    = 0.8;           // Weekly Gap ATR Min

//--- Strategy 6: EMA Fractal v4
input group "=== 6: EMA Fractal v4 ==="
input ENUM_TIMEFRAMES  Inp6_TF_Exec        = PERIOD_H2;    // Execution Timeframe
input int              Inp6_EMAFast        = 10;           // Fast EMA Length
input int              Inp6_EMAMid         = 20;           // Mid EMA Length
input int              Inp6_EMASlow        = 50;           // Slow EMA Length
input bool             Inp6_TradeLong      = true;         // Trade Long
input bool             Inp6_TradeShort     = true;         // Trade Short
input int              Inp6_FracLookback   = 2;            // Fractal Lookback
input int              Inp6_MaxCandlesFrac = 30;           // Max Candles for Fractal
input bool             Inp6_UseDistFilter  = true;         // Use Distance Filter
input double           Inp6_MaxDistPct     = 5.0;          // Max Distance %
input int              Inp6_MaxBarsPending = 30;           // Max Bars Pending
input double           Inp6_MaxEntryDistPct = 10.0;        // Max Entry Distance %
input ENUM_SL_MODE_FRAC Inp6_SLMode        = SLM_FULL;     // Stop Loss Mode
input double           Inp6_RiskPct        = 2.0;          // Risk %
input ENUM_TRAIL_MODE  Inp6_TrailMode      = TRL_ATR;      // Trail Mode
input int              Inp6_ATRPeriod      = 14;           // ATR Period
input double           Inp6_ATRMult        = 2.0;          // ATR Multiplier
input int              Inp6_EMATrailLen    = 10;           // EMA Trail Length
input bool             Inp6_UseBreakeven   = true;         // Use Breakeven
input double           Inp6_BEMinR         = 1.0;          // BE Min R Multiple
input ENUM_PARTIAL_MODE Inp6_PartialMode   = PRT_BE;       // Partial Close Mode
input double           Inp6_PartialTPPct   = 50.0;         // Partial TP %
input bool             Inp6_UseSession     = false;        // Use Session Filter
input int              Inp6_SessStart      = 8;            // Session Start Hour
input int              Inp6_SessEnd        = 20;           // Session End Hour

//+------------------------------------------------------------------+
//| Global Variables                                                   |
//+------------------------------------------------------------------+
CTrade   g_trade;
datetime g_lastBarTime;

// Indicator handles (initialized to INVALID_HANDLE)
// Strategy 1-3 (Magic Trend + BB)
int h_cci, h_atr, h_bb;
// Strategy 4 (Deep Weekly PB)
int h4_w_ema50, h4_w_atr, h4_d_ema_fast, h4_d_ema_slow, h4_h2_ema, h4_h2_atr;
// Strategy 5 (Trend Ride)
int h5_w_ema_fast, h5_w_ema_slow, h5_w_atr, h5_d_ema_fast, h5_d_ema_slow, h5_d_atr, h5_h2_atr, h5_h2_adx;
// Strategy 6 (EMA Fractal)
int h6_w_ema5, h6_w_ema50, h6_d_ema10, h6_d_ema20, h6_h2_ema_fast, h6_h2_ema_mid, h6_h2_ema_trail, h6_h2_atr;

// Magic Trend state
double g_magicTrend;
bool   g_mtBullish;
bool   g_mtInit;

// Strategy 1 state
int      g_s1_sessionTrades;
datetime g_s1_sessionDate;

// Strategy 2 state
int g_s2_addCount;

// Strategy 3 state
double g_s3_atrAtEntry;
bool   g_s3_hasPosition;

// Strategy 4 state
bool   g_s4_wkDeep, g_s4_dCross, g_s4_dPB;
double g_s4_pbLow, g_s4_pbHigh, g_s4_wATH;
int    g_s4_pbAge;
double g_s4_anchor, g_s4_stop, g_s4_rDist, g_s4_hiSince, g_s4_pbBreak;
int    g_s4_barsIn;

// Strategy 5 state
double g_s5_anchor, g_s5_anchorR, g_s5_stop, g_s5_hiSince, g_s5_loSince;
int    g_s5_barsIn;
bool   g_s5_didAdd1, g_s5_didAdd2;

// Strategy 6 state
int    g_s6_dir, g_s6_barsSetup, g_s6_barsPend;
bool   g_s6_waiting, g_s6_pend, g_s6_beActive, g_s6_partialDone;
double g_s6_entryPx, g_s6_slPx, g_s6_lastFL, g_s6_lastFH, g_s6_trailSL, g_s6_initRisk;

//+------------------------------------------------------------------+
//| Forward declarations for strategy functions                        |
//+------------------------------------------------------------------+
void Strategy_MTBBSingleTrade();
void Strategy_MTBBPresets();
void Strategy_USOpenMTBB();
void Strategy_DeepWeeklyPB();
void Strategy_TrendRide();
void Strategy_EMAFractal();

//+------------------------------------------------------------------+
//| Expert initialization function                                     |
//+------------------------------------------------------------------+
int OnInit()
  {
//--- Configure trade object
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(10);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

//--- Initialize all indicator handles to INVALID_HANDLE
   h_cci = INVALID_HANDLE;
   h_atr = INVALID_HANDLE;
   h_bb  = INVALID_HANDLE;

   h4_w_ema50   = INVALID_HANDLE;
   h4_w_atr     = INVALID_HANDLE;
   h4_d_ema_fast = INVALID_HANDLE;
   h4_d_ema_slow = INVALID_HANDLE;
   h4_h2_ema    = INVALID_HANDLE;
   h4_h2_atr    = INVALID_HANDLE;

   h5_w_ema_fast = INVALID_HANDLE;
   h5_w_ema_slow = INVALID_HANDLE;
   h5_w_atr      = INVALID_HANDLE;
   h5_d_ema_fast = INVALID_HANDLE;
   h5_d_ema_slow = INVALID_HANDLE;
   h5_d_atr      = INVALID_HANDLE;
   h5_h2_atr     = INVALID_HANDLE;
   h5_h2_adx     = INVALID_HANDLE;

   h6_w_ema5      = INVALID_HANDLE;
   h6_w_ema50     = INVALID_HANDLE;
   h6_d_ema10     = INVALID_HANDLE;
   h6_d_ema20     = INVALID_HANDLE;
   h6_h2_ema_fast = INVALID_HANDLE;
   h6_h2_ema_mid  = INVALID_HANDLE;
   h6_h2_ema_trail = INVALID_HANDLE;
   h6_h2_atr      = INVALID_HANDLE;

//--- Initialize state variables
   g_lastBarTime = 0;

   g_magicTrend = 0.0;
   g_mtBullish  = false;
   g_mtInit     = false;

   g_s1_sessionTrades = 0;
   g_s1_sessionDate   = 0;

   g_s2_addCount = 0;

   g_s3_atrAtEntry  = 0.0;
   g_s3_hasPosition = false;

   g_s4_wkDeep  = false;
   g_s4_dCross  = false;
   g_s4_dPB     = false;
   g_s4_pbLow   = 0.0;
   g_s4_pbHigh  = 0.0;
   g_s4_wATH    = 0.0;
   g_s4_pbAge   = 0;
   g_s4_anchor  = 0.0;
   g_s4_stop    = 0.0;
   g_s4_rDist   = 0.0;
   g_s4_hiSince = 0.0;
   g_s4_pbBreak = 0.0;
   g_s4_barsIn  = 0;

   g_s5_anchor  = 0.0;
   g_s5_anchorR = 0.0;
   g_s5_stop    = 0.0;
   g_s5_hiSince = 0.0;
   g_s5_loSince = 0.0;
   g_s5_barsIn  = 0;
   g_s5_didAdd1 = false;
   g_s5_didAdd2 = false;

   g_s6_dir         = 0;
   g_s6_barsSetup   = 0;
   g_s6_barsPend    = 0;
   g_s6_waiting     = false;
   g_s6_pend        = false;
   g_s6_beActive    = false;
   g_s6_partialDone = false;
   g_s6_entryPx     = 0.0;
   g_s6_slPx        = 0.0;
   g_s6_lastFL      = 0.0;
   g_s6_lastFH      = 0.0;
   g_s6_trailSL     = 0.0;
   g_s6_initRisk    = 0.0;

//--- Create indicator handles based on selected strategy
   switch(InpStrategy)
     {
      case STRAT_MTBB_SINGLE:
        {
         h_cci = iCCI(_Symbol, PERIOD_CURRENT, Inp1_CCIPeriod, PRICE_TYPICAL);
         h_atr = iATR(_Symbol, PERIOD_CURRENT, Inp1_ATRPeriod);
         h_bb  = iBands(_Symbol, PERIOD_CURRENT, Inp1_BBLength, 0, Inp1_BBDev, PRICE_CLOSE);
         if(h_cci == INVALID_HANDLE || h_atr == INVALID_HANDLE || h_bb == INVALID_HANDLE)
           {
            PrintFormat("Strategy 1: Failed to create indicator handles. CCI=%d ATR=%d BB=%d", h_cci, h_atr, h_bb);
            return(INIT_FAILED);
           }
         break;
        }
      case STRAT_MTBB_PRESETS:
        {
         int cci2=Inp2_CCILen, atr2=Inp2_ATRLen, bb2=Inp2_BBLen;
         double bbm2=Inp2_BBMult;
         if(Inp2_Preset==PRE_ESH_MAX)   { cci2=20; atr2=10; bb2=50; bbm2=1.8; }
         if(Inp2_Preset==PRE_ESH_BAL)   { cci2=20; atr2=5;  bb2=20; bbm2=2.0; }
         if(Inp2_Preset==PRE_ESH_TIGHT) { cci2=20; atr2=7;  bb2=40; bbm2=1.8; }
         if(Inp2_Preset==PRE_ESH_FULL)  { cci2=20; atr2=14; bb2=20; bbm2=2.0; }
         h_cci = iCCI(_Symbol, PERIOD_CURRENT, cci2, PRICE_TYPICAL);
         h_atr = iATR(_Symbol, PERIOD_CURRENT, atr2);
         h_bb  = iBands(_Symbol, PERIOD_CURRENT, bb2, 0, bbm2, PRICE_CLOSE);
         if(h_cci == INVALID_HANDLE || h_atr == INVALID_HANDLE || h_bb == INVALID_HANDLE)
           {
            PrintFormat("Strategy 2: Failed to create indicator handles.");
            return(INIT_FAILED);
           }
         break;
        }
      case STRAT_USOPEN_MTBB:
        {
         int cci3=Inp3_CCILen, atr3=Inp3_ATRLen, bb3=Inp3_BBLen;
         double bbm3=Inp3_BBMult;
         if(Inp3_Preset==PRE_MAXNET) { cci3=20; atr3=5;  bb3=20; bbm3=2.0; }
         if(Inp3_Preset==PRE_BESTPF) { cci3=20; atr3=20; bb3=50; bbm3=2.5; }
         if(Inp3_Preset==PRE_LOWDD)  { cci3=20; atr3=14; bb3=20; bbm3=2.5; }
         h_cci = iCCI(_Symbol, PERIOD_CURRENT, cci3, PRICE_TYPICAL);
         h_atr = iATR(_Symbol, PERIOD_CURRENT, atr3);
         h_bb  = iBands(_Symbol, PERIOD_CURRENT, bb3, 0, bbm3, PRICE_CLOSE);
         if(h_cci == INVALID_HANDLE || h_atr == INVALID_HANDLE || h_bb == INVALID_HANDLE)
           {
            PrintFormat("Strategy 3: Failed to create indicator handles.");
            return(INIT_FAILED);
           }
         break;
        }
      case STRAT_DEEP_WEEKLY_PB:
        {
         h4_w_ema50    = iMA(_Symbol, Inp4_TF_Weekly, Inp4_W_EMALen, 0, MODE_EMA, PRICE_CLOSE);
         h4_w_atr      = iATR(_Symbol, Inp4_TF_Weekly, Inp4_W_ATRLen);
         h4_d_ema_fast = iMA(_Symbol, Inp4_TF_Daily, Inp4_D_FastLen, 0, MODE_EMA, PRICE_CLOSE);
         h4_d_ema_slow = iMA(_Symbol, Inp4_TF_Daily, Inp4_D_SlowLen, 0, MODE_EMA, PRICE_CLOSE);
         h4_h2_ema     = iMA(_Symbol, Inp4_TF_Exec, Inp4_H2_EMALen, 0, MODE_EMA, PRICE_CLOSE);
         h4_h2_atr     = iATR(_Symbol, Inp4_TF_Exec, Inp4_H2_ATRLen);
         if(h4_w_ema50 == INVALID_HANDLE || h4_w_atr == INVALID_HANDLE ||
            h4_d_ema_fast == INVALID_HANDLE || h4_d_ema_slow == INVALID_HANDLE ||
            h4_h2_ema == INVALID_HANDLE || h4_h2_atr == INVALID_HANDLE)
           {
            PrintFormat("Strategy 4: Failed to create indicator handles.");
            return(INIT_FAILED);
           }
         break;
        }
      case STRAT_TREND_RIDE:
        {
         h5_w_ema_fast = iMA(_Symbol, Inp5_TF_Weekly, Inp5_W_EMAFast, 0, MODE_EMA, PRICE_CLOSE);
         h5_w_ema_slow = iMA(_Symbol, Inp5_TF_Weekly, Inp5_W_EMASlow, 0, MODE_EMA, PRICE_CLOSE);
         h5_w_atr      = iATR(_Symbol, Inp5_TF_Weekly, Inp5_ATRLen);
         h5_d_ema_fast = iMA(_Symbol, Inp5_TF_Daily, Inp5_D_EMAFast, 0, MODE_EMA, PRICE_CLOSE);
         h5_d_ema_slow = iMA(_Symbol, Inp5_TF_Daily, Inp5_D_EMASlow, 0, MODE_EMA, PRICE_CLOSE);
         h5_d_atr      = iATR(_Symbol, Inp5_TF_Daily, Inp5_ATRLen);
         h5_h2_atr     = iATR(_Symbol, Inp5_TF_Exec, Inp5_ATRLen);
         h5_h2_adx     = iADX(_Symbol, Inp5_TF_Exec, Inp5_ADXLen);
         if(h5_w_ema_fast == INVALID_HANDLE || h5_w_ema_slow == INVALID_HANDLE ||
            h5_w_atr == INVALID_HANDLE || h5_d_ema_fast == INVALID_HANDLE ||
            h5_d_ema_slow == INVALID_HANDLE || h5_d_atr == INVALID_HANDLE ||
            h5_h2_atr == INVALID_HANDLE || h5_h2_adx == INVALID_HANDLE)
           {
            PrintFormat("Strategy 5: Failed to create indicator handles.");
            return(INIT_FAILED);
           }
         break;
        }
      case STRAT_EMA_FRACTAL:
        {
         h6_w_ema5      = iMA(_Symbol, PERIOD_W1, 5, 0, MODE_EMA, PRICE_CLOSE);
         h6_w_ema50     = iMA(_Symbol, PERIOD_W1, 50, 0, MODE_EMA, PRICE_CLOSE);
         h6_d_ema10     = iMA(_Symbol, PERIOD_D1, 10, 0, MODE_EMA, PRICE_CLOSE);
         h6_d_ema20     = iMA(_Symbol, PERIOD_D1, 20, 0, MODE_EMA, PRICE_CLOSE);
         h6_h2_ema_fast = iMA(_Symbol, Inp6_TF_Exec, Inp6_EMAFast, 0, MODE_EMA, PRICE_CLOSE);
         h6_h2_ema_mid  = iMA(_Symbol, Inp6_TF_Exec, Inp6_EMAMid, 0, MODE_EMA, PRICE_CLOSE);
         h6_h2_ema_trail = iMA(_Symbol, Inp6_TF_Exec, Inp6_EMATrailLen, 0, MODE_EMA, PRICE_CLOSE);
         h6_h2_atr      = iATR(_Symbol, Inp6_TF_Exec, Inp6_ATRPeriod);
         if(h6_w_ema5 == INVALID_HANDLE || h6_w_ema50 == INVALID_HANDLE ||
            h6_d_ema10 == INVALID_HANDLE || h6_d_ema20 == INVALID_HANDLE ||
            h6_h2_ema_fast == INVALID_HANDLE || h6_h2_ema_mid == INVALID_HANDLE ||
            h6_h2_ema_trail == INVALID_HANDLE || h6_h2_atr == INVALID_HANDLE)
           {
            PrintFormat("Strategy 6: Failed to create indicator handles.");
            return(INIT_FAILED);
           }
         break;
        }
     }

   PrintFormat("MultiStrategy EA initialized. Strategy: %d, Magic: %d", (int)InpStrategy, InpMagicNumber);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                   |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
//--- Release all valid indicator handles
   if(h_cci != INVALID_HANDLE)         IndicatorRelease(h_cci);
   if(h_atr != INVALID_HANDLE)         IndicatorRelease(h_atr);
   if(h_bb  != INVALID_HANDLE)         IndicatorRelease(h_bb);

   if(h4_w_ema50 != INVALID_HANDLE)    IndicatorRelease(h4_w_ema50);
   if(h4_w_atr != INVALID_HANDLE)      IndicatorRelease(h4_w_atr);
   if(h4_d_ema_fast != INVALID_HANDLE) IndicatorRelease(h4_d_ema_fast);
   if(h4_d_ema_slow != INVALID_HANDLE) IndicatorRelease(h4_d_ema_slow);
   if(h4_h2_ema != INVALID_HANDLE)     IndicatorRelease(h4_h2_ema);
   if(h4_h2_atr != INVALID_HANDLE)     IndicatorRelease(h4_h2_atr);

   if(h5_w_ema_fast != INVALID_HANDLE) IndicatorRelease(h5_w_ema_fast);
   if(h5_w_ema_slow != INVALID_HANDLE) IndicatorRelease(h5_w_ema_slow);
   if(h5_w_atr != INVALID_HANDLE)      IndicatorRelease(h5_w_atr);
   if(h5_d_ema_fast != INVALID_HANDLE) IndicatorRelease(h5_d_ema_fast);
   if(h5_d_ema_slow != INVALID_HANDLE) IndicatorRelease(h5_d_ema_slow);
   if(h5_d_atr != INVALID_HANDLE)      IndicatorRelease(h5_d_atr);
   if(h5_h2_atr != INVALID_HANDLE)     IndicatorRelease(h5_h2_atr);
   if(h5_h2_adx != INVALID_HANDLE)     IndicatorRelease(h5_h2_adx);

   if(h6_w_ema5 != INVALID_HANDLE)      IndicatorRelease(h6_w_ema5);
   if(h6_w_ema50 != INVALID_HANDLE)     IndicatorRelease(h6_w_ema50);
   if(h6_d_ema10 != INVALID_HANDLE)     IndicatorRelease(h6_d_ema10);
   if(h6_d_ema20 != INVALID_HANDLE)     IndicatorRelease(h6_d_ema20);
   if(h6_h2_ema_fast != INVALID_HANDLE) IndicatorRelease(h6_h2_ema_fast);
   if(h6_h2_ema_mid != INVALID_HANDLE)  IndicatorRelease(h6_h2_ema_mid);
   if(h6_h2_ema_trail != INVALID_HANDLE) IndicatorRelease(h6_h2_ema_trail);
   if(h6_h2_atr != INVALID_HANDLE)      IndicatorRelease(h6_h2_atr);

   PrintFormat("MultiStrategy EA deinitialized. Reason: %d", reason);
  }

//+------------------------------------------------------------------+
//| Expert tick function                                               |
//+------------------------------------------------------------------+
void OnTick()
  {
//--- Determine the timeframe for new bar check
   ENUM_TIMEFRAMES barTF = PERIOD_CURRENT;

   switch(InpStrategy)
     {
      case STRAT_MTBB_SINGLE:
      case STRAT_MTBB_PRESETS:
      case STRAT_USOPEN_MTBB:
         barTF = PERIOD_CURRENT;
         break;
      case STRAT_DEEP_WEEKLY_PB:
         barTF = Inp4_TF_Exec;
         break;
      case STRAT_TREND_RIDE:
         barTF = Inp5_TF_Exec;
         break;
      case STRAT_EMA_FRACTAL:
         barTF = Inp6_TF_Exec;
         break;
     }

//--- Check for new bar
   if(!CheckNewBar(barTF))
      return;

//--- Dispatch to the selected strategy
   switch(InpStrategy)
     {
      case STRAT_MTBB_SINGLE:
         Strategy_MTBBSingleTrade();
         break;
      case STRAT_MTBB_PRESETS:
         Strategy_MTBBPresets();
         break;
      case STRAT_USOPEN_MTBB:
         Strategy_USOpenMTBB();
         break;
      case STRAT_DEEP_WEEKLY_PB:
         Strategy_DeepWeeklyPB();
         break;
      case STRAT_TREND_RIDE:
         Strategy_TrendRide();
         break;
      case STRAT_EMA_FRACTAL:
         Strategy_EMAFractal();
         break;
     }
  }

//+------------------------------------------------------------------+
//| Helper: Read single indicator value                                |
//+------------------------------------------------------------------+
double GetInd(int handle, int bufIdx, int shift)
  {
   double buf[1];
   if(CopyBuffer(handle, bufIdx, shift, 1, buf) < 1)
      return(0.0);
   return(buf[0]);
  }

//+------------------------------------------------------------------+
//| Helper: Check for new bar on given timeframe                       |
//+------------------------------------------------------------------+
bool CheckNewBar(ENUM_TIMEFRAMES tf)
  {
   datetime t[1];
   if(CopyTime(_Symbol, tf, 0, 1, t) < 1)
      return(false);
   if(t[0] == g_lastBarTime)
      return(false);
   g_lastBarTime = t[0];
   return(true);
  }

//+------------------------------------------------------------------+
//| Helper: Get local hour with offset                                 |
//+------------------------------------------------------------------+
int GetLocalHour(int offset)
  {
   MqlDateTime dt;
   TimeCurrent(dt);
   int h = (dt.hour + offset) % 24;
   if(h < 0)
      h += 24;
   return(h);
  }

//+------------------------------------------------------------------+
//| Helper: Get current minute                                         |
//+------------------------------------------------------------------+
int GetLocalMinute()
  {
   MqlDateTime dt;
   TimeCurrent(dt);
   return(dt.min);
  }

//+------------------------------------------------------------------+
//| Helper: Check if current time is within a session window           |
//+------------------------------------------------------------------+
bool IsInWindow(int sH, int sM, int eH, int eM, int offset)
  {
   int h   = GetLocalHour(offset);
   int m   = GetLocalMinute();
   int cur = h * 60 + m;
   int s   = sH * 60 + sM;
   int e   = eH * 60 + eM;
   return(cur >= s && cur < e);
  }

//+------------------------------------------------------------------+
//| Helper: Count open positions for given magic                       |
//+------------------------------------------------------------------+
int CountPos(int magic)
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == magic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         count++;
     }
   return(count);
  }

//+------------------------------------------------------------------+
//| Helper: Close all positions for given magic                        |
//+------------------------------------------------------------------+
void CloseAll(int magic, string comment)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == magic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
        {
         g_trade.PositionClose(ticket);
         if(comment != "")
            PrintFormat("CloseAll: Closed ticket %d - %s", (int)ticket, comment);
        }
     }
  }

//+------------------------------------------------------------------+
//| Helper: Update Magic Trend indicator                               |
//+------------------------------------------------------------------+
void UpdateMagicTrend(double cci, double atr, double lo, double hi, double mult)
  {
   if(!g_mtInit)
     {
      if(cci >= 0)
        {
         g_magicTrend = lo - atr * mult;
         g_mtBullish  = true;
        }
      else
        {
         g_magicTrend = hi + atr * mult;
         g_mtBullish  = false;
        }
      g_mtInit = true;
      return;
     }

   if(cci >= 0)
     {
      double up = lo - atr * mult;
      g_magicTrend = MathMax(up, g_magicTrend);
      g_mtBullish  = true;
     }
   else
     {
      double dn = hi + atr * mult;
      g_magicTrend = MathMin(dn, g_magicTrend);
      g_mtBullish  = false;
     }
  }

//+------------------------------------------------------------------+
//| Helper: Detect fractal high                                        |
//+------------------------------------------------------------------+
bool IsFracHigh(int shift, int lb, ENUM_TIMEFRAMES tf)
  {
   int size = 2 * lb + 1;
   double h[];
   ArrayResize(h, size);
   if(CopyHigh(_Symbol, tf, shift - lb, size, h) < size)
      return(false);
   double pivot = h[lb];
   for(int i = 0; i < size; i++)
     {
      if(i != lb && h[i] >= pivot)
         return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Helper: Detect fractal low                                         |
//+------------------------------------------------------------------+
bool IsFracLow(int shift, int lb, ENUM_TIMEFRAMES tf)
  {
   int size = 2 * lb + 1;
   double l[];
   ArrayResize(l, size);
   if(CopyLow(_Symbol, tf, shift - lb, size, l) < size)
      return(false);
   double pivot = l[lb];
   for(int i = 0; i < size; i++)
     {
      if(i != lb && l[i] <= pivot)
         return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Helper: Get highest high over a range                              |
//+------------------------------------------------------------------+
double GetHighest(ENUM_TIMEFRAMES tf, int count, int startShift)
  {
   double h[];
   ArrayResize(h, count);
   if(CopyHigh(_Symbol, tf, startShift, count, h) < count)
      return(0.0);
   double mx = h[0];
   for(int i = 1; i < count; i++)
     {
      if(h[i] > mx)
         mx = h[i];
     }
   return(mx);
  }

//+------------------------------------------------------------------+
//| Helper: Get lowest low over a range                                |
//+------------------------------------------------------------------+
double GetLowest(ENUM_TIMEFRAMES tf, int count, int startShift)
  {
   double l[];
   ArrayResize(l, count);
   if(CopyLow(_Symbol, tf, startShift, count, l) < count)
      return(0.0);
   double mn = l[0];
   for(int i = 1; i < count; i++)
     {
      if(l[i] < mn)
         mn = l[i];
     }
   return(mn);
  }

//+------------------------------------------------------------------+
//| Helper: Get average entry price of position                        |
//+------------------------------------------------------------------+
double GetPositionAvgPrice(int magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == magic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         return(PositionGetDouble(POSITION_PRICE_OPEN));
     }
   return(0.0);
  }

//+------------------------------------------------------------------+
//| Helper: Get position volume                                        |
//+------------------------------------------------------------------+
double GetPositionVolume(int magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == magic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         return(PositionGetDouble(POSITION_VOLUME));
     }
   return(0.0);
  }

//+------------------------------------------------------------------+
//| Helper: Get position ticket                                        |
//+------------------------------------------------------------------+
long GetPositionTicket(int magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == magic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         return((long)ticket);
     }
   return(-1);
  }

//+------------------------------------------------------------------+
//| Helper: Get position type (POSITION_TYPE_BUY/SELL or -1)           |
//+------------------------------------------------------------------+
int GetPositionType(int magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) == magic &&
         PositionGetString(POSITION_SYMBOL) == _Symbol)
         return((int)PositionGetInteger(POSITION_TYPE));
     }
   return(-1);
  }

//+------------------------------------------------------------------+
//| STRATEGY 1: MT+BB Single Trade                                     |
//+------------------------------------------------------------------+
void Strategy_MTBBSingleTrade()
  {
//--- Time window
   bool inWindow = IsInWindow(Inp1_StartHour, Inp1_StartMin, Inp1_EndHour, Inp1_EndMin, Inp1_TimeOffset);
   bool atClose  = IsInWindow(Inp1_EndHour, Inp1_EndMin, Inp1_EndHour, Inp1_EndMin + 5, Inp1_TimeOffset);

//--- Session reset on new day
   MqlDateTime dt;
   TimeCurrent(dt);
   datetime today = (datetime)(dt.day_of_year + dt.year * 366);
   if(today != g_s1_sessionDate)
     {
      g_s1_sessionDate   = today;
      g_s1_sessionTrades = 0;
     }

//--- Close at session end
   if(Inp1_CloseAtEnd && atClose && CountPos(InpMagicNumber) > 0)
     {
      CloseAll(InpMagicNumber, "S1 Session End");
      return;
     }

   if(!inWindow)
      return;

//--- Indicator values (shift=1 = last completed bar)
   double cci       = GetInd(h_cci, 0, 1);
   double atr       = GetInd(h_atr, 0, 1);
   double bbBasis   = GetInd(h_bb, 0, 1);
   double bbUpper   = GetInd(h_bb, 1, 1);
   double bbLower   = GetInd(h_bb, 2, 1);
   double bbUpperP  = GetInd(h_bb, 1, 2);
   double bbLowerP  = GetInd(h_bb, 2, 2);

   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
   double o1 = iOpen(_Symbol, PERIOD_CURRENT, 1);
   double h1 = iHigh(_Symbol, PERIOD_CURRENT, 1);
   double l1 = iLow(_Symbol, PERIOD_CURRENT, 1);

   if(atr <= 0 || bbBasis <= 0)
      return;

//--- Update Magic Trend
   UpdateMagicTrend(cci, atr, l1, h1, Inp1_ATRMult);

//--- Candle analysis
   double bodySize    = MathAbs(c1 - o1);
   double candleRange = h1 - l1;
   double bodyRatio   = candleRange > 0 ? bodySize / candleRange : 0;
   bool   isBull      = c1 > o1;
   bool   isBear      = c1 < o1;
   bool   bodyOK      = !Inp1_BodyFilter || bodyRatio >= Inp1_BodyMinRatio;

//--- BB Squeeze check
   bool squeezePrev = false;
   if(Inp1_SqueezeFilter)
     {
      double bw = bbBasis != 0 ? (bbUpper - bbLower) / bbBasis * 100.0 : 0;
      double bwSum = 0;
      for(int i = 1; i <= Inp1_SqueezeLen; i++)
        {
         double b = GetInd(h_bb, 0, i + 1);
         double u = GetInd(h_bb, 1, i + 1);
         double lo = GetInd(h_bb, 2, i + 1);
         if(b > 0) bwSum += (u - lo) / b * 100.0;
        }
      double bwAvg = bwSum / Inp1_SqueezeLen;
      // Check previous bar squeeze
      double bwP = 0;
      double bP = GetInd(h_bb, 0, 2);
      double uP = GetInd(h_bb, 1, 2);
      double lP = GetInd(h_bb, 2, 2);
      if(bP > 0) bwP = (uP - lP) / bP * 100.0;
      squeezePrev = bwP < bwAvg;
     }

//--- Entry signals
   bool boLong  = c1 > bbUpper && c2 <= bbUpperP && isBull;
   bool boShort = c1 < bbLower && c2 >= bbLowerP && isBear;
   bool mrLong  = c1 > bbLower && (c2 < bbLowerP || l1 < bbLower) && isBull;
   bool mrShort = c1 < bbUpper && (c2 > bbUpperP || h1 > bbUpper) && isBear;

   bool longSig = false, shortSig = false;
   if(Inp1_EntryMode == ENTRY_BREAKOUT)    { longSig = boLong;  shortSig = boShort; }
   else if(Inp1_EntryMode == ENTRY_MEAN_REV) { longSig = mrLong;  shortSig = mrShort; }
   else { longSig = boLong || mrLong; shortSig = boShort || mrShort; }

//--- Filters
   if(Inp1_NeedMT) { longSig = longSig && g_mtBullish; shortSig = shortSig && !g_mtBullish; }
   longSig  = longSig  && bodyOK;
   shortSig = shortSig && bodyOK;
   if(Inp1_SqueezeFilter) { longSig = longSig && squeezePrev; shortSig = shortSig && squeezePrev; }
   longSig  = longSig  && Inp1_AllowLong;
   shortSig = shortSig && Inp1_AllowShort;

   bool canTrade = g_s1_sessionTrades < Inp1_MaxTrades && CountPos(InpMagicNumber) == 0;

//--- Long entry
   if(canTrade && longSig)
     {
      double slLong = 0;
      if(Inp1_SLType == SL_ATR)        slLong = c1 - atr * Inp1_SL_ATRMult;
      else if(Inp1_SLType == SL_FIXED) slLong = c1 - Inp1_SL_FixedPts * _Point;
      else                              slLong = bbBasis;

      double slDist = MathAbs(c1 - slLong);
      double tpLong = 0;
      if(Inp1_TPType == TP_RR)          tpLong = c1 + slDist * Inp1_TP_RR;
      else if(Inp1_TPType == TP_FIXED)  tpLong = c1 + Inp1_TP_FixedPts * _Point;
      else { tpLong = bbUpper; if(tpLong <= c1) tpLong = c1 + slDist * 1.5; }

      slLong = NormalizeDouble(slLong, _Digits);
      tpLong = NormalizeDouble(tpLong, _Digits);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(g_trade.Buy(InpDefaultLot, _Symbol, ask, slLong, tpLong, "S1 Long"))
        {
         g_s1_sessionTrades++;
         PrintFormat("S1 LONG @ %.5f SL:%.5f TP:%.5f", ask, slLong, tpLong);
        }
     }

//--- Short entry
   if(canTrade && shortSig)
     {
      double slShort = 0;
      if(Inp1_SLType == SL_ATR)        slShort = c1 + atr * Inp1_SL_ATRMult;
      else if(Inp1_SLType == SL_FIXED) slShort = c1 + Inp1_SL_FixedPts * _Point;
      else                              slShort = bbBasis;

      double slDist = MathAbs(slShort - c1);
      double tpShort = 0;
      if(Inp1_TPType == TP_RR)          tpShort = c1 - slDist * Inp1_TP_RR;
      else if(Inp1_TPType == TP_FIXED)  tpShort = c1 - Inp1_TP_FixedPts * _Point;
      else { tpShort = bbLower; if(tpShort >= c1) tpShort = c1 - slDist * 1.5; }

      slShort = NormalizeDouble(slShort, _Digits);
      tpShort = NormalizeDouble(tpShort, _Digits);
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(g_trade.Sell(InpDefaultLot, _Symbol, bid, slShort, tpShort, "S1 Short"))
        {
         g_s1_sessionTrades++;
         PrintFormat("S1 SHORT @ %.5f SL:%.5f TP:%.5f", bid, slShort, tpShort);
        }
     }
  }

//+------------------------------------------------------------------+
//| STRATEGY 2: MT+BB Presets + Adds                                   |
//+------------------------------------------------------------------+
void Strategy_MTBBPresets()
  {
//--- Resolve preset parameters
   int trSH=15, trSM=30, trEH=16, trEM=30;
   int adSH=15, adSM=30, adEH=15, adEM=40;
   int clSH=16, clSM=29, clEH=16, clEM=30;
   double atrMult=1.0, slATR=1.0, tpATR=2.0;
   int maxAdds=0;

   switch(Inp2_Preset)
     {
      case PRE_ESH_MAX:
         trSH=15; trSM=47; trEH=16; trEM=12;
         adSH=15; adSM=47; adEH=15; adEM=57;
         clSH=16; clSM=11; clEH=16; clEM=12;
         atrMult=1.2; slATR=1.5; tpATR=4.0; maxAdds=1;
         break;
      case PRE_ESH_BAL:
         trSH=15; trSM=37; trEH=16; trEM=12;
         adSH=15; adSM=37; adEH=15; adEM=42;
         clSH=16; clSM=11; clEH=16; clEM=12;
         atrMult=1.0; slATR=1.2; tpATR=2.0; maxAdds=1;
         break;
      case PRE_ESH_TIGHT:
         trSH=15; trSM=47; trEH=15; trEM=59;
         adSH=15; adSM=47; adEH=15; adEM=59;
         clSH=15; clSM=58; clEH=15; clEM=59;
         atrMult=1.2; slATR=2.0; tpATR=2.5; maxAdds=2;
         break;
      case PRE_ESH_FULL:
         trSH=15; trSM=30; trEH=16; trEM=30;
         adSH=15; adSM=30; adEH=15; adEM=40;
         clSH=16; clSM=29; clEH=16; clEM=30;
         atrMult=1.0; slATR=1.0; tpATR=2.0; maxAdds=0;
         break;
      case PRE_CUSTOM_2:
         trSH=15; trSM=30; trEH=16; trEM=30;
         adSH=15; adSM=30; adEH=15; adEM=40;
         clSH=16; clSM=29; clEH=16; clEM=30;
         atrMult=Inp2_ATRMult; slATR=Inp2_SL_ATR; tpATR=Inp2_TP_ATR; maxAdds=Inp2_MaxAdds;
         break;
     }

   int off = Inp2_TimeOffset;
   bool inTrade = IsInWindow(trSH, trSM, trEH, trEM, off);
   bool inAdd   = IsInWindow(adSH, adSM, adEH, adEM, off);
   bool inClose = IsInWindow(clSH, clSM, clEH, clEM, off);

//--- Force close
   if(inClose && CountPos(InpMagicNumber) > 0)
     {
      CloseAll(InpMagicNumber, "S2 SessionEnd");
      g_s2_addCount = 0;
      return;
     }

   if(!inTrade)
     { g_s2_addCount = 0; return; }

//--- Check chart timeframe
   if(Inp2_Only1M && Period() != PERIOD_M1)
      return;

//--- Indicators
   double cci = GetInd(h_cci, 0, 1);
   double atr = GetInd(h_atr, 0, 1);
   double bbUpper = GetInd(h_bb, 1, 1);
   double bbLower = GetInd(h_bb, 2, 1);
   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
   double bbUpperP = GetInd(h_bb, 1, 2);
   double bbLowerP = GetInd(h_bb, 2, 2);

   if(atr <= 0) return;

//--- Magic Trend
   double l1 = iLow(_Symbol, PERIOD_CURRENT, 1);
   double h1 = iHigh(_Symbol, PERIOD_CURRENT, 1);
   UpdateMagicTrend(cci, atr, l1, h1, atrMult);
   bool trendUp = g_mtBullish;

//--- Signals: BB breakout + MT confirm
   bool breakLong  = c1 > bbUpper && c2 <= bbUpperP;
   bool breakShort = c1 < bbLower && c2 >= bbLowerP;
   bool longSig  = Inp2_AllowLong  && breakLong  && trendUp    && c1 > g_magicTrend;
   bool shortSig = Inp2_AllowShort && breakShort && !trendUp   && c1 < g_magicTrend;

//--- Position tracking
   int posCount = CountPos(InpMagicNumber);
   int posType  = GetPositionType(InpMagicNumber);

//--- Reset add counter when flat
   if(posCount == 0)
      g_s2_addCount = 0;

//--- Initial entry when flat
   if(posCount == 0 && !inClose)
     {
      if(longSig)
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double sl = NormalizeDouble(ask - slATR * atr, _Digits);
         double tp = NormalizeDouble(ask + tpATR * atr, _Digits);
         if(g_trade.Buy(Inp2_Qty, _Symbol, ask, sl, tp, "S2 Long"))
           { g_s2_addCount = 0; PrintFormat("S2 LONG @ %.5f", ask); }
        }
      if(shortSig)
        {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double sl = NormalizeDouble(bid + slATR * atr, _Digits);
         double tp = NormalizeDouble(bid - tpATR * atr, _Digits);
         if(g_trade.Sell(Inp2_Qty, _Symbol, bid, sl, tp, "S2 Short"))
           { g_s2_addCount = 0; PrintFormat("S2 SHORT @ %.5f", bid); }
        }
     }

//--- Add-on entries
   bool canAdd = inAdd && g_s2_addCount < maxAdds;
   if(canAdd && posCount > 0)
     {
      if(posType == POSITION_TYPE_BUY && longSig)
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double sl = NormalizeDouble(ask - slATR * atr, _Digits);
         double tp = NormalizeDouble(ask + tpATR * atr, _Digits);
         if(g_trade.Buy(Inp2_Qty, _Symbol, ask, sl, tp, "S2 Add Long"))
           { g_s2_addCount++; PrintFormat("S2 ADD LONG %d/%d", g_s2_addCount, maxAdds); }
        }
      if(posType == POSITION_TYPE_SELL && shortSig)
        {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double sl = NormalizeDouble(bid + slATR * atr, _Digits);
         double tp = NormalizeDouble(bid - tpATR * atr, _Digits);
         if(g_trade.Sell(Inp2_Qty, _Symbol, bid, sl, tp, "S2 Add Short"))
           { g_s2_addCount++; PrintFormat("S2 ADD SHORT %d/%d", g_s2_addCount, maxAdds); }
        }
     }

//--- Update SL/TP on existing positions each bar
   if(posCount > 0)
     {
      double avgPx = GetPositionAvgPrice(InpMagicNumber);
      long ticket = GetPositionTicket(InpMagicNumber);
      if(ticket > 0 && avgPx > 0)
        {
         double newSL, newTP;
         if(posType == POSITION_TYPE_BUY)
           { newSL = NormalizeDouble(avgPx - slATR * atr, _Digits); newTP = NormalizeDouble(avgPx + tpATR * atr, _Digits); }
         else
           { newSL = NormalizeDouble(avgPx + slATR * atr, _Digits); newTP = NormalizeDouble(avgPx - tpATR * atr, _Digits); }
         g_trade.PositionModify((ulong)ticket, newSL, newTP);
        }
     }
  }

//+------------------------------------------------------------------+
//| STRATEGY 3: US Open MT+BB                                          |
//+------------------------------------------------------------------+
void Strategy_USOpenMTBB()
  {
//--- Resolve preset
   int sessSH=15, sessSM=30, sessEH=16, sessEM=30;
   double atrMult=1.0, slATR=1.0, tpATR=2.0;

   switch(Inp3_Preset)
     {
      case PRE_MAXNET: atrMult=1.0; slATR=1.0; tpATR=2.0; break;
      case PRE_BESTPF: atrMult=1.0; slATR=1.2; tpATR=2.0; break;
      case PRE_LOWDD:  atrMult=1.0; slATR=1.5; tpATR=1.5; break;
      case PRE_CUSTOM_3: atrMult=Inp3_ATRMult; slATR=Inp3_SL_ATR; tpATR=Inp3_TP_ATR; break;
     }

   int off = Inp3_TimeOffset;
   bool inSess  = IsInWindow(sessSH, sessSM, sessEH, sessEM, off);
   bool lastBar = IsInWindow(16, 29, 16, 30, off);
   bool entryOK = inSess && !lastBar;

//--- Force close at last bar
   if(lastBar && CountPos(InpMagicNumber) > 0)
     {
      CloseAll(InpMagicNumber, "S3 SessionEnd 16:29");
      g_s3_hasPosition = false;
      g_s3_atrAtEntry  = 0;
      return;
     }

   if(!inSess) return;
   if(Inp3_Only1M && Period() != PERIOD_M1) return;

//--- Indicators
   double cci = GetInd(h_cci, 0, 1);
   double atr = GetInd(h_atr, 0, 1);
   double bbUpper = GetInd(h_bb, 1, 1);
   double bbLower = GetInd(h_bb, 2, 1);
   double bbUpperP = GetInd(h_bb, 1, 2);
   double bbLowerP = GetInd(h_bb, 2, 2);
   double c1 = iClose(_Symbol, PERIOD_CURRENT, 1);
   double c2 = iClose(_Symbol, PERIOD_CURRENT, 2);
   double l1 = iLow(_Symbol, PERIOD_CURRENT, 1);
   double h1 = iHigh(_Symbol, PERIOD_CURRENT, 1);

   if(atr <= 0) return;

//--- Magic Trend
   UpdateMagicTrend(cci, atr, l1, h1, atrMult);
   bool trendUp = g_mtBullish;

//--- Breakout signals
   bool breakLong  = c1 > bbUpper && c2 <= bbUpperP;
   bool breakShort = c1 < bbLower && c2 >= bbLowerP;
   bool longSig  = entryOK && Inp3_AllowLong  && breakLong  && trendUp  && c1 > g_magicTrend;
   bool shortSig = entryOK && Inp3_AllowShort && breakShort && !trendUp && c1 < g_magicTrend;

//--- Track position state
   int posCount = CountPos(InpMagicNumber);
   if(posCount == 0)
     {
      g_s3_hasPosition = false;
      g_s3_atrAtEntry  = 0;
     }

//--- New position check (store ATR at entry)
   if(posCount > 0 && !g_s3_hasPosition)
     {
      g_s3_hasPosition = true;
      g_s3_atrAtEntry  = atr;
     }

//--- Entries (only when flat)
   if(posCount == 0)
     {
      if(longSig)
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         if(g_trade.Buy(Inp3_Qty, _Symbol, ask, 0, 0, "S3 Long"))
           {
            g_s3_atrAtEntry  = atr;
            g_s3_hasPosition = true;
            PrintFormat("S3 LONG @ %.5f", ask);
           }
        }
      if(shortSig)
        {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         if(g_trade.Sell(Inp3_Qty, _Symbol, bid, 0, 0, "S3 Short"))
           {
            g_s3_atrAtEntry  = atr;
            g_s3_hasPosition = true;
            PrintFormat("S3 SHORT @ %.5f", bid);
           }
        }
     }

//--- Manage exits with stored ATR
   if(posCount > 0 && g_s3_atrAtEntry > 0)
     {
      double avgPx = GetPositionAvgPrice(InpMagicNumber);
      long ticket = GetPositionTicket(InpMagicNumber);
      int posType = GetPositionType(InpMagicNumber);
      if(ticket > 0 && avgPx > 0)
        {
         double newSL, newTP;
         if(posType == POSITION_TYPE_BUY)
           {
            newSL = NormalizeDouble(avgPx - slATR * g_s3_atrAtEntry, _Digits);
            newTP = NormalizeDouble(avgPx + tpATR * g_s3_atrAtEntry, _Digits);
           }
         else
           {
            newSL = NormalizeDouble(avgPx + slATR * g_s3_atrAtEntry, _Digits);
            newTP = NormalizeDouble(avgPx - tpATR * g_s3_atrAtEntry, _Digits);
           }
         g_trade.PositionModify((ulong)ticket, newSL, newTP);
        }
     }
  }

//+------------------------------------------------------------------+
//| STRATEGY 4: Deep Weekly Pullback                                   |
//+------------------------------------------------------------------+
void Strategy_DeepWeeklyPB()
  {
   ENUM_TIMEFRAMES tfE = Inp4_TF_Exec;
   ENUM_TIMEFRAMES tfD = Inp4_TF_Daily;
   ENUM_TIMEFRAMES tfW = Inp4_TF_Weekly;

//--- MTF indicator values
   double wClose  = iClose(_Symbol, tfW, 1);
   double wHigh   = iHigh(_Symbol, tfW, 1);
   double wEma50  = GetInd(h4_w_ema50, 0, 1);
   double wAtr    = GetInd(h4_w_atr, 0, 1);

   double dClose  = iClose(_Symbol, tfD, 1);
   double dHigh   = iHigh(_Symbol, tfD, 1);
   double dLow    = iLow(_Symbol, tfD, 1);
   double dEma10  = GetInd(h4_d_ema_fast, 0, 1);
   double dEma20  = GetInd(h4_d_ema_slow, 0, 1);
   double dEma10p = GetInd(h4_d_ema_fast, 0, 2);
   double dEma20p = GetInd(h4_d_ema_slow, 0, 2);

   double h2Close = iClose(_Symbol, tfE, 1);
   double h2High  = iHigh(_Symbol, tfE, 1);
   double h2Low   = iLow(_Symbol, tfE, 1);
   double h2Ema   = GetInd(h4_h2_ema, 0, 1);
   double h2Atr   = GetInd(h4_h2_atr, 0, 1);

   if(h2Atr <= 0 || wAtr <= 0) return;

//--- Weekly ATH tracking
   if(g_s4_wATH == 0) g_s4_wATH = wHigh;
   if(wHigh > g_s4_wATH) g_s4_wATH = wHigh;

//--- Weekly deep pullback detection
   bool wTrendOK = !Inp4_UseWeeklyTrend || (wClose >= wEma50);
   double wDdPct = g_s4_wATH != 0 ? ((g_s4_wATH - wClose) / g_s4_wATH) * 100.0 : 0;
   bool deepByDD  = wDdPct >= Inp4_DeepDDPct;
   bool deepByATR = wClose <= (wEma50 - Inp4_DeepATRMult * wAtr);
   bool wDeepPB   = wTrendOK && (deepByDD || deepByATR);

//--- Daily cross detection
   bool dCrossUp = dEma10p <= dEma20p && dEma10 > dEma20;

//--- Daily pullback zone
   double zTop = MathMax(dEma10, dEma20);
   double zBot = MathMin(dEma10, dEma20);
   bool touchedZone = (dLow <= zTop) && (dHigh >= zBot);

//--- Bars since daily cross (approximate via scanning)
   int barsSinceCross = -1;
   for(int i = 1; i <= Inp4_CrossLookback + 5; i++)
     {
      double f1 = GetInd(h4_d_ema_fast, 0, i);
      double s1 = GetInd(h4_d_ema_slow, 0, i);
      double f2 = GetInd(h4_d_ema_fast, 0, i + 1);
      double s2 = GetInd(h4_d_ema_slow, 0, i + 1);
      if(f2 <= s2 && f1 > s1) { barsSinceCross = i; break; }
     }
   bool crossRecent = barsSinceCross >= 0 && barsSinceCross <= Inp4_CrossLookback;

//--- Position state
   int posCount = CountPos(InpMagicNumber);
   bool isFlat = posCount == 0;

//--- State machine (only when flat)
   if(isFlat)
     {
      // Step 1: Weekly deep pullback
      if(!g_s4_wkDeep && wDeepPB)
        {
         g_s4_wkDeep = true; g_s4_dCross = false; g_s4_dPB = false;
         g_s4_pbLow = 0; g_s4_pbHigh = 0; g_s4_pbAge = 0;
         PrintFormat("S4: Weekly Deep active DD%%=%.2f", wDdPct);
        }
      // Step 2: Daily cross after deep
      if(g_s4_wkDeep && !g_s4_dCross && dCrossUp)
        {
         g_s4_dCross = true; g_s4_dPB = false;
         g_s4_pbLow = 0; g_s4_pbHigh = 0; g_s4_pbAge = 0;
         Print("S4: Daily Cross Up detected");
        }
      // Step 3: Pullback into EMA zone
      bool pbWindowOK = crossRecent && barsSinceCross <= Inp4_PBMaxDays;
      bool dailyPBok = pbWindowOK && (!Inp4_PBNeedTouch || touchedZone);
      if(g_s4_wkDeep && g_s4_dCross && !g_s4_dPB && dailyPBok)
        {
         g_s4_dPB = true;
         g_s4_pbLow = h2Low; g_s4_pbHigh = h2High; g_s4_pbAge = 0;
         Print("S4: Daily PB into zone - armed for entry");
        }
      // Expire
      if(g_s4_dCross && barsSinceCross > Inp4_PBMaxDays)
        {
         g_s4_wkDeep = false; g_s4_dCross = false; g_s4_dPB = false;
         g_s4_pbLow = 0; g_s4_pbHigh = 0; g_s4_pbAge = 0;
        }
     }

//--- H2 Entry condition
   bool reclaimOK   = h2Close > h2Ema;
   bool dailyValid  = !Inp4_ReqDailyAbove20 || (dClose >= dEma20);
   bool enterCond   = isFlat && g_s4_wkDeep && g_s4_dCross && g_s4_dPB && reclaimOK && dailyValid;

//--- Update PB extremes while waiting
   if(isFlat && g_s4_dPB)
     {
      g_s4_pbAge++;
      if(g_s4_pbLow == 0) g_s4_pbLow = h2Low;
      else g_s4_pbLow = MathMin(g_s4_pbLow, h2Low);
      if(g_s4_pbHigh == 0) g_s4_pbHigh = h2High;
      else g_s4_pbHigh = MathMax(g_s4_pbHigh, h2High);
      if(g_s4_pbAge > 180)
        {
         g_s4_wkDeep = false; g_s4_dCross = false; g_s4_dPB = false;
         g_s4_pbLow = 0; g_s4_pbHigh = 0; g_s4_pbAge = 0;
        }
     }

//--- Place buy stop entry
   if(enterCond)
     {
      double pivotHigh = GetHighest(tfE, Inp4_PivotLen, 1);
      double entryPx = NormalizeDouble(pivotHigh + Inp4_EntryBufATR * h2Atr, _Digits);
      double qtyRaw = (AccountInfoDouble(ACCOUNT_EQUITY) * Inp4_RiskPct / 100.0) / h2Close;
      double qty = Inp4_MinQty > 0 ? MathMax(qtyRaw, Inp4_MinQty) : qtyRaw;
      qty = NormalizeDouble(MathMax(qty, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)), 2);

      // Cancel existing pending orders first
      for(int i = OrdersTotal() - 1; i >= 0; i--)
        {
         ulong ticket = OrderGetTicket(i);
         if(ticket > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagicNumber)
            g_trade.OrderDelete(ticket);
        }

      g_trade.BuyStop(qty, entryPx, _Symbol, 0, 0, ORDER_TIME_GTC, 0, "S4 Entry");
      PrintFormat("S4 BUY STOP @ %.5f qty=%.4f", entryPx, qty);
     }

//--- Position management (LONG only)
   if(posCount > 0)
     {
      int posType = GetPositionType(InpMagicNumber);
      if(posType != POSITION_TYPE_BUY) return;

      double avgPx = GetPositionAvgPrice(InpMagicNumber);
      long ticket = GetPositionTicket(InpMagicNumber);
      if(ticket <= 0) return;

      // Detect new fill
      if(g_s4_anchor == 0 && avgPx > 0)
        {
         g_s4_anchor  = avgPx;
         g_s4_hiSince = h2High;
         g_s4_barsIn  = 0;
         g_s4_stop    = g_s4_pbLow - Inp4_StopPadATR * h2Atr;
         g_s4_rDist   = MathAbs(g_s4_anchor - g_s4_stop);
         g_s4_pbBreak = g_s4_pbHigh;
         // Reset setup
         g_s4_wkDeep = false; g_s4_dCross = false; g_s4_dPB = false;
         g_s4_pbAge = 0;
         PrintFormat("S4 FILLED anchor=%.5f stop=%.5f R=%.5f", g_s4_anchor, g_s4_stop, g_s4_rDist);
        }

      g_s4_barsIn++;
      g_s4_hiSince = MathMax(g_s4_hiSince, h2High);

      double usedR = g_s4_rDist > 0 ? g_s4_rDist : 1.5 * h2Atr;

      // BE
      bool reachedBE = h2High >= g_s4_anchor + Inp4_BE_R * usedR;
      bool pbBreak   = Inp4_BEOnPBBreak && g_s4_pbBreak > 0 && h2High >= g_s4_pbBreak;
      if(reachedBE || pbBreak)
         g_s4_stop = MathMax(g_s4_stop, g_s4_anchor + Inp4_BE_PlusR * usedR);

      // Trail
      double distATHPct = g_s4_wATH != 0 ? ((g_s4_wATH - h2Close) / g_s4_wATH) * 100.0 : 999;
      bool useTight = distATHPct <= Inp4_NearATHPct;
      if(h2High >= g_s4_anchor + Inp4_TrailStartR * usedR)
        {
         double chandMult = useTight ? Inp4_TightTrailATR : Inp4_TrailATR;
         double chand = g_s4_hiSince - chandMult * h2Atr;
         g_s4_stop = MathMax(g_s4_stop, chand);
        }

      // Time stop
      if(g_s4_barsIn >= Inp4_TimeStopBars && h2High < g_s4_anchor + usedR)
        {
         CloseAll(InpMagicNumber, "S4 TimeStop");
         g_s4_anchor = 0; g_s4_stop = 0; g_s4_rDist = 0;
         g_s4_hiSince = 0; g_s4_barsIn = 0;
         return;
        }

      // Modify stop
      double normStop = NormalizeDouble(g_s4_stop, _Digits);
      g_trade.PositionModify((ulong)ticket, normStop, 0);
     }

//--- Reset when flat
   if(isFlat)
     {
      g_s4_anchor = 0; g_s4_stop = 0; g_s4_rDist = 0;
      g_s4_hiSince = 0; g_s4_barsIn = 0; g_s4_pbBreak = 0;
     }
  }

//+------------------------------------------------------------------+
//| STRATEGY 5: Trend Ride v3.4                                        |
//+------------------------------------------------------------------+
void Strategy_TrendRide()
  {
   ENUM_TIMEFRAMES tfE = Inp5_TF_Exec;
   ENUM_TIMEFRAMES tfD = Inp5_TF_Daily;
   ENUM_TIMEFRAMES tfW = Inp5_TF_Weekly;

//--- Weekly indicators
   double wEmaFast = GetInd(h5_w_ema_fast, 0, 1);
   double wEmaSlow = GetInd(h5_w_ema_slow, 0, 1);
   double wAtr     = GetInd(h5_w_atr, 0, 1);
   bool wLongOK    = wEmaFast > wEmaSlow;
   bool wShortOK   = wEmaFast < wEmaSlow;
   double wGap     = MathAbs(wEmaFast - wEmaSlow);
   bool strongTrend = wAtr > 0 ? (wGap >= Inp5_WGapATRMin * wAtr) : false;
   double sizeMult = strongTrend ? Inp5_RegimeBoost : 1.0;
   double adxMin   = strongTrend ? Inp5_ADXMinStrong : Inp5_ADXMinBase;

//--- Daily indicators
   double dEmaFast = GetInd(h5_d_ema_fast, 0, 1);
   double dEmaSlow = GetInd(h5_d_ema_slow, 0, 1);
   double dClose   = iClose(_Symbol, tfD, 1);
   double dLow     = iLow(_Symbol, tfD, 1);
   double dHigh    = iHigh(_Symbol, tfD, 1);
   double dAtr     = GetInd(h5_d_atr, 0, 1);
   bool dLongOK    = dEmaFast > dEmaSlow;
   bool dShortOK   = dEmaFast < dEmaSlow;

//--- PBD (Pullback Days) validation
   // Scan daily bars for pullback into EMA zone
   bool pbdLongOK = false, pbdShortOK = false;
   bool reclaimLongOK = false, reclaimShortOK = false;
   bool extLongOK = false, extShortOK = false;

   for(int i = 1; i <= Inp5_PBDDays; i++)
     {
      double dl = iLow(_Symbol, tfD, i);
      double dh = iHigh(_Symbol, tfD, i);
      double ef = GetInd(h5_d_ema_fast, 0, i);
      double es = GetInd(h5_d_ema_slow, 0, i);
      double zTop = MathMax(ef, es);
      double zBot = MathMin(ef, es);
      if(Inp5_UseEMAZone)
        {
         if(dl <= zTop && dl >= zBot) pbdLongOK = true;
         if(dh >= zBot && dh <= zTop) pbdShortOK = true;
        }
      else
        {
         if(dl <= ef) pbdLongOK = true;
         if(dh >= ef) pbdShortOK = true;
        }
     }

   reclaimLongOK  = !Inp5_RequireReclaim || (dClose > dEmaFast);
   reclaimShortOK = !Inp5_RequireReclaim || (dClose < dEmaFast);
   extLongOK  = dAtr > 0 ? (MathAbs(dClose - dEmaFast) <= Inp5_MaxExtATR * dAtr) : true;
   extShortOK = extLongOK;

//--- H2 indicators
   double tClose = iClose(_Symbol, tfE, 1);
   double tHigh  = iHigh(_Symbol, tfE, 1);
   double tLow   = iLow(_Symbol, tfE, 1);
   double tAtr   = GetInd(h5_h2_atr, 0, 1);
   double tAdx   = GetInd(h5_h2_adx, 0, 1); // Main ADX line = buffer 0
   double tAdxP  = GetInd(h5_h2_adx, 0, 2);

   if(tAtr <= 0) return;

   bool adxOK = (tAdx >= adxMin) && (!Inp5_ADXRising || tAdx > tAdxP);

//--- Breakout/Breakdown
   double hh = GetHighest(tfE, Inp5_EntryLookback, 2); // highest of previous bars (shift 2 to entryLookback+1)
   double ll = GetLowest(tfE, Inp5_EntryLookback, 2);
   bool breakoutOK  = tClose > hh;
   bool breakdownOK = tClose < ll;

//--- Signals
   bool longFilter  = wLongOK && dLongOK;
   bool shortFilter = wShortOK && dShortOK;

   bool longA  = longFilter  && pbdLongOK  && reclaimLongOK  && extLongOK  && adxOK && breakoutOK;
   bool shortA = shortFilter && pbdShortOK && reclaimShortOK && extShortOK && adxOK && breakdownOK;
   bool longB  = longFilter  && pbdLongOK  && reclaimLongOK  && extLongOK  && adxOK;
   bool shortB = shortFilter && pbdShortOK && reclaimShortOK && extShortOK && adxOK;

   bool useA = Inp5_EntryMode == TENT_BOTH || Inp5_EntryMode == TENT_PBD_BO;
   bool useB = Inp5_EntryMode == TENT_BOTH || Inp5_EntryMode == TENT_PBD_REC;

   bool longSig  = (useA && longA) || (useB && longB);
   bool shortSig = (useA && shortA) || (useB && shortB);

//--- Position sizing
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double starterQty = NormalizeDouble(MathMax((equity * Inp5_StarterPct * sizeMult / 100.0) / tClose, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)), 2);
   double addon1Qty  = NormalizeDouble(MathMax((equity * Inp5_Addon1Pct * sizeMult / 100.0) / tClose, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)), 2);
   double addon2Qty  = NormalizeDouble(MathMax((equity * Inp5_Addon2Pct * sizeMult / 100.0) / tClose, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)), 2);

//--- Position state
   int posCount = CountPos(InpMagicNumber);
   bool isFlat  = posCount == 0;

//--- Starter entries
   if(isFlat && longSig)
     {
      g_s5_anchor  = tClose; g_s5_anchorR = Inp5_StopATR * tAtr;
      g_s5_stop    = g_s5_anchor - g_s5_anchorR;
      g_s5_hiSince = tHigh; g_s5_loSince = tLow;
      g_s5_barsIn  = 0; g_s5_didAdd1 = false; g_s5_didAdd2 = false;
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl = NormalizeDouble(g_s5_stop, _Digits);
      g_trade.Buy(starterQty, _Symbol, ask, sl, 0, "S5 Long");
      PrintFormat("S5 LONG @ %.5f strong=%d", ask, strongTrend);
     }
   if(isFlat && shortSig)
     {
      g_s5_anchor  = tClose; g_s5_anchorR = Inp5_StopATR * tAtr;
      g_s5_stop    = g_s5_anchor + g_s5_anchorR;
      g_s5_hiSince = tHigh; g_s5_loSince = tLow;
      g_s5_barsIn  = 0; g_s5_didAdd1 = false; g_s5_didAdd2 = false;
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl = NormalizeDouble(g_s5_stop, _Digits);
      g_trade.Sell(starterQty, _Symbol, bid, sl, 0, "S5 Short");
      PrintFormat("S5 SHORT @ %.5f strong=%d", bid, strongTrend);
     }

//--- Manage LONG
   int posType = GetPositionType(InpMagicNumber);
   if(posCount > 0 && posType == POSITION_TYPE_BUY)
     {
      g_s5_barsIn++;
      g_s5_hiSince = MathMax(g_s5_hiSince, tHigh);
      double usedR = g_s5_anchorR > 0 ? g_s5_anchorR : Inp5_StopATR * tAtr;

      bool reached1R = tHigh >= g_s5_anchor + 1.0 * usedR;
      bool reached2R = tHigh >= g_s5_anchor + 2.0 * usedR;

      // Add1 @ +1R
      if(reached1R && !g_s5_didAdd1 && Inp5_Addon1Pct > 0)
        {
         g_s5_didAdd1 = true;
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         g_trade.Buy(addon1Qty, _Symbol, ask, NormalizeDouble(g_s5_stop, _Digits), 0, "S5 Add1");
         if(Inp5_LockOnAdd1)
            g_s5_stop = MathMax(g_s5_stop, g_s5_anchor + Inp5_LockBEExtraR * usedR);
         PrintFormat("S5 ADD1 qty=%.4f", addon1Qty);
        }
      // Add2 @ +2R
      if(reached2R && !g_s5_didAdd2 && Inp5_Addon2Pct > 0 && (!Inp5_Add2OnlyStrong || strongTrend))
        {
         g_s5_didAdd2 = true;
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         g_trade.Buy(addon2Qty, _Symbol, ask, NormalizeDouble(g_s5_stop, _Digits), 0, "S5 Add2");
         PrintFormat("S5 ADD2 qty=%.4f", addon2Qty);
        }

      // BE
      if(tHigh >= g_s5_anchor + Inp5_BE_R * usedR)
         g_s5_stop = MathMax(g_s5_stop, g_s5_anchor + Inp5_BE_PlusR * usedR);

      // Chandelier trail
      if(tHigh >= g_s5_anchor + Inp5_TrailR * usedR)
        {
         double chand = g_s5_hiSince - Inp5_TrailATR * tAtr;
         g_s5_stop = MathMax(g_s5_stop, chand);
        }

      // Time stop
      if(g_s5_barsIn >= Inp5_TimeStopBars && !reached1R)
        { CloseAll(InpMagicNumber, "S5 TimeStop"); return; }

      // Update all position stops
      double normStop = NormalizeDouble(g_s5_stop, _Digits);
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong tk = PositionGetTicket(i);
         if(tk > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber && PositionGetString(POSITION_SYMBOL) == _Symbol)
            g_trade.PositionModify(tk, normStop, 0);
        }
     }

//--- Manage SHORT
   if(posCount > 0 && posType == POSITION_TYPE_SELL)
     {
      g_s5_barsIn++;
      g_s5_loSince = MathMin(g_s5_loSince, tLow);
      double usedR = g_s5_anchorR > 0 ? g_s5_anchorR : Inp5_StopATR * tAtr;

      bool reached1R = tLow <= g_s5_anchor - 1.0 * usedR;
      bool reached2R = tLow <= g_s5_anchor - 2.0 * usedR;

      if(reached1R && !g_s5_didAdd1 && Inp5_Addon1Pct > 0)
        {
         g_s5_didAdd1 = true;
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         g_trade.Sell(addon1Qty, _Symbol, bid, NormalizeDouble(g_s5_stop, _Digits), 0, "S5 Add1 S");
         if(Inp5_LockOnAdd1)
            g_s5_stop = MathMin(g_s5_stop, g_s5_anchor - Inp5_LockBEExtraR * usedR);
        }
      if(reached2R && !g_s5_didAdd2 && Inp5_Addon2Pct > 0 && (!Inp5_Add2OnlyStrong || strongTrend))
        {
         g_s5_didAdd2 = true;
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         g_trade.Sell(addon2Qty, _Symbol, bid, NormalizeDouble(g_s5_stop, _Digits), 0, "S5 Add2 S");
        }

      if(tLow <= g_s5_anchor - Inp5_BE_R * usedR)
         g_s5_stop = MathMin(g_s5_stop, g_s5_anchor - Inp5_BE_PlusR * usedR);

      if(tLow <= g_s5_anchor - Inp5_TrailR * usedR)
        {
         double chand = g_s5_loSince + Inp5_TrailATR * tAtr;
         g_s5_stop = MathMin(g_s5_stop, chand);
        }

      if(g_s5_barsIn >= Inp5_TimeStopBars && !reached1R)
        { CloseAll(InpMagicNumber, "S5 TimeStop S"); return; }

      double normStop = NormalizeDouble(g_s5_stop, _Digits);
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong tk = PositionGetTicket(i);
         if(tk > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber && PositionGetString(POSITION_SYMBOL) == _Symbol)
            g_trade.PositionModify(tk, normStop, 0);
        }
     }

//--- Reset when flat
   if(isFlat)
     {
      g_s5_anchor = 0; g_s5_anchorR = 0; g_s5_stop = 0;
      g_s5_hiSince = 0; g_s5_loSince = 0; g_s5_barsIn = 0;
      g_s5_didAdd1 = false; g_s5_didAdd2 = false;
     }
  }

//+------------------------------------------------------------------+
//| STRATEGY 6: EMA Fractal v4                                         |
//+------------------------------------------------------------------+
void Strategy_EMAFractal()
  {
   ENUM_TIMEFRAMES tfE = Inp6_TF_Exec;

//--- Session filter
   if(Inp6_UseSession)
     {
      MqlDateTime dt; TimeCurrent(dt);
      if(dt.hour < Inp6_SessStart || dt.hour >= Inp6_SessEnd)
         return;
     }

//--- HTF EMAs for trend filter
   double wEma5  = GetInd(h6_w_ema5, 0, 1);
   double wEma50 = GetInd(h6_w_ema50, 0, 1);
   double dEma10 = GetInd(h6_d_ema10, 0, 1);
   double dEma20 = GetInd(h6_d_ema20, 0, 1);

   bool cond_w_bull = wEma5 > wEma50;
   bool cond_d_bull = dEma10 > dEma20;
   bool cond_w_bear = wEma5 < wEma50;
   bool cond_d_bear = dEma10 < dEma20;
   bool htfBullish  = cond_w_bull && cond_d_bull;
   bool htfBearish  = cond_w_bear && cond_d_bear;

//--- H2 EMAs
   double h2Ema10  = GetInd(h6_h2_ema_fast, 0, 1);
   double h2Ema20  = GetInd(h6_h2_ema_mid, 0, 1);
   double h2EmaT   = GetInd(h6_h2_ema_trail, 0, 1);
   double h2Atr    = GetInd(h6_h2_atr, 0, 1);
   double h2Ema20p = GetInd(h6_h2_ema_mid, 0, 2);

   double c1 = iClose(_Symbol, tfE, 1);
   double c2 = iClose(_Symbol, tfE, 2);
   double o1 = iOpen(_Symbol, tfE, 1);
   double h1 = iHigh(_Symbol, tfE, 1);
   double l1 = iLow(_Symbol, tfE, 1);

   if(h2Atr <= 0) return;

//--- Cross detection
   bool crossAbove = c1 > h2Ema20 && c2 <= h2Ema20p;
   bool crossBelow = c1 < h2Ema20 && c2 >= h2Ema20p;

//--- Setup conditions
   bool setupLong  = Inp6_TradeLong  && htfBullish && h2Ema10 < h2Ema20 && crossAbove;
   bool setupShort = Inp6_TradeShort && htfBearish && h2Ema10 > h2Ema20 && crossBelow;

//--- Fractal detection (on completed bars, shifted by lookback)
   int lb = Inp6_FracLookback;
   bool fhDet = IsFracHigh(1 + lb, lb, tfE);
   bool flDet = IsFracLow(1 + lb, lb, tfE);
   double fhPrice = fhDet ? iHigh(_Symbol, tfE, 1 + lb) : 0;
   double flPrice = flDet ? iLow(_Symbol, tfE, 1 + lb) : 0;

   if(flDet && flPrice > 0) g_s6_lastFL = flPrice;
   if(fhDet && fhPrice > 0) g_s6_lastFH = fhPrice;

//--- Position tracking
   int posCount = CountPos(InpMagicNumber);

//--- Setup activation
   if(setupLong && !g_s6_waiting && posCount == 0 && !g_s6_pend)
     {
      g_s6_waiting = true; g_s6_barsSetup = 0; g_s6_dir = 1;
      Print("S6: LONG SETUP activated");
     }
   if(setupShort && !g_s6_waiting && posCount == 0 && !g_s6_pend)
     {
      g_s6_waiting = true; g_s6_barsSetup = 0; g_s6_dir = -1;
      Print("S6: SHORT SETUP activated");
     }

//--- Waiting for fractal
   if(g_s6_waiting)
     {
      g_s6_barsSetup++;
      if(g_s6_barsSetup > Inp6_MaxCandlesFrac)
        {
         g_s6_waiting = false; g_s6_barsSetup = 0; g_s6_dir = 0;
         Print("S6: TIMEOUT - no fractal found");
        }
     }

//--- Fractal found -> prepare order
   if(g_s6_waiting && g_s6_dir == 1 && fhDet && g_s6_barsSetup <= Inp6_MaxCandlesFrac)
     {
      double dp = h2Ema20 > 0 ? MathAbs(fhPrice - h2Ema20) / h2Ema20 * 100.0 : 0;
      if(!Inp6_UseDistFilter || dp <= Inp6_MaxDistPct)
        {
         g_s6_entryPx = fhPrice;
         g_s6_slPx = (Inp6_SLMode == SLM_FULL) ? g_s6_lastFL : g_s6_entryPx - (g_s6_entryPx - g_s6_lastFL) / 2.0;
         if(g_s6_slPx > 0 && g_s6_slPx < g_s6_entryPx)
           {
            g_s6_pend = true; g_s6_barsPend = 0;
            g_s6_waiting = false; g_s6_barsSetup = 0;
            g_s6_beActive = false; g_s6_partialDone = false;
            g_s6_initRisk = g_s6_entryPx - g_s6_slPx;
            PrintFormat("S6: LONG pending Entry=%.5f SL=%.5f Risk=%.5f", g_s6_entryPx, g_s6_slPx, g_s6_initRisk);
           }
        }
     }
   if(g_s6_waiting && g_s6_dir == -1 && flDet && g_s6_barsSetup <= Inp6_MaxCandlesFrac)
     {
      double dp = h2Ema20 > 0 ? MathAbs(flPrice - h2Ema20) / h2Ema20 * 100.0 : 0;
      if(!Inp6_UseDistFilter || dp <= Inp6_MaxDistPct)
        {
         g_s6_entryPx = flPrice;
         g_s6_slPx = (Inp6_SLMode == SLM_FULL) ? g_s6_lastFH : g_s6_entryPx + (g_s6_lastFH - g_s6_entryPx) / 2.0;
         if(g_s6_slPx > 0 && g_s6_slPx > g_s6_entryPx)
           {
            g_s6_pend = true; g_s6_barsPend = 0;
            g_s6_waiting = false; g_s6_barsSetup = 0;
            g_s6_beActive = false; g_s6_partialDone = false;
            g_s6_initRisk = g_s6_slPx - g_s6_entryPx;
            PrintFormat("S6: SHORT pending Entry=%.5f SL=%.5f Risk=%.5f", g_s6_entryPx, g_s6_slPx, g_s6_initRisk);
           }
        }
     }

//--- Place/manage pending order
   if(g_s6_pend && posCount == 0)
     {
      // Cancel old orders first
      for(int i = OrdersTotal() - 1; i >= 0; i--)
        {
         ulong ticket = OrderGetTicket(i);
         if(ticket > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagicNumber)
            g_trade.OrderDelete(ticket);
        }

      double riskAmt = AccountInfoDouble(ACCOUNT_EQUITY) * Inp6_RiskPct / 100.0;
      double slDist  = MathAbs(g_s6_entryPx - g_s6_slPx);
      double lossPer = slDist * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      double qty     = lossPer > 0 ? riskAmt / lossPer : InpDefaultLot;
      qty = NormalizeDouble(MathMax(qty, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)), 2);

      double normEntry = NormalizeDouble(g_s6_entryPx, _Digits);
      double normSL    = NormalizeDouble(g_s6_slPx, _Digits);

      if(g_s6_dir == 1)
         g_trade.BuyStop(qty, normEntry, _Symbol, normSL, 0, ORDER_TIME_GTC, 0, "S6 Long");
      else
         g_trade.SellStop(qty, normEntry, _Symbol, normSL, 0, ORDER_TIME_GTC, 0, "S6 Short");

      g_s6_barsPend++;

      // Expiry checks
      bool cancelHTF  = (g_s6_dir == 1 && !htfBullish) || (g_s6_dir == -1 && !htfBearish);
      bool cancelTime = g_s6_barsPend > Inp6_MaxBarsPending;
      double entryDist = c1 > 0 ? MathAbs(g_s6_entryPx - c1) / c1 * 100.0 : 0;
      bool cancelDist = g_s6_barsPend > 5 && entryDist > Inp6_MaxEntryDistPct;

      if(cancelHTF || cancelTime || cancelDist)
        {
         for(int i = OrdersTotal() - 1; i >= 0; i--)
           {
            ulong ticket = OrderGetTicket(i);
            if(ticket > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagicNumber)
               g_trade.OrderDelete(ticket);
           }
         g_s6_pend = false; g_s6_barsPend = 0;
         g_s6_entryPx = 0; g_s6_slPx = 0; g_s6_dir = 0;
         Print("S6: Order CANCELLED");
        }
     }

//--- When position opens
   if(g_s6_pend && posCount > 0)
     {
      g_s6_pend = false;
      g_s6_trailSL = g_s6_slPx;
      PrintFormat("S6: FILLED dir=%d trailSL=%.5f initRisk=%.5f", g_s6_dir, g_s6_trailSL, g_s6_initRisk);
     }

//--- Trailing stop management
   if(posCount > 0 && !g_s6_pend)
     {
      int posType = GetPositionType(InpMagicNumber);
      long ticket = GetPositionTicket(InpMagicNumber);
      if(ticket <= 0) return;

      //--- LONG trailing
      if(posType == POSITION_TYPE_BUY && g_s6_dir == 1)
        {
         double oldTrail = g_s6_trailSL;
         if(Inp6_TrailMode == TRL_FRACTAL && flDet && flPrice > 0 && flPrice > g_s6_trailSL)
            g_s6_trailSL = flPrice;
         else if(Inp6_TrailMode == TRL_ATR)
           { double ns = c1 - h2Atr * Inp6_ATRMult; if(ns > g_s6_trailSL) g_s6_trailSL = ns; }
         else if(Inp6_TrailMode == TRL_CHANDELIER)
           {
            double highest = GetHighest(tfE, Inp6_ATRPeriod, 1);
            double ns = highest - h2Atr * Inp6_ATRMult;
            if(ns > g_s6_trailSL) g_s6_trailSL = ns;
           }
         else if(Inp6_TrailMode == TRL_EMA && h2EmaT > g_s6_trailSL)
            g_s6_trailSL = h2EmaT;

         // Breakeven
         if(Inp6_UseBreakeven && !g_s6_beActive)
           {
            double minProfit = g_s6_initRisk > 0 ? g_s6_initRisk * Inp6_BEMinR : h2Atr;
            if(g_s6_entryPx > 0 && c1 > g_s6_entryPx + minProfit)
              {
               g_s6_beActive = true;
               double beLevel = g_s6_entryPx + h2Atr * 0.3;
               if(beLevel > g_s6_trailSL) g_s6_trailSL = beLevel;
               // Partial TP
               if(Inp6_PartialMode == PRT_BE && !g_s6_partialDone)
                 {
                  double vol = GetPositionVolume(InpMagicNumber);
                  double closeQty = NormalizeDouble(vol * Inp6_PartialTPPct / 100.0, 2);
                  if(closeQty >= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN))
                    { g_trade.PositionClosePartial((ulong)ticket, closeQty); g_s6_partialDone = true; }
                 }
              }
           }

         g_trade.PositionModify((ulong)ticket, NormalizeDouble(g_s6_trailSL, _Digits), 0);
        }

      //--- SHORT trailing
      if(posType == POSITION_TYPE_SELL && g_s6_dir == -1)
        {
         if(Inp6_TrailMode == TRL_FRACTAL && fhDet && fhPrice > 0 && fhPrice < g_s6_trailSL)
            g_s6_trailSL = fhPrice;
         else if(Inp6_TrailMode == TRL_ATR)
           { double ns = c1 + h2Atr * Inp6_ATRMult; if(ns < g_s6_trailSL) g_s6_trailSL = ns; }
         else if(Inp6_TrailMode == TRL_CHANDELIER)
           {
            double lowest = GetLowest(tfE, Inp6_ATRPeriod, 1);
            double ns = lowest + h2Atr * Inp6_ATRMult;
            if(ns < g_s6_trailSL) g_s6_trailSL = ns;
           }
         else if(Inp6_TrailMode == TRL_EMA && h2EmaT > 0 && h2EmaT < g_s6_trailSL)
            g_s6_trailSL = h2EmaT;

         // Breakeven
         if(Inp6_UseBreakeven && !g_s6_beActive)
           {
            double minProfit = g_s6_initRisk > 0 ? g_s6_initRisk * Inp6_BEMinR : h2Atr;
            if(g_s6_entryPx > 0 && c1 < g_s6_entryPx - minProfit)
              {
               g_s6_beActive = true;
               double beLevel = g_s6_entryPx - h2Atr * 0.3;
               if(beLevel < g_s6_trailSL) g_s6_trailSL = beLevel;
               if(Inp6_PartialMode == PRT_BE && !g_s6_partialDone)
                 {
                  double vol = GetPositionVolume(InpMagicNumber);
                  double closeQty = NormalizeDouble(vol * Inp6_PartialTPPct / 100.0, 2);
                  if(closeQty >= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN))
                    { g_trade.PositionClosePartial((ulong)ticket, closeQty); g_s6_partialDone = true; }
                 }
              }
           }

         g_trade.PositionModify((ulong)ticket, NormalizeDouble(g_s6_trailSL, _Digits), 0);
        }
     }

//--- Reset when flat and no pending
   if(posCount == 0 && !g_s6_pend && !g_s6_waiting)
     {
      if(g_s6_dir != 0) Print("S6: RESET - position closed");
      g_s6_dir = 0; g_s6_beActive = false; g_s6_partialDone = false;
      g_s6_trailSL = 0; g_s6_entryPx = 0; g_s6_slPx = 0;
      g_s6_barsPend = 0; g_s6_initRisk = 0;
     }
  }

//+------------------------------------------------------------------+
//| End of MultiStrategy EA                                            |
//+------------------------------------------------------------------+
