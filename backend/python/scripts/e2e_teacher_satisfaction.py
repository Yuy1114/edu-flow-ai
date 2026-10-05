"""真机校验：教师声明画像 → 排课 → 方案级满足度落库 → 方案详情读数一致。

与前两个 E2E 脚本的分工：那些验的是第一阶段正式排课链路，这个只验画像满足度这条：
Java 装配画像 → 作业 payload → Python 排序 → 导出/导入 → `schedule_teacher_satisfaction`
→ `/api/allocation-schemes/{id}/template-draft` 的 satisfaction 块。

刻意用真实 MySQL 而不是假连接：假连接验的是列名对不对，这里验的是"真库能存、页面能读、
两处读数一致"。fixture 自己造、不自清理，可在同一个库上重复执行。

用法（必须在隔离库上跑，端口别用生产那台）：
    E2E_CONFIRM_TARGET=127.0.0.1:3316/edu_flow_ai \\
    API_BASE_URL=http://127.0.0.1:8080 DB_HOST=127.0.0.1 DB_PORT=3316 \\
    DB_NAME=edu_flow_ai DB_USERNAME=root DB_PASSWORD=*** \\
    backend/python/.venv/bin/python backend/python/scripts/e2e_teacher_satisfaction.py
"""

from __future__ import annotations

import json
import os
import time
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
LOW_THRESHOLD = 0.7
REPORT_COMPONENTS = (
    "early_period", "late_period", "preferred_weekday",
    "preferred_period", "daily_load", "room_type",
)

# 排课引擎里的画像维度名 → 教师声明里的键，用来核对"声明了什么"。
DECLARED_TO_COMPONENT = {
    "avoidFirstPeriod": "early_period",
    "avoidLastPeriod": "late_period",
    "preferredWeekdays": "preferred_weekday",
    "preferredPeriods": "preferred_period",
    "preferredMaxDailyHours": "daily_load",
}


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = Request(API_BASE + path, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            envelope = json.load(response)
    except HTTPError as exc:
        raise AssertionError(f"{method} {path} HTTP {exc.code}: {exc.read().decode()}") from exc
    if envelope.get("code") != 0:
        raise AssertionError(f"{method} {path}: {json.dumps(envelope, ensure_ascii=False)}")
    return envelope.get("data")


def db() -> pymysql.Connection:
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USERNAME, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4", cursorclass=DictCursor, autocommit=True,
    )


def require_isolated_target() -> None:
    expected = f"{DB_HOST}:{DB_PORT}/{DB_NAME}"
    if os.getenv("E2E_CONFIRM_TARGET") != expected:
        raise RuntimeError(
            "拒绝在未确认的库上跑真机校验（会写新数据）："
            f"请设置 E2E_CONFIRM_TARGET={expected}"
        )


def matrix(rows: int = 11) -> str:
    """全 0 可用性矩阵：可行性交给引擎默认，避免本脚本顺手测了不可用矩阵。

    行数跟当前时间轴一致（ADR 0001 修订后是 11 节，18×7×11=1386）。
    """
    return json.dumps([[0 for _ in range(7)] for _ in range(rows)], separators=(",", ":"))


