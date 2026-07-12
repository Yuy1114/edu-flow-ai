"""Build a cleaned timetable dataset from the held-out test schedules."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ingest.build_history_training_dataset import _slugify, _write_combined_tables
from ingest.csv_to_jsonl import convert_dir
from ingest.parse_schedule_excel import parse_schedule_excel

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = BACKEND_ROOT / "data" / "raw" / "2025-2026学年2学期总课表"
DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "data" / "parsed" / "test_schedule_dataset"


def build_test_schedule_dataset(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    semester_name: str | None = None,
    fail_fast: bool = False,
) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")

    semester_name = semester_name or input_dir.name
    semester_key = _slugify(semester_name)
    output_root.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in input_dir.rglob("*") if path.suffix.lower() in {".xls", ".xlsx"})
    items: list[dict[str, Any]] = []
    parsed_dirs_by_quality: dict[str, list[Path]] = defaultdict(list)
    status_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    parse_counts: Counter[str] = Counter()

    print(f"处理测试学期 {semester_name}: {len(files)} 个课表", flush=True)
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
                "semester": semester_name,
                "semester_key": semester_key,
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "counts": report.get("counts", {}),
                "quality": quality,
            })
        except Exception as exc:  # noqa: BLE001 - keep batch inspectable
            items.append({
                "status": "failed",
                "semester": semester_name,
                "semester_key": semester_key,
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            if fail_fast:
                raise

    combined_dir = output_root / "_combined"
    review_combined_dir = output_root / "_review_needed"
    combined_files = _write_combined_tables(parsed_dirs_by_quality["accepted"], combined_dir)
    review_combined_files = _write_combined_tables(parsed_dirs_by_quality["review_needed"], review_combined_dir)

    report = {
        "status": "ok" if all(item["status"] == "ok" for item in items) else "failed",
        "version": "test-schedule-dataset-v1",
        "input_dir": str(input_dir),
        "output_root": str(output_root),
        "semester": semester_name,
        "semester_key": semester_key,
        "combined_dir": str(combined_dir),
        "review_combined_dir": str(review_combined_dir),
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
    (output_root / "test_schedule_dataset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cleaned CSV/JSONL from held-out test schedules.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--semester-name", default=None)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    report = build_test_schedule_dataset(
        input_dir=Path(args.input_dir),
        output_root=Path(args.output_root),
        semester_name=args.semester_name,
        fail_fast=args.fail_fast,
    )
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
