-- Group 13 Policy Learning — DRAFT
PRAGMA foreign_keys=ON;
CREATE TABLE policy_candidate (
 policy_id TEXT PRIMARY KEY,policy_hash TEXT NOT NULL,training_manifest_hash TEXT NOT NULL,
 action_vocabulary_json TEXT NOT NULL,model_type TEXT NOT NULL,artifact_ref TEXT NOT NULL,
 created_at INTEGER NOT NULL,metrics_json TEXT NOT NULL
);
CREATE TABLE policy_decision_trace (
 trace_id TEXT PRIMARY KEY,trace_hash TEXT NOT NULL,policy_id TEXT NOT NULL,subject_id TEXT NOT NULL,
 decision_time INTEGER NOT NULL,availability_time INTEGER NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('WAIT','BUY','SELL','HOLD','EXIT')),
 score REAL,explanation_json TEXT NOT NULL
);
CREATE INDEX ix_g13_trace_policy ON policy_decision_trace(policy_id,availability_time);
CREATE TABLE policy_training_manifest (
 manifest_id TEXT PRIMARY KEY,manifest_hash TEXT NOT NULL,discovery_cutoff INTEGER NOT NULL,
 train_partition_json TEXT NOT NULL,validation_partition_json TEXT NOT NULL,
 final_holdout_accessed INTEGER NOT NULL CHECK(final_holdout_accessed=0)
);
