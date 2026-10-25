-- Group 12 Autonomous Discovery — DRAFT
PRAGMA foreign_keys=ON;
CREATE TABLE discovery_feature_vector (
 vector_id TEXT PRIMARY KEY,vector_hash TEXT NOT NULL,subject_id TEXT NOT NULL,partition_id TEXT NOT NULL,
 availability_time INTEGER NOT NULL,feature_schema_id TEXT NOT NULL,features_json TEXT NOT NULL
);
CREATE INDEX ix_g12_vector_partition ON discovery_feature_vector(partition_id,availability_time);
CREATE TABLE discovered_relation (
 relation_id TEXT PRIMARY KEY,relation_hash TEXT NOT NULL,discovery_partition_id TEXT NOT NULL,
 method_id TEXT NOT NULL,definition_json TEXT NOT NULL,support REAL NOT NULL,effect_json TEXT NOT NULL,
 discovered_at INTEGER NOT NULL
);
CREATE TABLE confirmation_result (
 confirmation_id TEXT PRIMARY KEY,confirmation_hash TEXT NOT NULL,relation_id TEXT NOT NULL,
 confirmation_partition_id TEXT NOT NULL,status TEXT NOT NULL,metrics_json TEXT NOT NULL
);
