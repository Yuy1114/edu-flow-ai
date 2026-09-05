"""Generate reproducible synthetic scheduling inputs without a database.

The task JSONL is accepted directly by ``scheduler.pattern_builder``.  The
resource JSON is intentionally separate: it describes the rooms required by a
future database-free scheduling runner without pretending it was imported from
the production database.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from scheduler.paths import OUTPUT_DIR

Profile = Literal["balanced", "formal-mix", "lab-heavy", "constrained"]
DEFAULT_OUTPUT_DIR = OUTPUT_DIR / "synthetic"
AUTOMATIC_DAY_COUNT = 5
AUTOMATIC_PERIOD_COUNT = 8
SEMESTER_WEEK_COUNT = 18
FORMAL_ASSISTANT_INTERVAL = 37
FORMAL_UNAVAILABLE_INTERVAL = 41
FORMAL_WEEK_WINDOW_INTERVAL = 43
FORMAL_FIXED_ROOM_INTERVAL = 47
FORMAL_CANDIDATE_ROOM_INTERVAL = 31

COURSE_STEMS = [
    "高等数学", "大学英语", "程序设计基础", "数据结构", "数据库原理", "操作系统",
    "计算机网络", "人工智能导论", "软件工程", "大学物理", "线性代数", "离散数学",
    "马克思主义原理", "信息安全", "Web 开发", "算法设计", "机器学习", "Python 编程",
]
MAJORS = ["计算机科学", "软件工程", "人工智能", "数据科学", "网络工程", "信息管理"]
SURNAMES = ["陈", "林", "王", "李", "张", "刘", "周", "吴", "赵", "黄", "徐", "孙"]

# Calibrated from the historical allocation snapshot.  These remain controlled
# combinations: sessions × weeks × session_hours always equals total hours.
THEORY_PATTERNS = (
    ((4, 1, 2), 1), ((8, 1, 4), 5), ((12, 1, 6), 3), ((16, 1, 8), 10),
    ((20, 1, 10), 4), ((24, 2, 6), 7), ((32, 2, 8), 26), ((36, 1, 18), 1),
    ((40, 2, 10), 24), ((48, 3, 8), 9), ((56, 2, 14), 2), ((60, 3, 10), 1),
    ((64, 4, 8), 2), ((72, 3, 12), 5), ((80, 4, 10), 1),
)
LAB_PATTERNS = (
    ((8, 1, 2), 4), ((16, 1, 4), 18), ((24, 1, 6), 8), ((32, 2, 4), 28),
    ((40, 2, 5), 18), ((48, 2, 6), 14), ((64, 2, 8), 7), ((80, 2, 10), 3),
)


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 20260816
    # Calibrated against the accepted 2025-2026 semester export: roughly
    # 2,515 offerings, 541 active teachers, 355 classes and 320 classrooms.
    # ``courses`` is retained as the public/API parameter name, but its value
    # means the number of teaching-task offerings generated for the semester.
    courses: int = 1964
    teachers: int = 541
    class_groups: int = 362
    classrooms: int = 320
    profile: Profile = "balanced"


def generate(*, config: GeneratorConfig, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict:
    if min(config.courses, config.teachers, config.class_groups, config.classrooms) <= 0:
        raise ValueError("courses, teachers, class_groups and classrooms must all be positive")
    rng = random.Random(config.seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    # The historical allocation run contains 84 lab tasks among 2,452 tasks
    # (about 3.4%). Balanced uses that baseline; the other profiles are load
    # tests rather than replicas of the source semester.
    lab_share = {
        "balanced": 0.04,
        "formal-mix": 0.04,
        "lab-heavy": 0.24,
        "constrained": 0.12,
    }[config.profile]
    lab_course_count = max(1, round(config.courses * lab_share))
    theory_course_count = config.courses - lab_course_count
    lab_room_share = {
        "balanced": 0.08,
        "formal-mix": 0.08,
        "lab-heavy": 0.22,
        "constrained": 0.12,
    }[config.profile]
    lab_room_count = max(1, round(config.classrooms * lab_room_share))
    standard_room_count = config.classrooms - lab_room_count
    large_room_count = max(1, round(standard_room_count * 0.2))
    # A normal teaching room must accommodate the school's dominant two-class
    # lecture (normally 56-84 students).  The pressure profiles deliberately
    # retain smaller rooms; they are not acceptance fixtures for a feasible
    # semester.
    regular_room_capacity = 90 if config.profile in {"balanced", "formal-mix"} else 60
    rooms = [
        {"id": index, "name": f"A{100 + index}", "classroom_type": "普通教室",
         "capacity": 120 if index <= large_room_count else regular_room_capacity}
        for index in range(1, standard_room_count + 1)
    ] + [
        {"id": standard_room_count + index, "name": f"Lab{200 + index}",
         "classroom_type": "机房", "capacity": 48}
        for index in range(1, lab_room_count + 1)
    ]
    class_catalog = _build_class_catalog(config.class_groups, rng)
    pair_pool = _build_pair_pool(class_catalog)
    tasks: list[dict] = []
    class_weekly_pressure: Counter[int] = Counter()
    class_semester_pressure: Counter[int] = Counter()
    for course_index in range(config.courses):
        is_lab = course_index >= theory_course_count
        course_type = "上机课" if is_lab else "理论课"
        total_hours, sessions_per_week, duration_weeks = _choose_pattern(rng, is_lab)
        teacher_id = course_index % config.teachers + 1
        teacher_name = f"{SURNAMES[(teacher_id - 1) % len(SURNAMES)]}老师 {teacher_id}"
        selected_classes = _select_task_classes(
            rng,
            class_catalog=class_catalog,
            pair_pool=pair_pool,
            selection_index=course_index,
            is_lab=is_lab,
            profile=config.profile,
            weekly_load=sessions_per_week * (4 if is_lab else 2),
            total_hours=total_hours,
            class_weekly_pressure=class_weekly_pressure,
            class_semester_pressure=class_semester_pressure,
        )
        class_names = [str(item["name"]) for item in selected_classes]
        class_group_ids = [int(item["id"]) for item in selected_classes]
        task = {
            "source_key": f"SIM-{course_index + 1:04d}",
            "teaching_task_id": course_index + 1,
            "course_code": f"SIM{course_index + 1:04d}",
            "course_name": f"{COURSE_STEMS[course_index % len(COURSE_STEMS)]} {course_index // len(COURSE_STEMS) + 1}",
            "course_type": course_type,
            "teacher_name": teacher_name,
            "primary_teacher_id": teacher_id,
            "teacher_ids": [teacher_id],
            # One record is one real teaching task.  A paired lecture carries
            # both class relations directly instead of relying on a later merge.
            "class_name": class_names[0],
            "class_names": ",".join(class_names),
            "class_group_ids": class_group_ids,
            "required_room_type": "机房" if is_lab else "普通教室",
            "total_hours": total_hours,
            "sessions_per_week": sessions_per_week,
            "duration_weeks": duration_weeks,
            "student_count": sum(int(item["student_count"]) for item in selected_classes),
            # Compatibility only. Synthetic tasks no longer need post-hoc merge.
            "merge_group_id": "",
        }
        if config.profile == "formal-mix":
            _apply_formal_constraints(
                task,
                task_index=course_index,
                teacher_count=config.teachers,
                rooms=rooms,
            )
        tasks.append(task)

    task_path = output_dir / "teaching_tasks.jsonl"
    room_path = output_dir / "classrooms.json"
    manifest_path = output_dir / "manifest.json"
    _write_jsonl(task_path, tasks)
    room_path.write_text(json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8")
    weekly_slots = sum(task["sessions_per_week"] * (4 if task["course_type"] == "上机课" else 2) for task in tasks)
    multi_class_tasks = sum(len(task["class_group_ids"]) > 1 for task in tasks)
    class_associations = sum(len(task["class_group_ids"]) for task in tasks)
    active_class_groups = {
        class_group_id
        for task in tasks
        for class_group_id in task["class_group_ids"]
    }
    preflight = resource_capacity_preflight(tasks, rooms)
    constraint_counts = {
        "assistant_teacher_tasks": sum(bool(task.get("assistant_teacher_id")) for task in tasks),
        "teacher_unavailable_tasks": sum(bool(task.get("teacher_unavailable_slots")) for task in tasks),
        "allowed_weeks_tasks": sum(bool(task.get("allowed_weeks")) for task in tasks),
        "fixed_classroom_tasks": sum(bool(task.get("fixed_classroom_name")) for task in tasks),
        "candidate_classroom_tasks": sum(bool(task.get("candidate_classroom_names")) for task in tasks),
    }
    manifest = {
        "generator": "v3-capacity-preflight-formal-mix",
        "config": asdict(config),
        "counts": {
            "courses": config.courses,
            "teaching_tasks": len(tasks),
            "multi_class_tasks": multi_class_tasks,
            "single_class_tasks": len(tasks) - multi_class_tasks,
            "class_associations": class_associations,
            "teachers": config.teachers,
            "class_groups": len(class_catalog),
            "active_class_groups": len(active_class_groups),
            "classrooms": len(rooms),
            "theory_courses": theory_course_count,
            "lab_courses": lab_course_count,
            "standard_rooms": len(rooms) - lab_room_count,
            "large_classrooms": large_room_count,
            "lab_rooms": lab_room_count,
            "weekly_slots": weekly_slots,
            "room_week_capacity": len(rooms) * 5 * 8,
            **constraint_counts,
        },
        "task_type_counts": dict(Counter(task["course_type"] for task in tasks)),
        "resource_capacity_preflight": preflight,
        "paths": {"teaching_tasks": str(task_path), "classrooms": str(room_path)},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _choose_pattern(rng: random.Random, is_lab: bool) -> tuple[int, int, int]:
    options = LAB_PATTERNS if is_lab else THEORY_PATTERNS
    return rng.choices([item[0] for item in options], weights=[item[1] for item in options], k=1)[0]


def _build_class_catalog(class_group_count: int, rng: random.Random) -> list[dict]:
    """Create stable major/year cohorts whose adjacent classes can be paired."""
    section_by_cohort: defaultdict[tuple[str, int], int] = defaultdict(int)
    catalog: list[dict] = []
    all_cohorts = [
        (major, grade)
        for grade in range(2022, 2026)
        for major in MAJORS
    ]
    # Tiny tests still need parallel classes; full-size runs use all 24
    # major/year cohorts and therefore about 15 classes per cohort.
    cohort_count = min(len(all_cohorts), max(1, class_group_count // 4))
    cohorts = all_cohorts[:cohort_count]
    for index in range(class_group_count):
        major, grade = cohorts[index % len(cohorts)]
        cohort = (major, grade)
        section_by_cohort[cohort] += 1
        section = section_by_cohort[cohort]
        catalog.append({
            "id": index + 1,
            "major": major,
            "grade": grade,
            "section": section,
            "name": f"{grade}级{major}{section:02d}班",
            "student_count": rng.randint(28, 42),
        })
    return catalog


def _build_pair_pool(class_catalog: list[dict]) -> list[tuple[dict, dict]]:
    by_cohort: defaultdict[tuple[str, int], list[dict]] = defaultdict(list)
    for item in class_catalog:
        by_cohort[(str(item["major"]), int(item["grade"]))].append(item)
    pairs: list[tuple[dict, dict]] = []
    for cohort in sorted(by_cohort):
        classes = sorted(by_cohort[cohort], key=lambda item: int(item["section"]))
        pairs.extend((classes[index], classes[index + 1]) for index in range(0, len(classes) - 1, 2))
    return pairs


def _select_task_classes(
    rng: random.Random,
    *,
    class_catalog: list[dict],
    pair_pool: list[tuple[dict, dict]],
    selection_index: int,
    is_lab: bool,
    profile: Profile,
    weekly_load: int,
    total_hours: int,
    class_weekly_pressure: Counter[int],
    class_semester_pressure: Counter[int],
) -> list[dict]:
    # Ordinary lectures follow the school's dominant adjacent-pair pattern.
    # Balanced lab tasks stay single so the 48-seat lab pool is feasible;
    # pressure profiles deliberately include some paired lab tasks.
    pair_share = {
        "balanced": 0.0 if is_lab else 0.80,
        "formal-mix": 0.0 if is_lab else 0.80,
        "lab-heavy": 0.35 if is_lab else 0.82,
        "constrained": 0.55 if is_lab else 0.90,
    }[profile]
    if pair_pool and rng.random() < pair_share:
        selected = _least_loaded(
            [list(pair) for pair in pair_pool],
            selection_index=selection_index,
            weekly_load=weekly_load,
            total_hours=total_hours,
            class_weekly_pressure=class_weekly_pressure,
            class_semester_pressure=class_semester_pressure,
        )
    else:
        selected = _least_loaded(
            [[item] for item in class_catalog],
            selection_index=selection_index,
            weekly_load=weekly_load,
            total_hours=total_hours,
            class_weekly_pressure=class_weekly_pressure,
            class_semester_pressure=class_semester_pressure,
        )
    for item in selected:
        class_id = int(item["id"])
        class_weekly_pressure[class_id] += weekly_load
        class_semester_pressure[class_id] += total_hours
    return selected


def _least_loaded(
    candidates: list[list[dict]],
    *,
    selection_index: int,
    weekly_load: int,
    total_hours: int,
    class_weekly_pressure: Counter[int],
    class_semester_pressure: Counter[int],
) -> list[dict]:
    """Choose a cohort without manufacturing an overloaded acceptance fixture."""
    offset = selection_index % len(candidates)
    rotated = candidates[offset:] + candidates[:offset]

    def score(candidate: list[dict]) -> tuple[int, int, int, int]:
        ids = [int(item["id"]) for item in candidate]
        weekly = [class_weekly_pressure[class_id] + weekly_load for class_id in ids]
        semester = [class_semester_pressure[class_id] + total_hours for class_id in ids]
        return max(weekly), max(semester), sum(weekly), sum(semester)

    return min(rotated, key=score)


def _apply_formal_constraints(
    task: dict[str, Any],
    *,
    task_index: int,
    teacher_count: int,
    rooms: list[dict[str, Any]],
) -> None:
    """Add a deterministic sample of the constraints consumed by the DB chain."""
    primary_teacher_id = int(task["primary_teacher_id"])
    if task_index % FORMAL_ASSISTANT_INTERVAL == 0 and teacher_count > 1:
        assistant_id = (primary_teacher_id + max(1, teacher_count // 2) - 1) % teacher_count + 1
        if assistant_id == primary_teacher_id:
            assistant_id = assistant_id % teacher_count + 1
        task["assistant_teacher_id"] = assistant_id
        task["assistant_teacher_name"] = f"{SURNAMES[(assistant_id - 1) % len(SURNAMES)]}老师 {assistant_id}"
        task["teacher_ids"] = [primary_teacher_id, assistant_id]

    if task_index % FORMAL_UNAVAILABLE_INTERVAL == 0:
        task["teacher_unavailable_slots"] = [{
            "teacher_id": primary_teacher_id,
            "week_number": 0,
            "day_of_week": task_index % AUTOMATIC_DAY_COUNT + 1,
            "period_index": (1, 3, 5, 7)[task_index % 4],
        }]

    if task_index % FORMAL_WEEK_WINDOW_INTERVAL == 0:
        duration = int(task["duration_weeks"])
        # A formal availability window constrains placement without turning
        # every sample into a fixed historical mask. Keep up to four weeks of
        # choice so the mixed fixture exercises search rather than pre-solving it.
        allowed_span = min(SEMESTER_WEEK_COUNT, duration + 4)
        start_count = SEMESTER_WEEK_COUNT - allowed_span + 1
        start_week = (task_index * 7) % start_count + 1
        task["allowed_weeks"] = list(range(start_week, start_week + allowed_span))

    required_type = str(task["required_room_type"])
    student_count = int(task["student_count"])
    eligible = [
        room for room in rooms
        if room["classroom_type"] == required_type and int(room["capacity"]) >= student_count
    ]
    if not eligible:
        return
    offset = task_index % len(eligible)
    rotated = eligible[offset:] + eligible[:offset]
    has_explicit_week_window = task_index % FORMAL_WEEK_WINDOW_INTERVAL == 0
    if task_index % FORMAL_FIXED_ROOM_INTERVAL == 0 and not has_explicit_week_window:
        task["fixed_classroom_id"] = int(rotated[0]["id"])
        task["fixed_classroom_name"] = str(rotated[0]["name"])
    elif (
        task_index % FORMAL_CANDIDATE_ROOM_INTERVAL == 0
        or task_index % FORMAL_FIXED_ROOM_INTERVAL == 0
    ):
        selected = rotated[:min(6, len(rotated))]
        task["candidate_classroom_ids"] = [int(room["id"]) for room in selected]
        task["candidate_classroom_names"] = [str(room["name"]) for room in selected]


def resource_capacity_preflight(
    tasks: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    *,
    day_count: int = AUTOMATIC_DAY_COUNT,
    period_count: int = AUTOMATIC_PERIOD_COUNT,
    semester_weeks: int = SEMESTER_WEEK_COUNT,
) -> dict[str, Any]:
    """Check necessary nested room-capacity conditions before scheduling.

    A room with 120 seats can serve every lower tier, while a 60-seat room
    cannot serve a paired class of 70.  Checking only total room-hours hides
    that bottleneck, so each room type is audited at every capacity boundary.
    This is a necessary condition, not a proof that the timetable is feasible.
    """
    tiers: list[dict[str, Any]] = []
    missing_pool: list[dict[str, Any]] = []
    room_types = sorted({str(task.get("required_room_type") or "") for task in tasks})
    for room_type in room_types:
        typed_rooms = [room for room in rooms if str(room.get("classroom_type") or "") == room_type]
        typed_tasks = [task for task in tasks if str(task.get("required_room_type") or "") == room_type]
        max_students = max((int(task.get("student_count") or 0) for task in typed_tasks), default=0)
        thresholds = {1}
        thresholds.update(
            int(room.get("capacity") or 0) + 1
            for room in typed_rooms
            if 0 < int(room.get("capacity") or 0) < max_students
        )
        for minimum_capacity in sorted(thresholds):
            tier_tasks = [
                task for task in typed_tasks
                if max(1, int(task.get("student_count") or 0)) >= minimum_capacity
            ]
            tier_rooms = [
                room for room in typed_rooms
                if int(room.get("capacity") or 0) >= minimum_capacity
            ]
            demand_hours = sum(int(task.get("total_hours") or 0) for task in tier_tasks)
            supply_hours = len(tier_rooms) * day_count * period_count * semester_weeks
            tiers.append({
                "room_type": room_type,
                "minimum_capacity": minimum_capacity,
                "task_count": len(tier_tasks),
                "room_count": len(tier_rooms),
                "demand_hours": demand_hours,
                "supply_hours": supply_hours,
                "slack_hours": supply_hours - demand_hours,
                "utilization": round(demand_hours / supply_hours, 6) if supply_hours else None,
                "feasible": demand_hours <= supply_hours,
            })

        for task in typed_tasks:
            candidates = typed_rooms
            fixed_name = str(task.get("fixed_classroom_name") or "").strip()
            if fixed_name:
                candidates = [room for room in candidates if str(room.get("name")) == fixed_name]
            candidate_names = {str(name) for name in task.get("candidate_classroom_names") or []}
            if candidate_names:
                candidates = [room for room in candidates if str(room.get("name")) in candidate_names]
            candidates = [
                room for room in candidates
                if int(room.get("capacity") or 0) >= int(task.get("student_count") or 0)
            ]
            if not candidates:
                missing_pool.append({
                    "source_key": task.get("source_key"),
                    "room_type": room_type,
                    "student_count": int(task.get("student_count") or 0),
                })

    failed_tiers = [tier for tier in tiers if not tier["feasible"]]
    feasible = not failed_tiers and not missing_pool
    return {
        "kind": "necessary_nested_room_capacity",
        "automatic_domain": {
            "day_count": day_count,
            "period_count": period_count,
            "semester_weeks": semester_weeks,
        },
        "feasible": feasible,
        "status": "ok" if feasible else "insufficient",
        "tiers": tiers,
        "failed_tiers": failed_tiers,
        "task_without_eligible_room_count": len(missing_pool),
        "task_without_eligible_room_preview": missing_pool[:20],
    }


def _student_count(rng: random.Random, *, is_lab: bool, profile: Profile) -> int:
    roll = rng.random()
    if roll < 0.03:
        low, high = 12, 19
    elif roll < 0.13:
        low, high = 20, 24
    elif roll < 0.45:
        low, high = 25, 31
    elif roll < 0.91:
        low, high = 32, 48
    else:
        low, high = 49, 63
    # Balanced samples must be feasible in the 48-seat lab pool. Pressure
    # profiles intentionally retain over-capacity lab tasks.
    if is_lab and profile == "balanced":
        high = min(high, 48)
        low = min(low, high)
    return rng.randint(low, high)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic scheduling inputs.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--courses", type=int, default=1964)
    parser.add_argument("--teachers", type=int, default=541)
    parser.add_argument("--class-groups", type=int, default=362)
    parser.add_argument("--classrooms", type=int, default=320)
    parser.add_argument(
        "--profile", choices=["balanced", "formal-mix", "lab-heavy", "constrained"], default="balanced",
    )
    args = parser.parse_args()
    report = generate(config=GeneratorConfig(
        seed=args.seed, courses=args.courses, teachers=args.teachers,
        class_groups=args.class_groups, classrooms=args.classrooms, profile=args.profile,
    ), output_dir=Path(args.output_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
