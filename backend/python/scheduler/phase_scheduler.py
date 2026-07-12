"""分段(phase)周模板排课引擎 — V3.5 主力排课器.

链路: task patterns → 合班合并 → 分段装箱 → 段内贪心放格(模型软偏好 + 全枚举兜底
     + 单阻塞者搬迁修复) → 两张周段模板 → 冲突/课时守恒自检.

设计要点:
  * 周段模板是"动态释放"的离散化: T1 覆盖前 8 周, T2 覆盖后 10 周, 段内每周相同.
  * 模板内部无冲突 ⇒ 任意 week→template 映射都无冲突; 课时守恒只依赖每模板周数预算.
  * 模型分数只影响格子选择顺序(软偏好), 永不裁剪可行域.
  * fragment 携带 duration_weeks: 展开第 w 周时, 仅当 w 在其模板映射周中的
    出现序号 ≤ duration_weeks 才生效(相对掩码语义, 换周后依然成立).

产出 cover 文档与 export_template_cover_db_draft 兼容:
  {cover_id, phase_weeks, templates: [{template_id, week_budget, fragments: [...]}]}
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scheduler.paths import OUTPUT_DIR
from scheduler.pattern_builder import DEFAULT_OUTPUT_PATH as DEFAULT_PATTERNS_PATH
from scheduler.placement_single_model import OUTPUT_DIR as SINGLE_MODEL_DIR
from scheduler.placement_single_model import V35SinglePlacementModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402

DEFAULT_OUTPUT_PATH = OUTPUT_DIR / "phase_cover.json"
DEFAULT_REPORT_PATH = OUTPUT_DIR / "phase_cover_report.json"
DEFAULT_UNRESOLVED_PATH = OUTPUT_DIR / "phase_cover_unresolved.jsonl"

DEFAULT_ALLOWED_WEEKDAYS = frozenset(range(1, 6))
DEFAULT_ALLOWED_PERIODS = frozenset(range(1, 6))
DEFAULT_PHASE_WEEKS = (8, 10)


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


def _load_patterns(path: Path) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        r["uid"] = str(r["source_key"])
        r["classes"] = _parse_classes(r)
        r["weekly_load"] = int(r["weekly_slot_count"]) * int(r["consecutive_slots"])
    return rows


def _load_rooms_by_type() -> dict[str, list[str]]:
    conn = connect(load_db_config())
    by_type: dict[str, list[str]] = defaultdict(list)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, classroom_type FROM classroom")
            for r in cur.fetchall():
                by_type[str(r["classroom_type"]).strip()].append(str(r["name"]))
    finally:
        conn.close()
    for names in by_type.values():
        names.sort()
    return dict(by_type)


# ── Step 0: 合班合并 ─────────────────────────────────────────────────
# 教师周需求超过段容量时, 同教师同课程的多个班合并为大班段.
# 注意: 此处为自动合并; 生产使用前应由教务确认真实合班关系并校验大教室容量.

def _merge_sections(patterns: list[dict], *, week_cap: int, t1_weeks: int) -> tuple[list[dict], list[dict]]:
    free_cap = int(2 * week_cap * 0.9)   # 自由课可分两段, 留 10% 余量
    locked_cap = int(week_cap * 0.9)     # 长课锁定单段

    def loads(rows: list[dict]) -> tuple[Counter, Counter]:
        total: Counter = Counter()
        locked: Counter = Counter()
        for r in rows:
            t = (r.get("teacher_name") or "").strip()
            if not t:
                continue
            total[t] += r["weekly_load"]
            if int(r["duration_weeks"]) > t1_weeks:
                locked[t] += r["weekly_load"]
        return total, locked

    merged_log: list[dict] = []
    rows = list(patterns)
    for _ in range(6):
        total, locked = loads(rows)
        over = {t for t, w in total.items() if w > free_cap or locked[t] > locked_cap}
        if not over:
            break
        next_rows: list[dict] = []
        by_group: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            t = (r.get("teacher_name") or "").strip()
            if t in over:
                key = (t, r.get("course_code"), r.get("course_name"), r.get("total_hours"),
                       r.get("course_type"), r.get("required_room_type"))
                by_group[key].append(r)
            else:
                next_rows.append(r)
        for key, group in by_group.items():
            chunks = [group[i:i + 2] for i in range(0, len(group), 2)]
            for chunk in chunks:
                base = dict(chunk[0])
                all_classes = [c for r in chunk for c in r["classes"]]
                base["classes"] = list(dict.fromkeys(all_classes))
                base["class_names"] = ",".join(base["classes"])
                base["merged_from"] = sum(int(r.get("merged_from") or 1) for r in chunk)
                base["merged_source_keys"] = [
                    k for r in chunk for k in (r.get("merged_source_keys") or [r["uid"]])
                ]
                next_rows.append(base)
                if len(chunk) > 1:
                    merged_log.append({
                        "teacher": key[0], "course": key[2], "hours": key[3],
                        "sections_before": len(chunk), "classes": base["classes"],
                    })
        rows = next_rows
    return rows, merged_log


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
        if not fits(r, large):
            failures.append({"uid": r["uid"], "stage": "locked_phase_full",
                             "course": r.get("course_name"), "teacher": r.get("teacher_name"),
                             "classes": r["classes"]})
            continue
        assign[r["uid"]] = large
        add(r, [large])
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
        self.fragments: list[dict] = []

    def free(self, r: dict, day: int, start: int, room: str) -> bool:
        teacher = (r.get("teacher_name") or "").strip()
        for off in range(int(r["consecutive_slots"])):
            key = (day, start + off)
            if teacher and (teacher, *key) in self.teacher:
                return False
            if any((c, *key) in self.cls for c in r["classes"]):
                return False
            if (room, *key) in self.room:
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
):
    unplaced: list[dict] = []
    switched = 0
    repairs = 0
    patterns_by_uid = {r["uid"]: r for r in patterns}
    room_names = {name for names in rooms_by_type.values() for name in names}

    def room_pool(r: dict) -> list[str]:
        want = str(r.get("required_room_type") or "").strip()
        pool = rooms_by_type.get(want) or [n for v in rooms_by_type.values() for n in v]
        rot = hash(r["uid"]) % max(1, len(pool))
        return pool[rot:] + pool[:rot]

    def find_spot(r: dict, targets: list[PhaseTemplate], used_slots: set[tuple], used_days: Counter):
        starts = _valid_starts(int(r["consecutive_slots"]), allowed_periods)
        # 1) 模型候选优先 (软偏好): 只在候选无冲突时采纳, 不构成可行域边界
        for rank, cand in enumerate(model_candidates.get(r["uid"], []), start=1):
            day, start, room = cand.day_of_week, cand.period_index, cand.classroom_name
            if day not in allowed_days or start not in starts or (day, start) in used_slots:
                continue
            if room not in room_names:
                continue
            if all(t.free(r, day, start, room) for t in targets):
                return day, start, room, rank, float(cand.score)
        # 2) 全枚举兜底: 天数分散优先
        day_order = sorted(allowed_days, key=lambda d: (used_days[d], d))
        for day in day_order:
            for start in starts:
                if (day, start) in used_slots:
                    continue
                for room in room_pool(r):
                    if all(t.free(r, day, start, room) for t in targets):
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
                room = next((rm for rm in room_pool(r) if template.free(r, day, start, rm)), None)
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
    ok, mismatch = 0, []
    total_budget = sum(t.week_budget for t in templates.values())
    for r in patterns:
        uid, phase = r["uid"], assign.get(r["uid"])
        if phase is None:
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
    return {"ok": ok, "mismatch_count": len(mismatch), "mismatch_preview": mismatch[:10]}


# ── 输出 ─────────────────────────────────────────────────────────────

def _fragment_doc(frag: dict, index_by_uid: Counter, *, effective_duration: int | None = None) -> dict[str, Any]:
    pattern = frag["pattern"]
    index_by_uid[frag["uid"]] += 1
    fragment_index = index_by_uid[frag["uid"]]
    # 跨段课在每张模板里只承担本段的周数份额, 否则两段各自过滤会导致超上
    duration_weeks = (
        effective_duration if effective_duration is not None
        else int(pattern.get("duration_weeks") or 0)
    )
    session_hours = int(pattern.get("session_hours") or 0)
    segments = [{"day_of_week": frag["day"], "period_index": frag["start"] + off}
                for off in range(frag["consecutive"])]
    return {
        "fragment_id": f"{frag['uid']}#frag{fragment_index}",
        "source_key": frag["uid"],
        "fragment_index": fragment_index,
        "course_name": pattern.get("course_name"),
        "course_code": pattern.get("course_code"),
        "teacher_name": pattern.get("teacher_name"),
        "class_name": pattern.get("class_name"),
        "class_names": ",".join(frag["classes"]),
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
        "covered_hours": duration_weeks * session_hours,
        "week_mask": pattern.get("week_mask") or [],
        "merged_from": pattern.get("merged_from"),
        "candidate_rank": frag["candidate_rank"],
        "score": frag["score"],
    }


def build_phase_cover(
    *,
    patterns_path: Path = DEFAULT_PATTERNS_PATH,
    model_dir: Path = SINGLE_MODEL_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    unresolved_path: Path = DEFAULT_UNRESOLVED_PATH,
    phase_weeks: tuple[int, ...] = DEFAULT_PHASE_WEEKS,
    top_k: int = 80,
    allowed_weekdays: frozenset[int] | None = None,
    allowed_periods: frozenset[int] | None = None,
) -> dict[str, Any]:
    allowed_days = sorted(allowed_weekdays or DEFAULT_ALLOWED_WEEKDAYS)
    periods = sorted(allowed_periods or DEFAULT_ALLOWED_PERIODS)
    week_cap = len(allowed_days) * len(periods)
    phase_names = [f"phase_t{i}" for i in range(1, len(phase_weeks) + 1)]
    phase_budget = dict(zip(phase_names, phase_weeks))

    raw_patterns = _load_patterns(patterns_path)
    rooms_by_type = _load_rooms_by_type()
    patterns, merged_log = _merge_sections(raw_patterns, week_cap=week_cap, t1_weeks=min(phase_weeks))

    assign, pack_failures, pack_stats = assign_phases(
        patterns, phase_names=phase_names, phase_budget=phase_budget, week_cap=week_cap)

    model = V35SinglePlacementModel.load(model_dir)
    model_candidates = {r["uid"]: model.predict_topk(r, top_k=top_k) for r in patterns}

    templates = {name: PhaseTemplate(name, phase_budget[name]) for name in phase_names}
    unplaced, switched, repairs = place_all(
        patterns, assign, templates,
        rooms_by_type=rooms_by_type, model_candidates=model_candidates,
        allowed_days=allowed_days, allowed_periods=periods)

    conservation = hour_conservation(patterns, assign, templates)
    audits = {name: audit_template(t) for name, t in templates.items()}

    index_by_uid: Counter = Counter()
    template_docs = []
    cumulative_budget = 0
    for name in phase_names:
        t = templates[name]
        docs = []
        for f in t.fragments:
            full_duration = int(f["pattern"].get("duration_weeks") or 0)
            effective = (
                max(0, min(t.week_budget, full_duration - cumulative_budget))
                if assign.get(f["uid"]) == "BOTH"
                else full_duration
            )
            docs.append(_fragment_doc(f, index_by_uid, effective_duration=effective))
        template_docs.append({
            "template_id": name,
            "week_budget": t.week_budget,
            "fragments": sorted(
                docs,
                key=lambda item: (item["day_of_week"], item["period_index"],
                                  item["classroom_name"], item["source_key"]),
            ),
        })
        cumulative_budget += t.week_budget
    cover_doc = {
        "cover_id": "phase_cover_v1",
        "template_count": len(template_docs),
        "phase_weeks": list(phase_weeks),
        "templates": template_docs,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(cover_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    unresolved_rows = [dict(row, reason=row.get("reason") or "not_placed") for row in pack_failures + unplaced]
    with unresolved_path.open("w", encoding="utf-8") as handle:
        for row in unresolved_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")

    completed = len(patterns) - len(unresolved_rows)
    model_hits = sum(1 for t in templates.values() for f in t.fragments if f["candidate_rank"] > 0)
    total_frags = sum(len(t.fragments) for t in templates.values())
    report = {
        "cover_id": "phase_cover_v1",
        "phase_weeks": list(phase_weeks),
        "week_cap": week_cap,
        "allowed_weekdays": allowed_days,
        "allowed_periods": periods,
        "raw_task_count": len(raw_patterns),
        "merged_task_count": len(patterns),
        "merged_section_count": len(merged_log),
        "merged_preview": merged_log[:20],
        "initial_task_count": len(patterns),
        "completed_task_count": completed,
        "remaining_task_count": len(unresolved_rows),
        "template_count": len(template_docs),
        "fragment_count": total_frags,
        "phase_counts": dict(Counter(assign.values())),
        "packing_failures": len(pack_failures),
        "class_load_max": pack_stats["class_load_max"],
        "placement_switched": switched,
        "placement_repairs": repairs,
        "model_hit_fragments": model_hits,
        "model_hit_rate": round(model_hits / max(1, total_frags), 4),
        "conflicts": audits,
        "conservation_ok": conservation["ok"],
        "conservation_mismatch": conservation["mismatch_count"],
        "conservation_mismatch_preview": conservation["mismatch_preview"],
        "validation_issue_count": (
            len(unresolved_rows)
            + conservation["mismatch_count"]
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
    parser.add_argument("--model-dir", default=str(SINGLE_MODEL_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--unresolved", default=str(DEFAULT_UNRESOLVED_PATH))
    parser.add_argument("--phase-weeks", default="8,10", help="每个周段的周数预算, 逗号分隔")
    parser.add_argument("--top-k", type=int, default=80)
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
    )
    print(json.dumps({k: v for k, v in report.items()
                      if k not in {"merged_preview", "conservation_mismatch_preview"}},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
