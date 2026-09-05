"""Deterministic, database-free scheduler scenarios.

Run with ``python -m scheduler.synthetic_test_suite``.  The scenarios use the
same absolute-week placement functions as production, while replacing
the database room lookup and placement model with explicit fixture data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from scheduler.phase_scheduler import (
    DynamicSemesterSchedule,
    audit_dynamic_schedule,
    final_hour_audit,
    place_dynamic,
)


PHASE_WEEKS = (8, 10)
ALLOWED_DAYS = (1, 2, 3, 4, 5)
ALLOWED_PERIODS = tuple(range(1, 9))


@dataclass(frozen=True)
class Scenario:
    name: str
    patterns: list[dict[str, Any]]
    rooms_by_type: dict[str, list[str]]
    room_capacity_by_name: dict[str, int] | None = None
    allowed_days: tuple[int, ...] = ALLOWED_DAYS
    allowed_periods: tuple[int, ...] = ALLOWED_PERIODS
    expect_complete: bool = True
    expected_unresolved_reason: str | None = None
    expected_room: str | None = None


def _pattern(
    uid: str,
    *,
    teacher: str,
    class_name: str,
    room_type: str,
    weekly_sessions: int,
    duration_weeks: int,
    consecutive_slots: int,
    student_count: int = 0,
) -> dict[str, Any]:
    return {
        "uid": uid,
        "source_key": uid,
        "course_name": uid,
        "teacher_name": teacher,
        "classes": [class_name],
        "required_room_type": room_type,
        "weekly_slot_count": weekly_sessions,
        "duration_weeks": duration_weeks,
        "consecutive_slots": consecutive_slots,
        "session_hours": consecutive_slots,
        "weekly_load": weekly_sessions * consecutive_slots,
        "student_count": student_count,
    }


def scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="feasible_mixed_course_types",
            rooms_by_type={"普通教室": ["A101", "A102"], "机房": ["Lab201"]},
            patterns=[
                _pattern("theory-16", teacher="T-A", class_name="C-A", room_type="普通教室", weekly_sessions=1, duration_weeks=8, consecutive_slots=2),
                _pattern("theory-32", teacher="T-A", class_name="C-B", room_type="普通教室", weekly_sessions=2, duration_weeks=8, consecutive_slots=2),
                _pattern("lab-16", teacher="T-B", class_name="C-C", room_type="机房", weekly_sessions=1, duration_weeks=4, consecutive_slots=4),
            ],
        ),
        Scenario(
            name="missing_required_room_type",
            rooms_by_type={"普通教室": ["A101"]},
            patterns=[
                _pattern("lab-without-lab", teacher="T-A", class_name="C-A", room_type="机房", weekly_sessions=1, duration_weeks=4, consecutive_slots=4),
            ],
            expect_complete=False,
            expected_unresolved_reason="required_room_type_unavailable",
        ),
        Scenario(
            name="insufficient_time_capacity",
            rooms_by_type={"普通教室": ["A101"]},
            allowed_days=(1,),
            allowed_periods=(1, 2, 3, 4),
            patterns=[
                _pattern("three_sessions_in_two_blocks", teacher="T-A", class_name="C-A", room_type="普通教室", weekly_sessions=3, duration_weeks=4, consecutive_slots=2),
            ],
            expect_complete=False,
            expected_unresolved_reason="automatic_search_exhausted",
        ),
        Scenario(
            name="single_room_capacity_exhausted",
            rooms_by_type={"普通教室": ["A101"]},
            allowed_days=(1,),
            allowed_periods=(1, 2, 3, 4),
            patterns=[
                _pattern("room-a", teacher="T-A", class_name="C-A", room_type="普通教室", weekly_sessions=2, duration_weeks=18, consecutive_slots=2),
                _pattern("room-b", teacher="T-B", class_name="C-B", room_type="普通教室", weekly_sessions=2, duration_weeks=18, consecutive_slots=2),
            ],
            expect_complete=False,
            expected_unresolved_reason="automatic_search_exhausted",
        ),
        Scenario(
            name="single_room_exact_capacity",
            rooms_by_type={"普通教室": ["A101"]},
            allowed_days=(1,),
            allowed_periods=(1, 2, 3, 4),
            patterns=[
                _pattern("room-exact", teacher="T-A", class_name="C-A", room_type="普通教室", weekly_sessions=2, duration_weeks=9, consecutive_slots=2),
            ],
        ),
        Scenario(
            name="teacher_daily_cap_exhausted",
            rooms_by_type={"普通教室": ["A101", "A102"]},
            allowed_days=(1,),
            allowed_periods=ALLOWED_PERIODS,
            patterns=[
                _pattern("teacher-load-a", teacher="T-A", class_name="C-A", room_type="普通教室", weekly_sessions=1, duration_weeks=18, consecutive_slots=4),
                _pattern("teacher-load-b", teacher="T-A", class_name="C-B", room_type="普通教室", weekly_sessions=1, duration_weeks=18, consecutive_slots=4),
            ],
            expect_complete=False,
            expected_unresolved_reason="automatic_search_exhausted",
        ),
        Scenario(
            name="teacher_daily_cap_exactly_six",
            rooms_by_type={"普通教室": ["A101", "A102"], "机房": ["Lab201"]},
            allowed_days=(1,),
            allowed_periods=ALLOWED_PERIODS,
            patterns=[
                _pattern("teacher-four-slots", teacher="T-A", class_name="C-A", room_type="机房", weekly_sessions=1, duration_weeks=9, consecutive_slots=4),
                _pattern("teacher-two-slots", teacher="T-A", class_name="C-B", room_type="普通教室", weekly_sessions=1, duration_weeks=9, consecutive_slots=2),
            ],
        ),
        Scenario(
            name="same_class_over_phase_capacity",
            rooms_by_type={"普通教室": ["A101", "A102"]},
            allowed_days=(1,),
            allowed_periods=(1, 2, 3, 4),
            patterns=[
                _pattern("class-load-a", teacher="T-A", class_name="C-A", room_type="普通教室", weekly_sessions=2, duration_weeks=18, consecutive_slots=2),
                _pattern("class-load-b", teacher="T-B", class_name="C-A", room_type="普通教室", weekly_sessions=2, duration_weeks=18, consecutive_slots=2),
            ],
            expect_complete=False,
            expected_unresolved_reason="automatic_search_exhausted",
        ),
        Scenario(
            name="dynamic_week_hour_conservation",
            rooms_by_type={"普通教室": ["A101", "A102"], "机房": ["Lab201"]},
            patterns=[
                _pattern("short-eight-weeks", teacher="T-A", class_name="C-A", room_type="普通教室", weekly_sessions=1, duration_weeks=8, consecutive_slots=2),
                _pattern("locked-nine-weeks", teacher="T-B", class_name="C-B", room_type="普通教室", weekly_sessions=1, duration_weeks=9, consecutive_slots=2),
                _pattern("spanning-eleven-weeks", teacher="T-C", class_name="C-C", room_type="机房", weekly_sessions=1, duration_weeks=11, consecutive_slots=4),
                _pattern("spanning-eighteen-weeks", teacher="T-D", class_name="C-D", room_type="普通教室", weekly_sessions=1, duration_weeks=18, consecutive_slots=2),
            ],
        ),
        Scenario(
            name="classroom_capacity_exact_fit",
            rooms_by_type={"机房": ["Lab201"]},
            room_capacity_by_name={"Lab201": 48},
            patterns=[
                _pattern("lab-exact-capacity", teacher="T-A", class_name="C-A", room_type="机房",
                         weekly_sessions=1, duration_weeks=4, consecutive_slots=4, student_count=48),
            ],
        ),
        Scenario(
            name="classroom_capacity_too_small",
            rooms_by_type={"机房": ["Lab201"]},
            room_capacity_by_name={"Lab201": 48},
            patterns=[
                _pattern("lab-over-capacity", teacher="T-A", class_name="C-A", room_type="机房",
                         weekly_sessions=1, duration_weeks=4, consecutive_slots=4, student_count=49),
            ],
            expect_complete=False,
            expected_unresolved_reason="classroom_capacity_unavailable",
        ),
        Scenario(
            name="classroom_capacity_selects_large_room",
            rooms_by_type={"机房": ["Lab201", "Lab202"]},
            room_capacity_by_name={"Lab201": 32, "Lab202": 48},
            expected_room="Lab202",
            patterns=[
                _pattern("lab-select-large", teacher="T-A", class_name="C-A", room_type="机房",
                         weekly_sessions=1, duration_weeks=4, consecutive_slots=4, student_count=40),
            ],
        ),
    ]


def run_scenario(scenario: Scenario) -> dict[str, Any]:
    schedule = DynamicSemesterSchedule(sum(PHASE_WEEKS))
    unplaced, _ = place_dynamic(
        scenario.patterns,
        schedule,
        rooms_by_type=scenario.rooms_by_type,
        model_candidates={pattern["uid"]: [] for pattern in scenario.patterns},
        allowed_days=list(scenario.allowed_days),
        allowed_periods=list(scenario.allowed_periods),
        room_capacity_by_name=scenario.room_capacity_by_name,
    )
    conflicts = {schedule.name: audit_dynamic_schedule(schedule)}
    conservation = final_hour_audit(scenario.patterns, schedule)
    room_type_by_name = {
        room: room_type
        for room_type, rooms in scenario.rooms_by_type.items()
        for room in rooms
    }
    resource_type_mismatches = [
        {
            "uid": fragment["uid"],
            "expected": fragment["pattern"].get("required_room_type"),
            "actual": room_type_by_name.get(fragment["room"]),
            "room": fragment["room"],
        }
        for fragment in schedule.fragments
        if fragment["pattern"].get("required_room_type")
        and room_type_by_name.get(fragment["room"]) != fragment["pattern"].get("required_room_type")
    ]
    unresolved = unplaced
    actual_complete = not unresolved
    result = {
        "scenario": scenario.name,
        "expect_complete": scenario.expect_complete,
        "actual_complete": actual_complete,
        "unresolved": unresolved,
        "conflicts": conflicts,
        "conservation_mismatch": conservation["mismatch_count"],
        "resource_type_mismatches": resource_type_mismatches,
        "capacity_mismatches": [
            {
                "uid": fragment["uid"],
                "student_count": int(fragment["pattern"].get("student_count") or 0),
                "capacity": int((scenario.room_capacity_by_name or {}).get(fragment["room"]) or 0),
                "room": fragment["room"],
            }
            for fragment in schedule.fragments
            if int(fragment["pattern"].get("student_count") or 0) > 0
            and scenario.room_capacity_by_name is not None
            and int((scenario.room_capacity_by_name or {}).get(fragment["room"]) or 0)
                < int(fragment["pattern"].get("student_count") or 0)
        ],
        "fragment_count": len(schedule.fragments),
    }
    if scenario.expected_room:
        result["expected_room_selected"] = any(
            fragment["room"] == scenario.expected_room
            for fragment in schedule.fragments
            if fragment["uid"] == scenario.patterns[0]["uid"]
        )
    if actual_complete:
        result["valid"] = (
            scenario.expect_complete
            and not any(sum(audit.values()) for audit in conflicts.values())
            and conservation["mismatch_count"] == 0
            and not resource_type_mismatches
            and not result["capacity_mismatches"]
            and (scenario.expected_room is None or result.get("expected_room_selected", False))
        )
    else:
        result["valid"] = (
            not scenario.expect_complete
            and (
                scenario.expected_unresolved_reason is None
                or any(item.get("reason") == scenario.expected_unresolved_reason
                       or item.get("stage") == scenario.expected_unresolved_reason
                       for item in unresolved)
            )
        )
    return result


def run_all() -> dict[str, Any]:
    results = [run_scenario(scenario) for scenario in scenarios()]
    return {
        "scenario_count": len(results),
        "passed": sum(result["valid"] for result in results),
        "failed": [result["scenario"] for result in results if not result["valid"]],
        "results": results,
    }


def main() -> None:
    report = run_all()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
