"""Build V3.5 weekly scheduling patterns from teaching-task-like samples.

Pattern answers: how many weekly placements a task needs, how long it lasts,
and whether each placement requires consecutive slots.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scheduler.paths import OUTPUT_DIR

DEFAULT_INPUT_PATH = OUTPUT_DIR / "clean_training_samples.jsonl"
DEFAULT_OUTPUT_PATH = OUTPUT_DIR / "task_patterns.jsonl"
DEFAULT_DROPPED_PATH = OUTPUT_DIR / "dropped_task_patterns.jsonl"
DEFAULT_REPORT_PATH = OUTPUT_DIR / "pattern_report.json"
MAX_WEEKLY_SLOT_COUNT = 6

THEORY_RULES: dict[int, tuple[int, int]] = {
    4: (1, 2),
    8: (1, 4),
    16: (1, 8),
    24: (2, 6),
    32: (2, 8),
    48: (3, 8),
    64: (4, 8),
}

LAB_RULES: dict[int, tuple[int, int]] = {
    8: (1, 2),
    16: (1, 4),
    24: (1, 6),
    32: (2, 4),
    48: (2, 6),
}


def build_patterns(
    *,
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    dropped_path: Path = DEFAULT_DROPPED_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    max_weekly_slot_count: int = MAX_WEEKLY_SLOT_COUNT,
) -> dict[str, Any]:
    rows = _read_jsonl(input_path)
    grouped = _group_by_source(rows)
    raw_patterns = [_build_pattern(source_key, group) for source_key, group in sorted(grouped.items())]
    patterns: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for pattern in raw_patterns:
        if _safe_int(pattern.get("weekly_slot_count")) > max_weekly_slot_count:
            dropped_pattern = dict(pattern)
            dropped_pattern["drop_reason"] = "irregular_high_weekly_slot_count"
            dropped.append(dropped_pattern)
        else:
            patterns.append(pattern)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_path, patterns)
    _write_jsonl(dropped_path, dropped)

    report = _build_report(patterns, dropped=dropped, raw_count=len(raw_patterns), max_weekly_slot_count=max_weekly_slot_count)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _build_pattern(source_key: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    course_type = str(first.get("course_type") or "").strip()
    required_room_type = str(first.get("required_room_type") or "").strip()
    total_hours = _safe_int(first.get("total_hours"))
    observed_slots = sorted({str(row.get("slot_label") or "") for row in rows if row.get("slot_label")})
    observed_weeks = sorted({week for row in rows for week in _parse_weeks(row.get("observed_weeks"))})
    observed_slot_units = sum(max(1, len(_parse_weeks(row.get("observed_weeks")))) for row in rows)
    consecutive_slots = _consecutive_slots(course_type, required_room_type)

    explicit_sessions = _safe_int(first.get("sessions_per_week"))
    explicit_weeks = _safe_int(first.get("duration_weeks"))
    if explicit_sessions > 0 and explicit_weeks > 0:
        # 教学任务显式指定的课时排布优先; 入库关卡已校验 次数×周数×每次课时==总课时
        weekly_slot_count, duration_weeks, source = explicit_sessions, explicit_weeks, "explicit"
    elif total_hours > 0:
        weekly_slot_count, duration_weeks, source = _pattern_from_hours(total_hours, course_type, required_room_type)
    else:
        duration_weeks = max(1, len(observed_weeks))
        avg_slot_units_per_week = max(1, round(observed_slot_units / duration_weeks))
        weekly_slot_count = max(1, round(avg_slot_units_per_week / consecutive_slots))
        source = "observed_history"
    session_hours = consecutive_slots * 2
    sessions_per_week = weekly_slot_count
    estimated_total_hours = duration_weeks * sessions_per_week * session_hours

    return {
        "source_key": source_key,
        "course_name": str(first.get("course_name") or ""),
        "course_code": str(first.get("course_code") or ""),
        "teacher_name": str(first.get("teacher_name") or ""),
        "class_name": str(first.get("class_name") or ""),
        "class_names": str(first.get("class_names") or first.get("class_group_names") or first.get("class_name") or ""),
        "teaching_task_id": first.get("teaching_task_id"),
        "course_type": course_type,
        "required_room_type": required_room_type,
        "total_hours": total_hours,
        "pattern_source": source,
        "session_hours": session_hours,
        "sessions_per_week": sessions_per_week,
        "weekly_slot_count": weekly_slot_count,
        "duration_weeks": duration_weeks,
        "consecutive_slots": consecutive_slots,
        "estimated_total_hours": estimated_total_hours,
        "observed_slot_count": len(observed_slots),
        "observed_slots": observed_slots,
        "observed_week_count": len(observed_weeks),
        "observed_weeks": observed_weeks,
        "week_mask": observed_weeks or list(range(1, duration_weeks + 1)),
    }


def _pattern_from_hours(total_hours: int, course_type: str, required_room_type: str) -> tuple[int, int, str]:
    rules = LAB_RULES if _is_lab(course_type, required_room_type) else THEORY_RULES
    if total_hours in rules:
        weekly_slot_count, duration_weeks = rules[total_hours]
        return weekly_slot_count, duration_weeks, "hours_rule"

    session_hours = 4 if _is_lab(course_type, required_room_type) else 2
    sessions = max(1, round(total_hours / session_hours))
    if sessions <= 8:
        weekly_slot_count = 1
    elif sessions <= 16:
        weekly_slot_count = 2
    else:
        weekly_slot_count = min(4, max(2, round(sessions / 8)))
    duration_weeks = max(1, min(16, round(sessions / weekly_slot_count)))
    return weekly_slot_count, duration_weeks, "hours_fallback"


def _consecutive_slots(course_type: str, required_room_type: str) -> int:
    return 2 if _is_lab(course_type, required_room_type) else 1


def _is_lab(course_type: str, required_room_type: str) -> bool:
    return course_type == "上机课" or required_room_type == "机房"


def _group_by_source(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source_key = str(row.get("source_key") or "").strip()
        if source_key:
            grouped[source_key].append(row)
    return grouped


def _build_report(
    patterns: list[dict[str, Any]],
    *,
    dropped: list[dict[str, Any]],
    raw_count: int,
    max_weekly_slot_count: int,
) -> dict[str, Any]:
    def counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for pattern in rows:
            value = str(pattern.get(key))
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items(), key=lambda item: (-item[1], item[0])))

    invalid = [pattern for pattern in patterns if _pattern_issue(pattern)]
    return {
        "raw_pattern_count": raw_count,
        "pattern_count": len(patterns),
        "dropped_count": len(dropped),
        "drop_rate": round(len(dropped) / max(1, raw_count), 6),
        "max_weekly_slot_count": max_weekly_slot_count,
        "drop_reason_counts": counts(dropped, "drop_reason"),
        "source_counts": counts(patterns, "pattern_source"),
        "course_type_counts": counts(patterns, "course_type"),
        "room_type_counts": counts(patterns, "required_room_type"),
        "weekly_slot_count_counts": counts(patterns, "weekly_slot_count"),
        "duration_weeks_counts": counts(patterns, "duration_weeks"),
        "consecutive_slots_counts": counts(patterns, "consecutive_slots"),
        "invalid_count": len(invalid),
        "invalid_preview": invalid[:30],
        "dropped_preview": dropped[:30],
        "preview": patterns[:30],
    }


def _pattern_issue(pattern: dict[str, Any]) -> str:
    if _safe_int(pattern.get("weekly_slot_count")) <= 0:
        return "invalid_weekly_slot_count"
    if _safe_int(pattern.get("duration_weeks")) <= 0:
        return "invalid_duration_weeks"
    if _safe_int(pattern.get("consecutive_slots")) not in {1, 2}:
        return "invalid_consecutive_slots"
    if _safe_int(pattern.get("duration_weeks")) > 18:
        return "duration_too_long"
    return ""


def _parse_weeks(value: Any) -> list[int]:
    result = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        week = _safe_int(part)
        if week > 0:
            result.append(week)
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build V3.5 weekly task patterns.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--dropped", default=str(DEFAULT_DROPPED_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--max-weekly-slot-count", type=int, default=MAX_WEEKLY_SLOT_COUNT)
    args = parser.parse_args()

    report = build_patterns(
        input_path=Path(args.input),
        output_path=Path(args.output),
        dropped_path=Path(args.dropped),
        report_path=Path(args.report),
        max_weekly_slot_count=args.max_weekly_slot_count,
    )
    print(json.dumps({k: v for k, v in report.items() if k not in {"preview", "invalid_preview", "dropped_preview"}}, ensure_ascii=False, indent=2))
    print(f"output: {args.output}")
    print(f"dropped: {args.dropped}")
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
