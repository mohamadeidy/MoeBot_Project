//+------------------------------------------------------------------+
//|                 B&M Bot v1 Breakout Trend Rebuild                 |
//| Clean opportunity-first MT5 Expert Advisor.                       |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "B&M Bot v1 DEMO - Breakout, retest, continuation, running SL/TP."

#include <Trade/Trade.mqh>
CTrade trade;

enum BMRunMode { BM_DIAGNOSTICS_ONLY = 0, BM_DEMO_EXECUTION = 1, BM_DEMO_EXECUTION_WITH_MANAGEMENT = 2 };
enum BMMarketState { BM_STATE_UNKNOWN, BM_STATE_RANGE, BM_STATE_BREAKOUT_UP, BM_STATE_BREAKOUT_DOWN, BM_STATE_PULLBACK_WAIT_BUY, BM_STATE_PULLBACK_WAIT_SELL, BM_STATE_CONTINUATION_READY_BUY, BM_STATE_CONTINUATION_READY_SELL, BM_STATE_BIAS_WEAKENING, BM_STATE_OLD_SELL_FAILED, BM_STATE_OLD_BUY_FAILED, BM_STATE_TRADE_ACTIVE };
enum BMDirection { BM_DIR_NONE, BM_DIR_BUY, BM_DIR_SELL };
enum BMEntryType { BM_ENTRY_NONE, BM_ENTRY_BREAKOUT, BM_ENTRY_RETEST, BM_ENTRY_CONTINUATION };

input bool EnableTrading = true;
input bool AllowLiveTrading = false;
input bool EnableTradeManagement = true;
input bool AllowDirectExitOnOppositeBreak = false;
input long MagicNumber = 26070101;
input string SymbolsToTrade = "XAUUSD,XAGUSD,WTI,US30,US100,US500,GER30,EURUSD_,GBPUSD_,USDJPY_,AUDUSD_,USDCAD_,USDCHF_";
input bool PrintEveryScan = true;
input bool PrintNoTradeReasons = true;
input BMRunMode RunMode = BM_DEMO_EXECUTION_WITH_MANAGEMENT;
input int DonchianPeriodM15 = 20;
input int DonchianPeriodH1 = 20;
input int ATRPeriodM15 = 14;
input int ATRPeriodH1 = 14;
input int EMAFastPeriod = 50;
input int EMASlowPeriod = 100;
input int SwingLookback = 3;
input double BreakoutBufferATR = 0.15;
input double MinBodyPercent = 0.50;
input double CloseStrengthPercent = 0.75;
input double TooLateATR = 1.50;
input double RetestBufferATR = 0.30;
input int SetupExpiryM15Bars = 12;
input double MinSL_ATR = 0.40;
input double MaxSL_ATR = 6.00;
input double SLBufferATR = 0.25;
input double BreakEvenAtR = 1.00;
input double BreakEvenBufferATR = 0.05;
input bool UseProgressiveProfitLock = true;
input double ProfitLockTriggerR_1 = 1.50;
input double ProfitLockSecureR_1 = 0.50;
input double ProfitLockTriggerR_2 = 2.00;
input double ProfitLockSecureR_2 = 1.00;
input double ProfitLockTriggerR_3 = 2.50;
input double ProfitLockSecureR_3 = 1.50;
input double ProfitLockTriggerR_4 = 3.00;
input double ProfitLockSecureR_4 = 2.00;
input double ATRTrailMultiplier = 2.00;
input bool UseStructureTrailing = true;
input bool UseATRTrailing = true;
input double InitialTP_R = 2.00;
input double TPExtendATR = 1.50;
input bool UseRunningTP = true;
input bool ExtendTPBeforeHit = true;
input double TPPreExtendPercent = 0.75;
input bool RequireSLProtectedBeforeTPExtend = true;
input int MaxSpreadPoints_XAUUSD = 150;
input int MaxSpreadPoints_XAGUSD = 150;
input int MaxSpreadPoints_WTI = 500;
input int MaxSpreadPoints_US30 = 500;
input int MaxSpreadPoints_US100 = 500;
input int MaxSpreadPoints_US500 = 500;
input int MaxSpreadPoints_GER30 = 500;
input int MaxSpreadPoints_EURUSD = 50;
input int MaxSpreadPoints_GBPUSD = 50;
input int MaxSpreadPoints_USDJPY = 50;
input int MaxSpreadPoints_AUDUSD = 50;
input int MaxSpreadPoints_USDCAD = 50;
input int MaxSpreadPoints_USDCHF = 50;
input double Lot_XAUUSD = 0.01;
input double Lot_XAGUSD = 0.01;
input double Lot_WTI = 0.01;
input double Lot_US30 = 0.01;
input double Lot_US100 = 0.01;
input double Lot_US500 = 0.01;
input double Lot_GER30 = 0.01;
input double Lot_EURUSD = 0.02;
input double Lot_GBPUSD = 0.02;
input double Lot_USDJPY = 0.02;
input double Lot_AUDUSD = 0.02;
input double Lot_USDCAD = 0.02;
input double Lot_USDCHF = 0.02;

const ENUM_TIMEFRAMES BM_TF_CONTEXT = PERIOD_H4;
const ENUM_TIMEFRAMES BM_TF_STRUCTURE = PERIOD_H1;
const ENUM_TIMEFRAMES BM_TF_ENTRY = PERIOD_M15;

struct BMSymbolContext
{
   string symbol; bool tradable; int spreadPoints; double lot; BMDirection h4ContextDirection; BMDirection h1StructureDirection; BMMarketState m15State; BMMarketState marketState;
   double donchianHighM15; double donchianLowM15; double donchianHighH1; double donchianLowH1; double atrM15; double atrH1; double ema50M15; double ema100M15;
   double lastSwingHighM15; double lastSwingLowM15; double breakoutLevel; BMDirection breakoutDirection; double openPrice; double highPrice; double lowPrice; double closePrice; double candleBody; double candleRange;
   bool bullishCandle; bool bearishCandle; bool bodyStrong; bool closeStrength; bool buyCloseStrength; bool sellCloseStrength; bool buyBodyStrong; bool sellBodyStrong; bool breakoutConfirmed; bool tooLate; bool slValid; bool spreadValid; string action; string reason; datetime signalTime;
   BMMarketState oldBiasState; bool biasWeakening; bool oldSellFailed; bool oldBuyFailed; BMDirection newWatchDirection;
};
struct BMSetupState { string symbol; BMDirection direction; BMEntryType entryType; bool active; double breakoutLevel; datetime setupStartTime; datetime lastUpdateTime; bool invalidated; string invalidationReason; double highestSinceBreakout; double lowestSinceBreakout; double pullbackLow; double pullbackHigh; double microHighAfterPullback; double microLowAfterPullback; bool pullbackSeen; bool continuationReady; int barsSinceSetup; };
struct BMPositionState { string symbol; ulong ticket; BMDirection direction; double entryPrice; double currentSL; double currentTP; double initialRisk; double currentR; bool reachedBreakEven; double lastTrailLevel; double lastTPLevel; };

string g_symbols[]; BMSetupState g_setups[]; datetime g_lastM15Scan[]; BMDirection g_previousContext[]; BMPositionState g_positionStates[];

string DirText(BMDirection d){ if(d==BM_DIR_BUY) return "BUY"; if(d==BM_DIR_SELL) return "SELL"; return "NONE"; }
string StateText(BMMarketState s){ switch(s){ case BM_STATE_RANGE:return "RANGE"; case BM_STATE_BREAKOUT_UP:return "BREAKOUT_UP"; case BM_STATE_BREAKOUT_DOWN:return "BREAKOUT_DOWN"; case BM_STATE_PULLBACK_WAIT_BUY:return "PULLBACK_WAIT_BUY"; case BM_STATE_PULLBACK_WAIT_SELL:return "PULLBACK_WAIT_SELL"; case BM_STATE_CONTINUATION_READY_BUY:return "CONTINUATION_READY_BUY"; case BM_STATE_CONTINUATION_READY_SELL:return "CONTINUATION_READY_SELL"; case BM_STATE_BIAS_WEAKENING:return "BIAS_WEAKENING"; case BM_STATE_OLD_SELL_FAILED:return "OLD_SELL_FAILED"; case BM_STATE_OLD_BUY_FAILED:return "OLD_BUY_FAILED"; case BM_STATE_TRADE_ACTIVE:return "TRADE_ACTIVE"; default:return "UNKNOWN"; } }
string EntryText(BMEntryType e){ if(e==BM_ENTRY_BREAKOUT) return "BREAKOUT"; if(e==BM_ENTRY_RETEST) return "RETEST"; if(e==BM_ENTRY_CONTINUATION) return "CONTINUATION"; return "NONE"; }
void BMLog(string section,string msg){ Print("[B&M Bot] SECTION=",section," ",msg); }
string Upper(string s){ StringToUpper(s); return s; }

