"""按绝对周次占位的动态周模板排课引擎。

链路: task patterns → 显式合班合并 → 在 ``week × day × period`` 上贪心放置
     → 按每周实际课表签名去重 → 动态周模板 → 冲突/课时终审。

时间轴以 45 分钟为一个原子小节：上午 1-4、下午 5-8、晚上 9-10。
自动排课默认只使用 1-8，晚上 9-10 保留给人工调课。理论课占连续 2 小节，
上机/实验课占连续 4 小节。模型仅排序合法候选，永不裁剪可行域。

产出仍保持 template cover 契约，但模板数量由每周活跃任务及其排布动态决定；
每张模板携带明确的 ``week_numbers``，不再固定为 T1/T2 两张模板。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scheduler.paths import OUTPUT_DIR, SINGLE_PLACEMENT_MODEL_DIR
from scheduler.pattern_builder import DEFAULT_OUTPUT_PATH as DEFAULT_PATTERNS_PATH

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402

DEFAULT_OUTPUT_PATH = OUTPUT_DIR / "phase_cover.json"
DEFAULT_REPORT_PATH = OUTPUT_DIR / "phase_cover_report.json"
DEFAULT_UNRESOLVED_PATH = OUTPUT_DIR / "phase_cover_unresolved.jsonl"

DEFAULT_ALLOWED_WEEKDAYS = frozenset(range(1, 6))
# 完整校历每天 11 个 45 分钟原子小节：4（上午）+ 4（下午）+ 3（晚上 19:10-21:35）。
ALL_DAY_PERIODS = frozenset(range(1, 12))  # 每天11节：上午1-4、下午5-8、晚上9-11
MORNING_PERIODS = frozenset(range(1, 5))
AFTERNOON_PERIODS = frozenset(range(5, 9))
EVENING_PERIODS = frozenset(range(9, 11))
# 自动排课不占晚上；9-10 始终保留为人工调课的合法空闲 slot。
DEFAULT_ALLOWED_PERIODS = frozenset(range(1, 9))
# 仅保留参数兼容；主链路只使用其总和作为学期周数，不再据此固定切两张模板。
DEFAULT_PHASE_WEEKS = (8, 10)
# 教师单日节数上限 (真实课表: 最多 6 节 = 3 个课段, 上午+下午+晚课; 默认 4 节更舒适, 但满负荷教师需要 6)
TEACHER_DAY_CAP = 6


def _stable_rotation(value: str, size: int) -> int:
    """Return a process-independent rotation offset for deterministic runs."""
    if size <= 0:
        return 0
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) % size


# ── 数据准备 ─────────────────────────────────────────────────────────

def _parse_classes(row: dict) -> list[str]:
    raw = row.get("class_names") or row.get("class_name") or ""
    text = str(raw).replace("，", ",").replace("、", ",").replace(";", ",").replace("|", ",")
    seen, out = set(), []
    for part in text.split(","):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _parse_list(value: Any) -> list[Any]:
    """Accept native lists, JSON arrays and comma-separated DB values."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return parsed
        return [part.strip() for part in text.replace("，", ",").split(",") if part.strip()]
    return [value]


def _parse_int_list(value: Any) -> list[int]:
    result: list[int] = []
    for item in _parse_list(value):
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number not in result:
            result.append(number)
    return result


def _load_patterns(path: Path) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        r["uid"] = str(r["source_key"])
        r["classes"] = _parse_classes(r)
        r["class_group_ids"] = _parse_list(r.get("class_group_ids"))
        r["teacher_ids"] = _parse_list(r.get("teacher_ids"))
        r["candidate_classroom_ids"] = _parse_list(r.get("candidate_classroom_ids"))
        r["candidate_classroom_names"] = [str(item) for item in _parse_list(r.get("candidate_classroom_names"))]
        r["allowed_weeks"] = _parse_int_list(r.get("allowed_weeks"))
        unavailable = r.get("teacher_unavailable_slots") or []
        if isinstance(unavailable, str):
            try:
                unavailable = json.loads(unavailable)
            except json.JSONDecodeError:
                unavailable = []
        r["teacher_unavailable_slots"] = unavailable if isinstance(unavailable, list) else []
        r["weekly_load"] = int(r["weekly_slot_count"]) * int(r["consecutive_slots"])
    return rows


def _load_rooms_by_type(
    rooms_path: Path | None = None,
) -> tuple[dict[str, list[str]], dict[str, int], dict[str, str]]:
    if rooms_path is not None:
        rows = json.loads(rooms_path.read_text(encoding="utf-8"))
        by_type: dict[str, list[str]] = defaultdict(list)
        capacities: dict[str, int] = {}
        name_by_id: dict[str, str] = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            room_type = str(row.get("classroom_type") or "").strip()
            status = str(row.get("status") or "ACTIVE").strip().upper()
            if status not in {"", "ACTIVE", "ENABLED"}:
                continue
            if name and room_type:
                by_type[room_type].append(name)
                capacity = int(row.get("capacity") or 0)
                if capacity > 0:
                    capacities[name] = capacity
                room_id = row.get("id") if row.get("id") is not None else row.get("classroom_id")
                if room_id is not None:
                    name_by_id[str(room_id)] = name
        for names in by_type.values():
            names.sort()
        return dict(by_type), capacities, name_by_id
    conn = connect(load_db_config())
    by_type: dict[str, list[str]] = defaultdict(list)
    capacities: dict[str, int] = {}
    name_by_id: dict[str, str] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, classroom_type, capacity FROM classroom WHERE status = 'ACTIVE'")
            for r in cur.fetchall():
                by_type[str(r["classroom_type"]).strip()].append(str(r["name"]))
                capacity = int(r.get("capacity") or 0)
                if capacity > 0:
                    capacities[str(r["name"]).strip()] = capacity
                name_by_id[str(r["id"])] = str(r["name"]).strip()
    finally:
        conn.close()
    for names in by_type.values():
        names.sort()
    return dict(by_type), capacities, name_by_id


# ── Step 0: 合班合并 ─────────────────────────────────────────────────
def _merge_sections(patterns: list[dict], *, week_cap: int, t1_weeks: int) -> tuple[list[dict], list[dict]]:
    merged_log: list[dict] = []
    passthrough: list[dict] = []
    # 只接受源数据明确标记的合班组；同教师同课程但未标记时，仍是平行班。
    by_group: dict[tuple, list[dict]] = defaultdict(list)
    for r in patterns:
        merge_group_id = str(r.get("merge_group_id") or "").strip()
        if not merge_group_id:
            passthrough.append(r)
            continue
        t = (r.get("teacher_name") or "").strip()
        key = (merge_group_id, t, r.get("course_code"), r.get("course_name"), r.get("total_hours"),
               r.get("course_type"), r.get("required_room_type"))
        by_group[key].append(r)

    merged_rows: list[dict] = list(passthrough)
    for key, group in by_group.items():
        if len(group) <= 1:
            merged_rows.extend(group)
            continue
        base = dict(group[0])
        all_classes = [c for r in group for c in r["classes"]]
        base["classes"] = list(dict.fromkeys(all_classes))
        base["class_names"] = ",".join(base["classes"])
        base["merged_from"] = sum(int(r.get("merged_from") or 1) for r in group)
        base["student_count"] = sum(int(r.get("student_count") or 0) for r in group)
        base["merged_source_keys"] = [
            k for r in group for k in (r.get("merged_source_keys") or [r["uid"]])
        ]
        merged_rows.append(base)
        merged_log.append({
            "merge_group_id": key[0], "teacher": key[1], "course": key[3], "hours": key[4],
            "sections_before": len(group), "classes": base["classes"],
            "student_count": base["student_count"],
        })
    return merged_rows, merged_log


# ── Step 1: 分段装箱 ─────────────────────────────────────────────────

