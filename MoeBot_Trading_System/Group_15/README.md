# MoeBot Group 15 — Live Execution & Integration

**State:** PREPARATION ONLY — real execution is not authorized.

## Purpose
Frozen validated policy integration with MT5/broker execution, sizing, catastrophic safety, fill/slippage audit, monitoring, recovery; demo then gradual live.

## Hard exclusions
- live_before_group14_pass
- self_modifying_live_policy_without_governance
- bypass_catastrophic_safety

## Shared architecture
This group inherits `../GROUPS_9_15_SHARED_CONTRACT.json`. It consumes predecessor outputs read-only, preserves deterministic IDs/availability times, benchmarks before annual execution, keeps C: above the safety floor, and retains large verified compressed artifacts in the vault rather than on C:.

## Preparation checklist
- definition registry
- upstream/input contract
- schema draft
- causal availability rules
- exact cardinality inventory
- representative performance benchmark
- resource/storage preflight
- shard planner
- resumable executor
- streaming union validator
- synthetic parity/idempotence/causality tests
- closure/handoff contract

No real predecessor data may be executed until the dependency gate passes.
