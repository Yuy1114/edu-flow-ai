#!/usr/bin/env python3
"""Isolated Phase-1 formal scheduling acceptance test.

The target database must be disposable or explicitly dedicated to E2E work.
No cleanup is performed unless E2E_CLEAN_BEFORE/E2E_CLEAN_AFTER is true, and
cleanup additionally requires E2E_CONFIRM_CLEAN_DATABASE to exactly match
``host:port/database``.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pymysql
from pymysql.cursors import DictCursor


API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "edu_flow_ai")
DB_USERNAME = os.getenv("DB_USERNAME", "root")
DB_PASSWORD = os.environ["DB_PASSWORD"]
TERMINAL = {"SUCCESS", "NEEDS_MANUAL_REVIEW", "BLOCKED", "FAILED"}


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = Request(
        API_BASE + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            envelope = json.load(response)
    except HTTPError as exc:
        raise AssertionError(f"{method} {path} HTTP {exc.code}: {exc.read().decode()}") from exc
    if envelope.get("code") != 0:
        raise AssertionError(f"{method} {path}: {json.dumps(envelope, ensure_ascii=False)}")
    return envelope.get("data")


def db() -> pymysql.Connection:
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USERNAME,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def clean(label: str) -> dict[str, Any]:
    expected_target = f"{DB_HOST}:{DB_PORT}/{DB_NAME}"
    if os.getenv("E2E_CONFIRM_CLEAN_DATABASE") != expected_target:
        raise RuntimeError(
            "refusing E2E cleanup without an exact target confirmation: "
            f"set E2E_CONFIRM_CLEAN_DATABASE={expected_target}"
        )
    return api("POST", "/api/maintenance/cleanup-test-data", {
        "confirmText": "清理测试数据",
        "adminEmployeeNo": f"phase1-e2e-admin-{label}",
        "adminPassword": "test-only",
        "adminName": "Phase1 E2E Admin",
    })


def create_fixture(label: str) -> dict[str, int]:
    def create(path: str, payload: dict[str, Any]) -> int:
        return int(api("POST", path, payload)["id"])

    primary = create("/api/teachers", {
        "employeeNo": f"E2E-P-{label}", "password": "test-only", "role": "TEACHER",
        "name": "E2E主讲教师", "department": "计算机学院", "title": "讲师", "status": "ACTIVE",
    })
    assistant = create("/api/teachers", {
        "employeeNo": f"E2E-A-{label}", "password": "test-only", "role": "TEACHER",
        "name": "E2E助教", "department": "计算机学院", "title": "助教", "status": "ACTIVE",
    })
    lab_teacher = create("/api/teachers", {
        "employeeNo": f"E2E-L-{label}", "password": "test-only", "role": "TEACHER",
        "name": "E2E实验教师", "department": "计算机学院", "title": "实验师", "status": "ACTIVE",
    })
    matrix = [[-1 if period in (0, 1) and day == 0 else 0 for day in range(7)] for period in range(10)]
    api("PUT", f"/api/teachers/{primary}/profile", {
        "availabilityMatrixJson": json.dumps(matrix, separators=(",", ":")),
        "profileNote": None,
        "profilePreferenceJson": None,
    })

    class_ids = [create("/api/class-groups", {
        "name": f"E2E-软件工程{index}班-{label}", "major": "软件工程",
        "department": "计算机学院", "grade": "2025", "studentCount": 30,
    }) for index in (1, 2)]
    fixed_room = create("/api/classrooms", {
        "name": f"E2E-A101-{label}", "building": "A楼", "capacity": 80,
        "classroomType": "普通教室", "status": "ACTIVE",
    })
    create("/api/classrooms", {
        "name": f"E2E-A102-{label}", "building": "A楼", "capacity": 80,
        "classroomType": "普通教室", "status": "ACTIVE",
    })
    lab_rooms = [create("/api/classrooms", {
        "name": f"E2E-M20{index}-{label}", "building": "实验楼", "capacity": 80,
        "classroomType": "机房", "status": "ACTIVE",
    }) for index in (1, 2)]
    theory_course = create("/api/courses", {
        "name": f"E2E-软件工程导论-{label}", "courseType": "理论课",
        "requiredRoomType": "普通教室", "requiredHours": 12,
        "description": "正式链路E2E理论课", "status": "ACTIVE",
    })
    lab_course = create("/api/courses", {
        "name": f"E2E-程序设计实验-{label}", "courseType": "实验课",
        "requiredRoomType": "机房", "requiredHours": 12,
        "description": "正式链路E2E实验课", "status": "ACTIVE",
    })
    theory_task = create("/api/teaching-tasks", {
        "courseId": theory_course, "primaryTeacherId": primary,
        "assistantTeacherId": assistant, "classroomId": fixed_room,
        "totalHours": 12, "sessionsPerWeek": 1, "durationWeeks": 6,
        "requiredRoomType": "普通教室", "taskBatch": "PHASE1-E2E",
        "notes": "双班、助教、固定教室、主讲周一第1-2节禁排", "status": "ACTIVE",
        "classGroupIds": class_ids, "candidateClassroomIds": [],
    })
    lab_task = create("/api/teaching-tasks", {
        "courseId": lab_course, "primaryTeacherId": lab_teacher,
        "assistantTeacherId": None, "classroomId": None,
        "totalHours": 12, "sessionsPerWeek": 1, "durationWeeks": 3,
        "requiredRoomType": "机房", "taskBatch": "PHASE1-E2E",
        "notes": "双班、候选机房、4节连上", "status": "ACTIVE",
        "classGroupIds": class_ids, "candidateClassroomIds": lab_rooms,
    })
    allocation_task = create("/api/allocation-tasks", {
        "name": f"E2E正式排课-{label}", "description": "Phase1 formal chain E2E",
        "status": "CREATED", "createdBy": "e2e",
        "teachingTaskIds": [theory_task, lab_task],
        "generationConfig": {
            "allowedWeeks": "1,2,3,4,5,6", "allowedWeekdays": "1,2,3,4,5",
            "allowedPeriods": "1,2,3,4,5,6,7,8", "schemeCount": 1,
            "placementTopK": 20, "rawPlanCount": 20, "cpPlanCount": 20,
            "solverTimeLimitSeconds": 60, "generationMode": "FEASIBILITY",
        },
    })
    return {
        "primary": primary, "assistant": assistant, "labTeacher": lab_teacher,
        "class1": class_ids[0], "class2": class_ids[1], "fixedRoom": fixed_room,
        "labRoom1": lab_rooms[0], "labRoom2": lab_rooms[1],
        "theoryTask": theory_task, "labTask": lab_task, "allocationTask": allocation_task,
    }


def wait_for_generation(task_id: int) -> dict[str, Any]:
    api("POST", f"/api/allocation-tasks/{task_id}/templates/generate", {
        "totalWeeks": 6, "topK": 20, "maxTemplates": 8, "importDb": True,
    })
    deadline = time.monotonic() + int(os.getenv("E2E_TIMEOUT_SECONDS", "180"))
    while time.monotonic() < deadline:
        status = api("GET", f"/api/allocation-tasks/{task_id}/templates/generation-status")
        if status["status"] in TERMINAL:
            if status["status"] != "SUCCESS":
                raise AssertionError(json.dumps(status, ensure_ascii=False))
            return status
        time.sleep(0.5)
    raise TimeoutError("formal scheduling did not reach a terminal state")


def assert_database(fixture: dict[str, int], scheme_id: int) -> dict[str, Any]:
    with db() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) count FROM schema_migration WHERE version='013_validate_course_assignment_span'")
        assert cursor.fetchone()["count"] == 1
        cursor.execute("SELECT COUNT(*) count FROM schedule_template WHERE allocation_task_id=%s", fixture["allocationTask"])
        template_count = int(cursor.fetchone()["count"])
        cursor.execute("SELECT COUNT(*) count FROM schedule_template_week WHERE allocation_task_id=%s", fixture["allocationTask"])
        assert cursor.fetchone()["count"] == 6
        cursor.execute("""
            SELECT f.teaching_task_id, COUNT(DISTINCT fw.week_number) week_count,
                   GROUP_CONCAT(DISTINCT fw.week_number ORDER BY fw.week_number) exact_weeks
            FROM schedule_template_fragment f
            JOIN schedule_template_fragment_week fw ON fw.template_fragment_id=f.id
            WHERE f.allocation_task_id=%s GROUP BY f.teaching_task_id
        """, fixture["allocationTask"])
        exact_weeks = {row["teaching_task_id"]: row for row in cursor.fetchall()}
        assert exact_weeks[fixture["theoryTask"]]["week_count"] == 6
        assert exact_weeks[fixture["labTask"]]["week_count"] == 3
        cursor.execute("""
            SELECT f.teaching_task_id, MIN(x.cnt) min_count, MAX(x.cnt) max_count
            FROM schedule_template_fragment f
            JOIN (SELECT template_fragment_id,COUNT(*) cnt
                  FROM schedule_template_fragment_class_group GROUP BY template_fragment_id) x
              ON x.template_fragment_id=f.id
            WHERE f.allocation_task_id=%s GROUP BY f.teaching_task_id
        """, fixture["allocationTask"])
        assert all(row["min_count"] == row["max_count"] == 2 for row in cursor.fetchall())
        cursor.execute("""
            SELECT COUNT(*) count FROM schedule_template_fragment_teacher ft
            JOIN schedule_template_fragment f ON f.id=ft.template_fragment_id
            WHERE f.allocation_task_id=%s AND f.teaching_task_id=%s
              AND ft.teacher_id=%s AND ft.teacher_role='ASSISTANT'
        """, (fixture["allocationTask"], fixture["theoryTask"], fixture["assistant"]))
        assert cursor.fetchone()["count"] > 0
        cursor.execute("""
            SELECT COUNT(*) count FROM schedule_template_fragment_slot s
            JOIN schedule_template_fragment f ON f.id=s.template_fragment_id
            WHERE f.allocation_task_id=%s AND f.teaching_task_id=%s
              AND s.day_of_week=1 AND s.period_index IN (1,2)
        """, (fixture["allocationTask"], fixture["theoryTask"]))
        assert cursor.fetchone()["count"] == 0
        cursor.execute("""
            SELECT ca.id,ca.teaching_task_id,ca.classroom_id,ca.consecutive_slots,
                   ts.week_number,ts.day_of_week,ts.period_index
            FROM course_assignment ca JOIN time_slot ts ON ts.id=ca.time_slot_id
            WHERE ca.source_scheme_id=%s AND ca.status='ACTIVE' ORDER BY ca.id
        """, scheme_id)
        assignments = cursor.fetchall()
        assert len(assignments) == 9
        assert {row["consecutive_slots"] for row in assignments} == {2, 4}
        assert sum(row["consecutive_slots"] for row in assignments) == 24
        assert {row["classroom_id"] for row in assignments if row["teaching_task_id"] == fixture["theoryTask"]} == {fixture["fixedRoom"]}
        assert {row["classroom_id"] for row in assignments if row["teaching_task_id"] == fixture["labTask"]} <= {fixture["labRoom1"], fixture["labRoom2"]}
        cursor.execute("SELECT id,primary_teacher_id,assistant_teacher_id FROM teaching_task WHERE id IN (%s,%s)", (fixture["theoryTask"], fixture["labTask"]))
        teachers = {row["id"]: [value for value in (row["primary_teacher_id"], row["assistant_teacher_id"]) if value] for row in cursor.fetchall()}
        cursor.execute("SELECT teaching_task_id,class_group_id FROM teaching_task_class_group WHERE teaching_task_id IN (%s,%s)", (fixture["theoryTask"], fixture["labTask"]))
        classes: dict[int, list[int]] = {}
        for row in cursor.fetchall():
            classes.setdefault(row["teaching_task_id"], []).append(row["class_group_id"])

    occupied: dict[str, Counter[tuple[int, int, int, int]]] = {
        "teacher": Counter(), "class": Counter(), "room": Counter(),
    }
    for row in assignments:
        for offset in range(row["consecutive_slots"]):
            coordinate = (row["week_number"], row["day_of_week"], row["period_index"] + offset)
            occupied["room"][(row["classroom_id"], *coordinate)] += 1
            for teacher in teachers[row["teaching_task_id"]]:
                occupied["teacher"][(teacher, *coordinate)] += 1
            for class_group in classes[row["teaching_task_id"]]:
                occupied["class"][(class_group, *coordinate)] += 1
    collisions = {resource: sum(value > 1 for value in values.values()) for resource, values in occupied.items()}
    assert collisions == {"teacher": 0, "class": 0, "room": 0}
    return {
        "templateCount": template_count,
        "assignmentCount": len(assignments),
        "expandedAtomicPeriods": sum(row["consecutive_slots"] for row in assignments),
        "spans": sorted({row["consecutive_slots"] for row in assignments}),
        "collisions": collisions,
        "exactWeeks": {str(key): value["exact_weeks"] for key, value in exact_weeks.items()},
    }


def probe_manual_single_period(fixture: dict[str, int]) -> dict[str, Any]:
    """Prove the reserved weekend/evening slot supports a 1-period manual repair."""
    with db() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id,week_number,day_of_week,period_index
            FROM time_slot
            WHERE week_number=18 AND day_of_week=7 AND period_index=10
            """
        )
        target = cursor.fetchone()
    assert target is not None

    created = api("POST", "/api/course-assignments", {
        "sourceSchemeId": None,
        "teachingTaskId": fixture["theoryTask"],
        "classroomId": fixture["fixedRoom"],
        "timeSlotId": target["id"],
        "consecutiveSlots": 1,
        "status": None,
    })
    assignment = created["assignment"]
    assert assignment["consecutiveSlots"] == 1 and assignment["status"] == "ACTIVE"
    assert created["hourAudit"]["deltaTotalHours"] == 1
    assert created["hourAudit"]["mismatchTaskCount"] == 1

    cancelled = api("DELETE", f"/api/course-assignments/{assignment['id']}")
    assert cancelled["assignment"]["status"] == "INACTIVE"
    assert cancelled["hourAudit"]["deltaTotalHours"] == 0
    assert cancelled["hourAudit"]["mismatchTaskCount"] == 0

    with db() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT consecutive_slots,status FROM course_assignment WHERE id=%s",
            assignment["id"],
        )
        persisted = cursor.fetchone()
        assert persisted == {"consecutive_slots": 1, "status": "INACTIVE"}
        cursor.execute(
            """
            SELECT DISTINCT consecutive_slots
            FROM course_assignment
            WHERE teaching_task_id IN (%s,%s)
            ORDER BY consecutive_slots
            """,
            (fixture["theoryTask"], fixture["labTask"]),
        )
        observed_spans = [row["consecutive_slots"] for row in cursor.fetchall()]
        assert observed_spans == [1, 2, 4]

    return {
        "assignmentId": assignment["id"],
        "coordinate": {
            "weekNumber": target["week_number"],
            "dayOfWeek": target["day_of_week"],
            "periodIndex": target["period_index"],
        },
        "createdSpan": assignment["consecutiveSlots"],
        "createdStatus": assignment["status"],
        "hourDeltaWhileActive": created["hourAudit"]["deltaTotalHours"],
        "cancelledStatus": cancelled["assignment"]["status"],
        "hourDeltaAfterCancel": cancelled["hourAudit"]["deltaTotalHours"],
        "persistedSpans": observed_spans,
    }