def assign_phases(
    patterns: list[dict],
    *,
    phase_names: list[str],
    phase_budget: dict[str, int],
    week_cap: int,
):
    class_load = {p: Counter() for p in phase_names}
    teacher_load = {p: Counter() for p in phase_names}
    assign: dict[str, str] = {}
    failures: list[dict] = []
    small, large = phase_names[0], phase_names[-1]

    def entities(r: dict) -> tuple[list[str], str]:
        return r["classes"], (r.get("teacher_name") or "").strip()

    def add(r: dict, phases: list[str]) -> None:
        classes, teacher = entities(r)
        for p in phases:
            for c in classes:
                class_load[p][c] += r["weekly_load"]
            if teacher:
                teacher_load[p][teacher] += r["weekly_load"]

    def fits(r: dict, p: str) -> bool:
        classes, teacher = entities(r)
        w = r["weekly_load"]
        if any(class_load[p][c] + w > week_cap for c in classes):
            return False
        if teacher and teacher_load[p][teacher] + w > week_cap:
            return False
        return True

    def headroom(r: dict, p: str) -> int:
        classes, teacher = entities(r)
        w = r["weekly_load"]
        worst = max([class_load[p][c] + w for c in classes]
                    + ([teacher_load[p][teacher] + w] if teacher else [0]))
        return week_cap - worst

    spanning = [r for r in patterns if int(r["duration_weeks"]) > phase_budget[large]]
    locked = [r for r in patterns
              if phase_budget[small] < int(r["duration_weeks"]) <= phase_budget[large]]
    free = [r for r in patterns if int(r["duration_weeks"]) <= phase_budget[small]]
    free.sort(key=lambda r: (-r["weekly_load"], -len(r["classes"]), -int(r["duration_weeks"])))

    for r in spanning:
        assign[r["uid"]] = "BOTH"
        add(r, phase_names)
    for r in locked:
        if fits(r, large):
            assign[r["uid"]] = large
            add(r, [large])
        elif fits(r, small) and fits(r, large):
            # t2 放不下时降级为跨段: t1 承担前 small 周, t2 承担剩余 (相对掩码守恒)
            assign[r["uid"]] = "BOTH"
            add(r, phase_names)
        else:
            failures.append({"uid": r["uid"], "stage": "locked_phase_full",
                             "course": r.get("course_name"), "teacher": r.get("teacher_name"),
                             "classes": r["classes"]})
            continue
    for r in free:
        options = [p for p in phase_names if fits(r, p)]
        if not options:
            failures.append({"uid": r["uid"], "stage": "free_no_phase",
                             "course": r.get("course_name"), "teacher": r.get("teacher_name"),
                             "classes": r["classes"]})
            continue
        best = max(options, key=lambda p: headroom(r, p))
        assign[r["uid"]] = best
        add(r, [best])

    stats = {
        "class_over": {p: [(c, w) for c, w in class_load[p].items() if w > week_cap] for p in phase_names},
        "teacher_over": {p: [(t, w) for t, w in teacher_load[p].items() if w > week_cap] for p in phase_names},
        "class_load_max": {p: max(class_load[p].values(), default=0) for p in phase_names},
    }
    return assign, failures, stats


# ── Step 2: 段内放格 ─────────────────────────────────────────────────

class PhaseTemplate:
    def __init__(self, name: str, week_budget: int):
        self.name = name
        self.week_budget = week_budget
        self.teacher: dict[tuple, str] = {}
        self.cls: dict[tuple, str] = {}
        self.room: dict[tuple, str] = {}
        self.teacher_day: dict[tuple[str, int], int] = {}  # (teacher, day) -> 已占节数
        self.fragments: list[dict] = []

    def day_load(self, teacher: str, day: int) -> int:
        return self.teacher_day.get((teacher, day), 0)

    def free(self, r: dict, day: int, start: int, room: str,
             room_capacity_by_name: dict[str, int] | None = None) -> bool:
        student_count = int(r.get("student_count") or 0)
        if student_count > 0 and room_capacity_by_name is not None:
            capacity = int(room_capacity_by_name.get(room) or 0)
            if capacity < student_count:
                return False
        teacher = (r.get("teacher_name") or "").strip()
        for off in range(int(r["consecutive_slots"])):
            key = (day, start + off)
            if teacher and (teacher, *key) in self.teacher:
                return False
            if any((c, *key) in self.cls for c in r["classes"]):
                return False
            if (room, *key) in self.room:
                return False
        if teacher and self.day_load(teacher, day) + int(r["consecutive_slots"]) > TEACHER_DAY_CAP:
            return False
        return True

    def occupy(self, r: dict, day: int, start: int, room: str, *, candidate_rank: int, score: float) -> dict:
        teacher = (r.get("teacher_name") or "").strip()
        frag = {"uid": r["uid"], "pattern": r, "teacher": teacher, "classes": r["classes"],
                "room": room, "day": day, "start": start,
                "consecutive": int(r["consecutive_slots"]),
                "candidate_rank": candidate_rank, "score": score}
        self.fragments.append(frag)
        for off in range(int(r["consecutive_slots"])):
            key = (day, start + off)
            if teacher:
                self.teacher[(teacher, *key)] = r["uid"]
            for c in r["classes"]:
                self.cls[(c, *key)] = r["uid"]
            self.room[(room, *key)] = r["uid"]
        if teacher:
            self.teacher_day[(teacher, day)] = self.day_load(teacher, day) + int(r["consecutive_slots"])
        return frag

    def remove_fragment(self, frag: dict) -> None:
        self.fragments.remove(frag)
        for off in range(frag["consecutive"]):
            key = (frag["day"], frag["start"] + off)
            if frag["teacher"]:
                self.teacher.pop((frag["teacher"], *key), None)
            for c in frag["classes"]:
                self.cls.pop((c, *key), None)
            self.room.pop((frag["room"], *key), None)
        if frag["teacher"]:
            self.teacher_day[(frag["teacher"], frag["day"])] = self.day_load(frag["teacher"], frag["day"]) - frag["consecutive"]
            if self.teacher_day[(frag["teacher"], frag["day"])] <= 0:
                self.teacher_day.pop((frag["teacher"], frag["day"]), None)

    def blockers_at(self, r: dict, day: int, start: int) -> set[str]:
        teacher = (r.get("teacher_name") or "").strip()
        found: set[str] = set()
        for off in range(int(r["consecutive_slots"])):
            key = (day, start + off)
            if teacher and (teacher, *key) in self.teacher:
                found.add(self.teacher[(teacher, *key)])
            for c in r["classes"]:
                if (c, *key) in self.cls:
                    found.add(self.cls[(c, *key)])
        return found

    def task_slots(self, uid: str) -> set[tuple[int, int]]:
        return {(f["day"], f["start"]) for f in self.fragments if f["uid"] == uid}


def _valid_starts(consecutive: int, allowed_periods: list[int]) -> list[int]:
    if consecutive == 1:
        return list(allowed_periods)
    max_period = max(allowed_periods)
    # 连堂对齐自然边界: 2 课时块只能从第 1、3 节开始
    return [p for p in allowed_periods
            if (p - 1) % consecutive == 0 and p + consecutive - 1 <= max_period
            and all(p + off in allowed_periods for off in range(consecutive))]


