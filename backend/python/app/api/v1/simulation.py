"""Database-free synthetic scheduler endpoints for the simulation dashboard."""
from __future__ import annotations

import json
import hashlib
import os
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import gettempdir
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from scheduler.generate_synthetic_data import GeneratorConfig, generate, resource_capacity_preflight
from scheduler.run_synthetic_pipeline import run

router = APIRouter()
SIMULATION_SCHEMA_VERSION = "v3-capacity-preflight-formal-mix"

FAILURE_GUIDANCE = {
    "classroom_capacity_unavailable": {
        "category": "room_capacity",
        "message": "指定类型的教室都小于任务人数。",
        "suggestions": ["增加大容量同类型教室", "拆分教学任务或取消不合理合班", "降低该场景的班级规模"],
    },
    "required_room_type_unavailable": {
        "category": "room_type",
        "message": "资源池中不存在课程要求的教室类型。",
        "suggestions": ["补充对应类型教室", "检查任务的 required_room_type"],
    },
    "automatic_search_exhausted": {
        "category": "manual_review",
        "message": "自动启发式搜索未找到合法位置；这不等于已证明无解。",
        "suggestions": ["使用晚上 9-10 或其他保留时段人工调课", "扩大自动搜索或进行局部重排", "检查教师、班级和教室的共同空档"],
    },
    "allowed_weeks_insufficient": {
        "category": "week_domain",
        "message": "允许周次不足以覆盖课程要求的教学周数。",
        "suggestions": ["检查 allowed_weeks", "缩短或拆分教学周期", "由教务指定例外周次"],
    },
    "fixed_or_candidate_classroom_unavailable": {
        "category": "room_binding",
        "message": "固定教室或候选教室集合中没有可用资源。",
        "suggestions": ["检查固定教室状态", "扩大候选教室集合", "由教务解除不必要的教室绑定"],
    },
    "not_placed": {
        "category": "unknown",
        "message": "任务未能进入模板，当前原因信息不足。",
        "suggestions": ["检查 unresolved 样本和排课日志"],
    },
}


class SimulationRequest(BaseModel):
    seed: int = 20260816
    courses: int = Field(default=1964, ge=24, le=3000)
    teachers: int = Field(default=541, ge=8, le=800)
    class_groups: int = Field(default=362, ge=6, le=500)
    classrooms: int = Field(default=320, ge=4, le=400)
    profile: Literal["balanced", "formal-mix", "lab-heavy", "constrained"] = "balanced"
    simulation_id: str | None = Field(default=None, pattern=r"^sim-[0-9a-f]{16}$")


class SimulationTimetableRequest(BaseModel):
    simulation_id: str = Field(pattern=r"^sim-[0-9a-f]{16}$")
    template_id: str | None = None
    teacher: str | None = None
    class_name: str | None = None
    classroom: str | None = None
    course: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


