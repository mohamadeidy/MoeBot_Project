-- Group 14 Final Validation & Robustness — DRAFT
PRAGMA foreign_keys=ON;
CREATE TABLE validation_run (
 run_id TEXT PRIMARY KEY,run_hash TEXT NOT NULL,policy_hash TEXT NOT NULL,holdout_plan_hash TEXT NOT NULL,
 validation_type TEXT NOT NULL,start_time INTEGER NOT NULL,end_time INTEGER NOT NULL,
 status TEXT NOT NULL,metrics_json TEXT NOT NULL
);
CREATE TABLE stress_result (
 stress_id TEXT PRIMARY KEY,stress_hash TEXT NOT NULL,run_id TEXT NOT NULL,scenario_type TEXT NOT NULL,
 scenario_json TEXT NOT NULL,result_json TEXT NOT NULL
);
CREATE TABLE monte_carlo_result (
 mc_id TEXT PRIMARY KEY,mc_hash TEXT NOT NULL,run_id TEXT NOT NULL,seed TEXT NOT NULL,
 iterations INTEGER NOT NULL,summary_json TEXT NOT NULL
);
CREATE TABLE failure_analysis (
 failure_id TEXT PRIMARY KEY,failure_hash TEXT NOT NULL,run_id TEXT NOT NULL,
 category TEXT NOT NULL,evidence_json TEXT NOT NULL,policy_change_recommended INTEGER NOT NULL
);