def main() -> None:
    label = f"{int(time.time())}-{os.getpid()}"
    cleanup_before = None
    if os.getenv("E2E_CLEAN_BEFORE", "").lower() in {"1", "true", "yes"}:
        cleanup_before = clean(label)
    fixture = create_fixture(label)
    generation = wait_for_generation(fixture["allocationTask"])
    schemes = api("GET", f"/api/allocation-tasks/{fixture['allocationTask']}/schemes")
    assert len(schemes) == 1 and schemes[0]["status"] == "CANDIDATE"
    scheme_id = int(schemes[0]["id"])
    draft = api("GET", f"/api/allocation-schemes/{scheme_id}/template-draft")
    audit = draft["audit"]
    assert audit["valid"] and audit["reviewStatus"] == "COMPLETE"
    assert audit["hardConflictCount"] == 0 and audit["hourMismatchTaskCount"] == 0
    assert audit["requiredTotalHours"] == audit["scheduledTotalHours"] == 24
    confirmation = api("POST", f"/api/allocation-schemes/{scheme_id}/confirm", {})
    assert confirmation["assignmentCount"] == 9
    final_audit = api(
        "GET",
        f"/api/course-assignments/hour-audit?allocationTaskId={fixture['allocationTask']}",
    )
    assert final_audit["mismatchTaskCount"] == 0
    assert final_audit["requiredTotalHours"] == final_audit["scheduledTotalHours"] == 24
    database = assert_database(fixture, scheme_id)
    manual_single_period = probe_manual_single_period(fixture)
    report = {
        "status": "ok", "apiBaseUrl": API_BASE, "database": f"{DB_HOST}:{DB_PORT}/{DB_NAME}",
        "fixture": fixture, "generation": generation, "schemeId": scheme_id,
        "templateAudit": audit, "confirmation": confirmation,
        "finalHourAudit": final_audit, "databaseAssertions": database,
        "manualSinglePeriodProbe": manual_single_period,
        "cleanupBefore": cleanup_before,
    }
    report_path = os.getenv("E2E_REPORT_PATH")
    if report_path:
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.getenv("E2E_CLEAN_AFTER", "").lower() in {"1", "true", "yes"}:
        clean(label)


if __name__ == "__main__":
    main()
