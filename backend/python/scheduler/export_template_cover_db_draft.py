"""Export V3.5 template cover result into DB-ready dry-run JSONL files.

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

DEFAULT_OUTPUT_DIR = DEFAULT_COVER_PATH.parent / "db_draft"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "export_report.json"

ALGORITHM_VERSION = "v3.5-phase-cover-v1"


def export_db_draft(
    *,
    cover_path: Path = DEFAULT_COVER_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
    allocation_task_id: int = 1,
    total_weeks: int = 18,
    generation_run_id: str | None = None,
) -> dict[str, Any]:
    cover = json.loads(cover_path.read_text(encoding="utf-8"))
    templates = cover.get("templates", [])
    generation_run_id = generation_run_id or str(cover.get("generation_run_id") or "default")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    template_rows: list[dict[str, Any]] = []
    week_rows: list[dict[str, Any]] = []
    fragment_rows: list[dict[str, Any]] = []
    slot_rows: list[dict[str, Any]] = []

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
            "template_name": f"V3.5 模板 {template_index}",
            "template_order": template_index,
            "source_type": "AUTO",
            "algorithm_version": ALGORITHM_VERSION,
            "status": "ACTIVE",
            "fragment_count": len(fragments),
            "task_count": len({fragment.get("source_key") for fragment in fragments}),
        })

        for fragment in fragments:
            fragment_code = str(fragment.get("fragment_id") or f"fragment_{fragment_id}")
            fragment_row = _fragment_row(
                fragment,
                fragment_id=fragment_id,
                fragment_code=fragment_code,
                template_id=template_id,
                template_code=template_code,
                allocation_task_id=allocation_task_id,
                generation_run_id=generation_run_id,
            )
            fragment_rows.append(fragment_row)
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
                ))
            fragment_id += 1

    if template_rows:
        # 周映射按各模板的 week_budget 顺序铺开 (phase 引擎产出); 无预算信息时均分兜底.
        budgets = [_safe_int(template.get("week_budget")) for template in templates]
        if sum(budgets) != total_weeks or any(b <= 0 for b in budgets):
            base = total_weeks // max(1, len(template_rows))
            budgets = [base] * len(template_rows)
            budgets[-1] += total_weeks - sum(budgets)
        mapping_note = "phase week mapping: " + ", ".join(
            f"{row['template_code']}×{budget}" for row, budget in zip(template_rows, budgets)
        )
        week_number = 1
        for template_row, budget in zip(template_rows, budgets):
            for _ in range(budget):
                if week_number > total_weeks:
                    break
                week_rows.append({
                    "id": week_number,
                    "allocation_task_id": allocation_task_id,
                    "generation_run_id": generation_run_id,
                    "week_number": week_number,
                    "template_id": template_row["id"],
                    "template_code": template_row["template_code"],
                    "source_type": "AUTO",
                    "notes": mapping_note,
                })
                week_number += 1

    files = {
        "schedule_templates": output_dir / "schedule_templates.jsonl",
        "schedule_template_weeks": output_dir / "schedule_template_weeks.jsonl",
        "schedule_template_fragments": output_dir / "schedule_template_fragments.jsonl",
        "schedule_template_fragment_slots": output_dir / "schedule_template_fragment_slots.jsonl",
    }
    _write_jsonl(files["schedule_templates"], template_rows)
    _write_jsonl(files["schedule_template_weeks"], week_rows)
    _write_jsonl(files["schedule_template_fragments"], fragment_rows)
    _write_jsonl(files["schedule_template_fragment_slots"], slot_rows)

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
            "template_fragment_slots": len(slot_rows),
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
) -> dict[str, Any]:
    return {
        "id": fragment_id,
        "template_id": template_id,
        "template_code": template_code,
        "allocation_task_id": allocation_task_id,
        "generation_run_id": generation_run_id,
        "fragment_code": fragment_code,
        "teaching_task_id": _safe_int(fragment.get("teaching_task_id")) or None,
        "source_key": fragment.get("source_key"),
        "course_id": None,
        "course_name": fragment.get("course_name"),
        "teacher_id": None,
        "teacher_name": fragment.get("teacher_name"),
        "class_group_id": None,
        "class_name": fragment.get("class_names") or fragment.get("class_group_names") or fragment.get("class_name"),
        "classroom_id": None,
        "classroom_name": fragment.get("classroom_name"),
        "day_of_week": _safe_int(fragment.get("day_of_week")),
        "period_index": _safe_int(fragment.get("period_index")),
        "consecutive_slots": _safe_int(fragment.get("consecutive_slots")),
        "duration_weeks": _safe_int(fragment.get("duration_weeks")) or None,
        "session_hours": _safe_int(fragment.get("session_hours")) or None,
        "required_room_type": fragment.get("required_room_type"),
        "source_type": "AUTO",
        "lock_status": "UNLOCKED",
        "score": _safe_float(fragment.get("score")),
        "candidate_rank": _safe_int(fragment.get("candidate_rank")),
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
) -> dict[str, Any]:
    return {
        "template_fragment_id": template_fragment_id,
        "fragment_code": fragment_code,
        "template_id": template_id,
        "template_code": template_code,
        "allocation_task_id": allocation_task_id,
        "generation_run_id": generation_run_id,
        "teaching_task_id": _safe_int(fragment.get("teaching_task_id")) or None,
        "classroom_id": None,
        "teacher_id": None,
        "class_group_id": None,
        "source_key": fragment.get("source_key"),
        "classroom_name": fragment.get("classroom_name"),
        "teacher_name": fragment.get("teacher_name"),
        "class_name": fragment.get("class_names") or fragment.get("class_group_names") or fragment.get("class_name"),
        "day_of_week": _safe_int(segment.get("day_of_week")),
        "period_index": _safe_int(segment.get("period_index")),
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


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
    args = parser.parse_args()

    report = export_db_draft(
        cover_path=Path(args.cover),
        output_dir=Path(args.output_dir),
        report_path=Path(args.report),
        allocation_task_id=args.allocation_task_id,
        total_weeks=args.total_weeks,
        generation_run_id=args.generation_run_id,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "week_mapping_preview"}, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