def place_all(
    patterns: list[dict],
    assign: dict[str, str],
    templates: dict[str, PhaseTemplate],
    *,
    rooms_by_type: dict[str, list[str]],
    model_candidates: dict[str, list],
    allowed_days: list[int],
    allowed_periods: list[int],
    room_capacity_by_name: dict[str, int] | None = None,
):
    unplaced: list[dict] = []
    switched = 0
    repairs = 0
    patterns_by_uid = {r["uid"]: r for r in patterns}
    room_names = {name for names in rooms_by_type.values() for name in names}

    def room_pool(r: dict) -> list[str]:
        want = str(r.get("required_room_type") or "").strip()
        # A named room type is a hard constraint. Only tasks with no type may
        # use the complete room inventory.
        pool = rooms_by_type.get(want, []) if want else [n for v in rooms_by_type.values() for n in v]
        rot = _stable_rotation(str(r["uid"]), len(pool))
        return pool[rot:] + pool[:rot]

    def find_spot(r: dict, targets: list[PhaseTemplate], used_slots: set[tuple], used_days: Counter):
        starts = _valid_starts(int(r["consecutive_slots"]), allowed_periods)
        # 1) 模型候选优先 (软偏好): 只在候选无冲突时采纳, 不构成可行域边界
        for rank, cand in enumerate(model_candidates.get(r["uid"], []), start=1):
            day, start, room = cand.day_of_week, cand.period_index, cand.classroom_name
            if day not in allowed_days or start not in starts or (day, start) in used_slots:
                continue
            if room not in room_names or room not in room_pool(r):
                continue
            if all(t.free(r, day, start, room, room_capacity_by_name) for t in targets):
                return day, start, room, rank, float(cand.score)
        # 2) 全枚举兜底: 天数分散优先
        day_order = sorted(allowed_days, key=lambda d: (used_days[d], d))
        for day in day_order:
            for start in starts:
                if (day, start) in used_slots:
                    continue
                for room in room_pool(r):
                    if all(t.free(r, day, start, room, room_capacity_by_name) for t in targets):
                        return day, start, room, 0, 0.0
        return None

    def try_repair(r: dict, template: PhaseTemplate, used_slots: set[tuple]):
        """单阻塞者搬迁: 找一个只被 1 个可移动 fragment 挡住的格子, 挪走它."""
        nonlocal repairs
        starts = _valid_starts(int(r["consecutive_slots"]), allowed_periods)
        for day in allowed_days:
            for start in starts:
                if (day, start) in used_slots:
                    continue
                blocker_uids = template.blockers_at(r, day, start)
                if len(blocker_uids) != 1:
                    continue
                b_uid = next(iter(blocker_uids))
                if assign.get(b_uid) == "BOTH":
                    continue  # 跨段任务两张模板同格, 不动
                b_frags = [f for f in template.fragments
                           if f["uid"] == b_uid and f["day"] == day
                           and not (f["start"] + f["consecutive"] <= start
                                    or start + int(r["consecutive_slots"]) <= f["start"])]
                if len(b_frags) != 1:
                    continue
                b_frag = b_frags[0]
                template.remove_fragment(b_frag)
                room = next((rm for rm in room_pool(r)
                             if template.free(r, day, start, rm, room_capacity_by_name)), None)
                if room is None:
                    template.occupy(patterns_by_uid[b_uid], b_frag["day"], b_frag["start"], b_frag["room"],
                                    candidate_rank=b_frag["candidate_rank"], score=b_frag["score"])
                    continue
                trial = template.occupy(r, day, start, room, candidate_rank=0, score=0.0)
                b_pattern = patterns_by_uid[b_uid]
                new_spot = find_spot(b_pattern, [template], template.task_slots(b_uid), Counter())
                if new_spot is None:
                    template.remove_fragment(trial)
                    template.occupy(b_pattern, b_frag["day"], b_frag["start"], b_frag["room"],
                                    candidate_rank=b_frag["candidate_rank"], score=b_frag["score"])
                    continue
                nd, ns, nr, nrank, nscore = new_spot
                template.occupy(b_pattern, nd, ns, nr, candidate_rank=nrank, score=nscore)
                template.remove_fragment(trial)  # 试占撤销, 格子交还 place_task 统一放置
                repairs += 1
                return day, start, room, 0, 0.0
        return None

    def place_task(r: dict, targets: list[PhaseTemplate]) -> bool:
        need = int(r["weekly_slot_count"])
        used_days: Counter = Counter()
        used_slots: set[tuple] = set()
        placed: list[tuple[PhaseTemplate, dict]] = []
        for _ in range(need):
            spot = find_spot(r, targets, used_slots, used_days)
            if not spot and len(targets) == 1:
                spot = try_repair(r, targets[0], used_slots)
            if not spot:
                for t, frag in placed:  # 回滚, 保持模板干净
                    t.remove_fragment(frag)
                return False
            day, start, room, rank, score = spot
            for t in targets:
                placed.append((t, t.occupy(r, day, start, room, candidate_rank=rank, score=score)))
            used_days[day] += 1
            used_slots.add((day, start))
        return True

    # 教师紧张度: 个人段内周负载越高越先放, 让近饱和的个人课表在空模板上紧凑成型
    teacher_phase_load: dict[tuple[str, str], int] = defaultdict(int)
    for r in patterns:
        phase = assign.get(r["uid"])
        teacher = (r.get("teacher_name") or "").strip()
        if phase is None or not teacher:
            continue
        for p in (list(templates) if phase == "BOTH" else [phase]):
            teacher_phase_load[(teacher, p)] += r["weekly_load"]

    def tightness(r: dict) -> int:
        teacher = (r.get("teacher_name") or "").strip()
        phase = assign.get(r["uid"])
        if not teacher or phase is None:
            return 0
        phases = list(templates) if phase == "BOTH" else [phase]
        return max(teacher_phase_load[(teacher, p)] for p in phases)

    order = sorted(patterns, key=lambda r: (
        0 if assign.get(r["uid"]) == "BOTH" else 1,
        -tightness(r),
        -int(r["consecutive_slots"]),
        -r["weekly_load"],
        -len(r["classes"]),
    ))
    small_budget = min(t.week_budget for t in templates.values())
    for r in order:
        phase = assign.get(r["uid"])
        if phase is None:
            continue
        required_room_type = str(r.get("required_room_type") or "").strip()
        if required_room_type and not rooms_by_type.get(required_room_type):
            unplaced.append({"uid": r["uid"], "course": r.get("course_name"),
                             "teacher": r.get("teacher_name"), "classes": r["classes"],
                             "phase": phase, "weekly_load": r["weekly_load"],
                             "reason": "required_room_type_unavailable"})
            continue
        if int(r.get("student_count") or 0) > 0 and room_capacity_by_name is not None:
            if not any(int(room_capacity_by_name.get(room) or 0) >= int(r["student_count"])
                       for room in room_pool(r)):
                unplaced.append({"uid": r["uid"], "course": r.get("course_name"),
                                 "teacher": r.get("teacher_name"), "classes": r["classes"],
                                 "phase": phase, "weekly_load": r["weekly_load"],
                                 "student_count": r.get("student_count"),
                                 "reason": "classroom_capacity_unavailable"})
                continue
        targets = list(templates.values()) if phase == "BOTH" else [templates[phase]]
        if place_task(r, targets):
            continue
        if phase != "BOTH" and int(r["duration_weeks"]) <= small_budget:
            done = False
            for name, other in templates.items():
                if name == phase:
                    continue
                if place_task(r, [other]):
                    assign[r["uid"]] = name
                    switched += 1
                    done = True
                    break
            if done:
                continue
        unplaced.append({"uid": r["uid"], "course": r.get("course_name"),
                         "teacher": r.get("teacher_name"), "classes": r["classes"],
                         "phase": phase, "weekly_load": r["weekly_load"],
                         "reason": "no_available_slot"})
    return unplaced, switched, repairs


# ── Step 3: 自检 ─────────────────────────────────────────────────────

def audit_template(t: PhaseTemplate) -> dict[str, int]:
    counts = {"teacher": Counter(), "class": Counter(), "room": Counter()}
    for f in t.fragments:
        for off in range(f["consecutive"]):
            key = (f["day"], f["start"] + off)
            if f["teacher"]:
                counts["teacher"][(f["teacher"], *key)] += 1
            for c in f["classes"]:
                counts["class"][(c, *key)] += 1
            counts["room"][(f["room"], *key)] += 1
    return {k: sum(v - 1 for v in c.values() if v > 1) for k, c in counts.items()}


def hour_conservation(patterns: list[dict], assign: dict[str, str], templates: dict[str, PhaseTemplate]) -> dict:
    """按预算展开后, 每任务实际课时 vs pattern 课时."""
    frag_count: Counter = Counter()
    for t in templates.values():
        for f in t.fragments:
            frag_count[(f["uid"], t.name)] += 1
    ok, skipped_unplaced, mismatch = 0, 0, []
    total_budget = sum(t.week_budget for t in templates.values())
    for r in patterns:
        uid, phase = r["uid"], assign.get(r["uid"])
        if phase is None:
            continue
        if not any(frag_count[(uid, name)] for name in templates):
            # 未排任务由 remaining/unresolved 单独报告；守恒审计只判断已经
            # 进入课表的任务，避免把同一个失败重复计为课时错误。
            skipped_unplaced += 1
            continue
        need_weeks = int(r["duration_weeks"])
        session_hours = int(r["session_hours"])
        expected = int(r["weekly_slot_count"]) * need_weeks * session_hours
        if phase == "BOTH":
            budget = total_budget
            weekly_counts = {frag_count[(uid, name)] for name in templates}
            weekly = weekly_counts.pop() if len(weekly_counts) == 1 else -1
        else:
            budget = templates[phase].week_budget
            weekly = frag_count[(uid, phase)]
        actual_weeks = min(need_weeks, budget)
        actual = weekly * actual_weeks * session_hours if weekly >= 0 else -1
        if actual == expected and actual_weeks == need_weeks:
            ok += 1
        else:
            mismatch.append({"uid": uid, "course": r.get("course_name"), "expected_h": expected,
                             "actual_h": actual, "need_weeks": need_weeks, "budget": budget})
    return {
        "ok": ok,
        "skipped_unplaced_count": skipped_unplaced,
        "mismatch_count": len(mismatch),
        "mismatch_preview": mismatch[:10],
    }


# ── 动态学期排课（主链路）────────────────────────────────────────────

def _teacher_keys(pattern: dict[str, Any]) -> list[str]:
    ids = [
        *_parse_list(pattern.get("teacher_ids")),
        pattern.get("primary_teacher_id"),
        pattern.get("assistant_teacher_id"),
    ]
    keys = [f"id:{item}" for item in ids if item not in {None, "", 0, "0"}]
    if not keys:
        name = str(pattern.get("teacher_name") or "").strip()
        if name:
            keys.append(f"name:{name}")
    return list(dict.fromkeys(keys))


def _class_keys(pattern: dict[str, Any]) -> list[str]:
    ids = _parse_list(pattern.get("class_group_ids"))
    if ids:
        return list(dict.fromkeys(f"id:{item}" for item in ids if item not in {None, ""}))
    return list(dict.fromkeys(f"name:{name}" for name in pattern.get("classes", []) if name))


