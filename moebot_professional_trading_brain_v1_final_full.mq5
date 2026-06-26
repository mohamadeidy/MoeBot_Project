//+------------------------------------------------------------------+
//| MoeBot Professional Trading Brain v1 FINAL FULL                  |
//| Chart-symbol-only MT5 Expert Advisor                             |
//| Growth Mode / Small Account Growth Mode                          |
//| Core: MTF H4/H1/M15 + ICT/SMC + Wyckoff + Price Action +         |
//| Traditional confirmations + Structure SL/TP + Runner management. |
//| Added: session context, data quality, manual news windows,        |
//| file-based learning memory, detailed explainable logs.            |
//| IMPORTANT: trades ONLY _Symbol. Attach to oil chart for oil.      |
//+------------------------------------------------------------------+
#property strict
#property version   "1.10"
#property description "MoeBot Professional Trading Brain v1 FINAL FULL - chart symbol only"

#include <Trade/Trade.mqh>

CTrade trade;

//====================================================================
// ENUMS
//====================================================================
enum ENUM_BRAIN_DECISION
{
   DECISION_WAIT = 0,
   DECISION_BUY  = 1,
   DECISION_SELL = -1,
   DECISION_EXIT = 2
};

enum ENUM_BRAIN_STATE
{
   STATE_UNKNOWN = 0,
   STATE_TREND_BULL = 1,
   STATE_TREND_BEAR = 2,
   STATE_PULLBACK_BULL = 3,
   STATE_PULLBACK_BEAR = 4,
   STATE_RANGE = 5,
   STATE_REVERSAL_WARNING_BULL = 6,
   STATE_REVERSAL_WARNING_BEAR = 7,
   STATE_REVERSAL_CONFIRMED_BULL = 8,
   STATE_REVERSAL_CONFIRMED_BEAR = 9,
   STATE_EXPANSION_SPIKE = 10,
   STATE_NO_TRADE = 11
};

enum ENUM_SYMBOL_CLASS
{
   SYMBOL_CLASS_FOREX = 0,
   SYMBOL_CLASS_GOLD  = 1,
   SYMBOL_CLASS_SILVER= 2,
   SYMBOL_CLASS_OIL   = 3,
   SYMBOL_CLASS_INDEX = 4,
   SYMBOL_CLASS_OTHER = 5
};


enum ENUM_MARKET_SESSION
{
   SESSION_ASIA = 0,
   SESSION_LONDON = 1,
   SESSION_NEWYORK = 2,
   SESSION_OVERLAP = 3,
   SESSION_LOW_LIQUIDITY = 4
};

//====================================================================
// INPUTS - Growth Mode defaults agreed with user
//====================================================================
input string InpBotName = "MoeBot Professional Trading Brain v1 FINAL FULL";
input long   InpMagic   = 26062026;
input bool   InpChartSymbolOnly = true;       // Always true by design: use _Symbol only.
input bool   InpGrowthMode = true;            // No MaxTradesPerDay, fixed lots, take strong setups.
input bool   InpUseRiskPercent = false;       // OFF: do not throttle trades by percentage risk.

// Fixed lots for small account growth mode
input double InpForexLot  = 0.02;
input double InpGoldLot   = 0.01;
input double InpSilverLot = 0.01;
input double InpOilLot    = 0.01;             // Oil is allowed. Attach EA to broker oil chart.
input double InpIndexLot  = 0.01;
input double InpOtherLot  = 0.01;

// Core timeframes
input ENUM_TIMEFRAMES InpHTF = PERIOD_H4;
input ENUM_TIMEFRAMES InpMTF = PERIOD_H1;
input ENUM_TIMEFRAMES InpETF = PERIOD_M15;

// Strategy scoring
input int    InpEntryMinScore = 72;           // Strong setup threshold.
input int    InpReversalMinScore = 78;
input int    InpAddOnMinScore = 82;
input bool   InpTakeEveryStrongSetup = true;  // No artificial daily trade limits.
input bool   InpAllowBuy = true;
input bool   InpAllowSell = true;

// Add-ons and trade behavior
input bool   InpAllowSmartAddOns = true;      // Add only if existing trade is in profit and setup is strong.
input int    InpMaxAddOnsPerDirection = 0;    // 0 = unlimited. Keeps user request: do not choke trades.
input double InpAddOnMinProfitATR = 0.25;     // Same-direction position must be in profit at least this ATR.
input bool   InpCloseOnConfirmedReversal = true;
input bool   InpReverseAfterConfirmedExit = true;

// Safety only - not normal trade throttling
input bool   InpUseSpreadGuard = false;       // OFF by default to avoid reducing trades. Turn ON if needed.
input double InpMaxSpreadATRPercent = 18.0;   // If spread guard ON, block only abnormal spread vs ATR.
input bool   InpUseSpikeProtection = true;    // Blocks only catastrophic spike entries.
input double InpCatastrophicSpikeATR = 3.20;
input bool   InpManualNewsPause = false;      // Manual pause only. No external calendar in pure MQL5.
input bool   InpBlockIfOrderWouldHaveNoSLTP = true;
input bool   InpRequireTradingAllowed = true;

// Indicators
input int    InpEMAFast = 50;
input int    InpEMASlow = 200;
input int    InpRSIPeriod = 14;
input int    InpATRPeriod = 14;
input int    InpADXPeriod = 14;
input double InpADXTrendThreshold = 20.0;
input double InpADXRangeThreshold = 17.0;

// Structure / ICT / SMC
input int    InpSwingLeftRight = 2;
input int    InpSwingLookback = 120;
input double InpEqualLiquidityATR = 0.18;
input double InpOBRetestATR = 0.35;
input double InpFVGRetestATR = 0.35;
input double InpDisplacementATR = 0.62;
input double InpSweepCloseBackATR = 0.08;

// SL / TP / trade management
input double InpSL_ATR_Buffer = 0.30;
input double InpDefaultRR = 2.20;
input double InpMinRRSoft = 1.20;             // Soft scoring only, not a hard block.
input bool   InpUseBreakEven = true;
input double InpBreakEvenAtR = 0.80;
input double InpBreakEvenPlusATR = 0.05;
input bool   InpUseProfitLock = true;
input double InpProfitLockAtR = 1.20;
input double InpProfitLockR = 0.35;
input bool   InpUseATRTrailing = true;
input double InpTrailStartR = 1.50;
input double InpTrailATR = 1.20;
input bool   InpUseTPRunner = true;
input double InpRunnerNearTPPercent = 18.0;   // Extend TP when close to TP and protected.
input double InpRunnerExtendATR = 1.40;

// Logging and integrity
input bool   InpVerboseLogs = true;
input bool   InpWriteCSVLog = true;
input string InpCSVFileName = "MoeBot_Brain_v1_Full_Log.csv";
input bool   InpPrintEveryNewBar = true;

// Session / time context: scoring only by default, not a hard trade blocker.
input bool   InpUseSessionContext = true;
input int    InpServerToGMTOffsetHours = 0;       // Adjust if broker server time differs from GMT.
input bool   InpSessionCanReduceScore = false;    // OFF: respects Growth Mode; bad sessions do not choke good trades.
input int    InpLondonNYBoost = 3;
input int    InpLowLiquidityPenalty = 0;          // 0 by default so it does not reduce trades.

// Data quality / lookahead-safe integrity. Uses closed candles only.
input bool   InpStrictDataQuality = true;
input int    InpMaxAllowedMissingBars = 2;
input double InpBadTickATRMultiplier = 8.0;

// Learning layer: file-based setup memory. Boost-only by default so it learns without reducing trades.
input bool   InpUseLearningLayer = true;
input bool   InpLearningCanReduceScores = false;  // OFF: no learned penalty that could reduce good setups.
input int    InpMinLearningSamples = 8;
input int    InpLearningMaxBoost = 6;
input string InpLearningFileName = "MoeBot_Brain_v1_Final_Learning.csv";
input string InpPositionMapFileName = "MoeBot_Brain_v1_Final_PositionMap.csv";

// News layer: pure MQL5 cannot read a reliable economic calendar from all brokers. Manual pause + spike protection stay available.
input bool   InpUseManualNewsWindows = false;
input string InpManualNewsWindowsGMT = "";        // Example: 12:25-12:45;14:55-15:15 GMT. Empty = disabled.

//====================================================================
// STRUCTURES
//====================================================================
struct SwingMap
{
   double lastHigh;
   double prevHigh;
   double lastLow;
   double prevLow;
   datetime lastHighTime;
   datetime prevHighTime;
   datetime lastLowTime;
   datetime prevLowTime;
   bool validHigh;
   bool validLow;
};

struct Zone
{
   bool valid;
   double low;
   double high;
   datetime time;
   int direction; // 1 bullish zone, -1 bearish zone
   string name;
};

struct TFBrain
{
   ENUM_TIMEFRAMES tf;
   string name;
   bool dataOK;
   string dataNote;

   double close1;
   double open1;
   double high1;
   double low1;
   double close2;
   double high2;
   double low2;

   double emaFast;
   double emaSlow;
   double emaFastPrev;
   double emaSlowPrev;
   double rsi;
   double atr;
   double adx;
   double plusDI;
   double minusDI;

   SwingMap swings;
   int emaBias;       // 1 bull, -1 bear, 0 neutral
   int structureBias; // 1 HH/HL, -1 LH/LL, 0 neutral
   int finalBias;

   bool rangeLike;
   bool displacementUp;
   bool displacementDown;
   bool sweepHigh;
   bool sweepLow;
   bool bosUp;
   bool bosDown;
   bool chochUp;
   bool chochDown;
   bool mssUp;
   bool mssDown;

   bool inPremium;
   bool inDiscount;
   bool nearEquilibrium;
   double rangeHigh;
   double rangeLow;
   double rangeMid;

   bool equalHighs;
   bool equalLows;

   Zone bullFVG;
   Zone bearFVG;
   Zone bullOB;
   Zone bearOB;

   bool priceNearBullFVG;
   bool priceNearBearFVG;
   bool priceNearBullOB;
   bool priceNearBearOB;

