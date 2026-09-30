-- Group 10 Outcome & Counterfactual Intelligence — DRAFT
PRAGMA foreign_keys=ON;
CREATE TABLE setup_outcome (
 outcome_id TEXT PRIMARY KEY,outcome_hash TEXT NOT NULL,setup_id TEXT NOT NULL,
 setup_availability_time INTEGER NOT NULL,horizon_id TEXT NOT NULL,
 observation_end_time INTEGER NOT NULL,observation_end_availability_time INTEGER NOT NULL,
 mfe_price REAL,mae_price REAL,mfe_r REAL,mae_r REAL,time_to_mfe INTEGER,time_to_mae INTEGER,
 terminal_code TEXT,cost_model_id TEXT,details_json TEXT NOT NULL
);
CREATE INDEX ix_g10_outcome_setup ON setup_outcome(setup_id,horizon_id);
CREATE TABLE counterfactual_path (
 path_id TEXT PRIMARY KEY,path_hash TEXT NOT NULL,setup_id TEXT NOT NULL,scenario_id TEXT NOT NULL,
 start_time INTEGER NOT NULL,start_availability_time INTEGER NOT NULL,end_time INTEGER NOT NULL,
 transaction_cost REAL,slippage_assumption REAL,result_json TEXT NOT NULL
);
CREATE INDEX ix_g10_path_setup ON counterfactual_path(setup_id,scenario_id);
CREATE TABLE excursion_event (
 event_id TEXT PRIMARY KEY,event_hash TEXT NOT NULL,setup_id TEXT NOT NULL,event_type TEXT NOT NULL,
 event_time INTEGER NOT NULL,availability_time INTEGER NOT NULL,value REAL,details_json TEXT NOT NULL
);
