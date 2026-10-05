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
    fragment_weeks = _read_jsonl(input_dir / "schedule_template_fragment_weeks.jsonl")
    slots = _read_jsonl(input_dir / "schedule_template_fragment_slots.jsonl")
    fragment_teachers = _read_jsonl_if_exists(input_dir / "schedule_template_fragment_teachers.jsonl")
    fragment_class_groups = _read_jsonl_if_exists(input_dir / "schedule_template_fragment_class_groups.jsonl")
    satisfaction = _read_jsonl_if_exists(input_dir / "schedule_teacher_satisfaction.jsonl")
    export_report = _read_json_if_exists(input_dir / "export_report.json")

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
    issues.extend(_missing_refs(fragment_weeks, "template_fragment_week", "template_fragment_id", fragment_ids))
    issues.extend(_missing_refs(fragment_weeks, "template_fragment_week", "template_id", template_ids))
    issues.extend(_missing_refs(slots, "template_fragment_slot", "fragment_code", fragment_codes))
    issues.extend(_missing_refs(fragment_teachers, "template_fragment_teacher", "template_fragment_id", fragment_ids))
    issues.extend(_missing_refs(fragment_teachers, "template_fragment_teacher", "fragment_code", fragment_codes))
    issues.extend(_missing_refs(fragment_class_groups, "template_fragment_class_group", "template_fragment_id", fragment_ids))
    issues.extend(_missing_refs(fragment_class_groups, "template_fragment_class_group", "fragment_code", fragment_codes))
    issues.extend(_fragment_slot_count_issues(fragments, slots))
    issues.extend(_week_mapping_issues(weeks))
    issues.extend(_fragment_week_issues(fragment_weeks, weeks, fragment_ids))
    issues.extend(_relation_issues(fragment_teachers, "teacher_id", "fragment_teacher"))
    issues.extend(_relation_issues(fragment_class_groups, "class_group_id", "fragment_class_group"))
    # 满足度行的唯一键是 (template_code, teacher_key)：这里放过去，导入端会因为
    # UNIQUE 约束整批失败，所以在草案校验这关就拦住。
    issues.extend(_missing_refs(satisfaction, "teacher_satisfaction", "template_code", template_codes))
    issues.extend(_satisfaction_issues(satisfaction))
    identity_resolution = export_report.get("identity_resolution") or {}
    if identity_resolution.get("required"):
        issues.extend(identity_resolution.get("issues_preview") or [])
        issue_count = int(identity_resolution.get("issue_count") or 0)
        preview_count = len(identity_resolution.get("issues_preview") or [])
        if issue_count > preview_count:
            issues.append({
                "issue": "additional_identity_resolution_issues",
                "count": issue_count - preview_count,
            })

    report = {
        "input_dir": str(input_dir),
        "counts": {
            "templates": len(templates),
            "template_weeks": len(weeks),
            "template_fragments": len(fragments),
            "template_fragment_weeks": len(fragment_weeks),
            "template_fragment_slots": len(slots),
            "template_fragment_teachers": len(fragment_teachers),
            "template_fragment_class_groups": len(fragment_class_groups),
            "teacher_satisfaction": len(satisfaction),
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


def _fragment_week_issues(
    fragment_weeks: list[dict[str, Any]],
    template_weeks: list[dict[str, Any]],
    fragment_ids: set[Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    mapped = {
        (_safe_int(row.get("template_id")), _safe_int(row.get("week_number")))
        for row in template_weeks
    }
    seen: set[tuple[int, int]] = set()
    covered_fragments: set[int] = set()
    for index, row in enumerate(fragment_weeks, start=1):
        fragment_id = _safe_int(row.get("template_fragment_id"))
        template_id = _safe_int(row.get("template_id"))
        week_number = _safe_int(row.get("week_number"))
        key = (fragment_id, week_number)
        if week_number < 1 or week_number > 52:
            issues.append({"issue": "invalid_fragment_week", "row_index": index, "week_number": week_number})
        if key in seen:
            issues.append({"issue": "duplicate_fragment_week", "row_index": index, "value": key})
        if (template_id, week_number) not in mapped:
            issues.append({
                "issue": "fragment_week_not_mapped_to_template",
                "row_index": index,
                "template_id": template_id,
                "week_number": week_number,
            })
        seen.add(key)
        covered_fragments.add(fragment_id)
    for fragment_id in sorted(_safe_int(value) for value in fragment_ids):
        if fragment_id not in covered_fragments:
            issues.append({"issue": "fragment_without_active_week", "fragment_id": fragment_id})
    return issues


def _relation_issues(rows: list[dict[str, Any]], identity_field: str, row_type: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for index, row in enumerate(rows, start=1):
        identity = row.get(identity_field)
        if identity is None:
            issues.append({"issue": "missing_stable_id", "row_type": row_type, "row_index": index, "field": identity_field})
            continue
        key = (row.get("template_fragment_id"), identity)
        if key in seen:
            issues.append({"issue": "duplicate_fragment_relation", "row_type": row_type, "row_index": index, "value": key})
        seen.add(key)
    return issues


def _satisfaction_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for index, row in enumerate(rows, start=1):
        key = (row.get("template_code"), row.get("teacher_key"))
        if key in seen:
            issues.append({"issue": "duplicate_teacher_satisfaction", "row_index": index, "value": list(key)})
        seen.add(key)
        if not str(row.get("teacher_name") or "").strip():
            issues.append({"issue": "missing_teacher_name", "row_index": index})
        for field in ("satisfaction_score", "preference_score"):
            value = row.get(field)
            if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                issues.append({"issue": "score_out_of_range", "row_index": index, "field": field, "value": value})
        if _safe_int(row.get("item_count")) <= 0:
            issues.append({"issue": "non_positive_item_count", "row_index": index, "value": row.get("item_count")})
        if _safe_int(row.get("low_satisfaction")) not in (0, 1):
            issues.append({"issue": "invalid_low_satisfaction_flag", "row_index": index, "value": row.get("low_satisfaction")})
    return issues


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_jsonl_if_exists(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(path) if path.exists() else []


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


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