int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   ResolveSymbols();
   ArrayResize(g_setups,ArraySize(g_symbols)); ArrayResize(g_lastM15Scan,ArraySize(g_symbols)); ArrayResize(g_previousContext,ArraySize(g_symbols));
   for(int i=0;i<ArraySize(g_symbols);i++){ g_setups[i].symbol=g_symbols[i]; g_setups[i].active=false; g_lastM15Scan[i]=0; g_previousContext[i]=BM_DIR_NONE; }
   EventSetTimer(10);
   BMLog("CHART_READER","BOT=B&M_BOT DISPLAY_NAME=B&M_Bot RUNMODE="+(string)RunMode+" ACTION=INIT_COMPLETE");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ EventKillTimer(); }
void OnTick(){ ScanAll(false); if(EnableTradeManagement && RunMode==BM_DEMO_EXECUTION_WITH_MANAGEMENT) ManagePositions(); }
void OnTimer(){ ScanAll(false); }

void ResolveSymbols()
{
   string requested[]; int n=StringSplit(SymbolsToTrade,',',requested); ArrayResize(g_symbols,0);
   for(int i=0;i<n;i++)
   {
      string base=requested[i]; StringTrimLeft(base); StringTrimRight(base); if(base=="") continue;
      string resolved=""; bool tradeable=false;
      if(SymbolSelect(base,true)){ resolved=base; tradeable=IsSymbolTradeable(base); }
      if(resolved=="")
      {
         string ub=Upper(base); int total=SymbolsTotal(false);
         for(int j=0;j<total;j++){ string s=SymbolName(j,false); if(StringFind(Upper(s),ub)>=0){ SymbolSelect(s,true); if(IsSymbolTradeable(s)){ resolved=s; tradeable=true; break; } if(resolved=="") resolved=s; } }
      }
      if(resolved=="") BMLog("ERROR","REQUESTED_SYMBOL="+base+" RESOLVED_SYMBOL=NONE STATUS=NOT_FOUND ACTION=SKIP");
      else { int k=ArraySize(g_symbols); ArrayResize(g_symbols,k+1); g_symbols[k]=resolved; BMLog("CHART_READER","REQUESTED_SYMBOL="+base+" RESOLVED_SYMBOL="+resolved+" STATUS="+(tradeable?"TRADEABLE":"FOUND_NOT_TRADEABLE")); }
   }
}

bool IsSymbolTradeable(string symbol){ long mode=0; return SymbolInfoInteger(symbol,SYMBOL_TRADE_MODE,mode) && mode!=SYMBOL_TRADE_MODE_DISABLED; }
int DigitsFor(string s){ return (int)SymbolInfoInteger(s,SYMBOL_DIGITS); }
double NormalizePrice(string s,double p){ return NormalizeDouble(p,DigitsFor(s)); }

bool GetBufferValue(int handle,int shift,double &value){ double b[]; ArraySetAsSeries(b,true); if(handle==INVALID_HANDLE) return false; if(CopyBuffer(handle,0,shift,1,b)!=1){ IndicatorRelease(handle); return false; } value=b[0]; IndicatorRelease(handle); return value>0.0; }
bool GetATR(string s,ENUM_TIMEFRAMES tf,int period,double &v){ return GetBufferValue(iATR(s,tf,period),1,v); }
bool GetMA(string s,ENUM_TIMEFRAMES tf,int period,double &v){ return GetBufferValue(iMA(s,tf,period,0,MODE_EMA,PRICE_CLOSE),1,v); }

bool Donchian(MqlRates &r[],int start,int period,double &hi,double &lo)
{
   if(ArraySize(r)<=start+period) return false; hi=r[start].high; lo=r[start].low;
   for(int i=start;i<start+period;i++){ if(r[i].high>hi) hi=r[i].high; if(r[i].low<lo) lo=r[i].low; }
   return true;
}
bool Swing(MqlRates &r[],int look,double &hi,double &lo)
{
   if(ArraySize(r)<look*2+5) return false; hi=0.0; lo=0.0;
   for(int i=look+1;i<ArraySize(r)-look;i++)
   {
      bool sh=true, sl=true;
      for(int j=1;j<=look;j++){ if(r[i].high<=r[i-j].high || r[i].high<=r[i+j].high) sh=false; if(r[i].low>=r[i-j].low || r[i].low>=r[i+j].low) sl=false; }
      if(sh && hi==0.0) hi=r[i].high; if(sl && lo==0.0) lo=r[i].low; if(hi>0.0 && lo>0.0) return true;
   }
   hi=r[1].high; lo=r[1].low; return true;
}