   bool wyckoffSpring;
   bool wyckoffUpthrust;
   bool accumulationHint;
   bool distributionHint;

   bool rsiBullishExhaustion;
   bool rsiBearishExhaustion;
   bool rsiBullDiv;
   bool rsiBearDiv;

   int bullScore;
   int bearScore;
   string notes;
};

struct BrainDecision
{
   ENUM_BRAIN_DECISION decision;
   ENUM_BRAIN_STATE state;
   int buyScore;
   int sellScore;
   bool blockBuy;
   bool blockSell;
   string reason;
   string sessionName;
   string setupKey;
   int learningBias;
   double sl;
   double tp;
   double lot;
   double entry;
};


struct LearningStat
{
   string key;
   int wins;
   int losses;
   double netProfit;
};

struct PositionKeyMap
{
   long positionId;
   string key;
};

//====================================================================
// GLOBALS
//====================================================================
datetime g_lastETFBarTime = 0;
datetime g_lastManageTime = 0;
string   g_lastDecisionText = "";
LearningStat g_learning[];
PositionKeyMap g_posKeys[];


//====================================================================
// SESSION / NEWS / LEARNING MEMORY
//====================================================================
int ServerHourGMTAdjusted()
{
   datetime t = TimeCurrent() - InpServerToGMTOffsetHours*3600;
   MqlDateTime dt;
   TimeToStruct(t,dt);
   return dt.hour;
}

ENUM_MARKET_SESSION CurrentSession()
{
   int h = ServerHourGMTAdjusted();
   // Broad GMT windows, used as context not hard blocking.
   if(h>=13 && h<17) return SESSION_OVERLAP;
   if(h>=7 && h<13) return SESSION_LONDON;
   if(h>=17 && h<21) return SESSION_NEWYORK;
   if(h>=22 || h<6) return SESSION_ASIA;
   return SESSION_LOW_LIQUIDITY;
}

string SessionName(ENUM_MARKET_SESSION s)
{
   if(s==SESSION_ASIA) return "ASIA";
   if(s==SESSION_LONDON) return "LONDON";
   if(s==SESSION_NEWYORK) return "NEWYORK";
   if(s==SESSION_OVERLAP) return "OVERLAP";
   return "LOW_LIQ";
}

string StateCode(ENUM_BRAIN_STATE s)
{
   if(s==STATE_TREND_BULL) return "TB";
   if(s==STATE_TREND_BEAR) return "TS";
   if(s==STATE_PULLBACK_BULL) return "PB";
   if(s==STATE_PULLBACK_BEAR) return "PS";
   if(s==STATE_RANGE) return "RG";
   if(s==STATE_REVERSAL_WARNING_BULL) return "RWB";
   if(s==STATE_REVERSAL_WARNING_BEAR) return "RWS";
   if(s==STATE_REVERSAL_CONFIRMED_BULL) return "RCB";
   if(s==STATE_REVERSAL_CONFIRMED_BEAR) return "RCS";
   if(s==STATE_EXPANSION_SPIKE) return "SPK";
   if(s==STATE_NO_TRADE) return "NT";
   return "UK";
}

bool TimeInManualNewsWindow()
{
   if(!InpUseManualNewsWindows || InpManualNewsWindowsGMT=="") return false;
   int h = ServerHourGMTAdjusted();
   MqlDateTime dt;
   TimeToStruct(TimeCurrent() - InpServerToGMTOffsetHours*3600, dt);
   int nowMin = h*60 + dt.min;
   string windows = InpManualNewsWindowsGMT;
   string parts[];
   int n = StringSplit(windows, ';', parts);
   for(int i=0;i<n;i++)
   {
      string w = parts[i];
      StringTrimLeft(w); StringTrimRight(w);
      if(StringLen(w)<11) continue;
      string ab[];
      if(StringSplit(w, '-', ab)!=2) continue;
      string a=ab[0], b=ab[1];
      StringTrimLeft(a); StringTrimRight(a); StringTrimLeft(b); StringTrimRight(b);
      if(StringLen(a)<5 || StringLen(b)<5) continue;
      int ah=(int)StringToInteger(StringSubstr(a,0,2));
      int am=(int)StringToInteger(StringSubstr(a,3,2));
      int bh=(int)StringToInteger(StringSubstr(b,0,2));
      int bm=(int)StringToInteger(StringSubstr(b,3,2));
      int start=ah*60+am, end=bh*60+bm;
      if(start<=end)
      {
         if(nowMin>=start && nowMin<=end) return true;
      }
      else
      {
         if(nowMin>=start || nowMin<=end) return true;
      }
   }
   return false;
}

int FindLearningIndex(string key)
{
   for(int i=0;i<ArraySize(g_learning);i++) if(g_learning[i].key==key) return i;
   return -1;
}

void AddOrUpdateLearning(string key, bool win, double profit)
{
   if(key=="") key="UNKNOWN";
   int idx = FindLearningIndex(key);
   if(idx<0)
   {
      int n=ArraySize(g_learning);
      ArrayResize(g_learning,n+1);
      g_learning[n].key=key;
      g_learning[n].wins=0;
      g_learning[n].losses=0;
      g_learning[n].netProfit=0;
      idx=n;
   }
   if(win) g_learning[idx].wins++;
   else g_learning[idx].losses++;
   g_learning[idx].netProfit += profit;
}

void SaveLearningStats()
{
   if(!InpUseLearningLayer) return;
   int h = FileOpen(InpLearningFileName, FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   FileWrite(h,"key","wins","losses","netProfit");
   for(int i=0;i<ArraySize(g_learning);i++)
      FileWrite(h,g_learning[i].key,g_learning[i].wins,g_learning[i].losses,DoubleToString(g_learning[i].netProfit,2));
   FileClose(h);
}

void LoadLearningStats()
{
   ArrayResize(g_learning,0);
   if(!InpUseLearningLayer) return;
   int h = FileOpen(InpLearningFileName, FILE_READ|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   if(!FileIsEnding(h))
   {
      // skip header
      FileReadString(h); FileReadString(h); FileReadString(h); FileReadString(h);
   }
   while(!FileIsEnding(h))
   {
      string key = FileReadString(h);
      if(key=="") break;
      int wins = (int)StringToInteger(FileReadString(h));
      int losses = (int)StringToInteger(FileReadString(h));
      double net = StringToDouble(FileReadString(h));
      int n=ArraySize(g_learning);
      ArrayResize(g_learning,n+1);
      g_learning[n].key=key; g_learning[n].wins=wins; g_learning[n].losses=losses; g_learning[n].netProfit=net;
   }
   FileClose(h);
}

int LearningBiasForKey(string key)
{
   if(!InpUseLearningLayer || key=="") return 0;
   int idx=FindLearningIndex(key);
   if(idx<0) return 0;
   int total = g_learning[idx].wins + g_learning[idx].losses;
   if(total < InpMinLearningSamples) return 0;
   double wr = (double)g_learning[idx].wins / (double)total;
   int halfBoost = InpLearningMaxBoost/2;
   if(halfBoost<1) halfBoost=1;
   if(wr>=0.62 && g_learning[idx].netProfit>0) return InpLearningMaxBoost;
   if(wr>=0.55 && g_learning[idx].netProfit>0) return halfBoost;
   if(InpLearningCanReduceScores)
   {
      if(wr<=0.38 || g_learning[idx].netProfit<0) return -InpLearningMaxBoost;
      if(wr<=0.45) return -halfBoost;
   }
   return 0;
}

int FindPositionKeyIndex(long posid)
{
   for(int i=0;i<ArraySize(g_posKeys);i++) if(g_posKeys[i].positionId==posid) return i;
   return -1;
}

void SavePositionMap()
{
   int h = FileOpen(InpPositionMapFileName, FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   FileWrite(h,"positionId","setupKey");
   for(int i=0;i<ArraySize(g_posKeys);i++) FileWrite(h,IntegerToString(g_posKeys[i].positionId),g_posKeys[i].key);
   FileClose(h);
}

void LoadPositionMap()
{
   ArrayResize(g_posKeys,0);
   int h = FileOpen(InpPositionMapFileName, FILE_READ|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   if(!FileIsEnding(h)) { FileReadString(h); FileReadString(h); }
   while(!FileIsEnding(h))
   {
      string sid = FileReadString(h);
      if(sid=="") break;
      string key = FileReadString(h);
      int n=ArraySize(g_posKeys);
      ArrayResize(g_posKeys,n+1);
      g_posKeys[n].positionId=(long)StringToInteger(sid);
      g_posKeys[n].key=key;
   }
   FileClose(h);
}

void StorePositionKey(long posid, string key)
{
   if(posid<=0 || key=="") return;
   int idx=FindPositionKeyIndex(posid);
   if(idx<0)
   {
      int n=ArraySize(g_posKeys);
      ArrayResize(g_posKeys,n+1);
      g_posKeys[n].positionId=posid;
      g_posKeys[n].key=key;
   }
   else g_posKeys[idx].key=key;
   SavePositionMap();
}

string KeyForPosition(long posid)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx>=0) return g_posKeys[idx].key;
   return "UNKNOWN";
}

void RemovePositionKey(long posid)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx<0) return;
   int n=ArraySize(g_posKeys);
   for(int i=idx;i<n-1;i++) g_posKeys[i]=g_posKeys[i+1];
   ArrayResize(g_posKeys,n-1);
   SavePositionMap();
}

bool DataGapCheck(ENUM_TIMEFRAMES tf, string &note)
{
   if(!InpStrictDataQuality) { note="OK"; return true; }
   MqlRates r[];
   int need=60;
   if(!CopyRatesSafe(tf,need,r)) { note="GapCheck CopyRates failed"; return false; }
   int sec=PeriodSeconds(tf);
   if(sec<=0) { note="Invalid timeframe seconds"; return false; }
   int gaps=0;
   for(int i=1;i<need-1;i++)
   {
      int diff=(int)(r[i].time-r[i+1].time);
      if(diff > sec*2) gaps++;
      if(r[i].high<=0 || r[i].low<=0 || r[i].high<r[i].low || r[i].close<=0)
      { note="Bad OHLC values on "+TFToString(tf); return false; }
   }
   if(gaps>InpMaxAllowedMissingBars)
   {
      note="Too many candle gaps on "+TFToString(tf)+": "+IntegerToString(gaps);
      return false;
   }
   note="OK";
   return true;
}

