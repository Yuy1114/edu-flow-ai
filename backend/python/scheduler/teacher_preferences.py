"""教师画像的软偏好：只决定候选顺序，绝不改变可行域。

排课引擎的硬约束在 ``DynamicSemesterSchedule.base_free`` / ``room_free`` 里判定——
教师、班级、教室的时间互斥，固定不可用矩阵，房型、容量与单日上限（``TEACHER_DAY_CAP``）。
画像不是第四类硬约束，它是一台排序器：在同一个可行域里，先试更符合教师偏好的格子。

由此推出三条不变量，测试里逐条断言：

1. **画像读不到／字段缺失／取值荒谬 → 行为与没有画像时完全一致。** 引擎退回原有的
   确定性贪心顺序（按该任务已用天数的多少与天次序号）。
2. **画像与硬约束冲突 → 硬约束赢。** 候选只是被提前，可行性仍由 ``base_free`` /
   ``room_free`` 判定；画像永远不会把一个不可行的格子变成可行。
3. **画像永远压不过课时守恒。** 为了迁就偏好而少排一次课是不允许的：排不下照样进
   未排任务清单，交人工。

打分口径与 Java 侧「方案满意度」保持同一套分量名（``early_period`` / ``late_period`` /
``preferred_weekday`` / ``preferred_period`` / ``daily_load`` / ``room_type``），生成侧
与评估侧的分数可以放在同一页对照。但注意两处口径的差别，报告里分开写：

- **排序口径**只用已声明的偏好做加权平均（未声明的维度不参与，否则会把差异稀释成
  一堆相近的分）。权重在 ``WEIGHTS`` 一处常量表里。
- **报告口径**与 Java 一致：六个分量等权平均，未声明的记 1.0，便于两侧直接对比。

日课时的单位：引擎的硬上限 ``TEACHER_DAY_CAP`` 按**节**计，而画像的
``max_daily_lessons`` 与 Java 评估侧一样按**天内的课次数**计。两者都写进证据里，
不混用。
"""

from __future__ import annotations

from collections import Counter
import json
from typing import Any, Callable, Mapping, Sequence

# 一处常量表：Phase 1 的正式链路不接受画像权重参数，调口径就是改这里，并且必须在
# 报告里体现（profile_satisfaction.weights），否则两次运行的分数没法解释。
WEIGHTS: dict[str, float] = {
    "early_period": 1.0,
    "late_period": 1.0,
    "preferred_weekday": 0.8,
    "preferred_period": 0.8,
    "daily_load": 1.0,
    "compactness": 0.6,
}

# 与 Java 评估侧同名的六个分量（compactness 是排序侧的额外维度，不进对比口径）。
REPORT_COMPONENTS = (
    "early_period", "late_period", "preferred_weekday",
    "preferred_period", "daily_load", "room_type",
)

EARLY_PERIODS = frozenset({1, 2})
LATE_PERIODS = frozenset({9, 10, 11})

# 与 MlTeacherProfileController 的 low_satisfaction_count 同一阈值。
LOW_SATISFACTION_THRESHOLD = 0.7

KNOWN_KEYS = (
    "avoid_early_period", "avoid_late_period", "prefer_compact_schedule",
    "preferred_weekdays", "preferred_periods", "max_daily_lessons",
    "preferred_room_types",
)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "是"}


def _as_int_list(value: Any) -> tuple[int, ...]:
    if value is None or value == "":
        return ()
    items = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    result: list[int] = []
    for item in items:
        try:
            number = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if number not in result:
            result.append(number)
    return tuple(result)