def create_fixture(label: str) -> dict[str, Any]:
    def create(path: str, payload: dict[str, Any]) -> int:
        return int(api("POST", path, payload)["id"])

    def teacher(name: str, suffix: str, preference: dict[str, Any] | None) -> int:
        teacher_id = create("/api/teachers", {
            "employeeNo": f"E2E-SAT-{suffix}-{label}", "password": "test-only", "role": "TEACHER",
            "name": name, "department": "计算机学院", "title": "讲师", "status": "ACTIVE",
        })
        api("PUT", f"/api/teachers/{teacher_id}/profile", {
            "availabilityMatrixJson": matrix(),
            "profileNote": None,
            # profile_preference_json 存的就是偏好对象本身：Java 侧会把它包成
            # payload.preference 再归一化成 avoid_early_period / preferred_weekdays 等。
            # 这里再套一层 {"preference": ...} 会让画像解析成空，整条链路静默不带画像。
            "profilePreferenceJson": None if preference is None else json.dumps(preference),
        })
        return teacher_id

    # 主讲：要求周六 + 避早课，而任务允许的星期是 1~5 —— 真实场景里"提了但满足不了"的那类。
    primary = teacher(f"E2E满足度主讲-{label}", "P", {"preferredWeekdays": [6], "avoidFirstPeriod": True})
    # 助教：只提了星期 1~2，大概率被满足，用来对照"不是所有人都低"。
    assistant = teacher(f"E2E满足度助教-{label}", "A", {"preferredWeekdays": [1, 2]})
    # 实验教师：完全没声明画像 —— 不该出现在满足度表里。
    lab_teacher = teacher(f"E2E满足度实验教师-{label}", "L", None)

    class_ids = [create("/api/class-groups", {
        "name": f"E2E满足度{index}班-{label}", "major": "软件工程",
        "department": "计算机学院", "grade": "2025", "studentCount": 30,
    }) for index in (1, 2)]
    rooms = [create("/api/classrooms", {
        "name": f"E2E-SAT-{suffix}-{label}", "building": "A楼", "capacity": 80,
        "classroomType": "普通教室", "status": "ACTIVE",
    }) for suffix in ("101", "102")]
    theory_course = create("/api/courses", {
        "name": f"E2E满足度理论课-{label}", "courseType": "理论课",
        "requiredRoomType": "普通教室", "requiredHours": 12,
        "description": "满足度真机校验理论课", "status": "ACTIVE",
    })
    theory_task = create("/api/teaching-tasks", {
        "courseId": theory_course, "primaryTeacherId": primary, "assistantTeacherId": assistant,
        "classroomId": None, "totalHours": 12, "sessionsPerWeek": 1, "durationWeeks": 6,
        "requiredRoomType": "普通教室", "taskBatch": "E2E-SAT", "notes": "满足度真机校验",
        "status": "ACTIVE", "classGroupIds": class_ids, "candidateClassroomIds": rooms,
    })
    allocation_task = create("/api/allocation-tasks", {
        "name": f"E2E满足度排课-{label}", "description": "teacher satisfaction E2E",
        "status": "CREATED", "createdBy": "e2e",
        "teachingTaskIds": [theory_task],
        "generationConfig": {
            "allowedWeeks": "1,2,3,4,5,6", "allowedWeekdays": "1,2,3,4,5",
            "allowedPeriods": "1,2,3,4,5,6,7,8", "schemeCount": 1,
            "placementTopK": 20, "rawPlanCount": 20, "cpPlanCount": 20,
            "solverTimeLimitSeconds": 60, "generationMode": "FEASIBILITY",
        },
    })
    return {
        "primary": primary, "assistant": assistant, "labTeacher": lab_teacher,
        "theoryTask": theory_task, "allocationTask": allocation_task,
        "declaredTeacherIds": [primary, assistant],
        "primaryName": f"E2E满足度主讲-{label}",
        "undeclaredTeacherId": lab_teacher,
    }


def wait_for_generation(task_id: int) -> dict[str, Any]:
    """提交生成作业并轮询到终态，顺带量一下"按下生成到状态终态"的整条链路耗时。"""
    started = time.monotonic()
    api("POST", f"/api/allocation-tasks/{task_id}/templates/generate", {
        "totalWeeks": 6, "topK": 20, "maxTemplates": 8, "importDb": True,
    })
    deadline = started + int(os.getenv("E2E_TIMEOUT_SECONDS", "300"))
    while time.monotonic() < deadline:
        status = api("GET", f"/api/allocation-tasks/{task_id}/templates/generation-status")
        if status["status"] in TERMINAL:
            if status["status"] != "SUCCESS":
                raise AssertionError(json.dumps(status, ensure_ascii=False))
            return {**status, "jobSeconds": round(time.monotonic() - started, 3)}
        time.sleep(1)
    raise TimeoutError("V3.5 generation did not reach a terminal state")