//====================================================================
// UTILS
//====================================================================
string TFToString(ENUM_TIMEFRAMES tf)
{
   if(tf==PERIOD_M1) return "M1";
   if(tf==PERIOD_M5) return "M5";
   if(tf==PERIOD_M15) return "M15";
   if(tf==PERIOD_M30) return "M30";
   if(tf==PERIOD_H1) return "H1";
   if(tf==PERIOD_H4) return "H4";
   if(tf==PERIOD_D1) return "D1";
   return EnumToString(tf);
}

string DecisionToString(ENUM_BRAIN_DECISION d)
{
   if(d==DECISION_BUY) return "BUY";
   if(d==DECISION_SELL) return "SELL";
   if(d==DECISION_EXIT) return "EXIT";
   return "WAIT";
}

string StateToString(ENUM_BRAIN_STATE s)
{
   switch(s)
   {
      case STATE_TREND_BULL: return "Trend Bull";
      case STATE_TREND_BEAR: return "Trend Bear";
      case STATE_PULLBACK_BULL: return "Bull Pullback";
      case STATE_PULLBACK_BEAR: return "Bear Pullback";
      case STATE_RANGE: return "Range";
      case STATE_REVERSAL_WARNING_BULL: return "Reversal Warning Bull";
      case STATE_REVERSAL_WARNING_BEAR: return "Reversal Warning Bear";
      case STATE_REVERSAL_CONFIRMED_BULL: return "Reversal Confirmed Bull";
      case STATE_REVERSAL_CONFIRMED_BEAR: return "Reversal Confirmed Bear";
      case STATE_EXPANSION_SPIKE: return "Expansion/Spike";
      case STATE_NO_TRADE: return "No Trade";
      default: return "Unknown";
   }
}

void VPrint(string msg)
{
   if(InpVerboseLogs) Print(InpBotName," | ",_Symbol," | ",msg);
}

bool IsNewBar(ENUM_TIMEFRAMES tf)
{
   datetime t = iTime(_Symbol, tf, 0);
   if(t <= 0) return false;
   if(t != g_lastETFBarTime)
   {
      g_lastETFBarTime = t;
      return true;
   }
   return false;
}

double PointValue()
{
   double p = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(p<=0) p = _Point;
   return p;
}

double NormalizePrice(double price)
{
   return NormalizeDouble(price, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
}

double CurrentBid()
{
   double v=0;
   SymbolInfoDouble(_Symbol, SYMBOL_BID, v);
   return v;
}

double CurrentAsk()
{
   double v=0;
   SymbolInfoDouble(_Symbol, SYMBOL_ASK, v);
   return v;
}

double CurrentMid()
{
   return (CurrentBid()+CurrentAsk())/2.0;
}

string UpperSymbol()
{
   string s = _Symbol;
   StringToUpper(s);
   return s;
}

ENUM_SYMBOL_CLASS SymbolClass()
{
   string s = UpperSymbol();
   if(StringFind(s,"XAU")>=0 || StringFind(s,"GOLD")>=0) return SYMBOL_CLASS_GOLD;
   if(StringFind(s,"XAG")>=0 || StringFind(s,"SILVER")>=0) return SYMBOL_CLASS_SILVER;
   if(StringFind(s,"OIL")>=0 || StringFind(s,"WTI")>=0 || StringFind(s,"BRENT")>=0 || StringFind(s,"USO")>=0 || StringFind(s,"XTI")>=0 || StringFind(s,"UKO")>=0 || StringFind(s,"CL")>=0) return SYMBOL_CLASS_OIL;
   if(StringFind(s,"NAS")>=0 || StringFind(s,"US30")>=0 || StringFind(s,"DJ")>=0 || StringFind(s,"SPX")>=0 || StringFind(s,"US500")>=0 || StringFind(s,"GER")>=0 || StringFind(s,"DAX")>=0) return SYMBOL_CLASS_INDEX;

   // Basic FX detection: six-letter pair may have suffix, so inspect common currencies.
   string ccy[8] = {"USD","EUR","GBP","JPY","AUD","NZD","CAD","CHF"};
   int hits=0;
   for(int i=0;i<8;i++) if(StringFind(s,ccy[i])>=0) hits++;
   if(hits>=2) return SYMBOL_CLASS_FOREX;

   return SYMBOL_CLASS_OTHER;
}

string SymbolClassName(ENUM_SYMBOL_CLASS c)
{
   if(c==SYMBOL_CLASS_FOREX) return "FOREX";
   if(c==SYMBOL_CLASS_GOLD) return "GOLD";
   if(c==SYMBOL_CLASS_SILVER) return "SILVER";
   if(c==SYMBOL_CLASS_OIL) return "OIL";
   if(c==SYMBOL_CLASS_INDEX) return "INDEX";
   return "OTHER";
}

double FixedLotBySymbol()
{
   ENUM_SYMBOL_CLASS c = SymbolClass();
   if(c==SYMBOL_CLASS_FOREX) return InpForexLot;
   if(c==SYMBOL_CLASS_GOLD) return InpGoldLot;
   if(c==SYMBOL_CLASS_SILVER) return InpSilverLot;
   if(c==SYMBOL_CLASS_OIL) return InpOilLot;
   if(c==SYMBOL_CLASS_INDEX) return InpIndexLot;
   return InpOtherLot;
}

double NormalizeLot(double lot)
{
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(minLot<=0) minLot=0.01;
   if(maxLot<=0) maxLot=100.0;
   if(step<=0) step=0.01;

   lot = MathMax(lot, minLot);
   lot = MathMin(lot, maxLot);
   double steps = MathFloor((lot - minLot) / step + 0.5);
   double norm = minLot + steps*step;
   if(norm < minLot) norm = minLot;
   if(norm > maxLot) norm = maxLot;
   return NormalizeDouble(norm, 2);
}

bool DataSeriesOK(ENUM_TIMEFRAMES tf, string &note)
{
   note = "OK";
   if(Bars(_Symbol, tf) < MathMax(InpSwingLookback+20, 250))
   {
      note = "Not enough bars on " + TFToString(tf);
      return false;
   }
   long sync=0;
   if(!SeriesInfoInteger(_Symbol, tf, SERIES_SYNCHRONIZED, sync))
   {
      note = "SeriesInfo failed on " + TFToString(tf);
      return false;
   }
   if(sync==0)
   {
      note = "Series not synchronized on " + TFToString(tf);
      return false;
   }
   datetime t1 = iTime(_Symbol, tf, 1);
   if(t1<=0)
   {
      note = "No closed candle on " + TFToString(tf);
      return false;
   }
   string gapNote;
   if(!DataGapCheck(tf,gapNote))
   {
      note = gapNote;
      return false;
   }
   return true;
}

bool CopyRatesSafe(ENUM_TIMEFRAMES tf, int count, MqlRates &rates[])
{
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, tf, 0, count, rates);
   return copied >= count;
}

double GetMA(ENUM_TIMEFRAMES tf, int period, int shift)
{
   int h = iMA(_Symbol, tf, period, 0, MODE_EMA, PRICE_CLOSE);
   if(h==INVALID_HANDLE) return 0.0;
   double b[];
   ArraySetAsSeries(b,true);
   if(CopyBuffer(h,0,shift,1,b)<1)
   {
      IndicatorRelease(h);
      return 0.0;
   }
   IndicatorRelease(h);
   return b[0];
}

double GetRSI(ENUM_TIMEFRAMES tf, int shift)
{
   int h = iRSI(_Symbol, tf, InpRSIPeriod, PRICE_CLOSE);
   if(h==INVALID_HANDLE) return 50.0;
   double b[];
   ArraySetAsSeries(b,true);
   if(CopyBuffer(h,0,shift,1,b)<1)
   {
      IndicatorRelease(h);
      return 50.0;
   }
   IndicatorRelease(h);
   return b[0];
}

double GetATR(ENUM_TIMEFRAMES tf, int shift)
{
   int h = iATR(_Symbol, tf, InpATRPeriod);
   if(h==INVALID_HANDLE) return 0.0;
   double b[];
   ArraySetAsSeries(b,true);
   if(CopyBuffer(h,0,shift,1,b)<1)
   {
      IndicatorRelease(h);
      return 0.0;
   }
   IndicatorRelease(h);
   return b[0];
}

bool GetADXValues(ENUM_TIMEFRAMES tf, int shift, double &adx, double &plusDI, double &minusDI)
{
   adx=0; plusDI=0; minusDI=0;
   int h = iADX(_Symbol, tf, InpADXPeriod);
   if(h==INVALID_HANDLE) return false;
   double a[],p[],m[];
   ArraySetAsSeries(a,true); ArraySetAsSeries(p,true); ArraySetAsSeries(m,true);
   bool ok = (CopyBuffer(h,0,shift,1,a)>=1 && CopyBuffer(h,1,shift,1,p)>=1 && CopyBuffer(h,2,shift,1,m)>=1);
   IndicatorRelease(h);
   if(!ok) return false;
   adx=a[0]; plusDI=p[0]; minusDI=m[0];
   return true;
}

//====================================================================
// SWINGS / STRUCTURE
//====================================================================
void ResetSwingMap(SwingMap &s)
{
   s.lastHigh=0; s.prevHigh=0; s.lastLow=0; s.prevLow=0;
   s.lastHighTime=0; s.prevHighTime=0; s.lastLowTime=0; s.prevLowTime=0;
   s.validHigh=false; s.validLow=false;
}

bool IsSwingHigh(MqlRates &r[], int i, int lr)
{
   for(int j=1;j<=lr;j++)
   {
      if(r[i].high <= r[i-j].high) return false;
      if(r[i].high <= r[i+j].high) return false;
   }
   return true;
}

