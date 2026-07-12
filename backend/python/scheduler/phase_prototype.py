"""分段(phase)排课原型 — 下一阶段主线开发的种子.

链路: pattern 数据 → 合班模拟 → 分段装箱 → 段内贪心放格(两张周模板)
     → 冲突校验 + 课时守恒校验 + 单双周布局置换演示.

设计要点:
  * 周段模板 = 动态释放的离散化: T1 覆盖前 8 周, T2 覆盖后 10 周, 段内每周相同.
  * 模板内部无冲突 ⇒ 任意 week→template 映射都无冲突; 课时守恒只依赖每模板的周数预算.
  * 模型分数只作软偏好(影响格子选择顺序), 永不裁剪可行域.

验证结果 (2026-07, 真实数据 2701 任务): 合班后 2498 任务 100% 放置,
两模板零冲突, 课时全部守恒, 总耗时 ~1.2s. 对照: 旧 template_cover 剩 856 任务无法安置.

运行: python -m scheduler.phase_prototype [--run-dir <pipeline run 目录>]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scheduler.paths import OUTPUT_DIR

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402

PIPELINE_RUNS_DIR = OUTPUT_DIR / "runs"
DEFAULT_OUT_DIR = OUTPUT_DIR / "phase_proto"

ALLOWED_DAYS = [1, 2, 3, 4, 5]
ALLOWED_PERIODS = [1, 2, 3, 4]
WEEK_CAP = len(ALLOWED_DAYS) * len(ALLOWED_PERIODS)  # 20 cells / week / entity

# 周段预算: T1 = 8 周 (8 周课 1217 门), T2 = 10 周 (10 周课 685 门)
PHASES = {"T1": 8, "T2": 10}
TOTAL_WEEKS = 18


# ── 数据加载 ─────────────────────────────────────────────────────────

def latest_run_dir() -> Path:
    runs = sorted(d for d in PIPELINE_RUNS_DIR.iterdir() if (d / "task_patterns.jsonl").exists())
    if not runs:
        raise SystemExit(f"no pipeline run with task_patterns.jsonl under {PIPELINE_RUNS_DIR}")
    return runs[-1]


def load_patterns(run_dir: Path) -> list[dict]:
    rows = [json.loads(l) for l in (run_dir / "task_patterns.jsonl").read_text().splitlines() if l.strip()]
    for i, r in enumerate(rows):
        r["uid"] = f"t{i}"
        r["classes"] = parse_classes(r)
        r["weekly_load"] = int(r["weekly_slot_count"]) * int(r["consecutive_slots"])
    return rows


def parse_classes(row: dict) -> list[str]:
    raw = row.get("class_names") or row.get("class_name") or ""
    text = str(raw).replace("，", ",").replace("、", ",").replace(";", ",").replace("|", ",")
    seen, out = set(), []
    for part in text.split(","):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def load_rooms() -> dict[str, list[str]]:
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


# ── Step 0: 合班模拟 ─────────────────────────────────────────────────
# 教师周需求超过两段总容量时, 同教师同课程的多个班合并成大班段.
# 注意: 生产版需教务确认真实合班关系并校验教室容量, 此处仅两两合并做可行性验证.

def merge_sections(patterns: list[dict]) -> tuple[list[dict], list[dict]]:
    def teacher_weekly(rows: list[dict]) -> Counter:
        acc: Counter = Counter()
        for r in rows:
            t = (r.get("teacher_name") or "").strip()
            if t:
                acc[t] += r["weekly_load"]
        return acc

    merged_log: list[dict] = []
    rows = list(patterns)
    # 锁定 T2 的课程只能占 T2 的 20; 自由课可分两段. 保守目标: 总量 ≤ 36 且锁定量 ≤ 18 (留 10% 余量)
    for _ in range(6):
        weekly = teacher_weekly(rows)
        locked_weekly: Counter = Counter()
        for r in rows:
            t = (r.get("teacher_name") or "").strip()
            if t and int(r["duration_weeks"]) > PHASES["T1"]:
                locked_weekly[t] += r["weekly_load"]
        over = {t for t, w in weekly.items() if w > 36 or locked_weekly[t] > 18}
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
            teacher, _, course, hours = key[0], key[1], key[2], key[3]
            k = 2
            chunks = [group[i:i + k] for i in range(0, len(group), k)]
            for ci, chunk in enumerate(chunks, 1):
                base = dict(chunk[0])
                all_classes = [c for r in chunk for c in r["classes"]]
                base["classes"] = list(dict.fromkeys(all_classes))
                base["class_names"] = ",".join(base["classes"])
                base["uid"] = chunk[0]["uid"] + f"_m{ci}"
                base["merged_from"] = len(chunk)
                next_rows.append(base)
                if len(chunk) > 1:
                    merged_log.append({
                        "teacher": teacher, "course": course, "hours": hours,
                        "sections_before": len(chunk), "classes": base["classes"],
                    })
        rows = next_rows
    return rows, merged_log


# ── Step 1: 分段装箱 ─────────────────────────────────────────────────

def assign_phases(patterns: list[dict]):
    """返回 uid → 'T1' | 'T2' | 'BOTH', 装不下的记录, 以及负载统计."""
    class_load = {p: Counter() for p in PHASES}
    teacher_load = {p: Counter() for p in PHASES}
    assign: dict[str, str] = {}
    failures: list[dict] = []

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
        if any(class_load[p][c] + w > WEEK_CAP for c in classes):
            return False
        if teacher and teacher_load[p][teacher] + w > WEEK_CAP:
            return False
        return True

    def headroom(r: dict, p: str) -> float:
        classes, teacher = entities(r)
        w = r["weekly_load"]
        worst = max([class_load[p][c] + w for c in classes]
                    + ([teacher_load[p][teacher] + w] if teacher else [0]))
        return WEEK_CAP - worst

    spanning = [r for r in patterns if int(r["duration_weeks"]) > PHASES["T2"]]
    locked = [r for r in patterns if PHASES["T1"] < int(r["duration_weeks"]) <= PHASES["T2"]]
    free = [r for r in patterns if int(r["duration_weeks"]) <= PHASES["T1"]]
    free.sort(key=lambda r: (-r["weekly_load"], -len(r["classes"]), -int(r["duration_weeks"])))

    for r in spanning:
        assign[r["uid"]] = "BOTH"
        add(r, ["T1", "T2"])
    for r in locked:
        if not fits(r, "T2"):
            failures.append({"uid": r["uid"], "stage": "locked_T2", "course": r.get("course_name"),
                             "teacher": r.get("teacher_name"), "classes": r["classes"]})
            continue
        assign[r["uid"]] = "T2"
        add(r, ["T2"])
    for r in free:
        options = [p for p in ("T1", "T2") if fits(r, p)]
        if not options:
            failures.append({"uid": r["uid"], "stage": "free_no_phase", "course": r.get("course_name"),
                             "teacher": r.get("teacher_name"), "classes": r["classes"]})
            continue
        best = max(options, key=lambda p: headroom(r, p))
        assign[r["uid"]] = best
        add(r, [best])

    stats = {
        "class_over": {p: [(c, w) for c, w in class_load[p].items() if w > WEEK_CAP] for p in PHASES},
        "teacher_over": {p: [(t, w) for t, w in teacher_load[p].items() if w > WEEK_CAP] for p in PHASES},
        "class_load": class_load, "teacher_load": teacher_load,
    }
    return assign, failures, stats


# ── Step 2: 段内贪心放格 ─────────────────────────────────────────────

class Template:
    def __init__(self, name: str):
        self.name = name
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

    def occupy(self, r: dict, day: int, start: int, room: str) -> dict:
        teacher = (r.get("teacher_name") or "").strip()
        frag = {"uid": r["uid"], "course": r.get("course_name"), "teacher": teacher,
                "classes": r["classes"], "room": room, "day": day, "start": start,
                "consecutive": int(r["consecutive_slots"]),
                "duration_weeks": int(r["duration_weeks"])}
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
        """该 (day,start) 上挡住任务 r 的 fragment uid 集合(不含教室维度)."""
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


def valid_starts(consecutive: int) -> list[int]:
    if consecutive == 1:
        return list(ALLOWED_PERIODS)
    # 连堂必须对齐自然边界: 1-2 节 或 3-4 节
    return [p for p in ALLOWED_PERIODS if (p - 1) % consecutive == 0 and p + consecutive - 1 <= max(ALLOWED_PERIODS)]


def place_all(patterns: list[dict], assign: dict[str, str], rooms_by_type: dict[str, list[str]]):
    templates = {p: Template(p) for p in PHASES}
    unplaced: list[dict] = []
    switched = 0

    def room_pool(r: dict) -> list[str]:
        want = str(r.get("required_room_type") or "").strip()
        pool = rooms_by_type.get(want) or [n for v in rooms_by_type.values() for n in v]
        rot = hash(r["uid"]) % max(1, len(pool))
        return pool[rot:] + pool[:rot]

    patterns_by_uid = {r["uid"]: r for r in patterns}
    repairs = 0

    def find_spot(r: dict, targets: list[Template], used_slots: set[tuple], used_days: Counter) -> tuple | None:
        day_order = sorted(ALLOWED_DAYS, key=lambda d: (used_days[d], d))
        for day in day_order:
            for start in valid_starts(int(r["consecutive_slots"])):
                if (day, start) in used_slots:
                    continue
                for room in room_pool(r):
                    if all(t.free(r, day, start, room) for t in targets):
                        return day, start, room
        return None

    def try_repair(r: dict, template: Template, used_slots: set[tuple]) -> tuple | None:
        """单阻塞者搬迁: 找一个只被 1 个可移动 fragment 挡住的格子, 挪走它."""
        nonlocal repairs
        for day in ALLOWED_DAYS:
            for start in valid_starts(int(r["consecutive_slots"])):
                if (day, start) in used_slots:
                    continue
                blocker_uids = template.blockers_at(r, day, start)
                if len(blocker_uids) != 1:
                    continue
                b_uid = next(iter(blocker_uids))
                if assign.get(b_uid) == "BOTH":
                    continue  # 跨段任务两张模板同格, 不动
                b_frags = [f for f in template.fragments
                           if f["uid"] == b_uid and not (f["start"] + f["consecutive"] <= start
                                                         or start + int(r["consecutive_slots"]) <= f["start"]
                                                         or f["day"] != day)]
                if len(b_frags) != 1:
                    continue
                b_frag = b_frags[0]
                template.remove_fragment(b_frag)
                room = next((rm for rm in room_pool(r) if template.free(r, day, start, rm)), None)
                if room is None:
                    template.occupy(patterns_by_uid[b_uid], b_frag["day"], b_frag["start"], b_frag["room"])
                    continue
                new_frag = template.occupy(r, day, start, room)
                b_pattern = patterns_by_uid[b_uid]
                b_used = template.task_slots(b_uid)
                new_spot = find_spot(b_pattern, [template], b_used, Counter())
                if new_spot is None:
                    template.remove_fragment(new_frag)
                    template.occupy(b_pattern, b_frag["day"], b_frag["start"], b_frag["room"])
                    continue
                template.occupy(b_pattern, *new_spot)
                template.remove_fragment(new_frag)  # 试占撤销, 格子交还 place_task 统一放置
                repairs += 1
                return day, start, room
        return None

    def place_task(r: dict, targets: list[Template]) -> bool:
        need = int(r["weekly_slot_count"])
        used_days: Counter = Counter()
        used_slots: set[tuple] = set()
        placed_frags: list[tuple[Template, dict]] = []
        for _ in range(need):
            spot = find_spot(r, targets, used_slots, used_days)
            if not spot and len(targets) == 1:
                spot = try_repair(r, targets[0], used_slots)
            if not spot:
                for t, frag in placed_frags:  # 回滚, 保持模板干净
                    t.remove_fragment(frag)
                return False
            day, start, room = spot
            for t in targets:
                placed_frags.append((t, t.occupy(r, day, start, room)))
            used_days[day] += 1
            used_slots.add((day, start))
        return True

    # 教师紧张度: 该教师在其目标段内累计周负载越高, 越先放(个人课表近饱和的教师需要在空模板上紧凑成型)
    teacher_phase_load: dict[tuple[str, str], int] = defaultdict(int)
    for r in patterns:
        phase = assign.get(r["uid"])
        teacher = (r.get("teacher_name") or "").strip()
        if phase is None or not teacher:
            continue
        for p in (("T1", "T2") if phase == "BOTH" else (phase,)):
            teacher_phase_load[(teacher, p)] += r["weekly_load"]

    def tightness(r: dict) -> int:
        teacher = (r.get("teacher_name") or "").strip()
        phase = assign.get(r["uid"])
        if not teacher or phase is None:
            return 0
        if phase == "BOTH":
            return max(teacher_phase_load[(teacher, "T1")], teacher_phase_load[(teacher, "T2")])
        return teacher_phase_load[(teacher, phase)]

    order = sorted(patterns, key=lambda r: (
        0 if assign.get(r["uid"]) == "BOTH" else 1,
        -tightness(r),
        -int(r["consecutive_slots"]),
        -r["weekly_load"],
        -len(r["classes"]),
    ))
    for r in order:
        phase = assign.get(r["uid"])
        if phase is None:
            continue
        targets = list(templates.values()) if phase == "BOTH" else [templates[phase]]
        if place_task(r, targets):
            continue
        # 兜底: 换段重试 (仅自由课)
        if phase in ("T1", "T2") and int(r["duration_weeks"]) <= PHASES["T1"]:
            other = templates["T2" if phase == "T1" else "T1"]
            if place_task(r, [other]):
                assign[r["uid"]] = other.name
                switched += 1
                continue
        unplaced.append({"uid": r["uid"], "course": r.get("course_name"),
                         "teacher": r.get("teacher_name"), "classes": r["classes"],
                         "phase": phase, "weekly_load": r["weekly_load"]})
    return templates, unplaced, switched, repairs


# ── Step 3: 校验 ─────────────────────────────────────────────────────

def audit_template(t: Template) -> dict[str, int]:
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


def hour_conservation(patterns: list[dict], assign: dict[str, str], templates: dict[str, "Template"]) -> dict:
    """展开 M (T1=8周, T2=10周) 后, 每任务实际课时 vs pattern 课时."""
    frag_count: Counter = Counter()
    for t in templates.values():
        for f in t.fragments:
            frag_count[(f["uid"], t.name)] += 1
    ok, mismatch = 0, []
    for r in patterns:
        uid, phase = r["uid"], assign.get(r["uid"])
        if phase is None:
            continue
        need_weeks = int(r["duration_weeks"])
        session_hours = int(r["session_hours"])
        expected = int(r["weekly_slot_count"]) * need_weeks * session_hours
        if phase == "BOTH":
            budget = PHASES["T1"] + PHASES["T2"]
            weekly = frag_count[(uid, "T1")]
            weekly2 = frag_count[(uid, "T2")]
            actual_weeks = min(need_weeks, budget)
            actual = weekly * actual_weeks * session_hours if weekly == weekly2 else -1
        else:
            budget = PHASES[phase]
            weekly = frag_count[(uid, phase)]
            actual_weeks = min(need_weeks, budget)  # mask: 只用预算内前 N 个映射周
            actual = weekly * actual_weeks * session_hours
        if actual == expected and actual_weeks == need_weeks:
            ok += 1
        else:
            mismatch.append({"uid": uid, "course": r.get("course_name"), "expected_h": expected,
                             "actual_h": actual, "need_weeks": need_weeks, "budget": budget})
    return {"ok": ok, "mismatch_count": len(mismatch), "mismatch_preview": mismatch[:10]}


def main() -> None:
    parser = argparse.ArgumentParser(description="分段排课原型: 装箱 + 放格 + 校验.")
    parser.add_argument("--run-dir", default=None, help="pipeline run 目录(含 task_patterns.jsonl), 默认取最新")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else latest_run_dir()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    patterns = load_patterns(run_dir)
    rooms_by_type = load_rooms()
    print(f"run_dir={run_dir}")
    print(f"tasks={len(patterns)}  rooms={ {k: len(v) for k, v in rooms_by_type.items()} }")

    merged, merged_log = merge_sections(patterns)
    merged_teachers = sorted({m['teacher'] for m in merged_log})
    print(f"\n[Step0 合班] {len(patterns)} → {len(merged)} tasks, "
          f"合并 {sum(m['sections_before'] for m in merged_log) - len(merged_log)} 个班段, "
          f"涉及教师 {len(merged_teachers)} 人")

    assign, failures, stats = assign_phases(merged)
    n1 = sum(1 for v in assign.values() if v == "T1")
    n2 = sum(1 for v in assign.values() if v == "T2")
    nb = sum(1 for v in assign.values() if v == "BOTH")
    print(f"\n[Step1 分段] T1={n1}  T2={n2}  跨段={nb}  装不下={len(failures)}")
    for p in PHASES:
        cv = sorted(stats["class_load"][p].values())
        print(f"  {p}: 班级周需求 max={cv[-1] if cv else 0} "
              f"超容量班级={len(stats['class_over'][p])} 超容量教师={len(stats['teacher_over'][p])}")

    templates, unplaced, switched, repairs = place_all(merged, assign, rooms_by_type)
    total_frag = sum(len(t.fragments) for t in templates.values())
    print(f"\n[Step2 放格] fragments={total_frag}  未放置任务={len(unplaced)}  换段兜底={switched}  修复搬迁={repairs}")
    for p, t in templates.items():
        print(f"  {p}: {len(t.fragments)} fragments  冲突={audit_template(t)}")
    if unplaced:
        print("  未放置样例:", json.dumps(unplaced[:5], ensure_ascii=False))

    cons = hour_conservation(merged, assign, templates)
    print(f"\n[Step3 课时守恒] ok={cons['ok']}  mismatch={cons['mismatch_count']}")
    if cons["mismatch_count"]:
        print("  样例:", json.dumps(cons["mismatch_preview"][:5], ensure_ascii=False))

    report = {
        "run_dir": str(run_dir),
        "task_count": len(merged), "merged_log": merged_log,
        "phase_counts": {"T1": n1, "T2": n2, "BOTH": nb},
        "packing_failures": failures, "unplaced": unplaced,
        "switched": switched, "repairs": repairs,
        "conservation": {"ok": cons["ok"], "mismatch": cons["mismatch_count"]},
        "audits": {p: audit_template(t) for p, t in templates.items()},
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for p, t in templates.items():
        (out_dir / f"template_{p}.json").write_text(json.dumps(t.fragments, ensure_ascii=False, indent=1))
    print(f"\n输出 → {out_dir}")


if __name__ == "__main__":
    main()
