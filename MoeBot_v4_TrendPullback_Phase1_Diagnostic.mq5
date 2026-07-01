//+------------------------------------------------------------------+
//| MoeBot_v4_TrendPullback_Phase1_Diagnostic.mq5                    |
//| Phase 3 minimal primary execution; diagnostics retained.          |
//+------------------------------------------------------------------+
#property strict
#property version   "4.31"
#property description "MoeBot v4 Trend Pullback Phase 3 minimal primary execution with diagnostics retained."
#property description "Phase 3.1 signal availability diagnostics; no strategy or execution changes."
#property description "Phase 2.2 transition diagnostics are retained; no position management is included."

#include <Trade/Trade.mqh>

//--- Bot operating modes.
enum BotMode
{
   Conservative = 0,
   Growth       = 1
};

//--- Supported asset classes.
enum AssetClass
{
   FOREX   = 0,
   GOLD    = 1,
   SILVER  = 2,
   OIL     = 3,
   INDEX   = 4,
   UNKNOWN = 5
};

//--- Higher-timeframe directional bias.
enum H4Bias
{
   Bullish = 0,
   Bearish = 1,
   Flat    = 2,
   Unknown = 3
};

//--- EA state machine states. Phase 2.1 uses these as analysis states only.
enum EAState
{
   IDLE = 0,
   BIAS_ACTIVE,
   ZONE_VALID,
   TRIGGER_PENDING,
   ENTERED,
   MANAGING,
   ADDON_ELIGIBLE,
   CLOSED,
   ZONE_EXPIRED,
   ZONE_INVALIDATED
};

//--- Inputs.
input long    MagicNumber              = 404001;
input bool    EnableDebug              = true;
input BotMode Mode                     = Conservative;
input bool    EnableTrading            = false;

input double  ForexLot                 = 0.02;
input double  GoldLot                  = 0.01;
input double  SilverLot                = 0.01;
input double  OilLot                   = 0.01;
input double  IndexLot                 = 0.01;

input int     ForexMaxSpreadPoints     = 25;
input int     GoldMaxSpreadPoints      = 180;
input int     SilverMaxSpreadPoints    = 300;
input int     OilMaxSpreadPoints       = 80;
input int     IndexMaxSpreadPoints     = 300;

input int     TradeDeviationForexPoints  = 15;
input int     TradeDeviationGoldPoints   = 30;
input int     TradeDeviationSilverPoints = 30;
input int     TradeDeviationOilPoints    = 50;
input int     TradeDeviationIndexPoints  = 50;

input int     H4_EMA_Period            = 50;
input int     H1_EMA_Period            = 20;
input int     ATR_Period               = 14;
input int     H4_Slope_Lookback        = 6;
input int     M15_BOS_Lookback         = 5;

input int     ConservativeThreshold    = 75;
input int     GrowthThreshold          = 60;
input int     MaxAddOns                = 1;
input bool    UseManualNewsBlackout    = false;

input bool    EnableTransitionDiagnostics = true;
input int     TransitionH1Lookback        = 10;
input int     TransitionM15Lookback       = 5;
input double  TransitionMinH1BreakATR     = 0.10;
input double  TransitionFailureBufferATR  = 0.20;
input int     TransitionExpiryH1Bars      = 8;

//--- Strategy constants for Phase 2.1 diagnostics.
#define H1_ZONE_LOOKBACK_BARS 20
#define H1_ZONE_MAX_AGE_BARS 40

//--- Asset-specific parameters loaded from the detected symbol class.
struct AssetParams
{
   AssetClass assetClass;
   double     fixedLot;
   int        maxSpreadPoints;
   double     atrBuffer;
   double     minRR;
};

//--- Snapshot used for logging and chart diagnostics.
struct DiagnosticStatus
{
   string     symbol;
   AssetClass assetClass;
   EAState    state;
   int        currentSpreadPoints;
   double     selectedLot;
   bool       brokerBlockerActive;
   string     brokerBlockerReason;
   datetime   lastM15BarTime;
   string     debugText;
};

//--- H4 bias diagnostic details.
struct H4BiasInfo
{
   H4Bias bias;
   double emaNow;
   double emaPast;
   double atrH4;
   double slopeRatio;
   double distanceFromEmaATR;
   int    crossCount;
   string reason;
};

//--- H1 pullback zone diagnostic details.
struct H1ZoneInfo
{
   bool     valid;
   string   source;
   double   center;
   double   upper;
   double   lower;
   double   atrH1;
   datetime anchorTime;
   int      ageBars;
   int      touchCount;
   bool     invalidated;
   string   reason;
   double   swingHigh;
   double   swingLow;
};

//--- M15 BOS trigger diagnostic details.
struct M15TriggerInfo
{
   bool   bos;
   string direction;
   double priorHigh;
   double priorLow;
   double triggerOpen;
   double triggerHigh;
   double triggerLow;
   double triggerClose;
   double triggerBodyRatio;
   double bosBreakDistanceATR;
   double atrM15;
   bool   insideZone;
   bool   nearMiss;
   bool   tooLate;
   string reason;
};

//--- Final Phase 2.1 signal candidate diagnostic details.
struct SignalCandidate
{
   bool   hardGatesPassed;
   bool   candidate;
   string direction;
   int    score;
   int    warningCount;
   int    threshold;

   int    scoreBase;
   int    scoreBosStrength;
   int    scoreH4TrendQuality;
   int    scoreH4EmaDistance;
   int    scoreH1ZoneSource;
   int    scoreH1ZoneFreshness;
   int    scoreM15CandleBody;
   int    scoreTriggerLocation;
   int    scoreTotal;

   double bosBreakDistanceATR;
   double triggerBodyRatio;

   bool   warningZoneTouch2Or3;
   bool   warningNearMissTrigger;
   bool   warningLowLiquidity;
   bool   warningNewsBlackout;

   bool   decisionGrowthEligible;
   bool   decisionConservativeEligible;
   string decisionLabel;

   string decision;
   string reason;
};

//--- Phase 3.1 signal availability diagnostic details.
struct SignalAvailabilityDiagnostics
{
   bool   enabled;
   int    missingGatesCount;
   string primaryBlocker;
   string secondaryBlocker;
   string nearestSetupStatus;

   bool   h4Ready;
   bool   h1ZoneReady;
   bool   m15TriggerReady;
   bool   scoreReady;
   bool   warningsReady;

   string h4ReadinessReason;
   string h1ReadinessReason;
   string m15ReadinessReason;
   string scoreReadinessReason;
   string warningReadinessReason;

   int    currentScore;
   int    requiredScore;
   int    warningCount;
   int    maxAllowedWarnings;

   double m15BosBreakDistanceATR;
   double triggerDistanceFromZoneATR;
   double triggerBodyRatio;
   double h1ZoneAgeBars;
   int    h1TouchCount;

   string wouldHaveBeenCandidateIf;
   string nearestSetupDirection;
};

//--- Phase 3.1 early transition diagnostic details.
struct EarlyTransitionDiagnostics
{
   bool   enabled;
   bool   earlyTransitionWarning;
   int    transitionStrengthScore;
   string transitionMissingPiece;
   string transitionRiskLabel;

   bool   h4Exhaustion;
   bool   h1OppositeBos;
   bool   m15OppositeBos;
   bool   h1BosDistanceEnough;

   double h1BosDistanceATR;
   double requiredH1BosDistanceATR;
   double m15OppositeBreakDistanceATR;

   string oldDirectionRisk;
   string reason;
};

//--- Phase 3 execution diagnostic details.
struct ExecutionDiagnostics
{
   bool     enableTrading;
   bool     hasOpenPositionSymbolMagic;
   datetime executionBarTime;
   bool     executionAllowed;
   bool     executionAttempted;
   string   executionResult;
   string   executionReason;
   uint     executionRetcode;
   string   executionRetcodeDescription;
   double   entryPrice;
   double   slPrice;
   double   tpPrice;
   double   riskPoints;
   double   rr;
   double   lotRequested;
   double   lotNormalized;
   int      freshSpreadPoints;
   double   marginRequired;
   double   freeMargin;
};

//--- Phase 2.2 transition / simulated standby diagnostic details.
struct TransitionDiagnostics
{
   bool     enabled;

   bool     h4Directional;
   string   h4Direction;

   bool     h4Exhaustion;
   bool     h4SlopeWeakening;
   bool     h4FailedToExtend;
   double   h4SlopeRatio;

   bool     h1OppositeBOS;
   string   transitionDirection;
   double   h1BosLevel;
   double   h1BosDistanceATR;
   double   h1TriggerClose;
   double   h1Atr;

   bool     m15OppositeBOS;
   double   m15OppositeBreakDistanceATR;

   bool     transitionWarning;
   bool     standbyRecommended;

   bool     simulatedStandbyActive;
   string   simulatedStandbyDirection;
   datetime simulatedStandbyStartTime;
   int      simulatedStandbyAgeH1Bars;

   bool     wouldSuppressOldDirection;
   bool     wouldAllowNewDirection;

   bool     exitByH4Flip;
   bool     exitByTransitionFailure;
   bool     exitByExpiry;
   string   exitReason;

   string   reason;
};

//--- Global runtime state.
CTrade           trade;

AssetParams      g_assetParams;
DiagnosticStatus g_status;
H4BiasInfo       g_h4Info;
H1ZoneInfo       g_h1Info;
M15TriggerInfo   g_m15Info;
SignalCandidate  g_signal;
TransitionDiagnostics g_transition;
SignalAvailabilityDiagnostics g_availability;
EarlyTransitionDiagnostics g_earlyTransition;
ExecutionDiagnostics g_execution;
EAState          g_state          = IDLE;
datetime         g_lastM15BarTime = 0;
H4Bias           g_previousDirectionalBias = Unknown;
bool             g_simulatedStandbyActive = false;
string           g_simulatedStandbyDirection = "NONE";
H4Bias           g_simulatedStandbyOriginalH4Bias = Unknown;
datetime         g_simulatedStandbyStartTime = 0;
double           g_simulatedStandbyBosLevel = 0.0;
datetime         g_lastExecutionBarTime = 0;

//--- Indicator handles used only for analysis diagnostics.
int g_h4EmaHandle  = INVALID_HANDLE;
int g_h1EmaHandle  = INVALID_HANDLE;
int g_h4AtrHandle  = INVALID_HANDLE;
int g_h1AtrHandle  = INVALID_HANDLE;
int g_m15AtrHandle = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   SetState(IDLE);

   g_assetParams = LoadAssetParams(DetectAssetClass(_Symbol));
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(TradeDeviationForAsset(g_assetParams.assetClass));
   ResetAnalysisDiagnostics("Initialized");
   ResetExecutionDiagnostics("Initialized");

   g_status.symbol              = _Symbol;
   g_status.assetClass          = g_assetParams.assetClass;
   g_status.state               = g_state;
   g_status.currentSpreadPoints = GetCurrentSpreadPoints();
   g_status.selectedLot         = NormalizeLotToStep(g_assetParams.fixedLot);
   g_status.brokerBlockerActive = false;
   g_status.brokerBlockerReason = "Not checked yet";
   g_status.lastM15BarTime      = 0;
   g_status.debugText           = "Initialized";

   if(g_assetParams.assetClass == UNKNOWN)
      Print("[MoeBot v4 Phase3] WARNING: Unknown asset class for ", _Symbol, "; using Forex defaults.");

   if(!CreateIndicatorHandles())
      Print("[MoeBot v4 Phase3] WARNING: One or more indicator handles could not be created; analysis will fail gracefully until available.");

   if(EnableDebug)
      Print("[MoeBot v4 Phase3] Initialized on current chart symbol only: ", _Symbol);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ReleaseIndicatorHandles();
   Comment("");
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!IsNewM15Bar())
      return;

   UpdateDiagnosticStatus();

   if(EnableDebug)
      Print(g_status.debugText);

   Comment(g_status.debugText);
}