def _unavailable_for_task(
    pattern: dict[str, Any], weeks: tuple[int, ...], day: int, start: int, consecutive: int,
) -> bool:
    teacher_ids = {key.removeprefix("id:") for key in _teacher_keys(pattern) if key.startswith("id:")}
    for raw in pattern.get("teacher_unavailable_slots") or []:
        if not isinstance(raw, dict):
            continue
        unavailable_teacher = raw.get("teacher_id")
        if unavailable_teacher not in {None, ""} and teacher_ids and str(unavailable_teacher) not in teacher_ids:
            continue
        try:
            unavailable_day = int(raw.get("day_of_week") or raw.get("day") or 0)
            unavailable_period = int(raw.get("period_index") or raw.get("period") or 0)
            unavailable_week = int(raw.get("week_number") or raw.get("week") or 0)
        except (TypeError, ValueError):
            continue
        if unavailable_day != day or unavailable_period not in range(start, start + consecutive):
            continue
        if unavailable_week == 0 or unavailable_week in weeks:
            return True
    return False


def _candidate_week_masks(pattern: dict[str, Any], total_weeks: int) -> list[tuple[int, ...]]:
    """Build deterministic absolute-week candidates shared by every task fragment."""
    duration = int(pattern.get("duration_weeks") or 0)
    if duration <= 0 or duration > total_weeks:
        return []

    all_weeks = list(range(1, total_weeks + 1))
    allowed = sorted({week for week in _parse_int_list(pattern.get("allowed_weeks")) if 1 <= week <= total_weeks})
    allowed = allowed or all_weeks
    allowed_set = set(allowed)

    fixed = _parse_int_list(pattern.get("fixed_week_mask"))
    if not fixed and (
        pattern.get("week_mask_is_fixed")
        or str(pattern.get("pattern_source") or "") == "observed_history"
    ):
        fixed = _parse_int_list(pattern.get("week_mask") or pattern.get("observed_weeks"))
    if fixed:
        normalized = tuple(sorted({week for week in fixed if 1 <= week <= total_weeks}))
        return [normalized] if len(normalized) == duration and set(normalized) <= allowed_set else []

    candidates: list[tuple[int, ...]] = []
    for start in range(1, total_weeks - duration + 2):
        mask = tuple(range(start, start + duration))
        if set(mask) <= allowed_set:
            candidates.append(mask)

    # An explicit availability mask may intentionally be discontinuous (for
    # example odd weeks). In that case, use deterministic slices of it.
    if not candidates and len(allowed) >= duration:
        candidates.extend(tuple(allowed[index:index + duration])
                          for index in range(0, len(allowed) - duration + 1))

    preferred = tuple(_parse_int_list(pattern.get("week_mask")))
    if preferred in candidates:
        candidates.remove(preferred)
        candidates.insert(0, preferred)
    return candidates


