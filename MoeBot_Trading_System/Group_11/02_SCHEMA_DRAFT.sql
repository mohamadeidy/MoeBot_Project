-- Group 11 Visual Dataset & Audit — DRAFT
PRAGMA foreign_keys=ON;
CREATE TABLE visual_recipe (
 recipe_id TEXT PRIMARY KEY,recipe_hash TEXT NOT NULL,subject_type TEXT NOT NULL,subject_id TEXT NOT NULL,
 symbol TEXT NOT NULL,timeframe TEXT NOT NULL,window_start INTEGER NOT NULL,window_end INTEGER NOT NULL,
 renderer_version TEXT NOT NULL,overlay_spec_json TEXT NOT NULL,annotation_spec_json TEXT NOT NULL
);
CREATE INDEX ix_g11_recipe_subject ON visual_recipe(subject_type,subject_id);
CREATE TABLE visual_sample_manifest (
 sample_id TEXT PRIMARY KEY,sample_hash TEXT NOT NULL,stratum_id TEXT NOT NULL,recipe_id TEXT NOT NULL,
 selection_rank INTEGER NOT NULL,selection_seed TEXT NOT NULL,canonical_example INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE visual_audit_result (
 audit_id TEXT PRIMARY KEY,audit_hash TEXT NOT NULL,recipe_id TEXT NOT NULL,audit_version TEXT NOT NULL,
 status TEXT NOT NULL,review_time INTEGER NOT NULL,findings_json TEXT NOT NULL
);
