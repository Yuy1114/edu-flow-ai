"""开题承诺指标实测：100 门课程 / 50 间教室规模下的排课计算时间。

算例来自真实语料，构造是确定性的（固定学期 + 固定排序 + 固定规则），换台机器跑出来的
算例完全一样，只有耗时不同：

- 教学任务：`backend/data/parsed/history_training_dataset_v2/_tasks/teaching_tasks.csv`
  （5 个学期重建出的 8,833 个真实教学任务）里任务数最多的那个学期，取**开课面最广的 N 门课程**
  （按教学任务数降序，即同一门课有几个班在开）。
- 教室：`backend/data/parsed/history_training_dataset/_combined/classrooms.csv`
  （369 间真实教室）里按所选课程的**课时**需求比例抽教室，每种房型至少 1 间。
- pattern：每个任务只给总课时，节奏交给引擎自己的课时规则表
  （`pattern_builder._build_pattern` → `pattern_source="hours_rule"`），与生产路径一致。

为什么要跑两套资源供给：50 间教室的自动域容量（18 周 × 5 天 × 8 节 = 720 节/间 = 36,000 节）
对 100 门课的真实负载来说往往只有需求的一部分，这时"排不上"是资源不足的必然结果，而不是
算法的覆盖率问题。所以：
  - `promise`：**开题口径**，教室数就是 --rooms（默认 50）。
  - `resource_supply`：同样的课程，把教室补到"课时需求 / 0.7 余量"所需的间数，用于隔离原因。
两套都报耗时与排课质量，避免把资源约束说成算法能力。

计时边界（重要）：本脚本只测**引擎纯计算**——从 pattern 到动态周模板产出，单进程、不含
数据库与作业调度。完整作业链路（Java → ml-api → Python 子进程 → 落库）是另一个指标，
必须分开报，不要混成一个数。

用法：
    python scripts/bench_scale_promise.py --courses 100 --rooms 50 --repeat 5
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "python"))

from scheduler.pattern_builder import _build_pattern  # noqa: E402
from scheduler.export_template_cover_db_draft import export_db_draft  # noqa: E402
from scheduler.phase_scheduler import build_phase_cover  # noqa: E402
from scheduler.validate_db_draft_export import validate_export  # noqa: E402

DEFAULT_TASKS_CSV = REPO_ROOT / "backend" / "data" / "parsed" / "history_training_dataset_v2" / "_tasks" / "teaching_tasks.csv"
DEFAULT_CLASSROOMS_CSV = REPO_ROOT / "backend" / "data" / "parsed" / "history_training_dataset" / "_combined" / "classrooms.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "backend" / "data" / "analysis" / "promise_scale"

SEMESTER_WEEKS = 18
AUTOMATIC_PERIODS_PER_DAY = 8   # 自动域 1-8；晚间与周末是人工保留域
AUTOMATIC_WEEKDAYS = 5
ROOM_CAPACITY_PER_ROOM = SEMESTER_WEEKS * AUTOMATIC_WEEKDAYS * AUTOMATIC_PERIODS_PER_DAY
# 留的余量：教室不可能占满，占满就是压力场景而不是典型规模。
UTILIZATION_CEILING = 0.7


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.DictReader(handle)]


def _as_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _hours_by_room_type(rows: list[dict[str, str]]) -> Counter:
    hours: Counter = Counter()
    for row in rows:
        room_type = str(row.get("required_room_type") or "").strip()
        if room_type:
            hours[room_type] += _as_int(row.get("total_periods"))
    return hours


def _hardware() -> dict[str, Any]:
    def sysctl(key: str) -> str:
        try:
            return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:  # pragma: no cover - 只在拿不到硬件信息时走到
            return ""

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": sysctl("machdep.cpu.brand_string") or platform.processor(),
        "cpu_cores": sysctl("hw.ncpu"),
        "memory_bytes": _as_int(sysctl("hw.memsize")),
        "python": sys.version.split()[0],
    }


def _semester_rows(tasks: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    """任务数最多的那个学期（固定学期，保证算例可复现）。"""
    by_semester: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in tasks:
        by_semester[str(row.get("source_semester") or "").strip()].append(row)
    semester = max(sorted(by_semester), key=lambda name: (len(by_semester[name]), name))
    return semester, by_semester[semester]


def select_example_rows(rows: list[dict[str, str]], *, course_count: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """开课面最广的 course_count 门课程的全部教学任务（按任务数降序，固定可复现）。"""
    rows_by_course: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_course[str(row.get("course_name") or "").strip()].append(row)
    ranked = sorted(rows_by_course.items(), key=lambda item: (-len(item[1]), item[0]))
    chosen = ranked[:course_count]
    selected = [row for _, course_rows in chosen for row in course_rows]
    detail = {
        "courses_in_semester": len(rows_by_course),
        "selected_course_count": len(chosen),
        "task_count": len(selected),
        "task_count_top_course": len(chosen[0][1]) if chosen else 0,
        "ranking_rule": "按教学任务数降序（并列按课程名）",
    }
    return selected, detail


def build_patterns(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """每个真实教学任务过一遍引擎的课时规则表，得到 pattern（字段名与生产路径一致）。"""
    patterns = []
    for row in rows:
        names = [str(row.get("primary_teacher") or "").strip()]
        names += [name.strip() for name in str(row.get("assistant_teachers") or "").split(",") if name.strip()]
        # 语料里的教师身份只有姓名（见 implementation/13 的遗留口径），这里把它们当教师 key 用：
        # 引擎对 key 是不透明的，教师占用冲突照样按 key 判定。
        # 每周次数/持续周数交给课时规则表（pattern_source=hours_rule）：语料的
        # peak_sessions_per_week 是"某一周最多几次"，乘整学期周数会把课时严重超排。
        sample = {
            "course_name": row.get("course_name"),
            "course_code": row.get("course_code"),
            "course_type": row.get("course_type"),
            "required_room_type": row.get("required_room_type"),
            "teacher_name": names[0],
            "teacher_ids": [name for name in names if name],
            "student_count": _as_int(row.get("student_count_total")),
            "class_names": row.get("class_names") or row.get("class_name"),
            "class_name": row.get("class_name") or row.get("class_names"),
            "teaching_task_id": row.get("task_id"),
            "total_hours": _as_int(row.get("total_periods")),
            "allowed_weeks": list(range(1, SEMESTER_WEEKS + 1)),
        }
        pattern = _build_pattern(str(row.get("task_id") or ""), [sample])
        # uid 与 source_key 必须一致：引擎 `_load_patterns` 会用 source_key 覆盖 uid，
        # 两边不一致的话审计按 uid 找片段会全部落空（课时守恒会算成"全都没排"）。
        pattern["uid"] = pattern["source_key"] = f"bench-{row.get('task_id')}"
        patterns.append(pattern)
    return patterns


def room_mix_for(hours: Counter, *, room_count: int) -> dict[str, int]:
    """按课时需求比例把 room_count 间教室分给各房型，每种至少 1 间。"""
    total = sum(hours.values())
    if not total:
        raise SystemExit("所选任务没有任何可用的房型需求")
    order = sorted(hours, key=lambda name: (-hours[name], name))
    mix = {room_type: max(1, round(room_count * hours[room_type] / total)) for room_type in order}
    while sum(mix.values()) > room_count:  # 四舍五入会超出，从份额最小的减起
        for room_type in reversed(order):
            if sum(mix.values()) <= room_count:
                break
            if mix[room_type] > 1:
                mix[room_type] -= 1
    while sum(mix.values()) < room_count:
        mix[order[0]] += 1
    return mix


def required_room_mix(hours: Counter) -> dict[str, int]:
    """让课时需求落到教室容量的 70% 所需的房型配比（用于隔离"是资源还是算法"）。"""
    return {room_type: max(1, math.ceil(hours[room_type] / (ROOM_CAPACITY_PER_ROOM * UTILIZATION_CEILING)))
            for room_type in sorted(hours, key=lambda name: (-hours[name], name))}


def pick_rooms(room_rows: list[dict[str, str]], room_mix: dict[str, int]) -> list[dict[str, Any]]:
    """从真实教室池里按房型名额取教室（按名称排序，结果可复现）。"""
    pool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in room_rows:
        room_type = str(row.get("classroom_type") or "").strip()
        name = str(row.get("classroom_name") or "").strip()
        if room_type and name:
            pool[room_type].append({
                "name": name,
                "classroom_type": room_type,
                "capacity": _as_int(row.get("capacity")),
                "status": str(row.get("status") or "ACTIVE").strip(),
            })
    for rooms in pool.values():
        rooms.sort(key=lambda room: room["name"])

    picked: list[dict[str, Any]] = []
    for room_type, count in sorted(room_mix.items(), key=lambda item: (-item[1], item[0])):
        available = pool.get(room_type) or []
        if len(available) < count:
            raise SystemExit(f"真实教室里 {room_type} 只有 {len(available)} 间，凑不出 {count} 间")
        picked.extend(available[:count])
    return picked


def capacity_infeasible_uuids(patterns: list[dict[str, Any]], rooms: list[dict[str, Any]]) -> set[str]:
    """语料缺口导致的"必然排不上"：学生数超过所有教室的容量。

    教室容量在这份语料里是回填值（120，非真实座位数），所以学生数 >120 的任务谁也装不下——
    这是数据缺口，不该记到算法覆盖率上。真实座位数补齐后这些任务要重测。
    """
    max_capacity = max((int(room.get("capacity") or 0) for room in rooms), default=0)
    return {
        str(pattern["uid"]) for pattern in patterns
        if max_capacity and int(pattern.get("student_count") or 0) > max_capacity
    }


def cover_metrics(report: dict[str, Any], *, capacity_infeasible: set[str]) -> dict[str, Any]:
    conflicts = (report.get("conflicts") or {}).get("semester_dynamic") or {}
    initial = int(report.get("initial_task_count") or 0)
    completed = int(report.get("completed_task_count") or 0)
    feasible = max(0, initial - len(capacity_infeasible))
    required = report.get("required_total_hours")
    scheduled = report.get("scheduled_total_hours")
    return {
        "initial_task_count": initial,
        "completed_task_count": completed,
        "remaining_task_count": report.get("remaining_task_count"),
        "capacity_infeasible_task_count": len(capacity_infeasible),
        "feasible_task_count": feasible,
        "completion_rate": round(completed / initial, 4) if initial else None,
        "completion_rate_of_feasible": round(completed / feasible, 4) if feasible else None,
        "hour_completion_rate": round(scheduled / required, 4) if required else None,
        "template_count": report.get("template_count"),
        "fragment_count": report.get("fragment_count"),
        "output_fragment_count": report.get("output_fragment_count"),
        "teacher_conflicts": conflicts.get("teacher"),
        "class_conflicts": conflicts.get("class"),
        "room_conflicts": conflicts.get("room"),
        "required_total_hours": required,
        "scheduled_total_hours": scheduled,
        "hour_delta_total": report.get("hour_delta_total"),
        "conservation_mismatch": report.get("conservation_mismatch"),
        "hour_over_task_count": report.get("hour_over_task_count"),
        "hour_under_task_count": report.get("hour_under_task_count"),
        "capacity_mismatch_count": report.get("capacity_mismatch_count"),
        "validation_issue_count": report.get("validation_issue_count"),
        "unresolved_reason_counts": report.get("unresolved_reason_counts"),
        "placement_repairs": report.get("placement_repairs"),
        "packing_failures": report.get("packing_failures"),
    }


def _seconds_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [run["seconds"] for run in runs]
    return {
        "min": min(durations),
        "median": round(statistics.median(durations), 3),
        "max": max(durations),
        "mean": round(statistics.fmean(durations), 3),
        "stdev": round(statistics.stdev(durations), 3) if len(durations) > 1 else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure scheduling time on the 100-course / 50-room example.")
    parser.add_argument("--tasks-csv", default=str(DEFAULT_TASKS_CSV))
    parser.add_argument("--classrooms-csv", default=str(DEFAULT_CLASSROOMS_CSV))
    parser.add_argument("--courses", type=int, default=100)
    parser.add_argument("--rooms", type=int, default=50)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--chain", action="store_true",
                        help="额外量一遍草案导出与校验的耗时（不含 MySQL 落库）")
    parser.add_argument("--chain-allocation-task-id", type=int, default=1)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    semester, semester_rows = _semester_rows(_read_csv(Path(args.tasks_csv)))
    example_rows, selection = select_example_rows(semester_rows, course_count=args.courses)
    patterns = build_patterns(example_rows)
    hours = _hours_by_room_type(example_rows)
    classroom_rows = _read_csv(Path(args.classrooms_csv))

    patterns_path = out_dir / "task_patterns.jsonl"
    patterns_path.write_text(
        "".join(json.dumps(pattern, ensure_ascii=False) + "\n" for pattern in patterns), encoding="utf-8",
    )

    teachers = {name for pattern in patterns for name in (pattern.get("teacher_ids") or [])}
    classes = {name for pattern in patterns for name in str(pattern.get("class_names") or "").split(",") if name.strip()}
    example = {
        "semester": semester,
        "course_count": len({pattern.get("course_name") for pattern in patterns}),
        "task_count": len(patterns),
        "teacher_count": len(teachers),
        "class_count": len(classes),
        "total_hours": sum(int(pattern.get("total_hours") or 0) for pattern in patterns),
        "weekly_sessions": sum(int(pattern.get("weekly_slot_count") or 0) * int(pattern.get("duration_weeks") or 0)
                               for pattern in patterns),
        "duration_weeks": dict(Counter(int(pattern.get("duration_weeks") or 0) for pattern in patterns)),
        "consecutive_slots": dict(Counter(int(pattern.get("consecutive_slots") or 0) for pattern in patterns)),
        "pattern_source": dict(Counter(str(pattern.get("pattern_source") or "") for pattern in patterns)),
        "hours_by_room_type": dict(hours),
        "selection": selection,
        "constraints": {
            "time_axis": "每天 11 节（上午 1-4、下午 5-8、晚上 9-11），语义周 18 周",
            "allowed_weekdays": "工作日 1-5 为自动域，周末人工保留",
            "phase_weeks": "8 + 10",
            "rooms": "按课时需求比例抽真实教室；容量取语料回填值（120，非真实座位数）",
            "utilization_ceiling": UTILIZATION_CEILING,
        },
        "hardware": _hardware(),
    }

    configurations: dict[str, dict[str, Any]] = {}
    for name, room_mix in (
        ("promise", room_mix_for(hours, room_count=args.rooms)),
        ("resource_supply", required_room_mix(hours)),
    ):
        rooms = pick_rooms(classroom_rows, room_mix)
        rooms_path = out_dir / f"rooms_{name}.json"
        rooms_path.write_text(json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8")
        capacity_infeasible = capacity_infeasible_uuids(patterns, rooms)
        load = {room_type: hours[room_type] / (count * ROOM_CAPACITY_PER_ROOM)
                for room_type, count in room_mix.items()}

        runs: list[dict[str, Any]] = []
        for index in range(args.repeat):
            started = time.perf_counter()
            report = build_phase_cover(
                patterns_path=patterns_path,
                rooms_path=rooms_path,
                use_model=False,
                output_path=out_dir / f"phase_cover_{name}_run{index + 1}.json",
                report_path=out_dir / f"cover_report_{name}_run{index + 1}.json",
                unresolved_path=out_dir / f"unresolved_{name}_run{index + 1}.json",
            )
            runs.append({"run": index + 1, "seconds": round(time.perf_counter() - started, 3),
                         **cover_metrics(report, capacity_infeasible=capacity_infeasible)})

        configurations[name] = {
            "rooms_by_type": room_mix,
            "room_count": len(rooms),
            "load_of_automatic_domain": {room_type: round(value, 4) for room_type, value in load.items()},
            "capacity_infeasible_task_count": len(capacity_infeasible),
            "seconds": _seconds_summary(runs),
            "runs": runs,
            "quality_identical_across_runs": len({
                json.dumps({k: v for k, v in run.items() if k not in {"run", "seconds"}}, sort_keys=True, default=str)
                for run in runs
            }) == 1,
            "rooms_path": str(rooms_path),
        }

    summary = {
        "example": example,
        "configurations": configurations,
        "timing_boundary": "engine-only: patterns -> dynamic week templates, single process, no database",
    }
    (out_dir / "scale_example.json").write_text(
        json.dumps({"example": example, "configurations": {k: {kk: vv for kk, vv in v.items() if kk != "runs"}
                                                          for k, v in configurations.items()}},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if args.chain:
        # 链路的后半段（草案导出 + 校验）单独计时：夹在"引擎纯计算"和"整条子进程链路"之间，
        # 分开报才看得出时间花在哪一段。
        started = time.perf_counter()
        export_report = export_db_draft(
            cover_path=out_dir / "phase_cover_promise_run1.json",
            output_dir=out_dir / "chain_draft",
            allocation_task_id=args.chain_allocation_task_id,
            generation_run_id="bench-chain",
            rooms_path=out_dir / "rooms_promise.json",
        )
        export_seconds = time.perf_counter() - started
        started = time.perf_counter()
        validation = validate_export(input_dir=out_dir / "chain_draft",
                                     report_path=out_dir / "chain_draft" / "validation_report.json")
        validate_seconds = time.perf_counter() - started
        summary["chain"] = {
            "export_seconds": round(export_seconds, 3),
            "validate_seconds": round(validate_seconds, 3),
            "validation_issue_count": len(validation.get("issues") or []),
            "issue_counts": validation.get("issue_counts"),
            "export_counts": export_report.get("counts"),
            "note": ("不含 MySQL 落库：落库要先把教学任务/教师/班级/教室种进库，1,031 个任务的算例"
                     "没有现成入库路径；落库段与整条作业链路的实测见 implementation/16"),
        }
    (out_dir / "bench_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "example": {k: v for k, v in example.items() if k != "hardware"},
        "configurations": {
            name: {
                "rooms_by_type": cfg["rooms_by_type"],
                "load_of_automatic_domain": cfg["load_of_automatic_domain"],
                "seconds": cfg["seconds"],
                "quality_identical_across_runs": cfg["quality_identical_across_runs"],
                "metrics": {k: v for k, v in cfg["runs"][-1].items() if k not in {"run", "seconds"}},
            }
            for name, cfg in configurations.items()
        },
        "out_dir": str(out_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