//+------------------------------------------------------------------+
//| Creates analysis indicator handles.                               |
//+------------------------------------------------------------------+
bool CreateIndicatorHandles()
{
   bool success = true;

   g_h4EmaHandle  = iMA(_Symbol, PERIOD_H4, H4_EMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   g_h1EmaHandle  = iMA(_Symbol, PERIOD_H1, H1_EMA_Period, 0, MODE_EMA, PRICE_CLOSE);
   g_h4AtrHandle  = iATR(_Symbol, PERIOD_H4, ATR_Period);
   g_h1AtrHandle  = iATR(_Symbol, PERIOD_H1, ATR_Period);
   g_m15AtrHandle = iATR(_Symbol, PERIOD_M15, ATR_Period);

   if(g_h4EmaHandle == INVALID_HANDLE || g_h1EmaHandle == INVALID_HANDLE ||
      g_h4AtrHandle == INVALID_HANDLE || g_h1AtrHandle == INVALID_HANDLE ||
      g_m15AtrHandle == INVALID_HANDLE)
      success = false;

   return(success);
}

//+------------------------------------------------------------------+
//| Releases analysis indicator handles.                              |
//+------------------------------------------------------------------+
void ReleaseIndicatorHandles()
{
   if(g_h4EmaHandle != INVALID_HANDLE)
   {
      IndicatorRelease(g_h4EmaHandle);
      g_h4EmaHandle = INVALID_HANDLE;
   }

   if(g_h1EmaHandle != INVALID_HANDLE)
   {
      IndicatorRelease(g_h1EmaHandle);
      g_h1EmaHandle = INVALID_HANDLE;
   }

   if(g_h4AtrHandle != INVALID_HANDLE)
   {
      IndicatorRelease(g_h4AtrHandle);
      g_h4AtrHandle = INVALID_HANDLE;
   }

   if(g_h1AtrHandle != INVALID_HANDLE)
   {
      IndicatorRelease(g_h1AtrHandle);
      g_h1AtrHandle = INVALID_HANDLE;
   }

   if(g_m15AtrHandle != INVALID_HANDLE)
   {
      IndicatorRelease(g_m15AtrHandle);
      g_m15AtrHandle = INVALID_HANDLE;
   }
}

//+------------------------------------------------------------------+
//| Detects whether a new M15 candle has opened.                      |
//+------------------------------------------------------------------+
bool IsNewM15Bar()
{
   datetime currentBarTime = iTime(_Symbol, PERIOD_M15, 0);
   if(currentBarTime <= 0)
      return(false);

   if(currentBarTime == g_lastM15BarTime)
      return(false);

   g_lastM15BarTime = currentBarTime;
   return(true);
}

//+------------------------------------------------------------------+
//| Refreshes the diagnostic snapshot and formatted output.            |
//+------------------------------------------------------------------+
void UpdateDiagnosticStatus()
{
   g_status.symbol              = _Symbol;
   g_status.assetClass          = g_assetParams.assetClass;
   g_status.currentSpreadPoints = GetCurrentSpreadPoints();
   g_status.selectedLot         = NormalizeLotToStep(g_assetParams.fixedLot);
   g_status.lastM15BarTime      = g_lastM15BarTime;

   string blockerReason = "None";
   g_status.brokerBlockerActive = CheckBrokerBlockers(g_status.selectedLot, blockerReason);
   g_status.brokerBlockerReason = blockerReason;

   AnalyzeTrendPullback();
   EvaluatePhase3Execution();
   g_status.state     = g_state;
   g_status.debugText = BuildDiagnosticText();
}

//+------------------------------------------------------------------+
//| Runs Phase 2.1 analysis only.                                     |
//+------------------------------------------------------------------+
void AnalyzeTrendPullback()
{
   ResetAnalysisDiagnostics("Analysis pending");

   g_h4Info  = AnalyzeH4Bias();
   g_h1Info  = AnalyzeH1Zone(g_h4Info);
   g_m15Info = AnalyzeM15Trigger(g_h4Info, g_h1Info);
   g_signal  = BuildSignalCandidate(g_h4Info, g_h1Info, g_m15Info);
   AnalyzeTransitionDiagnostics();
   AnalyzeSignalAvailability();
   AnalyzeEarlyTransitionDiagnostics();

   UpdateAnalysisState(g_h4Info, g_h1Info, g_m15Info);

   if(IsDirectionalBias(g_h4Info.bias))
      g_previousDirectionalBias = g_h4Info.bias;
}

//+------------------------------------------------------------------+
//| Resets analysis diagnostics to safe defaults.                      |
//+------------------------------------------------------------------+
void ResetAnalysisDiagnostics(const string reason)
{
   g_h4Info.bias               = Unknown;
   g_h4Info.emaNow             = 0.0;
   g_h4Info.emaPast            = 0.0;
   g_h4Info.atrH4              = 0.0;
   g_h4Info.slopeRatio         = 0.0;
   g_h4Info.distanceFromEmaATR = 0.0;
   g_h4Info.crossCount         = 0;
   g_h4Info.reason             = reason;

   g_h1Info.valid       = false;
   g_h1Info.source      = "NONE";
   g_h1Info.center      = 0.0;
   g_h1Info.upper       = 0.0;
   g_h1Info.lower       = 0.0;
   g_h1Info.atrH1       = 0.0;
   g_h1Info.anchorTime  = 0;
   g_h1Info.ageBars     = 0;
   g_h1Info.touchCount  = 0;
   g_h1Info.invalidated = false;
   g_h1Info.reason      = reason;
   g_h1Info.swingHigh   = 0.0;
   g_h1Info.swingLow    = 0.0;

   g_m15Info.bos                 = false;
   g_m15Info.direction           = "NONE";
   g_m15Info.priorHigh           = 0.0;
   g_m15Info.priorLow            = 0.0;
   g_m15Info.triggerOpen         = 0.0;
   g_m15Info.triggerHigh         = 0.0;
   g_m15Info.triggerLow          = 0.0;
   g_m15Info.triggerClose        = 0.0;
   g_m15Info.triggerBodyRatio    = 0.0;
   g_m15Info.bosBreakDistanceATR = 0.0;
   g_m15Info.atrM15              = 0.0;
   g_m15Info.insideZone          = false;
   g_m15Info.nearMiss            = false;
   g_m15Info.tooLate             = false;
   g_m15Info.reason              = reason;

   g_signal.hardGatesPassed = false;
   g_signal.candidate       = false;
   g_signal.direction       = "NONE";
   g_signal.score           = 0;
   g_signal.warningCount    = 0;
   g_signal.threshold       = ActiveThreshold();
   g_signal.scoreBase       = 0;
   g_signal.scoreBosStrength = 0;
   g_signal.scoreH4TrendQuality = 0;
   g_signal.scoreH4EmaDistance = 0;
   g_signal.scoreH1ZoneSource = 0;
   g_signal.scoreH1ZoneFreshness = 0;
   g_signal.scoreM15CandleBody = 0;
   g_signal.scoreTriggerLocation = 0;
   g_signal.scoreTotal = 0;
   g_signal.bosBreakDistanceATR = 0.0;
   g_signal.triggerBodyRatio = 0.0;
   g_signal.warningZoneTouch2Or3 = false;
   g_signal.warningNearMissTrigger = false;
   g_signal.warningLowLiquidity = false;
   g_signal.warningNewsBlackout = false;
   g_signal.decisionGrowthEligible = false;
   g_signal.decisionConservativeEligible = false;
   g_signal.decisionLabel = "NONE";
   g_signal.decision = "NO_CANDIDATE";
   g_signal.reason = reason;

   ResetTransitionDiagnostics(reason);
   ResetSignalAvailabilityDiagnostics(reason);
   ResetEarlyTransitionDiagnostics(reason);
}

//+------------------------------------------------------------------+
//| Resets Phase 3 execution diagnostics to safe defaults.            |
//+------------------------------------------------------------------+
void ResetExecutionDiagnostics(const string reason)
{
   g_execution.enableTrading = EnableTrading;
   g_execution.hasOpenPositionSymbolMagic = false;
   g_execution.executionBarTime = 0;
   g_execution.executionAllowed = false;
   g_execution.executionAttempted = false;
   g_execution.executionResult = "NOT_EVALUATED";
   g_execution.executionReason = reason;
   g_execution.executionRetcode = 0;
   g_execution.executionRetcodeDescription = "NONE";
   g_execution.entryPrice = 0.0;
   g_execution.slPrice = 0.0;
   g_execution.tpPrice = 0.0;
   g_execution.riskPoints = 0.0;
   g_execution.rr = 0.0;
   g_execution.lotRequested = g_assetParams.fixedLot;
   g_execution.lotNormalized = 0.0;
   g_execution.freshSpreadPoints = 0;
   g_execution.marginRequired = 0.0;
   g_execution.freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
}

//+------------------------------------------------------------------+
//| Analyzes H4 directional bias from closed candles only.             |
//+------------------------------------------------------------------+
H4BiasInfo AnalyzeH4Bias()
{
   H4BiasInfo info;
   info.bias               = Unknown;
   info.emaNow             = 0.0;
   info.emaPast            = 0.0;
   info.atrH4              = 0.0;
   info.slopeRatio         = 0.0;
   info.distanceFromEmaATR = 0.0;
   info.crossCount         = 0;
   info.reason             = "H4 analysis not available";

   if(g_h4EmaHandle == INVALID_HANDLE || g_h4AtrHandle == INVALID_HANDLE)
   {
      info.reason = "H4 EMA or ATR handle is invalid";
      return(info);
   }

   int lookback = MathMax(1, H4_Slope_Lookback);
   double emaNow = 0.0;
   double emaPast = 0.0;
   double atrH4 = 0.0;

   if(!CopyIndicatorValue(g_h4EmaHandle, 1, emaNow) ||
      !CopyIndicatorValue(g_h4EmaHandle, 1 + lookback, emaPast) ||
      !CopyIndicatorValue(g_h4AtrHandle, 1, atrH4))
   {
      info.reason = "H4 indicator data is unavailable";
      return(info);
   }

   double closeNow = iClose(_Symbol, PERIOD_H4, 1);
   if(closeNow <= 0.0 || atrH4 <= 0.0)
   {
      info.reason = "H4 candle or ATR data is invalid";
      return(info);
   }

   info.emaNow = emaNow;
   info.emaPast = emaPast;
   info.atrH4 = atrH4;
   info.slopeRatio = (emaNow - emaPast) / atrH4;
   info.distanceFromEmaATR = MathAbs(closeNow - emaNow) / atrH4;
   info.crossCount = CountH4EmaCrosses(lookback);

   bool crossedTooOften = (info.crossCount > 2);
   bool slopeFlat = (MathAbs(info.slopeRatio) <= 0.15);
   bool tooClose = (info.distanceFromEmaATR < 0.25);

   if(slopeFlat || tooClose || crossedTooOften)
   {
      info.bias = Flat;
      if(slopeFlat)
         info.reason = "Flat: H4 EMA slope ratio is within neutral range";
      else if(tooClose)
         info.reason = "Flat: H4 close is too close to EMA50";
      else
         info.reason = "Flat: last closed H4 candles crossed EMA50 more than twice";
      return(info);
   }

   if(closeNow > emaNow && info.slopeRatio > 0.15)
   {
      info.bias = Bullish;
      info.reason = "Bullish: H4 close above EMA50 with positive EMA slope and acceptable structure";
      return(info);
   }

   if(closeNow < emaNow && info.slopeRatio < -0.15)
   {
      info.bias = Bearish;
      info.reason = "Bearish: H4 close below EMA50 with negative EMA slope and acceptable structure";
      return(info);
   }

   info.bias = Flat;
   info.reason = "Flat: H4 close and EMA slope are not directionally aligned";
   return(info);
}

//+------------------------------------------------------------------+
//| Counts H4 candle ranges crossing EMA50 over closed candles.        |
//+------------------------------------------------------------------+
int CountH4EmaCrosses(const int lookback)
{
   int crossCount = 0;
   int barsToCheck = MathMax(1, lookback);

   for(int shift = 1; shift <= barsToCheck; shift++)

   {
      double ema = 0.0;
      if(!CopyIndicatorValue(g_h4EmaHandle, shift, ema))
         continue;

      double high = iHigh(_Symbol, PERIOD_H4, shift);
      double low = iLow(_Symbol, PERIOD_H4, shift);
      if(high >= ema && low <= ema)
         crossCount++;
   }

   return(crossCount);
}

//+------------------------------------------------------------------+
//| Analyzes H1 pullback zone from closed candles only.                |
//+------------------------------------------------------------------+
H1ZoneInfo AnalyzeH1Zone(const H4BiasInfo &biasInfo)
{
   H1ZoneInfo zone;
   zone.valid       = false;
   zone.source      = "NONE";
   zone.center      = 0.0;
   zone.upper       = 0.0;
   zone.lower       = 0.0;
   zone.atrH1       = 0.0;
   zone.anchorTime  = 0;
   zone.ageBars     = 0;
   zone.touchCount  = 0;
   zone.invalidated = false;
   zone.reason      = "H1 zone analysis not available";
   zone.swingHigh   = 0.0;
   zone.swingLow    = 0.0;

   if(!IsDirectionalBias(biasInfo.bias))
   {
      zone.reason = "No H1 zone: H4 bias is not directional";
      return(zone);
   }

   if(g_h1EmaHandle == INVALID_HANDLE || g_h1AtrHandle == INVALID_HANDLE)
   {
      zone.reason = "H1 EMA or ATR handle is invalid";
      return(zone);
   }

   double atrH1 = 0.0;
   double emaH1 = 0.0;
   if(!CopyIndicatorValue(g_h1AtrHandle, 1, atrH1) || !CopyIndicatorValue(g_h1EmaHandle, 1, emaH1))
   {
      zone.reason = "H1 indicator data is unavailable";
      return(zone);
   }

   if(atrH1 <= 0.0 || emaH1 <= 0.0)
   {
      zone.reason = "H1 ATR or EMA data is invalid";
      return(zone);
   }

   if(IsDirectionalBias(g_previousDirectionalBias) && g_previousDirectionalBias != biasInfo.bias)
   {
      zone.invalidated = true;
      zone.reason = "H1 zone invalidated because H4 bias flipped";
      return(zone);
   }

   int anchorShift = -1;
   double center = 0.0;
   bool foundSwing = false;

   if(biasInfo.bias == Bullish)
      foundSwing = FindMostRecentSwingLow(anchorShift, center);
   else
      foundSwing = FindMostRecentSwingHigh(anchorShift, center);

   zone.atrH1 = atrH1;

   if(foundSwing)
   {
      zone.source = "SWING";
      zone.center = center;
      zone.anchorTime = iTime(_Symbol, PERIOD_H1, anchorShift);
      zone.ageBars = anchorShift;
      if(biasInfo.bias == Bullish)
         zone.swingLow = center;
      else
         zone.swingHigh = center;
   }
   else
   {
      zone.source = "EMA20";
      zone.center = emaH1;
      zone.anchorTime = iTime(_Symbol, PERIOD_H1, 1);
      zone.ageBars = 1;
      anchorShift = 1;
   }

   zone.lower = zone.center - (0.4 * atrH1);
   zone.upper = zone.center + (0.4 * atrH1);

   if(zone.ageBars > H1_ZONE_MAX_AGE_BARS)
   {
      zone.invalidated = true;
      zone.reason = "H1 zone invalid: age exceeds 40 closed H1 candles";
      return(zone);
   }

   zone.touchCount = CountH1ZoneTouches(zone, anchorShift);
   zone.invalidated = IsH1ZoneInvalidated(zone, biasInfo.bias, anchorShift);

   if(zone.invalidated)
   {
      zone.reason = "H1 zone invalidated by closed H1 candle beyond ATR buffer";
      return(zone);
   }

   if(zone.touchCount >= 4)
   {
      zone.valid = false;
      zone.reason = "H1 zone hard excluded: touch count is 4 or more";
      return(zone);
   }

   zone.valid = true;
   if(foundSwing)
      zone.reason = "H1 zone valid from most recent qualifying swing";
   else
      zone.reason = "H1 zone valid from EMA20 fallback";

   return(zone);
}

//+------------------------------------------------------------------+
//| Finds most recent qualifying H1 swing low.                         |
//+------------------------------------------------------------------+
bool FindMostRecentSwingLow(int &anchorShift, double &swingLow)
{
   for(int shift = 3; shift <= H1_ZONE_LOOKBACK_BARS; shift++)
   {
      double low = iLow(_Symbol, PERIOD_H1, shift);
      if(low <= 0.0)
         continue;

      if(low < iLow(_Symbol, PERIOD_H1, shift - 1) &&
         low < iLow(_Symbol, PERIOD_H1, shift - 2) &&
         low < iLow(_Symbol, PERIOD_H1, shift + 1) &&
         low < iLow(_Symbol, PERIOD_H1, shift + 2))
      {
         anchorShift = shift;
         swingLow = low;
         return(true);
      }
   }

   anchorShift = 1;
   swingLow = 0.0;
   return(false);
}

//+------------------------------------------------------------------+
//| Finds most recent qualifying H1 swing high.                        |
//+------------------------------------------------------------------+
bool FindMostRecentSwingHigh(int &anchorShift, double &swingHigh)
{
   for(int shift = 3; shift <= H1_ZONE_LOOKBACK_BARS; shift++)
   {
      double high = iHigh(_Symbol, PERIOD_H1, shift);
      if(high <= 0.0)
         continue;

      if(high > iHigh(_Symbol, PERIOD_H1, shift - 1) &&
         high > iHigh(_Symbol, PERIOD_H1, shift - 2) &&
         high > iHigh(_Symbol, PERIOD_H1, shift + 1) &&
         high > iHigh(_Symbol, PERIOD_H1, shift + 2))
      {
         anchorShift = shift;
         swingHigh = high;
         return(true);
      }
   }

   anchorShift = 1;
   swingHigh = 0.0;
   return(false);
}

//+------------------------------------------------------------------+
//| Counts closed H1 candle overlaps after zone anchor.                |
//+------------------------------------------------------------------+
int CountH1ZoneTouches(const H1ZoneInfo &zone, const int anchorShift)
{
   int touches = 0;
   int startShift = MathMax(1, anchorShift - 1);

   for(int shift = startShift; shift >= 1; shift--)
   {
      double high = iHigh(_Symbol, PERIOD_H1, shift);
      double low = iLow(_Symbol, PERIOD_H1, shift);

      if(high >= zone.lower && low <= zone.upper)
         touches++;
   }

   if(touches == 0 && zone.source == "EMA20")
      touches = 1;

   return(touches);
}

//+------------------------------------------------------------------+
//| Checks H1 zone invalidation from closed H1 candles.                |
//+------------------------------------------------------------------+
bool IsH1ZoneInvalidated(const H1ZoneInfo &zone, const H4Bias bias, const int anchorShift)
{
   int startShift = MathMax(1, anchorShift - 1);

   for(int shift = startShift; shift >= 1; shift--)
   {
      double closePrice = iClose(_Symbol, PERIOD_H1, shift);
      if(closePrice <= 0.0)
         continue;

      if(bias == Bullish && closePrice < (zone.lower - zone.atrH1))
         return(true);

      if(bias == Bearish && closePrice > (zone.upper + zone.atrH1))
         return(true);
   }

   return(false);
}

//+------------------------------------------------------------------+
//| Analyzes M15 BOS trigger from closed candles only.                 |
//+------------------------------------------------------------------+
M15TriggerInfo AnalyzeM15Trigger(const H4BiasInfo &biasInfo, const H1ZoneInfo &zone)
{
   M15TriggerInfo trigger;
   trigger.bos                 = false;
   trigger.direction           = "NONE";
   trigger.priorHigh           = 0.0;
   trigger.priorLow            = 0.0;
   trigger.triggerOpen         = 0.0;
   trigger.triggerHigh         = 0.0;
   trigger.triggerLow          = 0.0;
   trigger.triggerClose        = 0.0;
   trigger.triggerBodyRatio    = 0.0;
   trigger.bosBreakDistanceATR = 0.0;
   trigger.atrM15              = 0.0;
   trigger.insideZone          = false;
   trigger.nearMiss            = false;
   trigger.tooLate             = false;
   trigger.reason              = "M15 trigger analysis not available";

   if(!IsDirectionalBias(biasInfo.bias))
   {
      trigger.reason = "No M15 trigger: H4 bias is not directional";
      return(trigger);
   }

   if(!zone.valid || zone.invalidated)
   {
      trigger.reason = "No M15 trigger: H1 zone is not valid";
      return(trigger);
   }

   if(g_m15AtrHandle == INVALID_HANDLE)
   {
      trigger.reason = "M15 ATR handle is invalid";
      return(trigger);
   }

   double atrM15 = 0.0;
   if(!CopyIndicatorValue(g_m15AtrHandle, 1, atrM15) || atrM15 <= 0.0)
   {
      trigger.reason = "M15 ATR data is unavailable";
      return(trigger);
   }

   trigger.atrM15 = atrM15;
   trigger.triggerOpen  = iOpen(_Symbol, PERIOD_M15, 1);
   trigger.triggerHigh  = iHigh(_Symbol, PERIOD_M15, 1);
   trigger.triggerLow   = iLow(_Symbol, PERIOD_M15, 1);
   trigger.triggerClose = iClose(_Symbol, PERIOD_M15, 1);

   if(trigger.triggerClose <= 0.0 || trigger.triggerOpen <= 0.0 ||
      trigger.triggerHigh <= 0.0 || trigger.triggerLow <= 0.0)
   {
      trigger.reason = "M15 trigger candle data is invalid";
      return(trigger);
   }

   double triggerRange = trigger.triggerHigh - trigger.triggerLow;
   if(triggerRange > 0.0)
      trigger.triggerBodyRatio = MathAbs(trigger.triggerClose - trigger.triggerOpen) / triggerRange;

   if(!GetM15PriorStructure(M15_BOS_Lookback, trigger.priorHigh, trigger.priorLow))
   {
      trigger.reason = "M15 prior structure data is unavailable";
      return(trigger);
   }

   bool buyBos = (trigger.triggerClose > trigger.priorHigh);
   bool sellBos = (trigger.triggerClose < trigger.priorLow);

   if(biasInfo.bias == Bullish && buyBos)
   {
      trigger.bos = true;
      trigger.direction = "BUY";
      trigger.bosBreakDistanceATR = (trigger.triggerClose - trigger.priorHigh) / atrM15;
   }
   else if(biasInfo.bias == Bearish && sellBos)
   {
      trigger.bos = true;
      trigger.direction = "SELL";
      trigger.bosBreakDistanceATR = (trigger.priorLow - trigger.triggerClose) / atrM15;
   }
   else
   {
      trigger.reason = "No BOS in the direction of H4 bias";
   }

   if(trigger.bosBreakDistanceATR < 0.0)
      trigger.bosBreakDistanceATR = 0.0;

   trigger.insideZone = (trigger.triggerClose >= zone.lower && trigger.triggerClose <= zone.upper);
   double nearMissBuffer = 0.2 * zone.atrH1;
   trigger.nearMiss = (!trigger.insideZone &&
                       trigger.triggerClose >= (zone.lower - nearMissBuffer) &&
                       trigger.triggerClose <= (zone.upper + nearMissBuffer));
   trigger.tooLate = (MathAbs(trigger.triggerClose - zone.center) > atrM15);

   if(trigger.bos && trigger.tooLate)
      trigger.reason = "BOS exists but trigger is too far from H1 zone center";
   else if(trigger.bos && trigger.insideZone)
      trigger.reason = "BOS confirmed inside H1 zone";
   else if(trigger.bos && trigger.nearMiss)
      trigger.reason = "BOS confirmed with near-miss zone location warning";
   else if(trigger.bos)
      trigger.reason = "BOS confirmed outside H1 zone quality area";

   return(trigger);
}

//+------------------------------------------------------------------+
//| Gets M15 prior high/low excluding the trigger candle.              |
//+------------------------------------------------------------------+
bool GetM15PriorStructure(const int lookback, double &priorHigh, double &priorLow)
{
   int barsToCheck = MathMax(1, lookback);
   priorHigh = -DBL_MAX;
   priorLow = DBL_MAX;

   for(int shift = 2; shift <= (barsToCheck + 1); shift++)
   {
      double high = iHigh(_Symbol, PERIOD_M15, shift);
      double low = iLow(_Symbol, PERIOD_M15, shift);

      if(high <= 0.0 || low <= 0.0)
         return(false);

      if(high > priorHigh)
         priorHigh = high;
      if(low < priorLow)
         priorLow = low;
   }

   return(priorHigh > -DBL_MAX && priorLow < DBL_MAX);
}


//+------------------------------------------------------------------+
//| Resets Phase 2.2 transition diagnostics to safe defaults.          |
//+------------------------------------------------------------------+
void ResetTransitionDiagnostics(const string reason)
{
   g_transition.enabled = EnableTransitionDiagnostics;
   g_transition.h4Directional = false;
   g_transition.h4Direction = "Unknown";
   g_transition.h4Exhaustion = false;
   g_transition.h4SlopeWeakening = false;
   g_transition.h4FailedToExtend = false;
   g_transition.h4SlopeRatio = 0.0;
   g_transition.h1OppositeBOS = false;
   g_transition.transitionDirection = "NONE";
   g_transition.h1BosLevel = 0.0;
   g_transition.h1BosDistanceATR = 0.0;
   g_transition.h1TriggerClose = 0.0;
   g_transition.h1Atr = 0.0;
   g_transition.m15OppositeBOS = false;
   g_transition.m15OppositeBreakDistanceATR = 0.0;
   g_transition.transitionWarning = false;
   g_transition.standbyRecommended = false;
   g_transition.simulatedStandbyActive = false;
   g_transition.simulatedStandbyDirection = "NONE";
   g_transition.simulatedStandbyStartTime = 0;
   g_transition.simulatedStandbyAgeH1Bars = 0;
   g_transition.wouldSuppressOldDirection = false;
   g_transition.wouldAllowNewDirection = false;
   g_transition.exitByH4Flip = false;
   g_transition.exitByTransitionFailure = false;
   g_transition.exitByExpiry = false;
   g_transition.exitReason = "NONE";
   g_transition.reason = reason;
}

//+------------------------------------------------------------------+
//| Analyzes Phase 2.2 transition diagnostics only.                   |
//+------------------------------------------------------------------+
void AnalyzeTransitionDiagnostics()
{
   g_transition.enabled = EnableTransitionDiagnostics;
   g_transition.h4Directional = IsDirectionalBias(g_h4Info.bias);
   g_transition.h4Direction = H4BiasToString(g_h4Info.bias);
   g_transition.h4SlopeRatio = g_h4Info.slopeRatio;
   g_transition.h1Atr = g_h1Info.atrH1;

   if(g_h4Info.bias == Bearish)
      g_transition.transitionDirection = "BUY";
   else if(g_h4Info.bias == Bullish)
      g_transition.transitionDirection = "SELL";
   else
      g_transition.transitionDirection = "NONE";

   g_transition.h4SlopeWeakening = IsH4SlopeWeakening(g_h4Info.bias, g_h4Info.slopeRatio);
   g_transition.h4FailedToExtend = IsH4FailedToExtend(g_h4Info.bias);
   g_transition.h4Exhaustion = (g_transition.h4SlopeWeakening || g_transition.h4FailedToExtend);

   if(EnableTransitionDiagnostics && g_transition.h4Directional)
   {
      GetH1OppositeBOS(g_h4Info.bias,
                       g_transition.h1OppositeBOS,
                       g_transition.h1BosLevel,
                       g_transition.h1BosDistanceATR,
                       g_transition.h1TriggerClose,
                       g_transition.h1Atr);
      GetM15OppositeBOS(g_h4Info.bias,
                        g_transition.m15OppositeBOS,
                        g_transition.m15OppositeBreakDistanceATR);

      g_transition.standbyRecommended = (g_transition.h1OppositeBOS &&
                                         g_transition.h1BosDistanceATR >= TransitionMinH1BreakATR &&
                                         g_transition.m15OppositeBOS &&
                                         g_transition.h4Exhaustion);
      g_transition.transitionWarning = g_transition.standbyRecommended;
      g_transition.reason = g_transition.standbyRecommended ?
                            "Transition warning: H1/M15 opposite BOS with H4 exhaustion" :
                            "No standby recommendation from Phase 2.2 diagnostics";
   }
   else if(!EnableTransitionDiagnostics)
      g_transition.reason = "Transition diagnostics disabled";
   else
      g_transition.reason = "No transition setup: H4 bias is not directional";

   UpdateSimulatedStandbyState();
   g_transition.wouldSuppressOldDirection = (g_transition.standbyRecommended || g_transition.simulatedStandbyActive);
   g_transition.wouldAllowNewDirection = false;
}

//+------------------------------------------------------------------+
//| Resets Phase 3.1 signal availability diagnostics.                 |
//+------------------------------------------------------------------+
void ResetSignalAvailabilityDiagnostics(const string reason)
{
   g_availability.enabled = false;
   g_availability.missingGatesCount = 0;
   g_availability.primaryBlocker = "NONE";
   g_availability.secondaryBlocker = "NONE";
   g_availability.nearestSetupStatus = "NOT_EVALUATED";
   g_availability.h4Ready = false;
   g_availability.h1ZoneReady = false;
   g_availability.m15TriggerReady = false;
   g_availability.scoreReady = false;
   g_availability.warningsReady = false;
   g_availability.h4ReadinessReason = reason;
   g_availability.h1ReadinessReason = reason;
   g_availability.m15ReadinessReason = reason;
   g_availability.scoreReadinessReason = reason;
   g_availability.warningReadinessReason = reason;
   g_availability.currentScore = 0;
   g_availability.requiredScore = ActiveThreshold();
   g_availability.warningCount = 0;
   g_availability.maxAllowedWarnings = (Mode == Growth) ? 1 : 0;
   g_availability.m15BosBreakDistanceATR = 0.0;
   g_availability.triggerDistanceFromZoneATR = 0.0;
   g_availability.triggerBodyRatio = 0.0;
   g_availability.h1ZoneAgeBars = 0.0;
   g_availability.h1TouchCount = 0;
   g_availability.wouldHaveBeenCandidateIf = "NOT_EVALUATED";
   g_availability.nearestSetupDirection = "NONE";
}

//+------------------------------------------------------------------+
//| Resets Phase 3.1 early transition diagnostics.                    |
//+------------------------------------------------------------------+
void ResetEarlyTransitionDiagnostics(const string reason)
{
   g_earlyTransition.enabled = false;
   g_earlyTransition.earlyTransitionWarning = false;
   g_earlyTransition.transitionStrengthScore = 0;
   g_earlyTransition.transitionMissingPiece = "NONE";
   g_earlyTransition.transitionRiskLabel = "NONE";
   g_earlyTransition.h4Exhaustion = false;
   g_earlyTransition.h1OppositeBos = false;
   g_earlyTransition.m15OppositeBos = false;
   g_earlyTransition.h1BosDistanceEnough = false;
   g_earlyTransition.h1BosDistanceATR = 0.0;
   g_earlyTransition.requiredH1BosDistanceATR = TransitionMinH1BreakATR;
   g_earlyTransition.m15OppositeBreakDistanceATR = 0.0;
   g_earlyTransition.oldDirectionRisk = "LOW";
   g_earlyTransition.reason = reason;
}

//+------------------------------------------------------------------+
//| Analyzes Phase 3.1 signal availability diagnostics only.          |
//+------------------------------------------------------------------+
void AnalyzeSignalAvailability()
{
   g_availability.enabled = true;

   string intendedDirection = g_signal.direction;
   if(intendedDirection != "BUY" && intendedDirection != "SELL")
   {
      if(g_h4Info.bias == Bullish)
         intendedDirection = "BUY";
      else if(g_h4Info.bias == Bearish)
         intendedDirection = "SELL";
      else
         intendedDirection = "NONE";
   }
   g_availability.nearestSetupDirection = intendedDirection;

   g_availability.h4Ready = IsDirectionalBias(g_h4Info.bias);
   g_availability.h4ReadinessReason = g_availability.h4Ready ? "H4_DIRECTIONAL" : g_h4Info.reason;

   g_availability.h1ZoneReady = (g_h1Info.valid && !g_h1Info.invalidated && g_h1Info.touchCount < 4);
   if(g_availability.h1ZoneReady)
      g_availability.h1ReadinessReason = "H1_ZONE_READY";
   else if(!g_h1Info.valid)
      g_availability.h1ReadinessReason = g_h1Info.reason;
   else if(g_h1Info.invalidated)
      g_availability.h1ReadinessReason = "H1_ZONE_INVALIDATED";
   else if(g_h1Info.touchCount >= 4)
      g_availability.h1ReadinessReason = "H1_TOUCH_COUNT_TOO_HIGH";
   else
      g_availability.h1ReadinessReason = g_h1Info.reason;

   bool directionMatches = (intendedDirection == "BUY" || intendedDirection == "SELL") && g_m15Info.direction == intendedDirection;
   g_availability.m15TriggerReady = (g_m15Info.bos && directionMatches && !g_m15Info.tooLate && (g_m15Info.insideZone || g_m15Info.nearMiss));
   if(g_availability.m15TriggerReady)
      g_availability.m15ReadinessReason = "M15_TRIGGER_READY";
   else if(!g_m15Info.bos)
      g_availability.m15ReadinessReason = "M15_BOS_MISSING";
   else if(!directionMatches)
      g_availability.m15ReadinessReason = "M15_DIRECTION_MISMATCH";
   else if(g_m15Info.tooLate)
      g_availability.m15ReadinessReason = "M15_TRIGGER_TOO_LATE";
   else if(!g_m15Info.insideZone && !g_m15Info.nearMiss)
      g_availability.m15ReadinessReason = "M15_TRIGGER_OUTSIDE_H1_ZONE";
   else
      g_availability.m15ReadinessReason = g_m15Info.reason;

   g_availability.currentScore = g_signal.score;
   g_availability.requiredScore = ActiveThreshold();
   g_availability.scoreReady = (g_signal.score >= g_availability.requiredScore);
   g_availability.scoreReadinessReason = g_availability.scoreReady ? "SCORE_READY" : "SCORE_BELOW_THRESHOLD";

   g_availability.warningCount = g_signal.warningCount;
   g_availability.maxAllowedWarnings = (Mode == Growth) ? 1 : 0;
   g_availability.warningsReady = (g_signal.warningCount <= g_availability.maxAllowedWarnings);
   g_availability.warningReadinessReason = g_availability.warningsReady ? "WARNINGS_READY" : "WARNINGS_TOO_HIGH";

   g_availability.missingGatesCount = 0;
   if(!g_availability.h4Ready) g_availability.missingGatesCount++;
   if(!g_availability.h1ZoneReady) g_availability.missingGatesCount++;
   if(!g_availability.m15TriggerReady) g_availability.missingGatesCount++;
   if(!g_availability.scoreReady) g_availability.missingGatesCount++;
   if(!g_availability.warningsReady) g_availability.missingGatesCount++;

   string blockers[5];
   int blockerCount = 0;
   if(!g_availability.h4Ready) blockers[blockerCount++] = "H4_NOT_DIRECTIONAL";
   if(!g_availability.h1ZoneReady) blockers[blockerCount++] = "H1_ZONE_NOT_READY";
   if(!g_availability.m15TriggerReady) blockers[blockerCount++] = "M15_TRIGGER_NOT_READY";
   if(!g_availability.scoreReady) blockers[blockerCount++] = "SCORE_NOT_READY";
   if(!g_availability.warningsReady) blockers[blockerCount++] = "WARNINGS_TOO_HIGH";
   g_availability.primaryBlocker = (blockerCount > 0) ? blockers[0] : "NONE";
   g_availability.secondaryBlocker = (blockerCount > 1) ? blockers[1] : "NONE";

   if(g_signal.candidate)
      g_availability.nearestSetupStatus = "CANDIDATE_READY";
   else if(g_availability.missingGatesCount == 1)
      g_availability.nearestSetupStatus = "ONE_GATE_MISSING";
   else if(g_availability.missingGatesCount == 2)
      g_availability.nearestSetupStatus = "TWO_GATES_MISSING";
   else
      g_availability.nearestSetupStatus = "FAR_FROM_SETUP";

   if(g_availability.missingGatesCount == 0 && g_signal.candidate)
      g_availability.wouldHaveBeenCandidateIf = "ALREADY_CANDIDATE";
   else if(g_availability.missingGatesCount == 1)
      g_availability.wouldHaveBeenCandidateIf = g_availability.primaryBlocker;
   else
      g_availability.wouldHaveBeenCandidateIf = "MULTIPLE_CONDITIONS_MISSING";

   g_availability.m15BosBreakDistanceATR = g_m15Info.bosBreakDistanceATR;
   g_availability.triggerBodyRatio = g_m15Info.triggerBodyRatio;
   g_availability.h1ZoneAgeBars = g_h1Info.ageBars;
   g_availability.h1TouchCount = g_h1Info.touchCount;
   g_availability.triggerDistanceFromZoneATR = 0.0;
   if(g_h1Info.atrH1 > 0.0)
   {
      if(g_m15Info.triggerClose > g_h1Info.upper)
         g_availability.triggerDistanceFromZoneATR = (g_m15Info.triggerClose - g_h1Info.upper) / g_h1Info.atrH1;
      else if(g_m15Info.triggerClose < g_h1Info.lower)
         g_availability.triggerDistanceFromZoneATR = (g_h1Info.lower - g_m15Info.triggerClose) / g_h1Info.atrH1;
   }
}

//+------------------------------------------------------------------+
//| Analyzes Phase 3.1 early transition diagnostics only.             |
//+------------------------------------------------------------------+
void AnalyzeEarlyTransitionDiagnostics()
{
   g_earlyTransition.enabled = true;
   g_earlyTransition.h4Exhaustion = g_transition.h4Exhaustion;
   g_earlyTransition.h1OppositeBos = g_transition.h1OppositeBOS;
   g_earlyTransition.m15OppositeBos = g_transition.m15OppositeBOS;
   g_earlyTransition.h1BosDistanceATR = g_transition.h1BosDistanceATR;
   g_earlyTransition.requiredH1BosDistanceATR = TransitionMinH1BreakATR;
   g_earlyTransition.m15OppositeBreakDistanceATR = g_transition.m15OppositeBreakDistanceATR;
   g_earlyTransition.h1BosDistanceEnough = (g_earlyTransition.h1BosDistanceATR >= TransitionMinH1BreakATR);

   int score = 0;
   if(g_earlyTransition.h4Exhaustion) score += 35;
   if(g_earlyTransition.h1OppositeBos) score += 30;
   if(g_earlyTransition.h1BosDistanceEnough) score += 20;
   if(g_earlyTransition.m15OppositeBos) score += 15;
   g_earlyTransition.transitionStrengthScore = MathMin(score, 100);
   g_earlyTransition.earlyTransitionWarning = (g_earlyTransition.transitionStrengthScore >= 50);

   if(g_earlyTransition.transitionStrengthScore < 35)
      g_earlyTransition.transitionRiskLabel = "NONE";
   else if(g_earlyTransition.transitionStrengthScore < 50)
      g_earlyTransition.transitionRiskLabel = "WATCH";
   else if(g_earlyTransition.transitionStrengthScore < 75)
      g_earlyTransition.transitionRiskLabel = "EARLY_WARNING";
   else
      g_earlyTransition.transitionRiskLabel = "STRONG_TRANSITION_RISK";

   if(!g_earlyTransition.h4Exhaustion)
      g_earlyTransition.transitionMissingPiece = "H4_EXHAUSTION_MISSING";
   else if(!g_earlyTransition.h1OppositeBos)
      g_earlyTransition.transitionMissingPiece = "H1_OPPOSITE_BOS_MISSING";
   else if(!g_earlyTransition.h1BosDistanceEnough)
      g_earlyTransition.transitionMissingPiece = "H1_BOS_DISTANCE_TOO_SMALL";
   else if(!g_earlyTransition.m15OppositeBos)
      g_earlyTransition.transitionMissingPiece = "M15_OPPOSITE_BOS_MISSING";
   else
      g_earlyTransition.transitionMissingPiece = "NONE";

   if(g_earlyTransition.transitionStrengthScore < 50)
      g_earlyTransition.oldDirectionRisk = "LOW";
   else if(g_earlyTransition.transitionStrengthScore < 75)
      g_earlyTransition.oldDirectionRisk = "MEDIUM";
   else
      g_earlyTransition.oldDirectionRisk = "HIGH";

   if(g_earlyTransition.transitionStrengthScore < 35)
      g_earlyTransition.reason = "No early transition risk";
   else if(g_earlyTransition.h4Exhaustion && !g_earlyTransition.h1OppositeBos)
      g_earlyTransition.reason = "H4 exhaustion present but H1 opposite BOS missing";
   else if(g_earlyTransition.h1OppositeBos && !g_earlyTransition.h1BosDistanceEnough)
      g_earlyTransition.reason = "H1 opposite BOS exists but distance below threshold";
   else if(g_earlyTransition.transitionStrengthScore >= 75)
      g_earlyTransition.reason = "Strong transition risk detected; diagnostics only";
   else
      g_earlyTransition.reason = "Early transition risk detected; diagnostics only";
}

bool GetH1OppositeBOS(const H4Bias bias, bool &oppositeBOS, double &bosLevel, double &distanceATR, double &triggerClose, double &atrH1)
{
   oppositeBOS = false; bosLevel = 0.0; distanceATR = 0.0; triggerClose = iClose(_Symbol, PERIOD_H1, 1);
   if(!CopyIndicatorValue(g_h1AtrHandle, 1, atrH1) || atrH1 <= 0.0 || triggerClose <= 0.0)
      return(false);
   int lookback = MathMax(1, TransitionH1Lookback);
   if(bias == Bearish)
   {
      double priorHigh = -DBL_MAX;
      for(int shift = 2; shift <= lookback + 1; shift++)
      {
         double high = iHigh(_Symbol, PERIOD_H1, shift);
         double low = iLow(_Symbol, PERIOD_H1, shift);
         if(high <= 0.0 || low <= 0.0)
            return(false);

         priorHigh = MathMax(priorHigh, high);
      }
      if(priorHigh <= 0.0)
         return(false);

      bosLevel = priorHigh; distanceATR = MathMax(0.0, (triggerClose - priorHigh) / atrH1); oppositeBOS = (triggerClose > priorHigh);
   }
   else if(bias == Bullish)
   {
      double priorLow = DBL_MAX;
      for(int shift = 2; shift <= lookback + 1; shift++)
      {
         double high = iHigh(_Symbol, PERIOD_H1, shift);
         double low = iLow(_Symbol, PERIOD_H1, shift);
         if(high <= 0.0 || low <= 0.0)
            return(false);

         priorLow = MathMin(priorLow, low);
      }
      if(priorLow <= 0.0)
         return(false);

      bosLevel = priorLow; distanceATR = MathMax(0.0, (priorLow - triggerClose) / atrH1); oppositeBOS = (triggerClose < priorLow);
   }
   return(oppositeBOS);
}

bool GetM15OppositeBOS(const H4Bias bias, bool &oppositeBOS, double &distanceATR)
{
   oppositeBOS = false; distanceATR = 0.0;
   double atrM15 = 0.0, triggerClose = iClose(_Symbol, PERIOD_M15, 1);
   if(!CopyIndicatorValue(g_m15AtrHandle, 1, atrM15) || atrM15 <= 0.0 || triggerClose <= 0.0)
      return(false);
   int lookback = MathMax(1, TransitionM15Lookback);
   if(bias == Bearish)
   {
      double priorHigh = -DBL_MAX;
      for(int shift = 2; shift <= lookback + 1; shift++)
      {
         double high = iHigh(_Symbol, PERIOD_M15, shift);
         double low = iLow(_Symbol, PERIOD_M15, shift);
         if(high <= 0.0 || low <= 0.0)
            return(false);

         priorHigh = MathMax(priorHigh, high);
      }
      if(priorHigh <= 0.0)
         return(false);

      distanceATR = MathMax(0.0, (triggerClose - priorHigh) / atrM15); oppositeBOS = (triggerClose > priorHigh);
   }
   else if(bias == Bullish)
   {
      double priorLow = DBL_MAX;
      for(int shift = 2; shift <= lookback + 1; shift++)
      {
         double high = iHigh(_Symbol, PERIOD_M15, shift);

         double low = iLow(_Symbol, PERIOD_M15, shift);
         if(high <= 0.0 || low <= 0.0)
            return(false);

         priorLow = MathMin(priorLow, low);
      }
      if(priorLow <= 0.0)
         return(false);

      distanceATR = MathMax(0.0, (priorLow - triggerClose) / atrM15); oppositeBOS = (triggerClose < priorLow);
   }
   return(oppositeBOS);
}

bool IsH4SlopeWeakening(const H4Bias bias, const double slopeRatio)
{
   if(bias == Bullish) return(slopeRatio <= 0.25);
   if(bias == Bearish) return(slopeRatio >= -0.25);
   return(false);
}

bool IsH4FailedToExtend(const H4Bias bias)
{
   if(bias == Bullish)
   {
      double recentHigh = iHigh(_Symbol, PERIOD_H4, 1);
      double previousHighMax = MathMax(iHigh(_Symbol, PERIOD_H4, 2), MathMax(iHigh(_Symbol, PERIOD_H4, 3), iHigh(_Symbol, PERIOD_H4, 4)));
      return(recentHigh > 0.0 && previousHighMax > 0.0 && recentHigh <= previousHighMax);
   }
   if(bias == Bearish)
   {
      double recentLow = iLow(_Symbol, PERIOD_H4, 1);
      double previousLowMin = MathMin(iLow(_Symbol, PERIOD_H4, 2), MathMin(iLow(_Symbol, PERIOD_H4, 3), iLow(_Symbol, PERIOD_H4, 4)));
      return(recentLow > 0.0 && previousLowMin > 0.0 && recentLow >= previousLowMin);
   }
   return(false);
}

int GetH1BarsSince(const datetime startTime)
{
   if(startTime <= 0) return(0);
   int shift = iBarShift(_Symbol, PERIOD_H1, startTime, true);
   if(shift < 1) shift = iBarShift(_Symbol, PERIOD_H1, startTime, false);
   return(MathMax(0, shift - 1));
}

void ClearSimulatedStandbyState()
{
   g_simulatedStandbyActive = false;
   g_simulatedStandbyDirection = "NONE";
   g_simulatedStandbyOriginalH4Bias = Unknown;
   g_simulatedStandbyStartTime = 0;
   g_simulatedStandbyBosLevel = 0.0;
}

void UpdateSimulatedStandbyState()
{
   if(g_transition.standbyRecommended && !g_simulatedStandbyActive)
   {
      g_simulatedStandbyActive = true;
      g_simulatedStandbyDirection = g_transition.transitionDirection;
      g_simulatedStandbyOriginalH4Bias = g_h4Info.bias;
      g_simulatedStandbyStartTime = iTime(_Symbol, PERIOD_H1, 1);
      g_simulatedStandbyBosLevel = g_transition.h1BosLevel;
   }

   if(g_simulatedStandbyActive)
   {
      g_transition.simulatedStandbyActive = true;
      g_transition.simulatedStandbyDirection = g_simulatedStandbyDirection;
      g_transition.simulatedStandbyStartTime = g_simulatedStandbyStartTime;
      g_transition.simulatedStandbyAgeH1Bars = GetH1BarsSince(g_simulatedStandbyStartTime);

      double h1Close = iClose(_Symbol, PERIOD_H1, 1);
      double atrH1 = g_transition.h1Atr;
      if(atrH1 <= 0.0) CopyIndicatorValue(g_h1AtrHandle, 1, atrH1);

      if(g_simulatedStandbyOriginalH4Bias == Bearish && g_h4Info.bias == Bullish)
      { g_transition.exitByH4Flip = true; g_transition.exitReason = "Simulated standby exit: H4 flipped to bullish"; ClearSimulatedStandbyState(); }
      else if(g_simulatedStandbyOriginalH4Bias == Bullish && g_h4Info.bias == Bearish)
      { g_transition.exitByH4Flip = true; g_transition.exitReason = "Simulated standby exit: H4 flipped to bearish"; ClearSimulatedStandbyState(); }
      else if(atrH1 > 0.0 && h1Close > 0.0 && g_simulatedStandbyDirection == "BUY" && h1Close < g_simulatedStandbyBosLevel - (TransitionFailureBufferATR * atrH1))
      { g_transition.exitByTransitionFailure = true; g_transition.exitReason = "Simulated standby exit: transition failed and price returned through H1 BOS level"; ClearSimulatedStandbyState(); }
      else if(atrH1 > 0.0 && h1Close > 0.0 && g_simulatedStandbyDirection == "SELL" && h1Close > g_simulatedStandbyBosLevel + (TransitionFailureBufferATR * atrH1))
      { g_transition.exitByTransitionFailure = true; g_transition.exitReason = "Simulated standby exit: transition failed and price returned through H1 BOS level"; ClearSimulatedStandbyState(); }
      else if(g_transition.simulatedStandbyAgeH1Bars >= TransitionExpiryH1Bars)
      { g_transition.exitByExpiry = true; g_transition.exitReason = "Simulated standby exit: expiry reached without H4 flip or transition failure"; ClearSimulatedStandbyState(); }
   }
}

//+------------------------------------------------------------------+
//| Builds final signal diagnostics without order execution.           |
//+------------------------------------------------------------------+
SignalCandidate BuildSignalCandidate(const H4BiasInfo &biasInfo,
                                     const H1ZoneInfo &zone,
                                     const M15TriggerInfo &trigger)
{
   SignalCandidate signal;
   signal.hardGatesPassed = false;
   signal.candidate       = false;
   signal.direction       = trigger.direction;
   signal.score           = 0;
   signal.warningCount    = 0;
   signal.threshold       = ActiveThreshold();
   signal.scoreBase       = 0;
   signal.scoreBosStrength = ScoreBosStrength(trigger.bos, trigger.bosBreakDistanceATR);
   signal.scoreH4TrendQuality = ScoreH4TrendQuality(MathAbs(biasInfo.slopeRatio), biasInfo.crossCount);
   signal.scoreH4EmaDistance = ScoreH4EmaDistance(biasInfo.distanceFromEmaATR);
   signal.scoreH1ZoneSource = ScoreH1ZoneSource(zone.source);
   signal.scoreH1ZoneFreshness = ScoreH1ZoneFreshness(zone.touchCount);
   signal.scoreM15CandleBody = ScoreM15CandleBody(trigger.triggerBodyRatio);
   signal.scoreTriggerLocation = ScoreTriggerLocation(trigger.insideZone, trigger.nearMiss);
   signal.scoreTotal = 0;
   signal.bosBreakDistanceATR = trigger.bosBreakDistanceATR;
   signal.triggerBodyRatio = trigger.triggerBodyRatio;
   signal.warningZoneTouch2Or3 = (zone.touchCount == 2 || zone.touchCount == 3);
   signal.warningNearMissTrigger = trigger.nearMiss;
   signal.warningLowLiquidity = false;
   signal.warningNewsBlackout = UseManualNewsBlackout;
   signal.warningCount = CalculateWarningCount(signal.warningZoneTouch2Or3,
                                               signal.warningNearMissTrigger,
                                               signal.warningLowLiquidity,
                                               signal.warningNewsBlackout);
   signal.decisionGrowthEligible = false;
   signal.decisionConservativeEligible = false;
   signal.decisionLabel = "NONE";
   signal.decision = "NO_CANDIDATE";
   signal.reason = "Hard gates not evaluated";

   bool directionMatches = ((biasInfo.bias == Bullish && trigger.direction == "BUY") ||
                            (biasInfo.bias == Bearish && trigger.direction == "SELL"));

   signal.hardGatesPassed = (!g_status.brokerBlockerActive &&
                             biasInfo.bias != Flat &&
                             biasInfo.bias != Unknown &&
                             zone.valid &&
                             !zone.invalidated &&
                             zone.touchCount < 4 &&
                             trigger.bos &&
                             directionMatches &&
                             (trigger.insideZone || trigger.nearMiss) &&
                             !trigger.tooLate);

   if(signal.hardGatesPassed)
   {
      signal.scoreBase = 40;
      signal.scoreTotal = signal.scoreBase +
                          signal.scoreBosStrength +
                          signal.scoreH4TrendQuality +
                          signal.scoreH4EmaDistance +
                          signal.scoreH1ZoneSource +
                          signal.scoreH1ZoneFreshness +
                          signal.scoreM15CandleBody +
                          signal.scoreTriggerLocation;
      signal.scoreTotal = ClampInt(signal.scoreTotal, 0, 100);
      signal.score = signal.scoreTotal;
   }
   else
   {
      signal.scoreBase = 0;
      signal.scoreTotal = 0;
      signal.score = 0;
      signal.reason = BuildHardGateFailureReason(biasInfo, zone, trigger, directionMatches);
      return(signal);
   }

   signal.decisionGrowthEligible = (signal.hardGatesPassed && signal.scoreTotal >= GrowthThreshold && signal.warningCount <= 1);
   signal.decisionConservativeEligible = (signal.hardGatesPassed && signal.scoreTotal >= ConservativeThreshold && signal.warningCount == 0);

   if(signal.decisionConservativeEligible)
      signal.decisionLabel = "CONSERVATIVE";
   else if(signal.decisionGrowthEligible)
      signal.decisionLabel = "GROWTH";
   else
      signal.decisionLabel = "NONE";

   if(Mode == Growth)
   {
      signal.candidate = signal.decisionGrowthEligible;
      signal.decision = signal.candidate ? "GROWTH_CANDIDATE" : "NO_CANDIDATE";
      if(signal.candidate)
         signal.reason = "Growth accepted: score >= 60 and warningCount <= 1";
      else if(signal.scoreTotal < GrowthThreshold)
         signal.reason = "Growth rejected: score below 60";
      else if(signal.warningCount > 1)
         signal.reason = "Growth rejected: warningCount above 1";
      else
         signal.reason = "Growth rejected: eligibility rule failed";
   }
   else
   {
      signal.candidate = signal.decisionConservativeEligible;
      signal.decision = signal.candidate ? "CONSERVATIVE_CANDIDATE" : "NO_CANDIDATE";
      if(signal.candidate)
         signal.reason = "Conservative accepted: score >= 75 and warningCount == 0";
      else if(signal.scoreTotal < ConservativeThreshold)
         signal.reason = "Conservative rejected: score below 75";
      else if(signal.warningCount > 0)
         signal.reason = "Conservative rejected: warningCount must be 0";
      else
         signal.reason = "Conservative rejected: eligibility rule failed";
   }

   return(signal);
}

//+------------------------------------------------------------------+
//| Scoring helper functions.                                         |
//+------------------------------------------------------------------+
int ClampInt(const int value, const int minValue, const int maxValue)
{
   if(value < minValue)
      return(minValue);
   if(value > maxValue)
      return(maxValue);
   return(value);
}

int ScoreBosStrength(const bool bos, const double breakDistanceATR)
{
   if(!bos)
      return(0);
   if(breakDistanceATR > 0.50)
      return(15);
   if(breakDistanceATR >= 0.25)
      return(12);
   if(breakDistanceATR >= 0.10)
      return(9);
   if(breakDistanceATR > 0.00)
      return(5);
   return(0);
}

int ScoreH4TrendQuality(const double absSlopeRatio, const int crossCount)
{
   int score = 0;
   if(absSlopeRatio > 0.40)
      score = 10;
   else if(absSlopeRatio >= 0.25)
      score = 7;
   else if(absSlopeRatio >= 0.15)
      score = 4;

   if(crossCount == 1)
      score -= 2;
   else if(crossCount == 2)
      score -= 4;

   return(ClampInt(score, 0, 10));
}

int ScoreH4EmaDistance(const double distanceATR)
{
   if(distanceATR >= 0.25 && distanceATR < 0.50)
      return(8);
   if(distanceATR >= 0.50 && distanceATR < 1.00)
      return(6);
   if(distanceATR >= 1.00 && distanceATR <= 1.50)
      return(3);
   if(distanceATR > 1.50)
      return(1);
   return(0);
}

int ScoreH1ZoneSource(const string source)
{
   if(source == "SWING")
      return(10);
   if(source == "EMA20")
      return(5);
   return(0);
}

int ScoreH1ZoneFreshness(const int touchCount)
{
   if(touchCount == 1)
      return(8);
   if(touchCount == 2)
      return(5);
   if(touchCount == 3)
      return(3);
   return(0);
}

int ScoreM15CandleBody(const double bodyRatio)
{
   if(bodyRatio >= 0.70)
      return(7);
   if(bodyRatio >= 0.50)
      return(5);
   if(bodyRatio >= 0.30)
      return(3);
   if(bodyRatio > 0.00)
      return(1);
   return(0);
}

int ScoreTriggerLocation(const bool insideZone, const bool nearMiss)
{
   if(insideZone)
      return(2);
   if(nearMiss)
      return(1);
   return(0);
}

int CalculateWarningCount(const bool warningZoneTouch2Or3,
                          const bool warningNearMissTrigger,
                          const bool warningLowLiquidity,
                          const bool warningNewsBlackout)
{
   int count = 0;
   if(warningZoneTouch2Or3)
      count++;
   if(warningNearMissTrigger)
      count++;
   if(warningLowLiquidity)
      count++;
   if(warningNewsBlackout)
      count++;
   return(count);
}

//+------------------------------------------------------------------+
//| Explains first hard-gate failure found.                            |
//+------------------------------------------------------------------+
string BuildHardGateFailureReason(const H4BiasInfo &biasInfo,
                                  const H1ZoneInfo &zone,
                                  const M15TriggerInfo &trigger,
                                  const bool directionMatches)
{
   if(g_status.brokerBlockerActive)
      return("Broker blocker active: " + g_status.brokerBlockerReason);
   if(biasInfo.bias == Flat)
      return("H4 hard gate failed: bias is Flat");
   if(biasInfo.bias == Unknown)
      return("H4 hard gate failed: bias is Unknown");
   if(zone.invalidated)
      return("H1 hard gate failed: zone invalidated");
   if(!zone.valid)
      return("H1 hard gate failed: zone is not valid");
   if(zone.touchCount >= 4)
      return("H1 hard gate failed: zone touch count is 4 or more");
   if(!trigger.bos)
      return("M15 hard gate failed: BOS is missing");
   if(!directionMatches)
      return("M15 hard gate failed: BOS direction does not match H4 bias");
   if(!trigger.insideZone && !trigger.nearMiss)
      return("M15 hard gate failed: trigger is outside H1 zone quality area");
   if(trigger.tooLate)
      return("M15 hard gate failed: trigger is too late");

   return("Hard gate failed for unspecified diagnostic reason");
}

//+------------------------------------------------------------------+
//| Updates analysis state without execution behavior.                 |
//+------------------------------------------------------------------+
void UpdateAnalysisState(const H4BiasInfo &biasInfo, const H1ZoneInfo &zone, const M15TriggerInfo &trigger)
{
   if(biasInfo.bias != Bullish && biasInfo.bias != Bearish)
   {
      SetState(IDLE);
      return;
   }

   if(zone.invalidated)
   {
      SetState(ZONE_INVALIDATED);
      return;
   }

   if(!zone.valid)
   {
      SetState(BIAS_ACTIVE);
      return;
   }

   if(!trigger.bos)
   {
      SetState(TRIGGER_PENDING);
      return;
   }

   SetState(ZONE_VALID);
}

//+------------------------------------------------------------------+
//| Returns true when bias is directional.                             |
//+------------------------------------------------------------------+
bool IsDirectionalBias(const H4Bias bias)
{
   return(bias == Bullish || bias == Bearish);
}

//+------------------------------------------------------------------+
//| Returns the active score threshold for diagnostics.                |
//+------------------------------------------------------------------+
int ActiveThreshold()
{
   if(Mode == Growth)
      return(GrowthThreshold);

   return(ConservativeThreshold);
}

//+------------------------------------------------------------------+
//| Safely copies one indicator buffer value by closed-candle shift.   |
//+------------------------------------------------------------------+
bool CopyIndicatorValue(const int handle, const int shift, double &value)
{
   value = 0.0;
   if(handle == INVALID_HANDLE || shift < 0)
      return(false);

   double buffer[];
   ArraySetAsSeries(buffer, true);
   int copied = CopyBuffer(handle, 0, shift, 1, buffer);
   if(copied != 1)
      return(false);

   if(buffer[0] == EMPTY_VALUE)
      return(false);

   value = buffer[0];
   return(true);
}

//+------------------------------------------------------------------+
//| Detects the asset class from the current chart symbol.             |
//+------------------------------------------------------------------+
AssetClass DetectAssetClass(const string symbol)
{
   string upperSymbol = symbol;
   StringToUpper(upperSymbol);

   if(StringFind(upperSymbol, "XAU") >= 0 || StringFind(upperSymbol, "GOLD") >= 0)
      return(GOLD);

   if(StringFind(upperSymbol, "XAG") >= 0 || StringFind(upperSymbol, "SILVER") >= 0)
      return(SILVER);

   if(StringFind(upperSymbol, "OIL") >= 0 ||
      StringFind(upperSymbol, "WTI") >= 0 ||
      StringFind(upperSymbol, "USOIL") >= 0 ||
      StringFind(upperSymbol, "UKOIL") >= 0 ||
      StringFind(upperSymbol, "BRENT") >= 0)
      return(OIL);

   if(IsIndexSymbol(upperSymbol))
      return(INDEX);

   if(IsCommonForexSymbol(upperSymbol))
      return(FOREX);

   return(UNKNOWN);
}

//+------------------------------------------------------------------+
//| Loads default parameters for the detected asset class.             |
//+------------------------------------------------------------------+
AssetParams LoadAssetParams(const AssetClass assetClass)
{
   AssetParams params;
   params.assetClass = assetClass;

   switch(assetClass)
   {
      case GOLD:
         params.fixedLot        = GoldLot;
         params.maxSpreadPoints = GoldMaxSpreadPoints;
         params.atrBuffer       = 0.5;
         params.minRR           = 1.8;
         break;

      case SILVER:
         params.fixedLot        = SilverLot;
         params.maxSpreadPoints = SilverMaxSpreadPoints;
         params.atrBuffer       = 0.6;
         params.minRR           = 1.8;
         break;

      case OIL:
         params.fixedLot        = OilLot;
         params.maxSpreadPoints = OilMaxSpreadPoints;
         params.atrBuffer       = 0.7;
         params.minRR           = 1.5;
         break;

      case INDEX:
         params.fixedLot        = IndexLot;
         params.maxSpreadPoints = IndexMaxSpreadPoints;
         params.atrBuffer       = 0.7;
         params.minRR           = 1.5;
         break;

      case FOREX:
      case UNKNOWN:
      default:
         params.fixedLot        = ForexLot;
         params.maxSpreadPoints = ForexMaxSpreadPoints;
         params.atrBuffer       = 0.3;
         params.minRR           = 1.5;
         break;
   }

   return(params);
}

//+------------------------------------------------------------------+
//| Checks index symbols while allowing broker prefixes/suffixes.      |

//+------------------------------------------------------------------+
bool IsIndexSymbol(const string upperSymbol)
{
   string indexSymbols[] =
   {
      "US100", "NAS100", "USTEC", "NDX", "NASDAQ",
      "US30", "DJ30", "DOW",
      "US500", "SPX", "SP500",
      "GER40", "DAX"
   };

   for(int i = 0; i < ArraySize(indexSymbols); i++)
   {
      if(StringFind(upperSymbol, indexSymbols[i]) >= 0)
         return(true);
   }

   return(false);
}

//+------------------------------------------------------------------+
//| Checks common forex symbols while allowing broker suffixes.        |
//+------------------------------------------------------------------+
bool IsCommonForexSymbol(const string upperSymbol)
{
   string majorsAndCrosses[] =
   {
      "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
      "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD",
      "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD",
      "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
      "NZDJPY", "NZDCHF", "NZDCAD",
      "CADJPY", "CADCHF", "CHFJPY"
   };

   for(int i = 0; i < ArraySize(majorsAndCrosses); i++)
   {
      if(StringFind(upperSymbol, majorsAndCrosses[i]) >= 0)
         return(true);
   }

   return(false);
}

//+------------------------------------------------------------------+
//| Performs hard broker/environment blocker checks without execution. |
//+------------------------------------------------------------------+
bool CheckBrokerBlockers(const double selectedLot, string &reason)
{
   reason = "None";

   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
   {
      reason = "Terminal trading is not allowed";
      return(true);
   }

   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
   {
      reason = "MQL trading is not allowed for this EA";
      return(true);
   }

   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
   {
      reason = "Account trading is not allowed";
      return(true);
   }

   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
   {
      reason = "Expert trading is disabled for this account";
      return(true);
   }

   long tradeMode = SYMBOL_TRADE_MODE_DISABLED;
   if(!SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE, tradeMode))
   {
      reason = "Unable to read symbol trade mode";
      return(true);
   }

   if(tradeMode == SYMBOL_TRADE_MODE_DISABLED)
   {
      reason = "Symbol trade mode is disabled";
      return(true);
   }

   if(tradeMode == SYMBOL_TRADE_MODE_CLOSEONLY)
   {
      reason = "Symbol trade mode is close-only";
      return(true);
   }

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick) || tick.bid <= 0.0 || tick.ask <= 0.0)
   {
      reason = "Market tick data is unavailable";
      return(true);
   }

   if(!IsLotValid(selectedLot, reason))
      return(true);

   if(GetCurrentSpreadPoints() > g_assetParams.maxSpreadPoints)
   {
      reason = "Spread exceeds selected maximum";
      return(true);
   }

   if(!HasBasicMargin(selectedLot, reason))
      return(true);

   return(false);
}

