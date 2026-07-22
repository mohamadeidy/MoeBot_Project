#property strict
#property version   "0.92"
#property description "MoeBot Group 1 raw market-memory collector. No trading operations."

input string InpOutputRoot         = "MoeBot\\Group1\\spool";
input int    InpTimerSeconds       = 1;
input int    InpBackfillBars       = 5000;
input int    InpHistoricalTickHours= 0;
input bool   InpCollectTicks       = true;
input bool   InpCollectBars        = true;
input bool   InpUseCheckpoints     = true;
input int    InpClockHeartbeatSeconds= 300; // persist clock heartbeat every 5 minutes; poll still runs every timer event
input bool   InpRotateSpoolDaily    = true; // close one completed run folder per UTC day to bound active file size

#define COLLECTOR_VERSION "0.9.2"
#define SCHEMA_VERSION    "1.4.0"

string g_run_id;
string g_run_dir;
int g_tick_handle     = INVALID_HANDLE;
int g_bar_handle      = INVALID_HANDLE;
int g_clock_handle    = INVALID_HANDLE;
int g_session_handle  = INVALID_HANDLE;
int g_symbol_handle   = INVALID_HANDLE;
long g_seq = 0;
long g_tick_cursor_msc = -1;
int g_tick_cursor_count = 0;
ENUM_TIMEFRAMES g_tfs[] = {PERIOD_M1,PERIOD_M5,PERIOD_M15,PERIOD_M30,PERIOD_H1,PERIOD_H4,PERIOD_D1};
datetime g_last_closed_bar[];
bool g_has_clock_sample = false;
datetime g_last_clock_gmt = 0;
long g_last_clock_offset = 0;
int g_run_utc_day_key = 0;
#define ROTATION_REASON 9001

string IsoUtc(datetime utc_time)
{
   MqlDateTime dt;
   TimeToStruct(utc_time,dt);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d.000Z",dt.year,dt.mon,dt.day,dt.hour,dt.min,dt.sec);
}

int UtcDayKey(datetime utc_time)
{
   MqlDateTime dt;
   TimeToStruct(utc_time,dt);
   return dt.year*10000+dt.mon*100+dt.day;
}

void ResetRunClockState()
{
   g_has_clock_sample=false;
   g_last_clock_gmt=0;
   g_last_clock_offset=0;
}

long NormalizeUtcOffsetSeconds(const long raw_offset)
{
   // TimeTradeServer() and TimeGMT() are read sequentially with one-second resolution.
   // Rounding to the nearest minute removes harmless +/-1 second boundary jitter while
   // preserving every real-world broker UTC offset and DST transition. Raw epochs remain
   // stored in clock_samples.csv, so the original evidence is never lost.
   return (long)MathRound((double)raw_offset/60.0)*60;
}

int ClockHeartbeatSeconds()
{
   return (InpClockHeartbeatSeconds<1 ? 300 : InpClockHeartbeatSeconds);
}

long CurrentBrokerOffsetSeconds()
{
   datetime server=TimeTradeServer();
   datetime gmt=TimeGMT();
   return NormalizeUtcOffsetSeconds((long)(server-gmt));
}

string TfName(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1: return "M1";
      case PERIOD_M5: return "M5";
      case PERIOD_M15:return "M15";
      case PERIOD_M30:return "M30";
      case PERIOD_H1: return "H1";
      case PERIOD_H4: return "H4";
      case PERIOD_D1: return "D1";
   }
   return "UNKNOWN";
}

ulong Fnv1a64(string text)
{
   ulong hash=1469598103934665603;
   uchar bytes[];
   StringToCharArray(text,bytes,0,WHOLE_ARRAY,CP_UTF8);
   int n=ArraySize(bytes);
   for(int i=0;i<n-1;i++) { hash^=(ulong)bytes[i]; hash*=1099511628211; }
   return hash;
}

string SafeKeyPart(string value)
{
   StringReplace(value," ","_");
   StringReplace(value,".","_");
   StringReplace(value,"-","_");
   StringReplace(value,"/","_");
   StringReplace(value,"\\","_");
   return value;
}

string CheckpointName(ENUM_TIMEFRAMES tf)
{
   string identity=TerminalInfoString(TERMINAL_COMPANY)+"|"+AccountInfoString(ACCOUNT_SERVER)+"|"+
                   StringFormat("%I64d",AccountInfoInteger(ACCOUNT_LOGIN))+"|"+_Symbol+"|"+TfName(tf);
   return "MBG1."+StringFormat("%I64u",Fnv1a64(identity));
}