class DynamicSemesterSchedule:
    """A semester-wide occupancy map keyed by absolute week coordinates."""

    def __init__(self, total_weeks: int):
        self.name = "semester_dynamic"
        self.week_budget = total_weeks
        self.week_numbers = tuple(range(1, total_weeks + 1))
        self.teacher: dict[tuple[str, int, int, int], str] = {}
        self.cls: dict[tuple[str, int, int, int], str] = {}
        self.room: dict[tuple[str, int, int, int], str] = {}
        self.teacher_day: dict[tuple[str, int, int], int] = {}
        self.fragments: list[dict[str, Any]] = []
        self.repair_count = 0
        # The coordinate maps above retain the owning uid for repair/audit.
        # These parallel bitsets make the much hotter feasibility checks O(1)
        # in the number of weeks instead of rebuilding tuple keys for every
        # candidate room and every week.
        self._teacher_week_bits: dict[tuple[str, int, int], int] = {}
        self._class_week_bits: dict[tuple[str, int, int], int] = {}
        self._room_week_bits: dict[tuple[str, int, int], int] = {}
        self._week_bits_cache: dict[tuple[int, ...], int] = {}
        self._pattern_facts_cache: dict[
            int,
            tuple[
                dict[str, Any],
                tuple[tuple[str, ...], tuple[str, ...], int, dict[tuple[int, int], int]],
            ],
        ] = {}
        self._fragments_by_uid: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._teacher_day_uid_counts: dict[tuple[str, int, int], Counter] = defaultdict(Counter)
        self._teacher_day_load_week_bits: dict[tuple[str, int], dict[int, int]] = defaultdict(dict)

    def day_load(self, teacher: str, week: int, day: int) -> int:
        return self.teacher_day.get((teacher, week, day), 0)

    def _week_bits(self, weeks: tuple[int, ...]) -> int:
        cached = self._week_bits_cache.get(weeks)
        if cached is not None:
            return cached
        bits = 0
        for week in weeks:
            bits |= 1 << (week - 1)
        self._week_bits_cache[weeks] = bits
        return bits

    def _pattern_facts(
        self, pattern: dict[str, Any],
    ) -> tuple[tuple[str, ...], tuple[str, ...], int, dict[tuple[int, int], int]]:
        """Parse immutable task constraints once for the candidate hot path."""
        cache_key = id(pattern)
        cached = self._pattern_facts_cache.get(cache_key)
        if cached is not None and cached[0] is pattern:
            return cached[1]

        teachers = tuple(_teacher_keys(pattern))
        classes = tuple(_class_keys(pattern))
        consecutive = int(pattern["consecutive_slots"])
        teacher_ids = {key.removeprefix("id:") for key in teachers if key.startswith("id:")}
        unavailable_bits: dict[tuple[int, int], int] = {}
        all_week_bits = (1 << self.week_budget) - 1
        for raw in pattern.get("teacher_unavailable_slots") or []:
            if not isinstance(raw, dict):
                continue
            unavailable_teacher = raw.get("teacher_id")
            if (
                unavailable_teacher not in {None, ""}
                and teacher_ids
                and str(unavailable_teacher) not in teacher_ids
            ):
                continue
            try:
                day = int(raw.get("day_of_week") or raw.get("day") or 0)
                period = int(raw.get("period_index") or raw.get("period") or 0)
                week = int(raw.get("week_number") or raw.get("week") or 0)
            except (TypeError, ValueError):
                continue
            if week == 0:
                bits = all_week_bits
            elif 1 <= week <= self.week_budget:
                bits = 1 << (week - 1)
            else:
                continue
            coordinate = (day, period)
            unavailable_bits[coordinate] = unavailable_bits.get(coordinate, 0) | bits

        facts = teachers, classes, consecutive, unavailable_bits
        # Retaining the pattern reference prevents CPython from reusing an id
        # for a later, unrelated task while this schedule is still alive.
        self._pattern_facts_cache[cache_key] = (pattern, facts)
        return facts

    @staticmethod
    def _set_week_bits(store: dict[tuple[str, int, int], int], key: tuple[str, int, int], bits: int) -> None:
        store[key] = store.get(key, 0) | bits

    @staticmethod
    def _clear_week_bits(store: dict[tuple[str, int, int], int], key: tuple[str, int, int], bits: int) -> None:
        remaining = store.get(key, 0) & ~bits
        if remaining:
            store[key] = remaining
        else:
            store.pop(key, None)

    def base_free(
        self,
        pattern: dict[str, Any],
        weeks: tuple[int, ...],
        day: int,
        start: int,
    ) -> bool:
        """Check teacher/class constraints that do not depend on a room."""
        teachers, classes, consecutive, unavailable_bits = self._pattern_facts(pattern)
        week_bits = self._week_bits(weeks)
        for offset in range(consecutive):
            period = start + offset
            if unavailable_bits.get((day, period), 0) & week_bits:
                return False
            if any(self._teacher_week_bits.get((teacher, day, period), 0) & week_bits
                   for teacher in teachers):
                return False
            if any(self._class_week_bits.get((class_key, day, period), 0) & week_bits
                   for class_key in classes):
                return False
        for teacher in teachers:
            load_levels = self._teacher_day_load_week_bits.get((teacher, day), {})
            if any(
                load + consecutive > TEACHER_DAY_CAP and occupied_weeks & week_bits
                for load, occupied_weeks in load_levels.items()
            ):
                return False
        return True

    def room_free(
        self,
        pattern: dict[str, Any],
        weeks: tuple[int, ...],
        day: int,
        start: int,
        room: str,
        room_capacity_by_name: dict[str, int] | None = None,
    ) -> bool:
        student_count = int(pattern.get("student_count") or 0)
        if student_count > 0 and room_capacity_by_name is not None:
            if int(room_capacity_by_name.get(room) or 0) < student_count:
                return False
        _, _, consecutive, _ = self._pattern_facts(pattern)
        week_bits = self._week_bits(weeks)
        return not any(
            self._room_week_bits.get((room, day, start + offset), 0) & week_bits
            for offset in range(consecutive)
        )

    def first_free_room(
        self,
        weeks: tuple[int, ...],
        day: int,
        start: int,
        consecutive: int,
        rooms: list[str],
    ) -> str | None:
        """Return the first compatible room from an already capacity-filtered pool."""
        week_bits = self._week_bits(weeks)
        occupied = self._room_week_bits
        for room in rooms:
            for offset in range(consecutive):
                if occupied.get((room, day, start + offset), 0) & week_bits:
                    break
            else:
                return room
        return None

    def _update_teacher_day_load_bits(
        self, teacher: str, week: int, day: int, old_load: int, new_load: int,
    ) -> None:
        coordinate = (teacher, day)
        levels = self._teacher_day_load_week_bits[coordinate]
        week_bit = 1 << (week - 1)
        if old_load > 0:
            remaining = levels.get(old_load, 0) & ~week_bit
            if remaining:
                levels[old_load] = remaining
            else:
                levels.pop(old_load, None)
        if new_load > 0:
            levels[new_load] = levels.get(new_load, 0) | week_bit
        if not levels:
            self._teacher_day_load_week_bits.pop(coordinate, None)

    def free(
        self,
        pattern: dict[str, Any],
        weeks: tuple[int, ...],
        day: int,
        start: int,
        room: str,
        room_capacity_by_name: dict[str, int] | None = None,
    ) -> bool:
        return (
            self.base_free(pattern, weeks, day, start)
            and self.room_free(
                pattern, weeks, day, start, room, room_capacity_by_name,
            )
        )

    def occupy(
        self,
        pattern: dict[str, Any],
        weeks: tuple[int, ...],
        day: int,
        start: int,
        room: str,
        *,
        candidate_rank: int,
        score: float,
    ) -> dict[str, Any]:
        teachers, classes, consecutive, _ = self._pattern_facts(pattern)
        session_index = len(self._fragments_by_uid[pattern["uid"]]) + 1
        fragment = {
            "uid": pattern["uid"],
            "session_index": session_index,
            "logical_fragment_id": f"{pattern['uid']}#session{session_index}",
            "pattern": pattern,
            "teacher": str(pattern.get("teacher_name") or "").strip(),
            "teacher_keys": teachers,
            "classes": pattern.get("classes", []),
            "class_keys": classes,
            "room": room,
            "day": day,
            "start": start,
            "consecutive": consecutive,
            "week_mask": tuple(weeks),
            "candidate_rank": candidate_rank,
            "score": score,
        }
        self.fragments.append(fragment)
        self._fragments_by_uid[pattern["uid"]].append(fragment)
        week_bits = self._week_bits(weeks)
        for off in range(consecutive):
            period = start + off
            for teacher in teachers:
                self._set_week_bits(self._teacher_week_bits, (teacher, day, period), week_bits)
            for class_key in classes:
                self._set_week_bits(self._class_week_bits, (class_key, day, period), week_bits)
            self._set_week_bits(self._room_week_bits, (room, day, period), week_bits)
        for week in weeks:
            for off in range(consecutive):
                period = start + off
                for teacher in teachers:
                    self.teacher[(teacher, week, day, period)] = pattern["uid"]
                for class_key in classes:
                    self.cls[(class_key, week, day, period)] = pattern["uid"]
                self.room[(room, week, day, period)] = pattern["uid"]
            for teacher in teachers:
                key = (teacher, week, day)
                old_load = self.teacher_day.get(key, 0)
                new_load = old_load + consecutive
                self.teacher_day[key] = new_load
                self._update_teacher_day_load_bits(teacher, week, day, old_load, new_load)
                self._teacher_day_uid_counts[key][pattern["uid"]] += consecutive
        return fragment

    def remove_fragment(self, fragment: dict[str, Any]) -> None:
        self.fragments.remove(fragment)
        uid_fragments = self._fragments_by_uid.get(fragment["uid"])
        if uid_fragments is not None:
            uid_fragments.remove(fragment)
            if not uid_fragments:
                self._fragments_by_uid.pop(fragment["uid"], None)
        week_bits = self._week_bits(tuple(fragment["week_mask"]))
        for off in range(fragment["consecutive"]):
            period = fragment["start"] + off
            for teacher in fragment["teacher_keys"]:
                self._clear_week_bits(
                    self._teacher_week_bits, (teacher, fragment["day"], period), week_bits,
                )
            for class_key in fragment["class_keys"]:
                self._clear_week_bits(
                    self._class_week_bits, (class_key, fragment["day"], period), week_bits,
                )
            self._clear_week_bits(
                self._room_week_bits, (fragment["room"], fragment["day"], period), week_bits,
            )
        for week in fragment["week_mask"]:
            for off in range(fragment["consecutive"]):
                period = fragment["start"] + off
                for teacher in fragment["teacher_keys"]:
                    self.teacher.pop((teacher, week, fragment["day"], period), None)
                for class_key in fragment["class_keys"]:
                    self.cls.pop((class_key, week, fragment["day"], period), None)
                self.room.pop((fragment["room"], week, fragment["day"], period), None)
            for teacher in fragment["teacher_keys"]:
                key = (teacher, week, fragment["day"])
                old_load = self.teacher_day.get(key, 0)
                remaining = old_load - fragment["consecutive"]
                if remaining > 0:
                    self.teacher_day[key] = remaining
                else:
                    self.teacher_day.pop(key, None)
                self._update_teacher_day_load_bits(
                    teacher, week, fragment["day"], old_load, max(remaining, 0),
                )
                uid_counts = self._teacher_day_uid_counts.get(key)
                if uid_counts is not None:
                    uid_counts[fragment["uid"]] -= fragment["consecutive"]
                    if uid_counts[fragment["uid"]] <= 0:
                        uid_counts.pop(fragment["uid"], None)
                    if not uid_counts:
                        self._teacher_day_uid_counts.pop(key, None)

    def task_fragments(self, uid: str) -> list[dict[str, Any]]:
        return list(self._fragments_by_uid.get(uid, ()))

    def base_blocking_uids(
        self,
        pattern: dict[str, Any],
        weeks: tuple[int, ...],
        day: int,
        start: int,
    ) -> set[str]:
        """Return teacher/class and daily-load blockers for one time block."""
        blockers: set[str] = set()
        teachers, classes, consecutive, _ = self._pattern_facts(pattern)
        for week in weeks:
            for offset in range(consecutive):
                period = start + offset
                for teacher in teachers:
                    blocker = self.teacher.get((teacher, week, day, period))
                    if blocker:
                        blockers.add(blocker)
                for class_key in classes:
                    blocker = self.cls.get((class_key, week, day, period))
                    if blocker:
                        blockers.add(blocker)
            for teacher in teachers:
                if self.day_load(teacher, week, day) + consecutive > TEACHER_DAY_CAP:
                    blockers.update(self._teacher_day_uid_counts.get((teacher, week, day), ()))
        blockers.discard(str(pattern.get("uid") or ""))
        return blockers

    def room_blocking_uids(
        self,
        weeks: tuple[int, ...],
        day: int,
        start: int,
        consecutive: int,
        room: str,
    ) -> set[str]:
        blockers: set[str] = set()
        for week in weeks:
            for offset in range(consecutive):
                blocker = self.room.get((room, week, day, start + offset))
                if blocker:
                    blockers.add(blocker)
        return blockers

    def blocking_uids(
        self,
        pattern: dict[str, Any],
        weeks: tuple[int, ...],
        day: int,
        start: int,
        room: str,
    ) -> set[str]:
        """Return real teacher/class/room blockers, including daily-load blockers."""
        _, _, consecutive, _ = self._pattern_facts(pattern)
        blockers = self.base_blocking_uids(pattern, weeks, day, start)
        blockers.update(self.room_blocking_uids(weeks, day, start, consecutive, room))
        blockers.discard(str(pattern.get("uid") or ""))
        return blockers