//+------------------------------------------------------------------+
//| Validates lot against broker min/max/step.                         |
//+------------------------------------------------------------------+
bool IsLotValid(const double lot, string &reason)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(minLot <= 0.0 || maxLot <= 0.0 || lotStep <= 0.0)
   {
      reason = StringFormat("Unable to read broker lot constraints: min=%.8f max=%.8f step=%.8f", minLot, maxLot, lotStep);
      return(false);
   }

   if(lot < minLot)
   {
      reason = StringFormat("Selected lot %.8f is below broker minimum %.8f", lot, minLot);
      return(false);
   }

   if(lot > maxLot)
   {
      reason = StringFormat("Selected lot %.8f is above broker maximum %.8f", lot, maxLot);
      return(false);
   }

   double normalizedLot = NormalizeLotToStep(lot);
   if(MathAbs(normalizedLot - lot) > 0.0000001)
   {
      reason = StringFormat("Selected lot %.8f is not aligned to broker step %.8f; normalized step lot would be %.8f", lot, lotStep, normalizedLot);
      return(false);
   }

   reason = StringFormat("Lot %.8f is valid: min=%.8f max=%.8f step=%.8f", lot, minLot, maxLot, lotStep);
   return(true);
}

//+------------------------------------------------------------------+
//| Performs a basic margin availability check without execution.      |
//+------------------------------------------------------------------+
bool HasBasicMargin(const double lot, string &reason)
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick) || tick.ask <= 0.0)
   {
      reason = "Unable to read price for margin check";
      return(false);
   }

   double marginRequired = 0.0;
   if(!OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, lot, tick.ask, marginRequired))
   {
      reason = "Broker margin calculation is unavailable";
      return(false);
   }

   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(marginRequired > freeMargin)
   {
      reason = "Insufficient free margin for selected lot";
      return(false);
   }

   reason = "None";
   return(true);
}

