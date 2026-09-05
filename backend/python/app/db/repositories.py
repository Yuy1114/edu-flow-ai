"""SQL query helpers used by training sample generation and scheduling pipelines."""

from __future__ import annotations

import json
from typing import Any


def _parse_profile_preference(raw_json: str) -> dict[str, Any]:
    if not raw_json or not raw_json.strip():
        return {}
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_availability_matrix_unavailable(raw_json: str) -> set[tuple[int, int]]:
    """Parse 10×7 atomic-period matrix; -1 means fixed weekly unavailable."""
    slots: set[tuple[int, int]] = set()
    if not raw_json or not raw_json.strip():
        return slots
    try:
        matrix = json.loads(raw_json)
    except json.JSONDecodeError:
        return slots
    if not isinstance(matrix, list):
        return slots
    # Backward compatibility: the old profile used five two-period blocks.
    # Duplicate each row so its meaning is preserved on the 10×7 atomic axis.
    normalized = [row for block in matrix for row in (block, block)] if len(matrix) == 5 else matrix[:10]
    for period_index, row in enumerate(normalized, start=1):
        if not isinstance(row, list):
            continue
        for weekday_index, value in enumerate(row[:7], start=1):
            if value == -1:
                slots.add((weekday_index, period_index))
    return slots


def _parse_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_all(connection, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
    except Exception as exc:
        import sys as _sys

        preview = " ".join(sql.split())[:120]
        print(
            f"[SCHEDULE-CHAIN] DB error: {preview} | params={params} | {type(exc).__name__}: {exc}",
            file=_sys.stderr,
            flush=True,
        )
        raise


def fetch_tasks(connection) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        """
        SELECT
            tt.id AS teaching_task_id,
            tt.primary_teacher_id AS teacher_id,
            t.name AS teacher_name,
            tt.assistant_teacher_id,
            tt.classroom_id AS bound_classroom_id,
            tt.total_hours,
            tt.required_room_type,
            c.name AS course_name,
            c.code AS course_code,
            c.course_type,
            c.required_hours AS course_required_hours,
            t.department AS teacher_department,
            t.title AS teacher_title,
            NULL AS teacher_max_weekly_hours,
            bound_cr.classroom_type AS bound_classroom_type,
            COUNT(cg.id) AS class_group_count,
            COALESCE(SUM(cg.student_count), 0) AS total_student_count,
            GROUP_CONCAT(cg.id ORDER BY cg.id) AS class_group_ids,
            GROUP_CONCAT(cg.major ORDER BY cg.id) AS class_group_majors,
            GROUP_CONCAT(cg.grade ORDER BY cg.id) AS class_group_grades,
            GROUP_CONCAT(cg.name ORDER BY cg.id) AS class_group_names
        FROM teaching_task tt
        JOIN course c ON c.id = tt.course_id
        JOIN teacher t ON t.id = tt.primary_teacher_id
        LEFT JOIN classroom bound_cr ON bound_cr.id = tt.classroom_id
        LEFT JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
        LEFT JOIN class_group cg ON cg.id = ttcg.class_group_id
        WHERE tt.status = 'ACTIVE'
        GROUP BY
            tt.id,
            tt.primary_teacher_id,
            tt.assistant_teacher_id,
            tt.classroom_id,
            tt.total_hours,
            tt.required_room_type,
            t.name,
            c.name,
            c.code,
            c.course_type,
            c.required_hours,
            t.department,
            t.title,
            bound_cr.classroom_type
        ORDER BY tt.id
        """,
    )


def fetch_classrooms(connection) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        """
        SELECT id, name, building, capacity, classroom_type
        FROM classroom
        WHERE status = 'ACTIVE'
        ORDER BY id
        """,
    )


def fetch_time_slots(connection) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        """
        SELECT id, week_number, day_of_week, period_index, label
        FROM time_slot
        ORDER BY week_number, day_of_week, period_index
        """,
    )


