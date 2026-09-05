"""Validate V3.5 weekly task patterns."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scheduler.pattern_builder import DEFAULT_OUTPUT_PATH

DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_PATH.parent / "pattern_validation_report.json"


def validate(*, input_path: Path = DEFAULT_OUTPUT_PATH, report_path: Path = DEFAULT_REPORT_PATH) -> dict[str, Any]:
    patterns = _read_jsonl(input_path)
    issues: list[dict[str, Any]] = []

    for pattern in patterns:
        source_key = str(pattern.get("source_key") or "")
        issue_codes = _issues(pattern)
        if issue_codes:
            issues.append({"source_key": source_key, "issues": issue_codes, "pattern": pattern})

    report = {
        "pattern_count": len(patterns),
        "valid_count": len(patterns) - len(issues),
        "invalid_count": len(issues),
        "issue_counts": dict(Counter(issue for item in issues for issue in item["issues"]).most_common()),
        "distribution": _distribution(patterns),
        "invalid_preview": issues[:50],
        "preview": patterns[:20],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _issues(pattern: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    course_type = str(pattern.get("course_type") or "")
    weekly_slot_count = _safe_int(pattern.get("weekly_slot_count"))
    duration_weeks = _safe_int(pattern.get("duration_weeks"))
    consecutive_slots = _safe_int(pattern.get("consecutive_slots"))
    observed_week_count = _safe_int(pattern.get("observed_week_count"))
    week_mask = pattern.get("week_mask") or []

    if weekly_slot_count <= 0:
        issues.append("weekly_slot_count_not_positive")
    if duration_weeks <= 0:
        issues.append("duration_weeks_not_positive")
    if duration_weeks > 18:
        issues.append("duration_weeks_gt_18")
    if consecutive_slots not in {2, 4}:
        issues.append("bad_consecutive_slots")
    if _is_four_period_course(course_type) and consecutive_slots != 4:
        issues.append("lab_not_consecutive_4")
    if not _is_four_period_course(course_type) and consecutive_slots != 2:
        issues.append("theory_not_consecutive_2")
    if observed_week_count > 0 and duration_weeks != observed_week_count and pattern.get("pattern_source") == "observed_history":
        issues.append("duration_weeks_mismatch_observed")
    if len(week_mask) != duration_weeks:
        issues.append("week_mask_size_mismatch")
    if any(_safe_int(week) <= 0 or _safe_int(week) > 18 for week in week_mask):
        issues.append("week_mask_out_of_range")
    return issues


def _distribution(patterns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pattern_source": _counts(patterns, "pattern_source"),
        "course_type": _counts(patterns, "course_type"),
        "required_room_type": _counts(patterns, "required_room_type"),
        "weekly_slot_count": _counts(patterns, "weekly_slot_count"),
        "duration_weeks": _counts(patterns, "duration_weeks"),
        "consecutive_slots": _counts(patterns, "consecutive_slots"),
        "estimated_total_hours": _counts(patterns, "estimated_total_hours", limit=30),
    }


def _counts(patterns: list[dict[str, Any]], key: str, *, limit: int | None = None) -> dict[str, int]:
    counter = Counter(str(pattern.get(key)) for pattern in patterns)
    items = counter.most_common(limit)
    return dict(items)


def _is_four_period_course(course_type: str) -> bool:
    return course_type in {"上机课", "实验课"}


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V3.5 weekly task patterns.")
    parser.add_argument("--input", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    report = validate(input_path=Path(args.input), report_path=Path(args.report))
    print(json.dumps({k: v for k, v in report.items() if k not in {"preview", "invalid_preview"}}, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
