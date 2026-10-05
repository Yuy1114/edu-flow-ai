"""Export the absolute-week dynamic template cover into DB-ready JSONL files.

This script does not connect to MySQL. It converts the phase cover JSON into
rows shaped like the target database tables so the schema and data can be
reviewed before real insertion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scheduler.phase_scheduler import DEFAULT_OUTPUT_PATH as DEFAULT_COVER_PATH
from scheduler.teacher_preferences import template_satisfaction_rows

DEFAULT_OUTPUT_DIR = DEFAULT_COVER_PATH.parent / "db_draft"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "export_report.json"

ALGORITHM_VERSION = "v3.6-dynamic-week-cover-v2"


def export_db_draft(
    *,
    cover_path: Path = DEFAULT_COVER_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path | None = None,
    allocation_task_id: int = 1,
    total_weeks: int = 18,
    generation_run_id: str | None = None,
    task_source_path: Path | None = None,
    rooms_path: Path | None = None,
    profile_satisfaction_templates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cover = json.loads(cover_path.read_text(encoding="utf-8"))
    templates = cover.get("templates", [])
    generation_run_id = generation_run_id or str(cover.get("generation_run_id") or "default")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_path or output_dir / DEFAULT_REPORT_PATH.name
    report_path.parent.mkdir(parents=True, exist_ok=True)

    task_metadata = _load_task_metadata(task_source_path)
    room_id_by_name = _load_room_ids(rooms_path)

    template_rows: list[dict[str, Any]] = []
    week_rows: list[dict[str, Any]] = []
    fragment_rows: list[dict[str, Any]] = []
    fragment_week_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []
    fragment_teacher_rows: list[dict[str, Any]] = []
    fragment_class_group_rows: list[dict[str, Any]] = []
    identity_issues: list[dict[str, Any]] = []

    template_id_by_code: dict[str, int] = {}
    fragment_id = 1
    for template_index, template in enumerate(templates, start=1):
        template_code = str(template.get("template_id") or f"cover_v1_template_{template_index}")
        template_id = template_index
        template_id_by_code[template_code] = template_id
        fragments = template.get("fragments", [])
        template_rows.append({
            "id": template_id,
            "allocation_task_id": allocation_task_id,
            "generation_run_id": generation_run_id,
            "template_code": template_code,
            "template_name": f"动态周模板 {template_index}",
            "template_order": template_index,
            "source_type": "AUTO",
            "algorithm_version": ALGORITHM_VERSION,
            "status": "ACTIVE",
            "fragment_count": len(fragments),
            "task_count": len({fragment.get("source_key") for fragment in fragments}),
        })

        for fragment in fragments:
            fragment_code = str(fragment.get("fragment_id") or f"fragment_{fragment_id}")
            metadata = _metadata_for_fragment(fragment, task_metadata)
            identity = _fragment_identity(fragment, metadata, room_id_by_name)
            fragment_row = _fragment_row(
                fragment,
                fragment_id=fragment_id,
                fragment_code=fragment_code,
                template_id=template_id,
                template_code=template_code,
                allocation_task_id=allocation_task_id,
                generation_run_id=generation_run_id,
                identity=identity,
            )
            fragment_rows.append(fragment_row)
            fragment_teacher_rows.extend(_fragment_teacher_rows(
                fragment_id=fragment_id,
                fragment_code=fragment_code,
                template_id=template_id,
                template_code=template_code,
                allocation_task_id=allocation_task_id,
                generation_run_id=generation_run_id,
                teaching_task_id=fragment_row["teaching_task_id"],
                identity=identity,
            ))
            fragment_class_group_rows.extend(_fragment_class_group_rows(
                fragment_id=fragment_id,
                fragment_code=fragment_code,
                template_id=template_id,
                template_code=template_code,
                allocation_task_id=allocation_task_id,
                generation_run_id=generation_run_id,
                teaching_task_id=fragment_row["teaching_task_id"],
                identity=identity,
            ))
            identity_issues.extend(_identity_issues(
                fragment_code=fragment_code,
                identity=identity,
                required=task_source_path is not None or rooms_path is not None,
            ))
            for segment in fragment.get("segments") or []:
                slot_rows.append(_slot_row(
                    segment,
                    template_fragment_id=fragment_id,
                    fragment_code=fragment_code,
                    template_id=template_id,
                    template_code=template_code,
                    allocation_task_id=allocation_task_id,
                    generation_run_id=generation_run_id,
                    fragment=fragment,
                    identity=identity,
                ))
            fragment_id += 1

    if template_rows:
        explicit_weeks = [_int_list(template.get("week_numbers")) for template in templates]
        explicit_flat = [week for weeks in explicit_weeks for week in weeks]
        dynamic_mapping_required = (
            str(cover.get("cover_id") or "") == "dynamic_cover_v2"
            or any("week_numbers" in template for template in templates)
        )
        if dynamic_mapping_required:
            expected_weeks = list(range(1, total_weeks + 1))
            if sorted(explicit_flat) != expected_weeks:
                raise ValueError(
                    "dynamic cover week_numbers must map every semester week exactly once: "
                    f"expected={expected_weeks}, actual={sorted(explicit_flat)}"
                )
            mapping_note = "dynamic template mapping from explicit week_numbers"
            for template_row, weeks in zip(template_rows, explicit_weeks):
                for week_number in weeks:
                    week_rows.append(_week_row(
                        template_row=template_row,
                        week_number=week_number,
                        row_id=week_number,
                        allocation_task_id=allocation_task_id,
                        generation_run_id=generation_run_id,
                        notes=mapping_note,
                    ))
            week_rows.sort(key=lambda row: row["week_number"])
        else:
            # Only legacy artifacts without week_numbers may use sequential
            # week_budget fallback during the migration.
            budgets = [_safe_int(template.get("week_budget")) for template in templates]
            if sum(budgets) != total_weeks or any(b <= 0 for b in budgets):
                base = total_weeks // max(1, len(template_rows))
                budgets = [base] * len(template_rows)
                budgets[-1] += total_weeks - sum(budgets)
            mapping_note = "legacy phase mapping: " + ", ".join(
                f"{row['template_code']}×{budget}" for row, budget in zip(template_rows, budgets)
            )
            week_number = 1
            for template_row, budget in zip(template_rows, budgets):
                for _ in range(budget):
                    if week_number > total_weeks:
                        break
                    week_rows.append(_week_row(
                        template_row=template_row,
                        week_number=week_number,
                        row_id=week_number,
                        allocation_task_id=allocation_task_id,
                        generation_run_id=generation_run_id,
                        notes=mapping_note,
                    ))
                    week_number += 1

    mapped_weeks_by_template: dict[int, list[int]] = {}
    for week_row in week_rows:
        mapped_weeks_by_template.setdefault(_safe_int(week_row.get("template_id")), []).append(
            _safe_int(week_row.get("week_number"))
        )
    for mapped_weeks in mapped_weeks_by_template.values():
        mapped_weeks.sort()
    for fragment_row in fragment_rows:
        template_id = _safe_int(fragment_row.get("template_id"))
        mapped_weeks = mapped_weeks_by_template.get(template_id, [])
        # A logical semester fragment is copied into every dynamic template in
        # which it is active.  The template-local mask is therefore the
        # authoritative persistence scope; the full-semester week_mask remains
        # audit evidence and is only a compatibility fallback for old covers.
        explicit_weeks = (
            _int_list(fragment_row.get("template_week_mask"))
            or _int_list(fragment_row.get("week_mask"))
        )
        if explicit_weeks:
            unknown = sorted(set(explicit_weeks) - set(mapped_weeks))
            if unknown:
                raise ValueError(
                    "fragment active weeks must be mapped to its template: "
                    f"fragment={fragment_row.get('fragment_code')}, unknown={unknown}"
                )
            active_weeks = sorted(explicit_weeks)
        else:
            duration_weeks = _safe_int(fragment_row.get("duration_weeks"))
            active_weeks = mapped_weeks[:duration_weeks or len(mapped_weeks)]
        fragment_week_rows.extend({
            "template_fragment_id": fragment_row["id"],
            "allocation_task_id": allocation_task_id,
            "generation_run_id": generation_run_id,
            "template_id": template_id,
            "week_number": week_number,
        } for week_number in active_weeks)

    files = {
        "schedule_templates": output_dir / "schedule_templates.jsonl",
        "schedule_template_weeks": output_dir / "schedule_template_weeks.jsonl",
        "schedule_template_fragments": output_dir / "schedule_template_fragments.jsonl",
        "schedule_template_fragment_weeks": output_dir / "schedule_template_fragment_weeks.jsonl",
        "schedule_template_fragment_slots": output_dir / "schedule_template_fragment_slots.jsonl",
        "schedule_template_fragment_teachers": output_dir / "schedule_template_fragment_teachers.jsonl",
        "schedule_template_fragment_class_groups": output_dir / "schedule_template_fragment_class_groups.jsonl",
    }
    # 逐教师的画像满足度按模板落库：方案详情页要能直接读到"这个方案里谁不满意、为什么"，
    # 而不是每次打开页面都重算一遍（重算需要画像文件和整份 cover）。
    satisfaction_rows = template_satisfaction_rows(
        profile_satisfaction_templates or {},
        allocation_task_id=allocation_task_id,
        generation_run_id=generation_run_id,
    )
    if satisfaction_rows:
        files["schedule_teacher_satisfaction"] = output_dir / "schedule_teacher_satisfaction.jsonl"
    else:
        # 契约：一张表一个文件，即使没有画像也要有（空的），
        # 否则导入端会因为缺文件而无法保持"文件 ↔ 表"的对照。
        files["schedule_teacher_satisfaction"] = output_dir / "schedule_teacher_satisfaction.jsonl"
    _write_jsonl(files["schedule_templates"], template_rows)
    _write_jsonl(files["schedule_template_weeks"], week_rows)
    _write_jsonl(files["schedule_template_fragments"], fragment_rows)
    _write_jsonl(files["schedule_template_fragment_weeks"], fragment_week_rows)
    _write_jsonl(files["schedule_template_fragment_slots"], slot_rows)
    _write_jsonl(files["schedule_template_fragment_teachers"], fragment_teacher_rows)
    _write_jsonl(files["schedule_template_fragment_class_groups"], fragment_class_group_rows)
    _write_jsonl(files["schedule_teacher_satisfaction"], satisfaction_rows)

    report = {
        "allocation_task_id": allocation_task_id,
        "generation_run_id": generation_run_id,
        "total_weeks": total_weeks,
        "cover_path": str(cover_path),
        "output_dir": str(output_dir),
        "algorithm_version": ALGORITHM_VERSION,
        "counts": {
            "templates": len(template_rows),
            "template_weeks": len(week_rows),
            "template_fragments": len(fragment_rows),
            "template_fragment_weeks": len(fragment_week_rows),
            "template_fragment_slots": len(slot_rows),
            "template_fragment_teachers": len(fragment_teacher_rows),
            "template_fragment_class_groups": len(fragment_class_group_rows),
            "teacher_satisfaction": len(satisfaction_rows),
        },
        "identity_resolution": {
            "required": task_source_path is not None or rooms_path is not None,
            "task_source_path": str(task_source_path) if task_source_path else None,
            "rooms_path": str(rooms_path) if rooms_path else None,
            "issue_count": len(identity_issues),
            "issues_preview": identity_issues[:50],
        },
        "files": {key: str(path) for key, path in files.items()},
        "template_codes": list(template_id_by_code.keys()),
        "week_mapping_preview": week_rows[:18],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _fragment_row(
    fragment: dict[str, Any],
    *,
    fragment_id: int,
    fragment_code: str,
    template_id: int,
    template_code: str,
    allocation_task_id: int,
    generation_run_id: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    class_group_ids = identity["class_group_ids"]
    return {
        "id": fragment_id,
        "template_id": template_id,
        "template_code": template_code,
        "allocation_task_id": allocation_task_id,
        "generation_run_id": generation_run_id,
        "fragment_code": fragment_code,
        "teaching_task_id": _safe_int(fragment.get("teaching_task_id")) or None,
        "source_key": fragment.get("source_key"),
        "course_id": identity["course_id"],
        "course_name": fragment.get("course_name"),
        "teacher_id": identity["primary_teacher_id"],
        "teacher_name": fragment.get("teacher_name"),
        # The legacy scalar remains usable for a single-class task.  Multi-class
        # identity is represented losslessly by schedule_template_fragment_class_group.
        "class_group_id": class_group_ids[0] if len(class_group_ids) == 1 else None,
        "class_name": fragment.get("class_names") or fragment.get("class_group_names") or fragment.get("class_name"),
        "classroom_id": identity["classroom_id"],
        "classroom_name": fragment.get("classroom_name"),
        "day_of_week": _safe_int(fragment.get("day_of_week")),
        "period_index": _safe_int(fragment.get("period_index")),
        "consecutive_slots": _safe_int(fragment.get("consecutive_slots")),
        "duration_weeks": _safe_int(fragment.get("duration_weeks")) or None,
        "session_hours": _safe_int(fragment.get("session_hours")) or None,
        # Draft-only absolute-week evidence. The normalized DB expansion remains
        # schedule_template_week -> template, so the importer may ignore these.
        "week_mask": _int_list(fragment.get("week_mask")),
        "template_week_mask": _int_list(fragment.get("template_week_mask")),
        "required_room_type": fragment.get("required_room_type"),
        "source_type": "AUTO",
        "lock_status": "UNLOCKED",
        "score": _safe_float(fragment.get("score")),
        "candidate_rank": _safe_int(fragment.get("candidate_rank")),
    }


def _week_row(
    *,
    template_row: dict[str, Any],
    week_number: int,
    row_id: int,
    allocation_task_id: int,
    generation_run_id: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "id": row_id,
        "allocation_task_id": allocation_task_id,
        "generation_run_id": generation_run_id,
        "week_number": week_number,
        "template_id": template_row["id"],
        "template_code": template_row["template_code"],
        "source_type": "AUTO",
        "notes": notes,
    }


def _slot_row(
    segment: dict[str, Any],
    *,
    template_fragment_id: int,
    fragment_code: str,
    template_id: int,
    template_code: str,
    allocation_task_id: int,
    generation_run_id: str,
    fragment: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, Any]:
    class_group_ids = identity["class_group_ids"]
    return {
        "template_fragment_id": template_fragment_id,
        "fragment_code": fragment_code,
        "template_id": template_id,
        "template_code": template_code,
        "allocation_task_id": allocation_task_id,
        "generation_run_id": generation_run_id,
        "teaching_task_id": _safe_int(fragment.get("teaching_task_id")) or None,
        "classroom_id": identity["classroom_id"],
        "teacher_id": identity["primary_teacher_id"],
        "class_group_id": class_group_ids[0] if len(class_group_ids) == 1 else None,
        "source_key": fragment.get("source_key"),
        "classroom_name": fragment.get("classroom_name"),
        "teacher_name": fragment.get("teacher_name"),
        "class_name": fragment.get("class_names") or fragment.get("class_group_names") or fragment.get("class_name"),
        "day_of_week": _safe_int(segment.get("day_of_week")),
        "period_index": _safe_int(segment.get("period_index")),
    }


def _fragment_teacher_rows(
    *,
    fragment_id: int,
    fragment_code: str,
    template_id: int,
    template_code: str,
    allocation_task_id: int,
    generation_run_id: str,
    teaching_task_id: int | None,
    identity: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    primary = identity["primary_teacher_id"]
    assistant = identity["assistant_teacher_id"]
    if primary is not None:
        rows.append({
            "template_fragment_id": fragment_id,
            "fragment_code": fragment_code,
            "template_id": template_id,
            "template_code": template_code,
            "allocation_task_id": allocation_task_id,
            "generation_run_id": generation_run_id,
            "teaching_task_id": teaching_task_id,
            "teacher_id": primary,
            "teacher_role": "PRIMARY",
        })
    if assistant is not None and assistant != primary:
        rows.append({
            "template_fragment_id": fragment_id,
            "fragment_code": fragment_code,
            "template_id": template_id,
            "template_code": template_code,
            "allocation_task_id": allocation_task_id,
            "generation_run_id": generation_run_id,
            "teaching_task_id": teaching_task_id,
            "teacher_id": assistant,
            "teacher_role": "ASSISTANT",
        })
    return rows


def _fragment_class_group_rows(
    *,
    fragment_id: int,
    fragment_code: str,
    template_id: int,
    template_code: str,
    allocation_task_id: int,
    generation_run_id: str,
    teaching_task_id: int | None,
    identity: dict[str, Any],
) -> list[dict[str, Any]]:
    return [{
        "template_fragment_id": fragment_id,
        "fragment_code": fragment_code,
        "template_id": template_id,
        "template_code": template_code,
        "allocation_task_id": allocation_task_id,
        "generation_run_id": generation_run_id,
        "teaching_task_id": teaching_task_id,
        "class_group_id": class_group_id,
    } for class_group_id in identity["class_group_ids"]]


def _load_task_metadata(path: Path | None) -> dict[str, dict[Any, dict[str, Any]]]:
    by_source: dict[str, dict[str, Any]] = {}
    by_id: dict[int, dict[str, Any]] = {}
    if path is None or not path.exists():
        return {"by_source": by_source, "by_id": by_id}
    for row in _read_jsonl(path):
        source_key = str(row.get("source_key") or "")
        if source_key:
            by_source[source_key] = row
        task_id = _optional_int(row.get("teaching_task_id"))
        if task_id is not None:
            by_id[task_id] = row
    return {"by_source": by_source, "by_id": by_id}


def _load_room_ids(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return {}
    result: dict[str, int] = {}
    for row in payload:
        if not isinstance(row, dict) or str(row.get("status") or "ACTIVE") != "ACTIVE":
            continue
        room_id = _optional_int(row.get("id"))
        name = str(row.get("name") or "").strip()
        if room_id is not None and name:
            result[name] = room_id
    return result


def _metadata_for_fragment(
    fragment: dict[str, Any],
    metadata: dict[str, dict[Any, dict[str, Any]]],
) -> dict[str, Any]:
    task_id = _optional_int(fragment.get("teaching_task_id"))
    if task_id is not None and task_id in metadata["by_id"]:
        return metadata["by_id"][task_id]
    return metadata["by_source"].get(str(fragment.get("source_key") or ""), {})


def _fragment_identity(
    fragment: dict[str, Any],
    metadata: dict[str, Any],
    room_id_by_name: dict[str, int],
) -> dict[str, Any]:
    classroom_name = str(fragment.get("classroom_name") or "").strip()
    primary_teacher_id = _first_int(fragment.get("primary_teacher_id"), metadata.get("primary_teacher_id"))
    assistant_teacher_id = _first_int(fragment.get("assistant_teacher_id"), metadata.get("assistant_teacher_id"))
    class_group_ids = _int_list(fragment.get("class_group_ids") or metadata.get("class_group_ids"))
    return {
        "course_id": _first_int(fragment.get("course_id"), metadata.get("course_id")),
        "primary_teacher_id": primary_teacher_id,
        "assistant_teacher_id": assistant_teacher_id,
        "class_group_ids": class_group_ids,
        "classroom_id": _first_int(fragment.get("classroom_id"), room_id_by_name.get(classroom_name)),
    }


def _identity_issues(
    *,
    fragment_code: str,
    identity: dict[str, Any],
    required: bool,
) -> list[dict[str, Any]]:
    if not required:
        return []
    issues: list[dict[str, Any]] = []
    for field in ("course_id", "primary_teacher_id", "classroom_id"):
        if identity[field] is None:
            issues.append({"issue": "unresolved_stable_id", "fragment_code": fragment_code, "field": field})
    if not identity["class_group_ids"]:
        issues.append({"issue": "unresolved_stable_id", "fragment_code": fragment_code, "field": "class_group_ids"})
    return issues


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _int_list(value: Any) -> list[int]:
    values = value if isinstance(value, (list, tuple, set)) else str(value or "").split(",")
    result: list[int] = []
    for raw in values:
        parsed = _optional_int(raw)
        if parsed is not None and parsed not in result:
            result.append(parsed)
    return result


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Export V3.5 template cover into DB dry-run JSONL files.")
    parser.add_argument("--cover", default=str(DEFAULT_COVER_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--allocation-task-id", type=int, default=1)
    parser.add_argument("--total-weeks", type=int, default=18)
    parser.add_argument("--generation-run-id", default=None)
    parser.add_argument("--task-source", default=None)
    parser.add_argument("--rooms-json", default=None)
    args = parser.parse_args()

    report = export_db_draft(
        cover_path=Path(args.cover),
        output_dir=Path(args.output_dir),
        report_path=Path(args.report),
        allocation_task_id=args.allocation_task_id,
        total_weeks=args.total_weeks,
        generation_run_id=args.generation_run_id,
        task_source_path=Path(args.task_source) if args.task_source else None,
        rooms_path=Path(args.rooms_json) if args.rooms_json else None,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "week_mapping_preview"}, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
