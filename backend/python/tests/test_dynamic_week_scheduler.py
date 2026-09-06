from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scheduler.export_template_cover_db_draft import export_db_draft
from scheduler.phase_scheduler import (
    ALL_DAY_PERIODS,
    DEFAULT_ALLOWED_PERIODS,
    EVENING_PERIODS,
    DynamicSemesterSchedule,
    _dynamic_template_docs,
    _valid_starts,
    audit_dynamic_schedule,
    build_phase_cover,
    final_hour_audit,
    place_dynamic,
)
from scheduler.pattern_builder import _consecutive_slots, build_patterns
from scheduler.query_db_draft_timetable import query_week
from scheduler.validate_db_draft_export import validate_export


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _pattern(
    uid: str,
    *,
    duration_weeks: int,
    weekly_sessions: int = 1,
    consecutive_slots: int = 2,
    total_hours: int | None = None,
) -> dict:
    session_hours = consecutive_slots
    return {
        "uid": uid,
        "source_key": uid,
        "course_name": uid,
        "course_code": uid,
        "teacher_name": "同一教师",
        "classes": ["同一班级"],
        "class_names": "同一班级",
        "required_room_type": "普通教室",
        "student_count": 30,
        "weekly_slot_count": weekly_sessions,
        "duration_weeks": duration_weeks,
        "consecutive_slots": consecutive_slots,
        "session_hours": session_hours,
        "weekly_load": weekly_sessions * consecutive_slots,
        "total_hours": total_hours if total_hours is not None else weekly_sessions * duration_weeks * session_hours,
        "week_mask": list(range(1, duration_weeks + 1)),
        "week_mask_is_fixed": False,
    }


