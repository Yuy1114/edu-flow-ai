"""Audit base master data used by V3.5 scheduling.

Checks class groups, classrooms, courses, teachers, and teaching-task references.
The script is read-only and writes a JSON report for data-freeze decisions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402
from scheduler.paths import OUTPUT_DIR as PLACEMENT_OUTPUT_DIR  # noqa: E402

DEFAULT_REPORT_PATH = PLACEMENT_OUTPUT_DIR / "base_data_health_report.json"
ACTIVE_STATUS = "ACTIVE"
VALID_COURSE_TYPES = {"理论课", "上机课"}
VALID_ROOM_TYPES = {"普通教室", "机房", "实验室"}


def audit(*, report_path: Path = DEFAULT_REPORT_PATH) -> dict[str, Any]:
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            class_groups = _fetch(cur, "SELECT id, name, major, department, grade, student_count FROM class_group")
            classrooms = _fetch(cur, "SELECT id, name, building, capacity, classroom_type, status FROM classroom")
            courses = _fetch(cur, "SELECT id, name, code, credits, course_type, required_room_type, required_hours, status FROM course")
            teachers = _fetch(cur, "SELECT id, employee_no, name, department, title, status FROM teacher")
            teaching_refs = _fetch(cur, """
                SELECT
                    tt.id,
                    tt.course_id,
                    tt.primary_teacher_id,
                    tt.classroom_id,
                    tt.total_hours,
                    tt.required_room_type,
                    tt.task_batch,
                    tt.status,
                    c.id AS course_exists,
                    c.status AS course_status,
                    t.id AS teacher_exists,
                    t.status AS teacher_status,
                    cr.id AS classroom_exists,
                    cr.status AS classroom_status,
                    COUNT(ttcg.class_group_id) AS class_group_count
                FROM teaching_task tt
                LEFT JOIN course c ON c.id = tt.course_id
                LEFT JOIN teacher t ON t.id = tt.primary_teacher_id
                LEFT JOIN classroom cr ON cr.id = tt.classroom_id
                LEFT JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
                GROUP BY tt.id
            """)

        sections = {
            "class_groups": _audit_class_groups(class_groups),
            "classrooms": _audit_classrooms(classrooms),
            "courses": _audit_courses(courses),
            "teachers": _audit_teachers(teachers),
            "teaching_task_refs": _audit_teaching_refs(teaching_refs),
        }
        total_issues = sum(section["issue_count"] for section in sections.values())
        report = {
            "status": "ok" if total_issues == 0 else "issues_found",
            "summary": {
                "total_issues": total_issues,
                "class_group_count": len(class_groups),
                "classroom_count": len(classrooms),
                "course_count": len(courses),
                "teacher_count": len(teachers),
                "teaching_task_count": len(teaching_refs),
            },
            "sections": sections,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report
    finally:
        conn.close()


def _audit_class_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    issues.extend(_blank_issues(rows, "class_group", "name", "班级名称为空"))
    issues.extend(_duplicate_issues(rows, "class_group", "name", "班级名称重复"))
    for row in rows:
        if _safe_int(row.get("student_count")) <= 0:
            issues.append(_issue("class_group", row, "invalid_student_count", "班级人数必须大于0"))
        for field, message in [("major", "专业为空"), ("department", "院系为空"), ("grade", "年级为空")]:
            if _blank(row.get(field)):
                issues.append(_issue("class_group", row, f"blank_{field}", message))
    return _section(rows, issues)


def _audit_classrooms(rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    issues.extend(_blank_issues(rows, "classroom", "name", "教室名称为空"))
    issues.extend(_duplicate_issues(rows, "classroom", "name", "教室名称重复"))
    for row in rows:
        if _safe_int(row.get("capacity")) <= 0:
            issues.append(_issue("classroom", row, "invalid_capacity", "教室容量必须大于0"))
        if _blank(row.get("classroom_type")):
            issues.append(_issue("classroom", row, "blank_classroom_type", "教室类型为空"))
        elif str(row.get("classroom_type")) not in VALID_ROOM_TYPES:
            issues.append(_issue("classroom", row, "unknown_classroom_type", "教室类型不在约定集合内"))
        if str(row.get("status") or "") != ACTIVE_STATUS:
            issues.append(_issue("classroom", row, "inactive_status", "教室不是 ACTIVE 状态"))
    return _section(rows, issues, extra={"types": _counts(rows, "classroom_type")})


def _audit_courses(rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    issues.extend(_blank_issues(rows, "course", "name", "课程名称为空"))
    issues.extend(_blank_issues(rows, "course", "code", "课程代码为空"))
    issues.extend(_duplicate_issues(rows, "course", "code", "课程代码重复"))
    for row in rows:
        if _safe_float(row.get("credits")) <= 0:
            issues.append(_issue("course", row, "invalid_credits", "课程学分必须大于0"))
        if _safe_int(row.get("required_hours")) <= 0:
            issues.append(_issue("course", row, "invalid_required_hours", "课程课时必须大于0"))
        course_type = str(row.get("course_type") or "")
        if course_type not in VALID_COURSE_TYPES:
            issues.append(_issue("course", row, "unknown_course_type", "课程类型不在约定集合内"))
        required_room_type = str(row.get("required_room_type") or "")
        if required_room_type and required_room_type not in VALID_ROOM_TYPES:
            issues.append(_issue("course", row, "unknown_required_room_type", "课程要求教室类型不在约定集合内"))
        if str(row.get("status") or "") != ACTIVE_STATUS:
            issues.append(_issue("course", row, "inactive_status", "课程不是 ACTIVE 状态"))
    return _section(rows, issues, extra={"course_types": _counts(rows, "course_type"), "room_types": _counts(rows, "required_room_type")})


def _audit_teachers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    issues.extend(_blank_issues(rows, "teacher", "name", "教师姓名为空"))
    issues.extend(_duplicate_issues(rows, "teacher", "employee_no", "教师工号重复", skip_blank=True))
    for row in rows:
        if _blank(row.get("department")):
            issues.append(_issue("teacher", row, "blank_department", "教师院系为空"))
        if str(row.get("status") or "") != ACTIVE_STATUS:
            issues.append(_issue("teacher", row, "inactive_status", "教师不是 ACTIVE 状态"))
    return _section(rows, issues, extra={"departments": _counts(rows, "department")})


def _audit_teaching_refs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    for row in rows:
        if row.get("course_exists") is None:
            issues.append(_issue("teaching_task", row, "missing_course", "教学任务引用了不存在的课程"))
        elif str(row.get("course_status") or "") != ACTIVE_STATUS:
            issues.append(_issue("teaching_task", row, "inactive_course", "教学任务引用了非 ACTIVE 课程"))
        if row.get("teacher_exists") is None:
            issues.append(_issue("teaching_task", row, "missing_teacher", "教学任务引用了不存在的主讲教师"))
        elif str(row.get("teacher_status") or "") != ACTIVE_STATUS:
            issues.append(_issue("teaching_task", row, "inactive_teacher", "教学任务引用了非 ACTIVE 教师"))
        if row.get("classroom_id") is not None and row.get("classroom_exists") is None:
            issues.append(_issue("teaching_task", row, "missing_preferred_classroom", "教学任务指定了不存在的教室"))
        if row.get("classroom_exists") is not None and str(row.get("classroom_status") or "") != ACTIVE_STATUS:
            issues.append(_issue("teaching_task", row, "inactive_preferred_classroom", "教学任务指定了非 ACTIVE 教室"))
        if _safe_int(row.get("class_group_count")) <= 0:
            issues.append(_issue("teaching_task", row, "missing_class_group", "教学任务未绑定班级"))
        total_hours = _safe_int(row.get("total_hours"))
        if total_hours <= 0 or total_hours % 2 != 0:
            issues.append(_issue("teaching_task", row, "invalid_total_hours", "教学任务总课时必须为正偶数"))
        if _blank(row.get("task_batch")):
            issues.append(_issue("teaching_task", row, "blank_task_batch", "教学任务批次为空"))
    return _section(rows, issues, extra={"task_batches": _counts(rows, "task_batch"), "statuses": _counts(rows, "status")})


def _fetch(cur, sql: str) -> list[dict[str, Any]]:
    cur.execute(sql)
    return list(cur.fetchall())


def _section(rows: list[dict[str, Any]], issues: list[dict[str, Any]], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    data = {
        "row_count": len(rows),
        "issue_count": len(issues),
        "issue_counts": dict(Counter(issue["issue"] for issue in issues).most_common()),
        "issues_preview": issues[:100],
    }
    if extra:
        data.update(extra)
    return data


def _blank_issues(rows: list[dict[str, Any]], entity: str, field: str, message: str) -> list[dict[str, Any]]:
    return [_issue(entity, row, f"blank_{field}", message) for row in rows if _blank(row.get(field))]


def _duplicate_issues(rows: list[dict[str, Any]], entity: str, field: str, message: str, *, skip_blank: bool = False) -> list[dict[str, Any]]:
    values = [str(row.get(field) or "").strip() for row in rows]
    duplicated = {value for value, count in Counter(values).items() if count > 1 and (value or not skip_blank)}
    return [_issue(entity, row, f"duplicate_{field}", message, {field: row.get(field)}) for row in rows if str(row.get(field) or "").strip() in duplicated]


def _issue(entity: str, row: dict[str, Any], issue: str, message: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    data = {
        "entity": entity,
        "id": row.get("id"),
        "name": row.get("name"),
        "issue": issue,
        "message": message,
    }
    if extra:
        data.update(extra)
    return data


def _counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field) or "").strip() or "<blank>" for row in rows).items()))


def _blank(value: Any) -> bool:
    return str(value or "").strip() == ""


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit base master data for V3.5 scheduling.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()
    result = audit(report_path=Path(args.report))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