void LoadCheckpoints()
{
   for(int i=0;i<ArraySize(g_tfs);i++)
   {
      g_last_closed_bar[i]=0;
      if(!InpUseCheckpoints) continue;
      string key=CheckpointName(g_tfs[i]);
      if(GlobalVariableCheck(key)) g_last_closed_bar[i]=(datetime)GlobalVariableGet(key);
   }
}

void SaveCheckpoint(int index)
{
   if(!InpUseCheckpoints || index<0 || index>=ArraySize(g_tfs)) return;
   GlobalVariableSet(CheckpointName(g_tfs[index]),(double)g_last_closed_bar[index]);
}

string TickCheckpointName(string suffix)
{
   string identity=TerminalInfoString(TERMINAL_COMPANY)+"|"+AccountInfoString(ACCOUNT_SERVER)+"|"+
                   StringFormat("%I64d",AccountInfoInteger(ACCOUNT_LOGIN))+"|"+_Symbol+"|TICKS|"+suffix;
   return "MBG1."+StringFormat("%I64u",Fnv1a64(identity));
}

void LoadTickCheckpoint()
{
   g_tick_cursor_msc=-1;
   g_tick_cursor_count=0;
   if(!InpUseCheckpoints) return;
   string msc_key=TickCheckpointName("MSC");
   string count_key=TickCheckpointName("COUNT");
   if(GlobalVariableCheck(msc_key)) g_tick_cursor_msc=(long)GlobalVariableGet(msc_key);
   if(GlobalVariableCheck(count_key)) g_tick_cursor_count=(int)GlobalVariableGet(count_key);
}

void SaveTickCheckpoint()
{
   if(!InpUseCheckpoints || g_tick_cursor_msc<0) return;
   GlobalVariableSet(TickCheckpointName("MSC"),(double)g_tick_cursor_msc);
   GlobalVariableSet(TickCheckpointName("COUNT"),(double)g_tick_cursor_count);
}

string BuildRunId()
{
   string seed=TerminalInfoString(TERMINAL_COMPANY)+"|"+AccountInfoString(ACCOUNT_SERVER)+"|"+
               StringFormat("%I64d",AccountInfoInteger(ACCOUNT_LOGIN))+"|"+_Symbol+"|"+
               StringFormat("%I64d",(long)TimeLocal())+"|"+StringFormat("%I64u",GetTickCount64())+"|"+
               StringFormat("%I64d",ChartID());
   return "run_"+StringFormat("%I64d",(long)TimeLocal())+"_"+StringFormat("%I64u",Fnv1a64(seed));
}

string CsvEscape(string value)
{
   StringReplace(value,"\"","\"\"");
   return "\""+value+"\"";
}

string CsvBool(const bool value)
{
   return (value?"true":"false");
}