def place_dynamic(
    patterns: list[dict[str, Any]],
    schedule: DynamicSemesterSchedule,
    *,
    rooms_by_type: dict[str, list[str]],
    model_candidates: dict[str, list[Any]],
    allowed_days: list[int],
    allowed_periods: list[int],
    room_capacity_by_name: dict[str, int] | None = None,
    room_name_by_id: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, tuple[int, ...]]]:
    """Place tasks on absolute weeks; every fragment of one task shares one week mask."""
    unplaced: list[dict[str, Any]] = []
    week_assignment: dict[str, tuple[int, ...]] = {}
    room_name_by_id = room_name_by_id or {}
    room_names = {name for names in rooms_by_type.values() for name in names}
    patterns_by_uid = {pattern["uid"]: pattern for pattern in patterns}
    known_uids = set(patterns_by_uid)
    raw_room_pool_cache: dict[str, list[str]] = {}
    eligible_room_pool_cache: dict[str, list[str]] = {}
    week_masks_by_uid = {
        pattern["uid"]: _candidate_week_masks(pattern, schedule.week_budget)
        for pattern in patterns
    }
    starts_by_consecutive = {
        consecutive: _valid_starts(consecutive, allowed_periods)
        for consecutive in {int(pattern["consecutive_slots"]) for pattern in patterns}
    }

    # Warm the immutable task-facts cache before sorting/placement. This also
    # ensures every later feasibility check shares the exact same identities.
    for pattern in patterns:
        schedule._pattern_facts(pattern)

    def room_pool(pattern: dict[str, Any]) -> list[str]:
        cached = raw_room_pool_cache.get(pattern["uid"])
        if cached is not None:
            return cached
        wanted_type = str(pattern.get("required_room_type") or "").strip()
        pool = list(rooms_by_type.get(wanted_type, [])) if wanted_type else sorted(room_names)

        fixed_name = str(pattern.get("fixed_classroom_name") or "").strip()
        fixed_id = pattern.get("fixed_classroom_id")
        if not fixed_name and fixed_id not in {None, "", 0, "0"}:
            fixed_name = room_name_by_id.get(str(fixed_id), "")
        if fixed_name:
            pool = [room for room in pool if room == fixed_name]

        candidates = {str(name) for name in _parse_list(pattern.get("candidate_classroom_names")) if name}
        candidates.update(
            room_name_by_id[str(room_id)]
            for room_id in _parse_list(pattern.get("candidate_classroom_ids"))
            if str(room_id) in room_name_by_id
        )
        if candidates:
            pool = [room for room in pool if room in candidates]

        # Keep the relative order independent of pool size.  Adding classrooms
        # must not reshuffle all existing choices and make a richer resource
        # scenario look worse solely because of a modulo rotation.
        result = sorted(pool)
        raw_room_pool_cache[pattern["uid"]] = result
        return result

    def eligible_room_pool(pattern: dict[str, Any]) -> list[str]:
        cached = eligible_room_pool_cache.get(pattern["uid"])
        if cached is not None:
            return cached
        pool = room_pool(pattern)
        student_count = int(pattern.get("student_count") or 0)
        if student_count > 0 and room_capacity_by_name is not None:
            pool = [
                room for room in pool
                if int(room_capacity_by_name.get(room) or 0) >= student_count
            ]
        eligible_room_pool_cache[pattern["uid"]] = pool
        return pool

    def candidate_value(candidate: Any, field: str, default: Any = None) -> Any:
        if isinstance(candidate, dict):
            return candidate.get(field, default)
        return getattr(candidate, field, default)

    def find_spot(
        pattern: dict[str, Any],
        weeks: tuple[int, ...],
        used_slots: set[tuple[int, int]],
        used_days: Counter,
        pool: list[str],
    ) -> tuple[int, int, str, int, float] | None:
        consecutive = int(pattern["consecutive_slots"])
        starts = starts_by_consecutive[consecutive]
        preferred_candidates = model_candidates.get(pattern["uid"], [])
        pool_set = set(pool) if preferred_candidates else set()
        for rank, candidate in enumerate(preferred_candidates, start=1):
            day = int(candidate_value(candidate, "day_of_week", 0) or 0)
            start = int(candidate_value(candidate, "period_index", 0) or 0)
            room = str(candidate_value(candidate, "classroom_name", "") or "")
            if day not in allowed_days or start not in starts or (day, start) in used_slots or room not in pool_set:
                continue
            if (
                schedule.base_free(pattern, weeks, day, start)
                and schedule.room_free(
                    pattern, weeks, day, start, room, room_capacity_by_name,
                )
            ):
                return day, start, room, rank, float(candidate_value(candidate, "score", 0.0) or 0.0)

        for day in sorted(allowed_days, key=lambda value: (used_days[value], value)):
            for start in starts:
                if (day, start) in used_slots:
                    continue
                if not schedule.base_free(pattern, weeks, day, start):
                    continue
                room = schedule.first_free_room(weeks, day, start, consecutive, pool)
                if room is not None:
                    return day, start, room, 0, 0.0
        return None

    def place_task(pattern: dict[str, Any], pool: list[str]) -> bool:
        for weeks in week_masks_by_uid[pattern["uid"]]:
            used_days: Counter = Counter()
            used_slots: set[tuple[int, int]] = set()
            placed: list[dict[str, Any]] = []
            for _ in range(int(pattern["weekly_slot_count"])):
                spot = find_spot(pattern, weeks, used_slots, used_days, pool)
                if spot is None:
                    for fragment in reversed(placed):
                        schedule.remove_fragment(fragment)
                    break
                day, start, room, rank, score = spot
                placed.append(schedule.occupy(
                    pattern, weeks, day, start, room, candidate_rank=rank, score=score,
                ))
                used_days[day] += 1
                used_slots.add((day, start))
            else:
                week_assignment[pattern["uid"]] = weeks
                return True
        return False

    def remove_task(uid: str) -> list[dict[str, Any]]:
        fragments = sorted(
            schedule.task_fragments(uid),
            key=lambda fragment: int(fragment.get("session_index") or 0),
        )
        for fragment in reversed(fragments):
            schedule.remove_fragment(fragment)
        week_assignment.pop(uid, None)
        return fragments

    def restore_task(uid: str, fragments: list[dict[str, Any]], weeks: tuple[int, ...]) -> None:
        pattern = patterns_by_uid[uid]
        for original in fragments:
            restored = schedule.occupy(
                pattern,
                tuple(original["week_mask"]),
                original["day"],
                original["start"],
                original["room"],
                candidate_rank=original["candidate_rank"],
                score=original["score"],
            )
            # The logical identity is stable across dynamic template rebuilds
            # and through a failed repair rollback.
            restored["session_index"] = original.get("session_index")
            restored["logical_fragment_id"] = original.get("logical_fragment_id")
        week_assignment[uid] = weeks

    def try_local_repair(pattern: dict[str, Any], pool: list[str]) -> bool:
        """Bounded 1-2 task ejection/reinsertion, including room blockers."""
        blocker_sets: set[tuple[str, ...]] = set()
        consecutive = int(pattern["consecutive_slots"])
        starts = starts_by_consecutive[consecutive]
        for weeks in week_masks_by_uid[pattern["uid"]]:
            for day in allowed_days:
                for start in starts:
                    common_blockers = schedule.base_blocking_uids(pattern, weeks, day, start)
                    if len(common_blockers) > 2:
                        continue
                    for room in pool:
                        blockers = common_blockers | schedule.room_blocking_uids(
                            weeks, day, start, consecutive, room,
                        )
                        blockers.discard(str(pattern.get("uid") or ""))
                        if 1 <= len(blockers) <= 2 and blockers <= known_uids:
                            blocker_sets.add(tuple(sorted(blockers)))
        # Bound worst-case latency: deterministic, smallest ejection sets first.
        candidates = sorted(blocker_sets, key=lambda value: (len(value), value))[:40]
        for blocker_uids in candidates:
            original_fragments: dict[str, list[dict[str, Any]]] = {}
            original_weeks: dict[str, tuple[int, ...]] = {}
            for uid in blocker_uids:
                original_weeks[uid] = week_assignment[uid]
                original_fragments[uid] = remove_task(uid)

            pending_placed = place_task(pattern, pool)
            reinserted: list[str] = []
            if pending_placed:
                blocker_order = sorted(
                    blocker_uids,
                    key=lambda uid: (
                        -int(patterns_by_uid[uid].get("duration_weeks") or 0),
                        -int(patterns_by_uid[uid].get("consecutive_slots") or 0),
                        uid,
                    ),
                )
                for uid in blocker_order:
                    blocker_pattern = patterns_by_uid[uid]
                    if not place_task(blocker_pattern, eligible_room_pool(blocker_pattern)):
                        break
                    reinserted.append(uid)
                else:
                    schedule.repair_count += len(blocker_uids)
                    return True

            # Restore the exact pre-trial state before trying another blocker set.
            remove_task(pattern["uid"])
            for uid in blocker_uids:
                remove_task(uid)
            for uid in blocker_uids:
                restore_task(uid, original_fragments[uid], original_weeks[uid])
        return False

    teacher_pressure: Counter = Counter()
    class_pressure: Counter = Counter()
    for pattern in patterns:
        weighted = int(pattern.get("weekly_load") or 0) * int(pattern.get("duration_weeks") or 0)
        teachers, classes, _, _ = schedule._pattern_facts(pattern)
        for teacher in teachers:
            teacher_pressure[teacher] += weighted
        for class_key in classes:
            class_pressure[class_key] += weighted

    def pressure(pattern: dict[str, Any]) -> int:
        teachers, classes, _, _ = schedule._pattern_facts(pattern)
        values = [teacher_pressure[key] for key in teachers]
        values.extend(class_pressure[key] for key in classes)
        return max(values, default=0)

    order = sorted(patterns, key=lambda pattern: (
        -int(pattern.get("duration_weeks") or 0),
        -pressure(pattern),
        -int(pattern.get("consecutive_slots") or 0),
        -int(pattern.get("weekly_load") or 0),
        -len(schedule._pattern_facts(pattern)[1]),
        str(pattern.get("uid") or ""),
    ))

    for pattern in order:
        required_room_type = str(pattern.get("required_room_type") or "").strip()
        if required_room_type and not rooms_by_type.get(required_room_type):
            unplaced.append({
                "uid": pattern["uid"], "course": pattern.get("course_name"),
                "teacher": pattern.get("teacher_name"), "classes": pattern.get("classes", []),
                "reason": "required_room_type_unavailable",
            })
            continue
        masks = week_masks_by_uid[pattern["uid"]]
        if not masks:
            unplaced.append({
                "uid": pattern["uid"], "course": pattern.get("course_name"),
                "teacher": pattern.get("teacher_name"), "classes": pattern.get("classes", []),
                "reason": "allowed_weeks_insufficient",
            })
            continue
        raw_pool = room_pool(pattern)
        if not raw_pool:
            unplaced.append({
                "uid": pattern["uid"], "course": pattern.get("course_name"),
                "teacher": pattern.get("teacher_name"), "classes": pattern.get("classes", []),
                "reason": "fixed_or_candidate_classroom_unavailable",
            })
            continue
        student_count = int(pattern.get("student_count") or 0)
        pool = eligible_room_pool(pattern)
        if not pool:
            unplaced.append({
                "uid": pattern["uid"], "course": pattern.get("course_name"),
                "teacher": pattern.get("teacher_name"), "classes": pattern.get("classes", []),
                "student_count": student_count, "reason": "classroom_capacity_unavailable",
            })
            continue
        if not place_task(pattern, pool) and not try_local_repair(pattern, pool):
            unplaced.append({
                "uid": pattern["uid"], "course": pattern.get("course_name"),
                "teacher": pattern.get("teacher_name"), "classes": pattern.get("classes", []),
                "weekly_load": pattern.get("weekly_load"), "reason": "automatic_search_exhausted",
                "resolution": "manual_review_or_use_reserved_slots",
                "proven_infeasible": False,
            })
    return unplaced, week_assignment