bool IsSwingLow(MqlRates &r[], int i, int lr)
{
   for(int j=1;j<=lr;j++)
   {
      if(r[i].low >= r[i-j].low) return false;
      if(r[i].low >= r[i+j].low) return false;
   }
   return true;
}

bool BuildSwingMap(ENUM_TIMEFRAMES tf, SwingMap &s)
{
   ResetSwingMap(s);
   int lr = MathMax(1, InpSwingLeftRight);
   int need = MathMax(InpSwingLookback + lr + 10, 80);
   MqlRates r[];
   if(!CopyRatesSafe(tf, need, r)) return false;

   int highCount=0, lowCount=0;
   for(int i=lr+1; i<need-lr; i++)
   {
      if(highCount<2 && IsSwingHigh(r,i,lr))
      {
         if(highCount==0)
         {
            s.lastHigh = r[i].high;
            s.lastHighTime = r[i].time;
            s.validHigh = true;
         }
         else
         {
            s.prevHigh = r[i].high;
            s.prevHighTime = r[i].time;
         }
         highCount++;
      }
      if(lowCount<2 && IsSwingLow(r,i,lr))
      {
         if(lowCount==0)
         {
            s.lastLow = r[i].low;
            s.lastLowTime = r[i].time;
            s.validLow = true;
         }
         else
         {
            s.prevLow = r[i].low;
            s.prevLowTime = r[i].time;
         }
         lowCount++;
      }
      if(highCount>=2 && lowCount>=2) break;
   }
   return (s.validHigh && s.validLow);
}

int StructureBiasFromSwings(SwingMap &s)
{
   if(!s.validHigh || !s.validLow || s.prevHigh<=0 || s.prevLow<=0) return 0;
   bool hh = (s.lastHigh > s.prevHigh);
   bool hl = (s.lastLow  > s.prevLow);
   bool lh = (s.lastHigh < s.prevHigh);
   bool ll = (s.lastLow  < s.prevLow);
   if(hh && hl) return 1;
   if(lh && ll) return -1;
   return 0;
}

void InitZone(Zone &z)
{
   z.valid=false;
   z.low=0; z.high=0; z.time=0; z.direction=0; z.name="";
}

bool PriceNearZone(double price, Zone &z, double atr, double toleranceATR)
{
   if(!z.valid || atr<=0) return false;
   if(price >= z.low && price <= z.high) return true;
   double tol = atr * toleranceATR;
   if(MathAbs(price - z.low) <= tol || MathAbs(price - z.high) <= tol) return true;
   return false;
}

void DetectFVG(ENUM_TIMEFRAMES tf, TFBrain &b)
{
   InitZone(b.bullFVG);
   InitZone(b.bearFVG);
   MqlRates r[];
   if(!CopyRatesSafe(tf, 8, r)) return;

   // Closed candles only: shifts 1,2,3.
   // Bullish FVG: low of recent candle > high of older candle.
   if(r[1].low > r[3].high)
   {
      b.bullFVG.valid = true;
      b.bullFVG.low = r[3].high;
      b.bullFVG.high = r[1].low;
      b.bullFVG.time = r[1].time;
      b.bullFVG.direction = 1;
      b.bullFVG.name = "Bullish FVG";
   }

   // Bearish FVG: high of recent candle < low of older candle.
   if(r[1].high < r[3].low)
   {
      b.bearFVG.valid = true;
      b.bearFVG.low = r[1].high;
      b.bearFVG.high = r[3].low;
      b.bearFVG.time = r[1].time;
      b.bearFVG.direction = -1;
      b.bearFVG.name = "Bearish FVG";
   }
}

void DetectOrderBlocks(ENUM_TIMEFRAMES tf, TFBrain &b)
{
   InitZone(b.bullOB);
   InitZone(b.bearOB);
   MqlRates r[];
   int count = 40;
   if(!CopyRatesSafe(tf, count, r)) return;
   double atr = b.atr;
   if(atr<=0) return;

   // Find the latest bullish displacement and last bearish candle before it.
   for(int i=1; i<18; i++)
   {
      double body = MathAbs(r[i].close - r[i].open);
      bool upDisp = (r[i].close > r[i].open && body >= atr * InpDisplacementATR);
      if(upDisp)
      {
         for(int j=i+1; j<MathMin(i+12,count-1); j++)
         {
            if(r[j].close < r[j].open)
            {
               b.bullOB.valid = true;
               b.bullOB.low = r[j].low;
               b.bullOB.high = MathMax(r[j].open, r[j].close);
               b.bullOB.time = r[j].time;
               b.bullOB.direction = 1;
               b.bullOB.name = "Bullish Order Block";
               break;
            }
         }
      }
      if(b.bullOB.valid) break;
   }

   // Find the latest bearish displacement and last bullish candle before it.
   for(int i=1; i<18; i++)
   {
      double body = MathAbs(r[i].close - r[i].open);
      bool downDisp = (r[i].close < r[i].open && body >= atr * InpDisplacementATR);
      if(downDisp)
      {
         for(int j=i+1; j<MathMin(i+12,count-1); j++)
         {
            if(r[j].close > r[j].open)
            {
               b.bearOB.valid = true;
               b.bearOB.low = MathMin(r[j].open, r[j].close);
               b.bearOB.high = r[j].high;
               b.bearOB.time = r[j].time;
               b.bearOB.direction = -1;
               b.bearOB.name = "Bearish Order Block";
               break;
            }
         }
      }
      if(b.bearOB.valid) break;
   }
}

bool EqualHighsDetected(ENUM_TIMEFRAMES tf, double atr)
{
   if(atr<=0) return false;
   MqlRates r[];
   if(!CopyRatesSafe(tf, 80, r)) return false;
   double tol = atr * InpEqualLiquidityATR;
   for(int i=2;i<30;i++)
   {
      for(int j=i+3;j<60;j++)
      {
         if(MathAbs(r[i].high-r[j].high) <= tol) return true;
      }
   }
   return false;
}

bool EqualLowsDetected(ENUM_TIMEFRAMES tf, double atr)
{
   if(atr<=0) return false;
   MqlRates r[];
   if(!CopyRatesSafe(tf, 80, r)) return false;
   double tol = atr * InpEqualLiquidityATR;
   for(int i=2;i<30;i++)
   {
      for(int j=i+3;j<60;j++)
      {
         if(MathAbs(r[i].low-r[j].low) <= tol) return true;
      }
   }
   return false;
}

bool SimpleBullishDivergence(ENUM_TIMEFRAMES tf, double atr)
{
   if(atr<=0) return false;
   MqlRates r[];
   if(!CopyRatesSafe(tf, 50, r)) return false;
   // lightweight divergence: price makes lower low, RSI makes higher low between two recent swing zones.
   int a=-1,b=-1;
   for(int i=3;i<20;i++) if(r[i].low < r[i-1].low && r[i].low < r[i+1].low) { a=i; break; }
   for(int i=a+3;i<40 && a>0;i++) if(r[i].low < r[i-1].low && r[i].low < r[i+1].low) { b=i; break; }
   if(a<0 || b<0) return false;
   double rsiA = GetRSI(tf,a);
   double rsiB = GetRSI(tf,b);
   if(r[a].low < r[b].low && rsiA > rsiB) return true;
   return false;
}

bool SimpleBearishDivergence(ENUM_TIMEFRAMES tf, double atr)
{
   if(atr<=0) return false;
   MqlRates r[];
   if(!CopyRatesSafe(tf, 50, r)) return false;
   int a=-1,b=-1;
   for(int i=3;i<20;i++) if(r[i].high > r[i-1].high && r[i].high > r[i+1].high) { a=i; break; }
   for(int i=a+3;i<40 && a>0;i++) if(r[i].high > r[i-1].high && r[i].high > r[i+1].high) { b=i; break; }
   if(a<0 || b<0) return false;
   double rsiA = GetRSI(tf,a);
   double rsiB = GetRSI(tf,b);
   if(r[a].high > r[b].high && rsiA < rsiB) return true;
   return false;
}

//====================================================================
// TF BRAIN BUILDER
//====================================================================
void ResetTFBrain(TFBrain &b)
{
   b.dataOK=false; b.dataNote="";
   b.close1=0; b.open1=0; b.high1=0; b.low1=0; b.close2=0; b.high2=0; b.low2=0;
   b.emaFast=0; b.emaSlow=0; b.emaFastPrev=0; b.emaSlowPrev=0;
   b.rsi=50; b.atr=0; b.adx=0; b.plusDI=0; b.minusDI=0;
   ResetSwingMap(b.swings);
   b.emaBias=0; b.structureBias=0; b.finalBias=0;
   b.rangeLike=false; b.displacementUp=false; b.displacementDown=false;
   b.sweepHigh=false; b.sweepLow=false; b.bosUp=false; b.bosDown=false;
   b.chochUp=false; b.chochDown=false; b.mssUp=false; b.mssDown=false;
   b.inPremium=false; b.inDiscount=false; b.nearEquilibrium=false;
   b.rangeHigh=0; b.rangeLow=0; b.rangeMid=0;
   b.equalHighs=false; b.equalLows=false;
   InitZone(b.bullFVG); InitZone(b.bearFVG); InitZone(b.bullOB); InitZone(b.bearOB);
   b.priceNearBullFVG=false; b.priceNearBearFVG=false; b.priceNearBullOB=false; b.priceNearBearOB=false;
   b.wyckoffSpring=false; b.wyckoffUpthrust=false; b.accumulationHint=false; b.distributionHint=false;
   b.rsiBullishExhaustion=false; b.rsiBearishExhaustion=false; b.rsiBullDiv=false; b.rsiBearDiv=false;
   b.bullScore=0; b.bearScore=0; b.notes="";
}

