//+------------------------------------------------------------------+
//| MoeBot_v4_TrendPullback_Phase1_Diagnostic.mq5                    |
//| Phase 1 diagnostic skeleton only. No trade execution.            |
//+------------------------------------------------------------------+
#property strict
#property version   "4.01"
#property description "MoeBot v4 Trend Pullback Phase 1 diagnostic skeleton."
#property description "No strategy entries, martingale, grid, or trade execution are included."

//+------------------------------------------------------------------+
//| Bot operating modes                                               |
//+------------------------------------------------------------------+
enum BotMode
{
   Conservative = 0,
   Growth       = 1
};

//+------------------------------------------------------------------+
//| Supported asset classes                                           |
//+------------------------------------------------------------------+
enum AssetClass
{
   FOREX   = 0,
   GOLD    = 1,
   SILVER  = 2,
   OIL     = 3,
   INDEX   = 4,
   UNKNOWN = 5
};

//+------------------------------------------------------------------+
//| Higher-timeframe directional bias placeholder for later phases     |
//+------------------------------------------------------------------+
enum H4Bias
{
   Bullish = 0,
   Bearish = 1,
   Flat    = 2,
   Unknown = 3
};

//+------------------------------------------------------------------+
//| Future EA state machine states                                    |
//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input long    MagicNumber              = 404001;
input bool    EnableDebug              = true;
input BotMode Mode                     = Conservative;

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

input int     H4_EMA_Period            = 50;
input int     H1_EMA_Period            = 20;
input int     ATR_Period               = 14;
input int     H4_Slope_Lookback        = 6;
input int     M15_BOS_Lookback         = 5;

input int     ConservativeThreshold    = 75;
input int     GrowthThreshold          = 60;
input int     MaxAddOns                = 1;
input bool    UseManualNewsBlackout    = false;

//+------------------------------------------------------------------+
//| Asset-specific parameters loaded from the detected symbol class    |
//+------------------------------------------------------------------+
struct AssetParams
{
   AssetClass assetClass;
   double     fixedLot;
   int        maxSpreadPoints;
   double     atrBuffer;
   double     minRR;
};

//+------------------------------------------------------------------+
//| Snapshot used for logging and chart diagnostics                    |
//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
//| Global runtime state                                              |
//+------------------------------------------------------------------+
AssetParams      g_assetParams;
DiagnosticStatus g_status;
EAState          g_state          = IDLE;
datetime         g_lastM15BarTime = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   SetState(IDLE);

   g_assetParams = LoadAssetParams(DetectAssetClass(_Symbol));

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
      Print("[MoeBot v4 Phase1] WARNING: Unknown asset class for ", _Symbol, "; using Forex defaults.");

   if(EnableDebug)
      Print("[MoeBot v4 Phase1] Initialized on current chart symbol only: ", _Symbol);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
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
//| Detects whether a new M15 candle has opened                        |
//+------------------------------------------------------------------+
bool IsNewM15Bar()
{
   const datetime currentBarTime = iTime(_Symbol, PERIOD_M15, 0);

   if(currentBarTime <= 0)
      return(false);

   if(currentBarTime == g_lastM15BarTime)
      return(false);

   g_lastM15BarTime = currentBarTime;
   return(true);
}

//+------------------------------------------------------------------+
//| Refreshes the diagnostic snapshot and formatted output             |
//+------------------------------------------------------------------+
void UpdateDiagnosticStatus()
{
   g_status.symbol              = _Symbol;
   g_status.assetClass          = g_assetParams.assetClass;
   g_status.state               = g_state;
   g_status.currentSpreadPoints = GetCurrentSpreadPoints();
   g_status.selectedLot         = NormalizeLotToStep(g_assetParams.fixedLot);
   g_status.lastM15BarTime      = g_lastM15BarTime;

   string blockerReason = "None";
   g_status.brokerBlockerActive = CheckBrokerBlockers(g_status.selectedLot, blockerReason);
   g_status.brokerBlockerReason = blockerReason;
   g_status.debugText           = BuildDiagnosticText();
}

//+------------------------------------------------------------------+
//| Returns an uppercase copy of a string                              |
//| Compatible with MQL5 StringToUpper behavior by using local copy.   |
//+------------------------------------------------------------------+
string ToUpperCopy(const string value)
{
   string result = value;
   StringToUpper(result);
   return(result);
}