bool BuildSymbolContext(string symbol,BMSymbolContext &ctx)
{
   ctx.symbol=symbol; ctx.tradable=IsSymbolTradeable(symbol); ctx.action="WAIT_BREAKOUT"; ctx.reason="CONTEXT_BUILT"; ctx.marketState=BM_STATE_UNKNOWN; ctx.m15State=BM_STATE_UNKNOWN; ctx.oldBiasState=BM_STATE_UNKNOWN; ctx.biasWeakening=false; ctx.oldSellFailed=false; ctx.oldBuyFailed=false; ctx.newWatchDirection=BM_DIR_NONE;
   if(!ctx.tradable){ BMLog("ERROR","SYMBOL="+symbol+" ERROR=DATA_ERROR REASON=SYMBOL_NOT_TRADEABLE ACTION=SKIP"); return false; }
   MqlRates m15[],h1[],h4[]; ArraySetAsSeries(m15,true); ArraySetAsSeries(h1,true); ArraySetAsSeries(h4,true);
   int needM15=MathMax(DonchianPeriodM15+SwingLookback*2+10,EMASlowPeriod+10); int needH1=DonchianPeriodH1+10; int needH4=EMASlowPeriod+10;
   if(CopyRates(symbol,BM_TF_ENTRY,0,needM15,m15)<needM15 || CopyRates(symbol,BM_TF_STRUCTURE,0,needH1,h1)<needH1 || CopyRates(symbol,BM_TF_CONTEXT,0,needH4,h4)<needH4){ BMLog("ERROR","SYMBOL="+symbol+" ERROR=DATA_ERROR REASON=INSUFFICIENT_RATES ACTION=SKIP"); return false; }
   double h4emaFast=0.0,h4emaSlow=0.0; if(!GetATR(symbol,BM_TF_ENTRY,ATRPeriodM15,ctx.atrM15) || !GetATR(symbol,BM_TF_STRUCTURE,ATRPeriodH1,ctx.atrH1) || !GetMA(symbol,BM_TF_ENTRY,EMAFastPeriod,ctx.ema50M15) || !GetMA(symbol,BM_TF_ENTRY,EMASlowPeriod,ctx.ema100M15) || !GetMA(symbol,BM_TF_CONTEXT,EMAFastPeriod,h4emaFast) || !GetMA(symbol,BM_TF_CONTEXT,EMASlowPeriod,h4emaSlow)){ BMLog("ERROR","SYMBOL="+symbol+" ERROR=DATA_ERROR REASON=INDICATOR_COPY_FAILED ACTION=SKIP"); return false; }
   if(!Donchian(m15,2,DonchianPeriodM15,ctx.donchianHighM15,ctx.donchianLowM15) || !Donchian(h1,2,DonchianPeriodH1,ctx.donchianHighH1,ctx.donchianLowH1) || !Swing(m15,SwingLookback,ctx.lastSwingHighM15,ctx.lastSwingLowM15)){ BMLog("ERROR","SYMBOL="+symbol+" ERROR=DATA_ERROR REASON=LEVEL_BUILD_FAILED ACTION=SKIP"); return false; }
   ctx.signalTime=m15[1].time; ctx.openPrice=m15[1].open; ctx.highPrice=m15[1].high; ctx.lowPrice=m15[1].low; ctx.closePrice=m15[1].close; ctx.candleBody=MathAbs(ctx.closePrice-ctx.openPrice); ctx.candleRange=ctx.highPrice-ctx.lowPrice;
   ctx.bullishCandle=(ctx.closePrice>ctx.openPrice); ctx.bearishCandle=(ctx.closePrice<ctx.openPrice);
   ctx.bodyStrong=(ctx.candleRange>0.0 && ctx.candleBody>=MinBodyPercent*ctx.candleRange);
   bool closeUpper=(ctx.candleRange>0.0 && (ctx.closePrice-ctx.lowPrice)/ctx.candleRange>=CloseStrengthPercent); bool closeLower=(ctx.candleRange>0.0 && (ctx.highPrice-ctx.closePrice)/ctx.candleRange>=CloseStrengthPercent);
   ctx.buyCloseStrength=closeUpper; ctx.sellCloseStrength=closeLower; ctx.closeStrength=(ctx.buyCloseStrength || ctx.sellCloseStrength);
   ctx.buyBodyStrong=(ctx.bullishCandle && ctx.bodyStrong && ctx.buyCloseStrength);
   ctx.sellBodyStrong=(ctx.bearishCandle && ctx.bodyStrong && ctx.sellCloseStrength);
   ctx.h4ContextDirection=BM_DIR_NONE; if(h4[1].close>h4emaFast && h4[1].close>h4emaSlow) ctx.h4ContextDirection=BM_DIR_BUY; else if(h4[1].close<h4emaFast && h4[1].close<h4emaSlow) ctx.h4ContextDirection=BM_DIR_SELL;
   ctx.h1StructureDirection=BM_DIR_NONE; if(h1[1].close>ctx.donchianHighH1) ctx.h1StructureDirection=BM_DIR_BUY; else if(h1[1].close<ctx.donchianLowH1) ctx.h1StructureDirection=BM_DIR_SELL;
   ctx.spreadPoints=(int)SymbolInfoInteger(symbol,SYMBOL_SPREAD); ctx.lot=LotForSymbol(symbol); ctx.spreadValid=(ctx.spreadPoints<=MaxSpreadForSymbol(symbol));
   bool up=m15[1].close>ctx.donchianHighM15+BreakoutBufferATR*ctx.atrM15; bool dn=m15[1].close<ctx.donchianLowM15-BreakoutBufferATR*ctx.atrM15; ctx.breakoutConfirmed=false; ctx.tooLate=false; ctx.breakoutDirection=BM_DIR_NONE; ctx.breakoutLevel=0.0;
   if(m15[1].high>ctx.donchianHighM15 && m15[1].close<=ctx.donchianHighM15){ ctx.marketState=BM_STATE_RANGE; ctx.m15State=BM_STATE_RANGE; ctx.reason="FAKE_BREAKOUT_RISK"; ctx.action="WAIT_BREAKOUT"; }
   else if(m15[1].low<ctx.donchianLowM15 && m15[1].close>=ctx.donchianLowM15){ ctx.marketState=BM_STATE_RANGE; ctx.m15State=BM_STATE_RANGE; ctx.reason="FAKE_BREAKDOWN_RISK"; ctx.action="WAIT_BREAKOUT"; }
   else if(up && ctx.buyBodyStrong){ ctx.marketState=BM_STATE_BREAKOUT_UP; ctx.m15State=ctx.marketState; ctx.breakoutConfirmed=true; ctx.closeStrength=ctx.buyCloseStrength; ctx.breakoutDirection=BM_DIR_BUY; ctx.breakoutLevel=ctx.donchianHighM15; ctx.tooLate=(ctx.closePrice-ctx.breakoutLevel>TooLateATR*ctx.atrM15); ctx.action=ctx.tooLate?"WAIT_PULLBACK_OR_CONTINUATION":"EVALUATE_BUY"; }
   else if(dn && ctx.sellBodyStrong){ ctx.marketState=BM_STATE_BREAKOUT_DOWN; ctx.m15State=ctx.marketState; ctx.breakoutConfirmed=true; ctx.closeStrength=ctx.sellCloseStrength; ctx.breakoutDirection=BM_DIR_SELL; ctx.breakoutLevel=ctx.donchianLowM15; ctx.tooLate=(ctx.breakoutLevel-ctx.closePrice>TooLateATR*ctx.atrM15); ctx.action=ctx.tooLate?"WAIT_PULLBACK_OR_CONTINUATION":"EVALUATE_SELL"; }
   else { ctx.marketState=BM_STATE_RANGE; ctx.m15State=BM_STATE_RANGE; ctx.action="WAIT_BREAKOUT"; ctx.reason="PRICE_INSIDE_DONCHIAN_OR_WEAK_BREAK"; }
   if(ctx.h4ContextDirection==BM_DIR_SELL && ctx.breakoutDirection==BM_DIR_BUY){ ctx.biasWeakening=true; ctx.oldSellFailed=true; ctx.oldBiasState=BM_STATE_OLD_SELL_FAILED; ctx.newWatchDirection=BM_DIR_BUY; BMLog("ENTRY_DECISION","SYMBOL="+symbol+" STATE=BIAS_WEAKENING OLD_BIAS=SELL OPPOSITE_DIRECTION=BUY ACTION=WATCH_OPPOSITE_CONFIRMATION"); }
   if(ctx.h4ContextDirection==BM_DIR_BUY && ctx.breakoutDirection==BM_DIR_SELL){ ctx.biasWeakening=true; ctx.oldBuyFailed=true; ctx.oldBiasState=BM_STATE_OLD_BUY_FAILED; ctx.newWatchDirection=BM_DIR_SELL; BMLog("ENTRY_DECISION","SYMBOL="+symbol+" STATE=BIAS_WEAKENING OLD_BIAS=BUY OPPOSITE_DIRECTION=SELL ACTION=WATCH_OPPOSITE_CONFIRMATION"); }
   return true;
}

double LotForSymbol(string s)
{
   string u=Upper(s);
   if(StringFind(u,"XAUUSD")>=0) return Lot_XAUUSD;
   if(StringFind(u,"XAGUSD")>=0) return Lot_XAGUSD;
   if(StringFind(u,"WTI")>=0 || StringFind(u,"USOIL")>=0 || StringFind(u,"XTI")>=0) return Lot_WTI;
   if(StringFind(u,"US30")>=0) return Lot_US30;
   if(StringFind(u,"US100")>=0) return Lot_US100;
   if(StringFind(u,"US500")>=0) return Lot_US500;
   if(StringFind(u,"GER30")>=0 || StringFind(u,"DAX")>=0) return Lot_GER30;
   if(StringFind(u,"EURUSD")>=0) return Lot_EURUSD;
   if(StringFind(u,"GBPUSD")>=0) return Lot_GBPUSD;
   if(StringFind(u,"USDJPY")>=0) return Lot_USDJPY;
   if(StringFind(u,"AUDUSD")>=0) return Lot_AUDUSD;
   if(StringFind(u,"USDCAD")>=0) return Lot_USDCAD;
   if(StringFind(u,"USDCHF")>=0) return Lot_USDCHF;
   return 0.01;
}

int MaxSpreadForSymbol(string s)
{
   string u=Upper(s);
   if(StringFind(u,"XAUUSD")>=0) return MaxSpreadPoints_XAUUSD;
   if(StringFind(u,"XAGUSD")>=0) return MaxSpreadPoints_XAGUSD;
   if(StringFind(u,"WTI")>=0 || StringFind(u,"USOIL")>=0 || StringFind(u,"XTI")>=0) return MaxSpreadPoints_WTI;
   if(StringFind(u,"US30")>=0) return MaxSpreadPoints_US30;
   if(StringFind(u,"US100")>=0) return MaxSpreadPoints_US100;
   if(StringFind(u,"US500")>=0) return MaxSpreadPoints_US500;
   if(StringFind(u,"GER30")>=0 || StringFind(u,"DAX")>=0) return MaxSpreadPoints_GER30;
   if(StringFind(u,"EURUSD")>=0) return MaxSpreadPoints_EURUSD;
   if(StringFind(u,"GBPUSD")>=0) return MaxSpreadPoints_GBPUSD;
   if(StringFind(u,"USDJPY")>=0) return MaxSpreadPoints_USDJPY;
   if(StringFind(u,"AUDUSD")>=0) return MaxSpreadPoints_AUDUSD;
   if(StringFind(u,"USDCAD")>=0) return MaxSpreadPoints_USDCAD;
   if(StringFind(u,"USDCHF")>=0) return MaxSpreadPoints_USDCHF;
   return 999999;
}