def assert_rows(fixture: dict[str, Any], scheme: dict[str, Any]) -> dict[str, Any]:
    with db() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT generation_run_id FROM schedule_template WHERE allocation_task_id=%s ORDER BY id DESC LIMIT 1",
            (fixture["allocationTask"],),
        )
        run_row = cursor.fetchone()
        assert run_row, "本次 run 没有模板，无法核对满足度行"
        run_id = run_row["generation_run_id"]
        cursor.execute(
            "SELECT template_code FROM schedule_template WHERE allocation_task_id=%s AND generation_run_id=%s",
            (fixture["allocationTask"], run_id),
        )
        template_codes = {row["template_code"] for row in cursor.fetchall()}
        assert template_codes, "本次 run 没有模板，无法核对满足度行"

        cursor.execute("""
            SELECT id, template_code, teacher_key, teacher_id, teacher_name, item_count, days_used,
                   satisfaction_score, preference_score, low_satisfaction,
                   declared_dimensions_json, components_json, evidence_json
            FROM schedule_teacher_satisfaction
            WHERE allocation_task_id=%s AND generation_run_id=%s
        """, (fixture["allocationTask"], run_id))
        rows = cursor.fetchall()

    assert rows, "满足度表里没有行：画像既没进引擎，也没落库"
    assert {row["template_code"] for row in rows} <= template_codes, "满足度行挂到了不存在的模板上"
    assert {row["template_code"] for row in rows} == template_codes, "并非每个模板都有满足度行"

    assert not [row for row in rows if row["teacher_id"] == fixture["undeclaredTeacherId"]], (
        "没声明画像的教师不该出现在满足度表里"
    )

    for row in rows:
        assert 0.0 <= float(row["satisfaction_score"]) <= 1.0, f"满足度越界：{row}"
        assert 0.0 <= float(row["preference_score"]) <= 1.0, f"偏好满足度越界：{row}"
        assert int(row["item_count"]) > 0, f"排课量为 0 却出现在表里：{row}"
        assert bool(row["low_satisfaction"]) == (float(row["preference_score"]) < LOW_THRESHOLD), (
            f"低满足标记与偏好满足度不一致：{row}"
        )
        declared = json.loads(row["declared_dimensions_json"])
        components = json.loads(row["components_json"])
        json.loads(row["evidence_json"])
        assert declared and set(declared) <= set(REPORT_COMPONENTS), f"声明维度异常：{row}"

    low_rows = [row for row in rows if row["low_satisfaction"]]
    low_teachers = {row["teacher_key"] for row in low_rows}
    primary_rows = [row for row in rows if row["teacher_id"] == fixture["primary"]]
    assert primary_rows, "要求周六的主讲没有出现在满足度表里"
    assert all(row["low_satisfaction"] for row in primary_rows), (
        "要求周六（允许星期 1~5）的主讲应被判为低满足，实际："
        + json.dumps(primary_rows, ensure_ascii=False, default=str)
    )
    return {
        "runId": run_id,
        "templateCount": len(template_codes),
        "rowCount": len(rows),
        "teacherCount": len({row["teacher_key"] for row in rows}),
        "lowRowCount": len(low_rows),
        "lowTeacherCount": len(low_teachers),
        "primaryPreferenceScore": float(primary_rows[0]["preference_score"]),
        "primaryReasonFromDb": min(
            json.loads(primary_rows[0]["declared_dimensions_json"]),
            key=lambda name: json.loads(primary_rows[0]["components_json"]).get(name, 1.0),
        ),
        "sampleLowRow": {
            key: primary_rows[0][key] for key in (
                "template_code", "teacher_name", "item_count",
                "satisfaction_score", "preference_score", "low_satisfaction",
            )
        },
    }


