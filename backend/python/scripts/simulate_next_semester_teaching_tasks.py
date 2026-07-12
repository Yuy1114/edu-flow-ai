"""Create next-semester simulated teaching tasks by shuffling course/teacher/class assignments.

The script is dry-run by default. Use --execute to insert cloned teaching_task rows.
It never mutates source teaching tasks.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import connect, load_db_config  # noqa: E402


@dataclass(frozen=True)
class SourceTask:
    id: int
    course_id: int
    primary_teacher_id: int
    assistant_teacher_id: int | None
    classroom_id: int | None
    total_hours: int
    required_room_type: str | None
    class_group_ids: tuple[int, ...]


@dataclass(frozen=True)
class CourseInfo:
    id: int
    required_hours: int | None
    required_room_type: str | None


@dataclass(frozen=True)
class SimTask:
    source_task_id: int
    course_id: int
    primary_teacher_id: int
    class_group_ids: tuple[int, ...]
    total_hours: int
    required_room_type: str | None

    @property
    def signature(self) -> tuple[int, int, tuple[int, ...]]:
        return (self.course_id, self.primary_teacher_id, self.class_group_ids)


def simulate(
    *,
    execute: bool,
    seed: int,
    limit: int | None,
    create_allocation_task: bool,
    allocation_task_name: str | None,
    run_id: str | None,
) -> dict[str, Any]:
    run_id = run_id or datetime.now().strftime("SIM-NEXT-%Y%m%d%H%M%S")
    conn = connect(load_db_config())
    try:
        source_tasks = _load_source_tasks(conn, limit=limit)
        courses = _load_courses(conn)
        teacher_ids = _load_teacher_ids(conn)
        class_sets = [task.class_group_ids for task in source_tasks if task.class_group_ids]
        existing_signatures = _load_existing_signatures(conn)

        generated = _generate_tasks(
            source_tasks=source_tasks,
            courses=courses,
            teacher_ids=teacher_ids,
            class_sets=class_sets,
            existing_signatures=existing_signatures,
            seed=seed,
        )

        report: dict[str, Any] = {
            "status": "dry_run" if not execute else "executed",
            "run_id": run_id,
            "source_task_count": len(source_tasks),
            "generated_task_count": len(generated),
            "unique_generated_signatures": len({task.signature for task in generated}),
            "duplicate_generated_signatures": len(generated) - len({task.signature for task in generated}),
            "would_create_allocation_task": create_allocation_task,
            "sample": [_preview_task(conn, task) for task in generated[:8]],
        }

        if not execute:
            return report

        new_task_ids = _insert_generated_tasks(conn, generated, run_id=run_id)
        allocation_task_id = None
        if create_allocation_task:
            allocation_task_id = _create_allocation_task(
                conn,
                name=allocation_task_name or f"下学期模拟分课任务 {run_id}",
                teaching_task_ids=new_task_ids,
            )
        conn.commit()
        report["inserted_task_count"] = len(new_task_ids)
        report["new_task_id_range"] = [min(new_task_ids), max(new_task_ids)] if new_task_ids else []
        report["allocation_task_id"] = allocation_task_id
        return report
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cleanup(*, run_id: str, execute: bool) -> dict[str, Any]:
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM teaching_task WHERE task_batch = %s",
                (run_id,),
            )
            task_ids = [int(row["id"]) for row in cur.fetchall()]
            report = {"status": "dry_run" if not execute else "executed", "run_id": run_id, "matched_task_count": len(task_ids)}
            cur.execute("SELECT id FROM allocation_task WHERE name LIKE %s", (f"%{run_id}%",))
            allocation_task_ids = [int(row["id"]) for row in cur.fetchall()]
            report["matched_allocation_task_count"] = len(allocation_task_ids)
            if not execute:
                return report
            if task_ids:
                placeholders = ",".join(["%s"] * len(task_ids))
                cur.execute(f"DELETE FROM allocation_task_teaching_task WHERE teaching_task_id IN ({placeholders})", task_ids)
                cur.execute(f"DELETE FROM teaching_task_class_group WHERE teaching_task_id IN ({placeholders})", task_ids)
                cur.execute(f"DELETE FROM teaching_task WHERE id IN ({placeholders})", task_ids)
            if allocation_task_ids:
                placeholders = ",".join(["%s"] * len(allocation_task_ids))
                cur.execute(f"DELETE FROM allocation_task_teaching_task WHERE allocation_task_id IN ({placeholders})", allocation_task_ids)
                cur.execute(f"DELETE FROM allocation_task WHERE id IN ({placeholders})", allocation_task_ids)
        conn.commit()
        return report
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_source_tasks(conn, *, limit: int | None) -> list[SourceTask]:
    sql = """
        SELECT tt.id, tt.course_id, tt.primary_teacher_id, tt.assistant_teacher_id,
               tt.classroom_id, tt.total_hours, tt.required_room_type,
               GROUP_CONCAT(ttcg.class_group_id ORDER BY ttcg.class_group_id) AS class_group_ids
        FROM teaching_task tt
        JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
        WHERE tt.status = 'ACTIVE'
          AND COALESCE(tt.task_batch, 'DEFAULT') = 'DEFAULT'
        GROUP BY tt.id
        ORDER BY tt.id
    """
    if limit:
        sql += " LIMIT %s"
    with conn.cursor() as cur:
        cur.execute(sql, (limit,) if limit else None)
        rows = cur.fetchall()
    return [
        SourceTask(
            id=int(row["id"]),
            course_id=int(row["course_id"]),
            primary_teacher_id=int(row["primary_teacher_id"]),
            assistant_teacher_id=int(row["assistant_teacher_id"]) if row.get("assistant_teacher_id") else None,
            classroom_id=int(row["classroom_id"]) if row.get("classroom_id") else None,
            total_hours=int(row["total_hours"]),
            required_room_type=row.get("required_room_type"),
            class_group_ids=tuple(int(x) for x in str(row["class_group_ids"]).split(",") if x),
        )
        for row in rows
    ]


def _load_courses(conn) -> list[CourseInfo]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, required_hours, required_room_type FROM course WHERE status = 'ACTIVE' ORDER BY id")
        rows = cur.fetchall()
    return [CourseInfo(int(row["id"]), row.get("required_hours"), row.get("required_room_type")) for row in rows]


def _load_teacher_ids(conn) -> list[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM teacher WHERE status = 'ACTIVE' ORDER BY id")
        return [int(row["id"]) for row in cur.fetchall()]


def _load_existing_signatures(conn) -> set[tuple[int, int, tuple[int, ...]]]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tt.course_id, tt.primary_teacher_id,
                   GROUP_CONCAT(ttcg.class_group_id ORDER BY ttcg.class_group_id) AS class_group_ids
            FROM teaching_task tt
            JOIN teaching_task_class_group ttcg ON ttcg.teaching_task_id = tt.id
            WHERE tt.status = 'ACTIVE'
            GROUP BY tt.id
        """)
        rows = cur.fetchall()
    return {
        (int(row["course_id"]), int(row["primary_teacher_id"]), tuple(int(x) for x in str(row["class_group_ids"]).split(",") if x))
        for row in rows
    }


