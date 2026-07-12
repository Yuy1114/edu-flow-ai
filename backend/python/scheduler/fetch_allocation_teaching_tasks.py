"""Fetch teaching tasks bound to an allocation_task from DB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402

from scheduler.paths import OUTPUT_DIR as PLACEMENT_OUTPUT_DIR

DEFAULT_OUTPUT_PATH = PLACEMENT_OUTPUT_DIR / "allocation_tasks.jsonl"


def fetch(allocation_task_id: int, output_path: Path = DEFAULT_OUTPUT_PATH) -> dict[str, Any]:
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    tt.id AS teaching_task_id,
                    c.code AS course_code,
                    c.name AS course_name,
                    c.course_type,
                    t.name AS teacher_name,
                    GROUP_CONCAT(DISTINCT cg.name ORDER BY cg.name SEPARATOR ',') AS class_names,
                    GROUP_CONCAT(DISTINCT cg.major ORDER BY cg.major SEPARATOR ',') AS class_major,
                    GROUP_CONCAT(DISTINCT cg.department ORDER BY cg.department SEPARATOR ',') AS class_department,
                    GROUP_CONCAT(DISTINCT cg.grade ORDER BY cg.grade SEPARATOR ',') AS class_grade,
                    COALESCE(SUM(cg.student_count), 0) AS student_count,
                    COUNT(DISTINCT cg.id) AS class_group_count,
                    tt.total_hours,
                    tt.sessions_per_week,
                    tt.duration_weeks,
                    tt.required_room_type
                FROM allocation_task_teaching_task att
                JOIN teaching_task tt ON tt.id = att.teaching_task_id AND tt.status = 'ACTIVE'
                JOIN course c ON c.id = tt.course_id
                LEFT JOIN teacher t ON t.id = tt.primary_teacher_id
                JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
                JOIN class_group cg ON cg.id = ttcg.class_group_id
                WHERE att.allocation_task_id = %s
                  AND (tt.notes IS NULL OR tt.notes NOT LIKE 'unschedulable:%%')
                GROUP BY
                    tt.id, c.code, c.name, c.course_type, t.name, tt.total_hours, tt.sessions_per_week, tt.duration_weeks, tt.required_room_type
                ORDER BY c.code, class_names
            """, (allocation_task_id,))

            rows = cur.fetchall()
            if not rows:
                return {"status": "empty", "task_count": 0}

            jsonl_rows = []
            for r in rows:
                class_names = r["class_names"] or ""
                source_key = f"task:{r['teaching_task_id']}"
                jsonl_rows.append({
                    "source_key": source_key,
                    "course_name": r["course_name"],
                    "course_code": r["course_code"],
                    "teacher_name": r["teacher_name"] or "",
                    "class_name": class_names,
                    "class_names": class_names,
                    "class_group_names": class_names,
                    "class_group_count": r["class_group_count"] or 0,
                    "class_major": r["class_major"] or "",
                    "class_department": r["class_department"] or "",
                    "class_grade": str(r["class_grade"] or ""),
                    "student_count": r["student_count"] or 0,
                    "total_hours": r["total_hours"] or 0,
                    "sessions_per_week": r["sessions_per_week"],
                    "duration_weeks": r["duration_weeks"],
                    "course_type": r["course_type"],
                    "required_room_type": r["required_room_type"] or "",
                    "teaching_task_id": r["teaching_task_id"],
                })

            output_path.parent.mkdir(parents=True, exist_ok=True)
            _write_jsonl(output_path, jsonl_rows)

            return {
                "status": "ok",
                "allocation_task_id": allocation_task_id,
                "task_count": len(jsonl_rows),
                "output_path": str(output_path),
                "course_types": _counts(jsonl_rows, "course_type"),
                "room_types": _counts(jsonl_rows, "required_room_type"),
            }
    finally:
        conn.close()


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        val = str(row.get(key, ""))
        result[val] = result.get(val, 0) + 1
    return dict(sorted(result.items()))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch teaching tasks for an allocation task.")
    parser.add_argument("--allocation-task-id", type=int, required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args()

    result = fetch(allocation_task_id=args.allocation_task_id, output_path=Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
