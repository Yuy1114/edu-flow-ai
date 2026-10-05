"""冲突注入实验：把已知冲突逐类注进真实课表，验证审计全部检出、合法课表零误报。

开题承诺的"冲突检出率 100%"要区分两件事：
  1. 生成出的课表没有冲突（生成期硬约束）——`audit_placement_constraints` 在真实 cover 上全 0；
  2. 检测器能检出已知冲突——本模块把每一类硬约束分别注入一次，要求审计对应类别报警。
两者都通过才算"检出率 100%"，只报前者是把"没排错"当成"认得出错"。

注入是**最小改动**：每条注入只动一个片段的一个字段，尽量只触发目标类别；即使顺带触发了
其它类别，报告里也会如实列出（不能挑报）。
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping, Sequence

from scheduler.phase_scheduler import ALL_DAY_PERIODS, audit_placement_constraints, final_hour_audit

VIRTUAL_ROOM = "注入-虚拟教室"

# 审计的类别名 → 报告里用的字段
AUDIT_FIELDS = (
    "teacher", "class", "room",
    "room_type_mismatch", "capacity_mismatch", "time_axis_violation",
    "outside_automatic_domain",
)


class FragmentsSchedule:
    """给 `final_hour_audit` 用的最小 schedule 壳：它只读 `fragments`。"""

    def __init__(self, fragments: list[dict[str, Any]]) -> None:
        self.fragments = fragments
        self.name = "injected"
        self.week_numbers: list[int] = []


def fragments_from_cover(cover: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把 cover 文档里的片段摊成审计用的片段。

    周次用 `template_week_mask`（这份模板自己负责的周），**不是** `week_mask`：同一个逻辑
    片段会被放进多个模板（周次不连续时），用绝对周次会把同一格重复计数，制造出满屏假冲突。

    cover 片段只带一个 `teacher_name`（主讲），所以教师占用按主讲姓名判定；班级用
    `class_names`（合班按逗号分开）。这与生成侧 `_teacher_keys` 的口径不同（那边有教师 ID），
    是 cover 文档本身的字段限制，报告里明说。
    """
    fragments: list[dict[str, Any]] = []
    for template in cover.get("templates") or []:
        for doc in template.get("fragments") or []:
            weeks = doc.get("template_week_mask")
            if weeks is None:
                weeks = doc.get("week_mask") or []
            fragments.append({
                "uid": str(doc.get("source_key") or doc.get("fragment_id") or ""),
                "fragment_id": doc.get("fragment_id"),
                "room": str(doc.get("classroom_name") or ""),
                "day": int(doc.get("day_of_week") or 0),
                "start": int(doc.get("period_index") or 0),
                "consecutive": int(doc.get("consecutive_slots") or 0),
                "week_mask": [int(week) for week in weeks],
                "teacher_keys": [str(doc["teacher_name"])] if doc.get("teacher_name") else [],
                "class_keys": [name.strip() for name in str(doc.get("class_names") or "").split(",") if name.strip()],
                "required_room_type": doc.get("required_room_type"),
                "student_count": int(doc.get("student_count") or 0),
            })
    return fragments


def _clone(source: Mapping[str, Any], **overrides: Any) -> dict[str, Any]:
    fragment = copy.deepcopy(dict(source))
    fragment.update(overrides)
    return fragment