//+------------------------------------------------------------------+
//| Returns the current spread in points.                              |
//+------------------------------------------------------------------+
int GetCurrentSpreadPoints()
{
   long spread = 0;
   if(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD, spread))
      return((int)spread);

   MqlTick tick;
   if(SymbolInfoTick(_Symbol, tick) && tick.ask > 0.0 && tick.bid > 0.0 && _Point > 0.0)
      return((int)MathRound((tick.ask - tick.bid) / _Point));

   return(0);
}

//+------------------------------------------------------------------+
//| Returns volume digits implied by SYMBOL_VOLUME_STEP.               |
//+------------------------------------------------------------------+
int GetVolumeDigits()
{
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(lotStep <= 0.0)
      return(2);

   int digits = 0;
   double step = lotStep;
   while(digits < 8 && MathAbs(step - MathRound(step)) > 0.0000001)
   {
      step *= 10.0;
      digits++;
   }

   return(digits);
}

//+------------------------------------------------------------------+
//| Normalizes the configured fixed lot to broker volume step.         |
//+------------------------------------------------------------------+
double NormalizeLotToStep(const double lot)
{
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(lotStep <= 0.0)
      return(NormalizeDouble(lot, GetVolumeDigits()));

   double steppedLot = MathRound(lot / lotStep) * lotStep;
   return(NormalizeDouble(steppedLot, GetVolumeDigits()));
}


