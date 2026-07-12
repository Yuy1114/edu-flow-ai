"""Audit combined historical timetable training CSV files.

The audit is intentionally stricter than the importer: accepted training data
should have no hard errors, while softer signals remain visible for review.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_ROOT = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset"
DEFAULT_INPUT_DIR = DEFAULT_DATASET_ROOT / "_combined"
DEFAULT_OUTPUT_DIR = DEFAULT_DATASET_ROOT / "_audit"

COURSE_CODE_PATTERN = re.compile(r"^(?:[\u4e00-\u9fa5]{1,6}|[A-Za-z]{1,6})\d{2,4}$")
NOISE_TOKENS = {
    "虚拟",
    "虚拟103",
    "虚拟教室18",
    "CL001",
    "CL002",
    "CL003",
    "cl001",
    "cl002",
    "cl003",
    "攀岩墙",
    "设392",
    "设387",
    "未排地点",
    "08310B",
    "04113A",
}
AUDIT_FIELDS = [
    "severity",
    "issue",
    "message",
    "table",
    "row_index",
    "source_semester",
    "source_schedule",
    "course_id",
    "course_code",
    "course_name",
    "teacher_name",
    "class_name",
    "class_names",
    "classroom_name",
    "day_of_week",
    "period_index",
    "week_index",
    "total_hours",
    "detail",
]


def audit_history_training_dataset(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sample_size: int = 20,
) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")

    tables = {
        "courses": _read_csv(input_dir / "courses.csv"),
        "teachers": _read_csv(input_dir / "teachers.csv"),
        "classrooms": _read_csv(input_dir / "classrooms.csv"),
        "class_groups": _read_csv(input_dir / "class_groups.csv"),
        "teaching_tasks": _read_csv(input_dir / "teaching_tasks.csv"),
        "timetable_occurrences": _read_csv(input_dir / "timetable_occurrences.csv"),
    }

    issues: list[dict[str, Any]] = []
    issues.extend(_audit_courses(tables["courses"]))
    issues.extend(_audit_teachers(tables["teachers"]))
    issues.extend(_audit_classrooms(tables["classrooms"]))
    issues.extend(_audit_class_groups(tables["class_groups"]))
    issues.extend(_audit_teaching_tasks(tables["teaching_tasks"]))
    issues.extend(_audit_occurrences(tables["timetable_occurrences"]))

    summary = _summary(input_dir, output_dir, tables, issues)
    samples = _sample_issues(issues, sample_size=sample_size)

    output_dir.mkdir(parents=True, exist_ok=True)
    issues_path = output_dir / "audit_issues.csv"
    samples_path = output_dir / "audit_samples.csv"
    summary_path = output_dir / "audit_summary.json"
    _write_csv(issues_path, issues, AUDIT_FIELDS)
    _write_csv(samples_path, samples, AUDIT_FIELDS)
    summary["outputs"] = {
        "summary": str(summary_path),
        "issues": str(issues_path),
        "samples": str(samples_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _audit_courses(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    names_by_id: dict[str, set[str]] = defaultdict(set)
    first_row_by_id: dict[str, tuple[int, dict[str, Any]]] = {}
    names_by_code: dict[str, set[str]] = defaultdict(set)
    first_row_by_code: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, row in enumerate(rows, start=1):
        course_id = _clean(row.get("course_id"))
        code = _clean(row.get("course_code"))
        name = _clean(row.get("course_name"))
        hours = _safe_int(row.get("required_hours"))
        if course_id:
            names_by_id[course_id].add(_canonical_course_name(name))
            first_row_by_id.setdefault(course_id, (index, row))
        if code:
            names_by_code[code].add(_canonical_course_name(name))
            first_row_by_code.setdefault(code, (index, row))
        if not course_id:
            issues.append(_issue("error", "missing_course_id", "课程缺少 ID[...] 唯一键", "courses", index, row))
        if not _valid_course_code(code):
            issues.append(_issue("error", "bad_course_code", "课程代号不符合标准格式", "courses", index, row, detail=code))
        if not _valid_course_name(name):
            issues.append(_issue("error", "bad_course_name", "课程名为空或明显异常", "courses", index, row, detail=name))
        if hours <= 0 or hours % 2 != 0:
            issues.append(_issue("error", "bad_required_hours", "课程课时必须为正偶数", "courses", index, row, detail=str(row.get("required_hours") or "")))
        elif hours > 96:
            issues.append(_issue("review", "very_high_required_hours", "课程课时异常偏高，需要抽查", "courses", index, row, detail=str(hours)))
        hit = _noise_hit(row)
        if hit:
            issues.append(_issue("error", "noise_token_leaked", "课程行含有不应进入训练集的噪声关键词", "courses", index, row, detail=hit))
    for course_id, names in sorted(names_by_id.items()):
        clean_names = {name for name in names if name}
        if len(clean_names) <= 1:
            continue
        index, row = first_row_by_id[course_id]
        issues.append(_issue("error", "course_id_name_conflict", "同一课程 ID 对应多个课程名", "courses", index, row, detail=" | ".join(sorted(clean_names))))
    for code, names in sorted(names_by_code.items()):
        clean_names = {name for name in names if name}
        if len(clean_names) <= 1:
            continue
        index, row = first_row_by_code[code]
        issues.append(_issue("info", "course_code_name_conflict", "同一课程短码对应多个课程名", "courses", index, row, detail=" | ".join(sorted(clean_names))))
    return issues


def _audit_teachers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: Counter[str] = Counter(_clean(row.get("teacher_name")) for row in rows)
    for index, row in enumerate(rows, start=1):
        name = _clean(row.get("teacher_name"))
        if not name:
            issues.append(_issue("error", "missing_teacher_name", "教师名称为空", "teachers", index, row))
        elif seen[name] > 1:
            issues.append(_issue("review", "duplicate_teacher_name", "合并教师表中教师名称重复", "teachers", index, row, detail=name))
        hit = _noise_hit(row)
        if hit:
            issues.append(_issue("error", "noise_token_leaked", "教师行含有不应进入训练集的噪声关键词", "teachers", index, row, detail=hit))
    return issues


def _audit_classrooms(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: Counter[str] = Counter(_clean(row.get("classroom_name")) for row in rows)
    for index, row in enumerate(rows, start=1):
        name = _clean(row.get("classroom_name"))
        capacity = _safe_int(row.get("capacity"))
        if not name:
            issues.append(_issue("error", "missing_classroom_name", "教室名称为空", "classrooms", index, row))
        elif seen[name] > 1:
            issues.append(_issue("review", "duplicate_classroom_name", "合并教室表中教室名称重复", "classrooms", index, row, detail=name))
        if capacity <= 0:
            issues.append(_issue("error", "bad_classroom_capacity", "教室容量必须为正数", "classrooms", index, row, detail=str(row.get("capacity") or "")))
        hit = _noise_hit(row)
        if hit:
            issues.append(_issue("error", "noise_token_leaked", "教室行含有不应进入训练集的噪声关键词", "classrooms", index, row, detail=hit))
    return issues


def _audit_class_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not _clean(row.get("class_name")):
            issues.append(_issue("error", "missing_class_name", "班级名称为空", "class_groups", index, row))
        hit = _noise_hit(row)
        if hit:
            issues.append(_issue("error", "noise_token_leaked", "班级行含有不应进入训练集的噪声关键词", "class_groups", index, row, detail=hit))
    return issues


def _audit_teaching_tasks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        course_id = _clean(row.get("course_id"))
        code = _clean(row.get("course_code"))
        name = _clean(row.get("course_name"))
        hours = _safe_int(row.get("total_hours"))
        if not course_id:
            issues.append(_issue("error", "missing_course_id", "教学任务缺少课程 ID", "teaching_tasks", index, row))
        if not _valid_course_code(code):
            issues.append(_issue("error", "bad_course_code", "教学任务课程代号不符合标准格式", "teaching_tasks", index, row, detail=code))
        if not _valid_course_name(name):
            issues.append(_issue("error", "bad_course_name", "教学任务课程名为空或明显异常", "teaching_tasks", index, row, detail=name))
        if not _clean(row.get("teacher_name")):
            issues.append(_issue("error", "missing_teacher", "教学任务缺少教师", "teaching_tasks", index, row))
        if not (_clean(row.get("class_names")) or _clean(row.get("class_name"))):
            issues.append(_issue("error", "missing_class", "教学任务缺少班级", "teaching_tasks", index, row))
        if hours <= 0 or hours % 2 != 0:
            issues.append(_issue("error", "bad_total_hours", "教学任务课时必须为正偶数", "teaching_tasks", index, row, detail=str(row.get("total_hours") or "")))
        elif hours > 96:
            issues.append(_issue("review", "very_high_total_hours", "教学任务课时异常偏高，需要抽查", "teaching_tasks", index, row, detail=str(hours)))
        hit = _noise_hit(row)
        if hit:
            issues.append(_issue("error", "noise_token_leaked", "教学任务含有不应进入训练集的噪声关键词", "teaching_tasks", index, row, detail=hit))
    return issues


def _audit_occurrences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    slot_buckets: dict[tuple[str, str, str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        course_id = _clean(row.get("course_id"))
        code = _clean(row.get("course_code"))
        name = _clean(row.get("course_name"))
        if not course_id:
            issues.append(_issue("error", "missing_course_id", "课表片段缺少课程 ID", "timetable_occurrences", index, row))
        if not _valid_course_code(code):
            issues.append(_issue("error", "bad_course_code", "课表片段课程代号不符合标准格式", "timetable_occurrences", index, row, detail=code))
        if not _valid_course_name(name):
            issues.append(_issue("error", "bad_course_name", "课表片段课程名为空或明显异常", "timetable_occurrences", index, row, detail=name))
        if not _clean(row.get("teacher_name")):
            issues.append(_issue("error", "missing_teacher", "课表片段缺少教师", "timetable_occurrences", index, row))
        if not _clean(row.get("class_name")):
            issues.append(_issue("error", "missing_class", "课表片段缺少班级", "timetable_occurrences", index, row))
        if not _clean(row.get("classroom_name")):
            issues.append(_issue("error", "missing_classroom", "课表片段缺少教室", "timetable_occurrences", index, row))
        hit = _noise_hit(row)
        if hit:
            issues.append(_issue("error", "noise_token_leaked", "课表片段含有不应进入训练集的噪声关键词", "timetable_occurrences", index, row, detail=hit))
        slot_key = (
            _clean(row.get("source_schedule")),
            _clean(row.get("class_name")),
            _clean(row.get("week_index")),
            _clean(row.get("day_of_week")),
            _clean(row.get("period_index")),
        )
        slot_buckets[slot_key].append((index, row))

    for bucket in slot_buckets.values():
        distinct_courses = {
            (_clean(row.get("course_code")), _clean(row.get("course_name")), _clean(row.get("teacher_name")))
            for _, row in bucket
        }
        distinct_rooms = {_clean(row.get("classroom_name")) for _, row in bucket}
        if len(distinct_courses) > 1:
            index, row = bucket[0]
            detail = " | ".join("/".join(item) for item in sorted(distinct_courses))
            issues.append(_issue("review", "same_class_slot_multiple_courses", "同一班级同一周/星期/节次出现多个不同课程", "timetable_occurrences", index, row, detail=detail))
        elif len(distinct_rooms) > 1:
            index, row = bucket[0]
            issues.append(_issue("info", "same_course_slot_multiple_rooms", "同一课程同一节识别出多个教室", "timetable_occurrences", index, row, detail=",".join(sorted(distinct_rooms))))
    return issues


def _summary(input_dir: Path, output_dir: Path, tables: dict[str, list[dict[str, Any]]], issues: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts = Counter(str(issue.get("severity") or "") for issue in issues)
    issue_counts = Counter(str(issue.get("issue") or "") for issue in issues)
    table_issue_counts = Counter(str(issue.get("table") or "") for issue in issues)
    status = "ok" if severity_counts.get("error", 0) == 0 else "failed"
    if status == "ok" and severity_counts.get("review", 0) > 0:
        status = "review_needed"
    return {
        "version": "history-training-audit-v1",
        "status": status,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "row_counts": {name: len(rows) for name, rows in sorted(tables.items())},
        "issue_count": len(issues),
        "severity_counts": dict(severity_counts.most_common()),
        "issue_counts": dict(issue_counts.most_common()),
        "table_issue_counts": dict(table_issue_counts.most_common()),
        "hard_gate": {
            "passed": severity_counts.get("error", 0) == 0,
            "error_count": severity_counts.get("error", 0),
            "review_count": severity_counts.get("review", 0),
            "info_count": severity_counts.get("info", 0),
        },
        "issues_preview": issues[:80],
    }


def _sample_issues(issues: list[dict[str, Any]], *, sample_size: int) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    counts: Counter[tuple[str, str]] = Counter()
    for issue in issues:
        key = (str(issue.get("severity") or ""), str(issue.get("issue") or ""))
        if counts[key] >= sample_size:
            continue
        sampled.append(issue)
        counts[key] += 1
    return sampled


def _issue(
    severity: str,
    issue: str,
    message: str,
    table: str,
    row_index: int,
    row: dict[str, Any],
    *,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "issue": issue,
        "message": message,
        "table": table,
        "row_index": row_index,
        "source_semester": row.get("source_semester", ""),
        "source_schedule": row.get("source_schedule", ""),
        "course_id": row.get("course_id", ""),
        "course_code": row.get("course_code", ""),
        "course_name": row.get("course_name", ""),
        "teacher_name": row.get("teacher_name", ""),
        "class_name": row.get("class_name", ""),
        "class_names": row.get("class_names", ""),
        "classroom_name": row.get("classroom_name", ""),
        "day_of_week": row.get("day_of_week", ""),
        "period_index": row.get("period_index", ""),
        "week_index": row.get("week_index", ""),
        "total_hours": row.get("total_hours", row.get("required_hours", "")),
        "detail": detail,
    }


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


def _valid_course_code(value: Any) -> bool:
    return bool(COURSE_CODE_PATTERN.fullmatch(_clean(value)))


def _valid_course_name(value: Any) -> bool:
    text = re.sub(r"\s+", "", _clean(value))
    if len(text) < 2:
        return False
    if text in {"）", ")", "（", "(", "-", "--"}:
        return False
    if not re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", text):
        return False
    return not _valid_course_code(text)


def _canonical_course_name(value: Any) -> str:
    text = re.sub(r"\s+", "", _clean(value))
    return re.sub(r"^【专】[0-9.]+人", "", text)


def _noise_hit(row: dict[str, Any]) -> str:
    text = " ".join(str(value or "") for value in row.values())
    for token in sorted(NOISE_TOKENS, key=len, reverse=True):
        if token in text:
            return token
    return ""


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit combined historical timetable training dataset.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--sample-size", type=int, default=20)
    args = parser.parse_args()
    result = audit_history_training_dataset(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        sample_size=max(1, args.sample_size),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
