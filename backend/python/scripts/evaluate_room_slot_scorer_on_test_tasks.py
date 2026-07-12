"""Run the trained room+slot scorer on parsed test teaching tasks.

This is closer to the real usage contract than the labeled validation dataset:
    teaching task -> Top-K candidate room+slot recommendations

The report includes raw top-1 conflict rates and a simple greedy pass that uses
Top-K recommendations to choose one non-conflicting resource point per task.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from build_room_slot_training_dataset import (
    _base_task_features,
    _candidate_rooms,
    _global_slots,
    _read_csv,
    _sample_row,
)
from train_room_slot_scorer import CATEGORICAL_FEATURES, FEATURES, MODEL_FILENAME

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_DIR = REPO_ROOT / "backend" / "data" / "parsed" / "test_schedule_dataset" / "_combined"
DEFAULT_MODEL_DIR = REPO_ROOT / "backend" / "models" / "v3.5" / "room_slot_scorer"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "parsed" / "room_slot_test_recommendations"
TOP_KS = [1, 5, 10, 20]
RECOMMENDATION_FIELDS = [
    "source_semester",
    "source_schedule",
    "course_id",
    "course_code",
    "course_name",
    "teacher_name",
    "class_name",
    "class_names",
    "total_hours",
    "segment_count",
    "rank",
    "score",
    "candidate_room",
    "candidate_room_type",
    "candidate_capacity",
    "candidate_day_of_week",
    "candidate_period_index",
    "candidate_slot_key",
    "room_type_match",
]


def evaluate_room_slot_scorer_on_test_tasks(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    model_dir: Path = DEFAULT_MODEL_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    top_k: int = 20,
    limit_tasks: int | None = None,
) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")

    catboost = _load_catboost()
    model_path = model_dir / MODEL_FILENAME
    if not model_path.exists():
        raise SystemExit(f"model not found: {model_path}")
    model = catboost.CatBoostClassifier()
    model.load_model(str(model_path))

    tables = _load_tables(input_dir)
    tasks = [task for task in tables["tasks"] if _clean(task.get("schedulable")).lower() == "true"]
    if limit_tasks is not None:
        tasks = tasks[:limit_tasks]
    if not tasks:
        raise SystemExit("no schedulable teaching tasks found")

    candidate_rooms = _candidate_rooms(tables["classroom_by_name"])
    candidate_slots = _global_slots(tables["occurrences"])
    if not candidate_rooms:
        raise SystemExit("no candidate classrooms found")
    if not candidate_slots:
        raise SystemExit("no candidate slots found")

    top_k = max(1, top_k)
    recommendation_rows: list[dict[str, Any]] = []
    recommendations_by_task: list[dict[str, Any]] = []
    task_count = len(tasks)
    print(
        f"推荐测试: {task_count} 个教学任务, {len(candidate_rooms)} 个教室, {len(candidate_slots)} 个slot",
        flush=True,
    )

    for index, task in enumerate(tasks, start=1):
        if index == 1 or index % 100 == 0 or index == task_count:
            print(f"  [{index}/{task_count}] {_clean(task.get('course_name'))}", flush=True)
        task_recommendations = _recommend_for_task(
            model=model,
            task=task,
            tables=tables,
            candidate_rooms=candidate_rooms,
            candidate_slots=candidate_slots,
            top_k=top_k,
        )
        recommendations_by_task.append({
            "task": task,
            "recommendations": task_recommendations,
        })
        recommendation_rows.extend(task_recommendations)

    output_dir.mkdir(parents=True, exist_ok=True)
    recommendations_path = output_dir / "topk_recommendations.csv"
    report_path = output_dir / "evaluation_report.json"
    _write_csv(recommendations_path, recommendation_rows, RECOMMENDATION_FIELDS)

    top1_assignments = [_assignment(item["task"], item["recommendations"][0]) for item in recommendations_by_task]
    greedy_metrics = {
        f"top{top_k_value}": _greedy_assign(recommendations_by_task, top_k=top_k_value)
        for top_k_value in TOP_KS
        if top_k_value <= top_k
    }
    report = {
        "status": "ok",
        "version": "room-slot-test-recommendation-v1",
        "input_dir": str(input_dir),
        "model_path": str(model_path),
        "output_dir": str(output_dir),
        "top_k": top_k,
        "limit_tasks": limit_tasks,
        "source_counts": {
            "teaching_tasks": len(tables["tasks"]),
            "schedulable_tasks": len(tasks),
            "classrooms": len(candidate_rooms),
            "candidate_slots": len(candidate_slots),
            "candidate_room_slots_per_task": len(candidate_rooms) * len(candidate_slots),
        },
        "recommendation_rows": len(recommendation_rows),
        "raw_top1_conflicts": _conflict_metrics(top1_assignments),
        "greedy_topk_assignment": greedy_metrics,
        "outputs": {
            "recommendations": str(recommendations_path),
            "report": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _load_tables(input_dir: Path) -> dict[str, Any]:
    tasks = _read_csv(input_dir / "teaching_tasks.csv")
    occurrences = _read_csv(input_dir / "timetable_occurrences.csv")
    courses = _read_csv(input_dir / "courses.csv")
    classrooms = _read_csv(input_dir / "classrooms.csv")
    class_groups = _read_csv(input_dir / "class_groups.csv")
    return {
        "tasks": tasks,
        "occurrences": occurrences,
        "courses": courses,
        "classrooms": classrooms,
        "class_groups": class_groups,
        "course_by_key": {
            (_clean(row.get("source_schedule")), _clean(row.get("course_id"))): row
            for row in courses
        },
        "class_group_by_key": {
            (_clean(row.get("source_schedule")), _clean(row.get("class_name"))): row
            for row in class_groups
        },
        "classroom_by_name": {
            _clean(row.get("classroom_name")): row
            for row in classrooms
            if _clean(row.get("classroom_name"))
        },
    }


def _recommend_for_task(
    *,
    model: Any,
    task: dict[str, str],
    tables: dict[str, Any],
    candidate_rooms: list[str],
    candidate_slots: list[tuple[int, int]],
    top_k: int,
) -> list[dict[str, Any]]:
    course = tables["course_by_key"].get((_clean(task.get("source_schedule")), _clean(task.get("course_id"))), {})
    class_group = tables["class_group_by_key"].get((_clean(task.get("source_schedule")), _clean(task.get("class_name"))), {})
    base = _base_task_features(task, course, class_group, split="test")
    candidates = [
        _sample_row(
            base=base,
            classroom=tables["classroom_by_name"].get(room, {}),
            room=room,
            day=day,
            period=period,
            label=0,
        )
        for room in candidate_rooms
        for day, period in candidate_slots
    ]
    frame = pd.DataFrame(candidates)
    _coerce_features(frame)
    pool = _load_catboost().Pool(frame[FEATURES], cat_features=CATEGORICAL_FEATURES)
    scores = model.predict_proba(pool)[:, 1]
    frame["_score"] = scores
    ranked = frame.sort_values("_score", ascending=False).head(top_k).reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    for rank, row in enumerate(ranked.to_dict("records"), start=1):
        rows.append({
            "source_semester": row.get("source_semester", ""),
            "source_schedule": row.get("source_schedule", ""),
            "course_id": row.get("course_id", ""),
            "course_code": row.get("course_code", ""),
            "course_name": row.get("course_name", ""),
            "teacher_name": row.get("teacher_name", ""),
            "class_name": row.get("class_name", ""),
            "class_names": row.get("class_names", ""),
            "total_hours": row.get("total_hours", 0),
            "segment_count": row.get("segment_count", 0),
            "rank": rank,
            "score": round(float(row.get("_score", 0.0)), 10),
            "candidate_room": row.get("candidate_room", ""),
            "candidate_room_type": row.get("candidate_room_type", ""),
            "candidate_capacity": row.get("candidate_capacity", 0),
            "candidate_day_of_week": row.get("candidate_day_of_week", 0),
            "candidate_period_index": row.get("candidate_period_index", 0),
            "candidate_slot_key": row.get("candidate_slot_key", ""),
            "room_type_match": row.get("room_type_match", ""),
        })
    return rows


def _coerce_features(frame: pd.DataFrame) -> None:
    for column in FEATURES:
        if column not in frame:
            frame[column] = ""
    for column in CATEGORICAL_FEATURES:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    numeric_features = [column for column in FEATURES if column not in CATEGORICAL_FEATURES]
    for column in numeric_features:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _assignment(task: dict[str, str], recommendation: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_schedule": _clean(task.get("source_schedule")),
        "course_id": _clean(task.get("course_id")),
        "course_name": _clean(task.get("course_name")),
        "teacher_names": _split_names(task.get("teacher_name")),
        "class_names": _split_names(task.get("class_names")) or [_clean(task.get("class_name"))],
        "room": _clean(recommendation.get("candidate_room")),
        "day": _safe_int(recommendation.get("candidate_day_of_week")),
        "period": _safe_int(recommendation.get("candidate_period_index")),
        "score": float(recommendation.get("score") or 0.0),
    }


def _greedy_assign(recommendations_by_task: list[dict[str, Any]], *, top_k: int) -> dict[str, Any]:
    ordered = sorted(
        recommendations_by_task,
        key=lambda item: float(item["recommendations"][0].get("score") or 0.0),
        reverse=True,
    )
    used_rooms: set[tuple[str, int, int]] = set()
    used_teachers: set[tuple[str, int, int]] = set()
    used_classes: set[tuple[str, int, int]] = set()
    assignments: list[dict[str, Any]] = []
    unscheduled: list[dict[str, str]] = []

    for item in ordered:
        task = item["task"]
        chosen = None
        for recommendation in item["recommendations"][:top_k]:
            assignment = _assignment(task, recommendation)
            room_key = (assignment["room"], assignment["day"], assignment["period"])
            teacher_keys = {(name, assignment["day"], assignment["period"]) for name in assignment["teacher_names"] if name}
            class_keys = {(name, assignment["day"], assignment["period"]) for name in assignment["class_names"] if name}
            if room_key in used_rooms or teacher_keys & used_teachers or class_keys & used_classes:
                continue
            chosen = assignment
            used_rooms.add(room_key)
            used_teachers.update(teacher_keys)
            used_classes.update(class_keys)
            assignments.append(assignment)
            break
        if chosen is None:
            unscheduled.append({
                "source_schedule": _clean(task.get("source_schedule")),
                "course_id": _clean(task.get("course_id")),
                "course_name": _clean(task.get("course_name")),
            })

    conflicts = _conflict_metrics(assignments)
    total = len(recommendations_by_task)
    return {
        "task_count": total,
        "scheduled_count": len(assignments),
        "unscheduled_count": len(unscheduled),
        "unscheduled_rate": round(len(unscheduled) / total, 6) if total else 0.0,
        "conflicts_after_greedy": conflicts,
        "unscheduled_preview": unscheduled[:20],
    }


def _conflict_metrics(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_count": len(assignments),
        "resource_point": _group_conflicts(assignments, lambda row: [(row["room"], row["day"], row["period"])]),
        "teacher": _group_conflicts(
            assignments,
            lambda row: [(name, row["day"], row["period"]) for name in row["teacher_names"] if name],
        ),
        "class_group": _group_conflicts(
            assignments,
            lambda row: [(name, row["day"], row["period"]) for name in row["class_names"] if name],
        ),
    }


def _group_conflicts(assignments: list[dict[str, Any]], key_func: Any) -> dict[str, Any]:
    groups: dict[tuple[Any, ...], set[int]] = defaultdict(set)
    for index, assignment in enumerate(assignments):
        for key in key_func(assignment):
            if all(str(part) for part in key):
                groups[key].add(index)
    conflict_groups = {key: indexes for key, indexes in groups.items() if len(indexes) > 1}
    conflict_task_indexes = set().union(*conflict_groups.values()) if conflict_groups else set()
    return {
        "conflict_group_count": len(conflict_groups),
        "conflicting_task_count": len(conflict_task_indexes),
        "conflict_rate": round(len(conflict_task_indexes) / len(assignments), 6) if assignments else 0.0,
        "max_group_size": max((len(indexes) for indexes in conflict_groups.values()), default=0),
    }


def _load_catboost():
    try:
        import catboost
    except ModuleNotFoundError as exc:
        raise SystemExit("catboost is not installed. Run the backend Python dependency install first.") from exc
    return catboost


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _split_names(value: Any) -> list[str]:
    return [_clean(item) for item in re.split(r"[,，、/;；\s]+", str(value or "")) if _clean(item)]


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate room+slot scorer on parsed test teaching tasks.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--limit-tasks", type=int, default=None)
    args = parser.parse_args()
    report = evaluate_room_slot_scorer_on_test_tasks(
        input_dir=Path(args.input_dir),
        model_dir=Path(args.model_dir),
        output_dir=Path(args.output_dir),
        top_k=args.top_k,
        limit_tasks=args.limit_tasks,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