//+------------------------------------------------------------------+
//| Detects the asset class from the current chart symbol              |
//+------------------------------------------------------------------+
AssetClass DetectAssetClass(const string symbol)
{
   string upperSymbol = ToUpperCopy(symbol);

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
//| Loads default parameters for the detected asset class              |
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
//| Checks index symbols while allowing broker prefixes/suffixes       |
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
//| Checks common forex symbols while allowing broker suffixes         |
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
//| Performs hard broker/environment blocker checks without trading    |
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
      reason = "Expert Advisor trading is not allowed for this account";
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
//| Validates lot against broker min/max/step                          |
//+------------------------------------------------------------------+
bool IsLotValid(const double lot, string &reason)
{
   const double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   const double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   const double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(minLot <= 0.0 || maxLot <= 0.0 || lotStep <= 0.0)
   {
      reason = "Unable to read broker lot constraints";
      return(false);
   }

   if(lot < minLot || lot > maxLot)
   {
      reason = StringFormat("Selected lot %.8f is outside broker min/max limits %.8f - %.8f",
                            lot, minLot, maxLot);
      return(false);
   }

   const double steps      = MathRound((lot - minLot) / lotStep);
   const double alignedLot = NormalizeDouble(minLot + (steps * lotStep), GetVolumeDigits(lotStep));

   if(MathAbs(alignedLot - lot) > 0.0000001)
   {
      reason = StringFormat("Selected lot %.8f is not aligned to broker lot step %.8f",
                            lot, lotStep);
      return(false);
   }

   reason = "None";
   return(true);
}

//+------------------------------------------------------------------+
//| Performs a basic margin availability check without sending orders  |
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

   const double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(marginRequired > freeMargin)
   {
      reason = StringFormat("Insufficient free margin. Required=%.2f Free=%.2f",
                            marginRequired, freeMargin);
      return(false);
   }

   reason = "None";
   return(true);
}

//+------------------------------------------------------------------+
//| Returns the current spread in points                               |
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
//| Calculates volume digits from broker lot step                      |
//+------------------------------------------------------------------+
int GetVolumeDigits(const double lotStep)
{
   if(lotStep <= 0.0)
      return(2);

   int digits = 0;
   double value = lotStep;

   while(digits < 8 && MathAbs(value - MathRound(value)) > 0.00000001)
   {
      value *= 10.0;
      digits++;
   }

   return(digits);
}

//+------------------------------------------------------------------+
//| Normalizes the configured fixed lot to broker volume step          |
//+------------------------------------------------------------------+
double NormalizeLotToStep(const double lot)
{
   const double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   const double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   const double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(minLot <= 0.0 || maxLot <= 0.0 || lotStep <= 0.0)
      return(NormalizeDouble(lot, 2));

   const int digits = GetVolumeDigits(lotStep);

   if(lot < minLot || lot > maxLot)
      return(NormalizeDouble(lot, digits));

   const double steps      = MathRound((lot - minLot) / lotStep);
   const double alignedLot = minLot + (steps * lotStep);

   return(NormalizeDouble(alignedLot, digits));
}

//+------------------------------------------------------------------+
//| Returns the active score threshold based on current mode           |
//+------------------------------------------------------------------+
int ActiveThreshold()
{
   if(Mode == Growth)
      return(GrowthThreshold);

   return(ConservativeThreshold);
}

//+------------------------------------------------------------------+
//| Converts bool to text                                              |
//+------------------------------------------------------------------+
string BoolToText(const bool value)
{
   return(value ? "true" : "false");
}

//+------------------------------------------------------------------+
//| Formats lot value with broker volume digits                        |
//+------------------------------------------------------------------+
string FormatLot(const double lot)
{
   const double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   return(DoubleToString(lot, GetVolumeDigits(lotStep)));
}

//+------------------------------------------------------------------+
//| Builds the diagnostic block printed once per new M15 candle        |
//+------------------------------------------------------------------+
string BuildDiagnosticText()
{
   const string blockerText = g_status.brokerBlockerActive ? "YES" : "NO";

   return(StringFormat(
      "[MoeBot v4 Phase1]\n"
      "Symbol: %s\n"
      "AssetClass: %s\n"
      "Mode: %s\n"
      "State: %s\n"
      "Spread: %d\n"
      "MaxSpread: %d\n"
      "SelectedLot: %s\n"
      "ATR_Buffer: %.2f\n"
      "MinRR: %.2f\n"
      "ActiveThreshold: %d\n"
      "BrokerBlocker: %s\n"
      "Reason: %s\n"
      "Config: Magic=%s | H4_EMA=%d | H1_EMA=%d | ATR=%d | H4SlopeLookback=%d | M15BOS=%d | MaxAddOns=%d | ManualNews=%s\n"
      "NextPhaseStatus: Phase 1 only - no strategy analysis and no trade execution.",
      g_status.symbol,
      AssetClassToString(g_status.assetClass),
      ModeToString(Mode),
      StateToString(g_status.state),
      g_status.currentSpreadPoints,
      g_assetParams.maxSpreadPoints,
      FormatLot(g_status.selectedLot),
      g_assetParams.atrBuffer,
      g_assetParams.minRR,
      ActiveThreshold(),
      blockerText,
      g_status.brokerBlockerReason,
      IntegerToString(MagicNumber),
      H4_EMA_Period,
      H1_EMA_Period,
      ATR_Period,
      H4_Slope_Lookback,
      M15_BOS_Lookback,
      MaxAddOns,
      BoolToText(UseManualNewsBlackout)));
}

//+------------------------------------------------------------------+
//| Converts state to text                                             |
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
//| Converts asset class to text                                       |
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
//| Converts bot mode to text                                          |
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
//| Converts H4 bias to text placeholder for future phases             |
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
//| Updates the current EA state                                       |
//+------------------------------------------------------------------+
void SetState(const EAState newState)
{
   g_state = newState;
   g_status.state = g_state;
}
//+------------------------------------------------------------------+
