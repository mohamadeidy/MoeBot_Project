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


enum ENUM_SETUP_TYPE
{
   SETUP_NO_TRADE = 0,
   SETUP_TREND_CONTINUATION = 1,
   SETUP_PULLBACK_CONTINUATION = 2,
   SETUP_BREAKOUT_RETEST = 3,
   SETUP_REVERSAL_AFTER_SWEEP = 4,
   SETUP_RANGE_EDGE_SWEEP = 5
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


// Entry Brain v2 windows: map context is not a direct entry signal.
input int    InpMarketMapLookback = 100;
input int    InpActiveZoneLookback = 40;
input int    InpEventMemoryBars = 12;
input int    InpEntryTriggerBars = 3;
input int    InpCandidateSideSeparation = 7;

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
input string InpCloseAuditFileName = "MoeBot_Brain_v1_Close_Audit.csv";
input bool   InpPrintEveryNewBar = true;
input bool   InpRunFailedXAUUSDDebugHarness = false; // Optional one-shot regression/audit print for the failed XAUUSD class.

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
   bool hh;
   bool hl;
   bool lh;
   bool ll;
   string pattern;
};

struct Zone
{
   bool valid;
   double low;
   double high;
   double refinedLow;
   double refinedHigh;
   double bodyLow;
   double bodyHigh;
   double sourceOpen;
   double sourceHigh;
   double sourceLow;
   double sourceClose;
   double bodySize;
   double upperWick;
   double lowerWick;
   double wickBodyRatio;
   double displacementScore;
   double invalidationLevel;
   double targetLevel;
   double obstacleLevel;
   datetime time;
   datetime displacementTime;
   int direction; // 1 bullish zone, -1 bearish zone
   int qualityScore;
   int tapCount;
   string sourceEventID;
   string displacementLink;
   string targetRelation;
   bool hasStructureLink;
   bool hasSweepLink;
   bool hasDisplacement;
   bool fresh;
   bool mitigated;
   bool invalidated;
   bool tooWide;
   bool noisyWick;
   string wickClass;
   string structureLink;
   string freshness;
   string blockReason;
   string audit;
   string name;
};

struct StructureEvent
{
   bool valid;
   int direction;
   string eventType;
   string eventID;
   double level;
   double brokenLevel;
   datetime eventTime;
   double displacementScore;
   double closeBackQuality;
   string audit;
};

struct EntryModelResult
{
   int direction;
   bool hardBlock;
   bool storyComplete;
   bool zoneOK;
   bool liquidityOK;
   bool structureOK;
   bool displacementOK;
   bool retestOK;
   bool rrOK;
   bool locationOK;
   bool lateEntryOK;
   double entry;
   double sl;
   double tp;
   double rr;
   double targetLevel;
   double obstacleLevel;
   string blockReasons;
   string zoneResult;
   string liquidityResult;
   string structureResult;
   string displacementResult;
   string retestResult;
   string rrTargetResult;
   string lateEntryResult;
   string verdict;
   string audit;
};

struct EventMemoryRecord
{
   bool valid;
   string eventType;
   int direction;
   double level;
   datetime eventTime;
   int candleIndex;
   int age;
   ENUM_TIMEFRAMES sourceTF;
   double invalidationLevel;
   bool retested;
   bool invalidated;
   int qualityScore;
   string audit;
};

struct MarketMap
{
   bool valid;
   double majorHigh;
   double majorLow;
   double internalHigh;
   double internalLow;
   double rangeHigh;
   double rangeLow;
   double rangeMid;
   bool rangeDetected;
   bool inPremium;
   bool inDiscount;
   double buySideLiquidity;
   double sellSideLiquidity;
   double supportLevel;
   double resistanceLevel;
   string audit;
};


struct RejectionZone
{
   bool valid;
   int direction;
   double low;
   double high;
   double invalidationLevel;
   int strength;
   int age;
   int touches;
   ENUM_TIMEFRAMES tf;
   datetime sourceTime;
   bool invalidated;
   string zoneState;
   string audit;
};

struct TradeQualityResult
{
   int qualityScore;
   string grade;
   string decision;
   string rejectionZoneContext;
   bool rejectionZoneEntryUsed;
   bool rejectionZoneAgainstTrade;
   string qualityReasons;
   string redFlags;
   string confirmations;
};

struct SetupCandidate
{
   bool valid;
   bool mandatoryPass;
   bool hardBlock;
   ENUM_SETUP_TYPE setupType;
   int direction;
   int score;
   string hardBlockReason;
   string softMissingReasons;
   double entry;
   double sl;
   double tp;
   double rr;
   double invalidationLevel;
   double targetLevel;
   string targetSource;
   string linkedEvents;
   string eventAges;
   string retestType;
   string triggerType;
   string entryLocationType;
   string lateEntryStatus;
   int locationQuality;
   int targetQuality;
   bool rejectionZoneEntryUsed;
   bool rejectionZoneAgainstTrade;
   string rejectionZoneContext;
   string audit;
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
   bool priceInBullOBRefined;
   bool priceInBearOBRefined;
   RejectionZone bullRejectionZone;
   RejectionZone bearRejectionZone;

   bool wyckoffSpring;
   bool wyckoffUpthrust;
   bool accumulationHint;
   bool distributionHint;

   bool rsiBullishExhaustion;
   bool rsiBearishExhaustion;
   bool rsiBullDiv;
   bool rsiBearDiv;

   double majorHigh;
   double majorLow;
   double internalHigh;
   double internalLow;
   double equalHighLevel;
   double equalLowLevel;
   double buySideLiquidity;
   double sellSideLiquidity;
   double sweepHighLevel;
   double sweepLowLevel;
   datetime sweepHighTime;
   datetime sweepLowTime;
   double sweepHighQuality;
   double sweepLowQuality;
   double bosBrokenLevel;
   double chochBrokenLevel;
   double mssBrokenLevel;
   string eventAudit;
   string liquidityAudit;
   StructureEvent lastBullEvent;
   StructureEvent lastBearEvent;

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
   string waitReason;
   string audit;
   string obAudit;
   string reversalAudit;
   string entryModel;
   string sessionName;
   string setupKey;
   int learningBias;
   double sl;
   double tp;
   double lot;
   double entry;
   double bid;
   double ask;
   double spread;
   string decisionTF;
   string buyEntryAudit;
   string sellEntryAudit;
   string selectedSetupType;
   string candidateRanking;
   string candidateAudit;
   string qualityGrade;
   int qualityScore;
   string qualityDecision;
   string rejectionZoneContext;
   string rejectionZoneEntryUsed;
   string rejectionZoneAgainstTrade;
   string qualityReasons;
   string redFlags;
   string confirmations;
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
   string entryReason;
   string managementActions;
   string closeReasonOverride;
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
   FileWrite(h,"positionId","setupKey","entryReason","managementActions","closeReasonOverride");
   for(int i=0;i<ArraySize(g_posKeys);i++)
      FileWrite(h,IntegerToString(g_posKeys[i].positionId),g_posKeys[i].key,g_posKeys[i].entryReason,g_posKeys[i].managementActions,g_posKeys[i].closeReasonOverride);
   FileClose(h);
}

void LoadPositionMap()
{
   ArrayResize(g_posKeys,0);
   int h = FileOpen(InpPositionMapFileName, FILE_READ|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   if(!FileIsEnding(h))
   {
      FileReadString(h); FileReadString(h);
      if(!FileIsLineEnding(h)) FileReadString(h);
      if(!FileIsLineEnding(h)) FileReadString(h);
      if(!FileIsLineEnding(h)) FileReadString(h);
   }
   while(!FileIsEnding(h))
   {
      string sid = FileReadString(h);
      if(sid=="") break;
      string key = FileReadString(h);
      string entryReason = "";
      string actions = "";
      string closeOverride = "";
      if(!FileIsLineEnding(h)) entryReason = FileReadString(h);
      if(!FileIsLineEnding(h)) actions = FileReadString(h);
      if(!FileIsLineEnding(h)) closeOverride = FileReadString(h);
      int n=ArraySize(g_posKeys);
      ArrayResize(g_posKeys,n+1);
      g_posKeys[n].positionId=(long)StringToInteger(sid);
      g_posKeys[n].key=key;
      g_posKeys[n].entryReason=entryReason;
      g_posKeys[n].managementActions=actions;
      g_posKeys[n].closeReasonOverride=closeOverride;
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
      g_posKeys[n].entryReason="";
      g_posKeys[n].managementActions="";
      g_posKeys[n].closeReasonOverride="";
   }
   else g_posKeys[idx].key=key;
   SavePositionMap();
}

void StorePositionContext(long posid, string key, string entryReason)
{
   if(posid<=0) return;
   StorePositionKey(posid,key);
   int idx=FindPositionKeyIndex(posid);
   if(idx>=0)
   {
      g_posKeys[idx].entryReason=entryReason;
      SavePositionMap();
   }
}

string KeyForPosition(long posid)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx>=0) return g_posKeys[idx].key;
   return "UNKNOWN";
}

string EntryReasonForPosition(long posid)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx>=0) return g_posKeys[idx].entryReason;
   return "";
}

void AppendManagementAction(long posid, string action)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx<0) return;
   if(g_posKeys[idx].managementActions=="") g_posKeys[idx].managementActions=action;
   else g_posKeys[idx].managementActions += " || " + action;
   SavePositionMap();
}

string ManagementActionsForPosition(long posid)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx>=0) return g_posKeys[idx].managementActions;
   return "";
}

void SetCloseReasonOverride(long posid, string reason)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx<0) return;
   g_posKeys[idx].closeReasonOverride=reason;
   SavePositionMap();
}

string CloseReasonOverrideForPosition(long posid)
{
   int idx=FindPositionKeyIndex(posid);
   if(idx>=0) return g_posKeys[idx].closeReasonOverride;
   return "";
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
   if(StringFind(s,"NAS")>=0 || StringFind(s,"US100")>=0 || StringFind(s,"NASDAQ")>=0 || StringFind(s,"USTEC")>=0 || StringFind(s,"NDX")>=0 || StringFind(s,"NDQ")>=0 || StringFind(s,"TECH100")>=0 || StringFind(s,"US30")>=0 || StringFind(s,"DJ")>=0 || StringFind(s,"SPX")>=0 || StringFind(s,"US500")>=0 || StringFind(s,"GER")>=0 || StringFind(s,"DAX")>=0) return SYMBOL_CLASS_INDEX;

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
   s.hh=false; s.hl=false; s.lh=false; s.ll=false; s.pattern="UNKNOWN";
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
   s.hh = (s.lastHigh > s.prevHigh);
   s.hl = (s.lastLow  > s.prevLow);
   s.lh = (s.lastHigh < s.prevHigh);
   s.ll = (s.lastLow  < s.prevLow);
   if(s.hh && s.hl) { s.pattern="HH/HL"; return 1; }
   if(s.lh && s.ll) { s.pattern="LH/LL"; return -1; }
   if(s.hh && s.ll) s.pattern="EXPANDING";
   else if(s.lh && s.hl) s.pattern="COMPRESSING";
   else s.pattern="MIXED";
   return 0;
}

void InitZone(Zone &z)
{
   z.valid=false;
   z.low=0; z.high=0; z.refinedLow=0; z.refinedHigh=0; z.bodyLow=0; z.bodyHigh=0;
   z.sourceOpen=0; z.sourceHigh=0; z.sourceLow=0; z.sourceClose=0;
   z.bodySize=0; z.upperWick=0; z.lowerWick=0; z.wickBodyRatio=0; z.displacementScore=0; z.invalidationLevel=0;
   z.targetLevel=0; z.obstacleLevel=0;
   z.time=0; z.displacementTime=0; z.direction=0; z.qualityScore=0; z.tapCount=0;
   z.sourceEventID=""; z.displacementLink=""; z.targetRelation="";
   z.hasStructureLink=false; z.hasSweepLink=false; z.hasDisplacement=false;
   z.fresh=false; z.mitigated=false; z.invalidated=false; z.tooWide=false; z.noisyWick=false;
   z.wickClass="NONE"; z.structureLink="NONE"; z.freshness="NONE"; z.blockReason=""; z.audit=""; z.name="";
}

void InitStructureEvent(StructureEvent &e)
{
   e.valid=false; e.direction=0; e.eventType="NONE"; e.eventID="";
   e.level=0; e.brokenLevel=0; e.eventTime=0; e.displacementScore=0; e.closeBackQuality=0; e.audit="";
}

void InitEntryModelResult(EntryModelResult &r, int direction)
{
   r.direction=direction;
   r.hardBlock=false; r.storyComplete=false; r.zoneOK=false; r.liquidityOK=false; r.structureOK=false;
   r.displacementOK=false; r.retestOK=false; r.rrOK=false; r.locationOK=false; r.lateEntryOK=false;
   r.entry=0; r.sl=0; r.tp=0; r.rr=0; r.targetLevel=0; r.obstacleLevel=0;
   r.blockReasons=""; r.zoneResult=""; r.liquidityResult=""; r.structureResult="";
   r.displacementResult=""; r.retestResult=""; r.rrTargetResult=""; r.lateEntryResult="";
   r.verdict="WAIT"; r.audit="";
}

bool PriceNearZone(double price, Zone &z, double atr, double toleranceATR)
{
   if(!z.valid || atr<=0) return false;
   if(price >= z.low && price <= z.high) return true;
   double tol = atr * toleranceATR;
   if(MathAbs(price - z.low) <= tol || MathAbs(price - z.high) <= tol) return true;
   return false;
}

bool PriceInRefinedZone(double price, Zone &z, double atr)
{
   if(!z.valid) return false;
   double lo = (z.refinedLow>0 ? z.refinedLow : z.low);
   double hi = (z.refinedHigh>0 ? z.refinedHigh : z.high);
   double tol = MathMax(atr*0.08, PointValue()*10);
   return (price >= lo-tol && price <= hi+tol);
}

void InitRejectionZone(RejectionZone &z)
{
   z.valid=false; z.direction=0; z.low=0; z.high=0; z.invalidationLevel=0; z.strength=0; z.age=999; z.touches=0;
   z.tf=InpETF; z.sourceTime=0; z.invalidated=false; z.zoneState="EMPTY"; z.audit="";
}

void FinalizeRejectionAudit(RejectionZone &z)
{
   z.audit=StringFormat("RZ tf=%s dir=%d valid=%s state=%s low=%.5f high=%.5f inv=%.5f strength=%d age=%d touches=%d invalidated=%s",
                        TFToString(z.tf),z.direction,BoolYN(z.valid),z.zoneState,z.low,z.high,z.invalidationLevel,z.strength,z.age,z.touches,BoolYN(z.invalidated));
}

bool PriceNearRejectionZone(double price, RejectionZone &z, double atr, double tolATR)
{
   if(!z.valid || z.invalidated) return false;
   double tol=MathMax(atr*tolATR,PointValue()*12);
   return (price>=z.low-tol && price<=z.high+tol);
}