def assert_draft_view(fixture: dict[str, Any], scheme: dict[str, Any], rows: dict[str, Any]) -> dict[str, Any]:
    draft = api("GET", f"/api/allocation-schemes/{scheme['id']}/template-draft")
    satisfaction = draft.get("satisfaction") or {}
    assert satisfaction.get("profileApplied") is True, "方案详情没有拿到画像满足度（profileApplied 不为 true）"
    assert satisfaction["teacherCount"] == rows["teacherCount"], (
        f"页面教师数与库内不一致：{satisfaction['teacherCount']} vs {rows['teacherCount']}"
    )
    assert satisfaction["lowSatisfactionCount"] == rows["lowTeacherCount"], (
        f"页面低满足教师数与库内不一致：{satisfaction['lowSatisfactionCount']} vs {rows['lowTeacherCount']}"
    )
    assert len(satisfaction["lowSatisfactionTeachers"]) == satisfaction["lowSatisfactionCount"], (
        "低满足明细条数与低满足教师数不一致"
    )

    primary_low = [entry for entry in satisfaction["lowSatisfactionTeachers"]
                   if entry["teacherId"] == fixture["primary"]]
    assert primary_low, "页面低满足明细里没有要求周六的主讲"
    entry = primary_low[0]
    assert entry["primaryReasonDimension"] in entry["declaredDimensions"], "主因不在已声明维度里"
    assert entry["primaryReasonDimension"] == rows["primaryReasonFromDb"], (
        f"页面主因与库内最弱维度不一致：{entry['primaryReasonDimension']} vs {rows['primaryReasonFromDb']}"
    )
    assert abs(float(entry["preferenceScore"]) - rows["primaryPreferenceScore"]) < 1e-9, "页面分数与库内不一致"

    # 页面按教师聚合再平均：与库内逐行分数按人平均的结果必须对上。
    with db() as connection, connection.cursor() as cursor:
        cursor.execute("""
            SELECT teacher_key, AVG(preference_score) preference_score, AVG(satisfaction_score) satisfaction_score
            FROM schedule_teacher_satisfaction
            WHERE allocation_task_id=%s AND generation_run_id=%s GROUP BY teacher_key
        """, (fixture["allocationTask"], rows["runId"]))
        per_teacher = cursor.fetchall()
    expected_preference = sum(float(row["preference_score"]) for row in per_teacher) / len(per_teacher)
    expected_satisfaction = sum(float(row["satisfaction_score"]) for row in per_teacher) / len(per_teacher)
    assert abs(float(satisfaction["averagePreferenceScore"]) - expected_preference) < 1e-3, (
        f"页面平均偏好满足度对不上：{satisfaction['averagePreferenceScore']} vs {expected_preference}"
    )
    assert abs(float(satisfaction["averageSatisfactionScore"]) - expected_satisfaction) < 1e-3, (
        f"页面平均满足度对不上：{satisfaction['averageSatisfactionScore']} vs {expected_satisfaction}"
    )
    return {
        "profileApplied": satisfaction["profileApplied"],
        "teacherCount": satisfaction["teacherCount"],
        "lowSatisfactionCount": satisfaction["lowSatisfactionCount"],
        "averagePreferenceScore": satisfaction["averagePreferenceScore"],
        "averageSatisfactionScore": satisfaction["averageSatisfactionScore"],
        "lowSample": {
            key: entry[key] for key in (
                "templateCode", "teacherName", "declaredDimensions",
                "primaryReasonDimension", "primaryReasonScore", "preferenceScore", "lowSatisfaction",
            )
        },
    }


def assert_run_evidence(run_id: str) -> dict[str, Any]:
    """作业目录里的证据：画像确实作为输入进了这次生成。

    目录名是 `runs/<时间戳>_<run_id 末段>`，与库里的 generation_run_id 不同名，按末段匹配。
    """
    runs_dir = Path(__file__).resolve().parents[2] / "data" / "pipeline" / "v3.5" / "runs"
    suffix = run_id.rsplit("-", 1)[-1]
    candidates = sorted(runs_dir.glob(f"*_{suffix}"), key=lambda path: path.name)
    if not candidates:
        return {"runDir": None, "found": False, "runId": run_id}
    directory = candidates[-1]
    report_path = directory / "phase_cover_report.json"
    profiles_path = directory / "teacher_profiles.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    satisfaction = report.get("profile_satisfaction") or {}
    assert satisfaction.get("profile_applied") is True, (
        f"cover-report 里画像未生效：{directory}"
    )
    assert profiles_path.exists(), f"作业目录里没有 teacher_profiles.json：{directory}"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    assert profiles, "teacher_profiles.json 是空的（画像输入不可复现）"
    return {
        "runDir": str(directory),
        "found": True,
        "profileApplied": True,
        "profileCount": len(profiles),
        "templateReports": len(report.get("profile_satisfaction_templates") or {}),
        "rankedFragmentCount": satisfaction.get("ranked_fragment_count"),
    }


def main() -> None:
    require_isolated_target()
    label = f"{int(time.time())}-{os.getpid()}"
    fixture = create_fixture(label)
    generation = wait_for_generation(fixture["allocationTask"])
    schemes = api("GET", f"/api/allocation-tasks/{fixture['allocationTask']}/schemes")
    assert len(schemes) == 1, f"期望 1 个方案，实际 {len(schemes)}"
    scheme = schemes[0]
    rows = assert_rows(fixture, scheme)
    view = assert_draft_view(fixture, scheme, rows)
    evidence = assert_run_evidence(rows["runId"])
    report = {
        "status": "ok",
        "apiBaseUrl": API_BASE,
        "database": f"{DB_HOST}:{DB_PORT}/{DB_NAME}",
        "fixture": fixture,
        "generation": {"status": generation["status"], "jobSeconds": generation.get("jobSeconds")},
        "schemeId": scheme["id"],
        "runId": rows["runId"],
        "rows": rows,
        "draftView": view,
        "runEvidence": evidence,
    }
    report_path = os.getenv("E2E_REPORT_PATH")
    if report_path:
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
