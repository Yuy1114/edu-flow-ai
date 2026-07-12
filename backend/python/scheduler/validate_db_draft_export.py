"""Validate V3.5 DB dry-run JSONL export."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scheduler.export_template_cover_db_draft import DEFAULT_OUTPUT_DIR

DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "validation_report.json"


def validate_export(*, input_dir: Path = DEFAULT_OUTPUT_DIR, report_path: Path = DEFAULT_REPORT_PATH) -> dict[str, Any]:
    templates = _read_jsonl(input_dir / "schedule_templates.jsonl")
    weeks = _read_jsonl(input_dir / "schedule_template_weeks.jsonl")
    fragments = _read_jsonl(input_dir / "schedule_template_fragments.jsonl")
    slots = _read_jsonl(input_dir / "schedule_template_fragment_slots.jsonl")

    issues: list[dict[str, Any]] = []
    template_ids = {row["id"] for row in templates}
    template_codes = {row["template_code"] for row in templates}
    fragment_ids = {row["id"] for row in fragments}
    fragment_codes = {row["fragment_code"] for row in fragments}

    issues.extend(_missing_refs(weeks, "template_week", "template_id", template_ids))
    issues.extend(_missing_refs(weeks, "template_week", "template_code", template_codes))
    issues.extend(_missing_refs(fragments, "template_fragment", "template_id", template_ids))
    issues.extend(_missing_refs(fragments, "template_fragment", "template_code", template_codes))
    issues.extend(_missing_refs(slots, "template_fragment_slot", "template_fragment_id", fragment_ids))
    issues.extend(_missing_refs(slots, "template_fragment_slot", "fragment_code", fragment_codes))
    issues.extend(_fragment_slot_count_issues(fragments, slots))
    issues.extend(_week_mapping_issues(weeks))

    report = {
        "input_dir": str(input_dir),
        "counts": {
            "templates": len(templates),
            "template_weeks": len(weeks),
            "template_fragments": len(fragments),
            "template_fragment_slots": len(slots),
        },
        "issue_count": len(issues),
        "issue_counts": dict(Counter(issue["issue"] for issue in issues).most_common()),
        "issues_preview": issues[:80],
        "week_mapping": [
            {"week_number": row.get("week_number"), "template_code": row.get("template_code")}
            for row in sorted(weeks, key=lambda item: _safe_int(item.get("week_number")))
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _missing_refs(rows: list[dict[str, Any]], row_type: str, field: str, valid_values: set[Any]) -> list[dict[str, Any]]:
    issues = []
    for index, row in enumerate(rows, start=1):
        if row.get(field) not in valid_values:
            issues.append({"issue": "missing_reference", "row_type": row_type, "row_index": index, "field": field, "value": row.get(field)})
    return issues


def _fragment_slot_count_issues(fragments: list[dict[str, Any]], slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slot_counts: dict[int, int] = defaultdict(int)
    for slot in slots:
        slot_counts[_safe_int(slot.get("template_fragment_id"))] += 1
    issues = []
    for fragment in fragments:
        fragment_id = _safe_int(fragment.get("id"))
        expected = _safe_int(fragment.get("consecutive_slots"))
        actual = slot_counts.get(fragment_id, 0)
        if actual != expected:
            issues.append({
                "issue": "fragment_slot_count_mismatch",
                "fragment_id": fragment_id,
                "fragment_code": fragment.get("fragment_code"),
                "expected": expected,
                "actual": actual,
            })
    return issues


def _week_mapping_issues(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    week_numbers = [_safe_int(row.get("week_number")) for row in weeks]
    duplicates = [week for week, count in Counter(week_numbers).items() if count > 1]
    for week in duplicates:
        issues.append({"issue": "duplicate_week_mapping", "week_number": week})
    if week_numbers and sorted(week_numbers) != list(range(1, max(week_numbers) + 1)):
        issues.append({"issue": "week_mapping_not_contiguous", "week_numbers": sorted(week_numbers)})
    return issues


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V3.5 DB dry-run JSONL export.")
    parser.add_argument("--input-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    report = validate_export(input_dir=Path(args.input_dir), report_path=Path(args.report))
    print(json.dumps({k: v for k, v in report.items() if k != "issues_preview"}, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
