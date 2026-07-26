#!/usr/bin/env python3
"""Apply the reviewed Group 8 lifecycle-persistence integration once, fail closed."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_ENGINE_SHA256 = "58d8283d18a93b25e33f3ec5b991a926318f4591a0aa24e4fc1ee2955e7d1e88"
GAP_ID = "G8-ENGINE-LIFECYCLE-002"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact block, found {count}")
    path.write_text(text.replace(old, new, 1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group8-root", type=Path, required=True)
    parser.add_argument("--build-workflow", type=Path, required=True)
    args = parser.parse_args()
    root = args.group8_root.resolve()
    engine = root / "code/moebot_group8_engine_v0_8_0.py"
    audit_tool = root / "code/group8_technical_candidate_audit.py"
    finalizer = root / "code/group8_finalize_engine_build.py"
    build_workflow = args.build_workflow.resolve()
    status_path = root / "STATUS.json"
    manifest = json.loads((root / "ENGINE_BUILD_MANIFEST.json").read_text())
    status = json.loads(status_path.read_text())

    actual = sha256_file(engine)
    if actual != EXPECTED_ENGINE_SHA256:
        raise SystemExit(f"authoritative engine identity mismatch: {actual}")
    if manifest["identities"]["engine"]["sha256"] != EXPECTED_ENGINE_SHA256:
        raise SystemExit("engine build manifest does not bind expected reviewed engine")
    if status.get("annual_execution_2023_authorized") is not True:
        raise SystemExit("2023 was not authorized at gap discovery point")
    if status.get("annual_execution_2024_authorized") is not False:
        raise SystemExit("2024 OOS was unexpectedly authorized")

    replace_once(
        engine,
        '        self._insert_immutable("price_action_pattern_candidate", "candidate_id", cid, row, hash_column="candidate_hash", expected_hash=candidate_hash); self.definition_coverage[definition_id] += 1; return cid\n',
        '        self._insert_immutable("price_action_pattern_candidate", "candidate_id", cid, row, hash_column="candidate_hash", expected_hash=candidate_hash)\n        self.definition_coverage[definition_id] += 1\n        from group8_postprocess_v0_8_0 import ensure_pattern_creation_state\n        ensure_pattern_creation_state(self, cid)\n        return cid\n',
        "pattern-state integration",
    )
    replace_once(
        engine,
        '''        inserted = self._insert_immutable("narrative_hypothesis", "hypothesis_id", hid, row, hash_column="hypothesis_hash", expected_hash=h)\n        self.definition_coverage[definition_id] += 1\n        self._write_evidence_chain("narrative_hypothesis", hid, refs)\n        if inserted:\n            self._append_lifecycle(hid, initial_state, event_time=event_time, availability_time=availability_time, source_type=None, source_id=None, details={"creation": True})\n        return hid\n''',
        '''        self._insert_immutable("narrative_hypothesis", "hypothesis_id", hid, row, hash_column="hypothesis_hash", expected_hash=h)\n        self.definition_coverage[definition_id] += 1\n        self._write_evidence_chain("narrative_hypothesis", hid, refs)\n        from group8_postprocess_v0_8_0 import ensure_initial_hypothesis_lifecycle\n        ensure_initial_hypothesis_lifecycle(self, hid, initial_state, event_time=int(event_time), availability_time=int(availability_time))\n        return hid\n''',
        "crash-safe initial lifecycle integration",
    )
    replace_once(
        engine,
        '    def process_structural_narratives(self) -> None:\n        states=[dict(r) for r in self.input.execute("SELECT * FROM group3__structure_states ORDER BY close_time,state_id")];',
        '    def process_structural_narratives(self) -> None:\n        from group8_postprocess_v0_8_0 import continuation_structure_valid\n        states=[dict(r) for r in self.input.execute("SELECT * FROM group3__structure_states ORDER BY close_time,state_id")];',
        "continuation helper import",
    )
    replace_once(
        engine,
        '                if later: self._write_hypothesis("pa_continuation_after_pullback"',
        '                if later and continuation_structure_valid(self, st, leg, later, sd): self._write_hypothesis("pa_continuation_after_pullback"',
        "continuation structure-validity guard",
    )
    old_run = '''    def run(self) -> dict[str, Any]:\n        self.load_bars();self.process_base_price_action();self.process_dow();self.process_bounded_ranges();self.process_breakouts();self.process_context_rejections();self.process_failed_breakouts_and_retests();self.process_structural_narratives();self.process_wyckoff();self.process_ict();self.process_cross_school_and_mtf();report=self.audit(require_all_definitions_producible=False);self.out.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",("engine_audit_hash",report["report_hash"]));self.out.commit();return report\n'''
    new_run = '''    def run(self) -> dict[str, Any]:\n        from group8_postprocess_v0_8_0 import checkpoint, finalize_postprocessing, persist_audit_evidence\n        stages = [\n            ("load_bars", self.load_bars),\n            ("base_price_action", self.process_base_price_action),\n            ("dow", self.process_dow),\n            ("bounded_ranges", self.process_bounded_ranges),\n            ("breakouts", self.process_breakouts),\n            ("context_rejections", self.process_context_rejections),\n            ("failed_breakouts_retests", self.process_failed_breakouts_and_retests),\n            ("structural_narratives", self.process_structural_narratives),\n            ("wyckoff", self.process_wyckoff),\n            ("ict", self.process_ict),\n            ("cross_school_mtf", self.process_cross_school_and_mtf),\n        ]\n        for stage_name, stage_fn in stages:\n            stage_fn()\n            checkpoint(self, stage_name)\n        persistence_report = finalize_postprocessing(self)\n        checkpoint(self, "lifecycle_persistence")\n        report = self.audit(require_all_definitions_producible=False)\n        persist_audit_evidence(self, report, persistence_report)\n        checkpoint(self, "final_audit")\n        report = self.audit(require_all_definitions_producible=False)\n        self.out.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",("engine_audit_hash",report["report_hash"]))\n        self.out.commit()\n        return report\n'''
    replace_once(engine, old_run, new_run, "stage checkpoint/postprocessing run integration")
    replace_once(
        engine,
        'counts={t:self.out.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ["price_action_pattern_candidate","school_interpretation","narrative_hypothesis","hypothesis_lifecycle_event","shared_evidence","conflicting_evidence","multi_timeframe_context_relation","evidence_chain"]};',
        'counts={t:self.out.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ["price_action_pattern_candidate","price_action_pattern_state","school_interpretation","narrative_hypothesis","hypothesis_lifecycle_event","invalidation_record","group8_audit_evidence","processing_checkpoint","shared_evidence","conflicting_evidence","multi_timeframe_context_relation","evidence_chain"]};',
        "expanded audit persistence counts",
    )

    replace_once(
        audit_tool,
        "    engine_path=root/'code/moebot_group8_engine_v0_8_0.py';materializer_path=root/'code/group8_materialize_inputs.py';test_path=root/'tests/test_group8_engine_v0_8_0.py'\n",
        "    engine_path=root/'code/moebot_group8_engine_v0_8_0.py';materializer_path=root/'code/group8_materialize_inputs.py';postprocessor_path=root/'code/group8_postprocess_v0_8_0.py';test_path=root/'tests/test_group8_engine_v0_8_0.py';lifecycle_test_path=root/'tests/test_group8_lifecycle_persistence_v0_8_0.py'\n",
        "audit path binding",
    )
    replace_once(
        audit_tool,
        "    engine_text=engine_path.read_text();materializer_text=materializer_path.read_text();future_refs=sorted(t for t in FORBIDDEN_TABLE_REFERENCES if t in engine_text or t in materializer_text)\n",
        "    engine_text=engine_path.read_text();materializer_text=materializer_path.read_text();postprocessor_text=postprocessor_path.read_text();future_refs=sorted(t for t in FORBIDDEN_TABLE_REFERENCES if t in engine_text or t in materializer_text or t in postprocessor_text)\n    lifecycle_markers=['ensure_pattern_creation_state','ensure_initial_hypothesis_lifecycle','continuation_structure_valid','finalize_postprocessing','processing_checkpoint','invalidation_record','group8_audit_evidence','right_censored','completed_descriptive','contradicted']\n    checks['lifecycle_persistence_hardening_present']=all(x in engine_text+postprocessor_text for x in lifecycle_markers)\n    if not checks['lifecycle_persistence_hardening_present']:failures.append({'lifecycle_persistence_markers_missing':[x for x in lifecycle_markers if x not in engine_text+postprocessor_text]})\n",
        "audit lifecycle binding",
    )
    replace_once(
        audit_tool,
        "    hashes={'engine_sha256':file_hash(engine_path),'materializer_sha256':file_hash(materializer_path),'tests_sha256':file_hash(test_path),'schema_sha256':file_hash(root/'02_SCHEMA.sql'),'definition_registry_file_sha256':file_hash(root/'01_DEFINITION_REGISTRY.json'),'frozen_config_file_sha256':file_hash(root/'FROZEN_CONFIG.json')}\n",
        "    hashes={'engine_sha256':file_hash(engine_path),'materializer_sha256':file_hash(materializer_path),'postprocessor_sha256':file_hash(postprocessor_path),'tests_sha256':file_hash(test_path),'lifecycle_tests_sha256':file_hash(lifecycle_test_path),'schema_sha256':file_hash(root/'02_SCHEMA.sql'),'definition_registry_file_sha256':file_hash(root/'01_DEFINITION_REGISTRY.json'),'frozen_config_file_sha256':file_hash(root/'FROZEN_CONFIG.json')}\n",
        "audit identity hashes",
    )

    replace_once(
        finalizer,
        "    files={'engine':'code/moebot_group8_engine_v0_8_0.py','materializer':'code/group8_materialize_inputs.py','tests':'tests/test_group8_engine_v0_8_0.py','technical_audit':'reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json','schema':'02_SCHEMA.sql','definitions':'01_DEFINITION_REGISTRY.json','config':'FROZEN_CONFIG.json','upstream_contract':'contracts/UPSTREAM_INPUT_CONTRACT.json'}\n",
        "    files={'engine':'code/moebot_group8_engine_v0_8_0.py','materializer':'code/group8_materialize_inputs.py','postprocessor':'code/group8_postprocess_v0_8_0.py','tests':'tests/test_group8_engine_v0_8_0.py','lifecycle_tests':'tests/test_group8_lifecycle_persistence_v0_8_0.py','technical_audit':'reports/20_ENGINE_TECHNICAL_CANDIDATE_AUDIT.json','schema':'02_SCHEMA.sql','definitions':'01_DEFINITION_REGISTRY.json','config':'FROZEN_CONFIG.json','upstream_contract':'contracts/UPSTREAM_INPUT_CONTRACT.json'}\n",
        "finalizer identities",
    )
    replace_once(
        finalizer,
        "    status['engine_build']={'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'engine_sha256':identities['engine']['sha256'],'materializer_sha256':identities['materializer']['sha256'],'technical_audit_hash':audit['report_hash'],'engine_build_manifest_hash':manifest['manifest_hash']}\n",
        "    status['engine_build']={'status':'TECHNICAL_CANDIDATE_PASS','engine_version':ENGINE_VERSION,'schema_version':SCHEMA_VERSION,'config_id':CONFIG_ID,'engine_sha256':identities['engine']['sha256'],'materializer_sha256':identities['materializer']['sha256'],'postprocessor_sha256':identities['postprocessor']['sha256'],'technical_audit_hash':audit['report_hash'],'engine_build_manifest_hash':manifest['manifest_hash']}\n",
        "finalizer status identity",
    )

    replace_once(
        build_workflow,
        '          python "$GROUP8_ROOT/tests/test_group8_engine_v0_8_0.py"\n',
        '          python "$GROUP8_ROOT/tests/test_group8_engine_v0_8_0.py"\n          PYTHONPATH="$GROUP8_ROOT/code:$GROUP8_ROOT/tests" python "$GROUP8_ROOT/tests/test_group8_lifecycle_persistence_v0_8_0.py"\n',
        "technical workflow lifecycle regression",
    )

    report = {
        "format_version": 1,
        "status": "BLOCKING_GAP_FIXED_PENDING_RETEST",
        "phase": "ENGINE_BUILD_REVIEW_GAP_ANALYSIS",
        "gap_id": GAP_ID,
        "severity": "BLOCKING",
        "root_causes": [
            "Frozen persistent tables price_action_pattern_state, invalidation_record, group8_audit_evidence and processing_checkpoint were not populated by the technical candidate.",
            "Hypothesis lifecycle persistence did not provide contradiction/invalidation/completion/right-censor terminal semantics.",
            "The inserted-only initial lifecycle fix could not repair an interruption after hypothesis creation but before ordinal-0 lifecycle insertion.",
            "pa_continuation_after_pullback did not enforce referenced Group3 structure validity through the later same-direction validated displacement.",
        ],
        "minimal_correct_fix": [
            "Deterministic crash-recoverable ordinal-0 pattern/hypothesis state persistence.",
            "Append-only deterministic contradiction/terminal lifecycle and invalidation evidence.",
            "Deterministic stage checkpoints and Group8 audit evidence.",
            "Fail-closed continuation structure-validity gate before creation.",
            "Expanded lifecycle persistence, crash recovery, row-order, gap, and dependency rejection regression tests.",
        ],
        "previous_engine_sha256": EXPECTED_ENGINE_SHA256,
        "design_changed": False,
        "thresholds_changed": False,
        "upstream_changed": False,
        "2023_authorized_after_gap_detection": False,
        "2024_authorized": False,
    }
    report["report_hash"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    (root / "reports/22_ENGINE_LIFECYCLE_PERSISTENCE_GAP_ANALYSIS.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    status["annual_execution_authorized"] = False
    status["annual_execution_2023_authorized"] = False
    status["annual_execution_2024_authorized"] = False
    status["officially_closed"] = False
    status["status"] = "ENGINE_LIFECYCLE_PERSISTENCE_GAP_FIXED_PENDING_RETEST"
    status["engine_build"]["status"] = "BLOCKING_GAP_FIXED_PENDING_RETEST"
    status["engine_build"]["review_gap_id"] = GAP_ID
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PATCHED", "gap_id": GAP_ID, "new_engine_sha256": sha256_file(engine)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