void ScanAll(bool force)
{
   for(int i=0;i<ArraySize(g_symbols);i++)
   {
      datetime t=iTime(g_symbols[i],BM_TF_ENTRY,1); if(!force && t>0 && t==g_lastM15Scan[i]) continue; g_lastM15Scan[i]=t;
      BMSymbolContext ctx; if(!BuildSymbolContext(g_symbols[i],ctx)) continue; ApplyPreviousBiasFailure(i,ctx); PrintChartReader(ctx); EvaluateEntries(i,ctx); g_previousContext[i]=ctx.h4ContextDirection;
   }
}
void ApplyPreviousBiasFailure(int idx,BMSymbolContext &ctx)
{
   if(g_previousContext[idx]==BM_DIR_SELL && ctx.breakoutDirection==BM_DIR_BUY)
   {
      ctx.oldBiasState=BM_STATE_OLD_SELL_FAILED; ctx.oldSellFailed=true; ctx.biasWeakening=true; ctx.newWatchDirection=BM_DIR_BUY;
      BMLog("ENTRY_DECISION","SYMBOL="+ctx.symbol+" STATE=OLD_SELL_FAILED OLD_BIAS=SELL OPPOSITE_DIRECTION=BUY ACTION=WATCH_OPPOSITE_CONFIRMATION");
   }
   if(g_previousContext[idx]==BM_DIR_BUY && ctx.breakoutDirection==BM_DIR_SELL)
   {
      ctx.oldBiasState=BM_STATE_OLD_BUY_FAILED; ctx.oldBuyFailed=true; ctx.biasWeakening=true; ctx.newWatchDirection=BM_DIR_SELL;
      BMLog("ENTRY_DECISION","SYMBOL="+ctx.symbol+" STATE=OLD_BUY_FAILED OLD_BIAS=BUY OPPOSITE_DIRECTION=SELL ACTION=WATCH_OPPOSITE_CONFIRMATION");
   }
}

void PrintChartReader(BMSymbolContext &c){ if(PrintEveryScan) BMLog("CHART_READER","SYMBOL="+c.symbol+" TIME="+TimeToString(c.signalTime)+" H4_CONTEXT="+DirText(c.h4ContextDirection)+" H1_STRUCTURE="+DirText(c.h1StructureDirection)+" M15_STATE="+StateText(c.marketState)+" DONCHIAN_HIGH_M15="+DoubleToString(c.donchianHighM15,DigitsFor(c.symbol))+" DONCHIAN_LOW_M15="+DoubleToString(c.donchianLowM15,DigitsFor(c.symbol))+" DONCHIAN_HIGH_H1="+DoubleToString(c.donchianHighH1,DigitsFor(c.symbol))+" DONCHIAN_LOW_H1="+DoubleToString(c.donchianLowH1,DigitsFor(c.symbol))+" ATR_M15="+DoubleToString(c.atrM15,DigitsFor(c.symbol))+" ATR_H1="+DoubleToString(c.atrH1,DigitsFor(c.symbol))+" EMA_CONTEXT=M15_EMA50_"+DoubleToString(c.ema50M15,DigitsFor(c.symbol))+"_EMA100_"+DoubleToString(c.ema100M15,DigitsFor(c.symbol))+" LAST_SWING_HIGH_M15="+DoubleToString(c.lastSwingHighM15,DigitsFor(c.symbol))+" LAST_SWING_LOW_M15="+DoubleToString(c.lastSwingLowM15,DigitsFor(c.symbol))+" BULLISH_CANDLE="+(c.bullishCandle?"true":"false")+" BEARISH_CANDLE="+(c.bearishCandle?"true":"false")+" BUY_CLOSE_STRENGTH="+(c.buyCloseStrength?"true":"false")+" SELL_CLOSE_STRENGTH="+(c.sellCloseStrength?"true":"false")+" BUY_BODY_STRONG="+(c.buyBodyStrong?"true":"false")+" SELL_BODY_STRONG="+(c.sellBodyStrong?"true":"false")+" SPREAD_POINTS="+(string)c.spreadPoints+" OLD_BIAS_STATE="+StateText(c.oldBiasState)+" BIAS_WEAKENING="+(c.biasWeakening?"true":"false")+" NEW_WATCH_DIRECTION="+DirText(c.newWatchDirection)+" ACTION="+c.action); }

void EvaluateEntries(int idx,BMSymbolContext &c)
{
   if(c.breakoutConfirmed){ if(c.tooLate){ ActivateSetup(idx,c,c.breakoutDirection,BM_ENTRY_BREAKOUT); NoTrade(c,c.breakoutDirection,"TOO_LATE_DO_NOT_CHASE","WAIT_PULLBACK_OR_CONTINUATION"); } else AttemptOpen(c,c.breakoutDirection,BM_ENTRY_BREAKOUT,c.breakoutLevel); return; }
   if(g_setups[idx].active) EvaluateSetup(idx,c); else NoTrade(c,BM_DIR_NONE,c.reason,"WAIT_BREAKOUT");
}
void ActivateSetup(int idx,BMSymbolContext &c,BMDirection d,BMEntryType e){ g_setups[idx].symbol=c.symbol; g_setups[idx].direction=d; g_setups[idx].entryType=e; g_setups[idx].active=true; g_setups[idx].breakoutLevel=c.breakoutLevel; g_setups[idx].setupStartTime=c.signalTime; g_setups[idx].lastUpdateTime=c.signalTime; g_setups[idx].invalidated=false; g_setups[idx].highestSinceBreakout=c.highPrice; g_setups[idx].lowestSinceBreakout=c.lowPrice; g_setups[idx].pullbackLow=0.0; g_setups[idx].pullbackHigh=0.0; g_setups[idx].microHighAfterPullback=0.0; g_setups[idx].microLowAfterPullback=0.0; g_setups[idx].pullbackSeen=false; g_setups[idx].continuationReady=false; g_setups[idx].barsSinceSetup=0; }
void EvaluateSetup(int idx,BMSymbolContext &c)
{
   BMSetupState s=g_setups[idx];
   s.barsSinceSetup++;
   if(s.barsSinceSetup>SetupExpiryM15Bars){ g_setups[idx]=s; CancelSetup(idx,c,"SETUP_EXPIRED"); return; }

   bool hadPullbackBefore=s.pullbackSeen;
   double prevMicroHigh=s.microHighAfterPullback;
   double prevMicroLow=s.microLowAfterPullback;

   if(c.highPrice>s.highestSinceBreakout) s.highestSinceBreakout=c.highPrice;
   if(c.lowPrice<s.lowestSinceBreakout) s.lowestSinceBreakout=c.lowPrice;

   double retestBuffer=RetestBufferATR*c.atrM15;
   double buyRetestCeiling=s.breakoutLevel+retestBuffer;
   double buyRetestFloor=s.breakoutLevel-retestBuffer;
   double sellRetestCeiling=s.breakoutLevel+retestBuffer;
   double sellRetestFloor=s.breakoutLevel-retestBuffer;

   if(s.direction==BM_DIR_BUY && c.closePrice<s.breakoutLevel){ g_setups[idx]=s; CancelSetup(idx,c,"BUY_RETEST_INVALIDATED_CLOSE_BELOW_BREAKOUT"); return; }
   if(s.direction==BM_DIR_SELL && c.closePrice>s.breakoutLevel){ g_setups[idx]=s; CancelSetup(idx,c,"SELL_RETEST_INVALIDATED_CLOSE_ABOVE_BREAKDOWN"); return; }

   bool buyPullbackTouch=(s.direction==BM_DIR_BUY && c.lowPrice<=buyRetestCeiling && c.closePrice>=buyRetestFloor);
   bool sellPullbackTouch=(s.direction==BM_DIR_SELL && c.highPrice>=sellRetestFloor && c.closePrice<=sellRetestCeiling);

   if(buyPullbackTouch)
   {
      s.pullbackSeen=true;
      s.pullbackLow=(s.pullbackLow==0.0?c.lowPrice:MathMin(s.pullbackLow,c.lowPrice));
      if(s.microHighAfterPullback==0.0) s.microHighAfterPullback=c.highPrice;
   }
   if(sellPullbackTouch)
   {
      s.pullbackSeen=true;
      s.pullbackHigh=(s.pullbackHigh==0.0?c.highPrice:MathMax(s.pullbackHigh,c.highPrice));
      if(s.microLowAfterPullback==0.0) s.microLowAfterPullback=c.lowPrice;
   }

   bool retest=(s.direction==BM_DIR_BUY && s.pullbackSeen && c.buyBodyStrong && c.closePrice>=s.breakoutLevel) ||
               (s.direction==BM_DIR_SELL && s.pullbackSeen && c.sellBodyStrong && c.closePrice<=s.breakoutLevel);

   bool buyStillNotTooExtended=(c.closePrice-s.breakoutLevel<=TooLateATR*c.atrM15);
   bool sellStillNotTooExtended=(s.breakoutLevel-c.closePrice<=TooLateATR*c.atrM15);

   bool buyContinuation=(s.direction==BM_DIR_BUY && hadPullbackBefore && s.pullbackLow>0.0 && prevMicroHigh>0.0 && c.closePrice>prevMicroHigh && c.buyBodyStrong && buyStillNotTooExtended);
   bool sellContinuation=(s.direction==BM_DIR_SELL && hadPullbackBefore && s.pullbackHigh>0.0 && prevMicroLow>0.0 && c.closePrice<prevMicroLow && c.sellBodyStrong && sellStillNotTooExtended);

   s.continuationReady=(buyContinuation || sellContinuation);

   if(s.pullbackSeen)
   {
      if(s.direction==BM_DIR_BUY)
      {
         if(s.microHighAfterPullback==0.0 || c.highPrice>s.microHighAfterPullback) s.microHighAfterPullback=c.highPrice;
      }
      if(s.direction==BM_DIR_SELL)
      {
         if(s.microLowAfterPullback==0.0 || c.lowPrice<s.microLowAfterPullback) s.microLowAfterPullback=c.lowPrice;
      }
   }

   BMLog("ENTRY_DECISION","SYMBOL="+c.symbol+" DIRECTION="+DirText(s.direction)+" ENTRY_TYPE="+EntryText(s.entryType)+" PULLBACK_SEEN="+(s.pullbackSeen?"true":"false")+" MICRO_HIGH_AFTER_PULLBACK="+DoubleToString(s.microHighAfterPullback,DigitsFor(c.symbol))+" MICRO_LOW_AFTER_PULLBACK="+DoubleToString(s.microLowAfterPullback,DigitsFor(c.symbol))+" CONTINUATION_READY="+(s.continuationReady?"true":"false")+" BUY_BODY_STRONG="+(c.buyBodyStrong?"true":"false")+" SELL_BODY_STRONG="+(c.sellBodyStrong?"true":"false")+" ACTION=SETUP_TRACKING");

   g_setups[idx]=s;
   if(retest){ c.marketState=(s.direction==BM_DIR_BUY?BM_STATE_PULLBACK_WAIT_BUY:BM_STATE_PULLBACK_WAIT_SELL); AttemptOpen(c,s.direction,BM_ENTRY_RETEST,s.breakoutLevel); }
   else if(s.continuationReady){ c.marketState=(s.direction==BM_DIR_BUY?BM_STATE_CONTINUATION_READY_BUY:BM_STATE_CONTINUATION_READY_SELL); AttemptOpen(c,s.direction,BM_ENTRY_CONTINUATION,s.breakoutLevel); }
   else
   {
      string waitReason="SETUP_ACTIVE_WAITING_FOR_RETEST_OR_CONTINUATION";
      if(s.direction==BM_DIR_BUY && !buyStillNotTooExtended && !s.pullbackSeen) waitReason="STILL_TOO_EXTENDED_WAIT_STRUCTURE";
      if(s.direction==BM_DIR_SELL && !sellStillNotTooExtended && !s.pullbackSeen) waitReason="STILL_TOO_EXTENDED_WAIT_STRUCTURE";
      NoTrade(c,s.direction,waitReason,"WATCH");
   }
}
void CancelSetup(int idx,BMSymbolContext &c,string reason){ g_setups[idx].active=false; BMLog("SETUP_CANCEL","SYMBOL="+c.symbol+" DIRECTION="+DirText(g_setups[idx].direction)+" REASON="+reason+" ACTION=CANCEL_SETUP"); }
void NoTrade(BMSymbolContext &c,BMDirection d,string reason,string next){ if(PrintNoTradeReasons) BMLog("NO_TRADE","SYMBOL="+c.symbol+" DIRECTION="+DirText(d)+" REASON="+reason+" NEXT_ACTION="+next); }

