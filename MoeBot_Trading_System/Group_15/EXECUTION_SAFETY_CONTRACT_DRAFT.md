# Group 15 Execution Safety Contract — DRAFT

Group 15 real execution is forbidden until Group 14 produces an official robustness/edge PASS for an immutable policy version.

Required layers before live capital:
1. deterministic order-intent generation from the frozen policy;
2. broker/MT5 bridge with fill, reject, slippage, latency, and reconciliation audit;
3. structural stop handling and catastrophic risk ceiling;
4. open-risk reservation before new orders;
5. emergency close/kill-switch and reconnect recovery;
6. demo execution validation;
7. gradual live deployment only after demo execution evidence passes.

The live process may record diagnostics and propose future research, but it may not silently alter the policy, definitions, thresholds, or risk ceiling while trading.
