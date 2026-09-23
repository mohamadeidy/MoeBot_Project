# MoeBot Group 11 — Visual Dataset & Audit

**State:** PREPARATION ONLY — real execution is not authorized.

## Purpose
Deterministic chart-linked render recipes, representative visual samples, and broad audit coverage.

## Hard exclusions
- render_every_row
- retain_full_population_screenshots
- change_upstream_semantics

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