def _first_complete(fragments: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    complete = [f for f in fragments if f.get("teacher_keys") and f.get("class_keys") and f.get("room") and f.get("week_mask")]
    if not complete:
        raise ValueError("课表里没有同时带教师、班级、教室和周次的完整片段，注入实验无从下手")
    return complete[0]


def inject_teacher_occupancy(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """克隆一个片段，只保留教师 → 同一教师同一格两节课。"""
    source = _first_complete(fragments)
    fragments.append(_clone(source, uid=f"{source['uid']}#inject-teacher", class_keys=[], room=VIRTUAL_ROOM))
    return fragments


def inject_class_occupancy(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """克隆一个片段，只保留班级 → 同一班级同一格两节课。"""
    source = _first_complete(fragments)
    fragments.append(_clone(source, uid=f"{source['uid']}#inject-class", teacher_keys=[], room=VIRTUAL_ROOM))
    return fragments


def inject_room_occupancy(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """克隆一个片段，只保留教室 → 同一教室同一格被占两次。"""
    source = _first_complete(fragments)
    fragments.append(_clone(source, uid=f"{source['uid']}#inject-room", teacher_keys=[], class_keys=[]))
    return fragments


def inject_room_type_mismatch(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把片段的房型要求改成另一种 → 教室与房型不符（不动教室本身，避免顺带触发教室占用）。"""
    source = _first_complete(fragments)
    actual = str(rooms["room_type_by_name"].get(source["room"]) or "")
    other = next((name for name in rooms["all_types"] if name != actual), None)
    if other is None:
        raise ValueError("教室池里只有一种房型，注入不了房型不符")
    for fragment in fragments:
        if fragment is source:
            fragment["required_room_type"] = other
    return fragments


def inject_capacity_overflow(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把片段的班级人数改成超过该教室容量 → 容量不足。"""
    source = _first_complete(fragments)
    capacity = int(rooms["room_capacity_by_name"].get(source["room"]) or 0)
    if capacity <= 0:
        raise ValueError("拿不到该教室的容量，注入不了容量不足")
    for fragment in fragments:
        if fragment is source:
            fragment["student_count"] = capacity + 1
    return fragments


def inject_hour_shortage(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从某个片段的周次里去掉一周 → 课时少排。"""
    source = _first_complete(fragments)
    if len(source["week_mask"]) < 2:
        raise ValueError("该片段只有一周，去掉就没有周次了")
    for fragment in fragments:
        if fragment is source:
            fragment["week_mask"] = list(source["week_mask"])[:-1]
    return fragments


def inject_hour_excess(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给某个片段补一周（学期内没出现过的周）→ 课时超排。"""
    source = _first_complete(fragments)
    weeks = set(source["week_mask"])
    extra = next((week for week in range(1, (rooms["total_weeks"] or 18) + 1) if week not in weeks), None)
    if extra is None:
        raise ValueError("该片段已经占满学期周次，补不出超排")
    for fragment in fragments:
        if fragment is source:
            fragment["week_mask"] = sorted(weeks | {extra})
    return fragments


def inject_period_axis(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把一个片段推到时间轴末端之外（11 节之后）。"""
    source = _first_complete(fragments)
    for fragment in fragments:
        if fragment is source:
            fragment["start"] = max(ALL_DAY_PERIODS)
            fragment["consecutive"] = 2
    return fragments


def inject_weekday_axis(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把片段放到第 8 天（一周只有 7 天）。"""
    source = _first_complete(fragments)
    for fragment in fragments:
        if fragment is source:
            fragment["day"] = 8
    return fragments


def inject_week_axis(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把片段放到学期周次之外。"""
    source = _first_complete(fragments)
    total = int(rooms["total_weeks"] or 18)
    for fragment in fragments:
        if fragment is source:
            fragment["week_mask"] = [total + 1]
    return fragments


def inject_automatic_domain(fragments: list[dict[str, Any]], rooms: Mapping[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把片段排进晚间（自动域之外的人工保留域）→ 跨出自动域。"""
    source = _first_complete(fragments)
    evening = max(rooms["automatic_periods"]) + 1
    if evening not in ALL_DAY_PERIODS:
        raise ValueError("自动域已经到时间轴末端，注入不了跨域")
    for fragment in fragments:
        if fragment is source:
            fragment["start"] = evening
            fragment["consecutive"] = 1
    return fragments


INJECTIONS: tuple[tuple[str, str, Callable[..., list[dict[str, Any]]], dict[str, Any]], ...] = (
    ("teacher_occupancy", "同一教师同一格两节课", inject_teacher_occupancy, {"teacher": 1}),
    ("class_occupancy", "同一班级同一格两节课", inject_class_occupancy, {"class": 1}),
    ("room_occupancy", "同一教室同一格被占两次", inject_room_occupancy, {"room": 1}),
    ("room_type", "教室房型与要求不符", inject_room_type_mismatch, {"room_type_mismatch": 1}),
    ("capacity", "班级人数超过教室容量", inject_capacity_overflow, {"capacity_mismatch": 1}),
    ("hour_shortage", "课时少排", inject_hour_shortage, {"hour_mismatch": 1}),
    ("hour_excess", "课时超排", inject_hour_excess, {"hour_mismatch": 1}),
    ("period_axis", "节次越过时间轴末端", inject_period_axis, {"time_axis_violation": 1}),
    ("weekday_axis", "星期越界（第 8 天）", inject_weekday_axis, {"time_axis_violation": 1}),
    ("week_axis", "周次越界（学期之外）", inject_week_axis, {"time_axis_violation": 1}),
    ("automatic_domain", "排进晚间人工保留域", inject_automatic_domain, {"outside_automatic_domain": 1}),
)


def audit_once(
    fragments: Sequence[Mapping[str, Any]],
    *,
    patterns: list[dict[str, Any]],
    rooms: Mapping[str, Any],
) -> dict[str, Any]:
    """跑一遍完整审计：占用/房型/容量/时间轴 + 课时守恒。"""
    report = audit_placement_constraints(
        fragments,
        room_capacity_by_name=rooms.get("room_capacity_by_name"),
        room_type_by_name=rooms.get("room_type_by_name"),
        total_weeks=rooms.get("total_weeks"),
        automatic_periods=frozenset(rooms.get("automatic_periods") or ()),
    )
    conservation = final_hour_audit(patterns, FragmentsSchedule(list(fragments)))
    report["hour_mismatch"] = conservation["mismatch_count"]
    report["hour_under_task_count"] = conservation["under_task_count"]
    report["hour_over_task_count"] = conservation["over_task_count"]
    return report


def run_injection_experiment(
    cover: Mapping[str, Any],
    *,
    patterns: list[dict[str, Any]],
    rooms: Mapping[str, Any],
    expected_clean: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """先验合法课表零违规，再逐类注入并要求对应类别检出。

    `expected_clean` 用来对齐生成侧自己的读法（例如 cover 报告里的 `conservation_mismatch`）：
    课时守恒在一份"有未排任务"的课表上本来就不是 0，那是台账里的已知差额，不是审计的误报。
    冲突类（占用/房型/容量/时间轴）则必须严格为 0，否则就是误报。
    """
    clean_fragments = fragments_from_cover(cover)
    clean = audit_once(clean_fragments, patterns=patterns, rooms=rooms)
    # 冲突类必须零误报；课时守恒单独报，并（如果给了期望值）与生成侧读数对齐。
    false_positive = {field: clean.get(field) for field in AUDIT_FIELDS if clean.get(field)}
    expected_clean = dict(expected_clean or {})
    clean_mismatches = {field: (clean.get(field), value) for field, value in expected_clean.items()
                        if clean.get(field) != value}

    results = []
    for name, description, inject, expected in INJECTIONS:
        fragments = copy.deepcopy(clean_fragments)
        try:
            inject(fragments, rooms, copy.deepcopy(patterns))
        except ValueError as error:
            results.append({"name": name, "description": description, "expected": expected,
                            "detected": False, "skipped": str(error), "observed": {}})
            continue
        observed = audit_once(fragments, patterns=patterns, rooms=rooms)
        detected = all(int(observed.get(field) or 0) >= count for field, count in expected.items())
        side_effects = {
            field: observed.get(field) for field in AUDIT_FIELDS
            if observed.get(field) and field not in expected
        }
        if observed.get("hour_mismatch") and "hour_mismatch" not in expected:
            side_effects["hour_mismatch"] = observed["hour_mismatch"]
        results.append({
            "name": name,
            "description": description,
            "expected": expected,
            "observed_target": {field: observed.get(field) for field in expected},
            "detected": detected,
            "side_effects": side_effects,
        })

    detected_count = sum(1 for item in results if item["detected"] and not item.get("skipped"))
    skipped = [item for item in results if item.get("skipped")]
    return {
        "clean_schedule": {field: clean.get(field) for field in AUDIT_FIELDS}
        | {"hour_mismatch": clean["hour_mismatch"], "total": clean["total"]},
        "clean_hour_read_vs_generation": {"expected": expected_clean, "mismatched_fields": clean_mismatches},
        "false_positives_on_clean_schedule": false_positive,
        "injections": results,
        "injected_count": len(results),
        "detected_count": detected_count,
        "skipped_count": len(skipped),
        "detection_rate": round(detected_count / len(results), 4) if results else None,
        "passed": (not false_positive and not clean_mismatches
                   and detected_count + len(skipped) == len(results) and not skipped),
    }