bool OpenFiles()
{
   g_run_dir=InpOutputRoot+"\\"+g_run_id;
   FolderCreate(InpOutputRoot,FILE_COMMON);
   FolderCreate(g_run_dir,FILE_COMMON);

   int run_handle=FileOpen(g_run_dir+"\\run.csv",FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(run_handle==INVALID_HANDLE) return false;
   FileWriteString(run_handle,"run_id,started_at_utc,collector_version,schema_version,broker_name,account_server,symbol,terminal_build,config_json\r\n");
   string config=StringFormat("{\"timer_seconds\":%d,\"backfill_bars\":%d,\"historical_tick_hours\":%d,\"collect_ticks\":%s,\"collect_bars\":%s,\"use_checkpoints\":%s,\"clock_heartbeat_seconds\":%d,\"rotate_spool_daily\":%s,\"strategy_tester\":%s}",
                              InpTimerSeconds,InpBackfillBars,InpHistoricalTickHours,
                              CsvBool(InpCollectTicks),CsvBool(InpCollectBars),CsvBool(InpUseCheckpoints),
                              ClockHeartbeatSeconds(),CsvBool(InpRotateSpoolDaily),
                              CsvBool((bool)MQLInfoInteger(MQL_TESTER)));
   string run_line=CsvEscape(g_run_id)+","+CsvEscape(IsoUtc(TimeGMT()))+","+CsvEscape(COLLECTOR_VERSION)+","+
                   CsvEscape(SCHEMA_VERSION)+","+CsvEscape(TerminalInfoString(TERMINAL_COMPANY))+","+
                   CsvEscape(AccountInfoString(ACCOUNT_SERVER))+","+CsvEscape(_Symbol)+","+
                   IntegerToString((int)TerminalInfoInteger(TERMINAL_BUILD))+","+CsvEscape(config)+"\r\n";
   FileWriteString(run_handle,run_line);
   FileFlush(run_handle); FileClose(run_handle);

   g_tick_handle=FileOpen(g_run_dir+"\\ticks.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',');
   if(g_tick_handle==INVALID_HANDLE) return false;
   if(FileSize(g_tick_handle)==0)
      FileWrite(g_tick_handle,"run_id","symbol","event_time_msc","event_time_utc","observed_at_utc","tick_ordinal","bid","ask","spread","spread_points","last","volume","volume_real","flags","broker_offset_seconds","time_confidence","source","ingest_seq");
   FileSeek(g_tick_handle,0,SEEK_END);

   g_bar_handle=FileOpen(g_run_dir+"\\bars.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',');
   if(g_bar_handle==INVALID_HANDLE) return false;
   if(FileSize(g_bar_handle)==0)
      FileWrite(g_bar_handle,"run_id","symbol","timeframe","open_time_server","close_time_server","open_time_utc","close_time_utc","available_at_utc","observed_at_utc","open","high","low","close","tick_volume","real_volume","spread_points","broker_offset_seconds","time_confidence","is_closed","source");
   FileSeek(g_bar_handle,0,SEEK_END);

   g_clock_handle=FileOpen(g_run_dir+"\\clock_samples.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',');
   if(g_clock_handle==INVALID_HANDLE) return false;
   if(FileSize(g_clock_handle)==0)
      FileWrite(g_clock_handle,"run_id","observed_at_utc","server_epoch","gmt_epoch","local_epoch","server_minus_gmt_seconds");
   FileSeek(g_clock_handle,0,SEEK_END);

   g_session_handle=FileOpen(g_run_dir+"\\symbol_sessions.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',');
   if(g_session_handle==INVALID_HANDLE) return false;
   if(FileSize(g_session_handle)==0)
      FileWrite(g_session_handle,"run_id","symbol","day_of_week","session_index","from_seconds","to_seconds","observed_at_utc");
   FileSeek(g_session_handle,0,SEEK_END);

   g_symbol_handle=FileOpen(g_run_dir+"\\symbol_metadata.csv",FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ);
   if(g_symbol_handle==INVALID_HANDLE) return false;
   if(FileSize(g_symbol_handle)==0)
      FileWriteString(g_symbol_handle,"run_id,symbol,observed_at_utc,digits,point,tick_size,tick_value,tick_value_profit,tick_value_loss,volume_min,volume_max,volume_step,currency_base,currency_profit,currency_margin,description,symbol_path,trade_mode,calc_mode\r\n");
   FileSeek(g_symbol_handle,0,SEEK_END);
   return true;
}

void WriteClockSample(const bool force)
{
   if(g_clock_handle==INVALID_HANDLE) return;

   datetime server=TimeTradeServer();
   datetime gmt=TimeGMT();
   datetime local=TimeLocal();
   if(server<=0 || gmt<=0 || local<=0) return;

   long raw_offset=(long)(server-gmt);
   long offset=NormalizeUtcOffsetSeconds(raw_offset);
   int heartbeat=ClockHeartbeatSeconds();

   bool clock_moved_backward=(g_has_clock_sample && gmt<g_last_clock_gmt);
   bool heartbeat_due=(!g_has_clock_sample || clock_moved_backward ||
                       (long)(gmt-g_last_clock_gmt)>=(long)heartbeat);
   bool offset_changed=(g_has_clock_sample && offset!=g_last_clock_offset);

   // A forced sample closes the final clock segment, but never duplicates an
   // identical sample already written in the same second.
   bool exact_duplicate=(g_has_clock_sample && gmt==g_last_clock_gmt &&
                         offset==g_last_clock_offset);
   if((!force && !heartbeat_due && !offset_changed) || (force && exact_duplicate)) return;

   FileWrite(g_clock_handle,g_run_id,IsoUtc(gmt),(long)server,(long)gmt,(long)local,offset);
   FileFlush(g_clock_handle);
   g_has_clock_sample=true;
   g_last_clock_gmt=gmt;
   g_last_clock_offset=offset;
}

void ExportSymbolMetadata()
{
   string line=CsvEscape(g_run_id)+","+CsvEscape(_Symbol)+","+CsvEscape(IsoUtc(TimeGMT()))+","+
               IntegerToString((int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS))+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_POINT),16)+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),16)+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE),16)+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_PROFIT),16)+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS),16)+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),8)+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX),8)+","+
               DoubleToString(SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP),8)+","+
               CsvEscape(SymbolInfoString(_Symbol,SYMBOL_CURRENCY_BASE))+","+
               CsvEscape(SymbolInfoString(_Symbol,SYMBOL_CURRENCY_PROFIT))+","+
               CsvEscape(SymbolInfoString(_Symbol,SYMBOL_CURRENCY_MARGIN))+","+
               CsvEscape(SymbolInfoString(_Symbol,SYMBOL_DESCRIPTION))+","+
               CsvEscape(SymbolInfoString(_Symbol,SYMBOL_PATH))+","+
               IntegerToString((int)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_MODE))+","+
               IntegerToString((int)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_CALC_MODE))+"\r\n";
   FileWriteString(g_symbol_handle,line);
   FileFlush(g_symbol_handle);
}