def audit_dynamic_schedule(schedule: DynamicSemesterSchedule) -> dict[str, int]:
    counts = {"teacher": Counter(), "class": Counter(), "room": Counter()}
    for fragment in schedule.fragments:
        for week in fragment["week_mask"]:
            for offset in range(fragment["consecutive"]):
                coordinate = (week, fragment["day"], fragment["start"] + offset)
                for teacher in fragment["teacher_keys"]:
                    counts["teacher"][(teacher, *coordinate)] += 1
                for class_key in fragment["class_keys"]:
                    counts["class"][(class_key, *coordinate)] += 1
                counts["room"][(fragment["room"], *coordinate)] += 1
    return {name: sum(value - 1 for value in counter.values() if value > 1)
            for name, counter in counts.items()}


def final_hour_audit(
    patterns: list[dict[str, Any]], schedule: DynamicSemesterSchedule,
) -> dict[str, Any]:
    """Compare every source task and the global total; unplaced tasks count as shortages."""
    fragments_by_uid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fragment in schedule.fragments:
        fragments_by_uid[fragment["uid"]].append(fragment)

    task_rows: list[dict[str, Any]] = []
    for pattern in patterns:
        uid = pattern["uid"]
        session_hours = int(pattern.get("session_hours") or pattern.get("consecutive_slots") or 0)
        pattern_hours = (
            int(pattern.get("weekly_slot_count") or 0)
            * int(pattern.get("duration_weeks") or 0)
            * session_hours
        )
        required_hours = int(pattern.get("total_hours") or 0) or pattern_hours
        scheduled_hours = sum(len(fragment["week_mask"]) * session_hours
                              for fragment in fragments_by_uid.get(uid, []))
        delta = scheduled_hours - required_hours
        task_rows.append({
            "uid": uid,
            "course": pattern.get("course_name"),
            "required_hours": required_hours,
            "pattern_hours": pattern_hours,
            "scheduled_hours": scheduled_hours,
            "delta_hours": delta,
            "status": "exact" if delta == 0 else ("over" if delta > 0 else "under"),
            "placed": bool(fragments_by_uid.get(uid)),
        })

    required_total = sum(row["required_hours"] for row in task_rows)
    scheduled_total = sum(row["scheduled_hours"] for row in task_rows)
    mismatch = [row for row in task_rows if row["delta_hours"] != 0]
    return {
        "ok": len(task_rows) - len(mismatch),
        "mismatch_count": len(mismatch),
        "mismatch_preview": mismatch[:20],
        "tasks": task_rows,
        "required_total_hours": required_total,
        "scheduled_total_hours": scheduled_total,
        "delta_total_hours": scheduled_total - required_total,
        "over_task_count": sum(row["status"] == "over" for row in task_rows),
        "under_task_count": sum(row["status"] == "under" for row in task_rows),
        "over_hours": sum(max(0, row["delta_hours"]) for row in task_rows),
        "under_hours": sum(max(0, -row["delta_hours"]) for row in task_rows),
    }


# ── 输出 ─────────────────────────────────────────────────────────────

def _fragment_doc(
    frag: dict,
    index_by_uid: Counter,
    *,
    effective_duration: int | None = None,
    template_week_mask: list[int] | None = None,
) -> dict[str, Any]:
    pattern = frag["pattern"]
    if frag.get("session_index"):
        fragment_index = int(frag["session_index"])
    else:
        index_by_uid[frag["uid"]] += 1
        fragment_index = index_by_uid[frag["uid"]]
    fragment_id = str(frag.get("logical_fragment_id") or f"{frag['uid']}#frag{fragment_index}")
    # A logical semester fragment can be copied into several deduplicated week
    # templates. Each persisted fragment is editable only inside its own
    # template, so its duration must be local to that template copy. Keep the
    # full absolute week_mask below as audit evidence.
    task_week_mask = list(frag.get("week_mask") or pattern.get("week_mask") or [])
    duration_weeks = (
        effective_duration if effective_duration is not None
        else len(template_week_mask) if template_week_mask is not None
        else len(task_week_mask) or int(pattern.get("duration_weeks") or 0)
    )
    session_hours = int(pattern.get("session_hours") or 0)
    contribution_weeks = template_week_mask if template_week_mask is not None else task_week_mask
    segments = [{"day_of_week": frag["day"], "period_index": frag["start"] + off}
                for off in range(frag["consecutive"])]
    return {
        "fragment_id": fragment_id,
        "logical_fragment_id": fragment_id,
        "source_key": frag["uid"],
        "fragment_index": fragment_index,
        "course_name": pattern.get("course_name"),
        "course_code": pattern.get("course_code"),
        "teacher_name": pattern.get("teacher_name"),
        "primary_teacher_id": pattern.get("primary_teacher_id"),
        "assistant_teacher_id": pattern.get("assistant_teacher_id"),
        "student_count": int(pattern.get("student_count") or 0),
        "class_name": pattern.get("class_name"),
        "class_names": ",".join(frag["classes"]),
        "class_group_ids": _parse_list(pattern.get("class_group_ids")),
        "teaching_task_id": pattern.get("teaching_task_id"),
        "required_room_type": pattern.get("required_room_type"),
        "classroom_name": frag["room"],
        "resource_key": f"{frag['room']}|{frag['day']}|{frag['start']}",
        "day_of_week": frag["day"],
        "period_index": frag["start"],
        "slot_label": f"{frag['day']}|{frag['start']}",
        "segments": segments,
        "consecutive_slots": frag["consecutive"],
        "duration_weeks": duration_weeks,
        "session_hours": session_hours,
        "covered_hours": len(contribution_weeks) * session_hours,
        "week_mask": task_week_mask,
        "template_week_mask": list(contribution_weeks),
        "merged_from": pattern.get("merged_from"),
        "merged_source_keys": pattern.get("merged_source_keys") or [frag["uid"]],
        "candidate_rank": frag["candidate_rank"],
        "score": frag["score"],
    }