bool HasConflict(string s,BMDirection d){ for(int i=PositionsTotal()-1;i>=0;i--){ ulong ticket=PositionGetTicket(i); if(ticket>0 && PositionSelectByTicket(ticket) && PositionGetString(POSITION_SYMBOL)==s && PositionGetInteger(POSITION_MAGIC)==MagicNumber){ long type=PositionGetInteger(POSITION_TYPE); if((d==BM_DIR_BUY && type==POSITION_TYPE_SELL) || (d==BM_DIR_SELL && type==POSITION_TYPE_BUY) || (d!=BM_DIR_NONE)) return true; } } return false; }
bool StopsAllowOpen(string symbol,BMDirection direction,double entry,double sl,double tp,string &reason)
{
   int stops=(int)SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double minDistance=(double)MathMax(stops,(int)SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL))*SymbolInfoDouble(symbol,SYMBOL_POINT);
   if(minDistance<=0.0) return true;
   if(direction==BM_DIR_BUY && (entry-sl<minDistance || tp-entry<minDistance)){ reason="BROKER_STOPS_LEVEL_TOO_CLOSE"; return false; }
   if(direction==BM_DIR_SELL && (sl-entry<minDistance || entry-tp<minDistance)){ reason="BROKER_STOPS_LEVEL_TOO_CLOSE"; return false; }
   return true;
}

