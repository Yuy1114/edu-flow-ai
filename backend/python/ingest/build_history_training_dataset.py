"""Build a combined historical timetable training dataset from raw schedules."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ingest.csv_to_jsonl import convert_csv_to_jsonl, convert_dir
from ingest.parse_schedule_excel import parse_schedule_excel

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_ROOT = BACKEND_ROOT / "data" / "raw" / "history_training"
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset"
COMBINED_TABLES = {
    "courses.csv",
    "teachers.csv",
    "classrooms.csv",
    "class_groups.csv",
    "teaching_tasks.csv",
    "timetable_occurrences.csv",
}


def build_history_training_dataset(
    *,
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    fail_fast: bool = False,
) -> dict[str, Any]:
    if not input_root.exists() or not input_root.is_dir():
        raise SystemExit(f"input-root not found: {input_root}")

    semester_dirs = sorted([path for path in input_root.iterdir() if path.is_dir()])
    output_root.mkdir(parents=True, exist_ok=True)
    combined_dir = output_root / "_combined"
    combined_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    parsed_dirs_by_quality: dict[str, list[Path]] = defaultdict(list)
    status_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    parse_counts: Counter[str] = Counter()

    for semester_dir in semester_dirs:
        semester_key = _slugify(semester_dir.name)
        files = sorted([path for path in semester_dir.rglob("*") if path.suffix.lower() in {".xls", ".xlsx"}])
        print(f"处理学期 {semester_dir.name}: {len(files)} 个课表", flush=True)
        for index, input_path in enumerate(files, start=1):
            print(f"  [{index}/{len(files)}] {input_path.name}", flush=True)
            output_dir = output_root / semester_key / input_path.stem
            try:
                report = parse_schedule_excel(
                    input_path=input_path,
                    output_dir=output_dir,
                    task_batch=semester_key,
                )
                convert_dir(input_dir=output_dir)
                quality = report.get("quality") or {}
                quality_status = str(quality.get("status") or "unknown")
                parsed_dirs_by_quality[quality_status].append(output_dir)
                status_counts[quality_status] += 1
                for issue, count in (quality.get("issue_counts") or {}).items():
                    issue_counts[str(issue)] += int(count)
                for name, count in (report.get("counts") or {}).items():
                    parse_counts[name] += int(count or 0)
                items.append({
                    "status": "ok",
                    "semester": semester_dir.name,
                    "semester_key": semester_key,
                    "input_path": str(input_path),
                    "output_dir": str(output_dir),
                    "counts": report.get("counts", {}),
                    "quality": quality,
                })
            except Exception as exc:  # noqa: BLE001 - keep batch inspectable
                items.append({
                    "status": "failed",
                    "semester": semester_dir.name,
                    "semester_key": semester_key,
                    "input_path": str(input_path),
                    "output_dir": str(output_dir),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
                if fail_fast:
                    raise

    combined_files = _write_combined_tables(parsed_dirs_by_quality["accepted"], combined_dir)
    review_combined_dir = output_root / "_review_needed"
    review_combined_files = _write_combined_tables(parsed_dirs_by_quality["review_needed"], review_combined_dir)
    report = {
        "status": "ok" if all(item["status"] == "ok" for item in items) else "failed",
        "input_root": str(input_root),
        "output_root": str(output_root),
        "combined_dir": str(combined_dir),
        "review_combined_dir": str(review_combined_dir),
        "semester_count": len(semester_dirs),
        "file_count": len(items),
        "success_count": sum(1 for item in items if item["status"] == "ok"),
        "failed_count": sum(1 for item in items if item["status"] != "ok"),
        "parse_counts": dict(sorted(parse_counts.items())),
        "quality": {
            "status_counts": dict(status_counts.most_common()),
            "issue_counts": dict(issue_counts.most_common()),
        },
        "combined_files": combined_files,
        "review_combined_files": review_combined_files,
        "items": items,
    }
    (output_root / "history_training_dataset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _write_combined_tables(source_dirs: list[Path], combined_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for table_name in sorted(COMBINED_TABLES):
        if table_name == "classrooms.csv":
            rows = _combined_classrooms(source_dirs)
            fieldnames = ["classroom_name", "classroom_type", "capacity", "status", "raw_source"]
        elif table_name == "teachers.csv":
            rows = _combined_teachers(source_dirs)
            fieldnames = ["teacher_name", "department", "title", "raw_source"]
        else:
            rows, fieldnames = _combined_source_rows(source_dirs, table_name)
        csv_path = combined_dir / table_name
        jsonl_path = combined_dir / f"{Path(table_name).stem}.jsonl"
        _write_csv(csv_path, rows, fieldnames)
        convert_csv_to_jsonl(input_path=csv_path, output_path=jsonl_path)
        result[table_name] = {
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
            "rows": len(rows),
        }
    return result


def _combined_source_rows(source_dirs: list[Path], table_name: str) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    fieldnames: list[str] = []
    for source_dir in source_dirs:
        path = source_dir / table_name
        for row in _read_csv(path):
            enriched = {
                "source_semester": source_dir.parent.name,
                "source_schedule": source_dir.name,
                **row,
            }
            rows.append(enriched)
            for key in enriched:
                if key not in fieldnames:
                    fieldnames.append(key)
    return rows, fieldnames


def _combined_classrooms(source_dirs: list[Path]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    raw_sources: dict[str, set[str]] = defaultdict(set)
    for source_dir in source_dirs:
        for row in _read_csv(source_dir / "classrooms.csv"):
            classroom_name = _clean(row.get("classroom_name"))
            if not classroom_name:
                continue
            if classroom_name not in merged:
                merged[classroom_name] = {
                    "classroom_name": classroom_name,
                    "classroom_type": _clean(row.get("classroom_type")) or "普通教室",
                    "capacity": _clean(row.get("capacity")) or "120",
                    "status": _clean(row.get("status")) or "ACTIVE",
                    "raw_source": "",
                }
            elif _clean(row.get("classroom_type")) == "机房":
                merged[classroom_name]["classroom_type"] = "机房"
            raw_source = _clean(row.get("raw_source"))
            if raw_source:
                raw_sources[classroom_name].update(item for item in raw_source.split("+") if item)
    for classroom_name, row in merged.items():
        row["raw_source"] = "+".join(sorted(raw_sources.get(classroom_name, set())))
    return [merged[key] for key in sorted(merged)]


def _combined_teachers(source_dirs: list[Path]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    raw_sources: dict[str, set[str]] = defaultdict(set)
    for source_dir in source_dirs:
        for row in _read_csv(source_dir / "teachers.csv"):
            teacher_name = _clean(row.get("teacher_name"))
            if not teacher_name:
                continue
            if teacher_name not in merged:
                merged[teacher_name] = {
                    "teacher_name": teacher_name,
                    "department": _clean(row.get("department")),
                    "title": _clean(row.get("title")),
                    "raw_source": "",
                }
            else:
                _merge_first_non_empty(merged[teacher_name], row, "department")
                _merge_first_non_empty(merged[teacher_name], row, "title")
            raw_source = _clean(row.get("raw_source"))
            if raw_source:
                raw_sources[teacher_name].add(raw_source)
    for teacher_name, row in merged.items():
        row["raw_source"] = " | ".join(sorted(raw_sources.get(teacher_name, set())))
    return [merged[key] for key in sorted(merged)]


def _merge_first_non_empty(target: dict[str, Any], source: dict[str, Any], key: str) -> None:
    if not _clean(target.get(key)) and _clean(source.get(key)):
        target[key] = _clean(source.get(key))


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


def _slugify(value: str) -> str:
    text = re.sub(r"\s+", "", value)
    text = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", text)
    return text.strip("_") or "semester"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build combined historical timetable training CSV/JSONL.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    report = build_history_training_dataset(
        input_root=Path(args.input_root),
        output_root=Path(args.output_root),
        fail_fast=args.fail_fast,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