def ensure_default_time_slots(connection, *, weeks: int = 18, weekdays: int = 7, periods: int = 10) -> int:
    """Seed default time slots only when the table is empty.

    Returns the number of inserted rows. Existing time_slot data is never
    modified because these IDs are part of the Java persistence contract.
    """

    rows = fetch_all(connection, "SELECT COUNT(*) AS cnt FROM time_slot")
    existing = int(rows[0]["cnt"] or 0) if rows else 0
    if existing > 0:
        return 0

    inserted = 0
    with connection.cursor() as cursor:
        for week in range(1, weeks + 1):
            for day in range(1, weekdays + 1):
                for period in range(1, periods + 1):
                    label = f"第{week}周 周{day} 第{period}节"
                    cursor.execute(
                        """
                        INSERT IGNORE INTO time_slot
                            (week_number, day_of_week, period_index, label)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (week, day, period, label),
                    )
                    inserted += int(cursor.rowcount or 0)
    connection.commit()
    return inserted


def fetch_teacher_profiles(connection) -> dict[int, dict[str, object]]:
    """Return {teacher_id: {unavailable_slots, max_weekly_hours, profile_preference, ...}}."""
    rows = fetch_all(
        connection,
        """
        SELECT p.teacher_id, p.availability_matrix_json,
               p.profile_preference_json,
               NULL AS max_weekly_hours, t.name AS teacher_name,
               t.department
        FROM teacher_profile p
        JOIN teacher t ON t.id = p.teacher_id
        WHERE t.status = 'ACTIVE'
        """,
    )
    profiles: dict[int, dict[str, object]] = {}
    for row in rows:
        teacher_id = int(row["teacher_id"])
        unavailable = _parse_availability_matrix_unavailable(row.get("availability_matrix_json") or "")
        parsed_preference = _parse_profile_preference(row.get("profile_preference_json") or "")
        max_hours = _parse_optional_int(parsed_preference.get("preferredMaxWeeklyHours"))
        if max_hours is None:
            db_max = row.get("max_weekly_hours")
            max_hours = int(db_max) if db_max is not None else None
        profiles[teacher_id] = {
            "unavailable_slots": unavailable,
            "max_weekly_hours": max_hours,
            "profile_preference": parsed_preference,
            "teacher_name": row.get("teacher_name") or "",
            "department": row.get("department") or "",
        }
    return profiles


def fetch_allocation_task(connection, task_id: int) -> dict[str, Any] | None:
    """Get allocation task by id. Returns None if not found."""
    rows = fetch_all(
        connection,
        "SELECT id, name FROM allocation_task WHERE id = %s",
        (task_id,),
    )
    for row in rows:
        if int(row["id"]) == task_id:
            return row
    return None


def fetch_task_teaching_task_ids(connection, task_id: int) -> list[int]:
    """Get teaching task ids bound to an allocation task."""
    rows = fetch_all(
        connection,
        "SELECT teaching_task_id FROM allocation_task_teaching_task WHERE allocation_task_id = %s",
        (task_id,),
    )
    return [int(row["teaching_task_id"]) for row in rows]


def fetch_generation_config(connection, task_id: int) -> dict[str, Any] | None:
    """Get generation config for an allocation task. Returns None if not set."""
    rows = fetch_all(
        connection,
        """
        SELECT
            allowed_weeks, allowed_weekdays, allowed_periods,
            scheme_count,
            placement_top_k, raw_plan_count, cp_plan_count, solver_time_limit_seconds,
            generation_mode,
            teacher_profile_penalty_scale,
            early_period_penalty, late_period_penalty, weekend_penalty,
            model_weight, llm_weight,
            same_day_weight, capacity_waste_penalty,
            teacher_day_load_penalty, class_day_load_penalty,
            teacher_overload_penalty
        FROM allocation_task_generation_config
        WHERE task_id = %s
        """,
        (task_id,),
    )
    if not rows:
        return None
    return rows[0]