bool ValidateLot(string s,double lot,string &reason){ double min=SymbolInfoDouble(s,SYMBOL_VOLUME_MIN), max=SymbolInfoDouble(s,SYMBOL_VOLUME_MAX), step=SymbolInfoDouble(s,SYMBOL_VOLUME_STEP); if(lot<min || lot>max){ reason="LOT_OUT_OF_RANGE"; return false; } double steps=MathRound((lot-min)/step); if(MathAbs(min+steps*step-lot)>0.0000001){ reason="LOT_STEP_INVALID"; return false; } return true; }
bool CalcSLTP(BMSymbolContext &c,BMDirection d,double entry,double &sl,double &tp,string &reason)
{
   // DEMO execution fix:
   // The first version used the farthest structure SL, which rejected many clean index breakouts
   // as SL_TOO_WIDE. For demo testing we prefer the nearest valid logical SL:
   // 1) breakout-level buffer SL, or 2) recent swing SL, whichever is closer to entry while still valid.
   double breakoutSL=0.0;
   double swingSL=0.0;

   if(d==BM_DIR_BUY)
   {
      breakoutSL = c.breakoutLevel - SLBufferATR*c.atrM15;
      swingSL    = c.lastSwingLowM15;

      bool breakoutValid = (breakoutSL > 0.0 && breakoutSL < entry);
      bool swingValid    = (swingSL > 0.0 && swingSL < entry);

      if(breakoutValid && swingValid) sl = MathMax(breakoutSL, swingSL);  // closest SL below entry
      else if(breakoutValid)          sl = breakoutSL;
      else if(swingValid)             sl = swingSL;
      else { reason="NO_VALID_BUY_SL_CANDIDATE"; return false; }
   }
   else if(d==BM_DIR_SELL)
   {
      breakoutSL = c.breakoutLevel + SLBufferATR*c.atrM15;
      swingSL    = c.lastSwingHighM15;

      bool breakoutValid = (breakoutSL > 0.0 && breakoutSL > entry);
      bool swingValid    = (swingSL > 0.0 && swingSL > entry);

      if(breakoutValid && swingValid) sl = MathMin(breakoutSL, swingSL);  // closest SL above entry
      else if(breakoutValid)          sl = breakoutSL;
      else if(swingValid)             sl = swingSL;
      else { reason="NO_VALID_SELL_SL_CANDIDATE"; return false; }
   }
   else
   {
      reason="NO_DIRECTION_FOR_SL";
      return false;
   }

   sl=NormalizePrice(c.symbol,sl);
   double risk=MathAbs(entry-sl);
   if(risk<MinSL_ATR*c.atrM15){ reason="SL_TOO_TIGHT"; return false; }
   if(risk>MaxSL_ATR*c.atrM15){ reason="SL_TOO_WIDE"; return false; }

   tp=(d==BM_DIR_BUY?entry+InitialTP_R*risk:entry-InitialTP_R*risk);
   tp=NormalizePrice(c.symbol,tp);
   return true;
}
void AttemptOpen(BMSymbolContext &c,BMDirection d,BMEntryType e,double level)
{
   double entry=(d==BM_DIR_BUY?SymbolInfoDouble(c.symbol,SYMBOL_ASK):SymbolInfoDouble(c.symbol,SYMBOL_BID)); c.breakoutLevel=level; double sl=0.0,tp=0.0; string reason=""; bool slok=CalcSLTP(c,d,entry,sl,tp,reason); c.slValid=slok;
   string action=(RunMode==BM_DIAGNOSTICS_ONLY || !EnableTrading)?("WOULD_OPEN_"+DirText(d)):("OPEN_"+DirText(d));
   BMLog("ENTRY_DECISION","SYMBOL="+c.symbol+" DIRECTION="+DirText(d)+" ENTRY_TYPE="+EntryText(e)+" BREAKOUT_LEVEL="+DoubleToString(level,DigitsFor(c.symbol))+" CLOSE="+DoubleToString(c.closePrice,DigitsFor(c.symbol))+" ATR="+DoubleToString(c.atrM15,DigitsFor(c.symbol))+" BREAKOUT_CONFIRMED="+(c.breakoutConfirmed?"true":"false")+" BODY_STRONG="+(c.bodyStrong?"true":"false")+" CLOSE_STRENGTH="+(c.closeStrength?"true":"false")+" BUY_BODY_STRONG="+(c.buyBodyStrong?"true":"false")+" SELL_BODY_STRONG="+(c.sellBodyStrong?"true":"false")+" TOO_LATE="+(c.tooLate?"true":"false")+" SL_VALID="+(slok?"true":"false")+" SPREAD_VALID="+(c.spreadValid?"true":"false")+" ACTION="+action+" REASON="+(slok?"OPPORTUNITY_VALID":reason));
   if(!slok){ NoTrade(c,d,reason,"WAIT_NEXT_SETUP"); return; } if(!c.spreadValid){ NoTrade(c,d,"SPREAD_TOO_HIGH","WAIT_SPREAD_NORMALIZE"); return; } if(HasConflict(c.symbol,d)){ NoTrade(c,d,"CONFLICTING_MAGIC_POSITION_EXISTS","MANAGE_EXISTING_POSITION"); return; }
   string lotReason=""; if(!ValidateLot(c.symbol,c.lot,lotReason)){ NoTrade(c,d,lotReason,"CHECK_BROKER_VOLUME_RULES"); return; }
   if(!StopsAllowOpen(c.symbol,d,entry,sl,tp,reason)){ NoTrade(c,d,reason,"WAIT_VALID_BROKER_STOPS"); return; }
   if(!EnableTrading || RunMode==BM_DIAGNOSTICS_ONLY){ BMLog("ENTRY_DECISION","SYMBOL="+c.symbol+" DIRECTION="+DirText(d)+" ENTRY_TYPE="+EntryText(e)+" BREAKOUT_LEVEL="+DoubleToString(level,DigitsFor(c.symbol))+" CLOSE="+DoubleToString(c.closePrice,DigitsFor(c.symbol))+" ATR="+DoubleToString(c.atrM15,DigitsFor(c.symbol))+" BREAKOUT_CONFIRMED="+(c.breakoutConfirmed?"true":"false")+" BODY_STRONG="+(c.bodyStrong?"true":"false")+" CLOSE_STRENGTH="+(c.closeStrength?"true":"false")+" BUY_BODY_STRONG="+(c.buyBodyStrong?"true":"false")+" SELL_BODY_STRONG="+(c.sellBodyStrong?"true":"false")+" TOO_LATE="+(c.tooLate?"true":"false")+" SL_VALID=true SPREAD_VALID="+(c.spreadValid?"true":"false")+" ACTION=WOULD_OPEN_"+DirText(d)+" REASON=DIAGNOSTICS_OR_TRADING_DISABLED"); return; }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO && !AllowLiveTrading){ NoTrade(c,d,"LIVE_ACCOUNT_BLOCKED_ALLOW_LIVE_TRADING_FALSE","USE_DEMO_OR_ENABLE_ALLOW_LIVE_TRADING"); return; }
   bool ok=(d==BM_DIR_BUY)?trade.Buy(c.lot,c.symbol,0.0,sl,tp,"B&M Bot v1 "+EntryText(e)):trade.Sell(c.lot,c.symbol,0.0,sl,tp,"B&M Bot v1 "+EntryText(e));
   if(ok)
   {
      ulong openedTicket=FindLatestManagedPositionTicket(c.symbol,d);
      if(openedTicket>0 && PositionSelectByTicket(openedTicket))
         RegisterPositionState(openedTicket,c.symbol,d,PositionGetDouble(POSITION_PRICE_OPEN),PositionGetDouble(POSITION_SL),PositionGetDouble(POSITION_TP));
      BMLog("TRADE_OPEN","SYMBOL="+c.symbol+" DIRECTION="+DirText(d)+" ENTRY="+DoubleToString(entry,DigitsFor(c.symbol))+" LOT="+DoubleToString(c.lot,2)+" SL="+DoubleToString(sl,DigitsFor(c.symbol))+" INITIAL_TP="+DoubleToString(tp,DigitsFor(c.symbol))+" ENTRY_TYPE="+EntryText(e)+" REASON=ORDER_SENT");
   }
   else BMLog("ERROR","SYMBOL="+c.symbol+" ACTION=TRADE_REJECTED RETCODE="+(string)trade.ResultRetcode()+" COMMENT="+trade.ResultRetcodeDescription());
}

int FindPositionStateIndex(ulong ticket)
{
   for(int i=0;i<ArraySize(g_positionStates);i++)
   {
      if(g_positionStates[i].ticket==ticket)
         return i;
   }
   return -1;
}

void RegisterPositionState(ulong ticket,string symbol,BMDirection direction,double entry,double sl,double tp)
{
   if(ticket==0 || entry<=0.0 || sl<=0.0)
      return;

   double riskFromSL=MathAbs(entry-sl);
   double riskFromTP=0.0;
   if(tp>0.0 && InitialTP_R>0.0)
   {
      if(direction==BM_DIR_BUY && tp>entry)
         riskFromTP=(tp-entry)/InitialTP_R;
      if(direction==BM_DIR_SELL && tp<entry)
         riskFromTP=(entry-tp)/InitialTP_R;
   }

   double risk=(riskFromTP>0.0?riskFromTP:riskFromSL);
   if(risk<=0.0)
      return;

   int idx=FindPositionStateIndex(ticket);
   if(idx<0)
   {
      idx=ArraySize(g_positionStates);
      ArrayResize(g_positionStates,idx+1);
   }

   g_positionStates[idx].symbol=symbol;
   g_positionStates[idx].ticket=ticket;
   g_positionStates[idx].direction=direction;
   g_positionStates[idx].entryPrice=entry;
   g_positionStates[idx].currentSL=sl;
   g_positionStates[idx].currentTP=tp;
   g_positionStates[idx].initialRisk=risk;
   g_positionStates[idx].currentR=0.0;
   g_positionStates[idx].reachedBreakEven=false;
   g_positionStates[idx].lastTrailLevel=sl;
   g_positionStates[idx].lastTPLevel=tp;

   BMLog("POSITION_STATE",
         "SYMBOL="+symbol+
         " POSITION="+(string)ticket+
         " ENTRY="+DoubleToString(entry,DigitsFor(symbol))+
         " INITIAL_SL="+DoubleToString(sl,DigitsFor(symbol))+
         " INITIAL_RISK="+DoubleToString(risk,DigitsFor(symbol))+
         " ACTION=REGISTER_INITIAL_RISK");
}

bool EnsurePositionState(ulong ticket,string symbol,BMDirection direction,double entry,double sl,double tp,double &initialRisk)
{
   int idx=FindPositionStateIndex(ticket);
   if(idx>=0 && g_positionStates[idx].initialRisk>0.0)
   {
      initialRisk=g_positionStates[idx].initialRisk;
      g_positionStates[idx].currentSL=sl;
      g_positionStates[idx].currentTP=tp;
      return true;
   }

   RegisterPositionState(ticket,symbol,direction,entry,sl,tp);
   idx=FindPositionStateIndex(ticket);
   if(idx>=0 && g_positionStates[idx].initialRisk>0.0)
   {
      initialRisk=g_positionStates[idx].initialRisk;
      return true;
   }

   initialRisk=0.0;
   return false;
}

void UpdatePositionStateAfterSL(ulong ticket,double sl,double currentR)
{
   int idx=FindPositionStateIndex(ticket);
   if(idx<0)
      return;

   g_positionStates[idx].currentSL=sl;
   g_positionStates[idx].currentR=currentR;
   g_positionStates[idx].lastTrailLevel=sl;
   if(currentR>=BreakEvenAtR)
      g_positionStates[idx].reachedBreakEven=true;
}

ulong FindLatestManagedPositionTicket(string symbol,BMDirection direction)
{
   ulong latest=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetString(POSITION_SYMBOL)!=symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC)!=MagicNumber)
         continue;
      long type=PositionGetInteger(POSITION_TYPE);
      if(direction==BM_DIR_BUY && type!=POSITION_TYPE_BUY)
         continue;
      if(direction==BM_DIR_SELL && type!=POSITION_TYPE_SELL)
         continue;
      if(ticket>latest)
         latest=ticket;
   }
   return latest;
}