//+------------------------------------------------------------------+
//| Returns trade deviation points for the detected asset class.      |
//+------------------------------------------------------------------+
int TradeDeviationForAsset(const AssetClass assetClass)
{
   switch(assetClass)
   {
      case GOLD:   return(TradeDeviationGoldPoints);
      case SILVER: return(TradeDeviationSilverPoints);
      case OIL:    return(TradeDeviationOilPoints);
      case INDEX:  return(TradeDeviationIndexPoints);
      case FOREX:
      case UNKNOWN:
      default:     return(TradeDeviationForexPoints);
   }
}

//+------------------------------------------------------------------+
//| Checks for an existing position on this symbol and magic number.  |
//+------------------------------------------------------------------+
bool HasOpenPositionForSymbolMagic()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;

      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         return(true);
   }

   return(false);
}

//+------------------------------------------------------------------+
//| Performs Phase 3 validation and optional primary trade execution. |
//+------------------------------------------------------------------+
void EvaluatePhase3Execution()
{
   if(g_lastExecutionBarTime == g_lastM15BarTime)
      return;

   g_lastExecutionBarTime = g_lastM15BarTime;
   ResetExecutionDiagnostics("Execution evaluation started");
   g_execution.executionBarTime = g_lastM15BarTime;
   g_execution.enableTrading = EnableTrading;
   g_execution.hasOpenPositionSymbolMagic = HasOpenPositionForSymbolMagic();
   g_execution.lotRequested = g_assetParams.fixedLot;
   g_execution.freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);

   if(!g_signal.candidate)
   {
      g_execution.executionResult = "NO_CANDIDATE";
      g_execution.executionReason = "No Phase 2.1 candidate";
      return;
   }

   bool ready = ValidatePhase3ExecutionSetup();
   if(!ready)
   {
      g_execution.executionResult = EnableTrading ? "BLOCKED" : "DRY_RUN_BLOCKED";
      Print("[MoeBot v4 Phase3] ", g_execution.executionResult, ": ", g_execution.executionReason);
      return;
   }

   if(!EnableTrading)
   {
      g_execution.executionAllowed = true;
      g_execution.executionAttempted = false;
      g_execution.executionResult = "DRY_RUN_CANDIDATE_READY";
      g_execution.executionReason = "All execution-layer validation checks passed; trading disabled";
      Print("[MoeBot v4 Phase3] DRY_RUN_CANDIDATE_READY: ", g_signal.direction,
            " entry=", DoubleToString(g_execution.entryPrice, _Digits),
            " sl=", DoubleToString(g_execution.slPrice, _Digits),
            " tp=", DoubleToString(g_execution.tpPrice, _Digits),
            " lot=", DoubleToString(g_execution.lotNormalized, GetVolumeDigits()));
      return;
   }

   if(!RefreshPhase3MarketPricingAndRisk())
   {
      g_execution.executionAllowed = false;
      g_execution.executionAttempted = false;
      g_execution.executionResult = "BLOCKED";
      Print("[MoeBot v4 Phase3] BLOCKED: ", g_execution.executionReason);
      return;
   }

   g_execution.executionAllowed = true;
   g_execution.executionAttempted = true;
   bool callResult = false;
   if(g_signal.direction == "BUY")
      callResult = trade.Buy(g_execution.lotNormalized, _Symbol, g_execution.entryPrice, g_execution.slPrice, g_execution.tpPrice, "MoeBot Phase3 primary");
   else if(g_signal.direction == "SELL")
      callResult = trade.Sell(g_execution.lotNormalized, _Symbol, g_execution.entryPrice, g_execution.slPrice, g_execution.tpPrice, "MoeBot Phase3 primary");

   g_execution.executionRetcode = trade.ResultRetcode();
   g_execution.executionRetcodeDescription = trade.ResultRetcodeDescription();

   if(g_execution.executionRetcode == TRADE_RETCODE_DONE)
   {
      g_execution.executionResult = "TRADE_OPENED";
      g_execution.executionReason = StringFormat("retcode=%u %s order=%I64u deal=%I64u bool=%s",
                                                  g_execution.executionRetcode,
                                                  g_execution.executionRetcodeDescription,
                                                  trade.ResultOrder(),
                                                  trade.ResultDeal(),
                                                  callResult ? "true" : "false");
   }
   else
   {
      g_execution.executionResult = "TRADE_REJECTED";
      g_execution.executionReason = StringFormat("retcode=%u %s order=%I64u deal=%I64u bool=%s",
                                                  g_execution.executionRetcode,
                                                  g_execution.executionRetcodeDescription,
                                                  trade.ResultOrder(),
                                                  trade.ResultDeal(),
                                                  callResult ? "true" : "false");
   }

   Print("[MoeBot v4 Phase3] ", g_execution.executionResult, ": ", g_execution.executionReason);
}

