"""Validate iterative template cover v1."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scheduler.template_cover_v1 import DEFAULT_OUTPUT_PATH

DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_PATH.parent / "template_cover_v1_validation_report.json"


def validate_cover(*, cover_path: Path = DEFAULT_OUTPUT_PATH, report_path: Path = DEFAULT_REPORT_PATH) -> dict[str, Any]:
    cover = json.loads(cover_path.read_text(encoding="utf-8"))
    templates = cover.get("templates", [])
    issues: list[dict[str, Any]] = []
    template_summaries = []
    for template in templates:
        fragments = template.get("fragments", [])
        template_issues = []
        template_issues.extend(_occupancy_conflicts(fragments, "teacher_name", "teacher_conflict"))
        template_issues.extend(_class_occupancy_conflicts(fragments))
        template_issues.extend(_occupancy_conflicts(fragments, "classroom_name", "room_conflict"))
        template_issues.extend(_segment_boundary_issues(fragments))
        template_issues.extend(_fragment_hour_issues(fragments))
        for issue in template_issues:
            issue["template_id"] = template.get("template_id")
        issues.extend(template_issues)
        template_summaries.append({
            "template_id": template.get("template_id"),
            "fragment_count": len(fragments),
            "task_count": len({fragment.get("source_key") for fragment in fragments}),
            "issue_count": len(template_issues),
        })

    all_fragments = [fragment for template in templates for fragment in template.get("fragments", [])]
    issue_counts = dict(Counter(issue["issue"] for issue in issues).most_common())
    hard_issue_types = {"teacher_conflict", "class_conflict", "room_conflict", "invalid_segment_boundary", "invalid_fragment_hours"}
    report = {
        "cover_id": cover.get("cover_id"),
        "template_count": len(templates),
        "fragment_count": len(all_fragments),
        "task_count": len({fragment.get("source_key") for fragment in all_fragments}),
        "issue_count": len(issues),
        "hard_conflict_count": sum(count for issue, count in issue_counts.items() if issue in hard_issue_types),
        "issue_counts": issue_counts,
        "conflict_summary": {
            "hard_conflict_count": sum(count for issue, count in issue_counts.items() if issue in hard_issue_types),
            "teacher_groups": issue_counts.get("teacher_conflict", 0),
            "class_groups": issue_counts.get("class_conflict", 0),
            "room_groups": issue_counts.get("room_conflict", 0),
            "segment_boundary_issues": issue_counts.get("invalid_segment_boundary", 0),
            "hour_issues": issue_counts.get("invalid_fragment_hours", 0),
        },
        "templates": template_summaries,
        "issues_preview": issues[:80],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


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


def _segment_boundary_issues(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for fragment in fragments:
        consecutive_slots = _safe_int(fragment.get("consecutive_slots"))
        period_index = _safe_int(fragment.get("period_index"))
        if consecutive_slots > 1 and period_index > 0 and (period_index - 1) % consecutive_slots != 0:
            issues.append({
                "issue": "invalid_segment_boundary",
                "fragment_id": fragment.get("fragment_id"),
                "source_key": fragment.get("source_key"),
                "day_of_week": fragment.get("day_of_week"),
                "period_index": period_index,
                "consecutive_slots": consecutive_slots,
            })
    return issues


def _fragment_hour_issues(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    for fragment in fragments:
        duration_weeks = _safe_int(fragment.get("duration_weeks"))
        session_hours = _safe_int(fragment.get("session_hours"))
        covered_hours = _safe_int(fragment.get("covered_hours"))
        expected = duration_weeks * session_hours
        if expected <= 0 or covered_hours != expected:
            issues.append({
                "issue": "invalid_fragment_hours",
                "fragment_id": fragment.get("fragment_id"),
                "source_key": fragment.get("source_key"),
                "duration_weeks": duration_weeks,
                "session_hours": session_hours,
                "covered_hours": covered_hours,
                "expected_covered_hours": expected,
            })
    return issues


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
    parser = argparse.ArgumentParser(description="Validate V3.5 template cover v1.")
    parser.add_argument("--cover", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    report = validate_cover(cover_path=Path(args.cover), report_path=Path(args.report))
    print(json.dumps({k: v for k, v in report.items() if k != "issues_preview"}, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
