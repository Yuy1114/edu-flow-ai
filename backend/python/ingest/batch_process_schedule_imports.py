"""Batch process class schedule Excel imports.

For each .xls/.xlsx under input-dir:
1. parse_schedule_excel.py logic: Excel -> CSV
2. csv_to_jsonl.py logic: CSV -> JSONL
3. analyze_schedule_import.py logic: DB comparison report
4. prepare_import_review.py logic: human-review decision CSV

This script is read-only against the database. It does not apply decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ingest.analyze_schedule_import import analyze
from ingest.csv_to_jsonl import convert_dir
from ingest.parse_schedule_excel import DEFAULT_OUTPUT_ROOT, parse_schedule_excel
from ingest.prepare_import_review import prepare_review

DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "schedules"
DEFAULT_BATCH_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "batch_process_report.json"


DEFAULT_TRAINING_OUTPUT_ROOT = DEFAULT_OUTPUT_ROOT.parent / "schedule_imports_training"


def batch_process(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    task_batch: str = "DEFAULT",
    fail_fast: bool = False,
    training: bool = False,
) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")
    files = sorted([path for path in input_dir.rglob("*") if path.suffix.lower() in {".xls", ".xlsx"}])
    if training:
        output_root = DEFAULT_TRAINING_OUTPUT_ROOT
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    parsed_dirs: list[Path] = []
    print(f"发现 {len(files)} 个课表文件，输出目录：{output_root}", flush=True)
    for index, path in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] 处理 {path.name}", flush=True)
        output_dir = _unique_output_dir(output_root, path)
        try:
            _clean_stale_analysis_jsonl(output_dir)
            parse_report = parse_schedule_excel(input_path=path, output_dir=output_dir, task_batch=task_batch)
            jsonl_report = convert_dir(input_dir=output_dir)
            parsed_dirs.append(output_dir)
            item: dict[str, Any] = {
                "status": "ok",
                "input_path": str(path),
                "output_dir": str(output_dir),
                "parse_counts": parse_report.get("counts", {}),
                "parse_quality": parse_report.get("quality", {}),
                "jsonl": {"file_count": jsonl_report.get("file_count"), "total_rows": jsonl_report.get("total_rows")},
            }
            if not training:
                analysis_report = analyze(input_dir=output_dir)
                review_report = prepare_review(input_dir=output_dir)
                item["analysis"] = analysis_report.get("counts", {})
                item["conflict_counts"] = analysis_report.get("conflict_counts", {})
                item["new_item_counts"] = analysis_report.get("new_item_counts", {})
                item["review"] = review_report.get("counts", {})
            results.append(item)
        except Exception as exc:  # noqa: BLE001 - batch report should capture per-file failures
            item = {
                "status": "failed",
                "input_path": str(path),
                "output_dir": str(output_dir),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            results.append(item)
            if fail_fast:
                raise

    aggregate_dir = None
    aggregate_report = None
    if not training:
        aggregate_dir = output_root / f"_global_{task_batch}"
        print(f"生成全局聚合导入批次：{aggregate_dir}", flush=True)
        aggregate_report = _build_global_import_batch(
            source_dirs=parsed_dirs,
            output_dir=aggregate_dir,
            task_batch=task_batch,
        )
        analysis_report = analyze(input_dir=aggregate_dir)
        review_report = prepare_review(input_dir=aggregate_dir)
        aggregate_report["analysis"] = analysis_report.get("counts", {})
        aggregate_report["conflict_counts"] = analysis_report.get("conflict_counts", {})
        aggregate_report["new_item_counts"] = analysis_report.get("new_item_counts", {})
        aggregate_report["review"] = review_report.get("counts", {})

    report = {
        "status": "ok" if all(item["status"] == "ok" for item in results) else "failed",
        "input_dir": str(input_dir),
        "output_root": str(output_root),
        "task_batch": task_batch,
        "file_count": len(files),
        "success_count": sum(1 for item in results if item["status"] == "ok"),
        "failed_count": sum(1 for item in results if item["status"] != "ok"),
        "aggregate": _aggregate(results),
        "quality": _quality_aggregate(results),
        "global_batch": aggregate_report,
        "items": results,
    }
    (output_root / "batch_process_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _clean_stale_analysis_jsonl(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for path in output_dir.glob("import_*.jsonl"):
        path.unlink()


def _unique_output_dir(output_root: Path, input_path: Path) -> Path:
    stem = input_path.stem
    candidate = output_root / stem
    if not candidate.exists():
        return candidate
    # Reuse same deterministic directory for the same source file; parsing overwrites CSVs.
    return candidate


def _build_global_import_batch(*, source_dirs: list[Path], output_dir: Path, task_batch: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    courses = _merge_by_key(source_dirs, "courses.csv", "course_id")
    teachers = _merge_by_key(source_dirs, "teachers.csv", "teacher_name")
    classrooms = _merge_by_key(source_dirs, "classrooms.csv", "classroom_name")
    class_groups = _merge_by_key(source_dirs, "class_groups.csv", "class_name")
    teaching_tasks = _merge_teaching_tasks(source_dirs, task_batch)

    _write_csv(output_dir / "courses.csv", courses, [
        "course_id", "course_code", "course_name", "credits", "required_hours", "course_type", "required_room_type",
        "schedulable", "exclude_reason", "raw_text",
    ])
    _write_csv(output_dir / "teachers.csv", teachers, ["teacher_name", "department", "title", "raw_source"])
    _write_csv(output_dir / "classrooms.csv", classrooms, ["classroom_name", "classroom_type", "capacity", "status", "raw_source"])
    _write_csv(output_dir / "class_groups.csv", class_groups, [
        "class_name", "major", "department", "grade", "student_count", "academic_year", "semester",
    ])
    _write_csv(output_dir / "teaching_tasks.csv", teaching_tasks, [
        "course_id", "course_code", "course_name", "teacher_name", "class_name", "class_names", "total_hours", "required_room_type",
        "task_batch", "schedulable", "exclude_reason", "source", "resource_signature",
    ])

    report = {
        "status": "ok",
        "output_dir": str(output_dir),
        "source_batch_count": len(source_dirs),
        "counts": {
            "courses": len(courses),
            "teachers": len(teachers),
            "classrooms": len(classrooms),
            "class_groups": len(class_groups),
            "teaching_tasks": len(teaching_tasks),
        },
    }
    (output_dir / "global_import_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _merge_by_key(source_dirs: list[Path], filename: str, key_field: str) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for source_dir in source_dirs:
        for row in _read_csv(source_dir / filename):
            key = _clean(row.get(key_field))
            if not key and key_field == "course_id":
                key = _clean(row.get("course_code"))
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(row)
                continue
            _merge_row_values(merged[key], row)
    return [merged[key] for key in sorted(merged)]


def _merge_teaching_tasks(source_dirs: list[Path], task_batch: str) -> list[dict[str, str]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for source_dir in source_dirs:
        signatures = _occurrence_signatures(source_dir)
        for row in _read_csv(source_dir / "teaching_tasks.csv"):
            course_id = _clean(row.get("course_id"))
            course_code = _clean(row.get("course_code"))
            class_name = _clean(row.get("class_name"))
            teacher_names = _normalize_name_list(row.get("teacher_name"))
            slots = signatures.get((course_code, class_name), set())
            bucket_key = (course_id or course_code, teacher_names, _clean(row.get("schedulable")))
            buckets.setdefault(bucket_key, []).append({
                "row": dict(row),
                "class_name": class_name,
                "slots": slots,
            })

    result: list[dict[str, str]] = []
    for _, records in buckets.items():
        for component in _connected_by_resource_conflict(records):
            row = dict(component[0]["row"])
            class_names = sorted({record["class_name"] for record in component if record["class_name"]})
            resource_slots = sorted({slot for record in component for slot in record["slots"]})
            for record in component[1:]:
                _merge_row_values(row, record["row"])
            row["class_name"] = class_names[0] if class_names else _clean(row.get("class_name"))
            row["class_names"] = ",".join(class_names)
            row["teacher_name"] = _normalize_name_list(row.get("teacher_name"))
            row["task_batch"] = task_batch
            row["source"] = "schedule_excel_global"
            row["resource_signature"] = ";".join(resource_slots)
            result.append(row)
    return sorted(result, key=lambda row: (_clean(row.get("course_id")) or _clean(row.get("course_code")), _clean(row.get("teacher_name")), _clean(row.get("class_names"))))


def _connected_by_resource_conflict(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    remaining = list(range(len(records)))
    components: list[list[dict[str, Any]]] = []
    while remaining:
        seed = remaining.pop(0)
        component_indexes = {seed}
        component_slots = set(records[seed]["slots"])
        changed = True
        while changed:
            changed = False
            for index in list(remaining):
                slots = set(records[index]["slots"])
                if component_slots and slots and component_slots.intersection(slots):
                    remaining.remove(index)
                    component_indexes.add(index)
                    component_slots.update(slots)
                    changed = True
        components.append([records[index] for index in sorted(component_indexes)])
    return components


def _occurrence_signatures(source_dir: Path) -> dict[tuple[str, str], set[str]]:
    items: dict[tuple[str, str], set[str]] = {}
    for row in _read_csv(source_dir / "timetable_occurrences.csv"):
        course_code = _clean(row.get("course_code"))
        class_name = _clean(row.get("class_name"))
        classroom_name = _clean(row.get("classroom_name"))
        if not course_code or not class_name or not classroom_name:
            continue
        slot = "|".join([
            _clean(row.get("week_index")),
            _clean(row.get("day_of_week")),
            _clean(row.get("period_index")),
            classroom_name,
        ])
        items.setdefault((course_code, class_name), set()).add(slot)
    return items


def _merge_row_values(target: dict[str, str], source: dict[str, str]) -> None:
    for key, value in source.items():
        if not _clean(target.get(key)) and _clean(value):
            target[key] = value


def _normalize_name_list(value: str | None) -> str:
    names = [_clean(item) for item in str(value or "").replace("，", ",").replace("、", ",").replace(";", ",").split(",")]
    return ",".join(sorted(name for name in names if name))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate_counts: Counter[str] = Counter()
    conflict_counts: Counter[str] = Counter()
    new_item_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    for item in results:
        if item.get("status") != "ok":
            continue
        for key, value in (item.get("parse_counts") or {}).items():
            aggregate_counts[f"parse_{key}"] += int(value or 0)
        for key, value in (item.get("conflict_counts") or {}).items():
            conflict_counts[key] += int(value or 0)
        for key, value in (item.get("new_item_counts") or {}).items():
            new_item_counts[key] += int(value or 0)
        for key, value in (item.get("review") or {}).items():
            review_counts[key] += int(value or 0)
    return {
        "parse_counts": dict(sorted(aggregate_counts.items())),
        "conflict_counts": dict(sorted(conflict_counts.items())),
        "new_item_counts": dict(sorted(new_item_counts.items())),
        "review_counts": dict(sorted(review_counts.items())),
    }


def _quality_aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    scores: list[int] = []
    for item in results:
        quality = item.get("parse_quality") or {}
        status = str(quality.get("status") or "unknown")
        statuses[status] += 1
        if isinstance(quality.get("score"), int):
            scores.append(quality["score"])
        for issue, count in (quality.get("issue_counts") or {}).items():
            issue_counts[str(issue)] += int(count)
    return {
        "status_counts": dict(statuses.most_common()),
        "issue_counts": dict(issue_counts.most_common()),
        "min_score": min(scores) if scores else None,
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch process schedule Excel imports.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--task-batch", default="DEFAULT")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--training", action="store_true", help="Skip analysis and review; output to schedule_imports_training/")
    args = parser.parse_args()
    report = batch_process(
        input_dir=Path(args.input_dir),
        output_root=Path(args.output_root),
        task_batch=args.task_batch,
        fail_fast=args.fail_fast,
        training=args.training,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "items"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