void ExportSymbolSessions()
{
   datetime observed=TimeGMT();
   for(int day=0;day<=6;day++)
   {
      uint index=0;
      datetime from_time,to_time;
      while(SymbolInfoSessionTrade(_Symbol,(ENUM_DAY_OF_WEEK)day,index,from_time,to_time))
      {
         long from_seconds=(long)from_time%86400;
         long to_seconds=(long)to_time%86400;
         FileWrite(g_session_handle,g_run_id,_Symbol,day,(int)index,from_seconds,to_seconds,IsoUtc(observed));
         index++;
      }
   }
   FileFlush(g_session_handle);
}

void WriteTickWithOrdinal(const MqlTick &tick,string confidence,int ordinal)
{
   long offset=CurrentBrokerOffsetSeconds();
   long utc_msc=(long)tick.time_msc-offset*1000;
   g_seq++;
   double spread=tick.ask-tick.bid;
   int spread_points=(_Point>0.0?(int)MathRound(spread/_Point):0);
   FileWrite(g_tick_handle,g_run_id,_Symbol,(long)tick.time_msc,IsoUtc((datetime)(utc_msc/1000)),IsoUtc(TimeGMT()),ordinal,
             DoubleToString(tick.bid,_Digits),DoubleToString(tick.ask,_Digits),DoubleToString(spread,_Digits),spread_points,DoubleToString(tick.last,_Digits),
             (long)tick.volume,DoubleToString(tick.volume_real,8),(long)tick.flags,offset,confidence,"mt5",g_seq);
}

int ProcessTickBatch(MqlTick &ticks[],string confidence)
{
   int copied=ArraySize(ticks);
   if(copied<=0) return 0;
   long active_msc=-1;
   int occurrence=-1;
   int written=0;
   for(int i=0;i<copied;i++)
   {
      long msc=(long)ticks[i].time_msc;
      if(msc!=active_msc) { active_msc=msc; occurrence=0; }
      else occurrence++;

      if(g_tick_cursor_msc>=0)
      {
         if(msc<g_tick_cursor_msc) continue;
         if(msc==g_tick_cursor_msc && occurrence<g_tick_cursor_count) continue;
      }

      WriteTickWithOrdinal(ticks[i],confidence,occurrence);
      written++;
      if(msc>g_tick_cursor_msc)
      {
         g_tick_cursor_msc=msc;
         g_tick_cursor_count=occurrence+1;
      }
      else if(msc==g_tick_cursor_msc && occurrence+1>g_tick_cursor_count)
         g_tick_cursor_count=occurrence+1;
   }
   return written;
}