//+------------------------------------------------------------------+
//| Validates Phase 3 execution setup without changing positions.     |
//+------------------------------------------------------------------+
bool ValidatePhase3ExecutionSetup()
{
   if(!g_signal.hardGatesPassed)
      return(BlockPhase3Execution("BLOCKED_HARD_GATES"));

   if(g_status.brokerBlockerActive)
      return(BlockPhase3Execution("BLOCKED_BROKER: " + g_status.brokerBlockerReason));

   if(g_execution.hasOpenPositionSymbolMagic)
      return(BlockPhase3Execution("BLOCKED_EXISTING_POSITION"));

   if(g_signal.direction != "BUY" && g_signal.direction != "SELL")
      return(BlockPhase3Execution("BLOCKED_INVALID_DIRECTION"));

   g_execution.lotNormalized = NormalizeLotToStep(g_assetParams.fixedLot);
   string lotReason = "";
   if(!IsLotValid(g_execution.lotNormalized, lotReason))
      return(BlockPhase3Execution("BLOCKED_LOT_INVALID: " + lotReason));

   return(RefreshPhase3MarketPricingAndRisk());
}


//+------------------------------------------------------------------+
//| Refreshes tick, spread, SL/TP, stops/freeze, and margin checks.   |
//+------------------------------------------------------------------+
bool RefreshPhase3MarketPricingAndRisk()
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick) || tick.ask <= 0.0 || tick.bid <= 0.0)
      return(BlockPhase3Execution("BLOCKED_INVALID_TICK"));

   g_execution.freshSpreadPoints = GetCurrentSpreadPoints();
   if(g_execution.freshSpreadPoints > g_assetParams.maxSpreadPoints)
      return(BlockPhase3Execution("BLOCKED_SPREAD_AT_EXECUTION"));

   if(g_h1Info.atrH1 <= 0.0)
      return(BlockPhase3Execution("BLOCKED_INVALID_ATR"));

   if(g_signal.direction == "BUY")
   {
      if(g_h1Info.lower <= 0.0)
         return(BlockPhase3Execution("BLOCKED_INVALID_ZONE_EDGE"));
      g_execution.entryPrice = tick.ask;
      g_execution.slPrice = g_h1Info.lower - (g_assetParams.atrBuffer * g_h1Info.atrH1);
      g_execution.tpPrice = g_execution.entryPrice + ((g_execution.entryPrice - g_execution.slPrice) * g_assetParams.minRR);
   }
   else if(g_signal.direction == "SELL")
   {
      if(g_h1Info.upper <= 0.0)
         return(BlockPhase3Execution("BLOCKED_INVALID_ZONE_EDGE"));
      g_execution.entryPrice = tick.bid;
      g_execution.slPrice = g_h1Info.upper + (g_assetParams.atrBuffer * g_h1Info.atrH1);
      g_execution.tpPrice = g_execution.entryPrice - ((g_execution.slPrice - g_execution.entryPrice) * g_assetParams.minRR);
   }
   else
      return(BlockPhase3Execution("BLOCKED_INVALID_DIRECTION"));

   g_execution.entryPrice = NormalizeDouble(g_execution.entryPrice, _Digits);
   g_execution.slPrice = NormalizeDouble(g_execution.slPrice, _Digits);
   g_execution.tpPrice = NormalizeDouble(g_execution.tpPrice, _Digits);
   g_execution.rr = g_assetParams.minRR;

   if(g_execution.entryPrice <= 0.0 || g_execution.slPrice <= 0.0 || g_execution.tpPrice <= 0.0)
      return(BlockPhase3Execution("BLOCKED_INVALID_SLTP"));

   if(g_signal.direction == "BUY")
      g_execution.riskPoints = (g_execution.entryPrice - g_execution.slPrice) / _Point;
   else
      g_execution.riskPoints = (g_execution.slPrice - g_execution.entryPrice) / _Point;

   if(g_execution.riskPoints <= 0.0)
      return(BlockPhase3Execution("BLOCKED_INVALID_RISK"));

   if(!ValidateStopsAndFreeze())
      return(false);

   ENUM_ORDER_TYPE orderType = (g_signal.direction == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcMargin(orderType, _Symbol, g_execution.lotNormalized, g_execution.entryPrice, g_execution.marginRequired))
      return(BlockPhase3Execution("BLOCKED_MARGIN"));

   g_execution.freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(g_execution.marginRequired > g_execution.freeMargin)
      return(BlockPhase3Execution("BLOCKED_MARGIN"));

   return(true);
}