bool BuildTFBrain(ENUM_TIMEFRAMES tf, string name, TFBrain &b)
{
   ResetTFBrain(b);
   b.tf = tf;
   b.name = name;
   string note;
   if(!DataSeriesOK(tf,note))
   {
      b.dataOK=false;
      b.dataNote=note;
      return false;
   }

   MqlRates r[];
   if(!CopyRatesSafe(tf, MathMax(InpSwingLookback+30, 260), r))
   {
      b.dataOK=false;
      b.dataNote="CopyRates failed";
      return false;
   }

   b.dataOK=true;
   b.dataNote="OK";
   b.open1 = r[1].open;
   b.close1 = r[1].close;
   b.high1 = r[1].high;
   b.low1 = r[1].low;
   b.close2 = r[2].close;
   b.high2 = r[2].high;
   b.low2 = r[2].low;

   b.emaFast = GetMA(tf, InpEMAFast, 1);
   b.emaSlow = GetMA(tf, InpEMASlow, 1);
   b.emaFastPrev = GetMA(tf, InpEMAFast, 4);
   b.emaSlowPrev = GetMA(tf, InpEMASlow, 4);
   b.rsi = GetRSI(tf,1);
   b.atr = GetATR(tf,1);
   GetADXValues(tf,1,b.adx,b.plusDI,b.minusDI);

   BuildSwingMap(tf,b.swings);
   b.structureBias = StructureBiasFromSwings(b.swings);

   if(b.emaFast > b.emaSlow && b.emaFast >= b.emaFastPrev) b.emaBias=1;
   else if(b.emaFast < b.emaSlow && b.emaFast <= b.emaFastPrev) b.emaBias=-1;
   else b.emaBias=0;

   if(b.structureBias!=0 && b.emaBias!=0)
   {
      if(b.structureBias==b.emaBias) b.finalBias=b.structureBias;
      else b.finalBias=0;
   }
   else if(b.structureBias!=0) b.finalBias=b.structureBias;
   else b.finalBias=b.emaBias;

   if(b.atr>0)
   {
      double body = MathAbs(b.close1-b.open1);
      b.displacementUp = (b.close1>b.open1 && body >= b.atr*InpDisplacementATR);
      b.displacementDown = (b.close1<b.open1 && body >= b.atr*InpDisplacementATR);
   }

   if(b.swings.validHigh)
   {
      b.sweepHigh = (b.high1 > b.swings.lastHigh && b.close1 < b.swings.lastHigh - b.atr*InpSweepCloseBackATR);
      b.bosUp = (b.close1 > b.swings.lastHigh);
   }
   if(b.swings.validLow)
   {
      b.sweepLow = (b.low1 < b.swings.lastLow && b.close1 > b.swings.lastLow + b.atr*InpSweepCloseBackATR);
      b.bosDown = (b.close1 < b.swings.lastLow);
   }

   b.chochUp = (b.finalBias<0 && b.bosUp);
   b.chochDown = (b.finalBias>0 && b.bosDown);
   b.mssUp = (b.sweepLow && b.displacementUp && (b.close1 > b.high2 || b.bosUp));
   b.mssDown = (b.sweepHigh && b.displacementDown && (b.close1 < b.low2 || b.bosDown));

   // Premium / Discount based on current relevant range.
   if(b.swings.validHigh && b.swings.validLow)
   {
      b.rangeHigh = b.swings.lastHigh;
      b.rangeLow = b.swings.lastLow;
      if(b.rangeLow > b.rangeHigh)
      {
         double tmp=b.rangeLow; b.rangeLow=b.rangeHigh; b.rangeHigh=tmp;
      }
      b.rangeMid = (b.rangeHigh+b.rangeLow)/2.0;
      double price = b.close1;
      double eqTol = MathMax(b.atr*0.15, PointValue()*20);
      b.inDiscount = (price < b.rangeMid-eqTol);
      b.inPremium = (price > b.rangeMid+eqTol);
      b.nearEquilibrium = (!b.inDiscount && !b.inPremium);
   }

   b.rangeLike = (b.adx > 0 && b.adx < InpADXRangeThreshold);
   b.equalHighs = EqualHighsDetected(tf,b.atr);
   b.equalLows = EqualLowsDetected(tf,b.atr);

   DetectFVG(tf,b);
   DetectOrderBlocks(tf,b);
   double priceMid = CurrentMid();
   b.priceNearBullFVG = PriceNearZone(priceMid,b.bullFVG,b.atr,InpFVGRetestATR);
   b.priceNearBearFVG = PriceNearZone(priceMid,b.bearFVG,b.atr,InpFVGRetestATR);
   b.priceNearBullOB = PriceNearZone(priceMid,b.bullOB,b.atr,InpOBRetestATR);
   b.priceNearBearOB = PriceNearZone(priceMid,b.bearOB,b.atr,InpOBRetestATR);

   // Wyckoff hints: use range + sweep + close-back + displacement as simplified spring/upthrust.
   b.wyckoffSpring = (b.rangeLike && b.sweepLow && (b.displacementUp || b.close1>b.open1));
   b.wyckoffUpthrust = (b.rangeLike && b.sweepHigh && (b.displacementDown || b.close1<b.open1));
   b.accumulationHint = (b.rangeLike && (b.equalLows || b.wyckoffSpring) && b.rsi<55);
   b.distributionHint = (b.rangeLike && (b.equalHighs || b.wyckoffUpthrust) && b.rsi>45);

   b.rsiBullishExhaustion = (b.rsi <= 32.0);
   b.rsiBearishExhaustion = (b.rsi >= 68.0);
   b.rsiBullDiv = SimpleBullishDivergence(tf,b.atr);
   b.rsiBearDiv = SimpleBearishDivergence(tf,b.atr);

   // Local timeframe scores.
   if(b.finalBias>0) b.bullScore += 12;
   if(b.finalBias<0) b.bearScore += 12;
   if(b.structureBias>0) b.bullScore += 8;
   if(b.structureBias<0) b.bearScore += 8;
   if(b.emaBias>0) b.bullScore += 5;
   if(b.emaBias<0) b.bearScore += 5;
   if(b.sweepLow) b.bullScore += 12;
   if(b.sweepHigh) b.bearScore += 12;
   if(b.displacementUp) b.bullScore += 10;
   if(b.displacementDown) b.bearScore += 10;
   if(b.bosUp) b.bullScore += 12;
   if(b.bosDown) b.bearScore += 12;
   if(b.chochUp || b.mssUp) b.bullScore += 14;
   if(b.chochDown || b.mssDown) b.bearScore += 14;
   if(b.inDiscount) b.bullScore += 7;
   if(b.inPremium) b.bearScore += 7;
   if(b.priceNearBullFVG) b.bullScore += 8;
   if(b.priceNearBearFVG) b.bearScore += 8;
   if(b.priceNearBullOB) b.bullScore += 10;
   if(b.priceNearBearOB) b.bearScore += 10;
   if(b.wyckoffSpring || b.accumulationHint) b.bullScore += 8;
   if(b.wyckoffUpthrust || b.distributionHint) b.bearScore += 8;
   if(b.rsiBullishExhaustion || b.rsiBullDiv) b.bullScore += 4;
   if(b.rsiBearishExhaustion || b.rsiBearDiv) b.bearScore += 4;
   if(b.adx >= InpADXTrendThreshold && b.plusDI > b.minusDI) b.bullScore += 4;
   if(b.adx >= InpADXTrendThreshold && b.minusDI > b.plusDI) b.bearScore += 4;

   b.notes = StringFormat("%s bias=%d struct=%d bull=%d bear=%d sweepL=%s sweepH=%s bosU=%s bosD=%s chochU=%s chochD=%s OBb=%s OBs=%s FVGb=%s FVGs=%s",
                          b.name,b.finalBias,b.structureBias,b.bullScore,b.bearScore,
                          b.sweepLow?"Y":"N", b.sweepHigh?"Y":"N", b.bosUp?"Y":"N", b.bosDown?"Y":"N",
                          b.chochUp?"Y":"N", b.chochDown?"Y":"N",
                          b.bullOB.valid?"Y":"N", b.bearOB.valid?"Y":"N", b.bullFVG.valid?"Y":"N", b.bearFVG.valid?"Y":"N");
   return true;
}

//====================================================================
// MARKET STATE / DECISION ENGINE
//====================================================================
bool CatastrophicSpike(TFBrain &m15)
{
   if(!InpUseSpikeProtection || m15.atr<=0) return false;
   double range = m15.high1 - m15.low1;
   double body = MathAbs(m15.close1 - m15.open1);
   return (range >= m15.atr*InpCatastrophicSpikeATR || body >= m15.atr*InpCatastrophicSpikeATR);
}

ENUM_BRAIN_STATE DetectMarketState(TFBrain &h4, TFBrain &h1, TFBrain &m15)
{
   if(CatastrophicSpike(m15)) return STATE_EXPANSION_SPIKE;

   bool htfBull = (h4.finalBias>0);
   bool htfBear = (h4.finalBias<0);
   bool h1Bull = (h1.finalBias>0);
   bool h1Bear = (h1.finalBias<0);

   bool warningBull = ((htfBear || h1Bear) && (m15.chochUp || m15.mssUp || (m15.sweepLow && m15.displacementUp)));
   bool warningBear = ((htfBull || h1Bull) && (m15.chochDown || m15.mssDown || (m15.sweepHigh && m15.displacementDown)));

   bool confirmedBull = warningBull && (m15.bosUp || h1.chochUp || h1.mssUp) && (m15.priceNearBullOB || m15.priceNearBullFVG || m15.inDiscount || h1.inDiscount);
   bool confirmedBear = warningBear && (m15.bosDown || h1.chochDown || h1.mssDown) && (m15.priceNearBearOB || m15.priceNearBearFVG || m15.inPremium || h1.inPremium);

   if(confirmedBull) return STATE_REVERSAL_CONFIRMED_BULL;
   if(confirmedBear) return STATE_REVERSAL_CONFIRMED_BEAR;
   if(warningBull) return STATE_REVERSAL_WARNING_BULL;
   if(warningBear) return STATE_REVERSAL_WARNING_BEAR;

   if(h4.rangeLike && h1.rangeLike) return STATE_RANGE;
   if(htfBull && h1Bull)
   {
      if(m15.finalBias<0 || m15.inDiscount) return STATE_PULLBACK_BULL;
      return STATE_TREND_BULL;
   }
   if(htfBear && h1Bear)
   {
      if(m15.finalBias>0 || m15.inPremium) return STATE_PULLBACK_BEAR;
      return STATE_TREND_BEAR;
   }
   if(h1.rangeLike || m15.rangeLike) return STATE_RANGE;
   return STATE_UNKNOWN;
}

