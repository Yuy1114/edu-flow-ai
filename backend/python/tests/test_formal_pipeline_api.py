from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.pipeline import (
    GENERATABLE_ALLOCATION_TASK_STATUSES,
    PipelineJobRequest,
    _allocation_task_status,
    _finish_failed_or_recover,
    _parse_pipeline_result,
    _pipeline_terminal_error,
    _pipeline_command,
    _recover_interrupted_run,
    _to_status,
    _validate_formal_request,
)
from scheduler.import_db_draft_to_mysql import TABLE_FILES, _validate_import_identity, import_draft
from scheduler.export_template_as_scheme import _scheme_review_state
from scheduler.run_pipeline import _require_import_status


class FormalPipelineApiTest(unittest.TestCase):
    def test_formal_command_always_imports_and_never_truncates_or_trains(self):
        request = PipelineJobRequest(allocationTaskId=42)

        command = _pipeline_command(request)

        self.assertIn("--import-db", command)
        self.assertNotIn("--truncate-db", command)
        self.assertNotIn("--train-model", command)
        self.assertEqual(command[command.index("--allocation-task-id") + 1], "42")

    def test_formal_entry_rejects_non_persistent_or_destructive_modes(self):
        invalid_requests = [
            PipelineJobRequest(allocationTaskId=1, importDb=False),
            PipelineJobRequest(allocationTaskId=1, truncateDb=True),
            PipelineJobRequest(allocationTaskId=1, trainModel=True),
        ]

        for request in invalid_requests:
            with self.subTest(request=request.model_dump()):
                with self.assertRaises(HTTPException) as raised:
                    _validate_formal_request(request)
                self.assertEqual(raised.exception.status_code, 422)

    def test_formal_entry_rejects_weeks_outside_the_materializable_catalog(self):
        self.assertEqual(PipelineJobRequest(allocationTaskId=1).totalWeeks, 18)
        with self.assertRaises(ValueError):
            PipelineJobRequest(allocationTaskId=1, totalWeeks=19)

    def test_structured_result_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "pipeline.log"
            log.write_text(
                "ordinary log\n"
                'EDUFLOW_PIPELINE_RESULT={"status":"NEEDS_MANUAL_REVIEW","summary":"/tmp/s.json"}\n',
                encoding="utf-8",
            )
            self.assertEqual(_parse_pipeline_result(log)["status"], "NEEDS_MANUAL_REVIEW")

            log.write_text("ordinary log only\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _parse_pipeline_result(log)

    def test_manual_or_blocked_status_exposes_specific_gate_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.json"
            summary.write_text(
                json.dumps({
                    "publication_gate": {
                        "manual_reviews": ["irregular task patterns=1"],
                        "hard_blockers": ["hard conflicts=2"],
                    }
                }),
                encoding="utf-8",
            )
            manual = _pipeline_terminal_error(
                "NEEDS_MANUAL_REVIEW", {}, str(summary)
            )
            blocked = _pipeline_terminal_error("BLOCKED", {}, str(summary))

            self.assertIn("irregular task patterns=1", manual)
            self.assertIn("hard conflicts=2", blocked)

    def test_persisted_status_survives_java_process_state(self):
        status = _to_status({
            "id": "pipeline-abc",
            "status": "RUNNING",
            "progress": 10,
            "started_at_ms": 123,
            "finished_at_ms": None,
            "summary_path": None,
            "error_message": None,
        })

        self.assertEqual(status.jobId, "pipeline-abc")
        self.assertEqual(status.status, "RUNNING")
        self.assertEqual(status.startedAt, 123)

    def test_durable_job_is_the_allocation_task_status_source(self):
        # Every terminal class is mapped in Python, so task status never depends
        # on a Java client continuing to poll after submission.
        self.assertEqual(_allocation_task_status("QUEUED"), "RUNNING")
        self.assertEqual(_allocation_task_status("RUNNING"), "RUNNING")
        self.assertEqual(_allocation_task_status("SUCCESS"), "GENERATED")
        self.assertEqual(
            _allocation_task_status("NEEDS_MANUAL_REVIEW"),
            "NEEDS_MANUAL_REVIEW",
        )
        self.assertEqual(_allocation_task_status("BLOCKED"), "BLOCKED")
        self.assertEqual(_allocation_task_status("FAILED"), "FAILED")
        with self.assertRaises(ValueError):
            _allocation_task_status("MYSTERY")

    def test_direct_api_generation_contract_matches_java_fail_closed_contract(self):
        self.assertEqual(
            GENERATABLE_ALLOCATION_TASK_STATUSES,
            {"CREATED", "DRAFT", "PENDING", "FAILED", "BLOCKED"},
        )
        self.assertNotIn("GENERATED", GENERATABLE_ALLOCATION_TASK_STATUSES)
        self.assertNotIn("NEEDS_MANUAL_REVIEW", GENERATABLE_ALLOCATION_TASK_STATUSES)

    def test_restart_recovers_the_terminal_sentinel_before_marking_a_job_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "pipeline.log"
            log.write_text(
                'EDUFLOW_PIPELINE_RESULT={"status":"BLOCKED","publication_gate":'
                '{"hard_blockers":["inactive classroom=1"]}}\n',
                encoding="utf-8",
            )

            recovered = _recover_interrupted_run({"log_path": str(log)}, None)

        self.assertEqual(recovered["status"], "BLOCKED")
        self.assertIn("inactive classroom=1", recovered["error_message"])

    def test_restart_keeps_an_atomically_committed_candidate_queryable(self):
        successful = _recover_interrupted_run(
            {"log_path": "/missing/pipeline.log"},
            {"valid": 1, "status": "CANDIDATE"},
        )
        manual = _recover_interrupted_run(
            {"log_path": "/missing/pipeline.log"},
            {"valid": 0, "status": "CANDIDATE"},
        )
        failed = _recover_interrupted_run(
            {"log_path": "/missing/pipeline.log"},
            None,
        )

        self.assertEqual(successful["status"], "SUCCESS")
        self.assertEqual(manual["status"], "NEEDS_MANUAL_REVIEW")
        self.assertEqual(failed["status"], "FAILED")

    def test_nonzero_child_exit_recovers_an_atomically_committed_candidate(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("app.api.v1.pipeline._find_candidate", return_value={
                    "valid": 1, "status": "CANDIDATE",
                }), \
                patch("app.api.v1.pipeline._finish_job") as finish_job:
            _finish_failed_or_recover(
                "pipeline-after-commit",
                allocation_task_id=42,
                log_path=Path(directory) / "truncated.log",
                original_error="pipeline exited with code 1",
            )

        finish_job.assert_called_once_with(
            "pipeline-after-commit",
            status_value="SUCCESS",
            pipeline_status="OK",
            summary_path=None,
            error=None,
        )


class FormalImportContractTest(unittest.TestCase):
    class _MissingTableCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, _params=None):
            if sql.strip() != "SHOW TABLES":
                raise AssertionError(f"unexpected SQL after missing-table gate: {sql}")

        def fetchall(self):
            return [
                {"table": table}
                for table in TABLE_FILES
                if table != "schedule_template_fragment_slot"
            ]

    class _MissingTableConnection:
        def __init__(self):
            self.rolled_back = False

        def cursor(self):
            return FormalImportContractTest._MissingTableCursor()

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    def test_execute_with_missing_tables_raises_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory)
            for filename in TABLE_FILES.values():
                (input_dir / filename).write_text(
                    '{"generation_run_id":"v35-missing-table-proof"}\n',
                    encoding="utf-8",
                )
            connection = self._MissingTableConnection()
            with self.assertRaisesRegex(RuntimeError, "missing required tables"):
                import_draft(
                    input_dir=input_dir,
                    execute=True,
                    connection=connection,
                    commit=False,
                )
            self.assertTrue(connection.rolled_back)

    def test_every_draft_table_must_share_one_generation_run(self):
        rows = {
            table: [{"generation_run_id": "v35-run-1"}]
            for table in TABLE_FILES
        }
        self.assertEqual(_validate_import_identity(rows), "v35-run-1")

        rows["schedule_template_fragment_slot"][0]["generation_run_id"] = "v35-run-2"
        with self.assertRaises(ValueError):
            _validate_import_identity(rows)

    def test_requested_import_must_report_inserted(self):
        _require_import_status({"status": "inserted"}, step="test")
        for report in ({"status": "missing_tables"}, {"status": "dry_run_ok"}, {}):
            with self.subTest(report=json.dumps(report)):
                with self.assertRaises(RuntimeError):
                    _require_import_status(report, step="test")

    def test_publication_gate_manual_reason_is_persisted_in_scheme_review(self):
        review = _scheme_review_state(
            {"conflicts": {}, "remaining_task_count": 0, "conservation_mismatch": 0},
            publication_gate={
                "status": "NEEDS_MANUAL_REVIEW",
                "hard_blockers": [],
                "manual_reviews": ["irregular task patterns=1"],
            },
        )

        self.assertEqual(review["review_status"], "NEEDS_MANUAL_REVIEW")
        self.assertFalse(review["hard_blocked"])
        self.assertIn(
            "irregular task patterns=1",
            review["conflict_summary"]["publication_gate_manual_reviews"],
        )


if __name__ == "__main__":
    unittest.main()
