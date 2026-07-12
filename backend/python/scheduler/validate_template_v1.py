"""Validate V3.5 template v1 output."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scheduler.template_builder_v1 import DEFAULT_OUTPUT_PATH, DEFAULT_REPORT_PATH as TEMPLATE_REPORT_PATH

DEFAULT_VALIDATION_REPORT_PATH = DEFAULT_OUTPUT_PATH.parent / "template_v1_validation_report.json"


def validate_template(*, template_path: Path = DEFAULT_OUTPUT_PATH, report_path: Path = DEFAULT_VALIDATION_REPORT_PATH) -> dict[str, Any]:
    template = json.loads(template_path.read_text(encoding="utf-8"))
    fragments = template.get("fragments", [])
    issues: list[dict[str, Any]] = []

    issues.extend(_duplicate_fragment_ids(fragments))
    issues.extend(_segment_shape_issues(fragments))
    issues.extend(_occupancy_conflicts(fragments, "teacher_name", "teacher_conflict"))
    issues.extend(_class_occupancy_conflicts(fragments))
    issues.extend(_occupancy_conflicts(fragments, "classroom_name", "room_conflict"))

    report = {
        "template_id": template.get("template_id"),
        "fragment_count": len(fragments),
        "issue_count": len(issues),
        "issue_counts": dict(Counter(issue["issue"] for issue in issues).most_common()),
        "issues_preview": issues[:80],
        "distribution": {
            "day_period": dict(Counter(f"{fragment.get('day_of_week')}|{fragment.get('period_index')}" for fragment in fragments).most_common()),
            "consecutive_slots": dict(Counter(str(fragment.get("consecutive_slots")) for fragment in fragments).most_common()),
            "required_room_type": dict(Counter(str(fragment.get("required_room_type")) for fragment in fragments).most_common()),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _duplicate_fragment_ids(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(str(fragment.get("fragment_id")) for fragment in fragments)
    return [
        {"issue": "duplicate_fragment_id", "fragment_id": fragment_id, "count": count}
        for fragment_id, count in counter.items()
        if count > 1
    ]


def _segment_shape_issues(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for fragment in fragments:
        consecutive_slots = _safe_int(fragment.get("consecutive_slots"))
        segments = fragment.get("segments") or []
        if len(segments) != consecutive_slots:
            issues.append({"issue": "segment_count_mismatch", "fragment_id": fragment.get("fragment_id")})
            continue
        periods = sorted(_safe_int(segment.get("period_index")) for segment in segments)
        if periods and periods != list(range(periods[0], periods[0] + len(periods))):
            issues.append({"issue": "segments_not_consecutive", "fragment_id": fragment.get("fragment_id")})
        if any(period <= 0 or period > 5 for period in periods):
            issues.append({"issue": "segment_period_out_of_range", "fragment_id": fragment.get("fragment_id")})
    return issues


def _occupancy_conflicts(fragments: list[dict[str, Any]], field: str, issue: str) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for fragment in fragments:
        owner = str(fragment.get(field) or "").strip()
        if not owner:
            continue
        for segment in fragment.get("segments") or []:
            buckets[(owner, _safe_int(segment.get("day_of_week")), _safe_int(segment.get("period_index")))].append(fragment)
    issues = []
    for key, bucket in buckets.items():
        if len(bucket) <= 1:
            continue
        issues.append({
            "issue": issue,
            "key": f"{key[0]}|{key[1]}|{key[2]}",
            "count": len(bucket),
            "fragment_ids": [fragment.get("fragment_id") for fragment in bucket],
            "source_keys": [fragment.get("source_key") for fragment in bucket],
        })
    return sorted(issues, key=lambda item: item["count"], reverse=True)


def _class_occupancy_conflicts(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for fragment in fragments:
        class_names = _split_names(fragment.get("class_names") or fragment.get("class_group_names") or fragment.get("class_name"))
        for class_name in class_names:
            for segment in fragment.get("segments") or []:
                buckets[(class_name, _safe_int(segment.get("day_of_week")), _safe_int(segment.get("period_index")))].append(fragment)
    issues = []
    for key, bucket in buckets.items():
        if len(bucket) <= 1:
            continue
        issues.append({
            "issue": "class_conflict",
            "key": f"{key[0]}|{key[1]}|{key[2]}",
            "count": len(bucket),
            "fragment_ids": [fragment.get("fragment_id") for fragment in bucket],
            "source_keys": [fragment.get("source_key") for fragment in bucket],
        })
    return sorted(issues, key=lambda item: item["count"], reverse=True)


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _split_names(value: Any) -> list[str]:
    text = str(value or "").replace("，", ",").replace("、", ",").replace(";", ",").replace("|", ",")
    seen: set[str] = set()
    result: list[str] = []
    for item in text.split(","):
        name = item.strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V3.5 template v1.")
    parser.add_argument("--template", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_VALIDATION_REPORT_PATH))
    args = parser.parse_args()

    report = validate_template(template_path=Path(args.template), report_path=Path(args.report))
    print(json.dumps({k: v for k, v in report.items() if k != "issues_preview"}, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
