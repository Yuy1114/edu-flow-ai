"""
分析测试集 (2025-2026 第2学期) 课表导入产物，使用多信号加权评分找出特殊课程。

输出：
  stdout: 评分分析和汇总
  backend/models/v3.5/training/suspicious_courses.jsonl: 评分 ≥ threshold 的可疑课程

评分信号与权重：
  虚拟教师 / XN教室 / 虚拟教室 → 一票否决级 (100/80)
  超高课时 ≥120 / 高课时 80-119 / 偏高 60-79
  名称关键词：毕业、实训、实习、虚拟、课程设计
  高学分 ≥8
  代码前缀：毕、虚、XN
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PARSED_DIR = Path(__file__).resolve().parents[1] / "data" / "parsed" / "schedule_imports"
SUSPICIOUS_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "analysis" / "suspicious_courses.jsonl"

# 权重配置
WEIGHTS = {
    "virtual_teacher": 100,      # 虚拟教师
    "xn_classroom": 80,          # XN 开头教室
    "virtual_classroom": 80,     # 名称含"虚拟"的教室
    "hours_ge_120": 50,          # 课时 ≥ 120
    "hours_80_119": 30,          # 课时 80-119
    "hours_60_79": 10,           # 课时 60-79
    "name_毕业": 25,
    "name_实训": 20,
    "name_实习": 20,
    "name_虚拟": 20,
    "name_课程设计": 10,
    "name_军训": 30,
    "name_体育": 20,             # 含体育关键词
    "name_创新创业": 20,
    "name_就业指导": 20,
    "code_prefix_毕": 10,
    "code_prefix_虚": 10,
    "code_prefix_XN": 10,
    "credits_ge_8": 15,
    "credits_ge_6": 5,
}

# 筛选阈值：总分 >= 此值写入可疑 JSONL
SUSPICIOUS_THRESHOLD = 20


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def score_course(code: str, name: str, hours: float, credits: float,
                 teachers: list[str], classrooms: list[str],
                 schedulable: str) -> dict[str, Any]:
    """对一门课程进行多信号评分，返回评分详情。"""
    signals: dict[str, int] = {}
    total = 0

    # ── 教室信号 ──
    for room in classrooms:
        r = room.strip().lower()
        if r.startswith("xn"):
            signals["xn_classroom"] = max(signals.get("xn_classroom", 0), WEIGHTS["xn_classroom"])
        if "虚拟" in room:
            signals["virtual_classroom"] = max(signals.get("virtual_classroom", 0), WEIGHTS["virtual_classroom"])

    # ── 教师信号 ──
    for t in teachers:
        if "虚拟" in t:
            signals["virtual_teacher"] = WEIGHTS["virtual_teacher"]

    # ── 课时信号 ──
    if hours >= 120:
        signals["hours_ge_120"] = WEIGHTS["hours_ge_120"]
    elif hours >= 80:
        signals["hours_80_119"] = WEIGHTS["hours_80_119"]
    elif hours >= 60:
        signals["hours_60_79"] = WEIGHTS["hours_60_79"]

    # ── 课程名称信号 ──
    name_signals = {
        "毕业": "name_毕业", "毕业论文": "name_毕业", "毕业设计": "name_毕业",
        "实训": "name_实训", "实习": "name_实习",
        "虚拟": "name_虚拟",
        "课程设计": "name_课程设计",
        "军训": "name_军训",
        "创新创业": "name_创新创业",
        "就业指导": "name_就业指导",
    }
    for keyword, signal_key in name_signals.items():
        if keyword in name:
            signals[signal_key] = max(signals.get(signal_key, 0), WEIGHTS[signal_key])

    # ── 名称含体育关键词 ──
    pe_keywords = {"体育", "田径", "球类", "体操", "武术", "健美", "瑜伽", "跆拳道", "游泳", "太极"}
    if any(kw in name for kw in pe_keywords):
        signals["name_体育"] = WEIGHTS["name_体育"]

    # ── 课程代码前缀 ──
    if code.startswith("毕"):
        signals["code_prefix_毕"] = WEIGHTS["code_prefix_毕"]
    if code.startswith("虚"):
        signals["code_prefix_虚"] = WEIGHTS["code_prefix_虚"]
    if code.upper().startswith("XN"):
        signals["code_prefix_XN"] = WEIGHTS["code_prefix_XN"]

    # ── 学分信号 ──
    if credits >= 8:
        signals["credits_ge_8"] = WEIGHTS["credits_ge_8"]
    elif credits >= 6:
        signals["credits_ge_5"] = WEIGHTS["credits_ge_6"]

    for v in signals.values():
        total += v

    return {
        "code": code,
        "name": name,
        "hours": hours,
        "credits": credits,
        "score": total,
        "signals": signals,
        "teachers": teachers,
        "classrooms": classrooms,
        "schedulable": schedulable,
    }


def main() -> None:
    batch_dirs = sorted([d for d in PARSED_DIR.iterdir() if d.is_dir()])

    # 按 code 聚合课程的班级数据
    course_data: dict[str, dict[str, Any]] = {}
    # code -> [(class_name, teacher, classroom)]
    course_instances: dict[str, list[tuple[str, str, str]]] = defaultdict(list)

    for batch_dir in batch_dirs:
        class_name = batch_dir.name
        courses = _read_csv(batch_dir / "courses.csv")
        teachers = _read_csv(batch_dir / "teachers.csv")
        classrooms_csv = _read_csv(batch_dir / "classrooms.csv")
        teaching_tasks = _read_csv(batch_dir / "teaching_tasks.csv")

        for course in courses:
            code = course.get("course_code", "").strip()
            if not code:
                continue

            try:
                hours = float(course.get("required_hours", 0) or 0)
            except (ValueError, TypeError):
                hours = 0
            try:
                credits = float(course.get("credits", 0) or 0)
            except (ValueError, TypeError):
                credits = 0

            name = course.get("course_name", "").strip()
            schedulable = course.get("schedulable", "").strip()
            exclude_reason = course.get("exclude_reason", "").strip()

            if code not in course_data:
                course_data[code] = {
                    "code": code,
                    "name": name,
                    "hours_list": [],
                    "credits": credits,
                    "all_teachers": set(),
                    "all_classrooms": set(),
                    "class_count": 0,
                    "schedulable": schedulable,
                    "exclude_reason": exclude_reason,
                    "raw_text": course.get("raw_text", "").strip(),
                }

            cd = course_data[code]
            cd["hours_list"].append(hours)
            if not cd.get("credits"):
                cd["credits"] = credits
            cd["class_count"] += 1

        # 收集教师和教室信息
        for tt in teaching_tasks:
            code = tt.get("course_code", "").strip()
            teacher = tt.get("teacher_name", "").strip()
            if code in course_data and teacher:
                course_data[code]["all_teachers"].add(teacher)
                course_instances[code].append((class_name, teacher, ""))

        for cr in classrooms_csv:
            room = cr.get("classroom_name", "").strip()
            # 从 raw_source 尝试关联课程
            raw = cr.get("raw_source", "")

        # 从 occurrences 获取教室使用
        occurrences = _read_csv(batch_dir / "timetable_occurrences.csv")
        for occ in occurrences:
            code = occ.get("course_code", "").strip()
            room = occ.get("classroom_name", "").strip()
            if code in course_data and room:
                course_data[code]["all_classrooms"].add(room)

    # ── 评分 ──
    scored: list[dict[str, Any]] = []
    for code, cd in course_data.items():
        max_hours = max(cd["hours_list"]) if cd["hours_list"] else 0
        result = score_course(
            code=code,
            name=cd["name"],
            hours=max_hours,
            credits=cd["credits"],
            teachers=list(cd["all_teachers"]),
            classrooms=list(cd["all_classrooms"]),
            schedulable=cd["schedulable"],
        )
        result["class_count"] = cd["class_count"]
        result["raw_text"] = cd["raw_text"]
        result["exclude_reason"] = cd["exclude_reason"]
        scored.append(result)

    # 按分数降序
    scored.sort(key=lambda x: x["score"], reverse=True)

    # ── 输出统计 ──
    print(f"共分析 {len(batch_dirs)} 个班级, {len(course_data)} 门课程\n", flush=True)

    # 分数分布
    buckets = Counter()
    for s in scored:
        sc = s["score"]
        if sc >= 100:
            buckets["100+ (确定不排课)"] += 1
        elif sc >= 40:
            buckets["40-99 (很可能不排课)"] += 1
        elif sc >= 20:
            buckets["20-39 (可能不排课)"] += 1
        elif sc >= 10:
            buckets["10-19 (边缘)"] += 1
        else:
            buckets["0-9 (正常)"] += 1

    print("=== 评分分布 ===", flush=True)
    for bucket in ["100+ (确定不排课)", "40-99 (很可能不排课)", "20-39 (可能不排课)", "10-19 (边缘)", "0-9 (正常)"]:
        if buckets[bucket]:
            print(f"  {bucket}: {buckets[bucket]} 门", flush=True)

    # ── 输出可疑课程详情 ──
    suspicious = [s for s in scored if s["score"] >= SUSPICIOUS_THRESHOLD]
    borderline = [s for s in scored if 10 <= s["score"] < SUSPICIOUS_THRESHOLD]

    print(f"\n=== 可疑课程 (score >= {SUSPICIOUS_THRESHOLD}) ===", flush=True)
    print(f"共 {len(suspicious)} 门\n", flush=True)

    for s in suspicious:
        signals_str = ", ".join(f"{k}({v})" for k, v in sorted(s["signals"].items()))
        teachers_str = ", ".join(s["teachers"][:3])
        rooms_str = ", ".join(s["classrooms"][:3])
        print(f"{s['code']:20s} | {s['name']:35s} | score={s['score']:3d} | "
              f"课时={s['hours']:.0f} | 学分={s['credits']:.1f} | "
              f"班级数={s['class_count']:3d}", flush=True)
        print(f"  📶 信号: {signals_str}", flush=True)
        if teachers_str:
            print(f"  👤 教师: {teachers_str}", flush=True)
        if rooms_str:
            print(f"  🏫 教室: {rooms_str}", flush=True)
        if s["raw_text"]:
            raw = s["raw_text"][:100]
            print(f"  📝 原文: {raw}", flush=True)
        print("", flush=True)

    print(f"=== 边缘课程 (10 <= score < {SUSPICIOUS_THRESHOLD}) ===", flush=True)
    print(f"共 {len(borderline)} 门，建议人工抽查\n", flush=True)
    for s in borderline[:15]:
        signals_str = ", ".join(f"{k}({v})" for k, v in sorted(s["signals"].items()))
        print(f"  {s['code']:20s} | {s['name']:35s} | score={s['score']:2d} | "
              f"课时={s['hours']:.0f} | 班级数={s['class_count']:3d} | 信号: {signals_str}", flush=True)
    if len(borderline) > 15:
        print(f"  ... 还有 {len(borderline) - 15} 门", flush=True)

    # ── 写出可疑 JSONL ──
    SUSPICIOUS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # 原始分数 ≥ threshold 的写进去
    with SUSPICIOUS_OUTPUT.open("w", encoding="utf-8") as f:
        for s in suspicious:
            # 只保留序列化友好的字段
            record = {k: s[k] for k in ["code", "name", "hours", "credits", "score", "signals", "class_count",
                                         "teachers", "classrooms", "schedulable", "exclude_reason", "raw_text"]}
            # 集合 / list 转一下
            record["teachers"] = list(s["teachers"])
            record["classrooms"] = list(s["classrooms"])
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\n已输出可疑课程 JSONL: {SUSPICIOUS_OUTPUT} ({len(suspicious)} 条)", flush=True)

    # ── 对比新旧检测效果 ──
    old_flagged = {code for code, cd in course_data.items() if cd["schedulable"] == "false"}
    new_flagged = {s["code"] for s in suspicious}
    newly_detected = new_flagged - old_flagged
    missed = old_flagged - new_flagged
    print(f"\n旧检测标记了 {len(old_flagged)} 门, 新评分捕获 {len(new_flagged)} 门", flush=True)
    print(f"新发现: {len(newly_detected)} 门 (旧检测未标记但新评分 >= {SUSPICIOUS_THRESHOLD})", flush=True)
    if missed:
        print(f"遗漏: {len(missed)} 门 (旧检测标记了但新评分 < 阈值): {', '.join(sorted(missed))}", flush=True)
    print(f"\n完毕。", flush=True)


if __name__ == "__main__":
    main()
