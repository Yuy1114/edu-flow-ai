from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.repositories import _parse_availability_matrix_unavailable
from scheduler.export_template_cover_db_draft import export_db_draft
from scheduler.export_template_as_scheme import _scheme_review_state
from scheduler.fetch_allocation_teaching_tasks import (
    _is_explicitly_excluded,
    _parse_unavailable_matrix,
    _resource_issues,
    enrich_patterns_with_constraints,
)
from scheduler.query_db_draft_timetable import query_week
from scheduler.run_pipeline import (
    _overall_hour_audit,
    _publication_gate,
    _validate_allowed_config,
)
from scheduler.validate_db_draft_export import validate_export


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class SchedulerConstraintAlignmentTest(unittest.TestCase):
    def test_enrichment_restores_ids_and_hard_constraints_after_pattern_build(self) -> None:
        task = {
            "source_key": "task:42",
            "course_id": 7,
            "primary_teacher_id": 11,
            "assistant_teacher_id": 12,
            "teacher_ids": [11, 12],
            "class_group_ids": [21, 22],
            "fixed_classroom_id": 31,
            "fixed_classroom_name": "A101",
            "candidate_classroom_ids": [31, 32],
            "candidate_classroom_names": ["A101", "A102"],
            "teacher_unavailable_slots": [{
                "teacher_id": 12,
                "week_number": None,
                "day_of_week": 3,
                "period_index": 5,
            }],
            "allowed_weeks": [1, 2],
        }
        pattern = {"source_key": "task:42", "duration_weeks": 2}

        with TemporaryDirectory() as directory:
            root = Path(directory)
            tasks_path = root / "tasks.jsonl"
            patterns_path = root / "patterns.jsonl"
            _write_jsonl(tasks_path, [task])
            _write_jsonl(patterns_path, [pattern])

            report = enrich_patterns_with_constraints(
                patterns_path=patterns_path,
                task_source_path=tasks_path,
                allowed_weeks={2, 4},
            )
            enriched = _read_jsonl(patterns_path)[0]

        self.assertEqual(report["missing_source_count"], 0)
        self.assertEqual(enriched["teacher_ids"], [11, 12])
        self.assertEqual(enriched["class_group_ids"], [21, 22])
        self.assertEqual(enriched["fixed_classroom_id"], 31)
        self.assertEqual(enriched["allowed_weeks"], [2, 4])
        self.assertEqual(enriched["teacher_unavailable_slots"][0]["period_index"], 5)

    def test_export_preserves_multiclass_assistant_and_room_stable_ids(self) -> None:
        cover = {
            "templates": [{
                "template_id": "dynamic-a",
                "week_numbers": [1, 2],
                "week_budget": 2,
                "fragments": [{
                    "fragment_id": "task:42#frag1",
                    "source_key": "task:42",
                    "teaching_task_id": 42,
                    "course_name": "数据库",
                    "teacher_name": "主讲",
                    "class_names": "软工1班,软工2班",
                    "classroom_name": "A101",
                    "day_of_week": 1,
                    "period_index": 1,
                    "segments": [
                        {"day_of_week": 1, "period_index": 1},
                        {"day_of_week": 1, "period_index": 2},
                    ],
                    "consecutive_slots": 2,
                    "duration_weeks": 2,
                    "session_hours": 2,
                    "required_room_type": "普通教室",
                }],
            }],
        }
        task = {
            "source_key": "task:42",
            "teaching_task_id": 42,
            "course_id": 7,
            "primary_teacher_id": 11,
            "assistant_teacher_id": 12,
            "class_group_ids": [21, 22],
        }
        rooms = [{
            "id": 31,
            "name": "A101",
            "classroom_type": "普通教室",
            "capacity": 100,
            "status": "ACTIVE",
        }]

        with TemporaryDirectory() as directory:
            root = Path(directory)
            cover_path = root / "cover.json"
            tasks_path = root / "tasks.jsonl"
            rooms_path = root / "rooms.json"
            output_dir = root / "draft"
            cover_path.write_text(json.dumps(cover, ensure_ascii=False), encoding="utf-8")
            _write_jsonl(tasks_path, [task])
            rooms_path.write_text(json.dumps(rooms, ensure_ascii=False), encoding="utf-8")

            report = export_db_draft(
                cover_path=cover_path,
                output_dir=output_dir,
                allocation_task_id=9,
                total_weeks=2,
                task_source_path=tasks_path,
                rooms_path=rooms_path,
            )
            validation = validate_export(input_dir=output_dir, report_path=output_dir / "validation.json")
            fragment = _read_jsonl(output_dir / "schedule_template_fragments.jsonl")[0]
            teachers = _read_jsonl(output_dir / "schedule_template_fragment_teachers.jsonl")
            classes = _read_jsonl(output_dir / "schedule_template_fragment_class_groups.jsonl")
            week = query_week(input_dir=output_dir, week_number=1, output_path=None)

        self.assertEqual(report["identity_resolution"]["issue_count"], 0)
        self.assertEqual(validation["issue_count"], 0, validation["issues_preview"])
        self.assertEqual(fragment["course_id"], 7)
        self.assertEqual(fragment["teacher_id"], 11)
        self.assertIsNone(fragment["class_group_id"])
        self.assertEqual(fragment["classroom_id"], 31)
        self.assertEqual({row["teacher_id"] for row in teachers}, {11, 12})
        self.assertEqual({row["class_group_id"] for row in classes}, {21, 22})
        self.assertEqual(week["entries"][0]["teacher_ids"], [11, 12])
        self.assertEqual(week["entries"][0]["class_group_ids"], [21, 22])

    def test_dynamic_cover_never_falls_back_when_explicit_week_mapping_is_invalid(self) -> None:
        cover = {
            "cover_id": "dynamic_cover_v2",
            "templates": [{
                "template_id": "bad-dynamic",
                "week_numbers": [1, 1],
                "week_budget": 2,
                "fragments": [],
            }],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cover_path = root / "cover.json"
            cover_path.write_text(json.dumps(cover), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "map every semester week exactly once"):
                export_db_draft(
                    cover_path=cover_path,
                    output_dir=root / "draft",
                    total_weeks=2,
                )

    def test_ten_period_teacher_availability_is_preserved(self) -> None:
        matrix = [[0] * 7 for _ in range(10)]
        matrix[9][6] = -1
        raw = json.dumps(matrix)

        repository_slots = _parse_availability_matrix_unavailable(raw)
        task_slots = _parse_unavailable_matrix(77, raw)

        self.assertIn((7, 10), repository_slots)
        self.assertEqual(task_slots, [{
            "teacher_id": 77,
            "week_number": None,
            "day_of_week": 7,
            "period_index": 10,
        }])

    def test_legacy_five_block_availability_expands_to_atomic_period_pairs(self) -> None:
        matrix = [[0] * 7 for _ in range(5)]
        matrix[2][3] = -1
        raw = json.dumps(matrix)

        repository_slots = _parse_availability_matrix_unavailable(raw)
        task_slots = _parse_unavailable_matrix(77, raw)

        self.assertIn((4, 5), repository_slots)
        self.assertIn((4, 6), repository_slots)
        self.assertEqual(
            {(slot["day_of_week"], slot["period_index"]) for slot in task_slots},
            {(4, 5), (4, 6)},
        )

    def test_explicit_unschedulable_note_is_detected_instead_of_silently_filtered(self) -> None:
        self.assertTrue(_is_explicitly_excluded(" unschedulable: 校外实践 "))
        self.assertFalse(_is_explicitly_excluded("需要人工关注，但仍参与排课"))

    def test_inactive_fixed_resources_are_explicit_hard_issues(self) -> None:
        task = {
            "teaching_task_id": 42,
            "course_id": 7,
            "primary_teacher_id": 11,
            "assistant_teacher_id": 12,
            "class_group_ids": [21],
            "fixed_classroom_id": 31,
            "required_room_type": "机房",
        }
        row = {
            "course_status": "ACTIVE",
            "primary_teacher_status": "ACTIVE",
            "assistant_teacher_status": "INACTIVE",
            "fixed_classroom_status": "INACTIVE",
            "fixed_classroom_type": "普通教室",
            "candidate_classroom_link_count": 2,
            "active_candidate_classroom_count": 1,
        }

        hard, warnings = _resource_issues(row, task)

        self.assertEqual({issue["issue"] for issue in hard}, {
            "inactive_assistant_teacher",
            "inactive_fixed_classroom",
            "fixed_classroom_type_mismatch",
        })
        self.assertEqual(warnings[0]["issue"], "inactive_candidate_classrooms_ignored")

    def test_unplaced_and_hour_delta_require_review_without_becoming_hard_blockers(self) -> None:
        gate = _publication_gate(
            allocation_report={"task_count": 3, "bound_task_count": 3, "excluded_task_count": 0, "hard_issue_count": 0},
            pattern_report={"raw_pattern_count": 3, "dropped_count": 0, "warning_count": 1},
            pattern_validation={"invalid_count": 0},
            constraint_enrichment={"missing_source_count": 0},
            cover_report={
                "remaining_task_count": 1,
                "conservation_mismatch": 1,
                "capacity_mismatch_count": 0,
                "conflicts": {"dynamic": {"teacher": 0, "class": 0, "room": 0}},
            },
            db_draft_validation={"issue_count": 0},
        )

        self.assertEqual(gate["status"], "NEEDS_MANUAL_REVIEW")
        self.assertEqual(gate["hard_blockers"], [])
        self.assertFalse(gate["can_publish"])
        self.assertTrue(gate["can_import_candidate"])
        self.assertIn("irregular task patterns=1", gate["manual_reviews"])

    def test_dropped_pattern_and_resource_reference_are_hard_blockers(self) -> None:
        gate = _publication_gate(
            allocation_report={"task_count": 3, "bound_task_count": 3, "excluded_task_count": 0, "hard_issue_count": 1},
            pattern_report={"raw_pattern_count": 3, "dropped_count": 1},
            pattern_validation={"invalid_count": 0},
            constraint_enrichment={"missing_source_count": 0},
            cover_report={
                "remaining_task_count": 0,
                "conservation_mismatch": 0,
                "capacity_mismatch_count": 0,
                "conflicts": {"dynamic": {"teacher": 0, "class": 0, "room": 0}},
            },
            db_draft_validation={"issue_count": 0},
        )

        self.assertEqual(gate["status"], "BLOCKED")
        self.assertEqual(gate["hard_blocker_count"], 2)

    def test_incomplete_scheme_cannot_be_marked_valid_for_confirmation(self) -> None:
        manual = _scheme_review_state({
            "conflicts": {"dynamic": {"teacher": 0, "class": 0, "room": 0}},
            "remaining_task_count": 2,
            "conservation_mismatch": 2,
            "capacity_mismatch_count": 0,
        })
        blocked = _scheme_review_state({
            "conflicts": {"dynamic": {"teacher": 0, "class": 0, "room": 1}},
            "remaining_task_count": 0,
            "conservation_mismatch": 0,
            "capacity_mismatch_count": 0,
        })

        self.assertEqual(manual["review_status"], "NEEDS_MANUAL_REVIEW")
        self.assertTrue(manual["needs_manual_review"])
        self.assertEqual(blocked["review_status"], "BLOCKED")
        self.assertTrue(blocked["hard_blocked"])

    def test_overall_hour_audit_includes_explicitly_excluded_tasks(self) -> None:
        with TemporaryDirectory() as directory:
            excluded_path = Path(directory) / "excluded.jsonl"
            _write_jsonl(excluded_path, [{
                "source_key": "task:9",
                "teaching_task_id": 9,
                "course_name": "校外实践",
                "total_hours": 16,
                "exclusion_reason": "explicit_unschedulable_note",
            }])
            audit = _overall_hour_audit(
                cover_report={
                    "required_total_hours": 32,
                    "scheduled_total_hours": 30,
                    "hour_over_task_count": 0,
                    "hour_under_task_count": 1,
                },
                excluded_tasks_path=excluded_path,
            )

        self.assertEqual(audit["overall_bound_required_hours"], 48)
        self.assertEqual(audit["overall_scheduled_hours"], 30)
        self.assertEqual(audit["overall_delta_hours"], -18)
        self.assertEqual(audit["overall_under_task_count"], 2)
        self.assertEqual(audit["excluded_task_audit"][0]["scheduled_hours"], 0)

    def test_dirty_generation_config_is_rejected_before_scheduling(self) -> None:
        _validate_allowed_config(
            allowed_weeks=frozenset(range(1, 19)),
            allowed_weekdays=frozenset(range(1, 6)),
            allowed_periods=frozenset(range(1, 9)),
            total_weeks=18,
        )
        with self.assertRaisesRegex(ValueError, "allowed_weeks contains"):
            _validate_allowed_config(
                allowed_weeks=frozenset({1, 19}),
                allowed_weekdays=frozenset(range(1, 6)),
                allowed_periods=frozenset(range(1, 9)),
                total_weeks=18,
            )
        with self.assertRaisesRegex(ValueError, "allowed_periods must not be empty"):
            _validate_allowed_config(
                allowed_weeks=frozenset(range(1, 19)),
                allowed_weekdays=frozenset(range(1, 6)),
                allowed_periods=frozenset(),
                total_weeks=18,
            )


if __name__ == "__main__":
    unittest.main()
