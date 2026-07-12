"""Backfill teacher_name into schedule_template_fragment from DB teaching_task."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402


def backfill(*, execute: bool = False) -> dict[str, Any]:
    conn = connect(load_db_config())
    try:
        teacher_map = _build_teacher_map(conn)
        fragments = _get_empty_teacher_fragments(conn)

        updates = []
        for f in fragments:
            parts = str(f["source_key"]).split("|")
            if len(parts) < 3:
                continue
            course_code = parts[0]
            class_name = parts[2]
            teachers = teacher_map.get((course_code, class_name), [])
            if teachers:
                teacher_str = " / ".join(sorted(set(teachers)))
                updates.append({"id": f["id"], "source_key": f["source_key"], "teacher": teacher_str})

        print(f"缺教师: {len(fragments)}, 可回填: {len(updates)}")

        if not execute:
            return {"status": "dry_run", "updatable": len(updates), "total_empty": len(fragments)}

        updated = 0
        with conn.cursor() as cur:
            for u in updates:
                cur.execute("UPDATE schedule_template_fragment SET teacher_name = %s WHERE id = %s", (u["teacher"], u["id"]))
                updated += 1
        conn.commit()
        return {"status": "executed", "updated": updated, "total_empty": len(fragments)}
    finally:
        conn.close()


def _build_teacher_map(conn) -> dict[tuple[str, str], list[str]]:
    teacher_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.code AS course_code, cg.name AS class_name, t.name AS teacher_name
            FROM teaching_task tt
            JOIN course c ON c.id = tt.course_id
            JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
            JOIN class_group cg ON cg.id = ttcg.class_group_id
            LEFT JOIN teacher t ON t.id = tt.primary_teacher_id
            WHERE tt.status = 'ACTIVE' AND t.name IS NOT NULL
        """)
        for r in cur.fetchall():
            key = (str(r["course_code"]).strip(), str(r["class_name"]).strip())
            if key[0] and key[1]:
                teacher_map[key].append(str(r["teacher_name"]).strip())
    return teacher_map


def _get_empty_teacher_fragments(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, source_key FROM schedule_template_fragment WHERE teacher_name IS NULL OR teacher_name = ''")
        return cur.fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill teacher names from DB teaching_task.")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = backfill(execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