bool ProgressiveProfitLockSL(BMDirection direction,double entry,double initialRisk,double currentR,double &lockSL,string &stage,string &reason)
{
   if(!UseProgressiveProfitLock || initialRisk<=0.0)
      return false;

   double secureR=-1.0;
   double triggerR=0.0;

   if(currentR>=ProfitLockTriggerR_4 && ProfitLockSecureR_4>secureR)
   {
      secureR=ProfitLockSecureR_4;
      triggerR=ProfitLockTriggerR_4;
   }
   else if(currentR>=ProfitLockTriggerR_3 && ProfitLockSecureR_3>secureR)
   {
      secureR=ProfitLockSecureR_3;
      triggerR=ProfitLockTriggerR_3;
   }
   else if(currentR>=ProfitLockTriggerR_2 && ProfitLockSecureR_2>secureR)
   {
      secureR=ProfitLockSecureR_2;
      triggerR=ProfitLockTriggerR_2;
   }
   else if(currentR>=ProfitLockTriggerR_1 && ProfitLockSecureR_1>secureR)
   {
      secureR=ProfitLockSecureR_1;
      triggerR=ProfitLockTriggerR_1;
   }

   if(secureR<0.0)
      return false;

   if(direction==BM_DIR_BUY)
      lockSL=entry+(secureR*initialRisk);
   else if(direction==BM_DIR_SELL)
      lockSL=entry-(secureR*initialRisk);
   else
      return false;

   stage="PROFIT_LOCK";
   reason="PRICE_REACHED_"+DoubleToString(triggerR,2)+"R_LOCK_"+DoubleToString(secureR,2)+"R";
   return true;
}

bool CanModifyPositions()
{
   if(!EnableTrading) return false;
   if(!EnableTradeManagement) return false;
   if(RunMode!=BM_DEMO_EXECUTION_WITH_MANAGEMENT) return false;
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO && !AllowLiveTrading) return false;
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) return false;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED)) return false;
   return true;
}

bool ModifyDistanceAllowed(string symbol,BMDirection direction,double sl,double tp)
{
   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   double minDistance=(double)MathMax((int)SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL),(int)SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL))*point;
   if(minDistance<=0.0) return true;
   double bid=SymbolInfoDouble(symbol,SYMBOL_BID);
   double ask=SymbolInfoDouble(symbol,SYMBOL_ASK);
   if(direction==BM_DIR_BUY){ if(sl>0.0 && bid-sl<minDistance) return false; if(tp>0.0 && tp-bid<minDistance) return false; }
   if(direction==BM_DIR_SELL){ if(sl>0.0 && sl-ask<minDistance) return false; if(tp>0.0 && ask-tp<minDistance) return false; }
   return true;
}

void ManagePositions()
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket) || PositionGetInteger(POSITION_MAGIC)!=MagicNumber)
         continue;

      string s=PositionGetString(POSITION_SYMBOL);
      BMSymbolContext c;
      if(!BuildSymbolContext(s,c))
         continue;

      long type=PositionGetInteger(POSITION_TYPE);
      BMDirection d=(type==POSITION_TYPE_BUY?BM_DIR_BUY:BM_DIR_SELL);
      double entry=PositionGetDouble(POSITION_PRICE_OPEN);
      double sl=PositionGetDouble(POSITION_SL);
      double tp=PositionGetDouble(POSITION_TP);
      double price=(d==BM_DIR_BUY?SymbolInfoDouble(s,SYMBOL_BID):SymbolInfoDouble(s,SYMBOL_ASK));
      double currentStopRisk=MathAbs(entry-sl);
      if(currentStopRisk<=0.0)
         continue;

      double initialRisk=0.0;
      if(!EnsurePositionState(ticket,s,d,entry,sl,tp,initialRisk) || initialRisk<=0.0)
         continue;

      double currentR=(d==BM_DIR_BUY?(price-entry)/initialRisk:(entry-price)/initialRisk);
      double bestSL=sl;
      double effectiveSL=sl;
      string stage="";
      string reason="";
      bool canModify=CanModifyPositions();

      if(currentR>=BreakEvenAtR)
      {
         double be=(d==BM_DIR_BUY?entry+BreakEvenBufferATR*c.atrM15:entry-BreakEvenBufferATR*c.atrM15);
         if((d==BM_DIR_BUY && be>bestSL) || (d==BM_DIR_SELL && (bestSL==0.0 || be<bestSL)))
         {
            bestSL=be;
            stage="BREAKEVEN";
            reason="PRICE_REACHED_1R";
         }
      }

      double profitLockSL=0.0;
      string profitStage="";
      string profitReason="";
      if(ProgressiveProfitLockSL(d,entry,initialRisk,currentR,profitLockSL,profitStage,profitReason))
      {
         if((d==BM_DIR_BUY && profitLockSL>bestSL) || (d==BM_DIR_SELL && (bestSL==0.0 || profitLockSL<bestSL)))
         {
            bestSL=profitLockSL;
            stage=profitStage;
            reason=profitReason;
         }
      }

      if(UseStructureTrailing)
      {
         double st=(d==BM_DIR_BUY?c.lastSwingLowM15-SLBufferATR*c.atrM15:c.lastSwingHighM15+SLBufferATR*c.atrM15);
         if((d==BM_DIR_BUY && st>bestSL) || (d==BM_DIR_SELL && (bestSL==0.0 || st<bestSL)))
         {
            bestSL=st;
            stage="STRUCTURE_TRAIL";
            reason="CONFIRMED_M15_STRUCTURE";
         }
      }

      if(UseATRTrailing)
      {
         double at=(d==BM_DIR_BUY?price-ATRTrailMultiplier*c.atrM15:price+ATRTrailMultiplier*c.atrM15);
         if((d==BM_DIR_BUY && at>bestSL) || (d==BM_DIR_SELL && (bestSL==0.0 || at<bestSL)))
         {
            bestSL=at;
            stage="ATR_TRAIL";
            reason="ATR_RUNNING_SL";
         }
      }

      bestSL=NormalizePrice(s,bestSL);
      if(bestSL!=sl && stage!="")
      {
         if(!canModify)
         {
            BMLog("SL_RUNNING","SYMBOL="+s+" POSITION="+(string)ticket+" CURRENT_R="+DoubleToString(currentR,2)+" INITIAL_RISK="+DoubleToString(initialRisk,DigitsFor(s))+" STAGE="+stage+" OLD_SL="+DoubleToString(sl,DigitsFor(s))+" NEW_SL="+DoubleToString(bestSL,DigitsFor(s))+" REASON="+reason+" ACTION=WOULD_MODIFY_SL");
         }
         else if(!ModifyDistanceAllowed(s,d,bestSL,tp))
         {
            BMLog("SL_RUNNING","SYMBOL="+s+" POSITION="+(string)ticket+" CURRENT_R="+DoubleToString(currentR,2)+" INITIAL_RISK="+DoubleToString(initialRisk,DigitsFor(s))+" STAGE="+stage+" OLD_SL="+DoubleToString(sl,DigitsFor(s))+" NEW_SL="+DoubleToString(bestSL,DigitsFor(s))+" REASON=BROKER_STOPS_OR_FREEZE_LEVEL ACTION=WOULD_MODIFY_SL");
         }
         else if(trade.PositionModify(ticket,bestSL,tp))
         {
            effectiveSL=bestSL;
            UpdatePositionStateAfterSL(ticket,bestSL,currentR);
            BMLog("SL_RUNNING","SYMBOL="+s+" POSITION="+(string)ticket+" CURRENT_R="+DoubleToString(currentR,2)+" INITIAL_RISK="+DoubleToString(initialRisk,DigitsFor(s))+" STAGE="+stage+" OLD_SL="+DoubleToString(sl,DigitsFor(s))+" NEW_SL="+DoubleToString(bestSL,DigitsFor(s))+" REASON="+reason+" ACTION=MODIFY_SL");
         }
         else
         {
            BMLog("ERROR","SYMBOL="+s+" ACTION=SL_MODIFY_REJECTED POSITION="+(string)ticket+" RETCODE="+(string)trade.ResultRetcode()+" COMMENT="+trade.ResultRetcodeDescription());
         }
      }

      if(CheckStructureExit(ticket,c,d,entry,price,effectiveSL,tp,canModify))
         continue;
      if(UseRunningTP)
         ManageTP(ticket,c,d,effectiveSL,tp,price,canModify);
   }
}
bool CheckStructureExit(ulong ticket,BMSymbolContext &c,BMDirection d,double entry,double price,double effectiveSL,double tp,bool canModify)
{
   bool opposite=(d==BM_DIR_BUY && c.marketState==BM_STATE_BREAKOUT_DOWN) || (d==BM_DIR_SELL && c.marketState==BM_STATE_BREAKOUT_UP);
   bool structureBroken=(d==BM_DIR_BUY && c.closePrice<c.lastSwingLowM15) || (d==BM_DIR_SELL && c.closePrice>c.lastSwingHighM15);
   if(!opposite && !structureBroken) return false;
   if(!AllowDirectExitOnOppositeBreak || !canModify){ BMLog("EXIT","SYMBOL="+c.symbol+" POSITION="+(string)ticket+" ENTRY="+DoubleToString(entry,DigitsFor(c.symbol))+" EXIT="+DoubleToString(price,DigitsFor(c.symbol))+" EXIT_REASON="+(opposite?"OPPOSITE_BREAKOUT_CONFIRMED":"STRUCTURE_BREAK")+" RESULT_POINTS=0 RESULT_MONEY_APPROX=0 ACTION=WOULD_TIGHTEN_OR_EXIT"); return false; }
   if(!ModifyDistanceAllowed(c.symbol,d,effectiveSL,tp)){ BMLog("EXIT","SYMBOL="+c.symbol+" POSITION="+(string)ticket+" ENTRY="+DoubleToString(entry,DigitsFor(c.symbol))+" EXIT="+DoubleToString(price,DigitsFor(c.symbol))+" EXIT_REASON=BROKER_STOPS_OR_FREEZE_LEVEL RESULT_POINTS=0 RESULT_MONEY_APPROX=0 ACTION=WOULD_TIGHTEN_OR_EXIT"); return false; }
   double points=(d==BM_DIR_BUY?price-entry:entry-price)/SymbolInfoDouble(c.symbol,SYMBOL_POINT);
   double volume=PositionGetDouble(POSITION_VOLUME);
   double tickValue=SymbolInfoDouble(c.symbol,SYMBOL_TRADE_TICK_VALUE);
   double tickSize=SymbolInfoDouble(c.symbol,SYMBOL_TRADE_TICK_SIZE);
   double money=(tickSize>0.0)?((price-entry)/tickSize*tickValue*volume*(d==BM_DIR_BUY?1.0:-1.0)):0.0;
   if(trade.PositionClose(ticket))
      BMLog("EXIT","SYMBOL="+c.symbol+" POSITION="+(string)ticket+" ENTRY="+DoubleToString(entry,DigitsFor(c.symbol))+" EXIT="+DoubleToString(price,DigitsFor(c.symbol))+" EXIT_REASON="+(opposite?"OPPOSITE_BREAKOUT_CONFIRMED":"STRUCTURE_BREAK")+" RESULT_POINTS="+DoubleToString(points,1)+" RESULT_MONEY_APPROX="+DoubleToString(money,2)+" ACTION=CLOSE_POSITION");
   else
      BMLog("ERROR","SYMBOL="+c.symbol+" ACTION=EXIT_CLOSE_REJECTED POSITION="+(string)ticket+" RETCODE="+(string)trade.ResultRetcode()+" COMMENT="+trade.ResultRetcodeDescription());
   return true;
}

