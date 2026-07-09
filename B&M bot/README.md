# B&M bot

This folder stores the current B&M / MoeBot Price Action trading bot build and its documentation.

## Current active build

**MoeBot Price Action Decision Engine v1.0.5**

Mode:
- Demo trading active
- Live trading blocked
- Money Protection enabled
- Protected Running SL enabled
- Running TP extension only after the trade is protected

Important settings:
- `MagicNumber = 26070801`
- `EnableTrading = true`
- `AllowLiveTrading = false`
- `UseCurrentChartOnly = false`
- Attach to **one chart only** in multi-symbol mode.

## Files

- `src/MoeBot_PriceAction_Decision_Engine_v1_0_5_DEMO_ACTIVE_MONEY_PROTECTION_PROTECTED_RUNNING_SL_COMPILE_READY.mq5`
  - Latest bot source code.

- `docs/MoeBot_v1_05_Project_Summary_and_Monitoring_Plan.txt`
  - Full handoff summary, current status, monitoring plan, and future notes.

- `docs/MoeBot_PriceAction_Strategy_Documentation_v1_0_2.txt`
  - Full strategy document: Zone -> Reaction -> Confirmation.

## Current decision

Keep v1.0.5 running on demo and monitor:
1. Winner protection and protected running SL.
2. Losing trades and whether Early Invalidation Exit is needed.
3. USDCAD H4 support behavior.
4. M15 local zone performance.
5. Breakout failure behavior.

Next possible version, only if logs prove it is needed:
- v1.0.6 with Early Invalidation Exit only.