def _run(request: SimulationRequest) -> dict:
    simulation_id, root, generated = _ensure_dataset(request)
    result = run(config=_generator_config(request), output_dir=root, source_dir=root / "source")
    dataset = _dataset_preview(root / "source", generated, simulation_id=simulation_id)
    cover = json.loads((root / "phase_cover.json").read_text(encoding="utf-8"))
    report = json.loads((root / "phase_cover_report.json").read_text(encoding="utf-8"))
    unresolved_path = root / "unresolved.jsonl"
    unresolved = [json.loads(line) for line in unresolved_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    traces = _task_traces(root, cover, unresolved)
    return {
        "simulation_id": simulation_id,
        "dataset": dataset,
        "summary": result,
        "engine": {
            "teaching_task_count": report["raw_task_count"],
            "placement_task_count": report["merged_task_count"],
            "compatibility_merge_count": report["merged_section_count"],
            "template_count": report.get("template_count", 0),
            "unresolved_reason_counts": report["unresolved_reason_counts"],
        },
        "unresolved_preview": unresolved[:20],
        "failure_analysis": _failure_analysis(unresolved),
        "template_grids": _template_grids(cover),
        "timetable_views": _timetable_views(cover),
        "task_traces": traces[:50],
        "artifact_files": sorted(path.name for path in root.iterdir() if path.is_file()),
    }


def _preview(request: SimulationRequest) -> dict:
    simulation_id, root, generated = _ensure_dataset(request)
    return _dataset_preview(root / "source", generated, simulation_id=simulation_id)


def _simulation_root() -> Path:
    return Path(os.environ.get("EDU_FLOW_SIMULATION_DIR", Path(gettempdir()) / "edu-flow-ai-simulations"))


def _query_timetable(request: SimulationTimetableRequest) -> dict:
    cover_path = _simulation_root() / request.simulation_id / "phase_cover.json"
    if not cover_path.exists():
        raise HTTPException(status_code=404, detail="simulation result not found; run the simulation first")

    cover = json.loads(cover_path.read_text(encoding="utf-8"))
    entries = _timetable_entries(cover)
    options = {
        "templates": sorted({entry["template_id"] for entry in entries}),
        "teachers": sorted({entry["teacher"] for entry in entries if entry["teacher"]}),
        "classes": sorted({name for entry in entries for name in entry["classes"] if name}),
        "classrooms": sorted({entry["classroom"] for entry in entries if entry["classroom"]}),
        "courses": sorted({entry["course"] for entry in entries if entry["course"]}),
    }
    course_query = (request.course or "").strip().casefold()
    filtered = [
        entry for entry in entries
        if (not request.template_id or entry["template_id"] == request.template_id)
        and (not request.teacher or entry["teacher"] == request.teacher)
        and (not request.class_name or request.class_name in entry["classes"])
        and (not request.classroom or entry["classroom"] == request.classroom)
        and (not course_query or course_query in entry["course"].casefold() or course_query in entry["course_code"].casefold())
    ]
    total = len(filtered)
    start = (request.page - 1) * request.page_size
    page_entries = filtered[start:start + request.page_size]
    return {
        "simulation_id": request.simulation_id,
        "filters": options,
        "query": request.model_dump(exclude={"simulation_id", "page", "page_size"}),
        "summary": {
            "fragments": total,
            "teachers": len({entry["teacher"] for entry in filtered}),
            "classes": len({name for entry in filtered for name in entry["classes"]}),
            "classrooms": len({entry["classroom"] for entry in filtered}),
            "courses": len({entry["course_code"] for entry in filtered}),
            "occupied_segments": sum(entry["consecutive_slots"] for entry in filtered),
            "semester_occupied_segments": sum(
                entry["consecutive_slots"] * len(entry["week_numbers"])
                for entry in filtered
            ),
        },
        "total": total,
        "page": request.page,
        "page_size": request.page_size,
        "page_count": max(1, (total + request.page_size - 1) // request.page_size),
        "entries": page_entries,
    }


def _timetable_entries(cover: dict) -> list[dict]:
    entries = []
    for template in cover.get("templates", []):
        template_id = str(template.get("template_id") or "")
        week_numbers = [int(value) for value in template.get("week_numbers") or []]
        for fragment in template.get("fragments", []):
            classes = _class_names(fragment)
            start_period = int(fragment.get("period_index") or 0)
            consecutive_slots = int(fragment.get("consecutive_slots") or 1)
            entries.append({
                "fragment_id": str(fragment.get("fragment_id") or ""),
                "source_key": str(fragment.get("source_key") or ""),
                "template_id": template_id,
                "week_numbers": week_numbers,
                "week_label": _week_label(week_numbers),
                "course": str(fragment.get("course_name") or ""),
                "course_code": str(fragment.get("course_code") or ""),
                "teacher": str(fragment.get("teacher_name") or ""),
                "classes": classes,
                "classroom": str(fragment.get("classroom_name") or ""),
                "room_type": str(fragment.get("required_room_type") or ""),
                "day": int(fragment.get("day_of_week") or 0),
                "start_period": start_period,
                "end_period": start_period + consecutive_slots - 1,
                "consecutive_slots": consecutive_slots,
                "duration_weeks": int(fragment.get("duration_weeks") or 0),
                "covered_hours": int(fragment.get("covered_hours") or 0),
                "student_count": int(fragment.get("student_count") or 0),
            })
    return sorted(entries, key=lambda entry: (
        min(entry["week_numbers"], default=0), entry["template_id"], entry["day"],
        entry["start_period"], entry["teacher"], entry["course"], entry["classroom"]
    ))


def _class_names(row: dict) -> list[str]:
    raw = row.get("class_names") or row.get("class_name") or []
    if isinstance(raw, (list, tuple)):
        values = [str(value).strip() for value in raw]
    else:
        text = str(raw).replace("，", ",").replace("、", ",").replace(";", ",").replace("|", ",")
        values = [value.strip() for value in text.split(",")]
    return list(dict.fromkeys(value for value in values if value))


def _week_label(week_numbers: list[int] | tuple[int, ...]) -> str:
    weeks = sorted({int(value) for value in week_numbers})
    if not weeks:
        return "未指定周次"
    ranges: list[str] = []
    start = previous = weeks[0]
    for week in weeks[1:]:
        if week == previous + 1:
            previous = week
            continue
        ranges.append(str(start) if start == previous else f"{start}–{previous}")
        start = previous = week
    ranges.append(str(start) if start == previous else f"{start}–{previous}")
    return f"第{'、'.join(ranges)}周"


def _simulation_id(request: SimulationRequest) -> str:
    payload = {
        "schema_version": SIMULATION_SCHEMA_VERSION,
        **request.model_dump(exclude={"simulation_id"}),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"sim-{digest[:16]}"


def _ensure_dataset(request: SimulationRequest) -> tuple[str, Path, dict]:
    expected_id = _simulation_id(request)
    if request.simulation_id and request.simulation_id != expected_id:
        raise HTTPException(status_code=409, detail="simulation_id does not match the supplied simulation configuration")
    root = _simulation_root() / expected_id
    source_dir = root / "source"
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.exists():
        generated = generate(config=_generator_config(request), output_dir=source_dir)
    else:
        generated = json.loads(manifest_path.read_text(encoding="utf-8"))
        if generated.get("generator") != "v3-capacity-preflight-formal-mix":
            generated = generate(config=_generator_config(request), output_dir=source_dir)
    return expected_id, root, generated


def _generator_config(request: SimulationRequest) -> GeneratorConfig:
    return GeneratorConfig(
        seed=request.seed,
        courses=request.courses,
        teachers=request.teachers,
        class_groups=request.class_groups,
        classrooms=request.classrooms,
        profile=request.profile,
    )


def _dataset_preview(source_dir: Path, generated: dict, *, simulation_id: str) -> dict:
    task_path = source_dir / "teaching_tasks.jsonl"
    room_path = source_dir / "classrooms.json"
    tasks = [json.loads(line) for line in task_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rooms = json.loads(room_path.read_text(encoding="utf-8"))
    capacity_preflight = resource_capacity_preflight(tasks, rooms)

    room_capacity_by_type: dict[str, int] = defaultdict(int)
    for room in rooms:
        room_type = str(room.get("classroom_type") or "")
        room_capacity_by_type[room_type] = max(room_capacity_by_type[room_type], int(room.get("capacity") or 0))
    capacity_issues = [
        task for task in tasks
        if int(task.get("student_count") or 0) > room_capacity_by_type[str(task.get("required_room_type") or "")]
    ]

    weekly_slots = sum(
        int(task.get("sessions_per_week") or 0) * (4 if task.get("course_type") == "上机课" else 2)
        for task in tasks
    )
    lab_weekly_slots = sum(
        int(task.get("sessions_per_week") or 0) * 4
        for task in tasks if task.get("course_type") == "上机课"
    )
    lab_rooms = sum(1 for room in rooms if room.get("classroom_type") == "机房")
    standard_rooms = len(rooms) - lab_rooms
    large_rooms = sum(1 for room in rooms if room.get("classroom_type") == "普通教室" and int(room.get("capacity") or 0) >= 120)
    room_week_capacity = len(rooms) * 5 * 8
    lab_week_capacity = lab_rooms * 5 * 8
    multi_class_tasks = sum(len(_class_names(task)) > 1 for task in tasks)
    class_associations = sum(len(_class_names(task)) for task in tasks)
    active_class_groups = {
        str(class_group_id)
        for task in tasks
        for class_group_id in task.get("class_group_ids") or []
    }
    task_type_counts = {
        course_type: sum(1 for task in tasks if task.get("course_type") == course_type)
        for course_type in ("理论课", "上机课")
    }
    warning = None
    if not capacity_preflight["feasible"]:
        warning = "资源分层必要容量预检未通过；本场景必然需要人工复核或增加对应容量层级的教室。"
    elif lab_week_capacity and lab_weekly_slots > lab_week_capacity * 0.82:
        warning = "机房周容量接近上限，适合验证专用资源压力。"
    elif room_week_capacity and weekly_slots > room_week_capacity * 0.78:
        warning = "整体教室周容量偏紧，适合验证资源竞争和无解分支。"

    return {
        "simulation_id": simulation_id,
        "schema_version": SIMULATION_SCHEMA_VERSION,
        "config": generated["config"],
        "input_hash": hashlib.sha256(task_path.read_bytes() + b"\0" + room_path.read_bytes()).hexdigest(),
        "counts": {
            "teaching_tasks": len(tasks),
            "multi_class_tasks": multi_class_tasks,
            "single_class_tasks": len(tasks) - multi_class_tasks,
            "class_associations": class_associations,
            "teachers": generated["counts"]["teachers"],
            "class_groups": generated["counts"]["class_groups"],
            "active_class_groups": len(active_class_groups),
            "classrooms": len(rooms),
            "theory_tasks": task_type_counts["理论课"],
            "lab_tasks": task_type_counts["上机课"],
            "standard_rooms": standard_rooms,
            "large_rooms": large_rooms,
            "lab_rooms": lab_rooms,
            "weekly_slots": weekly_slots,
            "room_week_capacity": room_week_capacity,
            "lab_weekly_slots": lab_weekly_slots,
            "lab_week_capacity": lab_week_capacity,
            "capacity_issues": len(capacity_issues),
            "room_seats": sum(int(room.get("capacity") or 0) for room in rooms),
            "average_students": round(sum(int(task.get("student_count") or 0) for task in tasks) / max(1, len(tasks))),
            "max_task_students": max((int(task.get("student_count") or 0) for task in tasks), default=0),
            "assistant_teacher_tasks": sum(bool(task.get("assistant_teacher_id")) for task in tasks),
            "teacher_unavailable_tasks": sum(bool(task.get("teacher_unavailable_slots")) for task in tasks),
            "allowed_weeks_tasks": sum(bool(task.get("allowed_weeks")) for task in tasks),
            "fixed_classroom_tasks": sum(bool(task.get("fixed_classroom_name")) for task in tasks),
            "candidate_classroom_tasks": sum(bool(task.get("candidate_classroom_names")) for task in tasks),
        },
        "warning": warning,
        "resource_capacity_preflight": capacity_preflight,
        "tasks_preview": [_task_preview(task) for task in tasks[:20]],
        "capacity_issues_preview": [_capacity_issue_preview(task, room_capacity_by_type) for task in capacity_issues[:20]],
        "rooms": [
            {"name": room.get("name"), "type": room.get("classroom_type"), "capacity": int(room.get("capacity") or 0)}
            for room in rooms
        ],
    }


def _task_traces(root: Path, cover: dict, unresolved: list[dict]) -> list[dict]:
    patterns = {
        row["source_key"]: row
        for row in _read_jsonl(root / "task_patterns.jsonl")
    }
    fragments_by_source: dict[str, list[dict]] = defaultdict(list)
    for template in cover.get("templates", []):
        template_weeks = [int(value) for value in template.get("week_numbers") or []]
        for fragment in template.get("fragments", []):
            fragment_trace = {
                "fragment_id": fragment.get("fragment_id"),
                "template_id": template.get("template_id"),
                "week_numbers": template_weeks,
                "week_label": _week_label(template_weeks),
                "day": fragment.get("day_of_week"),
                "period": fragment.get("period_index"),
                "room": fragment.get("classroom_name"),
                "duration_weeks": fragment.get("duration_weeks"),
                "covered_hours": fragment.get("covered_hours"),
            }
            for source_key in fragment.get("merged_source_keys") or [fragment.get("source_key")]:
                fragments_by_source[str(source_key)].append(fragment_trace)
    unresolved_by_uid = {str(row.get("uid")): row for row in unresolved}
    traces = []
    for source_key, pattern in patterns.items():
        fragments = fragments_by_source.get(source_key, [])
        failure = unresolved_by_uid.get(source_key)
        if not fragments and failure is None:
            failure = {"uid": source_key, "reason": "not_placed"}
        traces.append({
            "source_key": source_key,
            "course": pattern.get("course_name"),
            "teacher": pattern.get("teacher_name"),
            "classes": _class_names(pattern),
            "pattern": {
                "source": pattern.get("pattern_source"),
                "sessions_per_week": pattern.get("sessions_per_week"),
                "duration_weeks": pattern.get("duration_weeks"),
                "consecutive_slots": pattern.get("consecutive_slots"),
                "total_hours": pattern.get("total_hours"),
                "room_type": pattern.get("required_room_type"),
            },
            "status": "unresolved" if failure else "scheduled",
            "templates": sorted({fragment["template_id"] for fragment in fragments}),
            "fragments": fragments,
            "failure": failure,
        })
    return sorted(traces, key=lambda trace: (trace["status"] != "unresolved", trace["source_key"]))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _task_preview(task: dict) -> dict:
    class_names = _class_names(task)
    return {
        "id": task.get("source_key"),
        "course": task.get("course_name"),
        "type": task.get("course_type"),
        "teacher": task.get("teacher_name"),
        "class_names": class_names,
        "class_group_ids": [str(value) for value in task.get("class_group_ids") or []],
        "class_count": len(class_names),
        "room_type": task.get("required_room_type"),
        "hours": int(task.get("total_hours") or 0),
        "weeks": int(task.get("duration_weeks") or 0),
        "sessions": int(task.get("sessions_per_week") or 0),
        "students": int(task.get("student_count") or 0),
    }


def _capacity_issue_preview(task: dict, room_capacity_by_type: dict[str, int]) -> dict:
    room_type = str(task.get("required_room_type") or "")
    return {
        **_task_preview(task),
        "students": int(task.get("student_count") or 0),
        "available_capacity": room_capacity_by_type[room_type],
    }


def _template_grids(cover: dict) -> list[dict]:
    grids: list[dict] = []
    for template in cover.get("templates", []):
        cells: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for fragment in template.get("fragments", []):
            for segment in fragment.get("segments", []):
                cells[(segment["day_of_week"], segment["period_index"])].append({
                    "course_name": fragment.get("course_name"),
                    "class_names": fragment.get("class_names"),
                    "classroom_name": fragment.get("classroom_name"),
                    "student_count": fragment.get("student_count", 0),
                })
        grids.append({
            "template_id": template.get("template_id"),
            "week_numbers": [int(value) for value in template.get("week_numbers") or []],
            "week_label": _week_label(template.get("week_numbers") or []),
            "cells": [
                {"day": day, "period": period, "count": len(cells[(day, period)]), "items": cells[(day, period)][:3]}
                for day in range(1, 6) for period in range(1, 12)
            ],
        })
    return grids


def _failure_analysis(unresolved: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in unresolved:
        grouped[str(row.get("reason") or "not_placed")].append(row)
    result = []
    for reason, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        guidance = FAILURE_GUIDANCE.get(reason, FAILURE_GUIDANCE["not_placed"])
        result.append({
            "reason": reason,
            "count": len(rows),
            **guidance,
            "examples": [
                {
                    "uid": row.get("uid"),
                    "course": row.get("course"),
                    "teacher": row.get("teacher"),
                    "classes": row.get("classes") or [],
                    "student_count": row.get("student_count"),
                }
                for row in rows[:3]
            ],
        })
    return result


def _timetable_views(cover: dict) -> list[dict]:
    fragments = [
        (template.get("template_id"), fragment)
        for template in cover.get("templates", [])
        for fragment in template.get("fragments", [])
    ]
    teacher_counts = Counter(str(fragment.get("teacher_name") or "") for _, fragment in fragments)
    class_counts: Counter = Counter()
    for _, fragment in fragments:
        class_counts.update(_class_names(fragment))
    entities = [
        *(('teacher', name, count) for name, count in teacher_counts.most_common(5) if name),
        *(('class', name, count) for name, count in class_counts.most_common(5) if name),
    ]
    views = []
    for kind, name, count in entities:
        filtered_templates = []
        for template in cover.get("templates", []):
            selected = []
            for fragment in template.get("fragments", []):
                matches = (
                    fragment.get("teacher_name") == name if kind == "teacher"
                    else name in _class_names(fragment)
                )
                if matches:
                    selected.append(fragment)
            filtered_templates.append({**template, "fragments": selected})
        views.append({
            "id": f"{kind}:{name}",
            "kind": kind,
            "name": name,
            "fragment_count": count,
            "template_grids": _template_grids({"templates": filtered_templates}),
        })
    return views


@router.post("/simulation/run")
def run_simulation(request: SimulationRequest) -> dict:
    return _run(request)


@router.post("/simulation/preview")
def preview_simulation(request: SimulationRequest) -> dict:
    return _preview(request)


@router.post("/simulation/timetable")
def query_timetable(request: SimulationTimetableRequest) -> dict:
    return _query_timetable(request)


@router.post("/simulation/boundary")
def scan_boundary(request: SimulationRequest) -> dict:
    scales = (1.0, 0.75, 0.5, 0.25)
    rows = []
    for scale in scales:
        classrooms = max(4, round(request.classrooms * scale))
        output = _run(request.model_copy(update={"classrooms": classrooms}))
        schedule = output["summary"]["schedule"]
        rows.append({
            "classrooms": classrooms,
            "status": output["summary"]["status"],
            "completed": schedule["completed"],
            "remaining": schedule["remaining"],
            "needs_manual_review": output["summary"]["needs_manual_review"],
            "reasons": schedule["unresolved_reason_counts"],
        })
    return {"baseline_classrooms": request.classrooms, "rows": rows}
