"""Extract training samples from parsed schedule imports.

Walks a directory of parsed schedule CSVs (produced by batch_process_schedule_imports.py --training)
and merges timetable_occurrences with courses/teachers/class_groups to produce a unified
training_samples.jsonl compatible with placement_single_model.py.

The output goes to clean_training_samples.jsonl directly, skipping the V3 clean_training_samples.py
pipeline since our data is already filtered by the parser.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scheduler.placement_single_model import DATA_PATH as SINGLE_DATA_PATH, TEXT_FEATURES, NUMERIC_FEATURES

DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "parsed" / "schedule_imports_training"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "models" / "v3.5" / "training" / "training_samples.jsonl"
DEFAULT_REPORT_PATH = Path(__file__).resolve().parents[2] / "models" / "v3.5" / "training" / "training_extract_report.json"


def extract(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")

    dirs = sorted([d for d in input_dir.iterdir() if d.is_dir()])
    all_samples: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    stats = Counter()
    aggregated_courses: dict[str, dict[str, Any]] = {}
    aggregated_teachers: dict[str, dict[str, Any]] = {}
    aggregated_class_groups: dict[str, dict[str, Any]] = {}

    for class_dir in dirs:
        occurrences = _read_csv(class_dir / "timetable_occurrences.csv")
        courses = _read_csv(class_dir / "courses.csv")
        teachers = _read_csv(class_dir / "teachers.csv")
        class_groups = _read_csv(class_dir / "class_groups.csv")

        for row in courses:
            code = str(row.get("course_code") or "").strip()
            if code:
                aggregated_courses.setdefault(code, {})
                for key in ["course_name", "course_code", "course_type", "required_room_type", "credits", "required_hours"]:
                    if row.get(key):
                        aggregated_courses[code][key] = row[key]

        for row in teachers:
            name = str(row.get("teacher_name") or "").strip()
            if name:
                aggregated_teachers.setdefault(name, {})
                aggregated_teachers[name]["teacher_name"] = name

        for row in class_groups:
            name = str(row.get("class_name") or "").strip()
            if name:
                aggregated_class_groups.setdefault(name, {})
                aggregated_class_groups[name].update({
                    "class_name": name,
                    "class_major": row.get("major") or "",
                    "class_department": row.get("department") or "",
                    "class_grade": _safe_int(row.get("grade")),
                    "student_count": _safe_int(row.get("student_count")),
                })

    for class_dir in dirs:
        occurrences = _read_csv(class_dir / "timetable_occurrences.csv")
        class_groups = _read_csv(class_dir / "class_groups.csv")
        local_class_groups = {_clean(row.get("class_name")): row for row in class_groups if _clean(row.get("class_name"))}

        for item in occurrences:
            course_code = _clean(item.get("course_code"))
            class_name = _clean(item.get("class_name"))
            teacher_name = _clean(item.get("teacher_name"))

            course = aggregated_courses.get(course_code, {})
            class_group = aggregated_class_groups.get(class_name) or local_class_groups.get(class_name, {})
            teacher = aggregated_teachers.get(teacher_name, {})

            total_hours = _safe_float(course.get("required_hours", 16))
            sample = {
                "course_name": course.get("course_name") or item.get("course_name") or course_code,
                "course_code": course_code,
                "teacher_no": teacher.get("teacher_name") or teacher_name or "",
                "teacher_name": teacher_name or "",
                "class_name": class_name or "",
                "class_major": class_group.get("class_major") or "",
                "class_department": class_group.get("class_department") or "",
                "course_type": course.get("course_type") or "理论课",
                "required_room_type": course.get("required_room_type") or "",
                "class_grade": _safe_int(class_group.get("class_grade")),
                "class_no": 0,
                "student_count": _safe_int(class_group.get("student_count")),
                "total_hours": total_hours,
                "classroom_name": _clean(item.get("classroom_name")),
                "day_of_week": _safe_int(item.get("day_of_week")),
                "period_index": _safe_int(item.get("period_index")),
                # 一条记录是一次授课，占 consecutive_slots 个原子小节。少了这一列，
                # 样本会把 2 节的课当成 1 节，学出来的落位和课时都是错的。
                "consecutive_slots": max(1, _safe_int(item.get("consecutive_slots")) or 1),
                "slot_label": f"{_safe_int(item.get('day_of_week'))}|{_safe_int(item.get('period_index'))}",
                "resource_key": f"{_clean(item.get('classroom_name'))}|{_safe_int(item.get('day_of_week'))}|{_safe_int(item.get('period_index'))}",
                "classroom_capacity": 80,
                "source_key": f"{course_code}|{teacher_name}|{class_name}",
            }
            if sample["classroom_name"] and sample["day_of_week"] > 0 and sample["period_index"] > 0:
                all_samples.append(sample)
                stats["valid_occurrences"] += 1
            else:
                skipped.append({"class_name": class_name, "course_code": course_code, "reason": "missing classroom/day/period"})
                stats["skipped_missing_fields"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_path, all_samples)

    report = {
        "status": "ok",
        "input_dir": str(input_dir),
        "output_path": str(output_path),
        "counts": dict(sorted(stats.items())),
        "unique_courses": len(aggregated_courses),
        "unique_teachers": len(aggregated_teachers),
        "unique_class_groups": len(aggregated_class_groups),
        "total_samples": len(all_samples),
        "skipped_count": len(skipped),
        "feature_dimensions": {
            "text_features": TEXT_FEATURES,
            "numeric_features": NUMERIC_FEATURES,
            "label_columns": ["classroom_name", "day_of_week", "period_index", "consecutive_slots", "resource_key", "slot_label"],
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else 0
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract training samples from parsed schedule imports.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()
    report = extract(
        input_dir=Path(args.input_dir),
        output_path=Path(args.output),
        report_path=Path(args.report),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
