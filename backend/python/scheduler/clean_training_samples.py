"""Clean V3.5 placement training samples and export JSONL.

The source CSV is timetable-derived real scheduling history, but it may contain
virtual rooms, placeholder rooms, empty rooms, and other records that are useful
for historical analysis but harmful for placement model training.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scheduler.paths import DATA_PATH, MODELS_DIR

DEFAULT_OUTPUT_PATH = MODELS_DIR / "clean_training_samples.jsonl"
DEFAULT_DROPPED_PATH = MODELS_DIR / "dropped_training_samples.jsonl"
DEFAULT_REPORT_PATH = MODELS_DIR / "clean_training_report.json"

ALLOWED_COURSE_TYPES = {"理论课", "上机课"}
ALLOWED_ROOM_TYPES = {"普通教室", "机房"}
REQUIRED_FIELDS = [
    "source_key",
    "resource_key",
    "course_name",
    "course_code",
    "class_name",
    "required_room_type",
    "classroom_name",
    "classroom_type",
    "day_of_week",
    "period_index",
]


def clean(
    *,
    input_path: Path = DATA_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    dropped_path: Path = DEFAULT_DROPPED_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    rows = _read_csv(input_path)
    clean_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    drop_reasons: Counter[str] = Counter()

    seen_source_resource: set[tuple[str, str]] = set()
    for row in rows:
        normalized = _normalize(row)
        reasons = _drop_reasons(normalized)
        dedupe_key = (normalized["source_key"], normalized["resource_key"])
        if not reasons and dedupe_key in seen_source_resource:
            reasons.append("duplicate_source_resource")
        if reasons:
            dropped = dict(normalized)
            dropped["drop_reasons"] = reasons
            dropped_rows.append(dropped)
            drop_reasons.update(reasons)
            continue
        seen_source_resource.add(dedupe_key)
        clean_rows.append(normalized)

    clean_rows.sort(key=lambda item: (item["source_key"], item["resource_key"]))
    dropped_rows.sort(key=lambda item: (item["source_key"], item["resource_key"]))

    _write_jsonl(output_path, clean_rows)
    _write_jsonl(dropped_path, dropped_rows)

    report = _build_report(rows, clean_rows, dropped_rows, drop_reasons)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: _strip(row.get(key)) for key in row.keys()}
    day = _safe_int(result.get("day_of_week"))
    period = _safe_int(result.get("period_index"))
    room = result.get("classroom_name", "")
    result["day_of_week"] = day
    result["period_index"] = period
    result["class_grade"] = _safe_int(result.get("class_grade"))
    result["class_no"] = _safe_int(result.get("class_no"))
    result["student_count"] = _safe_int(result.get("student_count"))
    result["total_hours"] = _safe_float(result.get("total_hours"))
    result["classroom_capacity"] = _safe_int(result.get("classroom_capacity"))
    result["slot_label"] = f"{day}|{period}" if day > 0 and period > 0 else ""
    result["resource_key"] = f"{room}|{day}|{period}" if room and day > 0 and period > 0 else result.get("resource_key", "")
    return result


def _drop_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    room = str(row.get("classroom_name") or "").strip()
    room_lower = room.lower()
    course_type = str(row.get("course_type") or "").strip()
    room_type = str(row.get("classroom_type") or "").strip()
    required_room_type = str(row.get("required_room_type") or "").strip()

    for field in REQUIRED_FIELDS:
        if row.get(field) in (None, "", 0) and field not in {"day_of_week", "period_index"}:
            reasons.append(f"missing_{field}")
    if _safe_int(row.get("day_of_week")) <= 0:
        reasons.append("invalid_day_of_week")
    if _safe_int(row.get("period_index")) <= 0:
        reasons.append("invalid_period_index")
    if _safe_int(row.get("day_of_week")) > 7:
        reasons.append("invalid_day_of_week")
    if _safe_int(row.get("period_index")) > 5:
        reasons.append("invalid_period_index")

    if not room:
        reasons.append("empty_room")
    if room_lower.startswith("xn"):
        reasons.append("placeholder_xn_room")
    if room.startswith("虚拟") or "虚拟" in room:
        reasons.append("virtual_room")
    if "操场" in room or "体育" in room:
        reasons.append("sports_room")
    if room in ("未排地点", "待定", "待分配", "无"):
        reasons.append("placeholder_room_name")
    if course_type not in ALLOWED_COURSE_TYPES:
        reasons.append("unsupported_course_type")
    if room_type not in ALLOWED_ROOM_TYPES:
        reasons.append("unsupported_room_type")
    if required_room_type and room_type and required_room_type != room_type:
        reasons.append("room_type_mismatch")
    return sorted(set(reasons))


def _build_report(
    raw_rows: list[dict[str, Any]],
    clean_rows: list[dict[str, Any]],
    dropped_rows: list[dict[str, Any]],
    drop_reasons: Counter[str],
) -> dict[str, Any]:
    return {
        "counts": {
            "raw_rows": len(raw_rows),
            "clean_rows": len(clean_rows),
            "dropped_rows": len(dropped_rows),
            "drop_rate": round(len(dropped_rows) / max(1, len(raw_rows)), 6),
            "source_key_count": len({row["source_key"] for row in clean_rows}),
            "resource_key_count": len({row["resource_key"] for row in clean_rows}),
            "slot_count": len({row["slot_label"] for row in clean_rows}),
            "room_count": len({row["classroom_name"] for row in clean_rows}),
        },
        "drop_reasons": dict(drop_reasons.most_common()),
        "clean_distribution": {
            "course_type": dict(Counter(row["course_type"] for row in clean_rows).most_common()),
            "required_room_type": dict(Counter(row["required_room_type"] for row in clean_rows).most_common()),
            "classroom_type": dict(Counter(row["classroom_type"] for row in clean_rows).most_common()),
            "slot_label_top20": dict(Counter(row["slot_label"] for row in clean_rows).most_common(20)),
            "room_top20": dict(Counter(row["classroom_name"] for row in clean_rows).most_common(20)),
        },
        "dropped_preview": dropped_rows[:30],
        "clean_preview": clean_rows[:30],
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _strip(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
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
    parser = argparse.ArgumentParser(description="Clean V3.5 placement training samples into JSONL.")
    parser.add_argument("--input", default=str(DATA_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--dropped", default=str(DEFAULT_DROPPED_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    report = clean(
        input_path=Path(args.input),
        output_path=Path(args.output),
        dropped_path=Path(args.dropped),
        report_path=Path(args.report),
    )
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
    print("drop_reasons:")
    for reason, count in report["drop_reasons"].items():
        print(f"  {reason}: {count}")
    print(f"output: {args.output}")
    print(f"dropped: {args.dropped}")
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