def _as_str_list(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    items = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    return tuple(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def normalize(raw: Any) -> dict[str, Any]:
    """只认已知键；未知键被忽略（不报错——画像schema会演进，排课不该因此停摆）。"""
    if not isinstance(raw, Mapping):
        return {}
    return {
        "avoid_early_period": _as_bool(raw.get("avoid_early_period")),
        "avoid_late_period": _as_bool(raw.get("avoid_late_period")),
        "prefer_compact_schedule": _as_bool(raw.get("prefer_compact_schedule")),
        "preferred_weekdays": _as_int_list(raw.get("preferred_weekdays")),
        "preferred_periods": _as_int_list(raw.get("preferred_periods")),
        "max_daily_lessons": _as_int_list(raw.get("max_daily_lessons"))[0]
        if _as_int_list(raw.get("max_daily_lessons")) else 0,
        "preferred_room_types": _as_str_list(raw.get("preferred_room_types")),
    }


def build_index(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """{教师ID 或 教师姓名: final_profile} → {``id:12`` / ``name:张三``: 规范化偏好}。

    数字键当教师 ID，其余当姓名，两种键都登记，与引擎里 ``_teacher_keys`` 的两种写法对应。
    """
    index: dict[str, dict[str, Any]] = {}
    for key, value in (payload or {}).items():
        preference = normalize(value)
        text = str(key).strip()
        if not text or not any(preference.get(name) for name in KNOWN_KEYS):
            continue
        if text.isdigit():
            index[f"id:{text}"] = preference
        else:
            index[f"name:{text}"] = preference
    return index


def has_preference(index: Mapping[str, dict[str, Any]], teacher_keys: Sequence[str]) -> bool:
    return any(key in index for key in teacher_keys)


def teacher_keys_of(fragment: Mapping[str, Any]) -> list[str]:
    """片段 → 教师 key。与引擎 ``_teacher_keys`` 同规则：有 ID 用 ``id:``，否则用 ``name:``。"""
    ids: list[Any] = list(fragment.get("teacher_ids") or [])
    ids.extend([fragment.get("primary_teacher_id"), fragment.get("assistant_teacher_id")])
    keys = [f"id:{item}" for item in ids if item not in {None, "", 0, "0"}]
    if not keys:
        name = str(fragment.get("teacher_name") or "").strip()
        if name:
            keys.append(f"name:{name}")
    return list(dict.fromkeys(keys))


def as_item(fragment: Mapping[str, Any]) -> dict[str, Any]:
    """把片段统一成评估项口径。

    排课引擎的片段用 ``day`` / ``start`` / ``consecutive`` / ``room``，cover 片段用
    ``day_of_week`` / ``period_index`` / ``consecutive_slots`` / ``classroom_name``，
    两者在报告里必须能一起算，否则生成侧与展示侧会各读一份字段名。
    """
    week_mask = (
        fragment.get("template_week_mask")
        or fragment.get("week_mask")
        or ()
    )
    return {
        "teacher_keys": list(fragment.get("teacher_keys") or teacher_keys_of(fragment)),
        "teacher_name": fragment.get("teacher_name"),
        "uid": fragment.get("uid") or fragment.get("fragment_id") or fragment.get("source_key"),
        "day": int(fragment.get("day_of_week") or fragment.get("day") or 0),
        "start": int(fragment.get("period_index") or fragment.get("start") or 0),
        "consecutive": int(fragment.get("consecutive_slots") or fragment.get("consecutive") or 0),
        "room": fragment.get("classroom_name") or fragment.get("room"),
        "week_mask": tuple(int(week) for week in week_mask),
    }


def _overlap(start: int, consecutive: int, periods: frozenset[int]) -> int:
    return sum(1 for offset in range(consecutive) if start + offset in periods)


def slot_components(
    preference: Mapping[str, Any],
    *,
    day: int,
    start: int,
    consecutive: int,
    mean_load_periods: float,
    sessions_today: float,
    compact_week_ratio: float,
) -> dict[str, float]:
    """一个候选格子相对某位教师偏好的分量，全部落在 [0, 1]，越大越合意。

    只返回**已声明**的维度（外加与声明无关的状态维度 daily_load / compactness），
    未声明的维度不进这个字典，避免在加权平均里稀释出无意义的相近分数。
    """
    components: dict[str, float] = {}
    if preference["avoid_early_period"]:
        components["early_period"] = 1.0 - _overlap(start, consecutive, EARLY_PERIODS) / consecutive
    if preference["avoid_late_period"]:
        components["late_period"] = 1.0 - _overlap(start, consecutive, LATE_PERIODS) / consecutive
    preferred_weekdays = tuple(preference["preferred_weekdays"])
    if preferred_weekdays:
        components["preferred_weekday"] = 1.0 if day in preferred_weekdays else 0.0
    preferred_periods = tuple(preference["preferred_periods"])
    if preferred_periods:
        components["preferred_period"] = (
            1.0 if any(start + offset in preferred_periods for offset in range(consecutive)) else 0.0
        )

    cap = int(preference["max_daily_lessons"] or 0)
    if cap > 0:
        # 这一天已经排的课次 + 这一次；超一点扣一点，超一倍为 0。
        predicted_sessions = sessions_today + 1.0
        components["daily_load"] = max(0.0, min(1.0, 1.0 - (predicted_sessions - cap) / cap)) \
            if predicted_sessions > cap else 1.0

    if preference["prefer_compact_schedule"]:
        # 紧凑 = 往教师本来就有课的那几天靠，少占新的一天。
        components["compactness"] = compact_week_ratio
    return components


def combine(components: Mapping[str, float]) -> float:
    """按 ``WEIGHTS`` 加权平均；没有任何维度时记 1.0（等于"无偏好"，不惩罚）。"""
    total_weight = 0.0
    total = 0.0
    for name, value in components.items():
        weight = WEIGHTS.get(name, 0.0)
        if weight <= 0:
            continue
        total += weight * value
        total_weight += weight
    return total / total_weight if total_weight else 1.0


class PreferenceRanker:
    """把画像变成候选顺序。没有画像的任务走引擎原有顺序（``order_for`` 返回空列表）。"""

    def __init__(self, index: Mapping[str, dict[str, Any]], room_type_of: Mapping[str, str] | None = None):
        self.index = dict(index)
        self.room_type_of = dict(room_type_of or {})

    def has(self, teacher_keys: Sequence[str]) -> bool:
        return has_preference(self.index, teacher_keys)

    def order_for(
        self,
        *,
        teacher_keys: Sequence[str],
        allowed_days: Sequence[int],
        starts: Sequence[int],
        consecutive: int,
        weeks: Sequence[int],
        day_load: Callable[[str, int, int], int],
        day_sessions: Callable[[str, int, int], int],
        used_days: Mapping[int, int],
    ) -> list[tuple[int, int, float]]:
        """按画像满足度降序给出 (day, start, score)。

        任务有多位教师时取**逐维度最小值**：一个格子只有对所有教师都合意才算好格子，
        与硬约束"任一教师被占即不可行"的方向一致。谁在拉低可以从
        ``satisfaction_report`` 的 ``declared_dimensions`` 与 ``components`` 读出来。
        """
        preferences = [(key, self.index[key]) for key in teacher_keys if key in self.index]
        if not preferences:
            return []

        scored: list[tuple[float, int, int, int, str]] = []
        for day in allowed_days:
            for start in starts:
                per_teacher: list[dict[str, float]] = []
                binding = preferences[0][0]
                binding_score = 2.0
                for teacher_key, preference in preferences:
                    loads = [day_load(teacher_key, week, day) for week in weeks]
                    mean_load = sum(loads) / len(loads) if loads else 0.0
                    sessions = [
                        day_sessions(teacher_key, week, day) for week in weeks
                    ]
                    mean_sessions = sum(sessions) / len(sessions) if sessions else 0.0
                    compact_ratio = (
                        sum(1 for value in sessions if value > 0) / len(sessions)
                        if sessions else 0.0
                    )
                    components = slot_components(
                        preference,
                        day=day, start=start, consecutive=consecutive,
                        mean_load_periods=mean_load,
                        sessions_today=mean_sessions,
                        compact_week_ratio=compact_ratio,
                    )
                    per_teacher.append(components)
                    own = combine(components)
                    if own < binding_score:
                        binding_score = own
                        binding = teacher_key
                merged: dict[str, float] = {}
                for components in per_teacher:
                    for name, value in components.items():
                        merged[name] = min(merged.get(name, 1.0), value)
                scored.append((combine(merged), day, start, int(used_days.get(day, 0)), binding))

        # 排序键：满意度降序 → 该任务已用天数升序（保留引擎自己的均衡倾向）→ 天次序号稳定。
        scored.sort(key=lambda item: (-item[0], item[3], item[1], item[2]))
        return [(day, start, round(score, 6)) for score, day, start, _used, _binding in scored]

    def room_pool_for(
        self, teacher_keys: Sequence[str], room_pool: Sequence[str],
    ) -> list[str]:
        """偏好房型排前，其余保持引擎原序——**只排序，不裁剪**。"""
        wanted: list[str] = []
        for key in teacher_keys:
            preference = self.index.get(key)
            if not preference:
                continue
            for room_type in preference["preferred_room_types"]:
                if room_type not in wanted:
                    wanted.append(room_type)
        if not wanted or not self.room_type_of:
            return list(room_pool)
        preferred = [room for room in room_pool if self.room_type_of.get(room) in wanted]
        others = [room for room in room_pool if self.room_type_of.get(room) not in wanted]
        return preferred + others


def satisfaction_report(
    *,
    index: Mapping[str, dict[str, Any]],
    fragments: Sequence[Mapping[str, Any]],
    room_type_of: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """生成侧的事后评估：分量名与 Java 侧一致，未声明的偏好记 1.0。

    这是给"接入前后对比"用的：同一批任务跑两次（有画像 / 无画像），比这里的
    ``avg_satisfaction_score`` 与 ``low_satisfaction_count``。
    """
    room_type_of = dict(room_type_of or {})
    by_teacher: dict[str, list[dict[str, Any]]] = {}
    names: dict[str, str] = {}
    for fragment in fragments:
        item = as_item(fragment)
        for key in item["teacher_keys"]:
            if key not in index:
                continue
            by_teacher.setdefault(key, []).append(item)
            if item.get("teacher_name") and key not in names:
                names[key] = str(item["teacher_name"])

    reports: list[dict[str, Any]] = []
    for teacher_key, items in sorted(by_teacher.items()):
        preference = index[teacher_key]
        total = max(1, len(items))
        early_count = sum(
            1 for item in items
            if any(period in EARLY_PERIODS for period in _periods_of(item))
        )
        late_count = sum(
            1 for item in items
            if any(period in LATE_PERIODS for period in _periods_of(item))
        )
        preferred_weekdays = tuple(preference["preferred_weekdays"])
        preferred_periods = tuple(preference["preferred_periods"])
        preferred_room_types = tuple(preference["preferred_room_types"])
        weekday_hits = sum(1 for item in items if item["day"] in preferred_weekdays) if preferred_weekdays else total
        period_hits = sum(
            1 for item in items
            if any(period in preferred_periods for period in _periods_of(item))
        ) if preferred_periods else total
        room_hits = sum(
            1 for item in items
            if room_type_of.get(str(item.get("room"))) in preferred_room_types
        ) if preferred_room_types else total

        daily_loads = Counter()
        for item in items:
            for week in item.get("week_mask") or ():
                daily_loads[(week, item["day"])] += 1
        cap = int(preference["max_daily_lessons"] or 0)
        overloaded_days = sum(1 for load in daily_loads.values() if cap > 0 and load > cap)

        components = {
            "early_period": 1.0 - early_count / total if preference["avoid_early_period"] else 1.0,
            "late_period": 1.0 - late_count / total if preference["avoid_late_period"] else 1.0,
            "preferred_weekday": weekday_hits / total,
            "preferred_period": period_hits / total,
            "daily_load": 1.0 - overloaded_days / len(daily_loads) if (cap > 0 and daily_loads) else 1.0,
            "room_type": room_hits / total,
        }
        components = {name: round(max(0.0, min(1.0, value)), 4) for name, value in components.items()}
        # 教师确实提过要求的维度。两个分数各管一件事：
        # ``satisfaction_score`` = 六分量等权（与 Java 方案满意度同口径）；
        # ``preference_score``  = 只对已声明维度取等权平均（"我提的要求被满足了多少"）。
        declared = [
            name for name, is_declared in {
                "early_period": preference["avoid_early_period"],
                "late_period": preference["avoid_late_period"],
                "preferred_weekday": bool(preferred_weekdays),
                "preferred_period": bool(preferred_periods),
                "daily_load": cap > 0,
                "room_type": bool(preferred_room_types),
            }.items() if is_declared
        ]
        preference_score = (
            round(sum(components[name] for name in declared) / len(declared), 4)
            if declared else 1.0
        )
        reports.append({
            "teacher_key": teacher_key,
            "teacher_name": names.get(teacher_key),
            "teacher_id": int(teacher_key.split(":", 1)[1])
            if teacher_key.startswith("id:") and teacher_key.split(":", 1)[1].isdigit() else None,
            "item_count": len(items),
            "days_used": len({item["day"] for item in items}),
            "satisfaction_score": round(sum(components.values()) / len(components), 4),
            "preference_score": preference_score,
            "declared_dimensions": declared,
            "components": components,
            "evidence": {
                "early_item_count": early_count,
                "late_item_count": late_count,
                "preferred_weekday_hits": weekday_hits,
                "preferred_period_hits": period_hits,
                "preferred_room_type_hits": room_hits if preferred_room_types else None,
                "overloaded_days": overloaded_days,
                "max_daily_lessons": cap or None,
            },
            "profile_used": {
                name: preference[name] for name in KNOWN_KEYS
            },
        })

    if not reports:
        return {
            "profile_applied": False,
            "teacher_count": 0,
            "weights": dict(WEIGHTS),
            "note": "没有被画像覆盖的教师参与本次排课；候选顺序与无画像时逐位相同。",
        }

    low = [report for report in reports if report["preference_score"] < LOW_SATISFACTION_THRESHOLD]
    low.sort(key=lambda report: (report["preference_score"], report["teacher_key"]))
    return {
        "profile_applied": True,
        "teacher_count": len(reports),
        "avg_satisfaction_score": round(
            sum(report["satisfaction_score"] for report in reports) / len(reports), 4
        ),
        "avg_preference_score": round(
            sum(report["preference_score"] for report in reports) / len(reports), 4
        ),
        "low_satisfaction_count": len(low),
        "low_satisfaction_threshold": LOW_SATISFACTION_THRESHOLD,
        "low_satisfaction_teachers": [
            {
                "teacher_key": report["teacher_key"],
                "satisfaction_score": report["satisfaction_score"],
                "preference_score": report["preference_score"],
                "components": report["components"],
                "evidence": report["evidence"],
            }
            for report in low[:10]
        ],
        "teachers": reports,
        "weights": dict(WEIGHTS),
        "note": (
            "生成侧口径：satisfaction_score 是六分量等权平均（与 Java 方案满意度一致，"
            "未声明的偏好记 1.0）；preference_score 只对教师已声明的维度取平均，"
            "low_satisfaction 按后者判定——只看一个维度的教师不会被 1.0 稀释。"
        ),
    }


def template_satisfaction_rows(
    reports_by_template: Mapping[str, Mapping[str, Any]],
    *,
    allocation_task_id: int | None = None,
    generation_run_id: str | None = None,
) -> list[dict[str, Any]]:
    """把"每个动态模板的满足度报告"摊平成落库行。

    方案级读数必须按模板算：一次生成产出多个模板（各覆盖不同周次），混在一起平均出来的
    分数不对应任何一个"方案"。``teacher_id`` 只在画像键本身是 ``id:`` 时有值——引擎里的
    片段如果只有姓名，就存姓名，不去猜 ID。
    """
    rows: list[dict[str, Any]] = []
    for template_code, report in reports_by_template.items():
        for teacher in report.get("teachers") or []:
            rows.append({
                "allocation_task_id": allocation_task_id,
                "generation_run_id": generation_run_id,
                "template_code": str(template_code),
                "teacher_id": teacher.get("teacher_id"),
                "teacher_name": teacher.get("teacher_name") or teacher["teacher_key"],
                "teacher_key": teacher["teacher_key"],
                "item_count": teacher["item_count"],
                "days_used": teacher["days_used"],
                "satisfaction_score": teacher["satisfaction_score"],
                "preference_score": teacher["preference_score"],
                # 低满足的判定留在打分的这一侧，展示端只读结论，免得两边各判一次判出分歧。
                "low_satisfaction": 1 if float(teacher["preference_score"]) < LOW_SATISFACTION_THRESHOLD else 0,
                # 列名就是落库列名：这些行的唯一消费者是导出/导入那两段。
                "declared_dimensions_json": json.dumps(teacher["declared_dimensions"], ensure_ascii=False),
                "components_json": json.dumps(teacher["components"], ensure_ascii=False),
                "evidence_json": json.dumps(teacher["evidence"], ensure_ascii=False),
            })
    rows.sort(key=lambda row: (row["template_code"], row["teacher_name"] or ""))
    return rows


def _periods_of(fragment: Mapping[str, Any]) -> range:
    return range(int(fragment["start"]), int(fragment["start"]) + int(fragment["consecutive"]))