void CaptureTicksRange(ulong start_msc,ulong end_msc,string confidence)
{
   if(!InpCollectTicks || end_msc<start_msc) return;
   const ulong chunk_msc=3600*1000;
   for(ulong from_msc=start_msc;from_msc<=end_msc;)
   {
      ulong proposed=from_msc+chunk_msc-1;
      ulong to_msc=(proposed<end_msc?proposed:end_msc);
      MqlTick ticks[];
      int copied=CopyTicksRange(_Symbol,ticks,COPY_TICKS_ALL,from_msc,to_msc);
      if(copied>0)
      {
         int written=ProcessTickBatch(ticks,confidence);
         if(written>0)
         {
            FileFlush(g_tick_handle); // durability barrier before tick checkpoint
            SaveTickCheckpoint();
         }
      }
      if(to_msc>=end_msc) break;
      from_msc=to_msc+1;
   }
}

void CaptureAvailableTicks(string confidence)
{
   if(!InpCollectTicks) return;
   MqlTick latest;
   if(!SymbolInfoTick(_Symbol,latest) || latest.time_msc<=0) return;
   ulong end_msc=(ulong)latest.time_msc;
   ulong start_msc;
   if(g_tick_cursor_msc>=0) start_msc=(ulong)g_tick_cursor_msc;
   else if(InpHistoricalTickHours>0)
      start_msc=(end_msc>(ulong)InpHistoricalTickHours*3600*1000 ? end_msc-(ulong)InpHistoricalTickHours*3600*1000 : 0);
   else start_msc=end_msc;
   CaptureTicksRange(start_msc,end_msc,confidence);
}

int TfIndex(ENUM_TIMEFRAMES tf)
{
   for(int i=0;i<ArraySize(g_tfs);i++) if(g_tfs[i]==tf) return i;
   return -1;
}

void ExportBarsForTf(ENUM_TIMEFRAMES tf,bool initial)
{
   int index=TfIndex(tf);
   if(index<0) return;
   MqlRates rates[];
   ArraySetAsSeries(rates,true);
   int copied=0;
   if(initial && g_last_closed_bar[index]>0)
   {
      datetime from_time=g_last_closed_bar[index]+PeriodSeconds(tf);
      copied=CopyRates(_Symbol,tf,from_time,TimeTradeServer(),rates);
   }
   else
   {
      int requested=initial?InpBackfillBars:10;
      copied=CopyRates(_Symbol,tf,1,requested,rates);
   }
   if(copied<=0) return;

   long offset=CurrentBrokerOffsetSeconds();
   datetime observed_gmt=TimeGMT();
   datetime current_bar=iTime(_Symbol,tf,0);
   for(int i=copied-1;i>=0;i--)
   {
      MqlRates r=rates[i];
      if(r.time<=0 || r.time>=current_bar) continue;
      if(g_last_closed_bar[index]!=0 && r.time<=g_last_closed_bar[index]) continue;
      datetime candidate_close=(i>0?rates[i-1].time:current_bar);
      int nominal=PeriodSeconds(tf);
      long candidate_delta=(long)(candidate_close-r.time);
      datetime close_server=(candidate_delta>=nominal/2 && candidate_delta<=nominal+nominal/2 ? candidate_close : r.time+nominal);
      datetime open_utc=(datetime)((long)r.time-offset);
      datetime close_utc=(datetime)((long)close_server-offset);
      FileWrite(g_bar_handle,g_run_id,_Symbol,TfName(tf),(long)r.time,(long)close_server,IsoUtc(open_utc),IsoUtc(close_utc),
                IsoUtc(close_utc),IsoUtc(observed_gmt),DoubleToString(r.open,_Digits),DoubleToString(r.high,_Digits),
                DoubleToString(r.low,_Digits),DoubleToString(r.close,_Digits),(long)r.tick_volume,
                DoubleToString((double)r.real_volume,8),(int)r.spread,offset,
                initial?"assumed_current_offset":"clock_segment",1,"mt5");
      if(r.time>g_last_closed_bar[index]) g_last_closed_bar[index]=r.time;
   }
   FileFlush(g_bar_handle); // durability barrier before advancing checkpoint
   SaveCheckpoint(index);
}

