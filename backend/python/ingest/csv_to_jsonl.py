"""Convert CSV files to JSONL.

Useful after parse_schedule_excel.py:
- CSV remains human-readable/reviewable.
- JSONL is easier for LLM classification and later import pipelines.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def convert_csv_to_jsonl(*, input_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    if input_path.suffix.lower() != ".csv":
        raise SystemExit(f"input must be a .csv file: {input_path}")
    output_path = output_path or input_path.with_suffix(".jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with input_path.open("r", encoding="utf-8-sig", newline="") as source, output_path.open("w", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        for row in reader:
            row_count += 1
            target.write(json.dumps(_normalize_row(row), ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "status": "ok",
        "input": str(input_path),
        "output": str(output_path),
        "row_count": row_count,
    }


DEFAULT_IMPORT_CSV_NAMES = {
    "courses.csv",
    "teachers.csv",
    "classrooms.csv",
    "class_groups.csv",
    "teaching_tasks.csv",
    "timetable_occurrences.csv",
}


def convert_dir(*, input_dir: Path, output_dir: Path | None = None, include_all: bool = False) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")
    output_dir = output_dir or input_dir
    results = []
    csv_paths = sorted(input_dir.glob("*.csv"))
    if not include_all:
        csv_paths = [path for path in csv_paths if path.name in DEFAULT_IMPORT_CSV_NAMES]
    for csv_path in csv_paths:
        output_path = output_dir / f"{csv_path.stem}.jsonl"
        results.append(convert_csv_to_jsonl(input_path=csv_path, output_path=output_path))
    return {
        "status": "ok",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "file_count": len(results),
        "total_rows": sum(item["row_count"] for item in results),
        "files": results,
    }


def _normalize_row(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        result[normalized_key] = _normalize_value(value)
    return result


def _normalize_value(value: str) -> Any:
    text = str(value or "").strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert CSV file(s) to JSONL.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="One CSV file")
    group.add_argument("--input-dir", help="Directory containing CSV files")
    parser.add_argument("--output", help="Output JSONL path when using --input")
    parser.add_argument("--output-dir", help="Output directory when using --input-dir")
    parser.add_argument("--include-all", action="store_true", help="When using --input-dir, convert every CSV instead of only schedule import CSVs")
    args = parser.parse_args()

    if args.input:
        result = convert_csv_to_jsonl(
            input_path=Path(args.input),
            output_path=Path(args.output) if args.output else None,
        )
    else:
        result = convert_dir(
            input_dir=Path(args.input_dir),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            include_all=args.include_all,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