bool IsBullishState(ENUM_BRAIN_STATE s)
{
   return (s==STATE_TREND_BULL || s==STATE_PULLBACK_BULL || s==STATE_REVERSAL_CONFIRMED_BULL);
}

bool IsBearishState(ENUM_BRAIN_STATE s)
{
   return (s==STATE_TREND_BEAR || s==STATE_PULLBACK_BEAR || s==STATE_REVERSAL_CONFIRMED_BEAR);
}

void SoftAdd(string &reason, string txt)
{
   if(reason=="") reason=txt;
   else reason = reason + " | " + txt;
}

void BuildDecision(TFBrain &h4, TFBrain &h1, TFBrain &m15, BrainDecision &d)
{
   d.decision=DECISION_WAIT;
   d.state=DetectMarketState(h4,h1,m15);
   d.buyScore=0; d.sellScore=0;
   d.blockBuy=false; d.blockSell=false;
   d.reason="";
   d.sessionName=SessionName(CurrentSession());
   d.setupKey="";
   d.learningBias=0;
   d.sl=0; d.tp=0; d.lot=NormalizeLot(FixedLotBySymbol()); d.entry=CurrentMid();

   // Hard integrity checks first.
   if(!h4.dataOK || !h1.dataOK || !m15.dataOK)
   {
      d.reason = "Data quality failed: " + h4.dataNote + ", " + h1.dataNote + ", " + m15.dataNote;
      d.state = STATE_NO_TRADE;
      return;
   }

   if(InpManualNewsPause)
   {
      d.reason = "Manual news pause is ON";
      d.state = STATE_NO_TRADE;
      return;
   }

   if(TimeInManualNewsWindow())
   {
      d.reason = "Manual GMT news window active";
      d.state = STATE_NO_TRADE;
      return;
   }

   if(d.state==STATE_EXPANSION_SPIKE)
   {
      d.reason = "Catastrophic spike/expansion detected on closed M15 candle";
      return;
   }

   // Weighted evidence: HTF context is important, but not absolute.
   d.buyScore += h4.bullScore/3;
   d.sellScore += h4.bearScore/3;
   d.buyScore += h1.bullScore/2;
   d.sellScore += h1.bearScore/2;
   d.buyScore += m15.bullScore;
   d.sellScore += m15.bearScore;

   // Market state score.
   if(d.state==STATE_TREND_BULL) { d.buyScore += 18; SoftAdd(d.reason,"Market trend bull"); }
   if(d.state==STATE_TREND_BEAR) { d.sellScore += 18; SoftAdd(d.reason,"Market trend bear"); }
   if(d.state==STATE_PULLBACK_BULL) { d.buyScore += 16; SoftAdd(d.reason,"Bull pullback context"); }
   if(d.state==STATE_PULLBACK_BEAR) { d.sellScore += 16; SoftAdd(d.reason,"Bear pullback context"); }
   if(d.state==STATE_REVERSAL_CONFIRMED_BULL) { d.buyScore += 24; d.blockSell=true; SoftAdd(d.reason,"Bull reversal confirmed blocks SELL"); }
   if(d.state==STATE_REVERSAL_CONFIRMED_BEAR) { d.sellScore += 24; d.blockBuy=true; SoftAdd(d.reason,"Bear reversal confirmed blocks BUY"); }

   // Reversal Warning logic: do not keep trading old direction, but do not reverse blindly unless score confirms.
   if(d.state==STATE_REVERSAL_WARNING_BULL)
   {
      d.blockSell=true;
      d.buyScore += 8;
      SoftAdd(d.reason,"M15 bullish reversal warning: SELL blocked, BUY needs confirmation");
   }
   if(d.state==STATE_REVERSAL_WARNING_BEAR)
   {
      d.blockBuy=true;
      d.sellScore += 8;
      SoftAdd(d.reason,"M15 bearish reversal warning: BUY blocked, SELL needs confirmation");
   }

   // ICT / SMC evidence detail.
   if(m15.sweepLow) SoftAdd(d.reason,"M15 sell-side sweep");
   if(m15.sweepHigh) SoftAdd(d.reason,"M15 buy-side sweep");
   if(m15.chochUp || m15.mssUp) SoftAdd(d.reason,"M15 bullish CHOCH/MSS");
   if(m15.chochDown || m15.mssDown) SoftAdd(d.reason,"M15 bearish CHOCH/MSS");
   if(m15.priceNearBullOB) SoftAdd(d.reason,"Retest bullish OB");
   if(m15.priceNearBearOB) SoftAdd(d.reason,"Retest bearish OB");
   if(m15.priceNearBullFVG) SoftAdd(d.reason,"Retest bullish FVG");
   if(m15.priceNearBearFVG) SoftAdd(d.reason,"Retest bearish FVG");

   // Direction permission.
   if(!InpAllowBuy) d.blockBuy=true;
   if(!InpAllowSell) d.blockSell=true;

   // Avoid selling lows / buying highs unless reversal is confirmed.
   if(m15.inDiscount && d.state!=STATE_REVERSAL_CONFIRMED_BEAR && d.state!=STATE_TREND_BEAR)
   {
      d.sellScore -= 8;
      SoftAdd(d.reason,"Discount area reduces low-quality SELL");
   }
   if(m15.inPremium && d.state!=STATE_REVERSAL_CONFIRMED_BULL && d.state!=STATE_TREND_BULL)
   {
      d.buyScore -= 8;
      SoftAdd(d.reason,"Premium area reduces low-quality BUY");
   }

   // Session context: boosts high-liquidity windows; by default never reduces scores.
   if(InpUseSessionContext)
   {
      ENUM_MARKET_SESSION sess = CurrentSession();
      if(sess==SESSION_LONDON || sess==SESSION_NEWYORK || sess==SESSION_OVERLAP)
      {
         d.buyScore += InpLondonNYBoost;
         d.sellScore += InpLondonNYBoost;
         SoftAdd(d.reason,"Session context: "+SessionName(sess)+" boost");
      }
      else if(sess==SESSION_LOW_LIQUIDITY && InpSessionCanReduceScore && InpLowLiquidityPenalty>0)
      {
         d.buyScore -= InpLowLiquidityPenalty;
         d.sellScore -= InpLowLiquidityPenalty;
         SoftAdd(d.reason,"Low-liquidity session penalty");
      }
   }

   // Setup key + learning layer. Boost-only by default; it does not choke trades.
   d.setupKey = SymbolClassName(SymbolClass()) + "_" + StateCode(d.state) + "_" + d.sessionName + "_" + (d.buyScore>=d.sellScore ? "B" : "S");
   d.learningBias = LearningBiasForKey(d.setupKey);
   if(d.learningBias!=0)
   {
      if(d.buyScore>=d.sellScore) d.buyScore += d.learningBias; else d.sellScore += d.learningBias;
      SoftAdd(d.reason,"Learning bias "+IntegerToString(d.learningBias)+" for "+d.setupKey);
   }

   // If score not strong, WAIT. No daily limit exists.
   int buyThreshold = (d.state==STATE_REVERSAL_CONFIRMED_BULL ? InpReversalMinScore : InpEntryMinScore);
   int sellThreshold = (d.state==STATE_REVERSAL_CONFIRMED_BEAR ? InpReversalMinScore : InpEntryMinScore);

   bool buyReady = (!d.blockBuy && d.buyScore >= buyThreshold && d.buyScore > d.sellScore+7);
   bool sellReady = (!d.blockSell && d.sellScore >= sellThreshold && d.sellScore > d.buyScore+7);

   if(buyReady) d.decision = DECISION_BUY;
   else if(sellReady) d.decision = DECISION_SELL;
   else d.decision = DECISION_WAIT;

   if(d.decision==DECISION_WAIT)
   {
      if(d.reason=="") d.reason="Scores not strong/clean enough";
      return;
   }

   // Compute SL/TP only after decision.
   double entry = (d.decision==DECISION_BUY ? CurrentAsk() : CurrentBid());
   d.entry=entry;
   d.sl = 0;
   d.tp = 0;

   double atr = MathMax(m15.atr, PointValue()*50);
   if(d.decision==DECISION_BUY)
   {
      double baseSL = 0;
      if(m15.swings.validLow) baseSL = m15.swings.lastLow;
      if(m15.bullOB.valid) baseSL = (baseSL==0 ? m15.bullOB.low : MathMin(baseSL,m15.bullOB.low));
      if(baseSL<=0 || baseSL>=entry) baseSL = entry - atr*1.4;
      d.sl = NormalizePrice(baseSL - atr*InpSL_ATR_Buffer);

      double target = 0;
      if(m15.swings.validHigh && m15.swings.lastHigh>entry) target=m15.swings.lastHigh;
      if(h1.swings.validHigh && h1.swings.lastHigh>entry) target=MathMax(target,h1.swings.lastHigh);
      double rrTP = entry + (entry-d.sl)*InpDefaultRR;
      d.tp = NormalizePrice(MathMax(target,rrTP));
      SoftAdd(d.reason,"SL under structure/OB with ATR buffer; TP to liquidity/RR");
   }
   if(d.decision==DECISION_SELL)
   {
      double baseSL = 0;
      if(m15.swings.validHigh) baseSL = m15.swings.lastHigh;
      if(m15.bearOB.valid) baseSL = (baseSL==0 ? m15.bearOB.high : MathMax(baseSL,m15.bearOB.high));
      if(baseSL<=0 || baseSL<=entry) baseSL = entry + atr*1.4;
      d.sl = NormalizePrice(baseSL + atr*InpSL_ATR_Buffer);

      double target = 0;
      if(m15.swings.validLow && m15.swings.lastLow<entry) target=m15.swings.lastLow;
      if(h1.swings.validLow && h1.swings.lastLow<entry) target=(target==0 ? h1.swings.lastLow : MathMin(target,h1.swings.lastLow));
      double rrTP = entry - (d.sl-entry)*InpDefaultRR;
      if(target==0) target=rrTP;
      d.tp = NormalizePrice(MathMin(target,rrTP));
      SoftAdd(d.reason,"SL above structure/OB with ATR buffer; TP to liquidity/RR");
   }
}

