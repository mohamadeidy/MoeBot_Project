-- Group 15 Live Execution & Integration — DRAFT
PRAGMA foreign_keys=ON;
CREATE TABLE order_intent (
 intent_id TEXT PRIMARY KEY,intent_hash TEXT NOT NULL,policy_hash TEXT NOT NULL,
 decision_trace_id TEXT NOT NULL,symbol TEXT NOT NULL,action TEXT NOT NULL,
 created_time INTEGER NOT NULL,risk_request_json TEXT NOT NULL
);
CREATE TABLE risk_reservation (
 reservation_id TEXT PRIMARY KEY,reservation_hash TEXT NOT NULL,intent_id TEXT NOT NULL,
 reserved_risk REAL NOT NULL,created_time INTEGER NOT NULL,released_time INTEGER,status TEXT NOT NULL
);
CREATE TABLE execution_event (
 execution_id TEXT PRIMARY KEY,execution_hash TEXT NOT NULL,intent_id TEXT NOT NULL,
 broker_order_id TEXT,event_type TEXT NOT NULL,event_time INTEGER NOT NULL,details_json TEXT NOT NULL
);
CREATE TABLE fill_audit (
 fill_id TEXT PRIMARY KEY,fill_hash TEXT NOT NULL,intent_id TEXT NOT NULL,broker_order_id TEXT,
 requested_price REAL,fill_price REAL,slippage REAL,latency_ms REAL,event_time INTEGER NOT NULL,
 audit_json TEXT NOT NULL
);
CREATE TABLE health_event (
 health_id TEXT PRIMARY KEY,health_hash TEXT NOT NULL,event_time INTEGER NOT NULL,severity TEXT NOT NULL,
 component TEXT NOT NULL,details_json TEXT NOT NULL
);