def _generate_tasks(
    *,
    source_tasks: list[SourceTask],
    courses: list[CourseInfo],
    teacher_ids: list[int],
    class_sets: list[tuple[int, ...]],
    existing_signatures: set[tuple[int, int, tuple[int, ...]]],
    seed: int,
) -> list[SimTask]:
    rng = random.Random(seed)
    course_pool = courses[:]
    teacher_pool = teacher_ids[:]
    class_pool = class_sets[:]
    rng.shuffle(course_pool)
    rng.shuffle(teacher_pool)
    rng.shuffle(class_pool)

    generated: list[SimTask] = []
    used = set(existing_signatures)
    generated_only = set()

    for index, source in enumerate(source_tasks):
        task = _pick_unique_task(
            source=source,
            index=index,
            course_pool=course_pool,
            teacher_pool=teacher_pool,
            class_pool=class_pool,
            used=used,
        )
        used.add(task.signature)
        generated_only.add(task.signature)
        generated.append(task)
    return generated


def _pick_unique_task(
    *,
    source: SourceTask,
    index: int,
    course_pool: list[CourseInfo],
    teacher_pool: list[int],
    class_pool: list[tuple[int, ...]],
    used: set[tuple[int, int, tuple[int, ...]]],
) -> SimTask:
    for offset in range(max(len(course_pool), len(teacher_pool), len(class_pool)) * 4):
        course = course_pool[(index + offset) % len(course_pool)]
        teacher_id = teacher_pool[(index * 3 + offset) % len(teacher_pool)]
        class_group_ids = class_pool[(index * 5 + offset) % len(class_pool)]
        total_hours = int(course.required_hours or source.total_hours)
        required_room_type = course.required_room_type or source.required_room_type
        candidate = SimTask(
            source_task_id=source.id,
            course_id=course.id,
            primary_teacher_id=teacher_id,
            class_group_ids=class_group_ids,
            total_hours=total_hours,
            required_room_type=required_room_type,
        )
        if candidate.signature not in used:
            return candidate
    raise RuntimeError(f"无法为源教学任务 {source.id} 生成唯一模拟任务")


