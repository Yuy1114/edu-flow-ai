"""标注历史课表数据集的可训练范围。

第二阶段的排序器只学习**常规课堂排课行为**：普通理论课，加上有规律周节奏的
上机/实验课。历史课表里还混着另外几类记录，它们都是真实的、也都不该进训练集：

- **集中实践**：课程设计、综合训练一类，把周一到周五整周占满，持续两三周。
  学进去，模型会以为"把一门课铺满一整周"是正常落位。
- **团队授课**：`teacher_name` 是三人以上的逗号列表。教师偏好（避开早课、
  偏好紧凑、日课时上限）对一个九人组合没有意义。
- **不支持的课程类型**：体育课在球场、虚拟课在虚拟教室，都不占常规教室。

判别集中实践靠的是**峰值 × 持续周数**这一对量：常规课峰值 1-4 次/周、持续
10 周以上；集中实践峰值 8-20 次/周、持续 2 周左右。单看任何一个都会误伤——
一门每周两次的实验课，一次连上 4 节，用"占用节次数"去量会被错当成集中实践。

本模块**只标记不丢弃**，与 `docs/implementation/12` 的导入口径一致：每条
occurrence 都保留，附上 `trainable` 与 `untrainable_reason`，训练时按标记筛。
把"高频"和"块状"分成两档，是因为前者（6-7 次/周）里既有正常的密集课也有
实践课，需要人工确认；后者（>=8 次/周）几乎全是课程设计。
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset" / "_combined"
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset" / "_scope"

# 本阶段引擎支持的课程类型：普通教室的理论课，机房的上机/实验课。
SUPPORTED_COURSE_TYPES = ("理论课", "上机课")

# 课名里出现这些词，就是集中实践，不看节奏也排除。名称判定和节奏判定互为补充：
# 有的课程设计只占两周但每周排满，有的挂着普通课名却整周块状占用。
PRACTICE_NAME_MARKERS = (
    "课程设计", "综合训练", "实训", "实习", "设计周", "写生", "采风", "认识实习",
)

# 峰值次/周的分档。常规课 1-5，密集课 6-7 需人工确认，>=8 基本是整周块状占用。
REGULAR_PEAK_MAX = 5
INTENSIVE_PEAK_MAX = 7

# 一次授课最多两位教师（主讲 + 助教）才保留教师身份；三人以上是团队授课。
MAX_TEACHERS_FOR_PROFILE = 2

TASK_FIELDS = [
    "source_semester", "source_schedule", "course_code", "course_name",
    "class_name", "course_type", "required_room_type",
    "session_count", "active_week_count", "peak_sessions_per_week",
    "rhythm_class", "teacher_count", "primary_teacher", "assistant_teachers",
    "trainable", "untrainable_reason",
]

OCCURRENCE_EXTRA_FIELDS = [
    "rhythm_class", "peak_sessions_per_week", "teacher_count",
    "primary_teacher", "assistant_teachers", "trainable", "untrainable_reason",
]


def label_training_scope(*, input_dir: Path, output_dir: Path) -> dict[str, Any]:
    courses = {_course_key(row): row for row in _read_csv(input_dir / "courses.csv")}
    occurrences = _read_csv(input_dir / "timetable_occurrences.csv")

    by_task: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in occurrences:
        by_task[_course_key(row)].append(row)

    task_rows: list[dict[str, Any]] = []
    verdict_by_task: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, rows in by_task.items():
        verdict = _judge_task(courses.get(key, {}), rows)
        verdict_by_task[key] = verdict
        task_rows.append({
            "source_semester": key[0],
            "source_schedule": key[1],
            "course_code": key[2],
            "course_name": _value(courses.get(key, {}), "course_name"),
            "class_name": _value(rows[0], "class_name"),
            "course_type": _value(courses.get(key, {}), "course_type"),
            "required_room_type": _value(courses.get(key, {}), "required_room_type"),
            **verdict,
        })

    labelled: list[dict[str, Any]] = []
    for row in occurrences:
        verdict = verdict_by_task[_course_key(row)]
        merged = dict(row)
        merged.pop("﻿source_semester", None)
        merged["source_semester"] = _value(row, "source_semester")
        merged.update({field: verdict[field] for field in OCCURRENCE_EXTRA_FIELDS})
        labelled.append(merged)

    output_dir.mkdir(parents=True, exist_ok=True)
    occurrence_fields = [
        field for field in labelled[0] if field not in OCCURRENCE_EXTRA_FIELDS
    ] + OCCURRENCE_EXTRA_FIELDS if labelled else []
    _write_csv(output_dir / "training_scope_tasks.csv", task_rows, TASK_FIELDS)
    _write_csv(output_dir / "timetable_occurrences_labeled.csv", labelled, occurrence_fields)

    report = _build_report(
        input_dir=input_dir,
        output_dir=output_dir,
        task_rows=task_rows,
        occurrences=labelled,
    )
    (output_dir / "training_scope_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report


def _judge_task(course: dict[str, str], rows: list[dict[str, str]]) -> dict[str, Any]:
    return judge_scope(
        course_type=_value(course, "course_type"),
        course_name=_value(course, "course_name"),
        week_sessions=Counter(_value(row, "week_index") for row in rows),
        teachers=_teachers_of(rows),
    )


def judge_scope(
    *,
    course_type: str,
    course_name: str,
    week_sessions: Counter[str],
    teachers: list[str],
) -> dict[str, Any]:
    """判定一个教学任务是否属于本阶段的可训练范围。

    `week_sessions` 是 {周次: 该周授课次数}。用"次数"而不是"占用节次数"是刻意的：
    实验课一次连上 4 节，按节次量会把每周两次的实验课误判成集中实践。
    """
    weeks = week_sessions
    peak = max(weeks.values()) if weeks else 0

    if peak <= REGULAR_PEAK_MAX:
        rhythm = "regular"
    elif peak <= INTENSIVE_PEAK_MAX:
        rhythm = "intensive"
    else:
        rhythm = "block"

    reason = ""
    if course_type not in SUPPORTED_COURSE_TYPES:
        reason = f"课程类型 {course_type or '未知'} 不在本阶段支持范围"
    elif any(marker in course_name for marker in PRACTICE_NAME_MARKERS):
        reason = "集中实践类课程"
    elif rhythm == "block":
        reason = f"整周块状占用（峰值 {peak} 次/周）"
    elif rhythm == "intensive":
        reason = f"高频节奏待人工确认（峰值 {peak} 次/周）"
    elif len(teachers) > MAX_TEACHERS_FOR_PROFILE:
        reason = f"团队授课（{len(teachers)} 位教师），教师偏好无法归属"

    return {
        "session_count": sum(weeks.values()),
        "active_week_count": len(weeks),
        "peak_sessions_per_week": peak,
        "rhythm_class": rhythm,
        "teacher_count": len(teachers),
        # 主讲取列表首位，与课程说明区 师[...] 的书写顺序一致。
        "primary_teacher": teachers[0] if teachers else "",
        "assistant_teachers": ",".join(teachers[1:]),
        "trainable": "false" if reason else "true",
        "untrainable_reason": reason,
    }


def _teachers_of(rows: list[dict[str, str]]) -> list[str]:
    for row in rows:
        raw = _value(row, "teacher_name")
        names = [name.strip() for name in raw.split(",") if name.strip()]
        if names:
            return names
    return []


def _build_report(
    *,
    input_dir: Path,
    output_dir: Path,
    task_rows: list[dict[str, Any]],
    occurrences: list[dict[str, Any]],
) -> dict[str, Any]:
    trainable_tasks = [row for row in task_rows if row["trainable"] == "true"]
    trainable_occurrences = [row for row in occurrences if row["trainable"] == "true"]
    reasons = Counter(
        row["untrainable_reason"].split("（")[0]
        for row in task_rows if row["trainable"] == "false"
    )
    reason_occurrences: Counter[str] = Counter()
    for row in occurrences:
        if row["trainable"] == "false":
            reason_occurrences[row["untrainable_reason"].split("（")[0]] += 1

    per_semester: dict[str, dict[str, int]] = defaultdict(lambda: {"occurrences": 0, "trainable": 0, "evening": 0})
    for row in trainable_occurrences:
        bucket = per_semester[_value(row, "source_semester")]
        bucket["trainable"] += 1
        if _int(row.get("period_index")) >= 9:
            bucket["evening"] += 1
    for row in occurrences:
        per_semester[_value(row, "source_semester")]["occurrences"] += 1

    return {
        "version": "training-scope-v1",
        "status": "ok",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "scope": {
            "supported_course_types": list(SUPPORTED_COURSE_TYPES),
            "regular_peak_max": REGULAR_PEAK_MAX,
            "intensive_peak_max": INTENSIVE_PEAK_MAX,
            "max_teachers_for_profile": MAX_TEACHERS_FOR_PROFILE,
        },
        "task_counts": {
            "total": len(task_rows),
            "trainable": len(trainable_tasks),
        },
        "occurrence_counts": {
            "total": len(occurrences),
            "trainable": len(trainable_occurrences),
            "trainable_evening": sum(
                1 for row in trainable_occurrences if _int(row.get("period_index")) >= 9
            ),
        },
        "excluded_tasks_by_reason": dict(reasons.most_common()),
        "excluded_occurrences_by_reason": dict(reason_occurrences.most_common()),
        "rhythm_class_counts": dict(Counter(row["rhythm_class"] for row in task_rows)),
        "course_type_counts": dict(Counter(row["course_type"] for row in trainable_tasks)),
        "per_semester": {key: dict(value) for key, value in sorted(per_semester.items())},
        "outputs": {
            "tasks": str(output_dir / "training_scope_tasks.csv"),
            "occurrences": str(output_dir / "timetable_occurrences_labeled.csv"),
        },
    }


def _course_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        _value(row, "source_semester"),
        _value(row, "source_schedule"),
        _value(row, "course_code"),
    )


def _value(row: dict[str, str], field: str) -> str:
    # 组合数据集的 CSV 带 BOM，首列键名会多一个 ﻿。
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
    parser = argparse.ArgumentParser(description="Label the trainable scope of the history timetable dataset.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    report = label_training_scope(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
