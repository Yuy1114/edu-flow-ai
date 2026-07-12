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
from scheduler.validate_template_cover_v1 import DEFAULT_REPORT_PATH as DEFAULT_COVER_VALIDATION_REPORT_PATH

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
    execute: bool = False,
    truncate: bool = False,
) -> dict[str, Any]:
    cover = json.loads(cover_path.read_text(encoding="utf-8"))
    templates = cover.get("templates", [])
    generation_run_id = generation_run_id or str(cover.get("generation_run_id") or "default")

    config = load_db_config()
    conn = connect(config)
    try:
        existing_tables = _existing_tables(conn)
        if "allocation_scheme" not in existing_tables:
            return {"status": "missing_allocation_scheme_table"}

        if truncate and execute:
            _truncate_scheme_items(conn, allocation_task_id)

        conn.begin()
        try:
            # Combine all templates into one scheme
            all_fragments = []
            template_codes = []
            total_weeks = 18
            for index, template in enumerate(templates, start=1):
                template_code = str(template.get("template_id") or f"template_{index}")
                template_codes.append(template_code)
                all_fragments.extend(template.get("fragments", []))

            fragment_count = len(all_fragments)
            task_count = len({f.get("source_key") for f in all_fragments})
            slot_count = sum(len(f.get("segments") or []) for f in all_fragments)
            all_weeks = list(range(1, total_weeks + 1))

            display_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            validation_report = _read_validation_report(validation_report_path)
            conflict_summary = validation_report.get("conflict_summary") or {
                "hard_conflict_count": 0,
                "teacher_groups": 0,
                "class_groups": 0,
                "room_groups": 0,
                "segment_boundary_issues": 0,
                "hour_issues": 0,
            }
            is_valid = _safe_int(conflict_summary.get("hard_conflict_count")) == 0
            scheme = {
                "scheme_name": f"V3.5 周模板排课方案 {display_time}",
                "summary": json.dumps({
                    "generation_run_id": generation_run_id,
                    "template_codes": template_codes,
                    "fragment_count": fragment_count,
                    "task_count": task_count,
                    "slot_count": slot_count,
                    "weeks": all_weeks,
                    "validation_issue_count": validation_report.get("issue_count", 0),
                    "validation_issues_preview": validation_report.get("issues_preview", [])[:20],
                }, ensure_ascii=False),
                "scheme_score": None,
                "model_version": "v3.5-tcv1",
                "conflict_summary": json.dumps(conflict_summary, ensure_ascii=False),
                "valid": is_valid,
                "status": "CANDIDATE",
            }

            if not execute:
                conn.rollback()
                return {
                    "status": "dry_run_ok",
                    "counts": {"templates": len(templates), "schemes": 1},
                    "schemes": [scheme],
                }

            with conn.cursor() as cur:
                scheme_ids = _insert_schemes(cur, allocation_task_id, [scheme])
            conn.commit()
            return {
                "status": "inserted",
                "counts": {"templates": len(templates), "schemes": 1, "scheme_ids": scheme_ids},
                "schemes": [scheme],
            }
        except Exception:
            conn.rollback()
            raise
    finally:
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
            "(SELECT id FROM allocation_scheme WHERE task_id = %s AND model_version = 'v3.5-tcv1')",
            (allocation_task_id,),
        )
        cur.execute(
            "DELETE FROM allocation_scheme WHERE task_id = %s AND model_version = 'v3.5-tcv1'",
            (allocation_task_id,),
        )
    conn.commit()


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