def _insert_generated_tasks(conn, tasks: list[SimTask], *, run_id: str) -> list[int]:
    new_ids: list[int] = []
    with conn.cursor() as cur:
        for task in tasks:
            cur.execute(
                """
                INSERT INTO teaching_task
                    (course_id, primary_teacher_id, assistant_teacher_id, classroom_id,
                     total_hours, required_room_type, task_batch, notes, status)
                VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s, 'ACTIVE')
                """,
                (
                    task.course_id,
                    task.primary_teacher_id,
                    task.total_hours,
                    task.required_room_type,
                    run_id,
                    f"[SIM_NEXT_SEMESTER:{run_id}] cloned from teaching_task#{task.source_task_id}",
                ),
            )
            cur.execute("SELECT LAST_INSERT_ID() AS id")
            new_id = int(cur.fetchone()["id"])
            new_ids.append(new_id)
            for class_group_id in task.class_group_ids:
                cur.execute(
                    "INSERT INTO teaching_task_class_group (teaching_task_id, class_group_id) VALUES (%s, %s)",
                    (new_id, class_group_id),
                )
    return new_ids


def _create_allocation_task(conn, *, name: str, teaching_task_ids: list[int]) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO allocation_task (name) VALUES (%s)", (name,))
        cur.execute("SELECT LAST_INSERT_ID() AS id")
        allocation_task_id = int(cur.fetchone()["id"])
        for teaching_task_id in teaching_task_ids:
            cur.execute(
                "INSERT INTO allocation_task_teaching_task (allocation_task_id, teaching_task_id) VALUES (%s, %s)",
                (allocation_task_id, teaching_task_id),
            )
    return allocation_task_id


def _preview_task(conn, task: SimTask) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT name, code FROM course WHERE id = %s", (task.course_id,))
        course = cur.fetchone()
        cur.execute("SELECT name FROM teacher WHERE id = %s", (task.primary_teacher_id,))
        teacher = cur.fetchone()
        placeholders = ",".join(["%s"] * len(task.class_group_ids))
        cur.execute(f"SELECT name FROM class_group WHERE id IN ({placeholders}) ORDER BY id", task.class_group_ids)
        classes = [row["name"] for row in cur.fetchall()]
    return {
        "source_task_id": task.source_task_id,
        "course": f"{course['name']}({course['code']})" if course else task.course_id,
        "teacher": teacher["name"] if teacher else task.primary_teacher_id,
        "classes": classes,
        "total_hours": task.total_hours,
        "required_room_type": task.required_room_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate next-semester teaching tasks by shuffling existing assignments.")
    parser.add_argument("--execute", action="store_true", help="Actually insert simulated teaching tasks.")
    parser.add_argument("--seed", type=int, default=20260609, help="Deterministic shuffle seed.")
    parser.add_argument("--limit", type=int, default=None, help="Only simulate the first N source tasks.")
    parser.add_argument("--create-allocation-task", action="store_true", help="Create an allocation_task bound to inserted simulated teaching tasks.")
    parser.add_argument("--allocation-task-name", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--cleanup-run-id", default=None, help="Delete simulated teaching tasks created by a previous run id.")
    args = parser.parse_args()

    if args.cleanup_run_id:
        result = cleanup(run_id=args.cleanup_run_id, execute=args.execute)
    else:
        result = simulate(
            execute=args.execute,
            seed=args.seed,
            limit=args.limit,
            create_allocation_task=args.create_allocation_task,
            allocation_task_name=args.allocation_task_name,
            run_id=args.run_id,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