//+------------------------------------------------------------------+
//| Records a Phase 3 execution blocker.                              |
//+------------------------------------------------------------------+
bool BlockPhase3Execution(const string reason)
{
   g_execution.executionAllowed = false;
   g_execution.executionReason = reason;
   return(false);
}

//+------------------------------------------------------------------+
//| Validates broker stops and freeze distances.                      |
//+------------------------------------------------------------------+
bool ValidateStopsAndFreeze()
{
   if(_Point <= 0.0)
      return(BlockPhase3Execution("BLOCKED_INVALID_RISK"));

   double slDistancePoints = 0.0;
   double tpDistancePoints = 0.0;
   if(g_signal.direction == "BUY")
   {
      slDistancePoints = (g_execution.entryPrice - g_execution.slPrice) / _Point;
      tpDistancePoints = (g_execution.tpPrice - g_execution.entryPrice) / _Point;
   }
   else
   {
      slDistancePoints = (g_execution.slPrice - g_execution.entryPrice) / _Point;
      tpDistancePoints = (g_execution.entryPrice - g_execution.tpPrice) / _Point;
   }

   if(slDistancePoints <= 0.0 || tpDistancePoints <= 0.0)
      return(BlockPhase3Execution("BLOCKED_INVALID_RISK"));

   long stopsLevel = 0;
   SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL, stopsLevel);
   if(stopsLevel > 0 && (slDistancePoints < stopsLevel || tpDistancePoints < stopsLevel))
      return(BlockPhase3Execution("BLOCKED_STOPS_LEVEL"));

   long freezeLevel = 0;
   SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL, freezeLevel);
   if(freezeLevel > 0 && (slDistancePoints < freezeLevel || tpDistancePoints < freezeLevel))
      return(BlockPhase3Execution("BLOCKED_FREEZE_LEVEL"));

   return(true);
}

