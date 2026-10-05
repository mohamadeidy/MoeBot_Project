-- MoeBot Group 9 Setup State Intelligence — DRAFT schema.
-- PREPARATION ONLY. No frozen semantics are implied.

PRAGMA foreign_keys=ON;

CREATE TABLE setup_instance (
  setup_id TEXT PRIMARY KEY,
  setup_hash TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  direction TEXT,
  origin_event_time INTEGER NOT NULL,
  origin_availability_time INTEGER NOT NULL,
  current_state TEXT NOT NULL CHECK(current_state IN ('FORMING','READY','FAILED','MISSING','INVALIDATED')),
  state_event_time INTEGER NOT NULL,
  state_availability_time INTEGER NOT NULL,
  definition_version TEXT NOT NULL,
  parent_lineage_hash TEXT NOT NULL,
  features_json TEXT NOT NULL
);

CREATE INDEX ix_setup_instance_scope
ON setup_instance(symbol,timeframe,state_availability_time,current_state);

CREATE TABLE setup_component_evidence (
  evidence_id TEXT PRIMARY KEY,
  evidence_hash TEXT NOT NULL,
  setup_id TEXT NOT NULL REFERENCES setup_instance(setup_id),
  component_name TEXT NOT NULL CHECK(component_name IN ('context','location','liquidity','displacement','structure','poi','retracement','confirmation')),
  source_group INTEGER NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_event_time INTEGER NOT NULL,
  source_availability_time INTEGER NOT NULL,
  observed_event_time INTEGER NOT NULL,
  observed_availability_time INTEGER NOT NULL,
  details_json TEXT NOT NULL
);

CREATE INDEX ix_setup_component_evidence_setup
ON setup_component_evidence(setup_id,component_name,observed_availability_time);

CREATE TABLE setup_transition (
  transition_id TEXT PRIMARY KEY,
  transition_hash TEXT NOT NULL,
  setup_id TEXT NOT NULL REFERENCES setup_instance(setup_id),
  from_state TEXT,
  to_state TEXT NOT NULL CHECK(to_state IN ('FORMING','READY','FAILED','MISSING','INVALIDATED')),
  trigger_evidence_id TEXT,
  event_time INTEGER NOT NULL,
  availability_time INTEGER NOT NULL,
  reason_code TEXT NOT NULL,
  details_json TEXT NOT NULL
);

CREATE INDEX ix_setup_transition_setup
ON setup_transition(setup_id,availability_time);

CREATE TABLE shard_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
