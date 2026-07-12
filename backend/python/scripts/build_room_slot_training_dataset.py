"""Build supervised room+slot recommendation samples from history timetables.

Each row is a pair:
    teaching task + candidate room + candidate day/period -> label

The first version intentionally uses only task fields and candidate fields. It
does not add historical-statistical context features, so inference can use the
same feature shape from newly imported teaching tasks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset" / "_combined"
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "data" / "parsed" / "room_slot_training_dataset"
DEFAULT_NEGATIVES_PER_POSITIVE = 5
DEFAULT_RANDOM_SEED = 20260615

OUTPUT_FIELDS = [
    "split",
    "label",
    "source_semester",
    "source_schedule",
    "course_id",
    "course_code",
    "course_code_prefix",
    "course_name",
    "course_type",
    "required_room_type",
    "total_hours",
    "segment_count",
    "teacher_name",
    "teacher_count",
    "class_name",
    "class_names",
    "class_count",
    "major",
    "department",
    "grade",
    "class_index",
    "is_zhuanshengben",
    "academic_year",
    "semester",
    "candidate_room",
    "candidate_room_type",
    "candidate_capacity",
    "candidate_day_of_week",
    "candidate_period_index",
    "candidate_slot_key",
    "room_type_match",
]


def build_room_slot_training_dataset(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    valid_semester: str | None = None,
    negatives_per_positive: int = DEFAULT_NEGATIVES_PER_POSITIVE,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")

    tasks = _read_csv(input_dir / "teaching_tasks.csv")
    occurrences = _read_csv(input_dir / "timetable_occurrences.csv")
    courses = _read_csv(input_dir / "courses.csv")
    classrooms = _read_csv(input_dir / "classrooms.csv")
    class_groups = _read_csv(input_dir / "class_groups.csv")

    valid_semester = valid_semester or _latest_semester(tasks)
    course_by_key = {
        (_clean(row.get("source_schedule")), _clean(row.get("course_id"))): row
        for row in courses
    }
    class_group_by_key = {
        (_clean(row.get("source_schedule")), _clean(row.get("class_name"))): row
        for row in class_groups
    }
    classroom_by_name = {
        _clean(row.get("classroom_name")): row
        for row in classrooms
        if _clean(row.get("classroom_name"))
    }
    global_slots = _global_slots(occurrences)
    positives_by_task = _positive_combos_by_task(occurrences)

    train_rows: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    positive_count = 0
    negative_count = 0

    for task in tasks:
        if _clean(task.get("schedulable")).lower() != "true":
            skipped["unschedulable_task"] += 1
            continue
        task_key = _task_key(task)
        positives = positives_by_task.get(task_key, {})
        if not positives:
            skipped["task_without_positive_room_slot"] += 1
            continue
        candidate_rooms = _candidate_rooms(classroom_by_name)
        if not candidate_rooms:
            skipped["task_without_candidate_rooms"] += 1
            continue
        candidate_combos = [
            (room, day, period)
            for room in candidate_rooms
            for day, period in global_slots
        ]
        positive_combos = set(positives)
        negative_pool = [combo for combo in candidate_combos if combo not in positive_combos]
        if not negative_pool:
            skipped["task_without_negative_pool"] += 1
            continue

        split = "valid" if _clean(task.get("source_semester")) == valid_semester else "train"
        course = course_by_key.get((_clean(task.get("source_schedule")), _clean(task.get("course_id"))), {})
        class_group = class_group_by_key.get((_clean(task.get("source_schedule")), _clean(task.get("class_name"))), {})
        base = _base_task_features(task, course, class_group, split=split)

        task_rows: list[dict[str, Any]] = []
        for room, day, period in sorted(positive_combos):
            task_rows.append(_sample_row(
                base=base,
                classroom=classroom_by_name.get(room, {}),
                room=room,
                day=day,
                period=period,
                label=1,
            ))
        positive_count += len(positive_combos)

        rng = random.Random(random_seed + _stable_int("|".join(task_key)))
        negative_target = min(len(negative_pool), len(positive_combos) * max(1, negatives_per_positive))
        for room, day, period in rng.sample(negative_pool, negative_target):
            task_rows.append(_sample_row(
                base=base,
                classroom=classroom_by_name.get(room, {}),
                room=room,
                day=day,
                period=period,
                label=0,
            ))
        negative_count += negative_target

        if split == "valid":
            valid_rows.extend(task_rows)
        else:
            train_rows.extend(task_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "train.csv"
    valid_path = output_dir / "valid.csv"
    all_path = output_dir / "all.csv"
    report_path = output_dir / "report.json"
    _write_csv(train_path, train_rows, OUTPUT_FIELDS)
    _write_csv(valid_path, valid_rows, OUTPUT_FIELDS)
    _write_csv(all_path, train_rows + valid_rows, OUTPUT_FIELDS)

    report = {
        "status": "ok",
        "version": "room-slot-training-dataset-v1",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "valid_semester": valid_semester,
        "negatives_per_positive": negatives_per_positive,
        "random_seed": random_seed,
        "source_counts": {
            "teaching_tasks": len(tasks),
            "timetable_occurrences": len(occurrences),
            "courses": len(courses),
            "classrooms": len(classrooms),
            "class_groups": len(class_groups),
            "global_slots": len(global_slots),
        },
        "row_counts": {
            "train": len(train_rows),
            "valid": len(valid_rows),
            "all": len(train_rows) + len(valid_rows),
            "positive": positive_count,
            "negative": negative_count,
        },
        "label_counts": dict(Counter(str(row["label"]) for row in train_rows + valid_rows).most_common()),
        "split_label_counts": {
            "train": dict(Counter(str(row["label"]) for row in train_rows).most_common()),
            "valid": dict(Counter(str(row["label"]) for row in valid_rows).most_common()),
        },
        "skipped": dict(skipped.most_common()),
        "outputs": {
            "train": str(train_path),
            "valid": str(valid_path),
            "all": str(all_path),
            "report": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _positive_combos_by_task(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[tuple[str, int, int], int]]:
    result: dict[tuple[str, str, str], dict[tuple[str, int, int], int]] = defaultdict(lambda: defaultdict(int))
    seen_weeks: dict[tuple[str, str, str, str, int, int], set[int]] = defaultdict(set)
    for row in rows:
        key = (
            _clean(row.get("source_schedule")),
            _clean(row.get("course_id")),
            _clean(row.get("class_name")),
        )
        room = _clean(row.get("classroom_name"))
        day = _safe_int(row.get("day_of_week"))
        period = _safe_int(row.get("period_index"))
        week = _safe_int(row.get("week_index"))
        if not all(key) or not room or day <= 0 or period <= 0:
            continue
        week_key = (*key, room, day, period)
        seen_weeks[week_key].add(week)
    for week_key, weeks in seen_weeks.items():
        source_schedule, course_id, class_name, room, day, period = week_key
        result[(source_schedule, course_id, class_name)][(room, day, period)] = len(weeks)
    return result


def _base_task_features(
    task: dict[str, str],
    course: dict[str, str],
    class_group: dict[str, str],
    *,
    split: str,
) -> dict[str, Any]:
    total_hours = _safe_int(task.get("total_hours"))
    class_name = _clean(task.get("class_name"))
    class_names = _clean(task.get("class_names"))
    return {
        "split": split,
        "source_semester": _clean(task.get("source_semester")),
        "source_schedule": _clean(task.get("source_schedule")),
        "course_id": _clean(task.get("course_id")),
        "course_code": _clean(task.get("course_code")),
        "course_code_prefix": _course_code_prefix(task.get("course_code")),
        "course_name": _clean(task.get("course_name")),
        "course_type": _clean(course.get("course_type")) or _infer_course_type(task),
        "required_room_type": _clean(task.get("required_room_type")),
        "total_hours": total_hours,
        "segment_count": total_hours // 2 if total_hours > 0 else 0,
        "teacher_name": _clean(task.get("teacher_name")),
        "teacher_count": len(_split_names(task.get("teacher_name"))),
        "class_name": class_name,
        "class_names": class_names,
        "class_count": len(_split_names(class_names)) or 1,
        "major": _clean(class_group.get("major")) or _major_from_class_name(class_name),
        "department": _clean(class_group.get("department")),
        "grade": _clean(class_group.get("grade")) or _grade_from_class_name(class_name),
        "class_index": _class_index(class_name),
        "is_zhuanshengben": "true" if "专升本" in class_name or "专升本" in class_names else "false",
        "academic_year": _clean(class_group.get("academic_year")),
        "semester": _clean(class_group.get("semester")),
    }


def _sample_row(
    *,
    base: dict[str, Any],
    classroom: dict[str, str],
    room: str,
    day: int,
    period: int,
    label: int,
) -> dict[str, Any]:
    candidate_room_type = _clean(classroom.get("classroom_type")) or "普通教室"
    required_room_type = _clean(base.get("required_room_type"))
    row = dict(base)
    row.update({
        "label": label,
        "candidate_room": room,
        "candidate_room_type": candidate_room_type,
        "candidate_capacity": _safe_int(classroom.get("capacity")) or 120,
        "candidate_day_of_week": day,
        "candidate_period_index": period,
        "candidate_slot_key": f"{day}-{period}",
        "room_type_match": "true" if not required_room_type or required_room_type == candidate_room_type else "false",
    })
    return row


def _candidate_rooms(classroom_by_name: dict[str, dict[str, str]]) -> list[str]:
    return sorted(classroom_by_name)


def _global_slots(rows: list[dict[str, str]]) -> list[tuple[int, int]]:
    slots = {
        (_safe_int(row.get("day_of_week")), _safe_int(row.get("period_index")))
        for row in rows
    }
    return sorted((day, period) for day, period in slots if day > 0 and period > 0)


def _latest_semester(rows: list[dict[str, str]]) -> str:
    semesters = sorted({_clean(row.get("source_semester")) for row in rows if _clean(row.get("source_semester"))})
    if not semesters:
        raise SystemExit("no source_semester values found")
    return semesters[-1]


def _task_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        _clean(row.get("source_schedule")),
        _clean(row.get("course_id")),
        _clean(row.get("class_name")),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {
                str(key or "").strip(): value.strip() if isinstance(value, str) else value
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        ]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _split_names(value: Any) -> list[str]:
    return [_clean(item) for item in re.split(r"[,，、/;；\s]+", str(value or "")) if _clean(item)]


def _course_code_prefix(value: Any) -> str:
    match = re.match(r"([A-Za-z\u4e00-\u9fa5]+)", _clean(value))
    return match.group(1) if match else ""


def _grade_from_class_name(value: str) -> str:
    match = re.search(r"(20\d{2})级", value or "")
    return match.group(1) if match else ""


def _class_index(value: str) -> str:
    match = re.search(r"(\d+)班", value or "")
    return match.group(1) if match else ""


def _major_from_class_name(value: str) -> str:
    text = re.sub(r"^20\d{2}级", "", value or "")
    text = re.sub(r"\d+班.*$", "", text)
    return text.strip()


def _infer_course_type(task: dict[str, str]) -> str:
    room_type = _clean(task.get("required_room_type"))
    if room_type == "机房":
        return "上机课"
    return "理论课"


def _stable_int(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return int(digest, 16)


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build room+slot recommendation training dataset.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--valid-semester", default=None)
    parser.add_argument("--negatives-per-positive", type=int, default=DEFAULT_NEGATIVES_PER_POSITIVE)
    parser.add_argument("--random-seed", type=int, default=DEFAULT_RANDOM_SEED)
    args = parser.parse_args()
    report = build_room_slot_training_dataset(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        valid_semester=args.valid_semester,
        negatives_per_positive=max(1, args.negatives_per_positive),
        random_seed=args.random_seed,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
