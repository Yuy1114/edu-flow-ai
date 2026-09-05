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
DEFAULT_ROOMS_PATH = PLACEMENT_OUTPUT_DIR / "active_classrooms.json"
DEFAULT_CONTEXT_PATH = PLACEMENT_OUTPUT_DIR / "allocation_context.json"
DEFAULT_EXCLUDED_PATH = PLACEMENT_OUTPUT_DIR / "excluded_teaching_tasks.jsonl"

_CONSTRAINT_FIELDS = (
    "course_id",
    "primary_teacher_id",
    "assistant_teacher_id",
    "teacher_ids",
    "class_group_ids",
    "fixed_classroom_id",
    "fixed_classroom_name",
    "candidate_classroom_ids",
    "candidate_classroom_names",
    "teacher_unavailable_slots",
    "allowed_weeks",
)


def fetch(
    allocation_task_id: int,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    rooms_path: Path | None = None,
    context_path: Path | None = None,
    excluded_path: Path | None = None,
    allowed_weeks: frozenset[int] | set[int] | list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Export the canonical scheduler input and its hard-constraint context.

    Only ACTIVE classrooms are put in ``rooms_path``.  Invalid references are
    kept visible in ``hard_issues`` instead of silently dropping a teaching
    task; the pipeline publication gate can then reject the run explicitly.
    """
    rooms_path = rooms_path or output_path.with_name(DEFAULT_ROOMS_PATH.name)
    context_path = context_path or output_path.with_name(DEFAULT_CONTEXT_PATH.name)
    excluded_path = excluded_path or output_path.with_name(DEFAULT_EXCLUDED_PATH.name)
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    tt.id AS teaching_task_id,
                    tt.status AS teaching_task_status,
                    c.id AS course_id,
                    c.code AS course_code,
                    c.name AS course_name,
                    c.course_type,
                    c.status AS course_status,
                    primary_teacher.id AS primary_teacher_id,
                    primary_teacher.name AS teacher_name,
                    primary_teacher.status AS primary_teacher_status,
                    assistant_teacher.id AS assistant_teacher_id,
                    assistant_teacher.name AS assistant_teacher_name,
                    assistant_teacher.status AS assistant_teacher_status,
                    fixed_room.id AS fixed_classroom_id,
                    fixed_room.name AS fixed_classroom_name,
                    fixed_room.status AS fixed_classroom_status,
                    fixed_room.classroom_type AS fixed_classroom_type,
                    GROUP_CONCAT(DISTINCT cg.name ORDER BY cg.name SEPARATOR ',') AS class_names,
                    GROUP_CONCAT(DISTINCT cg.id ORDER BY cg.id SEPARATOR ',') AS class_group_ids,
                    GROUP_CONCAT(DISTINCT cg.major ORDER BY cg.major SEPARATOR ',') AS class_major,
                    GROUP_CONCAT(DISTINCT cg.department ORDER BY cg.department SEPARATOR ',') AS class_department,
                    GROUP_CONCAT(DISTINCT cg.grade ORDER BY cg.grade SEPARATOR ',') AS class_grade,
                    COALESCE(SUM(cg.student_count), 0) AS student_count,
                    COUNT(DISTINCT cg.id) AS class_group_count,
                    tt.total_hours,
                    tt.sessions_per_week,
                    tt.duration_weeks,
                    tt.required_room_type,
                    tt.notes
                FROM allocation_task_teaching_task att
                JOIN teaching_task tt ON tt.id = att.teaching_task_id
                JOIN course c ON c.id = tt.course_id
                JOIN teacher primary_teacher ON primary_teacher.id = tt.primary_teacher_id
                LEFT JOIN teacher assistant_teacher ON assistant_teacher.id = tt.assistant_teacher_id
                LEFT JOIN classroom fixed_room ON fixed_room.id = tt.classroom_id
                LEFT JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
                LEFT JOIN class_group cg ON cg.id = ttcg.class_group_id
                WHERE att.allocation_task_id = %s
                GROUP BY
                    tt.id, tt.status, c.id, c.code, c.name, c.course_type, c.status,
                    primary_teacher.id, primary_teacher.name, primary_teacher.status,
                    assistant_teacher.id, assistant_teacher.name, assistant_teacher.status,
                    fixed_room.id, fixed_room.name, fixed_room.status, fixed_room.classroom_type,
                    tt.total_hours, tt.sessions_per_week, tt.duration_weeks, tt.required_room_type, tt.notes
                ORDER BY c.code, class_names
            """, (allocation_task_id,))

            rows = cur.fetchall()
            if not rows:
                cur.execute("""
                    SELECT id, name, building, capacity, classroom_type, status
                    FROM classroom
                    WHERE status = 'ACTIVE'
                    ORDER BY id
                """)
                active_rooms = [dict(room) for room in cur.fetchall()]
                output_path.parent.mkdir(parents=True, exist_ok=True)
                _write_jsonl(output_path, [])
                excluded_path.parent.mkdir(parents=True, exist_ok=True)
                _write_jsonl(excluded_path, [])
                rooms_path.parent.mkdir(parents=True, exist_ok=True)
                rooms_path.write_text(json.dumps(active_rooms, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                context = {
                    "allocation_task_id": allocation_task_id,
                    "active_resource_policy": True,
                    "allowed_weeks": sorted({int(week) for week in (allowed_weeks or []) if int(week) > 0}),
                    "task_count": 0,
                    "bound_task_count": 0,
                    "excluded_task_count": 0,
                    "active_classroom_count": len(active_rooms),
                    "hard_issue_count": 1,
                    "warning_count": 0,
                    "hard_issues": [{"issue": "no_active_teaching_tasks"}],
                    "warnings": [],
                }
                context_path.parent.mkdir(parents=True, exist_ok=True)
                context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
                return {
                    "status": "empty",
                    "allocation_task_id": allocation_task_id,
                    "task_count": 0,
                    "output_path": str(output_path),
                    "rooms_path": str(rooms_path),
                    "context_path": str(context_path),
                    "excluded_path": str(excluded_path),
                    "active_classroom_count": len(active_rooms),
                    "hard_issue_count": 1,
                    "warning_count": 0,
                    "hard_issues_preview": context["hard_issues"],
                    "warnings_preview": [],
                }

            teacher_ids = {
                int(teacher_id)
                for row in rows
                for teacher_id in (row.get("primary_teacher_id"), row.get("assistant_teacher_id"))
                if teacher_id is not None
            }
            unavailable_by_teacher, availability_issues = _fetch_teacher_unavailable(cur, teacher_ids)
            candidate_rooms_by_task = _fetch_candidate_classrooms(
                cur,
                {int(row["teaching_task_id"]) for row in rows},
            )

            cur.execute("""
                SELECT id, name, building, capacity, classroom_type, status
                FROM classroom
                WHERE status = 'ACTIVE'
                ORDER BY id
            """)
            active_rooms = [dict(room) for room in cur.fetchall()]

            jsonl_rows = []
            excluded_rows: list[dict[str, Any]] = []
            hard_issues: list[dict[str, Any]] = list(availability_issues)
            warnings: list[dict[str, Any]] = []
            for raw_row in rows:
                r = dict(raw_row)
                candidate_context = candidate_rooms_by_task.get(int(r["teaching_task_id"]), {})
                r.update(candidate_context)
                class_names = r["class_names"] or ""
                source_key = f"task:{r['teaching_task_id']}"
                primary_teacher_id = _optional_int(r.get("primary_teacher_id"))
                assistant_teacher_id = _optional_int(r.get("assistant_teacher_id"))
                task_teacher_ids = [
                    value for value in (primary_teacher_id, assistant_teacher_id)
                    if value is not None
                ]
                class_group_ids = _parse_int_csv(r.get("class_group_ids"))
                candidate_classroom_ids = _parse_int_csv(r.get("candidate_classroom_ids"))
                candidate_classroom_names = _parse_csv(r.get("candidate_classroom_names"))
                fixed_classroom_id = _optional_int(r.get("fixed_classroom_id"))
                unavailable = [
                    slot
                    for teacher_id in task_teacher_ids
                    for slot in unavailable_by_teacher.get(teacher_id, [])
                ]
                task = {
                    "source_key": source_key,
                    "course_id": _optional_int(r.get("course_id")),
                    "course_name": r["course_name"],
                    "course_code": r["course_code"],
                    "teacher_name": r["teacher_name"] or "",
                    "primary_teacher_id": primary_teacher_id,
                    "assistant_teacher_id": assistant_teacher_id,
                    "assistant_teacher_name": r.get("assistant_teacher_name") or "",
                    "teacher_ids": task_teacher_ids,
                    "class_name": class_names,
                    "class_names": class_names,
                    "class_group_names": class_names,
                    "class_group_ids": class_group_ids,
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
                    "fixed_classroom_id": fixed_classroom_id,
                    "fixed_classroom_name": r.get("fixed_classroom_name") or "",
                    "candidate_classroom_ids": candidate_classroom_ids,
                    "candidate_classroom_names": candidate_classroom_names,
                    "teacher_unavailable_slots": unavailable,
                    "allowed_weeks": sorted({int(week) for week in (allowed_weeks or []) if int(week) > 0}),
                }
                if _is_explicitly_excluded(r.get("notes")):
                    excluded_rows.append({
                        **task,
                        "notes": str(r.get("notes") or ""),
                        "exclusion_reason": "explicit_unschedulable_note",
                        "manual_review_required": True,
                    })
                    continue
                jsonl_rows.append(task)
                task_issues, task_warnings = _resource_issues(r, task)
                hard_issues.extend(task_issues)
                warnings.extend(task_warnings)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            _write_jsonl(output_path, jsonl_rows)
            excluded_path.parent.mkdir(parents=True, exist_ok=True)
            _write_jsonl(excluded_path, excluded_rows)
            rooms_path.parent.mkdir(parents=True, exist_ok=True)
            rooms_path.write_text(json.dumps(active_rooms, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

            context = {
                "allocation_task_id": allocation_task_id,
                "active_resource_policy": True,
                "allowed_weeks": sorted({int(week) for week in (allowed_weeks or []) if int(week) > 0}),
                "task_count": len(jsonl_rows),
                "bound_task_count": len(rows),
                "excluded_task_count": len(excluded_rows),
                "active_classroom_count": len(active_rooms),
                "hard_issue_count": len(hard_issues),
                "warning_count": len(warnings),
                "hard_issues": hard_issues,
                "warnings": warnings,
                "excluded_tasks": excluded_rows,
            }
            context_path.parent.mkdir(parents=True, exist_ok=True)
            context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

            return {
                "status": "ok",
                "allocation_task_id": allocation_task_id,
                "task_count": len(jsonl_rows),
                "bound_task_count": len(rows),
                "excluded_task_count": len(excluded_rows),
                "output_path": str(output_path),
                "rooms_path": str(rooms_path),
                "context_path": str(context_path),
                "excluded_path": str(excluded_path),
                "active_classroom_count": len(active_rooms),
                "hard_issue_count": len(hard_issues),
                "warning_count": len(warnings),
                "hard_issues_preview": hard_issues[:20],
                "warnings_preview": warnings[:20],
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


def _is_explicitly_excluded(notes: Any) -> bool:
    return str(notes or "").strip().lower().startswith("unschedulable:")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def enrich_patterns_with_constraints(
    *,
    patterns_path: Path,
    task_source_path: Path,
    allowed_weeks: frozenset[int] | set[int] | list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Restore stable IDs and hard constraints after pattern compilation.

    Pattern compilation intentionally focuses on cadence.  This explicit join
    prevents resource identity and availability constraints from being lost
    between the canonical teaching-task input and the placement engine.
    """
    tasks = _read_jsonl(task_source_path)
    task_by_source = {str(task.get("source_key") or ""): task for task in tasks}
    patterns = _read_jsonl(patterns_path)
    missing: list[str] = []
    global_weeks = sorted({int(week) for week in (allowed_weeks or []) if int(week) > 0})
    for pattern in patterns:
        source_key = str(pattern.get("source_key") or "")
        task = task_by_source.get(source_key)
        if task is None:
            missing.append(source_key)
            continue
        for field in _CONSTRAINT_FIELDS:
            if field == "allowed_weeks" and global_weeks:
                pattern[field] = global_weeks
            elif field in task:
                pattern[field] = task[field]
    _write_jsonl(patterns_path, patterns)
    return {
        "pattern_count": len(patterns),
        "enriched_count": len(patterns) - len(missing),
        "missing_source_count": len(missing),
        "missing_source_preview": missing[:20],
        "allowed_weeks": global_weeks,
    }


def _fetch_teacher_unavailable(
    cur: Any,
    teacher_ids: set[int],
) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    if not teacher_ids:
        return {}, []
    placeholders = ",".join(["%s"] * len(teacher_ids))
    ordered_ids = sorted(teacher_ids)
    cur.execute(
        f"""
        SELECT teacher_id, availability_matrix_json
        FROM teacher_profile
        WHERE teacher_id IN ({placeholders})
        """,
        tuple(ordered_ids),
    )
    result: dict[int, list[dict[str, Any]]] = {}
    issues: list[dict[str, Any]] = []
    for row in cur.fetchall():
        teacher_id = int(row["teacher_id"])
        try:
            result[teacher_id] = _parse_unavailable_matrix(
                teacher_id,
                row.get("availability_matrix_json") or "",
            )
        except ValueError as exception:
            # A malformed hard-availability declaration is not equivalent to
            # "fully available".  Keep the task data visible but block the
            # publication gate with an explicit resource issue.
            result[teacher_id] = []
            issues.append({
                "teacher_id": teacher_id,
                "issue": "invalid_teacher_availability_matrix",
                "message": str(exception),
            })
    return result, issues


def _fetch_candidate_classrooms(cur: Any, task_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not task_ids:
        return {}
    placeholders = ",".join(["%s"] * len(task_ids))
    ordered_ids = sorted(task_ids)
    cur.execute(
        f"""
        SELECT ttc.teaching_task_id, cr.id, cr.name, cr.status
        FROM teaching_task_classroom ttc
        JOIN classroom cr ON cr.id = ttc.classroom_id
        WHERE ttc.teaching_task_id IN ({placeholders})
        ORDER BY ttc.teaching_task_id, cr.id
        """,
        tuple(ordered_ids),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in cur.fetchall():
        grouped.setdefault(int(row["teaching_task_id"]), []).append(dict(row))

    result: dict[int, dict[str, Any]] = {}
    for task_id, rooms in grouped.items():
        active = [room for room in rooms if str(room.get("status") or "") == "ACTIVE"]
        result[task_id] = {
            "candidate_classroom_link_count": len(rooms),
            "active_candidate_classroom_count": len(active),
            "candidate_classroom_ids": ",".join(str(room["id"]) for room in active),
            "candidate_classroom_names": ",".join(str(room["name"]) for room in active),
        }
    return result


def _parse_unavailable_matrix(teacher_id: int, raw_json: str) -> list[dict[str, Any]]:
    if not str(raw_json or "").strip():
        return []
    try:
        matrix = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError) as exception:
        raise ValueError(f"teacher {teacher_id} availability is not valid JSON") from exception
    if not isinstance(matrix, list) or len(matrix) not in {5, 10}:
        raise ValueError(f"teacher {teacher_id} availability must be a 5x7 or 10x7 matrix")
    for row in matrix:
        if not isinstance(row, list) or len(row) != 7:
            raise ValueError(f"teacher {teacher_id} availability must be a 5x7 or 10x7 matrix")
        for value in row:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"teacher {teacher_id} availability only accepts -1, 0 and 1")
            if int(value) != value or int(value) not in {-1, 0, 1}:
                raise ValueError(f"teacher {teacher_id} availability only accepts -1, 0 and 1")
    normalized = [row for block in matrix for row in (block, block)] if len(matrix) == 5 else matrix
    slots: list[dict[str, Any]] = []
    for period_index, row in enumerate(normalized, start=1):
        for day_of_week, value in enumerate(row, start=1):
            if value == -1:
                slots.append({
                    "teacher_id": teacher_id,
                    "week_number": None,
                    "day_of_week": day_of_week,
                    "period_index": period_index,
                })
    return slots


def _resource_issues(row: dict[str, Any], task: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    task_id = task.get("teaching_task_id")
    hard: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def hard_issue(code: str, **details: Any) -> None:
        hard.append({"teaching_task_id": task_id, "issue": code, **details})

    def warning(code: str, **details: Any) -> None:
        warnings.append({"teaching_task_id": task_id, "issue": code, **details})

    if row.get("teaching_task_status") is not None and str(row.get("teaching_task_status")) != "ACTIVE":
        hard_issue("inactive_teaching_task")
    if str(row.get("course_status") or "") != "ACTIVE":
        hard_issue("inactive_course", course_id=task.get("course_id"))
    if str(row.get("primary_teacher_status") or "") != "ACTIVE":
        hard_issue("inactive_primary_teacher", teacher_id=task.get("primary_teacher_id"))
    if task.get("assistant_teacher_id") is not None and str(row.get("assistant_teacher_status") or "") != "ACTIVE":
        hard_issue("inactive_assistant_teacher", teacher_id=task.get("assistant_teacher_id"))
    if not task.get("class_group_ids"):
        hard_issue("missing_class_group")

    fixed_id = task.get("fixed_classroom_id")
    if fixed_id is not None:
        if str(row.get("fixed_classroom_status") or "") != "ACTIVE":
            hard_issue("inactive_fixed_classroom", classroom_id=fixed_id)
        required_type = str(task.get("required_room_type") or "")
        fixed_type = str(row.get("fixed_classroom_type") or "")
        if required_type and fixed_type and fixed_type != required_type:
            hard_issue(
                "fixed_classroom_type_mismatch",
                classroom_id=fixed_id,
                required_room_type=required_type,
                classroom_type=fixed_type,
            )

    linked = int(row.get("candidate_classroom_link_count") or 0)
    active = int(row.get("active_candidate_classroom_count") or 0)
    if linked > 0 and active == 0 and fixed_id is None:
        hard_issue("candidate_classrooms_all_inactive", linked_count=linked)
    elif linked > active:
        warning("inactive_candidate_classrooms_ignored", ignored_count=linked - active)
    return hard, warnings


def _parse_int_csv(value: Any) -> list[int]:
    result: list[int] = []
    for part in _parse_csv(value):
        parsed = _optional_int(part)
        if parsed is not None and parsed not in result:
            result.append(parsed)
    return result


def _parse_csv(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch teaching tasks for an allocation task.")
    parser.add_argument("--allocation-task-id", type=int, required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--rooms-output", default=str(DEFAULT_ROOMS_PATH))
    parser.add_argument("--context-output", default=str(DEFAULT_CONTEXT_PATH))
    parser.add_argument("--excluded-output", default=str(DEFAULT_EXCLUDED_PATH))
    parser.add_argument("--allowed-weeks", default="")
    args = parser.parse_args()

    result = fetch(
        allocation_task_id=args.allocation_task_id,
        output_path=Path(args.output),
        rooms_path=Path(args.rooms_output),
        context_path=Path(args.context_output),
        excluded_path=Path(args.excluded_output),
        allowed_weeks=_parse_int_csv(args.allowed_weeks),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