void DetectRejectionZones(ENUM_TIMEFRAMES tf, TFBrain &b)
{
   InitRejectionZone(b.bullRejectionZone);
   InitRejectionZone(b.bearRejectionZone);
   MqlRates r[]; ArraySetAsSeries(r,true);
   int lookback=(tf==InpETF ? InpActiveZoneLookback : InpMarketMapLookback);
   lookback=MathMax(20,MathMin(lookback,140));
   if(!CopyRatesSafe(tf,lookback+5,r)) return;
   double atr=MathMax(b.atr,PointValue()*50);
   double price=CurrentMid();

   RejectionZone bestBull,bestBear;
   InitRejectionZone(bestBull); InitRejectionZone(bestBear);
   for(int i=1; i<=lookback && i<ArraySize(r)-2; i++)
   {
      double body=MathMax(CandleBody(r[i]),PointValue());
      double upper=r[i].high-MathMax(r[i].open,r[i].close);
      double lower=MathMin(r[i].open,r[i].close)-r[i].low;
      bool bullReclaim=(r[i].close>r[i].open || r[i].close>r[i+1].high);
      bool bearReclaim=(r[i].close<r[i].open || r[i].close<r[i+1].low);
      bool bullSweep=(b.swings.validLow && r[i].low<b.swings.lastLow && r[i].close>b.swings.lastLow-atr*0.05);
      bool bearSweep=(b.swings.validHigh && r[i].high>b.swings.lastHigh && r[i].close<b.swings.lastHigh+atr*0.05);
      bool bull=(lower>=body*1.45 && bullReclaim) || bullSweep;
      bool bear=(upper>=body*1.45 && bearReclaim) || bearSweep;
      if(!bull && !bear) continue;

      int touches=0;
      bool invalid=false;
      if(bull)
      {
         double zl=r[i].low;
         double zh=MathMin(r[i].open,r[i].close)+body*0.35;
         for(int j=i-1; j>=1; j--)
         {
            if(r[j].low<=zh && r[j].high>=zl) touches++;
            if(r[j].close<zl-atr*0.12) invalid=true;
         }
         int strength=(int)MathMin(100.0, 30.0 + lower/body*12.0 + (bullSweep?18:0) + (r[i].close>r[i].open?8:0) + EventAgeScore(i));
         if(touches>3) strength-=18;
         if(i>InpMarketMapLookback) strength-=20;
         if(!invalid && strength>bestBull.strength)
         {
            bestBull.valid=true; bestBull.direction=1; bestBull.low=zl; bestBull.high=zh; bestBull.invalidationLevel=zl-atr*0.12;
            bestBull.strength=strength; bestBull.age=i; bestBull.touches=touches; bestBull.tf=tf; bestBull.sourceTime=r[i].time;
            bestBull.invalidated=false; bestBull.zoneState=(touches==0?"FRESH":(touches<=2?"REACTED":"WORN"));
         }
      }
      if(bear)
      {
         double zh=r[i].high;
         double zl=MathMax(r[i].open,r[i].close)-body*0.35;
         for(int j=i-1; j>=1; j--)
         {
            if(r[j].low<=zh && r[j].high>=zl) touches++;
            if(r[j].close>zh+atr*0.12) invalid=true;
         }
         int strength=(int)MathMin(100.0, 30.0 + upper/body*12.0 + (bearSweep?18:0) + (r[i].close<r[i].open?8:0) + EventAgeScore(i));
         if(touches>3) strength-=18;
         if(i>InpMarketMapLookback) strength-=20;
         if(!invalid && strength>bestBear.strength)
         {
            bestBear.valid=true; bestBear.direction=-1; bestBear.low=zl; bestBear.high=zh; bestBear.invalidationLevel=zh+atr*0.12;
            bestBear.strength=strength; bestBear.age=i; bestBear.touches=touches; bestBear.tf=tf; bestBear.sourceTime=r[i].time;
            bestBear.invalidated=false; bestBear.zoneState=(touches==0?"FRESH":(touches<=2?"REACTED":"WORN"));
         }
      }
   }
   if(bestBull.valid && bestBull.touches<=4 && bestBull.age<=lookback)
   {
      bestBull.valid=(price>=bestBull.low-atr*8.0 || tf!=InpETF); // historical HTF zones are context, not direct signals.
      FinalizeRejectionAudit(bestBull); b.bullRejectionZone=bestBull;
   }
   else { FinalizeRejectionAudit(b.bullRejectionZone); }
   if(bestBear.valid && bestBear.touches<=4 && bestBear.age<=lookback)
   {
      bestBear.valid=(price<=bestBear.high+atr*8.0 || tf!=InpETF);
      FinalizeRejectionAudit(bestBear); b.bearRejectionZone=bestBear;
   }
   else { FinalizeRejectionAudit(b.bearRejectionZone); }
}

string BoolYN(bool v) { return v ? "YES" : "NO"; }

double CandleBody(MqlRates &c) { return MathAbs(c.close-c.open); }

string WickClassForCandle(MqlRates &c, int direction, double &upperWick, double &lowerWick, double &ratio)
{
   double body = MathMax(CandleBody(c), PointValue());
   upperWick = c.high - MathMax(c.open,c.close);
   lowerWick = MathMin(c.open,c.close) - c.low;
   ratio = MathMax(upperWick,lowerWick) / body;
   if(ratio >= 2.80) return "LONG_WICK_NOISY";
   if(direction>0 && lowerWick/body >= 1.60) return "BULLISH_SWEEP_WICK";
   if(direction<0 && upperWick/body >= 1.60) return "BEARISH_SWEEP_WICK";
   if(ratio <= 1.20) return "CLEAN_BODY";
   return "MIXED_WICK";
}

int CountTouchesAfter(ENUM_TIMEFRAMES tf, Zone &z, datetime sourceTime, int direction, bool &invalidated)
{
   invalidated=false;
   MqlRates r[];
   if(!CopyRatesSafe(tf, 80, r)) return 0;
   int touches=0;
   for(int i=1;i<80;i++)
   {
      if(r[i].time<=sourceTime) break;
      if(direction>0 && r[i].low <= z.high && r[i].high >= z.low) touches++;
      if(direction<0 && r[i].high >= z.low && r[i].low <= z.high) touches++;
      if(direction>0 && r[i].close < z.low) invalidated=true;
      if(direction<0 && r[i].close > z.high) invalidated=true;
   }
   return touches;
}

void FinalizeOBAudit(ENUM_TIMEFRAMES tf, Zone &z)
{
   z.audit = StringFormat("OB[%s,%s] Event=%s Valid=%s Quality=%d Zone=%.5f-%.5f Refined=%.5f-%.5f Body=%.5f-%.5f SrcOHLC=%.5f/%.5f/%.5f/%.5f BodySize=%.5f UpperWick=%.5f LowerWick=%.5f WickBody=%.2f WickClass=%s DispScore=%.2f DispLink=%s StructLink=%s SweepLink=%s Freshness=%s Taps=%d Invalid=%.5f Target=%s Block=%s",
                          TFToString(tf), z.direction>0?"BULL":"BEAR", z.sourceEventID, BoolYN(z.valid), z.qualityScore,
                          z.low,z.high,z.refinedLow,z.refinedHigh,z.bodyLow,z.bodyHigh,
                          z.sourceOpen,z.sourceHigh,z.sourceLow,z.sourceClose,z.bodySize,z.upperWick,z.lowerWick,z.wickBodyRatio,z.wickClass,
                          z.displacementScore,z.displacementLink,z.structureLink,BoolYN(z.hasSweepLink),z.freshness,z.tapCount,z.invalidationLevel,z.targetRelation,z.blockReason);
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
      b.bullFVG.refinedLow = b.bullFVG.low + (b.bullFVG.high-b.bullFVG.low)*0.00;
      b.bullFVG.refinedHigh = b.bullFVG.low + (b.bullFVG.high-b.bullFVG.low)*0.55;
      b.bullFVG.invalidationLevel = b.bullFVG.low;
      b.bullFVG.sourceEventID = (b.lastBullEvent.valid ? b.lastBullEvent.eventID : TFToString(tf)+"_BULL_FVG_"+TimeToString(r[1].time,TIME_DATE|TIME_MINUTES));
      b.bullFVG.displacementScore = (b.atr>0 ? MathAbs(r[2].close-r[2].open)/b.atr : 0);
      b.bullFVG.hasDisplacement = (b.bullFVG.displacementScore>=InpDisplacementATR);
      b.bullFVG.hasStructureLink = (b.lastBullEvent.valid || b.bosUp || b.chochUp || b.mssUp);
      b.bullFVG.hasSweepLink = (b.sweepLow || b.inDiscount);
      bool invBull=false; b.bullFVG.tapCount=CountTouchesAfter(tf,b.bullFVG,b.bullFVG.time,1,invBull);
      b.bullFVG.invalidated=invBull; b.bullFVG.mitigated=(b.bullFVG.tapCount>1); b.bullFVG.fresh=(b.bullFVG.tapCount==0 && !invBull);
      b.bullFVG.freshness = b.bullFVG.invalidated ? "INVALIDATED" : (b.bullFVG.fresh ? "FRESH" : (b.bullFVG.tapCount==1 ? "TAPPED" : "MITIGATED"));
      b.bullFVG.qualityScore = 30 + (b.bullFVG.hasStructureLink?25:0) + (b.bullFVG.hasSweepLink?15:0) + (b.bullFVG.hasDisplacement?10:0) - (b.bullFVG.mitigated?15:0) - (b.bullFVG.invalidated?40:0);
      b.bullFVG.targetLevel=b.buySideLiquidity;
      b.bullFVG.targetRelation=StringFormat("target=%.5f obstacle=%.5f",b.bullFVG.targetLevel,b.bullFVG.obstacleLevel);
      b.bullFVG.audit=StringFormat("FVG[%s,BULL] Event=%s Valid=%s Quality=%d Zone=%.5f-%.5f Refined=%.5f-%.5f Disp=%.2f Struct=%s Sweep=%s Freshness=%s Taps=%d Target=%s",
                                   TFToString(tf),b.bullFVG.sourceEventID,BoolYN(b.bullFVG.valid),b.bullFVG.qualityScore,b.bullFVG.low,b.bullFVG.high,b.bullFVG.refinedLow,b.bullFVG.refinedHigh,b.bullFVG.displacementScore,BoolYN(b.bullFVG.hasStructureLink),BoolYN(b.bullFVG.hasSweepLink),b.bullFVG.freshness,b.bullFVG.tapCount,b.bullFVG.targetRelation);
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
      b.bearFVG.refinedLow = b.bearFVG.high - (b.bearFVG.high-b.bearFVG.low)*0.55;
      b.bearFVG.refinedHigh = b.bearFVG.high;
      b.bearFVG.invalidationLevel = b.bearFVG.high;
      b.bearFVG.sourceEventID = (b.lastBearEvent.valid ? b.lastBearEvent.eventID : TFToString(tf)+"_BEAR_FVG_"+TimeToString(r[1].time,TIME_DATE|TIME_MINUTES));
      b.bearFVG.displacementScore = (b.atr>0 ? MathAbs(r[2].close-r[2].open)/b.atr : 0);
      b.bearFVG.hasDisplacement = (b.bearFVG.displacementScore>=InpDisplacementATR);
      b.bearFVG.hasStructureLink = (b.lastBearEvent.valid || b.bosDown || b.chochDown || b.mssDown);
      b.bearFVG.hasSweepLink = (b.sweepHigh || b.inPremium);
      bool invBear=false; b.bearFVG.tapCount=CountTouchesAfter(tf,b.bearFVG,b.bearFVG.time,-1,invBear);
      b.bearFVG.invalidated=invBear; b.bearFVG.mitigated=(b.bearFVG.tapCount>1); b.bearFVG.fresh=(b.bearFVG.tapCount==0 && !invBear);
      b.bearFVG.freshness = b.bearFVG.invalidated ? "INVALIDATED" : (b.bearFVG.fresh ? "FRESH" : (b.bearFVG.tapCount==1 ? "TAPPED" : "MITIGATED"));
      b.bearFVG.qualityScore = 30 + (b.bearFVG.hasStructureLink?25:0) + (b.bearFVG.hasSweepLink?15:0) + (b.bearFVG.hasDisplacement?10:0) - (b.bearFVG.mitigated?15:0) - (b.bearFVG.invalidated?40:0);
      b.bearFVG.targetLevel=b.sellSideLiquidity;
      b.bearFVG.targetRelation=StringFormat("target=%.5f obstacle=%.5f",b.bearFVG.targetLevel,b.bearFVG.obstacleLevel);
      b.bearFVG.audit=StringFormat("FVG[%s,BEAR] Event=%s Valid=%s Quality=%d Zone=%.5f-%.5f Refined=%.5f-%.5f Disp=%.2f Struct=%s Sweep=%s Freshness=%s Taps=%d Target=%s",
                                   TFToString(tf),b.bearFVG.sourceEventID,BoolYN(b.bearFVG.valid),b.bearFVG.qualityScore,b.bearFVG.low,b.bearFVG.high,b.bearFVG.refinedLow,b.bearFVG.refinedHigh,b.bearFVG.displacementScore,BoolYN(b.bearFVG.hasStructureLink),BoolYN(b.bearFVG.hasSweepLink),b.bearFVG.freshness,b.bearFVG.tapCount,b.bearFVG.targetRelation);
   }
}

void BuildOrderBlockCandidate(ENUM_TIMEFRAMES tf, TFBrain &b, MqlRates &r[], int dispIndex, int sourceIndex, int direction, Zone &z)
{
   InitZone(z);
   double atr = b.atr;
   if(atr<=0) return;
   MqlRates src = r[sourceIndex];
   MqlRates disp = r[dispIndex];

   z.direction = direction;
   z.time = src.time;
   z.displacementTime = disp.time;
   z.sourceOpen = src.open;
   z.sourceHigh = src.high;
   z.sourceLow = src.low;
   z.sourceClose = src.close;
   z.bodySize = CandleBody(src);
   z.bodyLow = MathMin(src.open,src.close);
   z.bodyHigh = MathMax(src.open,src.close);
   z.wickClass = WickClassForCandle(src,direction,z.upperWick,z.lowerWick,z.wickBodyRatio);
   z.noisyWick = (z.wickClass=="LONG_WICK_NOISY");
   z.displacementScore = CandleBody(disp)/atr;
   z.hasDisplacement = (z.displacementScore >= InpDisplacementATR);

   if(direction>0)
   {
      z.name="Bullish Order Block";
      z.low=src.low;
      z.high=z.bodyHigh;
      z.invalidationLevel=src.low;
      z.hasStructureLink = (disp.close > b.swings.lastHigh || b.bosUp || b.chochUp || b.mssUp || disp.high > b.swings.lastHigh);
      z.structureLink = (b.mssUp?"MSS_UP":(b.chochUp?"CHOCH_UP":(b.bosUp?"BOS_UP":(disp.close>b.swings.lastHigh?"DISP_BROKE_SWING_HIGH":"NONE"))));
      z.sourceEventID = (b.lastBullEvent.valid ? b.lastBullEvent.eventID : TFToString(tf)+"_BULL_DISP_"+TimeToString(disp.time,TIME_DATE|TIME_MINUTES));
      z.displacementLink = StringFormat("dispTime=%s dispScore=%.2f broken=%.5f",TimeToString(disp.time,TIME_DATE|TIME_MINUTES),z.displacementScore,b.lastBullEvent.brokenLevel);
      z.hasSweepLink = b.sweepLow || (src.low < b.swings.lastLow && src.close > b.swings.lastLow) || b.inDiscount;
      z.refinedLow = z.low + (z.high-z.low)*0.00;
      z.refinedHigh = z.low + (z.high-z.low)*0.55; // lower half of bullish OB only
      z.targetLevel = b.buySideLiquidity;
      z.obstacleLevel = b.bearOB.valid ? b.bearOB.low : 0;
   }
   else
   {
      z.name="Bearish Order Block";
      z.low=z.bodyLow;
      z.high=src.high;
      z.invalidationLevel=src.high;
      z.hasStructureLink = (disp.close < b.swings.lastLow || b.bosDown || b.chochDown || b.mssDown || disp.low < b.swings.lastLow);
      z.structureLink = (b.mssDown?"MSS_DOWN":(b.chochDown?"CHOCH_DOWN":(b.bosDown?"BOS_DOWN":(disp.close<b.swings.lastLow?"DISP_BROKE_SWING_LOW":"NONE"))));
      z.sourceEventID = (b.lastBearEvent.valid ? b.lastBearEvent.eventID : TFToString(tf)+"_BEAR_DISP_"+TimeToString(disp.time,TIME_DATE|TIME_MINUTES));
      z.displacementLink = StringFormat("dispTime=%s dispScore=%.2f broken=%.5f",TimeToString(disp.time,TIME_DATE|TIME_MINUTES),z.displacementScore,b.lastBearEvent.brokenLevel);
      z.hasSweepLink = b.sweepHigh || (src.high > b.swings.lastHigh && src.close < b.swings.lastHigh) || b.inPremium;
      z.refinedLow = z.high - (z.high-z.low)*0.55; // upper half of bearish OB only
      z.refinedHigh = z.high;
      z.targetLevel = b.sellSideLiquidity;
      z.obstacleLevel = b.bullOB.valid ? b.bullOB.high : 0;
   }

   double width = z.high-z.low;
   z.tooWide = (width > atr*2.20 || width < PointValue()*5);
   bool invalid=false;
   int touches = CountTouchesAfter(tf,z,z.time,direction,invalid);
   z.mitigated = (touches>1);
   z.invalidated = invalid;
   z.fresh = (touches==0 && !invalid);
   z.tapCount = touches;
   z.freshness = z.invalidated ? "INVALIDATED" : (z.fresh ? "FRESH" : (touches==1 ? "TAPPED" : "MITIGATED"));
   z.targetRelation = StringFormat("target=%.5f obstacle=%.5f",z.targetLevel,z.obstacleLevel);

   z.qualityScore = 0;
   if(z.hasDisplacement) z.qualityScore += 20;
   if(z.displacementScore >= 1.00) z.qualityScore += 10;
   if(z.hasStructureLink) z.qualityScore += 24;
   if(z.hasSweepLink) z.qualityScore += 18;
   if(!z.noisyWick) z.qualityScore += 10; else z.qualityScore -= 18;
   if(!z.tooWide) z.qualityScore += 10; else z.qualityScore -= 16;
   if(z.fresh) z.qualityScore += 12;
   else if(touches==1) z.qualityScore += 2;
   else if(z.mitigated) z.qualityScore -= 14;
   if(z.invalidated) z.qualityScore -= 40;
   if(direction>0 && b.inDiscount) z.qualityScore += 8;
   if(direction<0 && b.inPremium) z.qualityScore += 8;

   string block="";
   if(!z.hasDisplacement) SoftAdd(block,"No meaningful displacement");
   if(!z.hasStructureLink) SoftAdd(block,"No BOS/CHOCH/MSS/swing-break link");
   if(!z.hasSweepLink) SoftAdd(block,"No sweep or logical premium/discount context");
   if(z.noisyWick) SoftAdd(block,"Long/noisy wick candle");
   if(z.tooWide) SoftAdd(block,"OB too wide or invalid width");
   if(z.mitigated) SoftAdd(block,"OB already mitigated by multiple taps");
   if(z.invalidated) SoftAdd(block,"OB invalidated");
   z.blockReason=block;
   z.valid = (z.qualityScore>=58 && z.hasDisplacement && z.hasStructureLink && z.hasSweepLink && !z.noisyWick && !z.tooWide && !z.invalidated && !z.mitigated);
   FinalizeOBAudit(tf,z);
}