//====================================================================
// SAFETY / EXECUTION
//====================================================================
bool TradingAllowedNow(string &why)
{
   why="OK";
   if(!InpRequireTradingAllowed) return true;
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
   {
      why="Terminal trading not allowed";
      return false;
   }
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
   {
      why="EA trading not allowed";
      return false;
   }
   long mode = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE);
   if(mode==SYMBOL_TRADE_MODE_DISABLED)
   {
      why="Symbol trade mode disabled";
      return false;
   }
   return true;
}

bool SpreadOK(TFBrain &m15, string &why)
{
   why="OK";
   if(!InpUseSpreadGuard) return true;
   double spread = CurrentAsk()-CurrentBid();
   if(m15.atr<=0) return true;
   double pct = (spread/m15.atr)*100.0;
   if(pct > InpMaxSpreadATRPercent)
   {
      why = StringFormat("Abnormal spread %.2f%% of M15 ATR",pct);
      return false;
   }
   return true;
}

bool StopsOK(ENUM_BRAIN_DECISION dir, double entry, double sl, double tp, string &why)
{
   why="OK";
   if(dir!=DECISION_BUY && dir!=DECISION_SELL) return false;
   double point = PointValue();
   int stops = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   int freeze = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double minDist = MathMax(stops,freeze) * point;
   if(minDist <= 0) minDist = point*5;

   if(sl<=0 || tp<=0)
   {
      why="SL or TP missing";
      return false;
   }
   if(dir==DECISION_BUY)
   {
      if(sl>=entry || tp<=entry) { why="Invalid BUY SL/TP geometry"; return false; }
      if((entry-sl)<minDist || (tp-entry)<minDist) { why="BUY SL/TP too close to broker stop/freeze level"; return false; }
   }
   if(dir==DECISION_SELL)
   {
      if(sl<=entry || tp>=entry) { why="Invalid SELL SL/TP geometry"; return false; }
      if((sl-entry)<minDist || (entry-tp)<minDist) { why="SELL SL/TP too close to broker stop/freeze level"; return false; }
   }
   return true;
}

bool MarginOK(ENUM_BRAIN_DECISION dir, double lot, string &why)
{
   why="OK";
   ENUM_ORDER_TYPE type = (dir==DECISION_BUY ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
   double price = (dir==DECISION_BUY ? CurrentAsk() : CurrentBid());
   double margin=0;
   if(!OrderCalcMargin(type,_Symbol,lot,price,margin))
   {
      why="OrderCalcMargin failed";
      return false;
   }
   double free = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(margin > free*0.92)
   {
      why=StringFormat("Not enough free margin. Need %.2f free %.2f",margin,free);
      return false;
   }
   return true;
}

int CountPositions(int direction)
{
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      if(direction==1 && type==POSITION_TYPE_BUY) count++;
      if(direction==-1 && type==POSITION_TYPE_SELL) count++;
      if(direction==0) count++;
   }
   return count;
}

double AggregateProfitDirection(int direction)
{
   double p=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      if(direction==1 && type==POSITION_TYPE_BUY) p += PositionGetDouble(POSITION_PROFIT);
      if(direction==-1 && type==POSITION_TYPE_SELL) p += PositionGetDouble(POSITION_PROFIT);
   }
   return p;
}

bool SameDirectionCanAdd(ENUM_BRAIN_DECISION dir, TFBrain &m15, BrainDecision &d, string &why)
{
   why="OK";
   if(!InpAllowSmartAddOns) { why="Smart add-ons OFF"; return false; }
   int direction = (dir==DECISION_BUY ? 1 : -1);
   int existing = CountPositions(direction);
   if(existing<=0) return true;
   if(InpMaxAddOnsPerDirection>0 && existing >= InpMaxAddOnsPerDirection+1)
   {
      why="Max add-ons reached";
      return false;
   }
   if((dir==DECISION_BUY && d.buyScore<InpAddOnMinScore) || (dir==DECISION_SELL && d.sellScore<InpAddOnMinScore))
   {
      why="Add-on score not strong enough";
      return false;
   }

   // Require at least one same-direction position to be protected/profitable by price distance.
   bool ok=false;
   double atr = MathMax(m15.atr, PointValue()*50);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double open=PositionGetDouble(POSITION_PRICE_OPEN);
      double price = (type==POSITION_TYPE_BUY ? CurrentBid() : CurrentAsk());
      if(direction==1 && type==POSITION_TYPE_BUY && (price-open)>=atr*InpAddOnMinProfitATR) ok=true;
      if(direction==-1 && type==POSITION_TYPE_SELL && (open-price)>=atr*InpAddOnMinProfitATR) ok=true;
   }
   if(!ok)
   {
      why="Existing same-direction trade is not profitable enough for smart add-on";
      return false;
   }
   return true;
}

void CloseOppositeIfConfirmed(BrainDecision &d)
{
   if(!InpCloseOnConfirmedReversal) return;
   if(d.decision!=DECISION_BUY && d.decision!=DECISION_SELL) return;
   bool confirmed = (d.state==STATE_REVERSAL_CONFIRMED_BULL || d.state==STATE_REVERSAL_CONFIRMED_BEAR);
   if(!confirmed) return;

   long closeType = (d.decision==DECISION_BUY ? POSITION_TYPE_SELL : POSITION_TYPE_BUY);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      if(PositionGetInteger(POSITION_TYPE)==closeType)
      {
         VPrint("Closing opposite position "+IntegerToString((long)ticket)+" due confirmed reversal: "+StateToString(d.state));
         trade.PositionClose(ticket);
      }
   }
}

bool ExecuteDecision(BrainDecision &d, TFBrain &m15)
{
   if(d.decision!=DECISION_BUY && d.decision!=DECISION_SELL) return false;

   string why;
   if(!TradingAllowedNow(why)) { VPrint("Blocked safety: "+why); return false; }
   if(!SpreadOK(m15,why)) { VPrint("Blocked safety: "+why); return false; }

   d.lot = NormalizeLot(FixedLotBySymbol());
   d.entry = (d.decision==DECISION_BUY ? CurrentAsk() : CurrentBid());
   d.sl=NormalizePrice(d.sl);
   d.tp=NormalizePrice(d.tp);

   if(InpBlockIfOrderWouldHaveNoSLTP && !StopsOK(d.decision,d.entry,d.sl,d.tp,why))
   {
      VPrint("Blocked safety: "+why);
      return false;
   }
   if(!MarginOK(d.decision,d.lot,why))
   {
      VPrint("Blocked safety: "+why);
      return false;
   }

   if(!SameDirectionCanAdd(d.decision,m15,d,why))
   {
      VPrint("Add-on blocked: "+why);
      return false;
   }

   CloseOppositeIfConfirmed(d);

   string keyShort = d.setupKey;
   if(StringLen(keyShort)>18) keyShort = StringSubstr(keyShort,0,18);
   string comment = StringFormat("MB1F %s K:%s",DecisionToString(d.decision),keyShort);
   bool ok=false;
   if(d.decision==DECISION_BUY)
      ok = trade.Buy(d.lot,_Symbol,0.0,d.sl,d.tp,comment);
   else if(d.decision==DECISION_SELL)
      ok = trade.Sell(d.lot,_Symbol,0.0,d.sl,d.tp,comment);

   if(ok)
   {
      ulong deal=trade.ResultDeal();
      if(deal>0 && HistoryDealSelect(deal))
      {
         long posid=(long)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
         StorePositionKey(posid,d.setupKey);
      }
      VPrint(StringFormat("ORDER SENT %s | Lot=%.2f | Entry=%.5f | SL=%.5f | TP=%.5f | BuyScore=%d | SellScore=%d | State=%s | Session=%s | Key=%s | Reason=%s",
                          DecisionToString(d.decision),d.lot,d.entry,d.sl,d.tp,d.buyScore,d.sellScore,StateToString(d.state),d.sessionName,d.setupKey,d.reason));
      return true;
   }
   VPrint(StringFormat("ORDER FAILED %s | retcode=%d | %s",DecisionToString(d.decision),(int)trade.ResultRetcode(),trade.ResultRetcodeDescription()));
   return false;
}

//====================================================================
// POSITION MANAGEMENT: BE / PROFIT LOCK / TRAILING / TP RUNNER
//====================================================================
double PositionInitialRiskDistance(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return 0;
   double open=PositionGetDouble(POSITION_PRICE_OPEN);
   double sl=PositionGetDouble(POSITION_SL);
   if(sl<=0) return 0;
   return MathAbs(open-sl);
}

bool PositionProtected(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return false;
   long type = PositionGetInteger(POSITION_TYPE);
   double open=PositionGetDouble(POSITION_PRICE_OPEN);
   double sl=PositionGetDouble(POSITION_SL);
   if(type==POSITION_TYPE_BUY && sl>=open) return true;
   if(type==POSITION_TYPE_SELL && sl<=open && sl>0) return true;
   return false;
}

