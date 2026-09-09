"""从分班课表还原真实教学任务，并识别合班。

学校导出的 Excel 是**一个班一份课表**。同一次合班授课，会在参与的每个班的
课表里各出现一次。直接把每份课表的每门课当成一个教学任务，就是 `CONTEXT.md`
明确要避免的"分班课表行"——同一次授课被数了 N 遍，容量、教师负载、课时统计
全都跟着错 N 倍。

还原分两步：

1. **合并成授课事件**。物理上，同一学期、同一课程、同一教室、同一周同一星期
   同一节次，只可能是一次课。参与班级取并集，教师取并集。教师**不进匹配键**——
   有 285 处同一节课在不同班的课表里记了不同教师名，把教师放进键会把一次课
   拆成两次。
2. **合并成教学任务**。键是 `(学期, 课程代码, 班级集合)`。班级集合必须进键：
   `大学英语` 这类课有多个平行班，同一课程代码下是多个互不相干的教学任务。
   实测这个键下每个任务的教师集合都唯一，说明键选对了。

合班判定因此是**结果而不是输入**：一个任务关联几个班，是从时间-教室-课程的
重合关系里推出来的，不依赖课表里任何"合班"标注（原始数据里也没有）。

容量口径：合班需要的教室要装得下所有班人数之和，所以 `student_count_total`
按班级求和。有约一成班级没有人数，此时标 `student_count_complete=false`，
不猜。
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ingest.label_training_scope import judge_scope

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset" / "_combined"
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset" / "_tasks"

SESSION_FIELDS = [
    "session_id", "source_semester", "course_code", "course_name",
    "classroom_name", "week_index", "day_of_week", "period_index", "consecutive_slots",
    "class_count", "class_names", "teacher_count", "teacher_names",
    "teacher_name_conflict", "task_id",
]

TASK_FIELDS = [
    "task_id", "source_semester", "course_code", "course_name",
    "course_type", "required_room_type",
    "class_count", "class_names", "is_joint_class",
    "student_count_total", "student_count_complete",
    "teacher_count", "primary_teacher", "assistant_teachers",
    "session_count", "total_periods", "active_week_count", "peak_sessions_per_week",
    "room_count", "rooms", "rhythm_class", "trainable", "untrainable_reason",
]


def build_teaching_tasks(*, input_dir: Path, output_dir: Path) -> dict[str, Any]:
    occurrences = _read_csv(input_dir / "timetable_occurrences.csv")
    courses = {_course_key(row): row for row in _read_csv(input_dir / "courses.csv")}
    student_counts = _student_counts(_read_csv(input_dir / "class_groups.csv"))

    sessions = _merge_into_sessions(occurrences)
    tasks, task_of_session = _group_into_tasks(sessions, _index_courses(courses), student_counts)

    for session in sessions:
        session["task_id"] = task_of_session[session["session_id"]]

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "teaching_sessions.csv", sessions, SESSION_FIELDS)
    _write_csv(output_dir / "teaching_tasks.csv", tasks, TASK_FIELDS)

    report = _build_report(
        input_dir=input_dir,
        output_dir=output_dir,
        occurrence_count=len(occurrences),
        sessions=sessions,
        tasks=tasks,
    )
    (output_dir / "teaching_tasks_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report


def _merge_into_sessions(occurrences: list[dict[str, str]]) -> list[dict[str, Any]]:
    """同学期 + 同课程 + 同教室 + 同周同星期同节次 = 一次物理授课。"""
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in occurrences:
        key = (
            _value(row, "source_semester"),
            _value(row, "course_code"),
            _value(row, "classroom_name"),
            _value(row, "week_index"),
            _value(row, "day_of_week"),
            _value(row, "period_index"),
        )
        bucket = grouped.setdefault(key, {
            "key": key,
            "course_name": _value(row, "course_name"),
            "consecutive_slots": _int(row.get("consecutive_slots")),
            "classes": set(),
            "teachers": set(),
            "teacher_spellings": set(),
        })
        bucket["classes"].add(_value(row, "class_name"))
        raw_teachers = _value(row, "teacher_name")
        bucket["teacher_spellings"].add(raw_teachers)
        for name in raw_teachers.split(","):
            if name.strip():
                bucket["teachers"].add(name.strip())

    sessions: list[dict[str, Any]] = []
    for index, bucket in enumerate(grouped.values(), start=1):
        semester, course_code, room, week, day, period = bucket["key"]
        classes = sorted(bucket["classes"])
        teachers = sorted(bucket["teachers"])
        sessions.append({
            "session_id": f"S{index:07d}",
            "source_semester": semester,
            "course_code": course_code,
            "course_name": bucket["course_name"],
            "classroom_name": room,
            "week_index": week,
            "day_of_week": day,
            "period_index": period,
            "consecutive_slots": bucket["consecutive_slots"],
            "class_count": len(classes),
            "class_names": ",".join(classes),
            "teacher_count": len(teachers),
            "teacher_names": ",".join(teachers),
            # 同一节课在不同班的课表里写了不同教师名，合并后留痕供人工核对。
            "teacher_name_conflict": "true" if len(bucket["teacher_spellings"]) > 1 else "false",
            "task_id": "",
        })
    return sessions


def _group_into_tasks(
    sessions: list[dict[str, Any]],
    courses: dict[tuple[str, str], dict[str, str]],
    student_counts: dict[tuple[str, str], int],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """键含班级集合：同一课程代码下的多个平行班是互不相干的教学任务。"""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        key = (
            session["source_semester"],
            session["course_code"],
            session["class_names"],
        )
        grouped[key].append(session)

    tasks: list[dict[str, Any]] = []
    task_of_session: dict[str, str] = {}
    for index, (key, items) in enumerate(sorted(grouped.items()), start=1):
        semester, course_code, class_names = key
        task_id = f"T{index:06d}"
        classes = class_names.split(",") if class_names else []
        teachers = sorted({name for item in items for name in item["teacher_names"].split(",") if name})
        rooms = sorted({item["classroom_name"] for item in items})
        week_sessions = Counter(item["week_index"] for item in items)
        course = courses.get((semester, course_code), {})

        verdict = judge_scope(
            course_type=_value(course, "course_type"),
            course_name=_value(course, "course_name"),
            week_sessions=week_sessions,
            teachers=teachers,
        )

        known = [student_counts.get((semester, name)) for name in classes]
        complete = all(value is not None for value in known)

        for item in items:
            task_of_session[item["session_id"]] = task_id

        tasks.append({
            "task_id": task_id,
            "source_semester": semester,
            "course_code": course_code,
            "course_name": items[0]["course_name"],
            "course_type": _value(course, "course_type"),
            "required_room_type": _value(course, "required_room_type"),
            "class_count": len(classes),
            "class_names": class_names,
            "is_joint_class": "true" if len(classes) > 1 else "false",
            "student_count_total": sum(value for value in known if value is not None),
            "student_count_complete": "true" if complete else "false",
            "teacher_count": verdict["teacher_count"],
            "primary_teacher": verdict["primary_teacher"],
            "assistant_teachers": verdict["assistant_teachers"],
            "session_count": len(items),
            "total_periods": sum(_int(item["consecutive_slots"]) for item in items),
            "active_week_count": verdict["active_week_count"],
            "peak_sessions_per_week": verdict["peak_sessions_per_week"],
            "room_count": len(rooms),
            "rooms": ",".join(rooms),
            "rhythm_class": verdict["rhythm_class"],
            "trainable": verdict["trainable"],
            "untrainable_reason": verdict["untrainable_reason"],
        })
    return tasks, task_of_session


def _index_courses(
    courses: dict[tuple[str, str, str], dict[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    """课程元信息是按班级文件存的；同学期同代码的任何一份都可用，取先到的一份。"""
    index: dict[tuple[str, str], dict[str, str]] = {}
    for (semester, _schedule, code), row in courses.items():
        index.setdefault((semester, code), row)
    return index


def _student_counts(rows: list[dict[str, str]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        raw = _value(row, "student_count")
        if raw.isdigit():
            counts[(_value(row, "source_semester"), _value(row, "class_name"))] = int(raw)
    return counts


def _build_report(
    *,
    input_dir: Path,
    output_dir: Path,
    occurrence_count: int,
    sessions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    trainable = [task for task in tasks if task["trainable"] == "true"]
    joint = [task for task in tasks if task["is_joint_class"] == "true"]
    per_semester: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tasks": 0, "trainable": 0, "joint": 0, "sessions": 0}
    )
    for task in tasks:
        bucket = per_semester[task["source_semester"]]
        bucket["tasks"] += 1
        bucket["sessions"] += task["session_count"]
        if task["trainable"] == "true":
            bucket["trainable"] += 1
        if task["is_joint_class"] == "true":
            bucket["joint"] += 1

    return {
        "version": "teaching-tasks-v1",
        "status": "ok",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "collapse": {
            "occurrence_rows": occurrence_count,
            "teaching_sessions": len(sessions),
            "duplicate_rows_removed": occurrence_count - len(sessions),
            "teaching_tasks": len(tasks),
        },
        "joint_class": {
            "joint_tasks": len(joint),
            "joint_task_ratio": round(len(joint) / len(tasks), 4) if tasks else 0.0,
            "class_count_distribution": dict(sorted(Counter(task["class_count"] for task in tasks).items())),
            "joint_sessions": sum(1 for item in sessions if item["class_count"] > 1),
        },
        "data_quality": {
            "teacher_name_conflict_sessions": sum(
                1 for item in sessions if item["teacher_name_conflict"] == "true"
            ),
            "tasks_missing_student_count": sum(
                1 for task in tasks if task["student_count_complete"] == "false"
            ),
            "tasks_using_multiple_rooms": sum(1 for task in tasks if task["room_count"] > 1),
        },
        "trainable": {
            "tasks": len(trainable),
            "sessions": sum(task["session_count"] for task in trainable),
            "periods": sum(task["total_periods"] for task in trainable),
            "joint_tasks": sum(1 for task in trainable if task["is_joint_class"] == "true"),
        },
        "excluded_tasks_by_reason": dict(Counter(
            task["untrainable_reason"].split("（")[0]
            for task in tasks if task["trainable"] == "false"
        ).most_common()),
        "per_semester": {key: dict(value) for key, value in sorted(per_semester.items())},
        "outputs": {
            "sessions": str(output_dir / "teaching_sessions.csv"),
            "tasks": str(output_dir / "teaching_tasks.csv"),
        },
    }


def _course_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        _value(row, "source_semester"),
        _value(row, "source_schedule"),
        _value(row, "course_code"),
    )


def _value(row: dict[str, str], field: str) -> str:
    return str(row.get(field) or row.get("﻿" + field) or "").strip()


def _int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild real teaching tasks and detect joint classes.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    report = build_teaching_tasks(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