void WriteRunComplete(const int reason)
{
   int handle=FileOpen(g_run_dir+"\\run_complete.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   if(handle==INVALID_HANDLE) return;
   FileWrite(handle,"run_id","ended_at_utc","status","deinit_reason","last_ingest_seq");
   string status=(reason==REASON_INITFAILED?"failed":"closed");
   FileWrite(handle,g_run_id,IsoUtc(TimeGMT()),status,reason,g_seq);
   FileFlush(handle);
   FileClose(handle);
}

void CloseFiles()
{
   if(g_tick_handle!=INVALID_HANDLE) { FileFlush(g_tick_handle); FileClose(g_tick_handle); g_tick_handle=INVALID_HANDLE; }
   if(g_bar_handle!=INVALID_HANDLE) { FileFlush(g_bar_handle); FileClose(g_bar_handle); g_bar_handle=INVALID_HANDLE; }
   if(g_clock_handle!=INVALID_HANDLE) { FileFlush(g_clock_handle); FileClose(g_clock_handle); g_clock_handle=INVALID_HANDLE; }
   if(g_session_handle!=INVALID_HANDLE) { FileFlush(g_session_handle); FileClose(g_session_handle); g_session_handle=INVALID_HANDLE; }
   if(g_symbol_handle!=INVALID_HANDLE) { FileFlush(g_symbol_handle); FileClose(g_symbol_handle); g_symbol_handle=INVALID_HANDLE; }
}

bool StartRunFiles()
{
   g_seq=0;
   g_run_id=BuildRunId();
   g_run_utc_day_key=UtcDayKey(TimeGMT());
   ResetRunClockState();
   if(!OpenFiles())
   {
      Print("MoeBot Group1: failed to open spool files. Error=",GetLastError());
      CloseFiles();
      return false;
   }
   WriteClockSample(true);
   ExportSymbolMetadata();
   ExportSymbolSessions();
   return true;
}

bool RotateRunIfNeeded()
{
   if(!InpRotateSpoolDaily) return true;
   datetime now_gmt=TimeGMT();
   if(now_gmt<=0 || UtcDayKey(now_gmt)==g_run_utc_day_key) return true;

   // Finalize the old daily run before opening the new run. Any ticks arriving
   // during this short rotation window are recovered by CopyTicksRange from the
   // durable tick cursor after the new files are open.
   WriteClockSample(true);
   CloseFiles();
   WriteRunComplete(ROTATION_REASON);
   if(!StartRunFiles()) return false;
   Print("MoeBot Group1 collector rotated daily spool. new run_id=",g_run_id);
   return true;
}

int OnInit()
{
   ArrayResize(g_last_closed_bar,ArraySize(g_tfs));
   LoadCheckpoints();
   LoadTickCheckpoint();
   if(!StartRunFiles()) return INIT_FAILED;
   CaptureAvailableTicks("assumed_current_offset");
   if(InpCollectBars)
   {
      for(int i=0;i<ArraySize(g_tfs);i++) ExportBarsForTf(g_tfs[i],true);
      FileFlush(g_bar_handle);
   }
   EventSetTimer((uint)(InpTimerSeconds<1?1:InpTimerSeconds));
   Print("MoeBot Group1 collector started. run_id=",g_run_id,". No trading functions are present.");
   return INIT_SUCCEEDED;
}

void FinalizeActiveRunData()
{
   // Native testers and terminals can deinitialize without another timer event.
   // Perform one final causal catch-up while the spool handles are still open so
   // the last available tick and every bar that is already closed are durable.
   // Checkpoints advance only after the corresponding file flushes inside the
   // capture/export functions. No current/open candle is exported.
   if(g_tick_handle!=INVALID_HANDLE)
      CaptureAvailableTicks("clock_segment");

   if(InpCollectBars && g_bar_handle!=INVALID_HANDLE)
   {
      for(int i=0;i<ArraySize(g_tfs);i++) ExportBarsForTf(g_tfs[i],false);
      FileFlush(g_bar_handle);
   }
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   FinalizeActiveRunData();
   // Close the final sparse clock segment only after final market-data catch-up.
   WriteClockSample(true);
   CloseFiles();
   WriteRunComplete(reason);
}

void OnTick()
{
   if(!RotateRunIfNeeded()) { ExpertRemove(); return; }
   CaptureAvailableTicks("clock_segment");
}

void OnTimer()
{
   if(!RotateRunIfNeeded()) { ExpertRemove(); return; }
   WriteClockSample(false);
   if(InpCollectBars)
   {
      for(int i=0;i<ArraySize(g_tfs);i++) ExportBarsForTf(g_tfs[i],false);
      FileFlush(g_bar_handle);
   }
   CaptureAvailableTicks("clock_segment");
}
