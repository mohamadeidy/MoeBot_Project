PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS metadata(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_registry(
    config_id TEXT PRIMARY KEY,
    engine_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_registry(
    dataset_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    year INTEGER NOT NULL,
    lineage TEXT NOT NULL,
    source_db_filename TEXT NOT NULL,
    source_db_size_bytes INTEGER NOT NULL,
    source_db_sha256 TEXT NOT NULL,
    group7_db_filename TEXT NOT NULL,
    group7_db_size_bytes INTEGER NOT NULL,
    group7_db_sha256 TEXT NOT NULL,
    data_release_tag TEXT NOT NULL,
    closure_tag TEXT NOT NULL,
    closure_commit_sha TEXT NOT NULL,
    adapter_map_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    record_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dependency_registry(
    dependency_id TEXT PRIMARY KEY,
    group_name TEXT NOT NULL,
    engine_version TEXT,
    schema_version TEXT,
    config_id TEXT,
    filename TEXT,
    size_bytes INTEGER,
    sha256 TEXT NOT NULL,
    lineage TEXT,
    read_only INTEGER NOT NULL CHECK(read_only=1),
    transitive INTEGER NOT NULL CHECK(transitive IN (0,1)),
    source_dependency_id TEXT,
    adapter_hash TEXT,
    record_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS school_registry(
    school_id TEXT PRIMARY KEY,
    school_version TEXT NOT NULL,
    school_name TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    prohibitions_json TEXT NOT NULL,
    school_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pattern_definition_registry(
    definition_id TEXT PRIMARY KEY,
    definition_version TEXT NOT NULL,
    school_id TEXT NOT NULL,
    definition_kind TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    FOREIGN KEY(school_id) REFERENCES school_registry(school_id)
);

CREATE TABLE IF NOT EXISTS interpretation_definition_registry(
    definition_id TEXT PRIMARY KEY,
    definition_version TEXT NOT NULL,
    school_id TEXT NOT NULL,
    interpretation_kind TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    FOREIGN KEY(school_id) REFERENCES school_registry(school_id)
);

CREATE TABLE IF NOT EXISTS price_action_pattern_candidate(
    candidate_id TEXT PRIMARY KEY,
    definition_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    source_bar_id INTEGER,
    related_source_bar_id INTEGER,
    event_time INTEGER NOT NULL,
    confirmation_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    lower REAL,
    upper REAL,
    intrinsic_pass INTEGER NOT NULL CHECK(intrinsic_pass IN (0,1)),
    ambiguous INTEGER NOT NULL CHECK(ambiguous IN (0,1)),
    reasons_json TEXT NOT NULL,
    features_json TEXT NOT NULL,
    upstream_refs_json TEXT NOT NULL,
    feature_hash TEXT NOT NULL,
    candidate_hash TEXT NOT NULL,
    FOREIGN KEY(definition_id) REFERENCES pattern_definition_registry(definition_id)
);

CREATE TABLE IF NOT EXISTS price_action_pattern_state(
    state_event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    state_ordinal INTEGER NOT NULL,
    source_bar_id INTEGER,
    event_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    state TEXT NOT NULL,
    ambiguous INTEGER NOT NULL CHECK(ambiguous IN (0,1)),
    details_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    UNIQUE(candidate_id,state_ordinal),
    FOREIGN KEY(candidate_id) REFERENCES price_action_pattern_candidate(candidate_id)
);

CREATE TABLE IF NOT EXISTS school_interpretation(
    interpretation_id TEXT PRIMARY KEY,
    definition_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    event_time INTEGER NOT NULL,
    confirmation_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    lifecycle_state TEXT NOT NULL,
    mandatory_evidence_complete INTEGER NOT NULL CHECK(mandatory_evidence_complete IN (0,1)),
    ambiguous INTEGER NOT NULL CHECK(ambiguous IN (0,1)),
    supporting_evidence_count INTEGER NOT NULL,
    conflicting_evidence_count INTEGER NOT NULL,
    evidence_strength_json TEXT NOT NULL,
    upstream_refs_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    interpretation_hash TEXT NOT NULL,
    FOREIGN KEY(definition_id) REFERENCES interpretation_definition_registry(definition_id),
    FOREIGN KEY(school_id) REFERENCES school_registry(school_id)
);

CREATE TABLE IF NOT EXISTS shared_evidence(
    shared_evidence_id TEXT PRIMARY KEY,
    source_group TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    subject_ids_json TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    availability_time INTEGER NOT NULL,
    details_json TEXT NOT NULL,
    shared_evidence_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conflicting_evidence(
    conflict_id TEXT PRIMARY KEY,
    left_subject_type TEXT NOT NULL,
    left_subject_id TEXT NOT NULL,
    right_subject_type TEXT NOT NULL,
    right_subject_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    event_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    details_json TEXT NOT NULL,
    conflict_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS narrative_hypothesis(
    hypothesis_id TEXT PRIMARY KEY,
    definition_id TEXT NOT NULL,
    school_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    direction TEXT NOT NULL,
    event_time INTEGER NOT NULL,
    confirmation_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    initial_state TEXT NOT NULL,
    mandatory_evidence_complete INTEGER NOT NULL CHECK(mandatory_evidence_complete IN (0,1)),
    ambiguous INTEGER NOT NULL CHECK(ambiguous IN (0,1)),
    supporting_evidence_count INTEGER NOT NULL,
    conflicting_evidence_count INTEGER NOT NULL,
    evidence_strength_json TEXT NOT NULL,
    upstream_refs_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    hypothesis_hash TEXT NOT NULL,
    FOREIGN KEY(definition_id) REFERENCES interpretation_definition_registry(definition_id),
    FOREIGN KEY(school_id) REFERENCES school_registry(school_id)
);

CREATE TABLE IF NOT EXISTS hypothesis_lifecycle_event(
    lifecycle_event_id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    lifecycle_ordinal INTEGER NOT NULL,
    source_type TEXT,
    source_id TEXT,
    event_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN (
        'candidate','active_supported','active_ambiguous','contradicted',
        'invalidated','completed_descriptive','right_censored'
    )),
    details_json TEXT NOT NULL,
    lifecycle_hash TEXT NOT NULL,
    UNIQUE(hypothesis_id,lifecycle_ordinal),
    FOREIGN KEY(hypothesis_id) REFERENCES narrative_hypothesis(hypothesis_id)
);

CREATE TABLE IF NOT EXISTS multi_timeframe_context_relation(
    relation_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    subject_timeframe TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_timeframe TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    event_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    overlap_ratio REAL,
    details_json TEXT NOT NULL,
    relation_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_chain(
    evidence_chain_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    evidence_ordinal INTEGER NOT NULL,
    source_group TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    source_timeframe TEXT,
    event_time INTEGER,
    availability_time INTEGER NOT NULL,
    details_json TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    UNIQUE(subject_type,subject_id,evidence_ordinal)
);

CREATE TABLE IF NOT EXISTS invalidation_record(
    invalidation_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    event_time INTEGER NOT NULL,
    confirmation_time INTEGER NOT NULL,
    availability_time INTEGER NOT NULL,
    reasons_json TEXT NOT NULL,
    details_json TEXT NOT NULL,
    invalidation_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group8_audit_evidence(
    audit_id TEXT PRIMARY KEY,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    details_json TEXT NOT NULL,
    checked_at INTEGER NOT NULL,
    audit_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_checkpoint(
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    last_bar_id INTEGER,
    last_time INTEGER,
    snapshot_hash TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(symbol,timeframe,stage)
);

CREATE INDEX IF NOT EXISTS ix_pa_candidate_tf_avail
    ON price_action_pattern_candidate(symbol,timeframe,availability_time,definition_id,candidate_id);
CREATE INDEX IF NOT EXISTS ix_pa_candidate_bar
    ON price_action_pattern_candidate(source_bar_id,definition_id,intrinsic_pass);
CREATE INDEX IF NOT EXISTS ix_pa_state_candidate_time
    ON price_action_pattern_state(candidate_id,availability_time,state_ordinal);
CREATE INDEX IF NOT EXISTS ix_school_interpretation_tf_avail
    ON school_interpretation(symbol,timeframe,availability_time,school_id,definition_id);
CREATE INDEX IF NOT EXISTS ix_hypothesis_tf_avail
    ON narrative_hypothesis(symbol,timeframe,availability_time,school_id,definition_id);
CREATE INDEX IF NOT EXISTS ix_hypothesis_lifecycle_time
    ON hypothesis_lifecycle_event(hypothesis_id,availability_time,lifecycle_ordinal);
CREATE INDEX IF NOT EXISTS ix_evidence_subject
    ON evidence_chain(subject_type,subject_id,availability_time,evidence_ordinal);
CREATE INDEX IF NOT EXISTS ix_shared_source
    ON shared_evidence(source_group,source_type,source_id,availability_time);
CREATE INDEX IF NOT EXISTS ix_conflict_left
    ON conflicting_evidence(left_subject_type,left_subject_id,availability_time);
CREATE INDEX IF NOT EXISTS ix_conflict_right
    ON conflicting_evidence(right_subject_type,right_subject_id,availability_time);
CREATE INDEX IF NOT EXISTS ix_mtf_subject
    ON multi_timeframe_context_relation(subject_type,subject_id,availability_time);
CREATE INDEX IF NOT EXISTS ix_invalidation_subject
    ON invalidation_record(subject_type,subject_id,availability_time);

CREATE TRIGGER IF NOT EXISTS no_update_price_action_pattern_candidate
BEFORE UPDATE ON price_action_pattern_candidate BEGIN
    SELECT RAISE(ABORT,'immutable creation record: price_action_pattern_candidate');
END;
CREATE TRIGGER IF NOT EXISTS no_delete_price_action_pattern_candidate
BEFORE DELETE ON price_action_pattern_candidate BEGIN
    SELECT RAISE(ABORT,'immutable creation record: price_action_pattern_candidate');
END;
CREATE TRIGGER IF NOT EXISTS no_update_school_interpretation
BEFORE UPDATE ON school_interpretation BEGIN
    SELECT RAISE(ABORT,'immutable creation record: school_interpretation');
END;
CREATE TRIGGER IF NOT EXISTS no_delete_school_interpretation
BEFORE DELETE ON school_interpretation BEGIN
    SELECT RAISE(ABORT,'immutable creation record: school_interpretation');
END;
CREATE TRIGGER IF NOT EXISTS no_update_narrative_hypothesis
BEFORE UPDATE ON narrative_hypothesis BEGIN
    SELECT RAISE(ABORT,'immutable creation record: narrative_hypothesis');
END;
CREATE TRIGGER IF NOT EXISTS no_delete_narrative_hypothesis
BEFORE DELETE ON narrative_hypothesis BEGIN
    SELECT RAISE(ABORT,'immutable creation record: narrative_hypothesis');
END;
CREATE TRIGGER IF NOT EXISTS no_update_shared_evidence
BEFORE UPDATE ON shared_evidence BEGIN
    SELECT RAISE(ABORT,'immutable creation record: shared_evidence');
END;
CREATE TRIGGER IF NOT EXISTS no_delete_shared_evidence
BEFORE DELETE ON shared_evidence BEGIN
    SELECT RAISE(ABORT,'immutable creation record: shared_evidence');
END;
CREATE TRIGGER IF NOT EXISTS no_update_conflicting_evidence
BEFORE UPDATE ON conflicting_evidence BEGIN
    SELECT RAISE(ABORT,'immutable creation record: conflicting_evidence');
END;
CREATE TRIGGER IF NOT EXISTS no_delete_conflicting_evidence
BEFORE DELETE ON conflicting_evidence BEGIN
    SELECT RAISE(ABORT,'immutable creation record: conflicting_evidence');
END;
