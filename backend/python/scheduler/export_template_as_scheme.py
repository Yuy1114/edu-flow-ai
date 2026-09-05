"""Import V3.5 template cover results into allocation_scheme as candidate schemes.

Combines all templates into one complete scheme (one scheme = one full curriculum).
Frontend detects V3.5 schemes by model_version and renders items via template timetable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scheduler.export_template_cover_db_draft import DEFAULT_COVER_PATH
from scheduler.paths import OUTPUT_DIR as PLACEMENT_OUTPUT_DIR
from scheduler.phase_scheduler import DEFAULT_REPORT_PATH as DEFAULT_COVER_VALIDATION_REPORT_PATH

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402

DEFAULT_REPORT_PATH = PLACEMENT_OUTPUT_DIR / "scheme_import_report.json"


def import_template_schemes(
    *,
    cover_path: Path = DEFAULT_COVER_PATH,
    allocation_task_id: int = 1,
    generation_run_id: str | None = None,
    report_path: Path = DEFAULT_REPORT_PATH,
    validation_report_path: Path = DEFAULT_COVER_VALIDATION_REPORT_PATH,
    publication_gate: dict[str, Any] | None = None,
    execute: bool = False,
    truncate: bool = False,
    connection=None,
    commit: bool = True,
) -> dict[str, Any]:
    cover = json.loads(cover_path.read_text(encoding="utf-8"))
    templates = cover.get("templates", [])
    generation_run_id = generation_run_id or str(cover.get("generation_run_id") or "default")

    config = load_db_config()
    owns_connection = connection is None
    conn = connection or connect(config)
    try:
        existing_tables = _existing_tables(conn)
        if "allocation_scheme" not in existing_tables:
            if execute:
                raise RuntimeError("cannot import scheduling candidate; allocation_scheme table is missing")
            return {"status": "missing_allocation_scheme_table"}

        if truncate and execute:
            _truncate_scheme_items(conn, allocation_task_id)

        if owns_connection:
            conn.begin()
        # Combine all templates into one scheme
        all_fragments = []
        template_codes = []
        total_weeks = _safe_int(cover.get("total_weeks")) or 18
        for index, template in enumerate(templates, start=1):
            template_code = str(template.get("template_id") or f"template_{index}")
            template_codes.append(template_code)
            all_fragments.extend(template.get("fragments", []))

        fragment_count = len(all_fragments)
        task_count = len({f.get("source_key") for f in all_fragments})
        slot_count = sum(len(f.get("segments") or []) for f in all_fragments)
        explicit_weeks = sorted({
            _safe_int(week)
            for template in templates
            for week in (template.get("week_numbers") or [])
            if _safe_int(week) > 0
        })
        all_weeks = explicit_weeks or list(range(1, total_weeks + 1))

        display_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        validation_report = _read_validation_report(validation_report_path)
        review = _scheme_review_state(validation_report, publication_gate=publication_gate)
        conflict_summary = review["conflict_summary"]
        hard_blocked = review["hard_blocked"]
        needs_manual_review = review["needs_manual_review"]
        review_status = review["review_status"]
        is_valid = review_status == "COMPLETE"
        scheme = {
                "scheme_name": f"V3.5 周模板排课方案 {display_time}",
                "summary": json.dumps({
                    "generation_run_id": generation_run_id,
                    "template_codes": template_codes,
                    "fragment_count": fragment_count,
                    "task_count": task_count,
                    "slot_count": slot_count,
                    "weeks": all_weeks,
                    "validation_issue_count": validation_report.get("validation_issue_count", 0),
                    "phase_weeks": validation_report.get("phase_weeks"),
                    "review_status": review_status,
                    "requires_manual_review": needs_manual_review,
                    "hard_blocked": hard_blocked,
                    "publication_gate_status": (publication_gate or {}).get("status"),
                    "publication_gate_manual_reviews": (publication_gate or {}).get("manual_reviews", []),
                    "publication_gate_hard_blockers": (publication_gate or {}).get("hard_blockers", []),
                    "unplaced_task_count": conflict_summary["unplaced_tasks"],
                    "hour_mismatch_task_count": conflict_summary["conservation_mismatch"],
                    "capacity_mismatch_count": conflict_summary["capacity_mismatch_count"],
                }, ensure_ascii=False),
                "scheme_score": None,
                "model_version": "v3.5-dynamic-week",
                "conflict_summary": json.dumps(conflict_summary, ensure_ascii=False),
                "valid": is_valid,
                "status": "CANDIDATE",
        }

        if not execute:
            result = {
                "status": "dry_run_ok",
                "counts": {"templates": len(templates), "schemes": 1},
                "schemes": [scheme],
            }
            _write_report(report_path, result)
            return result

        with conn.cursor() as cur:
            scheme_ids = _insert_schemes(cur, allocation_task_id, [scheme])
        if commit:
            conn.commit()
        result = {
            "status": "inserted",
            "counts": {"templates": len(templates), "schemes": 1, "scheme_ids": scheme_ids},
            "schemes": [scheme],
        }
        _write_report(report_path, result)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def _read_validation_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _scheme_review_state(
    validation_report: dict[str, Any],
    *,
    publication_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conflicts = validation_report.get("conflicts") or {}
    hard_conflict_count = sum(
        _safe_int(count)
        for audit in conflicts.values()
        for count in (audit or {}).values()
    )
    conflict_summary = dict(validation_report.get("conflict_summary") or {})
    conflict_summary["hard_conflict_count"] = max(
        _safe_int(conflict_summary.get("hard_conflict_count")), hard_conflict_count)
    conflict_summary["conservation_mismatch"] = max(
        _safe_int(conflict_summary.get("conservation_mismatch")),
        _safe_int(validation_report.get("conservation_mismatch")))
    conflict_summary["unplaced_tasks"] = max(
        _safe_int(conflict_summary.get("unplaced_tasks")),
        _safe_int(validation_report.get("remaining_task_count")))
    conflict_summary["capacity_mismatch_count"] = max(
        _safe_int(conflict_summary.get("capacity_mismatch_count")),
        _safe_int(validation_report.get("capacity_mismatch_count")))
    conflict_summary["hour_over_task_count"] = max(
        _safe_int(conflict_summary.get("hour_over_task_count")),
        _safe_int(validation_report.get("hour_over_task_count")))
    conflict_summary["hour_under_task_count"] = max(
        _safe_int(conflict_summary.get("hour_under_task_count")),
        _safe_int(validation_report.get("hour_under_task_count")))
    validation_report_present = bool(validation_report)
    gate = publication_gate or {}
    gate_status = str(gate.get("status") or "")
    gate_hard_blockers = [str(reason) for reason in (gate.get("hard_blockers") or [])]
    gate_manual_reviews = [str(reason) for reason in (gate.get("manual_reviews") or [])]
    conflict_summary["publication_gate_status"] = gate_status or None
    conflict_summary["publication_gate_hard_blockers"] = gate_hard_blockers
    conflict_summary["publication_gate_manual_reviews"] = gate_manual_reviews
    hard_blocked = (
        not validation_report_present
        or gate_status == "BLOCKED"
        or bool(gate_hard_blockers)
        or _safe_int(conflict_summary.get("hard_conflict_count")) > 0
        or _safe_int(conflict_summary.get("capacity_mismatch_count")) > 0
    )
    needs_manual_review = (
        gate_status == "NEEDS_MANUAL_REVIEW"
        or bool(gate_manual_reviews)
        or
        _safe_int(conflict_summary.get("unplaced_tasks")) > 0
        or _safe_int(conflict_summary.get("conservation_mismatch")) > 0
        or _safe_int(conflict_summary.get("hour_over_task_count")) > 0
        or _safe_int(conflict_summary.get("hour_under_task_count")) > 0
    )
    review_status = (
        "BLOCKED" if hard_blocked
        else "NEEDS_MANUAL_REVIEW" if needs_manual_review
        else "COMPLETE"
    )
    conflict_summary["review_status"] = review_status
    conflict_summary["validation_report_present"] = validation_report_present
    return {
        "review_status": review_status,
        "hard_blocked": hard_blocked,
        "needs_manual_review": needs_manual_review,
        "conflict_summary": conflict_summary,
    }


def _write_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _existing_tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        rows = cur.fetchall()
    result = set()
    for row in rows:
        result.update(str(value) for value in row.values())
    return result


def _truncate_scheme_items(conn, allocation_task_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM allocation_item WHERE scheme_id IN "
            "(SELECT id FROM allocation_scheme WHERE task_id = %s AND model_version IN ('v3.5-tcv1', 'v3.5-phase', 'v3.5-dynamic-week'))",
            (allocation_task_id,),
        )
        cur.execute(
            "DELETE FROM allocation_scheme WHERE task_id = %s AND model_version IN ('v3.5-tcv1', 'v3.5-phase', 'v3.5-dynamic-week')",
            (allocation_task_id,),
        )


def _insert_schemes(cur, task_id: int, schemes: list[dict[str, Any]]) -> list[int]:
    sql = """INSERT INTO allocation_scheme (task_id, scheme_name, summary, scheme_score, model_version, conflict_summary, valid, status)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
    ids = []
    for scheme in schemes:
        cur.execute(sql, (
            task_id,
            scheme["scheme_name"],
            scheme.get("summary"),
            scheme.get("scheme_score"),
            scheme.get("model_version"),
            scheme.get("conflict_summary"),
            scheme.get("valid", True),
            scheme.get("status", "CANDIDATE"),
        ))
        cur.execute("SELECT LAST_INSERT_ID() AS id")
        ids.append(cur.fetchone()["id"])
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Import V3.5 templates as allocation_scheme records.")
    parser.add_argument("--cover", default=str(DEFAULT_COVER_PATH))
    parser.add_argument("--allocation-task-id", type=int, default=1)
    parser.add_argument("--generation-run-id", default=None)
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()
    if args.truncate and not args.execute:
        raise SystemExit("--truncate requires --execute")

    result = import_template_schemes(
        cover_path=Path(args.cover),
        allocation_task_id=args.allocation_task_id,
        generation_run_id=args.generation_run_id,
        report_path=Path(args.report),
        execute=args.execute,
        truncate=args.truncate,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