def _dynamic_template_docs(
    schedule: DynamicSemesterSchedule,
) -> list[dict[str, Any]]:
    """Deduplicate weeks with exactly the same active fragments and placement."""
    active_by_signature: dict[tuple, tuple[list[int], list[dict[str, Any]]]] = {}
    for week in schedule.week_numbers:
        active = [fragment for fragment in schedule.fragments if week in fragment["week_mask"]]
        active.sort(key=lambda fragment: (
            fragment["day"], fragment["start"], fragment["room"],
            fragment["uid"], fragment["candidate_rank"],
        ))
        signature = tuple(
            (fragment["uid"], fragment["day"], fragment["start"], fragment["room"])
            for fragment in active
        )
        if signature in active_by_signature:
            active_by_signature[signature][0].append(week)
        else:
            active_by_signature[signature] = ([week], active)

    groups = sorted(active_by_signature.values(), key=lambda pair: pair[0][0])
    index_by_uid: Counter = Counter()
    templates: list[dict[str, Any]] = []
    for index, (weeks, active) in enumerate(groups, start=1):
        docs = [
            _fragment_doc(fragment, index_by_uid, template_week_mask=weeks)
            for fragment in active
        ]
        templates.append({
            "template_id": f"dynamic_template_{index:02d}",
            "week_budget": len(weeks),
            "week_numbers": weeks,
            "fragments": docs,
        })
    return templates


def build_phase_cover(
    *,
    patterns_path: Path = DEFAULT_PATTERNS_PATH,
    model_dir: Path = SINGLE_PLACEMENT_MODEL_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    unresolved_path: Path = DEFAULT_UNRESOLVED_PATH,
    phase_weeks: tuple[int, ...] = DEFAULT_PHASE_WEEKS,
    top_k: int = 80,
    allowed_weekdays: frozenset[int] | None = None,
    allowed_periods: frozenset[int] | None = None,
    rooms_path: Path | None = None,
    use_model: bool = True,
) -> dict[str, Any]:
    allowed_days = sorted(allowed_weekdays or DEFAULT_ALLOWED_WEEKDAYS)
    periods = sorted(allowed_periods or DEFAULT_ALLOWED_PERIODS)
    if not periods or not set(periods) <= ALL_DAY_PERIODS:
        raise ValueError(f"allowed_periods must be a non-empty subset of 1..10: {periods}")
    total_weeks = sum(int(value) for value in phase_weeks)
    if total_weeks <= 0:
        raise ValueError("semester total weeks must be positive")
    week_cap = len(allowed_days) * len(periods)

    raw_patterns = _load_patterns(patterns_path)
    rooms_by_type, room_capacity_by_name, room_name_by_id = _load_rooms_by_type(rooms_path)
    patterns, merged_log = _merge_sections(raw_patterns, week_cap=week_cap, t1_weeks=min(phase_weeks))

    model_error: str | None = None
    if use_model:
        try:
            # Keep core functions importable for deterministic rule tests without LightGBM.
            from scheduler.placement_single_model import V35SinglePlacementModel

            model = V35SinglePlacementModel.load(model_dir)
            model_candidates = {r["uid"]: model.predict_topk(r, top_k=top_k) for r in patterns}
        except Exception as exc:  # 模型是软偏好；加载失败必须退回规则可行域。
            model_error = f"{type(exc).__name__}: {exc}"
            model_candidates = {r["uid"]: [] for r in patterns}
    else:
        model_candidates = {r["uid"]: [] for r in patterns}

    schedule = DynamicSemesterSchedule(total_weeks)
    unplaced, week_assignment = place_dynamic(
        patterns, schedule,
        rooms_by_type=rooms_by_type, model_candidates=model_candidates,
        allowed_days=allowed_days, allowed_periods=periods,
        room_capacity_by_name=room_capacity_by_name,
        room_name_by_id=room_name_by_id,
    )

    conservation = final_hour_audit(patterns, schedule)
    audits = {schedule.name: audit_dynamic_schedule(schedule)}
    capacity_mismatches = [
        {"uid": f["uid"], "room": f["room"],
         "student_count": int(f["pattern"].get("student_count") or 0),
         "capacity": int(room_capacity_by_name.get(f["room"]) or 0)}
        for f in schedule.fragments
        if room_capacity_by_name is not None
        and int(f["pattern"].get("student_count") or 0) > int(room_capacity_by_name.get(f["room"]) or 0)
    ]

    template_docs = _dynamic_template_docs(schedule)
    cover_doc = {
        "cover_id": "dynamic_cover_v2",
        "template_count": len(template_docs),
        "total_weeks": total_weeks,
        "phase_weeks": [total_weeks],
        "time_axis": {
            "period_minutes": 45,
            "all_periods": sorted(ALL_DAY_PERIODS),
            "morning_periods": sorted(MORNING_PERIODS),
            "afternoon_periods": sorted(AFTERNOON_PERIODS),
            "evening_periods": sorted(EVENING_PERIODS),
            "automatic_periods": periods,
            "reserved_manual_periods": sorted(ALL_DAY_PERIODS - set(periods)),
        },
        "templates": template_docs,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(cover_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    unresolved_rows = [dict(row, reason=row.get("reason") or "not_placed") for row in unplaced]
    with unresolved_path.open("w", encoding="utf-8") as handle:
        for row in unresolved_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")

    completed = len(patterns) - len(unresolved_rows)
    model_hits = sum(1 for f in schedule.fragments if f["candidate_rank"] > 0)
    total_frags = len(schedule.fragments)
    output_fragment_count = sum(len(template["fragments"]) for template in template_docs)
    report = {
        "cover_id": "dynamic_cover_v2",
        "phase_weeks": [total_weeks],
        "total_weeks": total_weeks,
        "week_cap": week_cap,
        "allowed_weekdays": allowed_days,
        "allowed_periods": periods,
        "all_day_periods": sorted(ALL_DAY_PERIODS),
        "reserved_manual_periods": sorted(ALL_DAY_PERIODS - set(periods)),
        "raw_task_count": len(raw_patterns),
        "merged_task_count": len(patterns),
        "merged_section_count": len(merged_log),
        "merged_preview": merged_log[:20],
        "initial_task_count": len(patterns),
        "completed_task_count": completed,
        "remaining_task_count": len(unresolved_rows),
        "template_count": len(template_docs),
        "fragment_count": total_frags,
        "output_fragment_count": output_fragment_count,
        "phase_counts": {"dynamic": completed},
        "week_span_counts": dict(Counter(len(mask) for mask in week_assignment.values())),
        "week_assignment_preview": {uid: list(mask) for uid, mask in list(week_assignment.items())[:20]},
        "packing_failures": 0,
        "placement_switched": 0,
        "placement_repairs": schedule.repair_count,
        "model_hit_fragments": model_hits,
        "model_hit_rate": round(model_hits / max(1, total_frags), 4),
        "model_fallback_error": model_error,
        "conflicts": audits,
        "conservation_ok": conservation["ok"],
        "conservation_unplaced_skipped": 0,
        "conservation_mismatch": conservation["mismatch_count"],
        "conservation_mismatch_preview": conservation["mismatch_preview"],
        "hour_audit_tasks": conservation["tasks"],
        "required_total_hours": conservation["required_total_hours"],
        "scheduled_total_hours": conservation["scheduled_total_hours"],
        "hour_delta_total": conservation["delta_total_hours"],
        "hour_over_task_count": conservation["over_task_count"],
        "hour_under_task_count": conservation["under_task_count"],
        "hour_over_total": conservation["over_hours"],
        "hour_under_total": conservation["under_hours"],
        "unresolved_reason_counts": dict(Counter(row.get("reason") or "not_placed" for row in unresolved_rows)),
        "capacity_mismatch_count": len(capacity_mismatches),
        "capacity_mismatch_preview": capacity_mismatches[:10],
        "validation_issue_count": (
            len(unresolved_rows)
            + conservation["mismatch_count"]
            + len(capacity_mismatches)
            + sum(sum(a.values()) for a in audits.values())
        ),
        "output_path": str(output_path),
        "unresolved_path": str(unresolved_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build phase-based V3.5 weekly template cover.")
    parser.add_argument("--patterns", default=str(DEFAULT_PATTERNS_PATH))
    parser.add_argument("--model-dir", default=str(SINGLE_PLACEMENT_MODEL_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--unresolved", default=str(DEFAULT_UNRESOLVED_PATH))
    parser.add_argument("--phase-weeks", default="8,10", help="每个周段的周数预算, 逗号分隔")
    parser.add_argument("--top-k", type=int, default=80)
    parser.add_argument("--rooms-json", default=None, help="Synthetic room resource JSON; skips database lookup")
    parser.add_argument("--no-model", action="store_true", help="Use deterministic exhaustive placement only")
    args = parser.parse_args()
    phase_weeks = tuple(int(x) for x in args.phase_weeks.split(",") if x.strip())

    report = build_phase_cover(
        patterns_path=Path(args.patterns),
        model_dir=Path(args.model_dir),
        output_path=Path(args.output),
        report_path=Path(args.report),
        unresolved_path=Path(args.unresolved),
        phase_weeks=phase_weeks,
        top_k=args.top_k,
        rooms_path=Path(args.rooms_json) if args.rooms_json else None,
        use_model=not args.no_model,
    )
    print(json.dumps({k: v for k, v in report.items()
                      if k not in {"merged_preview", "conservation_mismatch_preview"}},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