void ManagePositionTicket(ulong ticket, TFBrain &h1, TFBrain &m15)
{
   if(!PositionSelectByTicket(ticket)) return;
   if(PositionGetString(POSITION_SYMBOL)!=_Symbol) return;
   if((long)PositionGetInteger(POSITION_MAGIC)!=InpMagic) return;

   long type = PositionGetInteger(POSITION_TYPE);
   double open=PositionGetDouble(POSITION_PRICE_OPEN);
   double sl=PositionGetDouble(POSITION_SL);
   double tp=PositionGetDouble(POSITION_TP);
   double price = (type==POSITION_TYPE_BUY ? CurrentBid() : CurrentAsk());
   double risk = MathAbs(open-sl);
   if(risk<=PointValue()*5) return;
   double profitDist = (type==POSITION_TYPE_BUY ? price-open : open-price);
   double rNow = profitDist / risk;
   double atr = MathMax(m15.atr, PointValue()*50);
   double newSL = sl;
   double newTP = tp;
   bool modify=false;

   // BreakEven
   if(InpUseBreakEven && rNow >= InpBreakEvenAtR)
   {
      if(type==POSITION_TYPE_BUY)
      {
         double be = NormalizePrice(open + atr*InpBreakEvenPlusATR);
         if(sl < be) { newSL=be; modify=true; }
      }
      else
      {
         double be = NormalizePrice(open - atr*InpBreakEvenPlusATR);
         if(sl==0 || sl > be) { newSL=be; modify=true; }
      }
   }

   // Profit Lock
   if(InpUseProfitLock && rNow >= InpProfitLockAtR)
   {
      if(type==POSITION_TYPE_BUY)
      {
         double lock = NormalizePrice(open + risk*InpProfitLockR);
         if(newSL < lock) { newSL=lock; modify=true; }
      }
      else
      {
         double lock = NormalizePrice(open - risk*InpProfitLockR);
         if(newSL==0 || newSL > lock) { newSL=lock; modify=true; }
      }
   }

   // ATR trailing after protected/profitable
   if(InpUseATRTrailing && rNow >= InpTrailStartR)
   {
      if(type==POSITION_TYPE_BUY)
      {
         double tr = NormalizePrice(price - atr*InpTrailATR);
         if(tr > newSL && tr < price) { newSL=tr; modify=true; }
      }
      else
      {
         double tr = NormalizePrice(price + atr*InpTrailATR);
         if((newSL==0 || tr < newSL) && tr > price) { newSL=tr; modify=true; }
      }
   }

   // TP Runner: only after SL protected.
   bool protectedNow=false;
   if(type==POSITION_TYPE_BUY && newSL>=open) protectedNow=true;
   if(type==POSITION_TYPE_SELL && newSL<=open && newSL>0) protectedNow=true;

   if(InpUseTPRunner && protectedNow && tp>0)
   {
      double distToTP = MathAbs(tp-price);
      double total = MathAbs(tp-open);
      if(total>0)
      {
         double nearPct = distToTP/total*100.0;
         bool continuation = false;
         if(type==POSITION_TYPE_BUY && (m15.finalBias>0 || h1.finalBias>0) && !m15.chochDown && !m15.mssDown) continuation=true;
         if(type==POSITION_TYPE_SELL && (m15.finalBias<0 || h1.finalBias<0) && !m15.chochUp && !m15.mssUp) continuation=true;
         if(nearPct <= InpRunnerNearTPPercent && continuation)
         {
            if(type==POSITION_TYPE_BUY)
            {
               double ext = NormalizePrice(tp + atr*InpRunnerExtendATR);
               if(ext>newTP) { newTP=ext; modify=true; }
            }
            else
            {
               double ext = NormalizePrice(tp - atr*InpRunnerExtendATR);
               if(newTP==0 || ext<newTP) { newTP=ext; modify=true; }
            }
         }
      }
   }

   // Reversal protection for open positions: tighten/exit if confirmed opposite structure.
   if(type==POSITION_TYPE_BUY && (m15.chochDown || m15.mssDown) && m15.displacementDown)
   {
      double protective = NormalizePrice(price - atr*0.35);
      if(protective>newSL && protective<price) { newSL=protective; modify=true; }
      VPrint("BUY position "+IntegerToString((long)ticket)+" reversal warning: protective SL tighten");
   }
   if(type==POSITION_TYPE_SELL && (m15.chochUp || m15.mssUp) && m15.displacementUp)
   {
      double protective = NormalizePrice(price + atr*0.35);
      if((newSL==0 || protective<newSL) && protective>price) { newSL=protective; modify=true; }
      VPrint("SELL position "+IntegerToString((long)ticket)+" reversal warning: protective SL tighten");
   }

   if(modify)
   {
      newSL=NormalizePrice(newSL);
      newTP=NormalizePrice(newTP);
      string why;
      ENUM_BRAIN_DECISION dir = (type==POSITION_TYPE_BUY ? DECISION_BUY : DECISION_SELL);
      if(StopsOK(dir,price,newSL,newTP,why))
      {
         if(trade.PositionModify(ticket,newSL,newTP))
            VPrint("POSITION MODIFIED "+IntegerToString((long)ticket)+StringFormat(" | SL %.5f -> %.5f | TP %.5f -> %.5f | R=%.2f",sl,newSL,tp,newTP,rNow));
         else
            VPrint("POSITION MODIFY FAILED "+IntegerToString((long)ticket)+" | "+trade.ResultRetcodeDescription());
      }
   }
}

void ManageOpenPositions(TFBrain &h1, TFBrain &m15)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      ManagePositionTicket(ticket,h1,m15);
   }
}

//====================================================================
// LOGGING
//====================================================================
void EnsureCSVHeader()
{
   if(!InpWriteCSVLog) return;
   int h = FileOpen(InpCSVFileName, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   if(FileSize(h)==0)
   {
      FileWrite(h,"time","symbol","class","session","setupKey","learningBias","state","decision","buyScore","sellScore","lot","entry","sl","tp","reason");
   }
   FileClose(h);
}

void LogCSV(BrainDecision &d)
{
   if(!InpWriteCSVLog) return;
   int h = FileOpen(InpCSVFileName, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   FileSeek(h,0,SEEK_END);
   FileWrite(h,TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),_Symbol,SymbolClassName(SymbolClass()),d.sessionName,d.setupKey,d.learningBias,StateToString(d.state),DecisionToString(d.decision),
             d.buyScore,d.sellScore,DoubleToString(d.lot,2),DoubleToString(d.entry,_Digits),DoubleToString(d.sl,_Digits),DoubleToString(d.tp,_Digits),d.reason);
   FileClose(h);
}

void ChartStatus(TFBrain &h4, TFBrain &h1, TFBrain &m15, BrainDecision &d)
{
   string txt = InpBotName + "\n";
   txt += "Symbol: " + _Symbol + " | Class: " + SymbolClassName(SymbolClass()) + " | Chart-symbol-only: YES\n";
   txt += "State: " + StateToString(d.state) + " | Decision: " + DecisionToString(d.decision) + " | B/S: " + IntegerToString(d.buyScore) + "/" + IntegerToString(d.sellScore) + "\n";
   txt += "Session: " + d.sessionName + " | Key: " + d.setupKey + " | LearningBias: " + IntegerToString(d.learningBias) + "\n";
   txt += h4.notes + "\n" + h1.notes + "\n" + m15.notes + "\n";
   txt += "Reason: " + d.reason + "\n";
   txt += "Fixed lot: " + DoubleToString(d.lot,2) + " | No MaxTradesPerDay | RiskPercent OFF";
   Comment(txt);
}

//====================================================================
// INIT / TICK
//====================================================================
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(30);
   EnsureCSVHeader();
   LoadLearningStats();
   LoadPositionMap();

   VPrint("INIT OK. This EA trades ONLY the chart symbol using _Symbol. Attach to oil chart if you want oil. No symbol list scanning.");
   VPrint(StringFormat("Growth Mode=%s | UseRiskPercent=%s | ForexLot=%.2f | GoldLot=%.2f | SilverLot=%.2f | OilLot=%.2f | No MaxTradesPerDay",
                       InpGrowthMode?"ON":"OFF", InpUseRiskPercent?"ON":"OFF", InpForexLot, InpGoldLot, InpSilverLot, InpOilLot));
   VPrint("Backtest integrity: closed candles only, H4/H1/M15 synchronized-data checks enabled, no lookahead logic.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   Comment("");
   SaveLearningStats();
   SavePositionMap();
   VPrint("DEINIT reason="+IntegerToString(reason));
}

void OnTick()
{
   // Build brains every tick for management, execute only on new M15 bar.
   TFBrain h4,h1,m15;
   bool ok4 = BuildTFBrain(InpHTF, TFToString(InpHTF), h4);
   bool ok1 = BuildTFBrain(InpMTF, TFToString(InpMTF), h1);
   bool ok15= BuildTFBrain(InpETF, TFToString(InpETF), m15);

   if(ok1 && ok15)
      ManageOpenPositions(h1,m15);

   bool newbar = IsNewBar(InpETF);
   if(!newbar) return;

   BrainDecision d;
   BuildDecision(h4,h1,m15,d);
   ChartStatus(h4,h1,m15,d);
   LogCSV(d);

   string line = StringFormat("Decision=%s | State=%s | Session=%s | Key=%s | B=%d S=%d | %s",DecisionToString(d.decision),StateToString(d.state),d.sessionName,d.setupKey,d.buyScore,d.sellScore,d.reason);
   if(InpPrintEveryNewBar || d.decision!=DECISION_WAIT) VPrint(line);

   if(d.decision==DECISION_BUY || d.decision==DECISION_SELL)
      ExecuteDecision(d,m15);
}

//====================================================================
// TRADE TRANSACTION LEARNING
//====================================================================
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(!InpUseLearningLayer) return;
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return;
   ulong deal = trans.deal;
   if(deal==0) return;
   if(!HistoryDealSelect(deal)) return;
   string sym = HistoryDealGetString(deal,DEAL_SYMBOL);
   if(sym!=_Symbol) return;
   long magic = (long)HistoryDealGetInteger(deal,DEAL_MAGIC);
   if(magic!=InpMagic) return;
   long entry = HistoryDealGetInteger(deal,DEAL_ENTRY);
   if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_OUT_BY) return;
   long posid = (long)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
   double profit = HistoryDealGetDouble(deal,DEAL_PROFIT) + HistoryDealGetDouble(deal,DEAL_SWAP) + HistoryDealGetDouble(deal,DEAL_COMMISSION);
   string key = KeyForPosition(posid);
   bool win = (profit>=0.0);
   AddOrUpdateLearning(key,win,profit);
   SaveLearningStats();
   RemovePositionKey(posid);
   VPrint(StringFormat("LEARNING UPDATE | PositionID=%d | Key=%s | Profit=%.2f | Result=%s",posid,key,profit,win?"WIN":"LOSS"));
}
//+------------------------------------------------------------------+
