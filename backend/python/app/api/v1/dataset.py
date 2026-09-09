"""历史课表训练语料的质检接口。

管理端的「数据质检台」读这里。语料是 `ingest` 三步处理的产物——解析、范围标注、
教学任务还原——以 CSV 落在磁盘上，不进 MySQL：它是训练语料，不参与任何排课决策，
第二阶段的训练管道也是直读文件。

接口只做聚合，不做清洗。把 25 万行 session 压成一份约 1.7MB 的载荷：字符串走
下标表，周次压成位掩码，(任务, 星期, 节次, 教室) 相同的落位合并成一条。前端拿到
后自己展开成热力图和课表网格。

聚合结果按文件 mtime 缓存在进程内。指纹取的是**结果内容**而不是文件时间戳，
这样两次清洗只要产出相同就是同一个指纹，快照表里才能真正比较。
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter()

BACKEND_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATASET_DIR = BACKEND_ROOT / "data" / "parsed" / "history_training_dataset_v2"

_CACHE: dict[str, Any] = {"key": None, "payload": None}


def _dataset_root() -> Path:
    return Path(os.environ.get("EDU_FLOW_DATASET_DIR", str(DEFAULT_DATASET_DIR)))


def _required_files(root: Path) -> dict[str, Path]:
    return {
        "tasks": root / "_tasks" / "teaching_tasks.csv",
        "sessions": root / "_tasks" / "teaching_sessions.csv",
        "task_report": root / "_tasks" / "teaching_tasks_report.json",
        "build_report": root / "history_training_dataset_report.json",
    }


@router.get("/dataset/board")
def dataset_board() -> dict[str, Any]:
    """质检看板的完整载荷。数据集缺失时返回 missing，而不是抛错。"""
    root = _dataset_root()
    files = _required_files(root)
    absent = [name for name, path in files.items() if not path.exists()]
    if absent:
        return {
            "status": "missing",
            "dataset_dir": str(root),
            "missing": absent,
            "message": "未找到清洗产物。请确认 EDU_FLOW_DATASET_DIR 指向 history_training_dataset_v2，"
                       "并且该目录已挂载进容器。",
        }
    key = "|".join(f"{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in files.values())
    if _CACHE["key"] != key:
        _CACHE["payload"] = _build_payload(files)
        _CACHE["key"] = key
    return _CACHE["payload"]


@router.get("/dataset/summary")
def dataset_summary() -> dict[str, Any]:
    """只要统计口径，不含逐条落位。Java 用它写快照表。"""
    board = dataset_board()
    if board.get("status") != "ok":
        return board
    return {
        "status": "ok",
        "dataset_dir": board["dataset_dir"],
        "fingerprint": board["fingerprint"],
        "meta": board["meta"],
    }


def _build_payload(files: dict[str, Path]) -> dict[str, Any]:
    tasks_raw = _read_csv(files["tasks"])
    sessions_raw = _read_csv(files["sessions"])
    task_report = json.loads(files["task_report"].read_text(encoding="utf-8"))
    build_report = json.loads(files["build_report"].read_text(encoding="utf-8"))

    semesters = _Table()
    rooms = _Table()
    courses = _Table()
    classes = _Table()
    teachers = _Table()
    reasons = _Table()

    task_rows: list[list[Any]] = []
    task_pos: dict[str, int] = {}
    for row in tasks_raw:
        task_pos[row["task_id"]] = len(task_rows)
        task_rows.append([
            semesters.idx(_v(row, "source_semester")),
            courses.idx(row["course_name"]),
            row["course_code"],
            [classes.idx(name) for name in row["class_names"].split(",") if name],
            [teachers.idx(name) for name in
             ([row["primary_teacher"]] if row["primary_teacher"] else [])
             + [name for name in row["assistant_teachers"].split(",") if name]],
            _int(row["student_count_total"]),
            1 if row["student_count_complete"] == "true" else 0,
            1 if row["trainable"] == "true" else 0,
            reasons.idx(row["untrainable_reason"]),
            row["rhythm_class"],
            1 if row["is_joint_class"] == "true" else 0,
            _int(row["session_count"]),
            _int(row["total_periods"]),
            _int(row["peak_sessions_per_week"]),
            _int(row["active_week_count"]),
            row["course_type"],
        ])

    # 同一 (任务, 星期, 节次, 教室, 跨度) 的多个周次压成一个位掩码。
    folded: dict[tuple[int, int, int, int, int], int] = {}
    for row in sessions_raw:
        week = _int(row["week_index"])
        if not 1 <= week <= 24:
            continue
        key = (
            task_pos[row["task_id"]],
            _int(row["day_of_week"]),
            _int(row["period_index"]),
            rooms.idx(row["classroom_name"]),
            _int(row["consecutive_slots"]) or 1,
        )
        folded[key] = folded.get(key, 0) | (1 << (week - 1))
    placements = [[a, b, c, d, e, mask] for (a, b, c, d, e), mask in folded.items()]

    meta = {
        "semesters": semesters.values,
        "source_files": build_report.get("file_count", 0),
        "occurrence_rows": task_report["collapse"]["occurrence_rows"],
        "sessions": task_report["collapse"]["teaching_sessions"],
        "tasks": task_report["collapse"]["teaching_tasks"],
        "duplicates_removed": task_report["collapse"]["duplicate_rows_removed"],
        "joint_ratio": task_report["joint_class"]["joint_task_ratio"],
        "class_dist": task_report["joint_class"]["class_count_distribution"],
        "excluded": task_report["excluded_tasks_by_reason"],
        "trainable": task_report["trainable"],
        "quality": task_report["data_quality"],
        "per_semester": task_report["per_semester"],
        "evening_sessions": sum(
            1 for row in sessions_raw if _int(row["period_index"]) >= 9
        ),
    }
    return {
        "status": "ok",
        "dataset_dir": str(files["tasks"].parent.parent),
        "fingerprint": _fingerprint(meta),
        "meta": meta,
        "rooms": rooms.values,
        "courses": courses.values,
        "classes": classes.values,
        "teachers": teachers.values,
        "reasons": reasons.values,
        "tasks": task_rows,
        "placements": placements,
    }


def _fingerprint(meta: dict[str, Any]) -> str:
    """按结果内容取指纹：两次清洗产出相同即同一指纹，与文件时间无关。"""
    material = json.dumps({
        key: meta[key] for key in
        ("occurrence_rows", "sessions", "tasks", "duplicates_removed",
         "excluded", "trainable", "quality", "per_semester")
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class _Table:
    """字符串下标表：载荷里重复出现的班级、教师、教室名只存一次。"""

    def __init__(self) -> None:
        self.values: list[str] = []
        self._index: dict[str, int] = {}

    def idx(self, value: str) -> int:
        if value not in self._index:
            self._index[value] = len(self.values)
            self.values.append(value)
        return self._index[value]


def _v(row: dict[str, str], field: str) -> str:
    return str(row.get(field) or row.get("﻿" + field) or "").strip()


def _int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
