"""画像只排序候选、不改变可行域——这组断言是这条保证的看门人。"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scheduler.pattern_builder import build_patterns
from scheduler.phase_scheduler import (
    DynamicSemesterSchedule,
    audit_dynamic_schedule,
    build_phase_cover,
    final_hour_audit,
    place_dynamic,
)
from scheduler.teacher_preferences import (
    REPORT_COMPONENTS,
    PreferenceRanker,
    build_index,
    combine,
    normalize,
    satisfaction_report,
    slot_components,
)

ALLOWED_DAYS = [1, 2, 3, 4, 5]
ROOMS = {"普通教室": ["A101", "A102"], "机房": ["Lab201"]}
CAPACITY = {"A101": 60, "A102": 60, "Lab201": 48}


def _pattern(
    uid: str,
    *,
    duration_weeks: int = 4,
    weekly_sessions: int = 1,
    consecutive_slots: int = 2,
    teacher: str = "张老师",
    **extra,
) -> dict:
    session_hours = consecutive_slots
    pattern = {
        "uid": uid,
        "source_key": uid,
        "course_name": uid,
        "course_code": uid,
        "teacher_name": teacher,
        "classes": ["一班"],
        "class_names": "一班",
        "required_room_type": "普通教室",
        "student_count": 30,
        "weekly_slot_count": weekly_sessions,
        "duration_weeks": duration_weeks,
        "consecutive_slots": consecutive_slots,
        "session_hours": session_hours,
        "weekly_load": weekly_sessions * consecutive_slots,
        "total_hours": weekly_sessions * duration_weeks * session_hours,
        "week_mask": list(range(1, duration_weeks + 1)),
        "week_mask_is_fixed": False,
    }
    pattern.update(extra)
    return pattern


def _place(
    patterns: list[dict],
    *,
    preferences: dict | None = None,
    total_weeks: int = 4,
    allowed_periods: list[int] | None = None,
    allowed_days: list[int] | None = None,
    rooms_by_type: dict | None = None,
    capacity: dict | None = None,
):
    schedule = DynamicSemesterSchedule(total_weeks=total_weeks)
    unplaced, assignments = place_dynamic(
        patterns,
        schedule,
        rooms_by_type=rooms_by_type or ROOMS,
        model_candidates={},
        allowed_days=list(allowed_days or ALLOWED_DAYS),
        allowed_periods=list(allowed_periods or range(1, 9)),
        room_capacity_by_name=capacity or CAPACITY,
        teacher_preferences=preferences,
    )
    return schedule, unplaced, assignments


def _signature(schedule) -> list[tuple]:
    return [
        (fragment["uid"], fragment["day"], fragment["start"], fragment["room"])
        for fragment in schedule.fragments
    ]


def _ranker(preferences: dict) -> PreferenceRanker:
    return PreferenceRanker(build_index(preferences), {"A101": "普通教室", "Lab201": "机房"})


class NoPreferenceMeansNoChangeTest(unittest.TestCase):
    """没有画像 = 与接入前逐位相同。这条不成立的话，接入就是不可验证的。"""

    def test_missing_and_empty_preferences_give_the_identical_placement(self) -> None:
        patterns = [_pattern("a"), _pattern("b", teacher="李老师"), _pattern("lab", consecutive_slots=4)]
        without, unplaced_without, _ = _place(patterns)
        empty, unplaced_empty, _ = _place(patterns, preferences={})

        self.assertEqual(_signature(without), _signature(empty))
        self.assertEqual(unplaced_without, unplaced_empty)
        # 无画像时没有任何片段是被"排序过"的：candidate_rank 全为 0。
        self.assertTrue(without.fragments)
        self.assertEqual([fragment["candidate_rank"] for fragment in without.fragments], [0, 0, 0])

    def test_a_teacher_absent_from_the_payload_keeps_the_default_order(self) -> None:
        patterns = [_pattern("a")]
        baseline, _, _ = _place(patterns)
        other_teacher_only, _, _ = _place(
            patterns, preferences={"99": {"avoid_early_period": True}},
        )
        self.assertEqual(_signature(baseline), _signature(other_teacher_only))


class PreferenceChangesOrderOnlyTest(unittest.TestCase):
    def test_avoiding_early_periods_moves_the_class_to_a_later_start(self) -> None:
        patterns = [_pattern("a")]
        baseline, _, _ = _place(patterns, allowed_periods=[1, 2, 3, 4])
        profiled, _, _ = _place(
            patterns,
            allowed_periods=[1, 2, 3, 4],
            preferences={"张老师": {"avoid_early_period": True}},
        )

        self.assertEqual(_signature(baseline)[0][2], 1)
        self.assertEqual(_signature(profiled)[0][2], 3)

    def test_a_preferred_weekday_is_used_when_it_is_free(self) -> None:
        patterns = [_pattern("a")]
        profiled, _, _ = _place(
            patterns, preferences={"张老师": {"preferred_weekdays": [4]}},
        )
        self.assertEqual(_signature(profiled)[0][1], 4)

    def test_preferred_room_type_only_reorders_the_pool(self) -> None:
        patterns = [_pattern("a")]
        profiled, _, _ = _place(
            patterns, preferences={"张老师": {"preferred_room_types": ["普通教室"]}},
        )
        # 池里两间都是普通教室，偏好不该裁掉任何一间。
        self.assertEqual(sorted({fragment["room"] for fragment in profiled.fragments}), ["A101"])
        self.assertEqual(len(profiled.fragments), 1)

    def test_the_placed_fragment_carries_the_profile_rank_and_score(self) -> None:
        patterns = [_pattern("a")]
        profiled, _, _ = _place(
            patterns, preferences={"张老师": {"avoid_early_period": True}},
        )
        fragment = profiled.fragments[0]
        self.assertGreater(fragment["candidate_rank"], 0)
        self.assertGreater(fragment["score"], 0.0)

    def test_the_daily_cap_pushes_a_second_course_to_another_day(self) -> None:
        patterns = [_pattern("a"), _pattern("b")]
        baseline, _, _ = _place(patterns)
        profiled, _, _ = _place(
            patterns, preferences={"张老师": {"max_daily_lessons": 1}},
        )

        self.assertEqual([fragment["day"] for fragment in baseline.fragments], [1, 1])
        self.assertEqual([fragment["day"] for fragment in profiled.fragments], [1, 2])


class HardConstraintsStillWinTest(unittest.TestCase):
    def test_a_preferred_but_unavailable_day_is_not_used(self) -> None:
        blocked = [
            {"day_of_week": 1, "period_index": period, "week_number": 0}
            for period in range(1, 9)
        ]
        patterns = [_pattern("a", teacher_unavailable_slots=blocked)]
        profiled, unplaced, _ = _place(
            patterns, preferences={"张老师": {"preferred_weekdays": [1]}},
        )

        self.assertEqual(unplaced, [])
        self.assertNotEqual(profiled.fragments[0]["day"], 1)

    def test_the_only_feasible_slot_is_used_even_when_the_profile_dislikes_it(self) -> None:
        patterns = [_pattern("a", consecutive_slots=1)]
        profiled, unplaced, _ = _place(
            patterns,
            allowed_periods=[1],
            preferences={"张老师": {"avoid_early_period": True}},
        )

        self.assertEqual(unplaced, [])
        self.assertEqual(profiled.fragments[0]["start"], 1)
        self.assertTrue(profiled.fragments[0]["candidate_rank"] > 0)

    def test_conflicts_and_hour_conservation_are_identical_with_and_without_profiles(self) -> None:
        patterns = [
            _pattern("a"),
            _pattern("b"),
            _pattern("c", consecutive_slots=4, required_room_type="机房", teacher="李老师"),
            _pattern("d", duration_weeks=2, teacher="王老师"),
        ]
        aggressive = {
            "张老师": {
                "avoid_early_period": True, "avoid_late_period": True,
                "prefer_compact_schedule": True, "preferred_weekdays": [3, 4],
                "preferred_periods": [5, 7], "max_daily_lessons": 1,
                "preferred_room_types": ["普通教室"],
            },
            "李老师": {"avoid_early_period": True, "max_daily_lessons": 2},
        }
        baseline, unplaced_baseline, _ = _place(patterns)
        profiled, unplaced_profiled, _ = _place(patterns, preferences=aggressive)

        self.assertEqual(unplaced_baseline, [])
        self.assertEqual(unplaced_profiled, [])
        self.assertEqual(len(baseline.fragments), len(profiled.fragments))
        self.assertEqual(
            audit_dynamic_schedule(baseline), audit_dynamic_schedule(profiled),
        )
        self.assertEqual(
            final_hour_audit(patterns, baseline), final_hour_audit(patterns, profiled),
        )
        self.assertNotEqual(_signature(baseline), _signature(profiled))


class RankerTest(unittest.TestCase):
    def test_compactness_prefers_the_day_the_teacher_already_teaches(self) -> None:
        ranker = _ranker({"张老师": {"prefer_compact_schedule": True}})
        order = ranker.order_for(
            teacher_keys=["name:张老师"],
            allowed_days=ALLOWED_DAYS,
            starts=[1],
            consecutive=2,
            weeks=(1, 2),
            day_load=lambda teacher, week, day: 2 if day == 4 else 0,
            day_sessions=lambda teacher, week, day: 1 if day == 4 else 0,
            used_days={},
        )
        self.assertEqual(order[0][0], 4)

    def test_a_slot_is_only_good_if_it_suits_every_teacher_on_the_task(self) -> None:
        ranker = _ranker({
            "张老师": {"avoid_early_period": True},
            "李老师": {},
        })
        order = ranker.order_for(
            teacher_keys=["name:张老师", "name:李老师"],
            allowed_days=[1],
            starts=[1, 3],
            consecutive=2,
            weeks=(1,),
            day_load=lambda teacher, week, day: 0,
            day_sessions=lambda teacher, week, day: 0,
            used_days={},
        )
        self.assertEqual([item[1] for item in order], [3, 1])
        self.assertEqual(order[0][2], 1.0)

    def test_teachers_without_preferences_keep_the_engine_order(self) -> None:
        ranker = _ranker({"别人": {"avoid_early_period": True}})
        self.assertEqual(
            ranker.order_for(
                teacher_keys=["name:张老师"],
                allowed_days=ALLOWED_DAYS, starts=[1], consecutive=2, weeks=(1,),
                day_load=lambda teacher, week, day: 0,
                day_sessions=lambda teacher, week, day: 0,
                used_days={},
            ),
            [],
        )

    def test_room_preference_reorders_without_dropping_rooms(self) -> None:
        ranker = _ranker({"张老师": {"preferred_room_types": ["机房"]}})
        pool = ranker.room_pool_for(["name:张老师"], ["A101", "Lab201"])
        self.assertEqual(pool, ["Lab201", "A101"])

    def test_an_undeclared_dimension_does_not_dilute_the_score(self) -> None:
        quiet = slot_components(
            normalize({}),
            day=1, start=1, consecutive=2, mean_load_periods=0.0,
            sessions_today=0.0, compact_week_ratio=0.0,
        )
        self.assertEqual(quiet, {})
        self.assertEqual(combine(quiet), 1.0)


class PayloadRobustnessTest(unittest.TestCase):
    def test_numeric_keys_are_teacher_ids_and_text_keys_are_names(self) -> None:
        index = build_index({"12": {"avoid_early_period": True}, "张三": {"avoid_late_period": True}})
        self.assertIn("id:12", index)
        self.assertIn("name:张三", index)

    def test_unknown_keys_and_junk_values_are_ignored_not_fatal(self) -> None:
        index = build_index({
            "12": {"avoid_early_period": True, "something_new": "x"},
            "13": {"avoid_early_period": "是", "max_daily_lessons": "4"},
            "14": {"avoid_early_period": True, "max_daily_lessons": "not-a-number"},
            "15": "nonsense",
            "16": {},
        })
        self.assertEqual(index["id:12"]["avoid_early_period"], True)
        self.assertEqual(index["id:13"]["avoid_early_period"], True)
        self.assertEqual(index["id:13"]["max_daily_lessons"], 4)
        self.assertEqual(index["id:14"]["max_daily_lessons"], 0)
        self.assertNotIn("id:15", index)
        self.assertNotIn("id:16", index)

    def test_preference_lists_accept_both_arrays_and_comma_text(self) -> None:
        self.assertEqual(normalize({"preferred_weekdays": "2,4"} )["preferred_weekdays"], (2, 4))
        self.assertEqual(normalize({"preferred_weekdays": [2, 2, 4]})["preferred_weekdays"], (2, 4))


class SatisfactionReportTest(unittest.TestCase):
    def test_components_match_the_names_java_reports(self) -> None:
        report = satisfaction_report(
            index=build_index({"张老师": {"avoid_early_period": True}}),
            fragments=[{
                "teacher_keys": ["name:张老师"], "uid": "a",
                "day": 1, "start": 1, "consecutive": 2, "room": "A101", "week_mask": (1, 2),
            }],
            room_type_of={"A101": "普通教室"},
        )
        self.assertEqual(tuple(report["teachers"][0]["components"]), REPORT_COMPONENTS)

    def test_a_teacher_stuck_in_early_periods_is_reported_as_low_satisfaction(self) -> None:
        index = build_index({"张老师": {"avoid_early_period": True}})
        fragments = [
            {"teacher_keys": ["name:张老师"], "uid": f"t{index_}",
             "day": 1, "start": 1, "consecutive": 2, "room": "A101", "week_mask": (1,)}
            for index_ in range(4)
        ]
        report = satisfaction_report(index=index, fragments=fragments, room_type_of={"A101": "普通教室"})

        self.assertTrue(report["profile_applied"])
        self.assertEqual(report["teacher_count"], 1)
        self.assertEqual(report["low_satisfaction_count"], 1)
        self.assertEqual(report["low_satisfaction_teachers"][0]["preference_score"], 0.0)
        self.assertEqual(
            report["low_satisfaction_teachers"][0]["components"]["early_period"], 0.0,
        )
        # 六分量口径（与 Java 对齐）会把"只提了一个要求"的教师抬到 0.8333，
        # 所以低满意判定必须走 preference_score。
        self.assertEqual(report["teachers"][0]["satisfaction_score"], 0.8333)
        self.assertEqual(report["teachers"][0]["declared_dimensions"], ["early_period"])

    def test_no_profile_coverage_is_reported_instead_of_faked(self) -> None:
        report = satisfaction_report(index=build_index({}), fragments=[], room_type_of={})
        self.assertFalse(report["profile_applied"])
        self.assertEqual(report["teacher_count"], 0)


class PhaseCoverIntegrationTest(unittest.TestCase):
    def _build(self, root: Path, *, preferences: dict | None):
        root.mkdir(parents=True, exist_ok=True)
        source = root / "tasks.jsonl"
        patterns_path = root / "patterns.jsonl"
        rooms_path = root / "rooms.json"
        source.write_text(json.dumps({
            "source_key": "t1", "course_name": "操作系统", "course_type": "理论课",
            "teacher_name": "张老师", "class_names": "一班", "required_room_type": "普通教室",
            "total_hours": 8, "sessions_per_week": 1, "duration_weeks": 4, "student_count": 30,
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        rooms_path.write_text(json.dumps([
            {"id": 1, "name": "A101", "classroom_type": "普通教室", "capacity": 60, "status": "ACTIVE"},
        ], ensure_ascii=False), encoding="utf-8")
        build_patterns(
            input_path=source, output_path=patterns_path,
            dropped_path=root / "dropped.jsonl", report_path=root / "pattern-report.json",
        )
        return build_phase_cover(
            patterns_path=patterns_path,
            output_path=root / "cover.json",
            report_path=root / "cover-report.json",
            unresolved_path=root / "unresolved.jsonl",
            rooms_path=rooms_path,
            use_model=False,
            teacher_preferences=preferences,
        )

    def test_the_cover_report_says_whether_the_profile_was_used(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = self._build(root / "baseline", preferences=None)
            profiled = self._build(
                root / "profiled", preferences={"张老师": {"avoid_early_period": True}},
            )

        self.assertFalse(baseline["profile_satisfaction"]["profile_applied"])
        self.assertTrue(profiled["profile_satisfaction"]["profile_applied"])
        self.assertEqual(profiled["profile_satisfaction"]["covered_teacher_count"], 1)
        self.assertEqual(profiled["profile_satisfaction"]["covered_fragment_count"], 1)
        self.assertEqual(profiled["profile_satisfaction"]["ranked_fragment_count"], 1)
        # 课时守恒与硬冲突审计两边都必须干净。
        self.assertTrue(baseline["conservation_ok"])
        self.assertTrue(profiled["conservation_ok"])
        self.assertEqual(baseline["validation_issue_count"], 0)
        self.assertEqual(profiled["validation_issue_count"], 0)
        self.assertEqual(baseline["scheduled_total_hours"], profiled["scheduled_total_hours"])


if __name__ == "__main__":
    unittest.main()