class DynamicWeekSchedulerTest(unittest.TestCase):
    def test_time_axis_is_four_plus_four_plus_two(self) -> None:
        self.assertEqual(sorted(ALL_DAY_PERIODS), list(range(1, 12)))
        self.assertEqual(sorted(DEFAULT_ALLOWED_PERIODS), list(range(1, 9)))
        self.assertEqual(sorted(EVENING_PERIODS), [9, 10])
        # 第11节没有第12节可接，所以它不是2节连堂的合法起点；
        # 晚间三节大块里，2节课落在9-10，第11节只能单独补1节。
        self.assertEqual(_valid_starts(2, list(range(1, 12))), [1, 3, 5, 7, 9])
        self.assertIn(11, _valid_starts(1, list(range(1, 12))))
        self.assertEqual(_valid_starts(4, list(range(1, 12))), [1, 5])
        self.assertEqual(_consecutive_slots("实验课", "普通教室"), 4)
        self.assertEqual(_consecutive_slots("实践课", ""), 2)

    def test_automatic_placement_never_uses_reserved_evening_periods(self) -> None:
        patterns = [
            _pattern("theory", duration_weeks=4, consecutive_slots=2),
            {**_pattern("lab", duration_weeks=4, consecutive_slots=4),
             "teacher_name": "实验教师", "classes": ["实验班"],
             "class_names": "实验班", "required_room_type": "机房"},
        ]
        schedule = DynamicSemesterSchedule(total_weeks=4)
        unplaced, _ = place_dynamic(
            patterns,
            schedule,
            rooms_by_type={"普通教室": ["A101"], "机房": ["Lab201"]},
            model_candidates={},
            allowed_days=[1, 2, 3, 4, 5],
            allowed_periods=sorted(DEFAULT_ALLOWED_PERIODS),
            room_capacity_by_name={"A101": 60, "Lab201": 48},
        )

        self.assertEqual(unplaced, [])
        self.assertTrue(schedule.fragments)
        self.assertTrue(all(
            fragment["start"] + fragment["consecutive"] - 1 <= 8
            for fragment in schedule.fragments
        ))

    def test_short_courses_reuse_the_same_slot_after_hours_are_met(self) -> None:
        patterns = [
            _pattern("short-a", duration_weeks=2),
            _pattern("short-b", duration_weeks=2),
        ]
        schedule = DynamicSemesterSchedule(total_weeks=4)
        unplaced, assignments = place_dynamic(
            patterns,
            schedule,
            rooms_by_type={"普通教室": ["A101"]},
            model_candidates={},
            allowed_days=[1],
            allowed_periods=[1, 2],
            room_capacity_by_name={"A101": 60},
        )

        self.assertEqual(unplaced, [])
        self.assertEqual(assignments["short-a"], (1, 2))
        self.assertEqual(assignments["short-b"], (3, 4))
        self.assertEqual(
            {(fragment["day"], fragment["start"], fragment["room"])
             for fragment in schedule.fragments},
            {(1, 1, "A101")},
        )
        self.assertEqual(audit_dynamic_schedule(schedule), {"teacher": 0, "class": 0, "room": 0})

        templates = _dynamic_template_docs(schedule)
        self.assertEqual([template["week_numbers"] for template in templates], [[1, 2], [3, 4]])
        self.assertEqual({template["fragments"][0]["source_key"] for template in templates}, {"short-a", "short-b"})

    def test_final_hour_audit_reports_task_and_global_over_under(self) -> None:
        placed = _pattern("placed-under", duration_weeks=2, total_hours=6)
        unplaced = _pattern("unplaced-under", duration_weeks=2, total_hours=4)
        schedule = DynamicSemesterSchedule(total_weeks=2)
        schedule.occupy(placed, (1, 2), 1, 1, "A101", candidate_rank=0, score=0.0)

        audit = final_hour_audit([placed, unplaced], schedule)

        self.assertEqual(audit["required_total_hours"], 10)
        self.assertEqual(audit["scheduled_total_hours"], 4)
        self.assertEqual(audit["delta_total_hours"], -6)
        self.assertEqual(audit["mismatch_count"], 2)
        by_uid = {row["uid"]: row for row in audit["tasks"]}
        self.assertEqual(by_uid["placed-under"]["delta_hours"], -2)
        self.assertEqual(by_uid["unplaced-under"]["delta_hours"], -4)
        self.assertFalse(by_uid["unplaced-under"]["placed"])

    def test_logical_fragment_ids_stay_stable_across_rebuilt_templates(self) -> None:
        long_task = _pattern("long", duration_weeks=4, weekly_sessions=2)
        short_task = {
            **_pattern("short", duration_weeks=2),
            "teacher_name": "另一教师",
            "classes": ["另一班级"],
            "class_names": "另一班级",
        }
        schedule = DynamicSemesterSchedule(total_weeks=4)
        unplaced, _ = place_dynamic(
            [long_task, short_task],
            schedule,
            rooms_by_type={"普通教室": ["A101", "A102"]},
            model_candidates={},
            allowed_days=[1, 2],
            allowed_periods=[1, 2, 3, 4],
            room_capacity_by_name={"A101": 60, "A102": 60},
        )
        self.assertEqual(unplaced, [])

        templates = _dynamic_template_docs(schedule)
        long_docs = [
            fragment
            for template in templates
            for fragment in template["fragments"]
            if fragment["source_key"] == "long"
        ]
        ids = {fragment["logical_fragment_id"] for fragment in long_docs}
        self.assertEqual(ids, {"long#session1", "long#session2"})
        self.assertEqual(sum(fragment["covered_hours"] for fragment in long_docs), 16)
        self.assertTrue(all(fragment["week_mask"] == [1, 2, 3, 4] for fragment in long_docs))
        self.assertTrue(all(
            fragment["duration_weeks"] == len(fragment["template_week_mask"])
            for fragment in long_docs
        ))

    def test_local_repair_moves_a_real_room_blocker(self) -> None:
        long_first = _pattern("long-first", duration_weeks=18)
        short_fixed = {
            **_pattern("short-fixed", duration_weeks=4, consecutive_slots=4),
            "teacher_name": "另一教师",
            "classes": ["另一班级"],
            "class_names": "另一班级",
            "fixed_classroom_name": "A101",
        }
        schedule = DynamicSemesterSchedule(total_weeks=18)
        unplaced, assignments = place_dynamic(
            [long_first, short_fixed],
            schedule,
            rooms_by_type={"普通教室": ["A101", "A102"]},
            model_candidates={},
            allowed_days=[1],
            allowed_periods=[1, 2, 3, 4],
            room_capacity_by_name={"A101": 60, "A102": 60},
        )

        self.assertEqual(unplaced, [])
        self.assertEqual(schedule.repair_count, 1)
        self.assertEqual(assignments["short-fixed"], (1, 2, 3, 4))
        room_by_uid = {fragment["uid"]: fragment["room"] for fragment in schedule.fragments}
        self.assertEqual(room_by_uid["short-fixed"], "A101")
        self.assertEqual(room_by_uid["long-first"], "A102")
        self.assertEqual(audit_dynamic_schedule(schedule), {"teacher": 0, "class": 0, "room": 0})

    def test_week_bitset_indexes_preserve_disjoint_reuse_after_removal(self) -> None:
        first = _pattern("first", duration_weeks=2)
        second = _pattern("second", duration_weeks=2)
        schedule = DynamicSemesterSchedule(total_weeks=4)
        first_fragment = schedule.occupy(
            first, (1, 2), 1, 1, "A101", candidate_rank=0, score=0.0,
        )

        self.assertTrue(schedule.free(second, (3, 4), 1, 1, "A101", {"A101": 60}))
        second_fragment = schedule.occupy(
            second, (3, 4), 1, 1, "A101", candidate_rank=0, score=0.0,
        )
        self.assertFalse(schedule.free(first, (1, 2), 1, 1, "A101", {"A101": 60}))

        schedule.remove_fragment(first_fragment)
        self.assertTrue(schedule.free(first, (1, 2), 1, 1, "A101", {"A101": 60}))
        self.assertFalse(schedule.free(first, (3, 4), 1, 1, "A101", {"A101": 60}))
        schedule.remove_fragment(second_fragment)
        self.assertEqual(schedule.fragments, [])

    def test_room_scan_checks_common_constraints_once_per_time_block(self) -> None:
        schedule = DynamicSemesterSchedule(total_weeks=18)
        room_names = [f"A{index:03d}" for index in range(50)]
        for index, room in enumerate(room_names[:-1]):
            blocker = {
                **_pattern(f"blocker-{index}", duration_weeks=18),
                "teacher_name": f"教师-{index}",
                "classes": [f"班级-{index}"],
                "class_names": f"班级-{index}",
            }
            schedule.occupy(
                blocker, tuple(range(1, 19)), 1, 1, room,
                candidate_rank=0, score=0.0,
            )

        base_check_count = 0
        original_base_free = schedule.base_free

        def counted_base_free(pattern, weeks, day, start):
            nonlocal base_check_count
            base_check_count += 1
            return original_base_free(pattern, weeks, day, start)

        schedule.base_free = counted_base_free  # type: ignore[method-assign]
        pending = {
            **_pattern("pending", duration_weeks=18),
            "teacher_name": "待排教师",
            "classes": ["待排班级"],
            "class_names": "待排班级",
        }
        unplaced, _ = place_dynamic(
            [pending],
            schedule,
            rooms_by_type={"普通教室": room_names},
            model_candidates={},
            allowed_days=[1],
            allowed_periods=[1, 2],
            room_capacity_by_name={room: 60 for room in room_names},
        )

        self.assertEqual(unplaced, [])
        self.assertEqual(base_check_count, 1)
        self.assertEqual(schedule.task_fragments("pending")[0]["room"], room_names[-1])

    def test_export_and_query_follow_explicit_dynamic_week_mapping(self) -> None:
        patterns = [_pattern("short-a", duration_weeks=2), _pattern("short-b", duration_weeks=2)]
        schedule = DynamicSemesterSchedule(total_weeks=4)
        unplaced, _ = place_dynamic(
            patterns,
            schedule,
            rooms_by_type={"普通教室": ["A101"]},
            model_candidates={},
            allowed_days=[1],
            allowed_periods=[1, 2],
            room_capacity_by_name={"A101": 60},
        )
        self.assertEqual(unplaced, [])

        with TemporaryDirectory() as directory:
            root = Path(directory)
            cover_path = root / "cover.json"
            draft_dir = root / "draft"
            cover_path.write_text(json.dumps({
                "cover_id": "dynamic_cover_v2",
                "total_weeks": 4,
                "templates": _dynamic_template_docs(schedule),
            }, ensure_ascii=False), encoding="utf-8")
            report = export_db_draft(
                cover_path=cover_path,
                output_dir=draft_dir,
                total_weeks=4,
            )
            week_one = query_week(input_dir=draft_dir, week_number=1, output_path=None)
            week_three = query_week(input_dir=draft_dir, week_number=3, output_path=None)

        self.assertEqual(report["counts"]["template_weeks"], 4)
        self.assertEqual({entry["source_key"] for entry in week_one["entries"]}, {"short-a"})
        self.assertEqual({entry["source_key"] for entry in week_three["entries"]}, {"short-b"})

    def test_long_course_exports_each_dynamic_template_with_its_local_weeks(self) -> None:
        long_task = _pattern("long", duration_weeks=4)
        short_task = {
            **_pattern("short", duration_weeks=2),
            "teacher_name": "另一教师",
            "classes": ["另一班级"],
            "class_names": "另一班级",
        }
        schedule = DynamicSemesterSchedule(total_weeks=4)
        unplaced, _ = place_dynamic(
            [long_task, short_task],
            schedule,
            rooms_by_type={"普通教室": ["A101", "A102"]},
            model_candidates={},
            allowed_days=[1, 2],
            allowed_periods=[1, 2, 3, 4],
            room_capacity_by_name={"A101": 60, "A102": 60},
        )
        self.assertEqual(unplaced, [])

        templates = _dynamic_template_docs(schedule)
        self.assertEqual([template["week_numbers"] for template in templates], [[1, 2], [3, 4]])
        self.assertEqual(
            [fragment["template_week_mask"]
             for template in templates
             for fragment in template["fragments"]
             if fragment["source_key"] == "long"],
            [[1, 2], [3, 4]],
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            cover_path = root / "cover.json"
            draft_dir = root / "draft"
            cover_path.write_text(json.dumps({
                "cover_id": "dynamic_cover_v2",
                "total_weeks": 4,
                "templates": templates,
            }, ensure_ascii=False), encoding="utf-8")
            report = export_db_draft(
                cover_path=cover_path,
                output_dir=draft_dir,
                total_weeks=4,
            )
            validation = validate_export(
                input_dir=draft_dir,
                report_path=draft_dir / "validation.json",
            )
            week_one = query_week(input_dir=draft_dir, week_number=1, output_path=None)
            week_three = query_week(input_dir=draft_dir, week_number=3, output_path=None)
            fragment_by_id = {
                row["id"]: row
                for row in _read_jsonl(draft_dir / "schedule_template_fragments.jsonl")
            }
            fragment_weeks = _read_jsonl(
                draft_dir / "schedule_template_fragment_weeks.jsonl"
            )

        long_weeks_by_fragment = {
            fragment_id: sorted(
                row["week_number"]
                for row in fragment_weeks
                if row["template_fragment_id"] == fragment_id
            )
            for fragment_id, fragment in fragment_by_id.items()
            if fragment["source_key"] == "long"
        }
        self.assertEqual(report["counts"]["templates"], 2)
        self.assertEqual(report["counts"]["template_fragment_weeks"], 6)
        self.assertEqual(validation["issue_count"], 0, validation["issues_preview"])
        self.assertEqual(sorted(long_weeks_by_fragment.values()), [[1, 2], [3, 4]])
        self.assertEqual({entry["source_key"] for entry in week_one["entries"]}, {"long", "short"})
        self.assertEqual({entry["source_key"] for entry in week_three["entries"]}, {"long"})

    def test_fragment_week_mask_falls_back_for_legacy_cover_and_stays_fail_closed(self) -> None:
        fragment = {
            "fragment_id": "legacy#session1",
            "source_key": "legacy",
            "course_name": "legacy",
            "day_of_week": 1,
            "period_index": 1,
            "segments": [
                {"day_of_week": 1, "period_index": 1},
                {"day_of_week": 1, "period_index": 2},
            ],
            "consecutive_slots": 2,
            "duration_weeks": 2,
            "session_hours": 2,
            "week_mask": [1, 2],
        }
        cover = {
            "cover_id": "dynamic_cover_v2",
            "templates": [{
                "template_id": "legacy-template",
                "week_numbers": [1, 2],
                "week_budget": 2,
                "fragments": [fragment],
            }],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cover_path = root / "cover.json"
            cover_path.write_text(json.dumps(cover), encoding="utf-8")
            report = export_db_draft(
                cover_path=cover_path,
                output_dir=root / "valid-draft",
                total_weeks=2,
            )
            self.assertEqual(report["counts"]["template_fragment_weeks"], 2)

            cover["templates"][0]["fragments"][0]["template_week_mask"] = [1, 3]
            cover_path.write_text(json.dumps(cover), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown=\\[3\\]"):
                export_db_draft(
                    cover_path=cover_path,
                    output_dir=root / "invalid-draft",
                    total_weeks=2,
                )

    def test_high_weekly_frequency_is_reviewed_but_never_dropped(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tasks.jsonl"
            patterns_path = root / "patterns.jsonl"
            dropped_path = root / "dropped.jsonl"
            rooms_path = root / "rooms.json"
            source.write_text(json.dumps({
                "source_key": "high-frequency",
                "course_name": "集中授课",
                "course_type": "理论课",
                "teacher_name": "集中教师",
                "class_names": "集中班",
                "required_room_type": "普通教室",
                "total_hours": 28,
                "sessions_per_week": 7,
                "duration_weeks": 2,
                "student_count": 30,
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            rooms_path.write_text(json.dumps([
                {"id": 1, "name": "A101", "classroom_type": "普通教室", "capacity": 60, "status": "ACTIVE"},
            ], ensure_ascii=False), encoding="utf-8")
            pattern_report = build_patterns(
                input_path=source,
                output_path=patterns_path,
                dropped_path=dropped_path,
                report_path=root / "pattern-report.json",
            )
            cover_report = build_phase_cover(
                patterns_path=patterns_path,
                output_path=root / "cover.json",
                report_path=root / "cover-report.json",
                unresolved_path=root / "unresolved.jsonl",
                rooms_path=rooms_path,
                use_model=False,
            )

        self.assertEqual(pattern_report["raw_pattern_count"], 1)
        self.assertEqual(pattern_report["pattern_count"], 1)
        self.assertEqual(pattern_report["dropped_count"], 0)
        self.assertEqual(pattern_report["warning_count"], 1)
        self.assertEqual(cover_report["raw_task_count"], 1)
        self.assertEqual(
            cover_report["raw_task_count"],
            cover_report["completed_task_count"] + cover_report["remaining_task_count"],
        )
        self.assertEqual(len(cover_report["hour_audit_tasks"]), 1)


if __name__ == "__main__":
    unittest.main()