void ManageTP(ulong ticket,BMSymbolContext &c,BMDirection d,double sl,double tp,double price,bool canModify)
{
   if(!PositionSelectByTicket(ticket))
      return;

   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   sl = PositionGetDouble(POSITION_SL);
   tp = PositionGetDouble(POSITION_TP);

   if(tp <= 0.0 || entry <= 0.0)
      return;

   if(!ExtendTPBeforeHit)
      return;

   double percent = TPPreExtendPercent;
   if(percent <= 0.10) percent = 0.75;
   if(percent >= 0.95) percent = 0.75;

   double triggerPrice = 0.0;

   if(d == BM_DIR_BUY)
      triggerPrice = entry + ((tp - entry) * percent);
   else if(d == BM_DIR_SELL)
      triggerPrice = entry - ((entry - tp) * percent);
   else
      return;

   bool reachedPreTP = false;

   if(d == BM_DIR_BUY && price >= triggerPrice)
      reachedPreTP = true;

   if(d == BM_DIR_SELL && price <= triggerPrice)
      reachedPreTP = true;

   if(!reachedPreTP)
      return;

   bool slProtected = false;

   if(d == BM_DIR_BUY && sl >= entry)
      slProtected = true;

   if(d == BM_DIR_SELL && sl > 0.0 && sl <= entry)
      slProtected = true;

   if(RequireSLProtectedBeforeTPExtend && !slProtected)
   {
      BMLog("TP_RUNNING",
            "SYMBOL="+c.symbol+
            " POSITION="+(string)ticket+
            " ENTRY="+DoubleToString(entry,DigitsFor(c.symbol))+
            " PRICE="+DoubleToString(price,DigitsFor(c.symbol))+
            " TRIGGER="+DoubleToString(triggerPrice,DigitsFor(c.symbol))+
            " OLD_TP="+DoubleToString(tp,DigitsFor(c.symbol))+
            " REASON=PRE_TP_REACHED_BUT_SL_NOT_PROTECTED ACTION=HOLD_TP");
      return;
   }

   bool momentum = false;

   if(d == BM_DIR_BUY && c.buyBodyStrong && c.marketState != BM_STATE_BREAKOUT_DOWN)
      momentum = true;

   if(d == BM_DIR_SELL && c.sellBodyStrong && c.marketState != BM_STATE_BREAKOUT_UP)
      momentum = true;

   if(!momentum)
   {
      BMLog("TP_RUNNING",
            "SYMBOL="+c.symbol+
            " POSITION="+(string)ticket+
            " OLD_TP="+DoubleToString(tp,DigitsFor(c.symbol))+
            " REASON=PRE_TP_REACHED_MOMENTUM_WEAK ACTION=HOLD_TP");
      return;
   }

   double newTP = tp;

   if(d == BM_DIR_BUY)
   {
      newTP = MathMax(tp + (TPExtendATR * c.atrM15), c.donchianHighH1);

      if(newTP <= tp)
         newTP = tp + (TPExtendATR * c.atrM15);
   }

   if(d == BM_DIR_SELL)
   {
      newTP = MathMin(tp - (TPExtendATR * c.atrM15), c.donchianLowH1);

      if(newTP >= tp)
         newTP = tp - (TPExtendATR * c.atrM15);
   }

   newTP = NormalizePrice(c.symbol,newTP);

   if((d == BM_DIR_BUY && newTP <= tp) || (d == BM_DIR_SELL && newTP >= tp))
      return;

   if(!canModify)
   {
      BMLog("TP_RUNNING",
            "SYMBOL="+c.symbol+
            " POSITION="+(string)ticket+
            " OLD_TP="+DoubleToString(tp,DigitsFor(c.symbol))+
            " NEW_TP="+DoubleToString(newTP,DigitsFor(c.symbol))+
            " TRIGGER="+DoubleToString(triggerPrice,DigitsFor(c.symbol))+
            " REASON=PRE_TP_REACHED_MOMENTUM_STRONG ACTION=WOULD_EXTEND_TP");
      return;
   }

   if(!ModifyDistanceAllowed(c.symbol,d,sl,newTP))
   {
      BMLog("TP_RUNNING",
            "SYMBOL="+c.symbol+
            " POSITION="+(string)ticket+
            " OLD_TP="+DoubleToString(tp,DigitsFor(c.symbol))+
            " NEW_TP="+DoubleToString(newTP,DigitsFor(c.symbol))+
            " REASON=BROKER_STOPS_OR_FREEZE_LEVEL ACTION=WOULD_EXTEND_TP");
      return;
   }

   if(trade.PositionModify(ticket,sl,newTP))
   {
      BMLog("TP_RUNNING",
            "SYMBOL="+c.symbol+
            " POSITION="+(string)ticket+
            " OLD_TP="+DoubleToString(tp,DigitsFor(c.symbol))+
            " NEW_TP="+DoubleToString(newTP,DigitsFor(c.symbol))+
            " TRIGGER="+DoubleToString(triggerPrice,DigitsFor(c.symbol))+
            " REASON=PRE_TP_REACHED_MOMENTUM_STRONG ACTION=MODIFY_TP");
   }
   else
   {
      BMLog("ERROR",
            "SYMBOL="+c.symbol+
            " ACTION=TP_MODIFY_REJECTED POSITION="+(string)ticket+
            " RETCODE="+(string)trade.ResultRetcode()+
            " COMMENT="+trade.ResultRetcodeDescription());
   }
}