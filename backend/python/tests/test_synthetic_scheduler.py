from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scheduler.pattern_builder import build_patterns
from scheduler.generate_synthetic_data import GeneratorConfig, generate, resource_capacity_preflight
from scheduler.run_synthetic_pipeline import run
from scheduler.run_pipeline import _validation_errors
from scheduler.phase_scheduler import _merge_sections
from scheduler.synthetic_test_suite import run_all
from scheduler.validate_patterns import validate
from app.api.v1.simulation import (
    SimulationRequest,
    SimulationTimetableRequest,
    _preview,
    _query_timetable,
    _run,
    scan_boundary,
)


class SyntheticSchedulerTest(unittest.TestCase):
    def test_controlled_scheduler_scenarios(self) -> None:
        report = run_all()
        self.assertEqual(report["failed"], [], report)
        self.assertEqual(report["passed"], report["scenario_count"])

    def test_course_types_build_to_valid_patterns(self) -> None:
        source_rows = [
            {
                "source_key": "theory-32",
                "course_type": "理论课",
                "required_room_type": "普通教室",
                "total_hours": 32,
                "class_name": "C-A",
            },
            {
                "source_key": "lab-32",
                "course_type": "上机课",
                "required_room_type": "机房",
                "total_hours": 32,
                "class_name": "C-B",
            },
        ]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tasks.jsonl"
            patterns = root / "patterns.jsonl"
            source.write_text("\n".join(json.dumps(row) for row in source_rows) + "\n", encoding="utf-8")
            build_patterns(
                input_path=source,
                output_path=patterns,
                dropped_path=root / "dropped.jsonl",
                report_path=root / "pattern-report.json",
            )
            report = validate(input_path=patterns, report_path=root / "validation-report.json")

        self.assertEqual(report["invalid_count"], 0, report["invalid_preview"])

    def test_generator_creates_reproducible_task_and_resource_data(self) -> None:
        with TemporaryDirectory() as first_dir, TemporaryDirectory() as second_dir:
            config = GeneratorConfig(seed=7, courses=24, teachers=12, class_groups=10, classrooms=8, profile="lab-heavy")
            first = generate(config=config, output_dir=Path(first_dir))
            second = generate(config=config, output_dir=Path(second_dir))
            first_tasks = Path(first["paths"]["teaching_tasks"]).read_text(encoding="utf-8")
            second_tasks = Path(second["paths"]["teaching_tasks"]).read_text(encoding="utf-8")
            task_rows = [json.loads(line) for line in first_tasks.splitlines() if line.strip()]
            patterns = Path(first_dir) / "patterns.jsonl"
            build_patterns(
                input_path=Path(first["paths"]["teaching_tasks"]),
                output_path=patterns,
                dropped_path=Path(first_dir) / "dropped.jsonl",
                report_path=Path(first_dir) / "pattern-report.json",
            )
            validation = validate(input_path=patterns, report_path=Path(first_dir) / "validation-report.json")

        self.assertEqual(first_tasks, second_tasks)
        self.assertEqual(first["counts"]["courses"], 24)
        self.assertEqual(first["counts"]["teaching_tasks"], 24)
        self.assertGreater(first["counts"]["multi_class_tasks"], 0)
        self.assertEqual(
            first["counts"]["class_associations"],
            sum(len(task["class_group_ids"]) for task in task_rows),
        )
        self.assertTrue(all(len(task["class_group_ids"]) in {1, 2} for task in task_rows))
        self.assertTrue(all(not task["merge_group_id"] for task in task_rows))
        for task in (row for row in task_rows if len(row["class_group_ids"]) == 2):
            class_names = task["class_names"].split(",")
            cohorts = [re.sub(r"\d{2}班$", "", name) for name in class_names]
            self.assertEqual(cohorts[0], cohorts[1])
            self.assertGreater(task["student_count"], 0)
        self.assertGreater(first["counts"]["lab_courses"], 0)
        self.assertGreater(first["counts"]["lab_rooms"], 0)
        self.assertEqual(validation["invalid_count"], 0, validation["invalid_preview"])

    def test_same_seed_produces_identical_cover_across_processes(self) -> None:
        python_root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as first_dir, TemporaryDirectory() as second_dir:
            common_args = [
                sys.executable,
                "-m",
                "scheduler.run_synthetic_pipeline",
                "--seed",
                "7",
                "--courses",
                "24",
                "--teachers",
                "12",
                "--class-groups",
                "10",
                "--classrooms",
                "8",
            ]
            for output_dir in (first_dir, second_dir):
                subprocess.run(
                    [*common_args, "--output-dir", output_dir],
                    cwd=python_root,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            first_cover = (Path(first_dir) / "phase_cover.json").read_text(encoding="utf-8")
            second_cover = (Path(second_dir) / "phase_cover.json").read_text(encoding="utf-8")

        self.assertEqual(first_cover, second_cover)

    def test_database_free_pipeline_reports_complete_or_incomplete(self) -> None:
        with TemporaryDirectory() as complete_dir, TemporaryDirectory() as constrained_dir:
            complete = run(
                config=GeneratorConfig(courses=24, teachers=12, class_groups=10, classrooms=8),
                output_dir=Path(complete_dir),
            )
            constrained = run(
                config=GeneratorConfig(courses=24, teachers=12, class_groups=10, classrooms=2, profile="constrained"),
                output_dir=Path(constrained_dir),
            )

        self.assertEqual(complete["status"], "ok", complete)
        self.assertEqual(constrained["status"], "needs_manual_review", constrained)
        self.assertTrue(constrained["needs_manual_review"])
        self.assertEqual(constrained["hard_constraint_error_count"], 0)
        self.assertFalse(constrained["resource_capacity_preflight"]["feasible"])

    def test_default_scale_balanced_is_complete_across_seeds(self) -> None:
        for seed in (7, 23, 20260816):
            with self.subTest(seed=seed), TemporaryDirectory() as directory:
                report = run(
                    config=GeneratorConfig(seed=seed),
                    output_dir=Path(directory),
                )

            self.assertEqual(report["generated"]["teaching_tasks"], 1964)
            self.assertEqual(report["status"], "ok", report)
            self.assertTrue(report["resource_capacity_preflight"]["feasible"])
            self.assertEqual(report["schedule"]["completed"], 1964)
            self.assertEqual(report["schedule"]["remaining"], 0)
            self.assertEqual(report["schedule"]["hard_conflict_count"], 0)
            self.assertEqual(report["schedule"]["capacity_mismatch"], 0)
            self.assertEqual(report["schedule"]["hour_audit"]["mismatch_count"], 0)

    def test_capacity_preflight_detects_a_nested_large_room_shortage(self) -> None:
        rooms = [
            {"name": "A101", "classroom_type": "普通教室", "capacity": 60},
            {"name": "A102", "classroom_type": "普通教室", "capacity": 120},
        ]
        tasks = [
            {
                "source_key": f"T-{index}", "required_room_type": "普通教室",
                "student_count": 70, "total_hours": 40,
            }
            for index in range(19)
        ]

        report = resource_capacity_preflight(tasks, rooms)

        self.assertFalse(report["feasible"])
        large_tier = next(tier for tier in report["tiers"] if tier["minimum_capacity"] == 61)
        self.assertEqual(large_tier["room_count"], 1)
        self.assertEqual(large_tier["demand_hours"], 760)
        self.assertEqual(large_tier["supply_hours"], 720)
        self.assertFalse(large_tier["feasible"])

    def test_formal_mix_constraints_survive_pattern_and_placement(self) -> None:
        config = GeneratorConfig(
            seed=20260816, courses=240, teachers=80,
            class_groups=48, classrooms=48, profile="formal-mix",
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = run(config=config, output_dir=root)
            tasks = {
                row["source_key"]: row
                for row in (
                    json.loads(line)
                    for line in (root / "source" / "teaching_tasks.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            }
            patterns = {
                row["source_key"]: row
                for row in (
                    json.loads(line)
                    for line in (root / "task_patterns.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            }
            cover = json.loads((root / "phase_cover.json").read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "ok", report)
        for field in (
            "assistant_teacher_tasks", "teacher_unavailable_tasks", "allowed_weeks_tasks",
            "fixed_classroom_tasks", "candidate_classroom_tasks",
        ):
            self.assertGreater(report["generated"][field], 0, field)

        fragments_by_source: dict[str, list[tuple[list[int], dict]]] = {}
        for template in cover["templates"]:
            weeks = [int(week) for week in template["week_numbers"]]
            for fragment in template["fragments"]:
                fragments_by_source.setdefault(fragment["source_key"], []).append((weeks, fragment))

        for source_key, task in tasks.items():
            pattern = patterns[source_key]
            fragments = fragments_by_source[source_key]
            if task.get("assistant_teacher_id"):
                self.assertIn(task["assistant_teacher_id"], pattern["teacher_ids"])
                self.assertEqual(pattern["assistant_teacher_id"], task["assistant_teacher_id"])
            if task.get("allowed_weeks"):
                allowed = set(task["allowed_weeks"])
                self.assertTrue(all(set(weeks) <= allowed for weeks, _ in fragments))
            if task.get("fixed_classroom_name"):
                self.assertTrue(all(fragment["classroom_name"] == task["fixed_classroom_name"] for _, fragment in fragments))
            if task.get("candidate_classroom_names"):
                candidates = set(task["candidate_classroom_names"])
                self.assertTrue(all(fragment["classroom_name"] in candidates for _, fragment in fragments))
            for unavailable in task.get("teacher_unavailable_slots") or []:
                for weeks, fragment in fragments:
                    applies = not unavailable["week_number"] or unavailable["week_number"] in weeks
                    occupied_periods = {segment["period_index"] for segment in fragment["segments"]}
                    overlaps = (
                        applies
                        and fragment["day_of_week"] == unavailable["day_of_week"]
                        and unavailable["period_index"] in occupied_periods
                    )
                    self.assertFalse(overlaps, (source_key, unavailable, fragment))

    def test_preview_and_run_use_the_same_generated_dataset(self) -> None:
        request = SimulationRequest(
            seed=11,
            courses=24,
            teachers=12,
            class_groups=10,
            classrooms=8,
            profile="balanced",
        )

        with TemporaryDirectory() as simulation_dir, patch.dict(
            "os.environ", {"EDU_FLOW_SIMULATION_DIR": simulation_dir}
        ):
            preview = _preview(request)
            source_path = Path(simulation_dir) / preview["simulation_id"] / "source" / "teaching_tasks.jsonl"
            source_mtime = source_path.stat().st_mtime_ns
            result = _run(request)

            self.assertEqual(source_mtime, source_path.stat().st_mtime_ns)
            self.assertTrue((source_path.parents[1] / "phase_cover.json").exists())
            self.assertGreater(len(result["task_traces"]), 0)
            self.assertGreater(len(result["timetable_views"]), 0)

        self.assertEqual(preview["simulation_id"], result["simulation_id"])
        self.assertEqual(preview["input_hash"], result["dataset"]["input_hash"])
        self.assertEqual(preview["counts"], result["dataset"]["counts"])
        self.assertEqual(preview["counts"]["teaching_tasks"], result["engine"]["teaching_task_count"])
        self.assertEqual(result["engine"]["compatibility_merge_count"], 0)

    def test_timetable_query_combines_teacher_class_and_room_filters(self) -> None:
        request = SimulationRequest(seed=19, courses=24, teachers=12, class_groups=10, classrooms=8)
        with TemporaryDirectory() as simulation_dir, patch.dict(
            "os.environ", {"EDU_FLOW_SIMULATION_DIR": simulation_dir}
        ):
            result = _run(request)
            unfiltered = _query_timetable(SimulationTimetableRequest(
                simulation_id=result["simulation_id"], page_size=200,
            ))
            sample = unfiltered["entries"][0]
            filtered = _query_timetable(SimulationTimetableRequest(
                simulation_id=result["simulation_id"],
                template_id=sample["template_id"],
                teacher=sample["teacher"],
                class_name=sample["classes"][0],
                classroom=sample["classroom"],
                page_size=200,
            ))

        self.assertGreater(unfiltered["total"], 0)
        self.assertGreater(filtered["total"], 0)
        self.assertTrue(all(entry["teacher"] == sample["teacher"] for entry in filtered["entries"]))
        self.assertTrue(all(entry["template_id"] == sample["template_id"] for entry in filtered["entries"]))
        self.assertTrue(all(sample["classes"][0] in entry["classes"] for entry in filtered["entries"]))
        self.assertTrue(all(entry["classroom"] == sample["classroom"] for entry in filtered["entries"]))
        self.assertIn(sample["teacher"], unfiltered["filters"]["teachers"])
        self.assertIn(sample["template_id"], unfiltered["filters"]["templates"])
        self.assertTrue(all(entry["week_numbers"] for entry in unfiltered["entries"]))

    def test_dynamic_templates_partition_the_semester_with_explicit_weeks(self) -> None:
        request = SimulationRequest(seed=23, courses=36, teachers=16, class_groups=12, classrooms=10)
        with TemporaryDirectory() as simulation_dir, patch.dict(
            "os.environ", {"EDU_FLOW_SIMULATION_DIR": simulation_dir}
        ):
            result = _run(request)
            cover_path = Path(simulation_dir) / result["simulation_id"] / "phase_cover.json"
            cover = json.loads(cover_path.read_text(encoding="utf-8"))

        templates = cover["templates"]
        covered_weeks = [week for template in templates for week in template["week_numbers"]]
        self.assertEqual(sorted(covered_weeks), list(range(1, 19)))
        self.assertEqual(len(covered_weeks), len(set(covered_weeks)))
        self.assertTrue(all(template["template_id"].startswith("dynamic_template_") for template in templates))
        self.assertTrue(all("phase_t" not in template["template_id"] for template in templates))
        self.assertEqual(result["engine"]["template_count"], len(templates))

    def test_failure_analysis_preserves_scheduler_stage_and_guidance(self) -> None:
        request = SimulationRequest(
            seed=13, courses=80, teachers=12, class_groups=10,
            classrooms=4, profile="constrained",
        )
        with TemporaryDirectory() as simulation_dir, patch.dict(
            "os.environ", {"EDU_FLOW_SIMULATION_DIR": simulation_dir}
        ):
            result = _run(request)

        reasons = result["summary"]["schedule"]["unresolved_reason_counts"]
        self.assertNotIn("not_placed", reasons)
        self.assertTrue(result["failure_analysis"])
        self.assertTrue(all(item["suggestions"] for item in result["failure_analysis"]))
        self.assertEqual(result["summary"]["status"], "needs_manual_review")
        self.assertTrue(result["summary"]["needs_manual_review"])
        self.assertEqual(result["summary"]["hard_constraint_error_count"], 0)
        # Final hour audit includes every task. An unresolved task contributes
        # zero scheduled hours and is therefore also an explicit shortage.
        self.assertEqual(
            result["summary"]["schedule"]["conservation_mismatch"],
            result["summary"]["schedule"]["remaining"],
        )
        audit = result["summary"]["schedule"]["hour_audit"]
        self.assertEqual(len(audit["tasks"]), result["engine"]["placement_task_count"])
        self.assertEqual(audit["mismatch_count"], result["summary"]["schedule"]["remaining"])

    def test_resource_reduction_never_reduces_unresolved_count(self) -> None:
        request = SimulationRequest(
            seed=17, courses=80, teachers=12, class_groups=10,
            classrooms=12, profile="constrained",
        )
        with TemporaryDirectory() as simulation_dir, patch.dict(
            "os.environ", {"EDU_FLOW_SIMULATION_DIR": simulation_dir}
        ):
            result = scan_boundary(request)

        remaining = [row["remaining"] for row in result["rows"]]
        self.assertEqual(remaining, sorted(remaining))

    def test_publication_gate_rejects_unplaced_or_invalid_output(self) -> None:
        errors = _validation_errors(
            pattern_validation={"invalid_count": 0},
            cover_report={
                "remaining_task_count": 1,
                "conflicts": {"phase_t1": {"teacher": 0, "class": 1, "room": 0}},
                "conservation_mismatch": 1,
            },
            db_draft_validation={"issue_count": 2},
        )
        self.assertEqual(errors, [
            "unplaced tasks=1",
            "hard conflicts=1",
            "hour conservation mismatches=1",
            "db draft issues=2",
        ])

    def test_only_explicit_merge_groups_are_combined(self) -> None:
        base = {
            "teacher_name": "T-A", "course_code": "C-1", "course_name": "高等数学",
            "total_hours": 32, "course_type": "理论课", "required_room_type": "普通教室",
            "classes": [], "weekly_load": 4,
        }
        patterns = [
            {**base, "uid": "parallel-a", "classes": ["C-A"], "student_count": 40, "merge_group_id": ""},
            {**base, "uid": "parallel-b", "classes": ["C-B"], "student_count": 42, "merge_group_id": ""},
            {**base, "uid": "merged-a", "classes": ["C-C"], "student_count": 38, "merge_group_id": "M-1"},
            {**base, "uid": "merged-b", "classes": ["C-D"], "student_count": 39, "merge_group_id": "M-1"},
            {**base, "uid": "standalone-c", "classes": ["C-E"], "student_count": 41, "merge_group_id": ""},
        ]
        merged, log = _merge_sections(patterns, week_cap=40, t1_weeks=8)

        self.assertEqual(len(merged), 4)
        self.assertEqual({row["uid"] for row in merged if not row.get("merge_group_id")}, {"parallel-a", "parallel-b", "standalone-c"})
        merged_group = next(row for row in merged if row.get("merge_group_id") == "M-1")
        self.assertEqual(merged_group["classes"], ["C-C", "C-D"])
        self.assertEqual(merged_group["student_count"], 77)
        self.assertEqual(merged_group["merged_from"], 2)
        self.assertEqual(log[0]["sections_before"], 2)