void DetectOrderBlocks(ENUM_TIMEFRAMES tf, TFBrain &b)
{
   InitZone(b.bullOB);
   InitZone(b.bearOB);
   MqlRates r[];
   int count = 80;
   if(!CopyRatesSafe(tf, count, r)) return;
   double atr = b.atr;
   if(atr<=0) return;

   Zone bestBull,bestBear,cand;
   InitZone(bestBull); InitZone(bestBear); InitZone(cand);

   for(int i=1; i<30; i++)
   {
      double body = CandleBody(r[i]);
      bool upDisp = (r[i].close > r[i].open && body >= atr * InpDisplacementATR);
      bool downDisp = (r[i].close < r[i].open && body >= atr * InpDisplacementATR);
      if(upDisp)
      {
         for(int j=i+1; j<MathMin(i+12,count-1); j++)
         {
            if(r[j].close < r[j].open)
            {
               BuildOrderBlockCandidate(tf,b,r,i,j,1,cand);
               if(cand.qualityScore > bestBull.qualityScore) bestBull=cand;
               break;
            }
         }
      }
      if(downDisp)
      {
         for(int j=i+1; j<MathMin(i+12,count-1); j++)
         {
            if(r[j].close > r[j].open)
            {
               BuildOrderBlockCandidate(tf,b,r,i,j,-1,cand);
               if(cand.qualityScore > bestBear.qualityScore) bestBear=cand;
               break;
            }
         }
      }
   }

   b.bullOB=bestBull;
   b.bearOB=bestBear;
   if(!b.bullOB.valid && b.bullOB.audit=="") FinalizeOBAudit(tf,b.bullOB);
   if(!b.bearOB.valid && b.bearOB.audit=="") FinalizeOBAudit(tf,b.bearOB);
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

double FindEqualLiquidityLevel(ENUM_TIMEFRAMES tf, double atr, bool highs)
{
   if(atr<=0) return 0;
   MqlRates r[];
   if(!CopyRatesSafe(tf, 80, r)) return 0;
   double tol = atr * InpEqualLiquidityATR;
   for(int i=2;i<30;i++)
   {
      for(int j=i+3;j<60;j++)
      {
         double a = highs ? r[i].high : r[i].low;
         double b = highs ? r[j].high : r[j].low;
         if(MathAbs(a-b) <= tol) return (a+b)/2.0;
      }
   }
   return 0;
}

void BuildStructureLiquidityEvents(ENUM_TIMEFRAMES tf, TFBrain &b)
{
   b.majorHigh = b.swings.prevHigh>0 ? MathMax(b.swings.lastHigh,b.swings.prevHigh) : b.swings.lastHigh;
   b.majorLow  = b.swings.prevLow>0 ? MathMin(b.swings.lastLow,b.swings.prevLow) : b.swings.lastLow;
   b.internalHigh = b.swings.lastHigh;
   b.internalLow = b.swings.lastLow;
   b.equalHighLevel = FindEqualLiquidityLevel(tf,b.atr,true);
   b.equalLowLevel = FindEqualLiquidityLevel(tf,b.atr,false);
   b.buySideLiquidity = (b.equalHighLevel>0 ? b.equalHighLevel : b.internalHigh);
   b.sellSideLiquidity = (b.equalLowLevel>0 ? b.equalLowLevel : b.internalLow);

   if(b.sweepHigh)
   {
      b.sweepHighLevel=b.swings.lastHigh;
      b.sweepHighTime=iTime(_Symbol,tf,1);
      b.sweepHighQuality = (b.atr>0 ? MathAbs(b.high1-b.close1)/b.atr : 0);
   }
   if(b.sweepLow)
   {
      b.sweepLowLevel=b.swings.lastLow;
      b.sweepLowTime=iTime(_Symbol,tf,1);
      b.sweepLowQuality = (b.atr>0 ? MathAbs(b.close1-b.low1)/b.atr : 0);
   }

   if(b.bosUp) b.bosBrokenLevel=b.swings.lastHigh;
   if(b.bosDown) b.bosBrokenLevel=b.swings.lastLow;
   if(b.chochUp) b.chochBrokenLevel=b.swings.lastHigh;
   if(b.chochDown) b.chochBrokenLevel=b.swings.lastLow;
   if(b.mssUp) b.mssBrokenLevel=(b.swings.validHigh ? b.swings.lastHigh : b.high2);
   if(b.mssDown) b.mssBrokenLevel=(b.swings.validLow ? b.swings.lastLow : b.low2);

   InitStructureEvent(b.lastBullEvent);
   InitStructureEvent(b.lastBearEvent);
   if(b.bosUp || b.chochUp || b.mssUp)
   {
      b.lastBullEvent.valid=true;
      b.lastBullEvent.direction=1;
      b.lastBullEvent.eventType = b.mssUp ? "MSS_UP" : (b.chochUp ? "CHOCH_UP" : "BOS_UP");
      b.lastBullEvent.eventID = TFToString(tf)+"_"+b.lastBullEvent.eventType+"_"+TimeToString(iTime(_Symbol,tf,1),TIME_DATE|TIME_MINUTES);
      b.lastBullEvent.level=b.high1;
      b.lastBullEvent.brokenLevel=(b.mssBrokenLevel>0?b.mssBrokenLevel:(b.chochBrokenLevel>0?b.chochBrokenLevel:b.bosBrokenLevel));
      b.lastBullEvent.eventTime=iTime(_Symbol,tf,1);
      b.lastBullEvent.displacementScore=(b.atr>0?MathAbs(b.close1-b.open1)/b.atr:0);
      b.lastBullEvent.closeBackQuality=b.sweepLowQuality;
      b.lastBullEvent.audit=StringFormat("%s broken=%.5f disp=%.2f sweepLow=%.5f quality=%.2f",b.lastBullEvent.eventID,b.lastBullEvent.brokenLevel,b.lastBullEvent.displacementScore,b.sweepLowLevel,b.sweepLowQuality);
   }
   if(b.bosDown || b.chochDown || b.mssDown)
   {
      b.lastBearEvent.valid=true;
      b.lastBearEvent.direction=-1;
      b.lastBearEvent.eventType = b.mssDown ? "MSS_DOWN" : (b.chochDown ? "CHOCH_DOWN" : "BOS_DOWN");
      b.lastBearEvent.eventID = TFToString(tf)+"_"+b.lastBearEvent.eventType+"_"+TimeToString(iTime(_Symbol,tf,1),TIME_DATE|TIME_MINUTES);
      b.lastBearEvent.level=b.low1;
      b.lastBearEvent.brokenLevel=(b.mssBrokenLevel>0?b.mssBrokenLevel:(b.chochBrokenLevel>0?b.chochBrokenLevel:b.bosBrokenLevel));
      b.lastBearEvent.eventTime=iTime(_Symbol,tf,1);
      b.lastBearEvent.displacementScore=(b.atr>0?MathAbs(b.close1-b.open1)/b.atr:0);
      b.lastBearEvent.closeBackQuality=b.sweepHighQuality;
      b.lastBearEvent.audit=StringFormat("%s broken=%.5f disp=%.2f sweepHigh=%.5f quality=%.2f",b.lastBearEvent.eventID,b.lastBearEvent.brokenLevel,b.lastBearEvent.displacementScore,b.sweepHighLevel,b.sweepHighQuality);
   }

   b.liquidityAudit = StringFormat("Liquidity[%s] BSL=%.5f SSL=%.5f EQH=%.5f EQL=%.5f SweepH=%.5f q=%.2f SweepL=%.5f q=%.2f",
                                   TFToString(tf),b.buySideLiquidity,b.sellSideLiquidity,b.equalHighLevel,b.equalLowLevel,b.sweepHighLevel,b.sweepHighQuality,b.sweepLowLevel,b.sweepLowQuality);
   b.eventAudit = StringFormat("Events[%s] pattern=%s BOS=%.5f CHOCH=%.5f MSS=%.5f BullEvent={%s} BearEvent={%s}",
                               TFToString(tf),b.swings.pattern,b.bosBrokenLevel,b.chochBrokenLevel,b.mssBrokenLevel,b.lastBullEvent.audit,b.lastBearEvent.audit);
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
   b.priceInBullOBRefined=false; b.priceInBearOBRefined=false;
   InitRejectionZone(b.bullRejectionZone); InitRejectionZone(b.bearRejectionZone);
   b.wyckoffSpring=false; b.wyckoffUpthrust=false; b.accumulationHint=false; b.distributionHint=false;
   b.rsiBullishExhaustion=false; b.rsiBearishExhaustion=false; b.rsiBullDiv=false; b.rsiBearDiv=false;
   b.majorHigh=0; b.majorLow=0; b.internalHigh=0; b.internalLow=0;
   b.equalHighLevel=0; b.equalLowLevel=0; b.buySideLiquidity=0; b.sellSideLiquidity=0;
   b.sweepHighLevel=0; b.sweepLowLevel=0; b.sweepHighTime=0; b.sweepLowTime=0;
   b.sweepHighQuality=0; b.sweepLowQuality=0; b.bosBrokenLevel=0; b.chochBrokenLevel=0; b.mssBrokenLevel=0;
   b.eventAudit=""; b.liquidityAudit="";
   InitStructureEvent(b.lastBullEvent); InitStructureEvent(b.lastBearEvent);
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
   BuildStructureLiquidityEvents(tf,b);

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
   DetectRejectionZones(tf,b);
   double priceMid = CurrentMid();
   b.priceNearBullFVG = PriceNearZone(priceMid,b.bullFVG,b.atr,InpFVGRetestATR);
   b.priceNearBearFVG = PriceNearZone(priceMid,b.bearFVG,b.atr,InpFVGRetestATR);
   b.priceNearBullOB = PriceNearZone(priceMid,b.bullOB,b.atr,InpOBRetestATR);
   b.priceNearBearOB = PriceNearZone(priceMid,b.bearOB,b.atr,InpOBRetestATR);
   b.priceInBullOBRefined = PriceInRefinedZone(priceMid,b.bullOB,b.atr);
   b.priceInBearOBRefined = PriceInRefinedZone(priceMid,b.bearOB,b.atr);

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
   if(b.priceNearBullOB) b.bullScore += 6 + b.bullOB.qualityScore/10;
   if(b.priceNearBearOB) b.bearScore += 6 + b.bearOB.qualityScore/10;
   if(b.priceInBullOBRefined) b.bullScore += 6;
   if(b.priceInBearOBRefined) b.bearScore += 6;
   if(b.wyckoffSpring || b.accumulationHint) b.bullScore += 8;
   if(b.wyckoffUpthrust || b.distributionHint) b.bearScore += 8;
   if(b.rsiBullishExhaustion || b.rsiBullDiv) b.bullScore += 4;
   if(b.rsiBearishExhaustion || b.rsiBearDiv) b.bearScore += 4;
   if(b.adx >= InpADXTrendThreshold && b.plusDI > b.minusDI) b.bullScore += 4;
   if(b.adx >= InpADXTrendThreshold && b.minusDI > b.plusDI) b.bearScore += 4;

   b.notes = StringFormat("%s bias=%d struct=%d/%s bull=%d bear=%d sweepL=%s sweepH=%s bosU=%s bosD=%s chochU=%s chochD=%s OBb=%s(%d/%s) OBs=%s(%d/%s) FVGb=%s FVGs=%s",
                          b.name,b.finalBias,b.structureBias,b.swings.pattern,b.bullScore,b.bearScore,
                          b.sweepLow?"Y":"N", b.sweepHigh?"Y":"N", b.bosUp?"Y":"N", b.bosDown?"Y":"N",
                          b.chochUp?"Y":"N", b.chochDown?"Y":"N",
                          b.bullOB.valid?"Y":"N", b.bullOB.qualityScore, b.bullOB.freshness,
                          b.bearOB.valid?"Y":"N", b.bearOB.qualityScore, b.bearOB.freshness,
                          b.bullFVG.valid?"Y":"N", b.bearFVG.valid?"Y":"N");
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

bool HTFConflictBlocksDirection(int dir, TFBrain &h4, TFBrain &h1, TFBrain &m15, ENUM_BRAIN_STATE state, string &why)
{
   bool completeReversal = (dir>0 && state==STATE_REVERSAL_CONFIRMED_BULL) || (dir<0 && state==STATE_REVERSAL_CONFIRMED_BEAR);
   if(completeReversal) return false;
   if(dir>0)
   {
      if((h4.finalBias<0 && h1.finalBias<0) || state==STATE_REVERSAL_WARNING_BEAR || state==STATE_REVERSAL_CONFIRMED_BEAR)
      {
         why="HTF/conflict gate blocks BUY without complete bullish reversal";
         return true;
      }
      if(m15.chochDown || m15.mssDown)
      {
         why="Active M15 bearish CHOCH/MSS blocks BUY";
         return true;
      }
   }
   else
   {
      if((h4.finalBias>0 && h1.finalBias>0) || state==STATE_REVERSAL_WARNING_BULL || state==STATE_REVERSAL_CONFIRMED_BULL)
      {
         why="HTF/conflict gate blocks SELL without complete bearish reversal";
         return true;
      }
      if(m15.chochUp || m15.mssUp)
      {
         why="Active M15 bullish CHOCH/MSS blocks SELL";
         return true;
      }
   }
   return false;
}

bool BuildPreEntryRiskModel(int dir, TFBrain &h1, TFBrain &m15, EntryModelResult &r, string &why)
{
   why="";
   double atr = MathMax(m15.atr, PointValue()*50);
   r.entry = (dir>0 ? CurrentAsk() : CurrentBid());
   double baseSL=0;
   if(dir>0)
   {
      if(m15.swings.validLow) baseSL=m15.swings.lastLow;
      if(m15.bullOB.valid) baseSL=(baseSL==0 ? m15.bullOB.invalidationLevel : MathMin(baseSL,m15.bullOB.invalidationLevel));
      if(m15.bullFVG.valid) baseSL=(baseSL==0 ? m15.bullFVG.invalidationLevel : MathMin(baseSL,m15.bullFVG.invalidationLevel));
      if(baseSL<=0 || baseSL>=r.entry) { SoftAdd(why,"BUY invalidation not logical"); return false; }
      r.sl=NormalizePrice(baseSL-atr*InpSL_ATR_Buffer);
      r.targetLevel=0;
      if(m15.buySideLiquidity>r.entry) r.targetLevel=m15.buySideLiquidity;
      if(h1.buySideLiquidity>r.entry) r.targetLevel=MathMax(r.targetLevel,h1.buySideLiquidity);
      if(r.targetLevel<=r.entry && m15.swings.validHigh && m15.swings.lastHigh>r.entry) r.targetLevel=m15.swings.lastHigh;
      if(r.targetLevel<=r.entry) { SoftAdd(why,"No buy-side target liquidity above entry"); return false; }
      r.obstacleLevel=(m15.bearOB.valid && m15.bearOB.low>r.entry ? m15.bearOB.low : 0);
      if(r.obstacleLevel>0 && r.obstacleLevel<r.targetLevel) r.tp=NormalizePrice(r.obstacleLevel);
      else r.tp=NormalizePrice(r.targetLevel);
   }
   else
   {
      if(m15.swings.validHigh) baseSL=m15.swings.lastHigh;
      if(m15.bearOB.valid) baseSL=(baseSL==0 ? m15.bearOB.invalidationLevel : MathMax(baseSL,m15.bearOB.invalidationLevel));
      if(m15.bearFVG.valid) baseSL=(baseSL==0 ? m15.bearFVG.invalidationLevel : MathMax(baseSL,m15.bearFVG.invalidationLevel));
      if(baseSL<=0 || baseSL<=r.entry) { SoftAdd(why,"SELL invalidation not logical"); return false; }
      r.sl=NormalizePrice(baseSL+atr*InpSL_ATR_Buffer);
      r.targetLevel=0;
      if(m15.sellSideLiquidity<r.entry && m15.sellSideLiquidity>0) r.targetLevel=m15.sellSideLiquidity;
      if(h1.sellSideLiquidity<r.entry && h1.sellSideLiquidity>0) r.targetLevel=(r.targetLevel==0 ? h1.sellSideLiquidity : MathMin(r.targetLevel,h1.sellSideLiquidity));
      if((r.targetLevel<=0 || r.targetLevel>=r.entry) && m15.swings.validLow && m15.swings.lastLow<r.entry) r.targetLevel=m15.swings.lastLow;
      if(r.targetLevel<=0 || r.targetLevel>=r.entry) { SoftAdd(why,"No sell-side target liquidity below entry"); return false; }
      r.obstacleLevel=(m15.bullOB.valid && m15.bullOB.high<r.entry ? m15.bullOB.high : 0);
      if(r.obstacleLevel>0 && r.obstacleLevel>r.targetLevel) r.tp=NormalizePrice(r.obstacleLevel);
      else r.tp=NormalizePrice(r.targetLevel);
   }

   double risk=MathAbs(r.entry-r.sl);
   double reward=MathAbs(r.tp-r.entry);
   if(risk<=PointValue()*5) { SoftAdd(why,"Risk distance invalid/tiny"); return false; }
   r.rr=reward/risk;
   if(r.rr < InpMinRRSoft) { SoftAdd(why,StringFormat("RR %.2f below minimum %.2f",r.rr,InpMinRRSoft)); return false; }
   string stopWhy;
   ENUM_BRAIN_DECISION d=(dir>0 ? DECISION_BUY : DECISION_SELL);
   if(!StopsOK(d,r.entry,r.sl,r.tp,stopWhy)) { SoftAdd(why,stopWhy); return false; }
   return true;
}

void EvaluateEntryModel(int dir, TFBrain &h4, TFBrain &h1, TFBrain &m15, ENUM_BRAIN_STATE state, EntryModelResult &r)
{
   InitEntryModelResult(r,dir);
   Zone z; Zone fvg;
   if(dir>0) { z=m15.bullOB; fvg=m15.bullFVG; }
   else { z=m15.bearOB; fvg=m15.bearFVG; }
   bool nearOB=(dir>0 ? m15.priceNearBullOB : m15.priceNearBearOB);
   bool nearFVG=(dir>0 ? m15.priceNearBullFVG : m15.priceNearBearFVG);
   bool refined=(dir>0 ? m15.priceInBullOBRefined : m15.priceInBearOBRefined);
   string conflictWhy="";
   bool conflict=HTFConflictBlocksDirection(dir,h4,h1,m15,state,conflictWhy);

   bool fvgUsable = nearFVG && fvg.valid && fvg.qualityScore>=45 && !fvg.invalidated && !fvg.mitigated;
   bool obUsable = nearOB && z.valid && refined;
   r.zoneOK = (obUsable || fvgUsable);
   r.retestOK = r.zoneOK;
   r.liquidityOK = (dir>0 ? (m15.sweepLow || h1.sweepLow || z.hasSweepLink || fvg.hasSweepLink) : (m15.sweepHigh || h1.sweepHigh || z.hasSweepLink || fvg.hasSweepLink));
   r.displacementOK = (dir>0 ? (m15.displacementUp || h1.displacementUp || z.hasDisplacement || fvg.hasDisplacement) : (m15.displacementDown || h1.displacementDown || z.hasDisplacement || fvg.hasDisplacement));
   r.structureOK = (dir>0 ? (m15.lastBullEvent.valid || h1.lastBullEvent.valid || z.hasStructureLink || fvg.hasStructureLink) : (m15.lastBearEvent.valid || h1.lastBearEvent.valid || z.hasStructureLink || fvg.hasStructureLink));
   r.locationOK = (dir>0 ? (m15.inDiscount || h1.inDiscount || z.hasSweepLink || fvg.hasSweepLink) : (m15.inPremium || h1.inPremium || z.hasSweepLink || fvg.hasSweepLink));
   double distFromEMA = (m15.atr>0 ? MathAbs(m15.close1-m15.emaFast)/m15.atr : 0);
   r.lateEntryOK = (distFromEMA <= 2.40 && !m15.nearEquilibrium);

   if(!r.zoneOK) SoftAdd(r.blockReasons,dir>0?"BUY zone/retest incomplete":"SELL zone/retest incomplete");
   if(nearOB && !z.valid) SoftAdd(r.blockReasons,"OB rejected: "+z.blockReason);
   if(nearOB && z.valid && !refined) SoftAdd(r.blockReasons,"OB touched outside refined entry zone");
   if(!r.liquidityOK) SoftAdd(r.blockReasons,"Liquidity/sweep context missing");
   if(!r.displacementOK) SoftAdd(r.blockReasons,"Displacement missing");
   if(!r.structureOK) SoftAdd(r.blockReasons,"Structure event missing");
   if(!r.locationOK) SoftAdd(r.blockReasons,"Premium/discount or logical location missing");
   if(!r.lateEntryOK) SoftAdd(r.blockReasons,"Late entry/no-man's-land risk");
   if(conflict) SoftAdd(r.blockReasons,conflictWhy);

   string riskWhy="";
   r.rrOK = BuildPreEntryRiskModel(dir,h1,m15,r,riskWhy);
   if(!r.rrOK) SoftAdd(r.blockReasons,"RR/target invalid: "+riskWhy);

   if(state==STATE_UNKNOWN)
   {
      bool independent = (dir>0 && r.liquidityOK && r.displacementOK && r.structureOK) || (dir<0 && r.liquidityOK && r.displacementOK && r.structureOK);
      if(!independent) SoftAdd(r.blockReasons,"State Unknown without independent complete setup");
   }

   r.zoneResult=StringFormat("zoneOK=%s nearOB=%s obValid=%s obQ=%d refined=%s nearFVG=%s fvgQ=%d",
                             BoolYN(r.zoneOK),BoolYN(nearOB),BoolYN(z.valid),z.qualityScore,BoolYN(refined),BoolYN(nearFVG),fvg.qualityScore);
   r.liquidityResult=StringFormat("liqOK=%s %s",BoolYN(r.liquidityOK),m15.liquidityAudit);
   r.structureResult=StringFormat("structOK=%s M15{%s} H1Bull{%s} H1Bear{%s}",BoolYN(r.structureOK),m15.eventAudit,h1.lastBullEvent.audit,h1.lastBearEvent.audit);
   r.displacementResult=StringFormat("dispOK=%s M15Up=%s M15Down=%s",BoolYN(r.displacementOK),BoolYN(m15.displacementUp),BoolYN(m15.displacementDown));
   r.retestResult=StringFormat("retestOK=%s obAudit={%s} fvgAudit={%s}",BoolYN(r.retestOK),z.audit,fvg.audit);
   r.rrTargetResult=StringFormat("rrOK=%s entry=%.5f sl=%.5f tp=%.5f rr=%.2f target=%.5f obstacle=%.5f",BoolYN(r.rrOK),r.entry,r.sl,r.tp,r.rr,r.targetLevel,r.obstacleLevel);
   r.lateEntryResult=StringFormat("lateOK=%s distEMA_ATR=%.2f nearEQ=%s",BoolYN(r.lateEntryOK),distFromEMA,BoolYN(m15.nearEquilibrium));
   r.hardBlock = (r.blockReasons!="");
   r.storyComplete = (!r.hardBlock && r.zoneOK && r.liquidityOK && r.structureOK && r.displacementOK && r.retestOK && r.rrOK && r.locationOK && r.lateEntryOK);
   r.verdict = r.storyComplete ? (dir>0?"BUY_READY":"SELL_READY") : "WAIT";
   r.audit = StringFormat("%s verdict=%s hardBlock=%s blocks=%s | %s | %s | %s | %s | %s | %s | %s",
                          dir>0?"BUY_MODEL":"SELL_MODEL",r.verdict,BoolYN(r.hardBlock),r.blockReasons,
                          r.zoneResult,r.liquidityResult,r.structureResult,r.displacementResult,r.retestResult,r.rrTargetResult,r.lateEntryResult);
}

string SetupTypeToString(ENUM_SETUP_TYPE t)
{
   if(t==SETUP_TREND_CONTINUATION) return "TrendContinuation";
   if(t==SETUP_PULLBACK_CONTINUATION) return "PullbackContinuation";
   if(t==SETUP_BREAKOUT_RETEST) return "BreakoutRetest";
   if(t==SETUP_REVERSAL_AFTER_SWEEP) return "ReversalAfterSweep";
   if(t==SETUP_RANGE_EDGE_SWEEP) return "RangeEdgeSweep";
   return "NoTrade";
}

void InitEventMemoryRecord(EventMemoryRecord &e)
{
   e.valid=false; e.eventType=""; e.direction=0; e.level=0; e.eventTime=0; e.candleIndex=0; e.age=999;
   e.sourceTF=InpETF; e.invalidationLevel=0; e.retested=false; e.invalidated=false; e.qualityScore=0; e.audit="";
}

void InitMarketMap(MarketMap &m)
{
   m.valid=false; m.majorHigh=0; m.majorLow=0; m.internalHigh=0; m.internalLow=0; m.rangeHigh=0; m.rangeLow=0; m.rangeMid=0;
   m.rangeDetected=false; m.inPremium=false; m.inDiscount=false; m.buySideLiquidity=0; m.sellSideLiquidity=0;
   m.supportLevel=0; m.resistanceLevel=0; m.audit="";
}

void InitSetupCandidate(SetupCandidate &c, ENUM_SETUP_TYPE t, int dir)
{
   c.valid=false; c.mandatoryPass=false; c.hardBlock=false; c.setupType=t; c.direction=dir; c.score=0;
   c.hardBlockReason=""; c.softMissingReasons=""; c.entry=0; c.sl=0; c.tp=0; c.rr=0; c.invalidationLevel=0; c.targetLevel=0;
   c.targetSource=""; c.linkedEvents=""; c.eventAges=""; c.retestType=""; c.triggerType=""; c.entryLocationType="";
   c.lateEntryStatus=""; c.locationQuality=0; c.targetQuality=0;
   c.rejectionZoneEntryUsed=false; c.rejectionZoneAgainstTrade=false; c.rejectionZoneContext=""; c.audit="";
}

int EventAgeScore(int age)
{
   if(age<=3) return 24;
   if(age<=6) return 18;
   if(age<=9) return 11;
   if(age<=12) return 6;
   return 0;
}

string EventAgeBucket(int age)
{
   if(age<=3) return "FRESH";
   if(age<=6) return "VALID";
   if(age<=9) return "VALID_DECAYED";
   if(age<=12) return "WEAK_NEEDS_TRIGGER";
   return "EXPIRED";
}

void BuildMarketMap(TFBrain &h4, TFBrain &h1, TFBrain &m15, MarketMap &map)
{
   InitMarketMap(map);
   map.valid=true;
   map.majorHigh = (h4.majorHigh>0 ? h4.majorHigh : h1.majorHigh);
   map.majorLow  = (h4.majorLow>0 ? h4.majorLow : h1.majorLow);
   map.internalHigh = (h1.internalHigh>0 ? h1.internalHigh : m15.internalHigh);
   map.internalLow  = (h1.internalLow>0 ? h1.internalLow : m15.internalLow);
   map.rangeHigh = (m15.rangeHigh>0 ? m15.rangeHigh : h1.rangeHigh);
   map.rangeLow = (m15.rangeLow>0 ? m15.rangeLow : h1.rangeLow);
   map.rangeMid = (map.rangeHigh>0 && map.rangeLow>0 ? (map.rangeHigh+map.rangeLow)/2.0 : m15.rangeMid);
   map.rangeDetected = (m15.rangeLike || h1.rangeLike || (map.rangeHigh>0 && map.rangeLow>0 && MathAbs(map.rangeHigh-map.rangeLow)<=MathMax(m15.atr*7.0,PointValue()*50)));
   map.inPremium = (m15.inPremium || h1.inPremium);
   map.inDiscount = (m15.inDiscount || h1.inDiscount);
   map.buySideLiquidity = MathMax(MathMax(m15.buySideLiquidity,h1.buySideLiquidity),h4.buySideLiquidity);
   map.sellSideLiquidity = m15.sellSideLiquidity;
   if(map.sellSideLiquidity<=0 || (h1.sellSideLiquidity>0 && h1.sellSideLiquidity<map.sellSideLiquidity)) map.sellSideLiquidity=h1.sellSideLiquidity;
   if(map.sellSideLiquidity<=0 || (h4.sellSideLiquidity>0 && h4.sellSideLiquidity<map.sellSideLiquidity)) map.sellSideLiquidity=h4.sellSideLiquidity;
   map.supportLevel = (m15.swings.validLow ? m15.swings.lastLow : map.internalLow);
   map.resistanceLevel = (m15.swings.validHigh ? m15.swings.lastHigh : map.internalHigh);
   map.audit = StringFormat("MarketMap lookback=%d majorH=%.5f majorL=%.5f intH=%.5f intL=%.5f range=%s[%.5f/%.5f] liqB=%.5f liqS=%.5f PD=%s/%s",
                            InpMarketMapLookback,map.majorHigh,map.majorLow,map.internalHigh,map.internalLow,BoolYN(map.rangeDetected),map.rangeHigh,map.rangeLow,map.buySideLiquidity,map.sellSideLiquidity,BoolYN(map.inPremium),BoolYN(map.inDiscount));
}

void SetMemoryEvent(EventMemoryRecord &e, string typ, int dir, double level, double invalidation, int age, ENUM_TIMEFRAMES tf, bool retested, bool invalidated, int baseScore)
{
   e.valid = !invalidated && age<=InpEventMemoryBars;
   e.eventType=typ; e.direction=dir; e.level=level; e.invalidationLevel=invalidation; e.age=age; e.candleIndex=age; e.sourceTF=tf;
   e.eventTime=iTime(_Symbol,tf,age); e.retested=retested; e.invalidated=invalidated; e.qualityScore=MathMax(0,baseScore+EventAgeScore(age));
   e.audit=StringFormat("%s dir=%d level=%.5f age=%d/%s tf=%s retested=%s invalidated=%s q=%d",typ,dir,level,age,EventAgeBucket(age),TFToString(tf),BoolYN(retested),BoolYN(invalidated),e.qualityScore);
}

void BuildEventMemory(TFBrain &m15, EventMemoryRecord &sweepHigh, EventMemoryRecord &sweepLow, EventMemoryRecord &bosUp, EventMemoryRecord &bosDown, EventMemoryRecord &chochUp, EventMemoryRecord &chochDown, EventMemoryRecord &mssUp, EventMemoryRecord &mssDown, EventMemoryRecord &dispUp, EventMemoryRecord &dispDown)
{
   InitEventMemoryRecord(sweepHigh); InitEventMemoryRecord(sweepLow); InitEventMemoryRecord(bosUp); InitEventMemoryRecord(bosDown); InitEventMemoryRecord(chochUp); InitEventMemoryRecord(chochDown); InitEventMemoryRecord(mssUp); InitEventMemoryRecord(mssDown); InitEventMemoryRecord(dispUp); InitEventMemoryRecord(dispDown);
   MqlRates r[]; ArraySetAsSeries(r,true);
   int need=MathMax(InpEventMemoryBars+5,20);
   if(!CopyRatesSafe(InpETF,need,r)) return;
   double atr=MathMax(m15.atr,PointValue()*50);
   for(int i=1; i<=InpEventMemoryBars && i<ArraySize(r)-2; i++)
   {
      bool upDisp=(r[i].close>r[i].open && CandleBody(r[i])>=atr*InpDisplacementATR);
      bool dnDisp=(r[i].close<r[i].open && CandleBody(r[i])>=atr*InpDisplacementATR);
      bool sh=(m15.swings.validHigh && r[i].high>m15.swings.lastHigh && r[i].close < m15.swings.lastHigh-atr*InpSweepCloseBackATR);
      bool sl=(m15.swings.validLow && r[i].low<m15.swings.lastLow && r[i].close > m15.swings.lastLow+atr*InpSweepCloseBackATR);
      bool bu=(m15.swings.validHigh && r[i].close>m15.swings.lastHigh);
      bool bd=(m15.swings.validLow && r[i].close<m15.swings.lastLow);
      if(upDisp && !dispUp.valid) SetMemoryEvent(dispUp,"DISPLACEMENT_UP",1,r[i].close,r[i].low,i,InpETF,false,(m15.chochDown||m15.mssDown),24);
      if(dnDisp && !dispDown.valid) SetMemoryEvent(dispDown,"DISPLACEMENT_DOWN",-1,r[i].close,r[i].high,i,InpETF,false,(m15.chochUp||m15.mssUp),24);
      if(sl && !sweepLow.valid) SetMemoryEvent(sweepLow,"SWEEP_LOW",1,m15.swings.lastLow,r[i].low,i,InpETF,(CurrentMid()>=m15.swings.lastLow),false,26);
      if(sh && !sweepHigh.valid) SetMemoryEvent(sweepHigh,"SWEEP_HIGH",-1,m15.swings.lastHigh,r[i].high,i,InpETF,(CurrentMid()<=m15.swings.lastHigh),false,26);
      if(bu && !bosUp.valid) SetMemoryEvent(bosUp,"BOS_UP",1,m15.swings.lastHigh,r[i].low,i,InpETF,(MathAbs(CurrentMid()-m15.swings.lastHigh)<=atr*InpOBRetestATR),(m15.chochDown||m15.mssDown),28);
      if(bd && !bosDown.valid) SetMemoryEvent(bosDown,"BOS_DOWN",-1,m15.swings.lastLow,r[i].high,i,InpETF,(MathAbs(CurrentMid()-m15.swings.lastLow)<=atr*InpOBRetestATR),(m15.chochUp||m15.mssUp),28);
      if(bu && m15.structureBias<0 && !chochUp.valid) SetMemoryEvent(chochUp,"CHOCH_UP",1,m15.swings.lastHigh,r[i].low,i,InpETF,false,(m15.chochDown||m15.mssDown),30);
      if(bd && m15.structureBias>0 && !chochDown.valid) SetMemoryEvent(chochDown,"CHOCH_DOWN",-1,m15.swings.lastLow,r[i].high,i,InpETF,false,(m15.chochUp||m15.mssUp),30);
      if(sl && upDisp && bu && !mssUp.valid) SetMemoryEvent(mssUp,"MSS_UP",1,m15.swings.lastHigh,r[i].low,i,InpETF,false,(m15.chochDown||m15.mssDown),34);
      if(sh && dnDisp && bd && !mssDown.valid) SetMemoryEvent(mssDown,"MSS_DOWN",-1,m15.swings.lastLow,r[i].high,i,InpETF,false,(m15.chochUp||m15.mssUp),34);
   }
}

bool HasFreshTrigger(int dir, TFBrain &m15, string &triggerType, int &quality)
{
   triggerType=""; quality=0;
   MqlRates r[]; ArraySetAsSeries(r,true);
   if(!CopyRatesSafe(InpETF,MathMax(InpEntryTriggerBars+3,6),r)) return false;
   double atr=MathMax(m15.atr,PointValue()*50);
   for(int i=1; i<=InpEntryTriggerBars && i<ArraySize(r); i++)
   {
      double body=CandleBody(r[i]);
      double upper=r[i].high-MathMax(r[i].open,r[i].close);
      double lower=MathMin(r[i].open,r[i].close)-r[i].low;
      if(dir>0)
      {
         if(r[i].close>r[i].open && body>=atr*0.25) { triggerType="BULL_CONTINUATION_CANDLE"; quality=24+(InpEntryTriggerBars-i)*4; return true; }
         if(lower>body*1.4 && r[i].close>r[i].open) { triggerType="BULL_REJECTION_WICK"; quality=26+(InpEntryTriggerBars-i)*4; return true; }
         if(m15.swings.validHigh && r[i].close>m15.swings.lastHigh) { triggerType="BULL_RECLAIM_CLOSE"; quality=28+(InpEntryTriggerBars-i)*4; return true; }
      }
      else
      {
         if(r[i].close<r[i].open && body>=atr*0.25) { triggerType="BEAR_CONTINUATION_CANDLE"; quality=24+(InpEntryTriggerBars-i)*4; return true; }
         if(upper>body*1.4 && r[i].close<r[i].open) { triggerType="BEAR_REJECTION_WICK"; quality=26+(InpEntryTriggerBars-i)*4; return true; }
         if(m15.swings.validLow && r[i].close<m15.swings.lastLow) { triggerType="BEAR_RECLAIM_CLOSE"; quality=28+(InpEntryTriggerBars-i)*4; return true; }
      }
   }
   return false;
}

bool ZoneTradableForSetup(Zone &z, ENUM_SETUP_TYPE setupType, bool needsFresh, string &why)
{
   why="";
   if(!z.valid && z.blockReason!="") { why="Zone invalid: "+z.blockReason; return false; }
   if(z.invalidated) { why="Zone invalidated"; return false; }
   if(z.noisyWick) { why="Zone noisy wick"; return false; }
   if(z.tooWide && setupType==SETUP_REVERSAL_AFTER_SWEEP) { why="Reversal zone too wide"; return false; }
   if(z.mitigated && needsFresh) { why="Fresh zone required but zone fully mitigated"; return false; }
   if(z.tapCount>2 && setupType!=SETUP_TREND_CONTINUATION) { why="Zone over-tapped"; return false; }
   return (z.valid || (!needsFresh && !z.invalidated && !z.noisyWick));
}

bool DetectRetestForCandidate(int dir, ENUM_SETUP_TYPE setupType, MarketMap &map, TFBrain &h4, TFBrain &h1, TFBrain &m15, SetupCandidate &c)
{
   double price=CurrentMid();
   double atr=MathMax(m15.atr,PointValue()*50);
   Zone ob=(dir>0 ? m15.bullOB : m15.bearOB);
   Zone fvg=(dir>0 ? m15.bullFVG : m15.bearFVG);
   string why="";
   bool nearOB=(dir>0 ? m15.priceNearBullOB : m15.priceNearBearOB);
   bool refined=(dir>0 ? m15.priceInBullOBRefined : m15.priceInBearOBRefined);
   if(nearOB && ZoneTradableForSetup(ob,setupType,(setupType==SETUP_REVERSAL_AFTER_SWEEP),why) && (refined || setupType!=SETUP_REVERSAL_AFTER_SWEEP))
   { c.retestType=(refined?"OB_REFINED":"OB_REACTION"); c.entryLocationType="OB"; c.locationQuality=refined?30:22; c.invalidationLevel=ob.invalidationLevel; return true; }
   if(PriceNearZone(price,fvg,atr,InpFVGRetestATR) && ZoneTradableForSetup(fvg,setupType,false,why))
   { c.retestType="FVG_RETEST"; c.entryLocationType="FVG"; c.locationQuality=24; c.invalidationLevel=fvg.invalidationLevel; return true; }
   double level=(dir>0 ? map.supportLevel : map.resistanceLevel);
   if(level>0 && MathAbs(price-level)<=atr*InpOBRetestATR)
   { c.retestType="STRUCTURE_RETEST"; c.entryLocationType="SUPPORT_RESISTANCE_RETEST"; c.locationQuality=22; c.invalidationLevel=(dir>0 ? level-atr*0.55 : level+atr*0.55); return true; }
   double broken=(dir>0 ? m15.swings.lastHigh : m15.swings.lastLow);
   if(((dir>0 && broken>0 && price>=broken-atr*InpOBRetestATR && price<=broken+atr*InpOBRetestATR) || (dir<0 && broken>0 && price<=broken+atr*InpOBRetestATR && price>=broken-atr*InpOBRetestATR)))
   { c.retestType="BREAKOUT_RETEST"; c.entryLocationType=(dir>0?"STRUCTURE_HIGH_TURNED_SUPPORT":"STRUCTURE_LOW_TURNED_RESISTANCE"); c.locationQuality=24; c.invalidationLevel=(dir>0 ? broken-atr*0.60 : broken+atr*0.60); return true; }
   if(map.rangeDetected && map.rangeHigh>0 && map.rangeLow>0)
   {
      if(dir>0 && price<=map.rangeLow+atr*0.70) { c.retestType="RANGE_EDGE_RETEST"; c.entryLocationType="RANGE_LOW"; c.locationQuality=26; c.invalidationLevel=map.rangeLow-atr*0.45; return true; }
      if(dir<0 && price>=map.rangeHigh-atr*0.70) { c.retestType="RANGE_EDGE_RETEST"; c.entryLocationType="RANGE_HIGH"; c.locationQuality=26; c.invalidationLevel=map.rangeHigh+atr*0.45; return true; }
   }
   RejectionZone rz1=(dir>0 ? h1.bullRejectionZone : h1.bearRejectionZone);
   RejectionZone rz4=(dir>0 ? h4.bullRejectionZone : h4.bearRejectionZone);
   if(PriceNearRejectionZone(price,rz1,atr,InpOBRetestATR*1.6) || PriceNearRejectionZone(price,rz4,atr,InpOBRetestATR*1.9))
   {
      RejectionZone rz;
      if(PriceNearRejectionZone(price,rz1,atr,InpOBRetestATR*1.6)) rz=rz1; else rz=rz4;
      c.retestType=(dir>0?"BULLISH_REJECTION_ZONE_RETEST":"BEARISH_REJECTION_ZONE_RETEST");
      c.entryLocationType=(dir>0?"HTF_BULLISH_REJECTION_ZONE":"HTF_BEARISH_REJECTION_ZONE");
      c.locationQuality=26 + MathMin(10,rz.strength/12);
      c.invalidationLevel=rz.invalidationLevel;
      c.rejectionZoneEntryUsed=true;
      c.rejectionZoneContext=rz.audit;
      return true;
   }
   Zone htf=(dir>0 ? h1.bullOB : h1.bearOB);
   if(PriceNearZone(price,htf,atr,InpOBRetestATR*1.4) && ZoneTradableForSetup(htf,setupType,false,why))
   { c.retestType=(dir>0?"HTF_DEMAND_RETEST":"HTF_SUPPLY_RETEST"); c.entryLocationType="H1_ZONE_WITH_M15_TRIGGER"; c.locationQuality=23; c.invalidationLevel=htf.invalidationLevel; return true; }
   c.hardBlockReason="No logical entry location/retest";
   return false;
}

bool BuildCandidateRiskModel(int dir, MarketMap &map, TFBrain &h1, TFBrain &m15, SetupCandidate &c)
{
   double atr=MathMax(m15.atr,PointValue()*50);
   c.entry=(dir>0 ? CurrentAsk() : CurrentBid());
   double inv=c.invalidationLevel;
   if(inv<=0) inv=(dir>0 ? m15.swings.lastLow : m15.swings.lastHigh);
   if(dir>0)
   {
      if(inv<=0 || inv>=c.entry) { c.hardBlockReason="No logical BUY invalidation"; return false; }
      c.sl=NormalizePrice(inv-atr*InpSL_ATR_Buffer);
      c.targetLevel=0; c.targetSource="";
      if(map.buySideLiquidity>c.entry) { c.targetLevel=map.buySideLiquidity; c.targetSource="MAP_BUY_SIDE_LIQUIDITY"; }
      if(h1.swings.validHigh && h1.swings.lastHigh>c.entry && (c.targetLevel==0 || h1.swings.lastHigh<c.targetLevel)) { c.targetLevel=h1.swings.lastHigh; c.targetSource="H1_EXTERNAL_SWING"; }
      if(map.rangeDetected && map.rangeHigh>c.entry && (c.targetLevel==0 || map.rangeHigh<c.targetLevel)) { c.targetLevel=map.rangeHigh; c.targetSource="RANGE_HIGH"; }
      double minTarget=c.entry+(c.entry-c.sl)*MathMax(InpMinRRSoft,InpDefaultRR*0.70);
      if(c.targetLevel<=c.entry) { c.targetLevel=minTarget; c.targetSource="MIN_RR_FALLBACK"; }
      c.tp=NormalizePrice(c.targetLevel);
   }
   else
   {
      if(inv<=0 || inv<=c.entry) { c.hardBlockReason="No logical SELL invalidation"; return false; }
      c.sl=NormalizePrice(inv+atr*InpSL_ATR_Buffer);
      c.targetLevel=0; c.targetSource="";
      if(map.sellSideLiquidity>0 && map.sellSideLiquidity<c.entry) { c.targetLevel=map.sellSideLiquidity; c.targetSource="MAP_SELL_SIDE_LIQUIDITY"; }
      if(h1.swings.validLow && h1.swings.lastLow<c.entry && (c.targetLevel==0 || h1.swings.lastLow>c.targetLevel)) { c.targetLevel=h1.swings.lastLow; c.targetSource="H1_EXTERNAL_SWING"; }
      if(map.rangeDetected && map.rangeLow<c.entry && (c.targetLevel==0 || map.rangeLow>c.targetLevel)) { c.targetLevel=map.rangeLow; c.targetSource="RANGE_LOW"; }
      double minTarget=c.entry-(c.sl-c.entry)*MathMax(InpMinRRSoft,InpDefaultRR*0.70);
      if(c.targetLevel<=0 || c.targetLevel>=c.entry) { c.targetLevel=minTarget; c.targetSource="MIN_RR_FALLBACK"; }
      c.tp=NormalizePrice(c.targetLevel);
   }
   double risk=MathAbs(c.entry-c.sl), reward=MathAbs(c.tp-c.entry);
   if(risk<=PointValue()*5) { c.hardBlockReason="Risk distance invalid/tiny"; return false; }
   c.rr=reward/risk;
   if(c.rr<InpMinRRSoft) { c.hardBlockReason=StringFormat("RR %.2f below minimum %.2f",c.rr,InpMinRRSoft); return false; }
   string why=""; if(!StopsOK((dir>0?DECISION_BUY:DECISION_SELL),c.entry,c.sl,c.tp,why)) { c.hardBlockReason=why; return false; }
   c.targetQuality=(c.targetSource=="MIN_RR_FALLBACK" ? 12 : 24);
   return true;
}

bool OppositeConfirmedReversal(int dir, ENUM_BRAIN_STATE state, TFBrain &m15)
{
   if(dir>0) return (state==STATE_REVERSAL_CONFIRMED_BEAR || m15.chochDown || m15.mssDown);
   return (state==STATE_REVERSAL_CONFIRMED_BULL || m15.chochUp || m15.mssUp);
}

bool HardConflictForCandidate(int dir, ENUM_SETUP_TYPE setupType, TFBrain &h4, TFBrain &h1, TFBrain &m15, ENUM_BRAIN_STATE state, string &why)
{
   why="";
   if(OppositeConfirmedReversal(dir,state,m15)) { why="Active confirmed opposite reversal/CHOCH-MSS"; return true; }
   if(setupType==SETUP_REVERSAL_AFTER_SWEEP) return false;
   if(dir>0 && h4.finalBias<0 && h1.finalBias<0) { why="Severe bearish HTF conflict without reversal playbook"; return true; }
   if(dir<0 && h4.finalBias>0 && h1.finalBias>0) { why="Severe bullish HTF conflict without reversal playbook"; return true; }
   return false;
}

void FinalizeCandidateAudit(SetupCandidate &c)
{
   c.audit=StringFormat("%s %s score=%d pass=%s hard=%s hardReason=%s soft=%s entryLoc=%s retest=%s trigger=%s events=%s ages=%s entry=%.5f sl=%.5f tp=%.5f rr=%.2f target=%s %.5f late=%s locQ=%d tgtQ=%d rzEntry=%s rzAgainst=%s rzCtx=%s",
                        (c.direction>0?"BUY":"SELL"),SetupTypeToString(c.setupType),c.score,BoolYN(c.mandatoryPass),BoolYN(c.hardBlock),c.hardBlockReason,c.softMissingReasons,c.entryLocationType,c.retestType,c.triggerType,c.linkedEvents,c.eventAges,c.entry,c.sl,c.tp,c.rr,c.targetSource,c.targetLevel,c.lateEntryStatus,c.locationQuality,c.targetQuality,BoolYN(c.rejectionZoneEntryUsed),BoolYN(c.rejectionZoneAgainstTrade),c.rejectionZoneContext);
}

void ScoreCommonCandidate(SetupCandidate &c, int baseScore, TFBrain &h4, TFBrain &h1, TFBrain &m15, string triggerType, int triggerQuality)
{
   c.score=baseScore + c.locationQuality + c.targetQuality + triggerQuality;
   c.triggerType=triggerType;
   if(c.direction>0)
   {
      if(h4.finalBias>0) c.score+=10; else SoftAdd(c.softMissingReasons,"H4 not bullish");
      if(h1.finalBias>0) c.score+=10; else SoftAdd(c.softMissingReasons,"H1 not bullish");
      if(m15.inDiscount) c.score+=5; else SoftAdd(c.softMissingReasons,"Not ideal discount");
   }
   else
   {
      if(h4.finalBias<0) c.score+=10; else SoftAdd(c.softMissingReasons,"H4 not bearish");
      if(h1.finalBias<0) c.score+=10; else SoftAdd(c.softMissingReasons,"H1 not bearish");
      if(m15.inPremium) c.score+=5; else SoftAdd(c.softMissingReasons,"Not ideal premium");
   }
   if(c.rr>=InpDefaultRR) c.score+=8; else SoftAdd(c.softMissingReasons,"RR below default target but above minimum");
}

void AddCandidate(SetupCandidate &arr[], int &count, SetupCandidate &c)
{
   if(count>=10) return;
   arr[count]=c;
   count++;
}

void EvaluateTrendContinuationCandidate(int dir, TFBrain &h4, TFBrain &h1, TFBrain &m15, MarketMap &map, ENUM_BRAIN_STATE state, SetupCandidate &c)
{
   InitSetupCandidate(c,SETUP_TREND_CONTINUATION,dir);
   bool aligned=(dir>0 ? (h4.finalBias>0 && h1.finalBias>0) : (h4.finalBias<0 && h1.finalBias<0));
   string conflict=""; if(HardConflictForCandidate(dir,c.setupType,h4,h1,m15,state,conflict)) { c.hardBlock=true; c.hardBlockReason=conflict; FinalizeCandidateAudit(c); return; }
   string trig=""; int tq=0; bool trigger=HasFreshTrigger(dir,m15,trig,tq);
   if(!aligned) { c.hardBlock=true; c.hardBlockReason="TrendContinuation requires HTF/H1 alignment"; FinalizeCandidateAudit(c); return; }
   if(!DetectRetestForCandidate(dir,c.setupType,map,h4,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   if(!trigger) { c.hardBlock=true; c.hardBlockReason="No fresh continuation/rejection trigger"; FinalizeCandidateAudit(c); return; }
   double dist=(m15.atr>0?MathAbs(m15.close1-m15.emaFast)/m15.atr:0); c.lateEntryStatus=StringFormat("distEMA_ATR=%.2f",dist);
   if(dist>2.80 || m15.nearEquilibrium) { c.hardBlock=true; c.hardBlockReason="Late/no-man's-land trend entry"; FinalizeCandidateAudit(c); return; }
   if(!BuildCandidateRiskModel(dir,map,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   c.mandatoryPass=true; c.valid=true; c.linkedEvents="HTF_ALIGNMENT"; c.eventAges="trend_context";
   ScoreCommonCandidate(c,18,h4,h1,m15,trig,tq); FinalizeCandidateAudit(c);
}

void EvaluatePullbackContinuationCandidate(int dir, TFBrain &h4, TFBrain &h1, TFBrain &m15, MarketMap &map, ENUM_BRAIN_STATE state, SetupCandidate &c)
{
   InitSetupCandidate(c,SETUP_PULLBACK_CONTINUATION,dir);
   bool htfOk=(dir>0 ? h4.finalBias>0 : h4.finalBias<0);
   bool value=(dir>0 ? (m15.inDiscount || h1.inDiscount || m15.finalBias<0) : (m15.inPremium || h1.inPremium || m15.finalBias>0));
   string conflict=""; if(HardConflictForCandidate(dir,c.setupType,h4,h1,m15,state,conflict)) { c.hardBlock=true; c.hardBlockReason=conflict; FinalizeCandidateAudit(c); return; }
   string trig=""; int tq=0; bool trigger=HasFreshTrigger(dir,m15,trig,tq);
   if(!htfOk) { c.hardBlock=true; c.hardBlockReason="PullbackContinuation requires HTF trend still valid"; FinalizeCandidateAudit(c); return; }
   if(!value) { c.hardBlock=true; c.hardBlockReason="Pullback not in logical value area"; FinalizeCandidateAudit(c); return; }
   if(!DetectRetestForCandidate(dir,c.setupType,map,h4,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   if(!trigger) { c.hardBlock=true; c.hardBlockReason="No fresh pullback reaction trigger"; FinalizeCandidateAudit(c); return; }
   double dist=(m15.atr>0?MathAbs(m15.close1-m15.emaFast)/m15.atr:0); c.lateEntryStatus=StringFormat("distEMA_ATR=%.2f",dist);
   if(dist>3.20) { c.hardBlock=true; c.hardBlockReason="Pullback entry late after move"; FinalizeCandidateAudit(c); return; }
   if(!BuildCandidateRiskModel(dir,map,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   c.mandatoryPass=true; c.valid=true; c.linkedEvents="HTF_TREND_PULLBACK_VALUE"; c.eventAges="pullback_context";
   ScoreCommonCandidate(c,20,h4,h1,m15,trig,tq); FinalizeCandidateAudit(c);
}

void EvaluateBreakoutRetestCandidate(int dir, EventMemoryRecord &bos, EventMemoryRecord &disp, TFBrain &h4, TFBrain &h1, TFBrain &m15, MarketMap &map, ENUM_BRAIN_STATE state, SetupCandidate &c)
{
   InitSetupCandidate(c,SETUP_BREAKOUT_RETEST,dir);
   string conflict=""; if(HardConflictForCandidate(dir,c.setupType,h4,h1,m15,state,conflict)) { c.hardBlock=true; c.hardBlockReason=conflict; FinalizeCandidateAudit(c); return; }
   if(!bos.valid) { c.hardBlock=true; c.hardBlockReason="No recent BOS/breakout event in memory"; FinalizeCandidateAudit(c); return; }
   string trig=""; int tq=0; bool trigger=HasFreshTrigger(dir,m15,trig,tq);
   if(!DetectRetestForCandidate(dir,c.setupType,map,h4,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   if(c.retestType!="BREAKOUT_RETEST" && c.retestType!="STRUCTURE_RETEST") SoftAdd(c.softMissingReasons,"Retest is not pure breakout level");
   if(!trigger) { c.hardBlock=true; c.hardBlockReason="No fresh breakout-retest trigger"; FinalizeCandidateAudit(c); return; }
   if(!BuildCandidateRiskModel(dir,map,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   c.mandatoryPass=true; c.valid=true; c.linkedEvents=bos.audit+"; "+disp.audit; c.eventAges=StringFormat("BOS=%d/%s DISP=%d/%s",bos.age,EventAgeBucket(bos.age),disp.age,EventAgeBucket(disp.age));
   ScoreCommonCandidate(c,22+EventAgeScore(bos.age)/2,h4,h1,m15,trig,tq); FinalizeCandidateAudit(c);
}

void EvaluateReversalAfterSweepCandidate(int dir, EventMemoryRecord &sweep, EventMemoryRecord &bos, EventMemoryRecord &choch, EventMemoryRecord &mss, EventMemoryRecord &disp, TFBrain &h4, TFBrain &h1, TFBrain &m15, MarketMap &map, ENUM_BRAIN_STATE state, SetupCandidate &c)
{
   InitSetupCandidate(c,SETUP_REVERSAL_AFTER_SWEEP,dir);
   bool hasStructure=(bos.valid || choch.valid || mss.valid);
   string trig=""; int tq=0; bool trigger=HasFreshTrigger(dir,m15,trig,tq);
   if(!sweep.valid) { c.hardBlock=true; c.hardBlockReason="Reversal requires liquidity sweep"; FinalizeCandidateAudit(c); return; }
   if(!disp.valid) { c.hardBlock=true; c.hardBlockReason="Reversal requires displacement away from sweep"; FinalizeCandidateAudit(c); return; }
   if(!hasStructure) { c.hardBlock=true; c.hardBlockReason="Reversal requires BOS/CHOCH/MSS"; FinalizeCandidateAudit(c); return; }
   if(!DetectRetestForCandidate(dir,c.setupType,map,h4,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   if(!trigger) { c.hardBlock=true; c.hardBlockReason="Reversal requires fresh rejection/confirmation trigger"; FinalizeCandidateAudit(c); return; }
   if(!BuildCandidateRiskModel(dir,map,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   c.mandatoryPass=true; c.valid=true; c.linkedEvents=sweep.audit+"; "+disp.audit+"; "+(mss.valid?mss.audit:(choch.valid?choch.audit:bos.audit));
   c.eventAges=StringFormat("SWEEP=%d/%s DISP=%d/%s STRUCT=%d",sweep.age,EventAgeBucket(sweep.age),disp.age,EventAgeBucket(disp.age),(mss.valid?mss.age:(choch.valid?choch.age:bos.age)));
   ScoreCommonCandidate(c,26+EventAgeScore(sweep.age)/2,h4,h1,m15,trig,tq); FinalizeCandidateAudit(c);
}

void EvaluateRangeEdgeSweepCandidate(int dir, EventMemoryRecord &sweep, TFBrain &h4, TFBrain &h1, TFBrain &m15, MarketMap &map, ENUM_BRAIN_STATE state, SetupCandidate &c)
{
   InitSetupCandidate(c,SETUP_RANGE_EDGE_SWEEP,dir);
   if(!map.rangeDetected) { c.hardBlock=true; c.hardBlockReason="No range detected"; FinalizeCandidateAudit(c); return; }
   if(!sweep.valid) { c.hardBlock=true; c.hardBlockReason="Range edge setup requires sweep/failed breakout"; FinalizeCandidateAudit(c); return; }
   string trig=""; int tq=0; bool trigger=HasFreshTrigger(dir,m15,trig,tq);
   if(!DetectRetestForCandidate(dir,c.setupType,map,h4,h1,m15,c) || c.retestType!="RANGE_EDGE_RETEST") { c.hardBlock=true; if(c.hardBlockReason=="") c.hardBlockReason="Not at range edge"; FinalizeCandidateAudit(c); return; }
   if(!trigger) { c.hardBlock=true; c.hardBlockReason="No range-edge rejection trigger"; FinalizeCandidateAudit(c); return; }
   if(!BuildCandidateRiskModel(dir,map,h1,m15,c)) { c.hardBlock=true; FinalizeCandidateAudit(c); return; }
   c.mandatoryPass=true; c.valid=true; c.linkedEvents=sweep.audit; c.eventAges=StringFormat("SWEEP=%d/%s",sweep.age,EventAgeBucket(sweep.age));
   ScoreCommonCandidate(c,22+EventAgeScore(sweep.age)/2,h4,h1,m15,trig,tq); FinalizeCandidateAudit(c);
}

void GenerateSetupCandidates(TFBrain &h4, TFBrain &h1, TFBrain &m15, ENUM_BRAIN_STATE state, SetupCandidate &candidates[], int &count, MarketMap &map, string &audit)
{
   count=0; audit="";
   BuildMarketMap(h4,h1,m15,map);
   EventMemoryRecord sweepHigh,sweepLow,bosUp,bosDown,chochUp,chochDown,mssUp,mssDown,dispUp,dispDown;
   BuildEventMemory(m15,sweepHigh,sweepLow,bosUp,bosDown,chochUp,chochDown,mssUp,mssDown,dispUp,dispDown);
   SetupCandidate c;
   EvaluateTrendContinuationCandidate(1,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluatePullbackContinuationCandidate(1,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluateBreakoutRetestCandidate(1,bosUp,dispUp,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluateReversalAfterSweepCandidate(1,sweepLow,bosUp,chochUp,mssUp,dispUp,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluateRangeEdgeSweepCandidate(1,sweepLow,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluateTrendContinuationCandidate(-1,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluatePullbackContinuationCandidate(-1,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluateBreakoutRetestCandidate(-1,bosDown,dispDown,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluateReversalAfterSweepCandidate(-1,sweepHigh,bosDown,chochDown,mssDown,dispDown,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   EvaluateRangeEdgeSweepCandidate(-1,sweepHigh,h4,h1,m15,map,state,c); AddCandidate(candidates,count,c);
   audit=map.audit+" || EventMemory{"+sweepLow.audit+" | "+sweepHigh.audit+" | "+bosUp.audit+" | "+bosDown.audit+" | "+mssUp.audit+" | "+mssDown.audit+"}";
}

string RankSetupCandidates(SetupCandidate &candidates[], int count)
{
   string out="";
   for(int i=0;i<count;i++)
   {
      string row=StringFormat("#%d %s %s score=%d valid=%s pass=%s hard=%s hardReason=%s soft=%s",i,(candidates[i].direction>0?"BUY":"SELL"),SetupTypeToString(candidates[i].setupType),candidates[i].score,BoolYN(candidates[i].valid),BoolYN(candidates[i].mandatoryPass),BoolYN(candidates[i].hardBlock),candidates[i].hardBlockReason,candidates[i].softMissingReasons);
      SoftAdd(out,row);
   }
   return out;
}

bool SelectBestCandidate(SetupCandidate &candidates[], int count, SetupCandidate &best, SetupCandidate &opposite, string &why)
{
   InitSetupCandidate(best,SETUP_NO_TRADE,0); InitSetupCandidate(opposite,SETUP_NO_TRADE,0); why="";
   int bestIdx=-1, oppIdx=-1;
   for(int i=0;i<count;i++)
   {
      if(!candidates[i].valid || !candidates[i].mandatoryPass || candidates[i].hardBlock) continue;
      if(bestIdx<0 || candidates[i].score>candidates[bestIdx].score) bestIdx=i;
   }
   if(bestIdx<0) { why="No valid playbook candidate"; return false; }
   for(int j=0;j<count;j++)
   {
      if(j==bestIdx) continue;
      if(!candidates[j].valid || !candidates[j].mandatoryPass || candidates[j].hardBlock) continue;
      if(candidates[j].direction==-candidates[bestIdx].direction)
      {
         if(oppIdx<0 || candidates[j].score>candidates[oppIdx].score) oppIdx=j;
      }
   }
   best=candidates[bestIdx];
   if(oppIdx>=0) opposite=candidates[oppIdx];
   int threshold=(best.setupType==SETUP_REVERSAL_AFTER_SWEEP ? InpReversalMinScore : InpEntryMinScore);
   if(best.score<threshold) { why=StringFormat("Best candidate score %d below threshold %d",best.score,threshold); return false; }
   if(oppIdx>=0 && best.score<=candidates[oppIdx].score+InpCandidateSideSeparation)
   { why=StringFormat("Best candidate does not clearly beat opposite side: best=%d opposite=%d",best.score,candidates[oppIdx].score); return false; }
   return true;
}

void InitTradeQualityResult(TradeQualityResult &q)
{
   q.qualityScore=0; q.grade="D"; q.decision="WAIT"; q.rejectionZoneContext="";
   q.rejectionZoneEntryUsed=false; q.rejectionZoneAgainstTrade=false;
   q.qualityReasons=""; q.redFlags=""; q.confirmations="";
}

string QualityGradeFromScore(int score)
{
   if(score>=96) return "A+";
   if(score>=86) return "A";
   if(score>=74) return "B";
   if(score>=62) return "C";
   return "D";
}

bool StrongTextContains(string haystack, string needle)
{
   return (StringFind(haystack,needle)>=0);
}

void ApplyRejectionZoneContext(SetupCandidate &c, TFBrain &h4, TFBrain &h1, TFBrain &m15, string &confirmations, string &redFlags)
{
   double price=CurrentMid();
   double atr=MathMax(m15.atr,PointValue()*50);
   RejectionZone supportive1=(c.direction>0 ? h1.bullRejectionZone : h1.bearRejectionZone);
   RejectionZone supportive4=(c.direction>0 ? h4.bullRejectionZone : h4.bearRejectionZone);
   RejectionZone opposite1=(c.direction>0 ? h1.bearRejectionZone : h1.bullRejectionZone);
   RejectionZone opposite4=(c.direction>0 ? h4.bearRejectionZone : h4.bullRejectionZone);

   if(c.rejectionZoneEntryUsed)
   {
      SoftAdd(confirmations,"rejection-zone-entry");
   }
   else if(PriceNearRejectionZone(price,supportive1,atr,InpOBRetestATR*1.8) || PriceNearRejectionZone(price,supportive4,atr,InpOBRetestATR*2.2))
   {
      RejectionZone rz; if(PriceNearRejectionZone(price,supportive1,atr,InpOBRetestATR*1.8)) rz=supportive1; else rz=supportive4;
      c.rejectionZoneEntryUsed=true;
      c.rejectionZoneContext=rz.audit;
      c.score += MathMin(12,MathMax(4,rz.strength/10));
      SoftAdd(confirmations,"supportive-rejection-zone");
   }

   bool oppositeNear=false;
   RejectionZone danger;
   if(PriceNearRejectionZone(price,opposite1,atr,InpOBRetestATR*2.0)) { oppositeNear=true; danger=opposite1; }
   else if(PriceNearRejectionZone(price,opposite4,atr,InpOBRetestATR*2.5)) { oppositeNear=true; danger=opposite4; }
   if(oppositeNear)
   {
      c.rejectionZoneAgainstTrade=true;
      SoftAdd(redFlags,"nearby-opposite-rejection-zone");
      if(c.rejectionZoneContext=="") c.rejectionZoneContext=danger.audit;
      else c.rejectionZoneContext=c.rejectionZoneContext+" AGAINST{"+danger.audit+"}";
   }
}

bool JudgeTradeQuality(SetupCandidate &c, TFBrain &h4, TFBrain &h1, TFBrain &m15, TradeQualityResult &q)
{
   InitTradeQualityResult(q);
   string red="";
   string conf="";
   ApplyRejectionZoneContext(c,h4,h1,m15,conf,red);

   if(c.targetSource=="MIN_RR_FALLBACK") SoftAdd(red,"MIN_RR_FALLBACK-target");
   if(c.targetQuality<=12) SoftAdd(red,"weak-or-fallback-target-quality");
   if(c.direction>0 && (m15.inPremium || h1.inPremium)) SoftAdd(red,"BUY-from-premium/not-ideal-location");
   if(c.direction<0 && (m15.inDiscount || h1.inDiscount)) SoftAdd(red,"SELL-from-discount/not-ideal-location");
   if(StringFind(c.triggerType,"CONTINUATION_CANDLE")>=0 && StringFind(c.triggerType,"RECLAIM")<0) SoftAdd(red,"plain-continuation-trigger-not-rejection-reclaim");
   bool hasFreshEvent=(StringFind(c.linkedEvents,"BOS")>=0 || StringFind(c.linkedEvents,"SWEEP")>=0 || StringFind(c.linkedEvents,"MSS")>=0 || StringFind(c.linkedEvents,"CHOCH")>=0 || StringFind(c.linkedEvents,"DISPLACEMENT")>=0 || StringFind(c.triggerType,"RECLAIM")>=0);
   if(!hasFreshEvent) SoftAdd(red,"no-fresh-sweep-BOS-reclaim-displacement");
   if(c.direction>0 && (h4.finalBias<0 || h1.finalBias<0)) SoftAdd(red,"HTF-pressure-against-BUY");
   if(c.direction<0 && (h4.finalBias>0 || h1.finalBias>0)) SoftAdd(red,"HTF-pressure-against-SELL");
   if(c.setupType==SETUP_BREAKOUT_RETEST && c.retestType!="BREAKOUT_RETEST" && c.retestType!="STRUCTURE_RETEST") SoftAdd(red,"breakout-retest-not-on-clean-structure-level");

   if(c.targetSource!="MIN_RR_FALLBACK") SoftAdd(conf,"clear-liquidity-or-structure-target");
   if(c.rr>=InpDefaultRR) SoftAdd(conf,"clean-RR");
   if(StringFind(c.triggerType,"REJECTION")>=0) SoftAdd(conf,"M15-rejection-wick");
   if(StringFind(c.triggerType,"RECLAIM")>=0) SoftAdd(conf,"reclaim-close");
   if(hasFreshEvent) SoftAdd(conf,"fresh-structure-event");
   if(c.direction>0 && !m15.chochDown && !m15.mssDown) SoftAdd(conf,"no-opposite-M15-CHOCH-MSS");
   if(c.direction<0 && !m15.chochUp && !m15.mssUp) SoftAdd(conf,"no-opposite-M15-CHOCH-MSS");
   if(c.rejectionZoneEntryUsed) SoftAdd(conf,"rejection-zone-support");

   int reds=0, cons=0;
   if(red!="") { reds=1; for(int i=0;i<StringLen(red);i++) if(StringSubstr(red,i,1)=="|") reds++; }
   if(conf!="") { cons=1; for(int j=0;j<StringLen(conf);j++) if(StringSubstr(conf,j,1)=="|") cons++; }

   q.qualityScore = c.score + cons*5 - reds*8;
   q.grade = QualityGradeFromScore(q.qualityScore);
   q.redFlags=red;
   q.confirmations=conf;
   q.rejectionZoneEntryUsed=c.rejectionZoneEntryUsed;
   q.rejectionZoneAgainstTrade=c.rejectionZoneAgainstTrade;
   q.rejectionZoneContext=c.rejectionZoneContext;

   bool strongEnough=(c.score>=InpEntryMinScore+12 || q.qualityScore>=82 || cons>=4);
   bool breakoutWeak=(c.setupType==SETUP_BREAKOUT_RETEST && reds>=3 && cons<3);
   bool manyRedFlags=(reds>=4 && !strongEnough);
   bool mediumRisk=(reds>=2 && q.qualityScore<74);

   if(breakoutWeak || manyRedFlags)
   {
      q.decision="BLOCK";
      q.qualityReasons=StringFormat("blocked by quality judge: reds=%d confirmations=%d score=%d grade=%s",reds,cons,q.qualityScore,q.grade);
      return false;
   }
   if(mediumRisk)
   {
      q.decision="WAIT";
      q.qualityReasons=StringFormat("quality wait: combined red flags with insufficient confirmation reds=%d confirmations=%d score=%d grade=%s",reds,cons,q.qualityScore,q.grade);
      return false;
   }
   if(reds>=2)
   {
      q.decision="DOWNGRADE";
      q.qualityReasons=StringFormat("allowed with downgrade: reds=%d confirmations=%d score=%d grade=%s",reds,cons,q.qualityScore,q.grade);
      return true;
   }
   q.decision="PASS";
   q.qualityReasons=StringFormat("quality pass: reds=%d confirmations=%d score=%d grade=%s",reds,cons,q.qualityScore,q.grade);
   return true;
}

void BuildDecisionFromCandidate(SetupCandidate &best, BrainDecision &d)
{
   d.decision=(best.direction>0 ? DECISION_BUY : DECISION_SELL);
   d.entry=best.entry; d.sl=best.sl; d.tp=best.tp;
   d.entryModel=best.audit;
   d.selectedSetupType=SetupTypeToString(best.setupType);
   SoftAdd(d.reason,StringFormat("Selected %s %s score=%d RR=%.2f retest=%s trigger=%s target=%s",best.direction>0?"BUY":"SELL",d.selectedSetupType,best.score,best.rr,best.retestType,best.triggerType,best.targetSource));
}

void BuildDecision(TFBrain &h4, TFBrain &h1, TFBrain &m15, BrainDecision &d)
{
   d.decision=DECISION_WAIT;
   d.state=DetectMarketState(h4,h1,m15);
   d.buyScore=0; d.sellScore=0;
   d.blockBuy=false; d.blockSell=false;
   d.reason="";
   d.waitReason="";
   d.audit="";
   d.obAudit="";
   d.reversalAudit="";
   d.entryModel="";
   d.sessionName=SessionName(CurrentSession());
   d.setupKey="";
   d.learningBias=0;
   d.sl=0; d.tp=0; d.lot=NormalizeLot(FixedLotBySymbol()); d.entry=CurrentMid();
   d.bid=CurrentBid(); d.ask=CurrentAsk(); d.spread=d.ask-d.bid; d.decisionTF=TFToString(InpETF);
   d.buyEntryAudit=""; d.sellEntryAudit=""; d.selectedSetupType="NoTrade"; d.candidateRanking=""; d.candidateAudit="";
   d.qualityGrade=""; d.qualityScore=0; d.qualityDecision=""; d.rejectionZoneContext=""; d.rejectionZoneEntryUsed="false"; d.rejectionZoneAgainstTrade="false"; d.qualityReasons=""; d.redFlags=""; d.confirmations="";

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

   // Entry Brain v2: generate scenario-specific playbook candidates instead of forcing one rigid checklist.
   SetupCandidate candidates[10];
   int candidateCount=0;
   MarketMap marketMap;
   string generationAudit="";
   GenerateSetupCandidates(h4,h1,m15,d.state,candidates,candidateCount,marketMap,generationAudit);
   d.candidateRanking = RankSetupCandidates(candidates,candidateCount);
   d.candidateAudit = generationAudit;
   d.obAudit = "H4_OB{" + h4.bullOB.audit + " || " + h4.bearOB.audit + "} H1_OB{" + h1.bullOB.audit + " || " + h1.bearOB.audit + "} M15_OB{" + m15.bullOB.audit + " || " + m15.bearOB.audit + "} FVG{" + m15.bullFVG.audit + " || " + m15.bearFVG.audit + "}";
   d.reversalAudit = StringFormat("State=%s M15Bull{%s} M15Bear{%s} H1Bull{%s} H1Bear{%s}",StateToString(d.state),m15.lastBullEvent.audit,m15.lastBearEvent.audit,h1.lastBullEvent.audit,h1.lastBearEvent.audit);

   SetupCandidate best, opposite;
   string selectWhy="";
   bool selected = SelectBestCandidate(candidates,candidateCount,best,opposite,selectWhy);

   if(selected && best.direction>0 && d.blockBuy) { selected=false; selectWhy="BUY candidate blocked by direction/reversal permission"; }
   if(selected && best.direction<0 && d.blockSell) { selected=false; selectWhy="SELL candidate blocked by direction/reversal permission"; }
   if(selected && best.direction>0 && !InpAllowBuy) { selected=false; selectWhy="BUY disabled by input"; }
   if(selected && best.direction<0 && !InpAllowSell) { selected=false; selectWhy="SELL disabled by input"; }

   d.bid=CurrentBid();
   d.ask=CurrentAsk();
   d.spread=d.ask-d.bid;
   d.decisionTF=TFToString(InpETF);

   // Keep legacy BUY/SELL entry audit columns useful by storing the best candidate per side.
   d.buyEntryAudit=""; d.sellEntryAudit="";
   for(int ci=0; ci<candidateCount; ci++)
   {
      if(candidates[ci].direction>0 && (d.buyEntryAudit=="" || candidates[ci].score>0)) d.buyEntryAudit=candidates[ci].audit;
      if(candidates[ci].direction<0 && (d.sellEntryAudit=="" || candidates[ci].score>0)) d.sellEntryAudit=candidates[ci].audit;
   }

   if(selected)
   {
      TradeQualityResult quality;
      bool qualityOK = JudgeTradeQuality(best,h4,h1,m15,quality);
      d.qualityGrade=quality.grade;
      d.qualityScore=quality.qualityScore;
      d.qualityDecision=quality.decision;
      d.rejectionZoneContext=quality.rejectionZoneContext;
      d.rejectionZoneEntryUsed=BoolYN(quality.rejectionZoneEntryUsed);
      d.rejectionZoneAgainstTrade=BoolYN(quality.rejectionZoneAgainstTrade);
      d.qualityReasons=quality.qualityReasons;
      d.redFlags=quality.redFlags;
      d.confirmations=quality.confirmations;

      if(!qualityOK)
      {
         selected=false;
         selectWhy=quality.qualityReasons+" redFlags={"+quality.redFlags+"} confirmations={"+quality.confirmations+"}";
      }
      else
      {
         // Blend scenario score into side score for transparent logs while the final gate remains candidate based.
         if(best.direction>0) d.buyScore += best.score;
         else d.sellScore += best.score;
         BuildDecisionFromCandidate(best,d);
         SoftAdd(d.reason,"QualityJudge="+quality.decision+" grade="+quality.grade+" qScore="+IntegerToString(quality.qualityScore));
      }
   }
   if(!selected)
   {
      d.decision=DECISION_WAIT;
      d.selectedSetupType="NoTrade";
      d.waitReason=selectWhy;
      if(selectWhy!="") SoftAdd(d.reason,"Entry Brain v2 WAIT: "+selectWhy);
   }

   d.audit = StringFormat("Bid=%.5f Ask=%.5f Spread=%.5f TF=%s selectedSetupType=%s quality=%s/%d/%s redFlags={%s} confirmations={%s} rejectionZoneContext={%s} H4[%s] H1[%s] M15[%s] %s Reversal{%s} CandidateRanking{%s} CandidateAudit{%s} OB_FVG_AUDIT=%s",
                          d.bid,d.ask,d.spread,d.decisionTF,d.selectedSetupType,d.qualityGrade,d.qualityScore,d.qualityDecision,d.redFlags,d.confirmations,d.rejectionZoneContext,h4.notes,h1.notes,m15.notes,generationAudit,d.reversalAudit,d.candidateRanking,d.candidateAudit,d.obAudit);

   if(d.decision==DECISION_WAIT)
   {
      if(d.reason=="") d.reason="No valid Entry Brain v2 playbook candidate";
      return;
   }

   SoftAdd(d.reason,"Entry Brain v2 scenario selected with SL/TP/RR prevalidated");
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
   if((dir==DECISION_BUY && (m15.chochDown || m15.mssDown)) || (dir==DECISION_SELL && (m15.chochUp || m15.mssUp)))
   {
      why="Active opposite M15 reversal warning blocks add-on";
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
      bool protectedPos = PositionProtected(ticket);
      if(direction==1 && type==POSITION_TYPE_BUY && protectedPos && (price-open)>=atr*InpAddOnMinProfitATR) ok=true;
      if(direction==-1 && type==POSITION_TYPE_SELL && protectedPos && (open-price)>=atr*InpAddOnMinProfitATR) ok=true;
   }
   if(!ok)
   {
      why="Existing same-direction trade is not both profitable and protected for smart add-on";
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
         SetCloseReasonOverride((long)PositionGetInteger(POSITION_IDENTIFIER),"REVERSAL_EXIT");
         AppendManagementAction((long)PositionGetInteger(POSITION_IDENTIFIER),"REVERSAL_EXIT opposite position close due "+StateToString(d.state));
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
         StorePositionContext(posid,d.setupKey,d.reason+" || "+d.audit);
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

int OppositeReversalScore(long positionType, TFBrain &h1, TFBrain &m15, string &reason)
{
   int score=0; reason="";
   if(positionType==POSITION_TYPE_BUY)
   {
      if(m15.chochDown) { score+=24; SoftAdd(reason,"M15 bearish CHOCH"); }
      if(m15.mssDown) { score+=28; SoftAdd(reason,"M15 bearish MSS"); }
      if(m15.bosDown) { score+=18; SoftAdd(reason,"M15 bearish BOS"); }
      if(m15.displacementDown) { score+=18; SoftAdd(reason,"M15 bearish displacement"); }
      if(m15.sweepHigh) { score+=10; SoftAdd(reason,"M15 buy-side sweep"); }
      if(h1.chochDown || h1.mssDown || h1.bosDown) { score+=18; SoftAdd(reason,"H1 bearish structure confirms"); }
      if(m15.priceNearBearOB || m15.priceNearBearFVG) { score+=8; SoftAdd(reason,"Bearish retest zone active"); }
   }
   else if(positionType==POSITION_TYPE_SELL)
   {
      if(m15.chochUp) { score+=24; SoftAdd(reason,"M15 bullish CHOCH"); }
      if(m15.mssUp) { score+=28; SoftAdd(reason,"M15 bullish MSS"); }
      if(m15.bosUp) { score+=18; SoftAdd(reason,"M15 bullish BOS"); }
      if(m15.displacementUp) { score+=18; SoftAdd(reason,"M15 bullish displacement"); }
      if(m15.sweepLow) { score+=10; SoftAdd(reason,"M15 sell-side sweep"); }
      if(h1.chochUp || h1.mssUp || h1.bosUp) { score+=18; SoftAdd(reason,"H1 bullish structure confirms"); }
      if(m15.priceNearBullOB || m15.priceNearBullFVG) { score+=8; SoftAdd(reason,"Bullish retest zone active"); }
   }
   return score;
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
   string modifyReason="";

   string reversalReason="";
   int reversalScore = OppositeReversalScore(type,h1,m15,reversalReason);
   bool protectedBefore = PositionProtected(ticket);
   bool strongOppositeReversal = (reversalScore>=58);
   if(strongOppositeReversal && !protectedBefore)
   {
      string action = "REVERSAL_EXIT Ticket="+IntegerToString((long)ticket)+StringFormat(" Score=%d Reason=%s",reversalScore,reversalReason);
      VPrint(action);
      AppendManagementAction((long)PositionGetInteger(POSITION_IDENTIFIER),action);
      SetCloseReasonOverride((long)PositionGetInteger(POSITION_IDENTIFIER),"REVERSAL_EXIT");
      if(trade.PositionClose(ticket))
         VPrint("POSITION CLOSED BY REVERSAL "+IntegerToString((long)ticket));
      else
         VPrint("REVERSAL EXIT FAILED "+IntegerToString((long)ticket)+" | "+trade.ResultRetcodeDescription());
      return;
   }

   // BreakEven
   if(InpUseBreakEven && rNow >= InpBreakEvenAtR)
   {
      if(type==POSITION_TYPE_BUY)
      {
         double be = NormalizePrice(open + atr*InpBreakEvenPlusATR);
         if(sl < be) { newSL=be; modify=true; SoftAdd(modifyReason,"BREAKEVEN"); }
      }
      else
      {
         double be = NormalizePrice(open - atr*InpBreakEvenPlusATR);
         if(sl==0 || sl > be) { newSL=be; modify=true; SoftAdd(modifyReason,"BREAKEVEN"); }
      }
   }

   // Profit Lock
   if(InpUseProfitLock && rNow >= InpProfitLockAtR)
   {
      if(type==POSITION_TYPE_BUY)
      {
         double lock = NormalizePrice(open + risk*InpProfitLockR);
         if(newSL < lock) { newSL=lock; modify=true; SoftAdd(modifyReason,"PROFIT_LOCK"); }
      }
      else
      {
         double lock = NormalizePrice(open - risk*InpProfitLockR);
         if(newSL==0 || newSL > lock) { newSL=lock; modify=true; SoftAdd(modifyReason,"PROFIT_LOCK"); }
      }
   }

   // ATR trailing after protected/profitable
   if(InpUseATRTrailing && rNow >= InpTrailStartR)
   {
      if(type==POSITION_TYPE_BUY)
      {
         double tr = NormalizePrice(price - atr*InpTrailATR);
         if(tr > newSL && tr < price) { newSL=tr; modify=true; SoftAdd(modifyReason,"ATR_TRAILING"); }
      }
      else
      {
         double tr = NormalizePrice(price + atr*InpTrailATR);
         if((newSL==0 || tr < newSL) && tr > price) { newSL=tr; modify=true; SoftAdd(modifyReason,"ATR_TRAILING"); }
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
               if(ext>newTP) { newTP=ext; modify=true; SoftAdd(modifyReason,"TP_EXTENSION"); }
            }
            else
            {
               double ext = NormalizePrice(tp - atr*InpRunnerExtendATR);
               if(newTP==0 || ext<newTP) { newTP=ext; modify=true; SoftAdd(modifyReason,"TP_EXTENSION"); }
            }
         }
      }
   }

   // Reversal protection for open positions: tighten/exit if confirmed opposite structure.
   if(type==POSITION_TYPE_BUY && (m15.chochDown || m15.mssDown) && m15.displacementDown)
   {
      double protective = NormalizePrice(price - atr*0.35);
      if(protective>newSL && protective<price) { newSL=protective; modify=true; SoftAdd(modifyReason,"REVERSAL_PROTECTION"); }
      string action = "BUY position "+IntegerToString((long)ticket)+StringFormat(" reversal protection: score=%d reason=%s protective SL tighten",reversalScore,reversalReason);
      VPrint(action);
      AppendManagementAction((long)PositionGetInteger(POSITION_IDENTIFIER),action);
   }
   if(type==POSITION_TYPE_SELL && (m15.chochUp || m15.mssUp) && m15.displacementUp)
   {
      double protective = NormalizePrice(price + atr*0.35);
      if((newSL==0 || protective<newSL) && protective>price) { newSL=protective; modify=true; SoftAdd(modifyReason,"REVERSAL_PROTECTION"); }
      string action = "SELL position "+IntegerToString((long)ticket)+StringFormat(" reversal protection: score=%d reason=%s protective SL tighten",reversalScore,reversalReason);
      VPrint(action);
      AppendManagementAction((long)PositionGetInteger(POSITION_IDENTIFIER),action);
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
         {
            VPrint("POSITION MODIFIED "+IntegerToString((long)ticket)+StringFormat(" | SL %.5f -> %.5f | TP %.5f -> %.5f | R=%.2f",sl,newSL,tp,newTP,rNow));
            AppendManagementAction((long)PositionGetInteger(POSITION_IDENTIFIER),StringFormat("%s MODIFY SL %.5f->%.5f TP %.5f->%.5f R=%.2f",modifyReason,sl,newSL,tp,newTP,rNow));
         }
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
      FileWrite(h,"time","symbol","class","timeframe","bid","ask","spread","session","setupKey","learningBias","state","decision","selectedSetupType","qualityGrade","qualityScore","qualityDecision","rejectionZoneContext","rejectionZoneEntryUsed","rejectionZoneAgainstTrade","qualityReasons","redFlags","confirmations","buyScore","sellScore","lot","entry","sl","tp","reason","waitBlockReason","entryModel","buyEntryAudit","sellEntryAudit","candidateRanking","candidateAudit","obFvgAudit","reversalAudit","fullAudit");
   }
   FileClose(h);

   int c = FileOpen(InpCloseAuditFileName, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(c!=INVALID_HANDLE)
   {
      if(FileSize(c)==0)
         FileWrite(c,"closeTime","symbol","positionId","deal","closePrice","profit","closeReason","setupKey","entryReason","managementActions","diagnosis");
      FileClose(c);
   }
}

void LogCSV(BrainDecision &d)
{
   if(!InpWriteCSVLog) return;
   int h = FileOpen(InpCSVFileName, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   FileSeek(h,0,SEEK_END);
   FileWrite(h,TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),_Symbol,SymbolClassName(SymbolClass()),d.decisionTF,DoubleToString(d.bid,_Digits),DoubleToString(d.ask,_Digits),DoubleToString(d.spread,_Digits),d.sessionName,d.setupKey,d.learningBias,StateToString(d.state),DecisionToString(d.decision),
             d.selectedSetupType,d.qualityGrade,d.qualityScore,d.qualityDecision,d.rejectionZoneContext,d.rejectionZoneEntryUsed,d.rejectionZoneAgainstTrade,d.qualityReasons,d.redFlags,d.confirmations,d.buyScore,d.sellScore,DoubleToString(d.lot,2),DoubleToString(d.entry,_Digits),DoubleToString(d.sl,_Digits),DoubleToString(d.tp,_Digits),d.reason,d.waitReason,d.entryModel,d.buyEntryAudit,d.sellEntryAudit,d.candidateRanking,d.candidateAudit,d.obAudit,d.reversalAudit,d.audit);
   FileClose(h);
}

string DealCloseReasonText(ulong deal)
{
   long reason = HistoryDealGetInteger(deal,DEAL_REASON);
   if(reason==DEAL_REASON_SL) return "SL";
   if(reason==DEAL_REASON_TP) return "TP";
   if(reason==DEAL_REASON_CLIENT) return "MANUAL_CLIENT";
   if(reason==DEAL_REASON_MOBILE) return "MANUAL_MOBILE";
   if(reason==DEAL_REASON_WEB) return "MANUAL_WEB";
   if(reason==DEAL_REASON_EXPERT) return "EXPERT";
   if(reason==DEAL_REASON_SO) return "STOP_OUT";
   return "UNKNOWN";
}

void LogCloseAudit(ulong deal, long posid, double closePrice, double profit)
{
   int h = FileOpen(InpCloseAuditFileName, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(h==INVALID_HANDLE) return;
   if(FileSize(h)==0)
      FileWrite(h,"closeTime","symbol","positionId","deal","closePrice","profit","closeReason","setupKey","entryReason","managementActions","diagnosis");
   FileSeek(h,0,SEEK_END);
   string key=KeyForPosition(posid);
   string entryReason=EntryReasonForPosition(posid);
   string actions=ManagementActionsForPosition(posid);
   string closeReason=DealCloseReasonText(deal);
   string overrideReason=CloseReasonOverrideForPosition(posid);
   if(overrideReason!="") closeReason=overrideReason;
   string diagnosis = StringFormat("Closed %s profit=%.2f; setupKey=%s; actions=%s",closeReason,profit,key,actions);
   FileWrite(h,TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),_Symbol,IntegerToString(posid),IntegerToString((long)deal),DoubleToString(closePrice,_Digits),DoubleToString(profit,2),closeReason,key,entryReason,actions,diagnosis);
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

void FailedXAUUSDDebugHarness(TFBrain &h4, TFBrain &h1, TFBrain &m15, BrainDecision &d)
{
   string sym=UpperSymbol();
   if(StringFind(sym,"XAU")<0 && StringFind(sym,"GOLD")<0) return;
   string expected = "Expected for failed 4082.6 class: WAIT unless BUY_MODEL storyComplete with valid refined bullish OB/FVG + sweep + displacement + BOS/MSS/CHOCH + RR; if BUY open and Bear Reversal Confirmed, protect/exit.";
   string report = "FAILED_XAUUSD_REGRESSION_DEBUG | State="+StateToString(d.state)+
                   " | Decision="+DecisionToString(d.decision)+
                   " | B/S="+IntegerToString(d.buyScore)+"/"+IntegerToString(d.sellScore)+
                   " | Expected="+expected+
                   " | H4="+h4.eventAudit+
                   " | H1="+h1.eventAudit+
                   " | M15="+m15.eventAudit+
                   " | Liquidity="+m15.liquidityAudit+
                   " | OB/FVG="+d.obAudit+
                   " | BuyVerdict="+d.buyEntryAudit+
                   " | SellVerdict="+d.sellEntryAudit+
                   " | Reversal="+d.reversalAudit+
                   " | Reason="+d.reason;
   VPrint(report);
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
   if(InpRunFailedXAUUSDDebugHarness) FailedXAUUSDDebugHarness(h4,h1,m15,d);

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
   double closePrice = HistoryDealGetDouble(deal,DEAL_PRICE);
   LogCloseAudit(deal,posid,closePrice,profit);
   string key = KeyForPosition(posid);
   if(!InpUseLearningLayer)
   {
      RemovePositionKey(posid);
      VPrint(StringFormat("CLOSE AUDIT | PositionID=%d | Key=%s | Profit=%.2f",posid,key,profit));
      return;
   }
   bool win = (profit>=0.0);
   AddOrUpdateLearning(key,win,profit);
   SaveLearningStats();
   RemovePositionKey(posid);
   VPrint(StringFormat("LEARNING UPDATE | PositionID=%d | Key=%s | Profit=%.2f | Result=%s",posid,key,profit,win?"WIN":"LOSS"));
}
//+------------------------------------------------------------------+