//+------------------------------------------------------------------+
//| Builds the diagnostic block printed once per new M15 candle.       |
//+------------------------------------------------------------------+
string BuildDiagnosticText()
{
   string blockerText = g_status.brokerBlockerActive ? "YES" : "NO";
   string candidateText = g_signal.candidate ? "YES" : "NO";
   string hardGateText = g_signal.hardGatesPassed ? "YES" : "NO";
   string h1ValidText = g_h1Info.valid ? "YES" : "NO";
   string h1InvalidatedText = g_h1Info.invalidated ? "YES" : "NO";
   string m15BosText = g_m15Info.bos ? "YES" : "NO";
   string insideZoneText = g_m15Info.insideZone ? "YES" : "NO";
   string nearMissText = g_m15Info.nearMiss ? "YES" : "NO";
   string tooLateText = g_m15Info.tooLate ? "YES" : "NO";
   string warningZoneTouchText = g_signal.warningZoneTouch2Or3 ? "YES" : "NO";
   string warningNearMissText = g_signal.warningNearMissTrigger ? "YES" : "NO";
   string warningLowLiquidityText = g_signal.warningLowLiquidity ? "YES" : "NO";
   string warningNewsBlackoutText = g_signal.warningNewsBlackout ? "YES" : "NO";
   string growthEligibleText = g_signal.decisionGrowthEligible ? "YES" : "NO";
   string conservativeEligibleText = g_signal.decisionConservativeEligible ? "YES" : "NO";
   string transitionStartTimeText = g_transition.simulatedStandbyActive ? TimeToString(g_transition.simulatedStandbyStartTime, TIME_DATE|TIME_MINUTES) : "NONE";
   string executionBarTimeText = g_execution.executionBarTime > 0 ? TimeToString(g_execution.executionBarTime, TIME_DATE|TIME_MINUTES) : "NONE";
   string executionText = StringFormat(
      "Execution:\n"
      "enable_trading: %s\n"
      "has_open_position_symbol_magic: %s\n"
      "execution_bar_time: %s\n"
      "execution_allowed: %s\n"
      "execution_attempted: %s\n"
      "execution_result: %s\n"
      "execution_reason: %s\n"
      "execution_retcode: %u\n"
      "execution_retcode_description: %s\n"
      "entry_price: %.5f\n"
      "sl_price: %.5f\n"
      "tp_price: %.5f\n"
      "risk_points: %.2f\n"
      "rr: %.2f\n"
      "lot_requested: %.8f\n"
      "lot_normalized: %.8f\n"
      "fresh_spread_points: %d\n"
      "margin_required: %.2f\n"
      "free_margin: %.2f\n"
      "sl_type: H1_ZONE_EDGE_ATR_BUFFER\n"
      "tp_type: RR_PROJECTION_FROM_ZONE_SL\n\n",
      g_execution.enableTrading ? "YES" : "NO",
      g_execution.hasOpenPositionSymbolMagic ? "YES" : "NO",
      executionBarTimeText,
      g_execution.executionAllowed ? "YES" : "NO",
      g_execution.executionAttempted ? "YES" : "NO",
      g_execution.executionResult,
      g_execution.executionReason,
      g_execution.executionRetcode,
      g_execution.executionRetcodeDescription,
      g_execution.entryPrice,
      g_execution.slPrice,
      g_execution.tpPrice,
      g_execution.riskPoints,
      g_execution.rr,
      g_execution.lotRequested,
      g_execution.lotNormalized,
      g_execution.freshSpreadPoints,
      g_execution.marginRequired,
      g_execution.freeMargin);
   string transitionText = StringFormat(
      "Transition:\n"
      "transition_enabled: %s\n"
      "h4_directional: %s\n"
      "h4_direction: %s\n"
      "h4_exhaustion: %s\n"
      "h4_slope_weakening: %s\n"
      "h4_failed_to_extend: %s\n"
      "h4_slope_ratio: %.4f\n\n"
      "h1_opposite_bos: %s\n"
      "transition_direction: %s\n"
      "h1_bos_level: %.5f\n"
      "h1_bos_distance_atr: %.4f\n"
      "h1_trigger_close: %.5f\n"
      "h1_atr: %.5f\n\n"
      "m15_opposite_bos: %s\n"
      "m15_opposite_break_distance_atr: %.4f\n\n"
      "transition_warning: %s\n"
      "standby_recommended: %s\n"
      "simulated_standby_active: %s\n"
      "simulated_standby_direction: %s\n"
      "simulated_standby_start_time: %s\n"
      "simulated_standby_age_h1_bars: %d\n\n"
      "would_suppress_old_direction: %s\n"
      "would_allow_new_direction: %s\n\n"
      "exit_by_h4_flip: %s\n"
      "exit_by_transition_failure: %s\n"
      "exit_by_expiry: %s\n"
      "transition_exit_reason: %s\n"
      "transition_reason: %s\n\n",
      g_transition.enabled ? "YES" : "NO",
      g_transition.h4Directional ? "YES" : "NO",
      g_transition.h4Direction,
      g_transition.h4Exhaustion ? "YES" : "NO",
      g_transition.h4SlopeWeakening ? "YES" : "NO",
      g_transition.h4FailedToExtend ? "YES" : "NO",
      g_transition.h4SlopeRatio,
      g_transition.h1OppositeBOS ? "YES" : "NO",
      g_transition.transitionDirection,
      g_transition.h1BosLevel,
      g_transition.h1BosDistanceATR,
      g_transition.h1TriggerClose,
      g_transition.h1Atr,
      g_transition.m15OppositeBOS ? "YES" : "NO",
      g_transition.m15OppositeBreakDistanceATR,
      g_transition.transitionWarning ? "YES" : "NO",
      g_transition.standbyRecommended ? "YES" : "NO",
      g_transition.simulatedStandbyActive ? "YES" : "NO",
      g_transition.simulatedStandbyDirection,
      transitionStartTimeText,
      g_transition.simulatedStandbyAgeH1Bars,
      g_transition.wouldSuppressOldDirection ? "YES" : "NO",
      g_transition.wouldAllowNewDirection ? "YES" : "NO",
      g_transition.exitByH4Flip ? "YES" : "NO",
      g_transition.exitByTransitionFailure ? "YES" : "NO",
      g_transition.exitByExpiry ? "YES" : "NO",
      g_transition.exitReason,
      g_transition.reason);
   string availabilityText = StringFormat(
      "SignalAvailability:\n"
      "availability_enabled: %s\n"
      "nearest_setup_status: %s\n"
      "nearest_setup_direction: %s\n"
      "missing_gates_count: %d\n"
      "primary_blocker: %s\n"
      "secondary_blocker: %s\n"
      "h4_ready: %s\n"
      "h1_zone_ready: %s\n"
      "m15_trigger_ready: %s\n"
      "score_ready: %s\n"
      "warnings_ready: %s\n"
      "h4_readiness_reason: %s\n"
      "h1_readiness_reason: %s\n"
      "m15_readiness_reason: %s\n"
      "score_readiness_reason: %s\n"
      "warning_readiness_reason: %s\n"
      "current_score: %d\n"
      "required_score: %d\n"
      "warning_count: %d\n"
      "max_allowed_warnings: %d\n"
      "m15_bos_break_distance_atr: %.4f\n"
      "trigger_distance_from_zone_atr: %.4f\n"
      "trigger_body_ratio: %.4f\n"
      "h1_zone_age_bars: %.0f\n"
      "h1_touch_count: %d\n"
      "would_have_been_candidate_if: %s\n\n",
      g_availability.enabled ? "YES" : "NO",
      g_availability.nearestSetupStatus,
      g_availability.nearestSetupDirection,
      g_availability.missingGatesCount,
      g_availability.primaryBlocker,
      g_availability.secondaryBlocker,
      g_availability.h4Ready ? "YES" : "NO",
      g_availability.h1ZoneReady ? "YES" : "NO",
      g_availability.m15TriggerReady ? "YES" : "NO",
      g_availability.scoreReady ? "YES" : "NO",
      g_availability.warningsReady ? "YES" : "NO",
      g_availability.h4ReadinessReason,
      g_availability.h1ReadinessReason,
      g_availability.m15ReadinessReason,
      g_availability.scoreReadinessReason,
      g_availability.warningReadinessReason,
      g_availability.currentScore,
      g_availability.requiredScore,
      g_availability.warningCount,
      g_availability.maxAllowedWarnings,
      g_availability.m15BosBreakDistanceATR,
      g_availability.triggerDistanceFromZoneATR,
      g_availability.triggerBodyRatio,
      g_availability.h1ZoneAgeBars,
      g_availability.h1TouchCount,
      g_availability.wouldHaveBeenCandidateIf);
   string earlyTransitionText = StringFormat(
      "EarlyTransition:\n"
      "early_transition_enabled: %s\n"
      "early_transition_warning: %s\n"
      "transition_strength_score: %d\n"
      "transition_risk_label: %s\n"
      "transition_missing_piece: %s\n"
      "h4_exhaustion: %s\n"
      "h1_opposite_bos: %s\n"
      "m15_opposite_bos: %s\n"
      "h1_bos_distance_enough: %s\n"
      "h1_bos_distance_atr: %.4f\n"
      "required_h1_bos_distance_atr: %.4f\n"
      "m15_opposite_break_distance_atr: %.4f\n"
      "old_direction_risk: %s\n"
      "early_transition_reason: %s\n\n",
      g_earlyTransition.enabled ? "YES" : "NO",
      g_earlyTransition.earlyTransitionWarning ? "YES" : "NO",
      g_earlyTransition.transitionStrengthScore,
      g_earlyTransition.transitionRiskLabel,
      g_earlyTransition.transitionMissingPiece,
      g_earlyTransition.h4Exhaustion ? "YES" : "NO",
      g_earlyTransition.h1OppositeBos ? "YES" : "NO",
      g_earlyTransition.m15OppositeBos ? "YES" : "NO",
      g_earlyTransition.h1BosDistanceEnough ? "YES" : "NO",
      g_earlyTransition.h1BosDistanceATR,
      g_earlyTransition.requiredH1BosDistanceATR,
      g_earlyTransition.m15OppositeBreakDistanceATR,
      g_earlyTransition.oldDirectionRisk,
      g_earlyTransition.reason);

   return(StringFormat(
      "[MoeBot v4 Phase3]\n"
      "Symbol: %s\n"
      "AssetClass: %s\n"
      "Mode: %s\n"
      "State: %s\n"
      "Spread: %d\n"
      "MaxSpread: %d\n"
      "SelectedLot: %.2f\n"
      "ATR_Buffer: %.2f\n"
      "MinRR: %.2f\n"
      "ActiveThreshold: %d\n"
      "Config: H4_EMA=%d H1_EMA=%d ATR=%d H4_SlopeLookback=%d M15_BOSLookback=%d MaxAddOns=%d ManualNewsBlackout=%s\n"
      "BrokerBlocker: %s\n"
      "Reason: %s\n"
      "NextPhaseStatus: Phase 3 minimal primary execution; Phase 2.2 transition diagnostics retained and diagnostics-only.\n\n"
      "H4:\n"
      "H4Bias: %s\n"
      "H4_EMA50_Now: %.5f\n"
      "H4_EMA50_Past: %.5f\n"
      "H4_ATR14: %.5f\n"
      "H4_SlopeRatio: %.4f\n"
      "H4_DistanceFromEMA_ATR: %.4f\n"
      "H4_CrossCount: %d\n"
      "H4_Reason: %s\n\n"
      "H1:\n"
      "H1_ZoneValid: %s\n"
      "H1_ZoneSource: %s\n"
      "H1_ZoneCenter: %.5f\n"
      "H1_ZoneUpper: %.5f\n"
      "H1_ZoneLower: %.5f\n"
      "H1_ATR14: %.5f\n"
      "H1_ZoneAgeBars: %d\n"
      "H1_TouchCount: %d\n"
      "H1_ZoneInvalidated: %s\n"
      "H1_Reason: %s\n\n"
      "M15:\n"
      "M15_BOS: %s\n"
      "M15_Direction: %s\n"
      "M15_PriorHigh: %.5f\n"
      "M15_PriorLow: %.5f\n"
      "M15_TriggerOpen: %.5f\n"
      "M15_TriggerHigh: %.5f\n"
      "M15_TriggerLow: %.5f\n"
      "M15_TriggerClose: %.5f\n"
      "M15_TriggerBodyRatio: %.4f\n"
      "M15_BosBreakDistanceATR: %.4f\n"
      "M15_ATR14: %.5f\n"
      "M15_InsideZone: %s\n"
      "M15_NearMiss: %s\n"
      "M15_TooLate: %s\n"
      "M15_Reason: %s\n\n"
      "Scoring:\n"
      "score_total: %d\n"
      "score_base: %d\n"
      "score_bos_strength: %d\n"
      "score_h4_trend_quality: %d\n"
      "score_h4_ema_distance: %d\n"
      "score_h1_zone_source: %d\n"
      "score_h1_zone_freshness: %d\n"
      "score_m15_candle_body: %d\n"
      "score_trigger_location: %d\n"
      "bos_break_distance_atr: %.4f\n"
      "trigger_body_ratio: %.4f\n\n"
      "Warnings:\n"
      "warning_zone_touch_2_or_3: %s\n"
      "warning_near_miss_trigger: %s\n"
      "warning_low_liquidity: %s\n"
      "warning_news_blackout: %s\n"
      "warningCount: %d\n\n"
      "%s"
      "%s"
      "%s"
      "%s"
      "Signal:\n"
      "HardGatesPassed: %s\n"
      "Score: %d\n"
      "WarningCount: %d\n"
      "Threshold: %d\n"
      "decision_growth_eligible: %s\n"
      "decision_conservative_eligible: %s\n"
      "decision_label: %s\n"
      "Candidate: %s\n"
      "FinalDecision: %s\n"
      "FinalReason: %s",
      g_status.symbol,
      AssetClassToString(g_status.assetClass),
      ModeToString(Mode),
      StateToString(g_status.state),
      g_status.currentSpreadPoints,
      g_assetParams.maxSpreadPoints,
      g_status.selectedLot,
      g_assetParams.atrBuffer,
      g_assetParams.minRR,
      ActiveThreshold(),
      H4_EMA_Period,
      H1_EMA_Period,
      ATR_Period,
      H4_Slope_Lookback,
      M15_BOS_Lookback,
      MaxAddOns,
      UseManualNewsBlackout ? "YES" : "NO",
      blockerText,
      g_status.brokerBlockerReason,
      H4BiasToString(g_h4Info.bias),
      g_h4Info.emaNow,
      g_h4Info.emaPast,
      g_h4Info.atrH4,
      g_h4Info.slopeRatio,
      g_h4Info.distanceFromEmaATR,
      g_h4Info.crossCount,
      g_h4Info.reason,
      h1ValidText,
      g_h1Info.source,
      g_h1Info.center,
      g_h1Info.upper,
      g_h1Info.lower,
      g_h1Info.atrH1,
      g_h1Info.ageBars,
      g_h1Info.touchCount,
      h1InvalidatedText,
      g_h1Info.reason,
      m15BosText,
      g_m15Info.direction,
      g_m15Info.priorHigh,
      g_m15Info.priorLow,
      g_m15Info.triggerOpen,
      g_m15Info.triggerHigh,
      g_m15Info.triggerLow,
      g_m15Info.triggerClose,
      g_m15Info.triggerBodyRatio,
      g_m15Info.bosBreakDistanceATR,
      g_m15Info.atrM15,
      insideZoneText,
      nearMissText,
      tooLateText,
      g_m15Info.reason,
      g_signal.scoreTotal,
      g_signal.scoreBase,
      g_signal.scoreBosStrength,
      g_signal.scoreH4TrendQuality,
      g_signal.scoreH4EmaDistance,
      g_signal.scoreH1ZoneSource,
      g_signal.scoreH1ZoneFreshness,
      g_signal.scoreM15CandleBody,
      g_signal.scoreTriggerLocation,
      g_signal.bosBreakDistanceATR,
      g_signal.triggerBodyRatio,
      warningZoneTouchText,
      warningNearMissText,
      warningLowLiquidityText,
      warningNewsBlackoutText,
      g_signal.warningCount,
      transitionText,
      availabilityText,
      earlyTransitionText,
      executionText,
      hardGateText,
      g_signal.score,
      g_signal.warningCount,
      g_signal.threshold,
      growthEligibleText,
      conservativeEligibleText,
      g_signal.decisionLabel,
      candidateText,
      g_signal.decision,
      g_signal.reason));
}

//+------------------------------------------------------------------+
//| Converts H4 bias to text.                                          |
//+------------------------------------------------------------------+
string H4BiasToString(const H4Bias bias)
{
   switch(bias)
   {
      case Bullish: return("Bullish");
      case Bearish: return("Bearish");
      case Flat:    return("Flat");
      case Unknown: return("Unknown");
      default:      return("Unknown");
   }
}

//+------------------------------------------------------------------+
//| Converts state to text.                                            |
//+------------------------------------------------------------------+
string StateToString(const EAState state)
{
   switch(state)
   {
      case IDLE:             return("IDLE");
      case BIAS_ACTIVE:      return("BIAS_ACTIVE");
      case ZONE_VALID:       return("ZONE_VALID");
      case TRIGGER_PENDING:  return("TRIGGER_PENDING");
      case ENTERED:          return("ENTERED");
      case MANAGING:         return("MANAGING");
      case ADDON_ELIGIBLE:   return("ADDON_ELIGIBLE");
      case CLOSED:           return("CLOSED");
      case ZONE_EXPIRED:     return("ZONE_EXPIRED");
      case ZONE_INVALIDATED: return("ZONE_INVALIDATED");
      default:               return("UNKNOWN_STATE");
   }
}

//+------------------------------------------------------------------+
//| Converts asset class to text.                                      |
//+------------------------------------------------------------------+
string AssetClassToString(const AssetClass assetClass)
{
   switch(assetClass)
   {
      case FOREX:   return("FOREX");
      case GOLD:    return("GOLD");
      case SILVER:  return("SILVER");
      case OIL:     return("OIL");
      case INDEX:   return("INDEX");
      case UNKNOWN: return("UNKNOWN");
      default:      return("UNKNOWN");
   }
}

//+------------------------------------------------------------------+
//| Converts bot mode to text.                                         |
//+------------------------------------------------------------------+
string ModeToString(const BotMode mode)
{
   switch(mode)
   {
      case Conservative: return("Conservative");
      case Growth:       return("Growth");
      default:           return("Unknown");
   }
}

//+------------------------------------------------------------------+
//| Updates the current EA state.                                      |
//+------------------------------------------------------------------+
void SetState(const EAState newState)
{
   g_state = newState;
   g_status.state = g_state;
}
//+------------------------------------------------------------------+
