"""Import V3.5 DB dry-run JSONL files into MySQL.

Safe by default:
  - Without --execute, only validates files and checks table availability.
  - With --execute, inserts rows in one transaction.

Run from backend/python so `app.db.session` can load the project .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scheduler.export_template_cover_db_draft import DEFAULT_OUTPUT_DIR

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import connect, load_db_config  # noqa: E402

TABLE_FILES = {
    "schedule_template": "schedule_templates.jsonl",
    "schedule_template_week": "schedule_template_weeks.jsonl",
    "schedule_template_fragment": "schedule_template_fragments.jsonl",
    "schedule_template_fragment_week": "schedule_template_fragment_weeks.jsonl",
    "schedule_template_fragment_slot": "schedule_template_fragment_slots.jsonl",
    "schedule_template_fragment_teacher": "schedule_template_fragment_teachers.jsonl",
    "schedule_template_fragment_class_group": "schedule_template_fragment_class_groups.jsonl",
}

INSERT_COLUMNS = {
    "schedule_template": [
        "allocation_task_id", "generation_run_id", "template_code", "template_name", "template_order",
        "source_type", "algorithm_version", "status", "fragment_count", "task_count",
    ],
    "schedule_template_week": [
        "allocation_task_id", "generation_run_id", "week_number", "template_id", "template_code", "source_type", "notes",
    ],
    "schedule_template_fragment": [
        "template_id", "template_code", "allocation_task_id", "generation_run_id", "fragment_code",
        "teaching_task_id", "source_key", "course_id", "course_name", "teacher_id", "teacher_name",
        "class_group_id", "class_name", "classroom_id", "classroom_name", "day_of_week", "period_index",
        "consecutive_slots", "duration_weeks", "session_hours", "required_room_type",
        "source_type", "lock_status", "score", "candidate_rank",
    ],
    "schedule_template_fragment_week": [
        "template_fragment_id", "allocation_task_id", "generation_run_id", "template_id", "week_number",
    ],
    "schedule_template_fragment_slot": [
        "template_fragment_id", "fragment_code", "template_id", "template_code", "allocation_task_id", "generation_run_id",
        "teaching_task_id", "classroom_id", "teacher_id", "class_group_id", "day_of_week", "period_index",
    ],
    "schedule_template_fragment_teacher": [
        "template_fragment_id", "fragment_code", "template_id", "template_code", "allocation_task_id",
        "generation_run_id", "teaching_task_id", "teacher_id", "teacher_role",
    ],
    "schedule_template_fragment_class_group": [
        "template_fragment_id", "fragment_code", "template_id", "template_code", "allocation_task_id",
        "generation_run_id", "teaching_task_id", "class_group_id",
    ],
}


def import_draft(
    *,
    input_dir: Path = DEFAULT_OUTPUT_DIR,
    execute: bool = False,
    truncate: bool = False,
    connection=None,
    commit: bool = True,
) -> dict[str, Any]:
    rows_by_table = {table: _read_jsonl(input_dir / filename) for table, filename in TABLE_FILES.items()}
    generation_run_id = _validate_import_identity(rows_by_table)
    config = load_db_config()
    owns_connection = connection is None
    connection = connection or connect(config)
    try:
        existing_tables = _existing_tables(connection)
        missing_tables = [table for table in TABLE_FILES if table not in existing_tables]
        report = {
            "database": config.database,
            "input_dir": str(input_dir),
            "execute": execute,
            "truncate": truncate,
            "counts": {table: len(rows) for table, rows in rows_by_table.items()},
            "generation_run_id": generation_run_id,
            "missing_tables": missing_tables,
        }
        if missing_tables:
            report["status"] = "missing_tables"
            if execute:
                raise RuntimeError(
                    "cannot import scheduling draft; missing required tables: "
                    + ", ".join(sorted(missing_tables))
                )
            return report
        if not execute:
            report["status"] = "dry_run_ok"
            return report

        with connection.cursor() as cursor:
            if truncate:
                _truncate_tables(cursor)

            template_id_map = _insert_templates(cursor, rows_by_table["schedule_template"])
            week_rows = [_replace_template_id(row, template_id_map) for row in rows_by_table["schedule_template_week"]]
            _insert_rows(cursor, "schedule_template_week", week_rows)

            fragment_rows = [_replace_template_id(row, template_id_map) for row in rows_by_table["schedule_template_fragment"]]
            fragment_id_map = _insert_fragments(cursor, fragment_rows)

            fragment_week_rows = _replace_fragment_and_template_ids(
                rows_by_table["schedule_template_fragment_week"], template_id_map, fragment_id_map)
            teacher_rows = _replace_fragment_and_template_ids(
                rows_by_table["schedule_template_fragment_teacher"], template_id_map, fragment_id_map)
            class_group_rows = _replace_fragment_and_template_ids(
                rows_by_table["schedule_template_fragment_class_group"], template_id_map, fragment_id_map)
            slot_rows = _replace_fragment_and_template_ids(
                rows_by_table["schedule_template_fragment_slot"], template_id_map, fragment_id_map)
            _insert_rows(cursor, "schedule_template_fragment_week", fragment_week_rows)
            _insert_rows(cursor, "schedule_template_fragment_teacher", teacher_rows)
            _insert_rows(cursor, "schedule_template_fragment_class_group", class_group_rows)
            _insert_rows(cursor, "schedule_template_fragment_slot", slot_rows)

            persisted_counts = _persisted_counts(cursor, generation_run_id)
            expected_counts = {table: len(rows) for table, rows in rows_by_table.items()}
            if persisted_counts != expected_counts:
                raise RuntimeError(
                    "scheduling draft persistence verification failed: "
                    f"expected={expected_counts}, actual={persisted_counts}"
                )

        if commit:
            connection.commit()
        report["status"] = "inserted"
        report["mapped_counts"] = {
            "templates": len(template_id_map),
            "fragments": len(fragment_id_map),
        }
        report["persisted_counts"] = persisted_counts
        return report
    except Exception:
        connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


def _existing_tables(connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        rows = cursor.fetchall()
    result = set()
    for row in rows:
        result.update(str(value) for value in row.values())
    return result


def _truncate_tables(cursor) -> None:
    for table in [
        "schedule_template_fragment_slot",
        "schedule_template_fragment_teacher",
        "schedule_template_fragment_class_group",
        "schedule_template_fragment_week",
        "schedule_template_fragment",
        "schedule_template_week",
        "schedule_template",
    ]:
        # DELETE remains inside the candidate batch transaction. TRUNCATE would
        # implicitly commit and could expose a half-imported formal run.
        cursor.execute(f"DELETE FROM {table}")


def _insert_templates(cursor, rows: list[dict[str, Any]]) -> dict[Any, int]:
    result = {}
    for row in rows:
        draft_id = row.get("id")
        _insert_row(cursor, "schedule_template", row)
        result[draft_id] = _last_insert_id(cursor)
    return result


def _insert_fragments(cursor, rows: list[dict[str, Any]]) -> dict[Any, int]:
    result = {}
    for row in rows:
        draft_id = row.get("id")
        _insert_row(cursor, "schedule_template_fragment", row)
        result[draft_id] = _last_insert_id(cursor)
    return result


def _replace_template_id(row: dict[str, Any], template_id_map: dict[Any, int]) -> dict[str, Any]:
    mapped = dict(row)
    mapped["template_id"] = template_id_map[row.get("template_id")]
    return mapped


def _replace_fragment_and_template_ids(
    rows: list[dict[str, Any]],
    template_id_map: dict[Any, int],
    fragment_id_map: dict[Any, int],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        mapped = _replace_template_id(row, template_id_map)
        draft_fragment_id = row.get("template_fragment_id")
        mapped["template_fragment_id"] = fragment_id_map[draft_fragment_id]
        result.append(mapped)
    return result


def _insert_row(cursor, table: str, row: dict[str, Any]) -> None:
    columns = INSERT_COLUMNS[table]
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
    cursor.execute(sql, tuple(row.get(column) for column in columns))


def _insert_rows(cursor, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = INSERT_COLUMNS[table]
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
    values = [tuple(row.get(column) for column in columns) for row in rows]
    cursor.executemany(sql, values)


def _last_insert_id(cursor) -> int:
    cursor.execute("SELECT LAST_INSERT_ID() AS id")
    return int(cursor.fetchone()["id"])


def _first_generation_run_id(rows_by_table: dict[str, list[dict[str, Any]]]) -> str | None:
    for rows in rows_by_table.values():
        for row in rows:
            value = row.get("generation_run_id")
            if value:
                return str(value)
    return None


def _validate_import_identity(rows_by_table: dict[str, list[dict[str, Any]]]) -> str:
    run_ids = {
        str(row.get("generation_run_id") or "").strip()
        for rows in rows_by_table.values()
        for row in rows
    }
    run_ids.discard("")
    if len(run_ids) != 1:
        raise ValueError(f"DB draft must contain exactly one generation_run_id, got {sorted(run_ids)}")
    generation_run_id = next(iter(run_ids))
    for table, rows in rows_by_table.items():
        missing = [index + 1 for index, row in enumerate(rows) if row.get("generation_run_id") != generation_run_id]
        if missing:
            raise ValueError(
                f"{table} contains rows without generation_run_id={generation_run_id}: lines={missing[:10]}"
            )
    return generation_run_id


def _persisted_counts(cursor, generation_run_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLE_FILES:
        cursor.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE generation_run_id = %s",
            (generation_run_id,),
        )
        counts[table] = int(cursor.fetchone()["count"])
    return counts


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import V3.5 DB dry-run JSONL files into MySQL.")
    parser.add_argument("--input-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--execute", action="store_true", help="Actually insert rows. Default is dry-run only.")
    parser.add_argument("--truncate", action="store_true", help="Truncate target template tables before inserting. Requires --execute.")
    args = parser.parse_args()
    if args.truncate and not args.execute:
        raise SystemExit("--truncate requires --execute")

    report = import_draft(input_dir=Path(args.input_dir), execute=args.execute, truncate=args.truncate)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
