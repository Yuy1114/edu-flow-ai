"""Build V3.5 template v1 from empty weekly template.

Flow:
  1. Read task patterns.
  2. Sort tasks from hard to easy.
  3. Generate placement TopK for each task.
  4. Greedily place required weekly fragments into an empty weekly template.
  5. Try shallow one-blocker repair for unresolved fragments.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scheduler.pattern_builder import DEFAULT_OUTPUT_PATH as DEFAULT_PATTERNS_PATH
from scheduler.paths import OUTPUT_DIR as PLACEMENT_OUTPUT_DIR
from scheduler.placement_single_model import OUTPUT_DIR as SINGLE_MODEL_DIR
from scheduler.placement_single_model import V35SinglePlacementModel

DEFAULT_OUTPUT_PATH = PLACEMENT_OUTPUT_DIR / "template_v1.json"
DEFAULT_UNRESOLVED_PATH = PLACEMENT_OUTPUT_DIR / "template_v1_unresolved.jsonl"
DEFAULT_REPORT_PATH = PLACEMENT_OUTPUT_DIR / "template_v1_report.json"

MAX_PERIOD_INDEX = 5


@dataclass(frozen=True)
class Candidate:
    resource_key: str
    classroom_name: str
    day_of_week: int
    period_index: int
    score: float

    @property
    def slot_label(self) -> str:
        return f"{self.day_of_week}|{self.period_index}"


class WeeklyTemplate:
    def __init__(self, *, allowed_weekdays: frozenset[int] | None = None, allowed_periods: frozenset[int] | None = None) -> None:
        self.fragments: list[dict[str, Any]] = []
        self.by_fragment_id: dict[str, dict[str, Any]] = {}
        self.teacher_occupancy: dict[tuple[str, int, int], str] = {}
        self.class_occupancy: dict[tuple[str, int, int], str] = {}
        self.room_occupancy: dict[tuple[str, int, int], str] = {}
        self.task_fragments: dict[str, list[str]] = {}
        self.locked_slots: set[str] = set()
        if allowed_weekdays is not None or allowed_periods is not None:
            for day in range(1, 8):
                if allowed_weekdays is not None and day not in allowed_weekdays:
                    for period in range(1, MAX_PERIOD_INDEX + 1):
                        self.locked_slots.add(f"{day}|{period}")
                elif allowed_periods is not None:
                    for period in range(1, MAX_PERIOD_INDEX + 1):
                        if period not in allowed_periods:
                            self.locked_slots.add(f"{day}|{period}")

    def can_place(self, pattern: dict[str, Any], candidate: Candidate, *, ignore_fragment_id: str | None = None) -> tuple[bool, list[str], list[str]]:
        if candidate.slot_label in self.locked_slots:
            return False, [], ["slot_locked"]
        segments = _segments(candidate.day_of_week, candidate.period_index, _safe_int(pattern.get("consecutive_slots")))
        if not segments:
            return False, [], ["invalid_consecutive_period"]

        blockers: list[str] = []
        reasons: list[str] = []
        teacher = str(pattern.get("teacher_name") or "").strip()
        class_names = _class_names(pattern)
        room = candidate.classroom_name

        for day, period in segments:
            if teacher:
                blocker = self.teacher_occupancy.get((teacher, day, period))
                if blocker and blocker != ignore_fragment_id:
                    blockers.append(blocker)
                    reasons.append("teacher_conflict")
            for class_name in class_names:
                blocker = self.class_occupancy.get((class_name, day, period))
                if blocker and blocker != ignore_fragment_id:
                    blockers.append(blocker)
                    reasons.append("class_conflict")
            blocker = self.room_occupancy.get((room, day, period))
            if blocker and blocker != ignore_fragment_id:
                blockers.append(blocker)
                reasons.append("room_conflict")

        blockers = sorted(set(blockers))
        reasons = sorted(set(reasons))
        return not blockers, blockers, reasons

    def place(self, pattern: dict[str, Any], candidate: Candidate, *, candidate_rank: int) -> dict[str, Any]:
        source_key = str(pattern["source_key"])
        fragment_index = len(self.task_fragments.get(source_key, [])) + 1
        fragment_id = f"{source_key}#frag{fragment_index}"
        segments = _segments(candidate.day_of_week, candidate.period_index, _safe_int(pattern.get("consecutive_slots")))
        fragment = {
            "fragment_id": fragment_id,
            "source_key": source_key,
            "fragment_index": fragment_index,
            "course_name": pattern.get("course_name"),
            "course_code": pattern.get("course_code"),
            "teacher_name": pattern.get("teacher_name"),
            "class_name": pattern.get("class_name"),
            "class_names": pattern.get("class_names") or pattern.get("class_group_names") or pattern.get("class_name"),
            "teaching_task_id": pattern.get("teaching_task_id"),
            "required_room_type": pattern.get("required_room_type"),
            "classroom_name": candidate.classroom_name,
            "resource_key": candidate.resource_key,
            "day_of_week": candidate.day_of_week,
            "period_index": candidate.period_index,
            "slot_label": candidate.slot_label,
            "segments": [{"day_of_week": day, "period_index": period} for day, period in segments],
            "consecutive_slots": _safe_int(pattern.get("consecutive_slots")),
            "week_mask": pattern.get("week_mask") or [],
            "duration_weeks": _safe_int(pattern.get("duration_weeks")),
            "session_hours": _safe_int(pattern.get("session_hours")),
            "covered_hours": _safe_int(pattern.get("duration_weeks")) * _safe_int(pattern.get("session_hours")),
            "candidate_rank": candidate_rank,
            "score": candidate.score,
        }
        self._index(fragment)
        return fragment

    def remove(self, fragment_id: str) -> dict[str, Any] | None:
        fragment = self.by_fragment_id.get(fragment_id)
        if not fragment:
            return None
        self._unindex(fragment)
        return fragment

    def restore(self, fragment: dict[str, Any]) -> None:
        self._index(fragment)

    def _index(self, fragment: dict[str, Any]) -> None:
        fragment_id = str(fragment["fragment_id"])
        self.by_fragment_id[fragment_id] = fragment
        self.fragments.append(fragment)
        self.task_fragments.setdefault(str(fragment["source_key"]), []).append(fragment_id)
        teacher = str(fragment.get("teacher_name") or "").strip()
        class_names = _class_names(fragment)
        room = str(fragment["classroom_name"])
        for segment in fragment["segments"]:
            key = (int(segment["day_of_week"]), int(segment["period_index"]))
            if teacher:
                self.teacher_occupancy[(teacher, *key)] = fragment_id
            for class_name in class_names:
                self.class_occupancy[(class_name, *key)] = fragment_id
            self.room_occupancy[(room, *key)] = fragment_id

    def _unindex(self, fragment: dict[str, Any]) -> None:
        fragment_id = str(fragment["fragment_id"])
        self.by_fragment_id.pop(fragment_id, None)
        self.fragments = [item for item in self.fragments if item["fragment_id"] != fragment_id]
        source_key = str(fragment["source_key"])
        self.task_fragments[source_key] = [item for item in self.task_fragments.get(source_key, []) if item != fragment_id]
        teacher = str(fragment.get("teacher_name") or "").strip()
        class_names = _class_names(fragment)
        room = str(fragment["classroom_name"])
        for segment in fragment["segments"]:
            key = (int(segment["day_of_week"]), int(segment["period_index"]))
            if teacher:
                self.teacher_occupancy.pop((teacher, *key), None)
            for class_name in class_names:
                self.class_occupancy.pop((class_name, *key), None)
            self.room_occupancy.pop((room, *key), None)


def build_template(
    *,
    patterns_path: Path = DEFAULT_PATTERNS_PATH,
    model_dir: Path = SINGLE_MODEL_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    unresolved_path: Path = DEFAULT_UNRESOLVED_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    top_k: int = 80,
    repair_depth: int = 0,
    enable_fallback: bool = True,
    allowed_weekdays: frozenset[int] | None = None,
    allowed_periods: frozenset[int] | None = None,
) -> dict[str, Any]:
    patterns = _read_jsonl(patterns_path)
    model = V35SinglePlacementModel.load(model_dir)
    fallback_rooms = _fallback_rooms(model)
    candidates_by_task = {pattern["source_key"]: _predict_candidates(model, pattern, top_k=top_k) for pattern in patterns}
    if allowed_weekdays is not None or allowed_periods is not None:
        _filter_candidates_by_config(candidates_by_task, allowed_weekdays=allowed_weekdays, allowed_periods=allowed_periods)
    ordered_patterns = sorted(patterns, key=lambda item: _task_sort_key(item, candidates_by_task.get(item["source_key"], [])))

    template = WeeklyTemplate(allowed_weekdays=allowed_weekdays, allowed_periods=allowed_periods)
    unresolved: list[dict[str, Any]] = []
    placement_attempts = 0
    fallback_attempts = 0
    fallback_successes = 0
    repair_successes = 0

    for pattern in ordered_patterns:
        needed = _safe_int(pattern.get("weekly_slot_count"))
        placed_for_task = 0
        used_slots: set[str] = set()
        candidates = candidates_by_task.get(pattern["source_key"], [])
        for fragment_no in range(1, needed + 1):
            placed = False
            for rank, candidate in enumerate(candidates, start=1):
                placement_attempts += 1
                if candidate.slot_label in used_slots:
                    continue
                ok, _blockers, _reasons = template.can_place(pattern, candidate)
                if ok:
                    template.place(pattern, candidate, candidate_rank=rank)
                    used_slots.add(candidate.slot_label)
                    placed_for_task += 1
                    placed = True
                    break
            if not placed and repair_depth > 0:
                repaired, slot_label = _try_repair(template, pattern, candidates, used_slots=used_slots, max_depth=repair_depth)
                if repaired:
                    repair_successes += 1
                    if slot_label:
                        used_slots.add(slot_label)
                    placed_for_task += 1
                    placed = True
            if not placed and enable_fallback:
                fallback_candidate, attempts = _find_fallback_candidate(template, pattern, fallback_rooms, used_slots=used_slots, allowed_weekdays=allowed_weekdays, allowed_periods=allowed_periods)
                fallback_attempts += attempts
                if fallback_candidate is not None:
                    template.place(pattern, fallback_candidate, candidate_rank=top_k + 1)
                    used_slots.add(fallback_candidate.slot_label)
                    placed_for_task += 1
                    fallback_successes += 1
                    placed = True
            if not placed:
                unresolved.append({
                    "source_key": pattern["source_key"],
                    "course_name": pattern.get("course_name"),
                    "class_name": pattern.get("class_name"),
                    "class_names": pattern.get("class_names") or pattern.get("class_group_names") or pattern.get("class_name"),
                    "teaching_task_id": pattern.get("teaching_task_id"),
                    "required_room_type": pattern.get("required_room_type"),
                    "fragment_no": fragment_no,
                    "needed_weekly_slot_count": needed,
                    "placed_for_task": placed_for_task,
                    "reason": "no_available_candidate",
                    "candidate_count": len(candidates),
                })

    # Post-generation: remove any fragments on locked slots
    if allowed_weekdays is not None or allowed_periods is not None:
        lock_check_days = allowed_weekdays or frozenset(range(1, 8))
        lock_check_periods = allowed_periods or frozenset(range(1, MAX_PERIOD_INDEX + 1))
        cleaned: list[dict[str, Any]] = []
        for frag in template.fragments:
            if frag["day_of_week"] not in lock_check_days or frag["period_index"] not in lock_check_periods:
                template.remove(str(frag["fragment_id"]))
                unresolved.append({
                    "source_key": frag["source_key"],
                    "course_name": frag.get("course_name"),
                    "class_name": frag.get("class_name"),
                    "class_names": frag.get("class_names") or frag.get("class_name"),
                    "teaching_task_id": frag.get("teaching_task_id"),
                    "required_room_type": frag.get("required_room_type"),
                    "fragment_no": frag.get("fragment_index"),
                    "needed_weekly_slot_count": 1,
                    "placed_for_task": 0,
                    "reason": "locked_slot_post_clean",
                    "candidate_count": 0,
                    "removed_slot": f"{frag['day_of_week']}|{frag['period_index']}",
                })
            else:
                cleaned.append(frag)

    placed_source_keys = {fragment["source_key"] for fragment in template.fragments}
    completed_source_keys = {
        pattern["source_key"]
        for pattern in patterns
        if len(template.task_fragments.get(pattern["source_key"], [])) >= _safe_int(pattern.get("weekly_slot_count"))
    }
    template_doc = {
        "template_id": "v1_main",
        "fragments": sorted(template.fragments, key=lambda item: (item["day_of_week"], item["period_index"], item["classroom_name"], item["source_key"])),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(template_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_jsonl(unresolved_path, unresolved)

    report = {
        "template_id": "v1_main",
        "task_count": len(patterns),
        "placed_task_count": len(placed_source_keys),
        "completed_task_count": len(completed_source_keys),
        "incomplete_task_count": len(patterns) - len(completed_source_keys),
        "fragment_count": len(template.fragments),
        "unresolved_fragment_count": len(unresolved),
        "placement_attempts": placement_attempts,
        "fallback_attempts": fallback_attempts,
        "fallback_successes": fallback_successes,
        "repair_successes": repair_successes,
        "top_k": top_k,
        "repair_depth": repair_depth,
        "enable_fallback": enable_fallback,
        "allowed_weekdays": sorted(allowed_weekdays) if allowed_weekdays else None,
        "allowed_periods": sorted(allowed_periods) if allowed_periods else None,
        "occupancy": {
            "teacher_keys": len(template.teacher_occupancy),
            "class_keys": len(template.class_occupancy),
            "room_keys": len(template.room_occupancy),
        },
        "unresolved_preview": unresolved[:50],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _try_repair(
    template: WeeklyTemplate,
    pattern: dict[str, Any],
    candidates: list[Candidate],
    *,
    used_slots: set[str],
    max_depth: int,
) -> tuple[bool, str | None]:
    return False, None


def _filter_candidates_by_config(
    candidates_by_task: dict[str, list[Candidate]],
    *,
    allowed_weekdays: frozenset[int] | None,
    allowed_periods: frozenset[int] | None,
) -> None:
    """Filter placement candidates in-place to only include allowed days/periods."""
    if allowed_weekdays is None and allowed_periods is None:
        return
    for source_key in list(candidates_by_task.keys()):
        original = candidates_by_task[source_key]
        filtered = [
            c for c in original
            if (allowed_weekdays is None or c.day_of_week in allowed_weekdays)
            and (allowed_periods is None or c.period_index in allowed_periods)
        ]
        candidates_by_task[source_key] = filtered


def _find_fallback_candidate(
    template: WeeklyTemplate,
    pattern: dict[str, Any],
    rooms: list[dict[str, Any]],
    *,
    used_slots: set[str],
    allowed_weekdays: frozenset[int] | None = None,
    allowed_periods: frozenset[int] | None = None,
) -> tuple[Candidate | None, int]:
    required_room_type = str(pattern.get("required_room_type") or "").strip()
    consecutive_slots = _safe_int(pattern.get("consecutive_slots"))
    attempts = 0
    for day in range(1, 8):
        if allowed_weekdays is not None and day not in allowed_weekdays:
            continue
        for period in range(1, MAX_PERIOD_INDEX + 1):
            if allowed_periods is not None and period not in allowed_periods:
                continue
            if f"{day}|{period}" in used_slots:
                continue
            if not _segments(day, period, consecutive_slots):
                continue
            for room in rooms:
                if required_room_type and str(room.get("classroom_type") or "") != required_room_type:
                    continue
                attempts += 1
                room_name = str(room["classroom_name"])
                candidate = Candidate(
                    resource_key=f"{room_name}|{day}|{period}",
                    classroom_name=room_name,
                    day_of_week=day,
                    period_index=period,
                    score=0.0,
                )
                ok, _blockers, _reasons = template.can_place(pattern, candidate)
                if ok:
                    return candidate, attempts
    return None, attempts


def _fallback_rooms(model: V35SinglePlacementModel) -> list[dict[str, Any]]:
    rooms = list(model.room_meta.values())
    return sorted(
        rooms,
        key=lambda item: (
            str(item.get("classroom_type") or ""),
            -_safe_int(item.get("classroom_capacity")),
            str(item.get("classroom_name") or ""),
        ),
    )


def _predict_candidates(model: V35SinglePlacementModel, pattern: dict[str, Any], *, top_k: int) -> list[Candidate]:
    return [
        Candidate(
            resource_key=item.resource_key,
            classroom_name=item.classroom_name,
            day_of_week=item.day_of_week,
            period_index=item.period_index,
            score=item.score,
        )
        for item in model.predict_topk(pattern, top_k=top_k)
    ]


def _task_sort_key(pattern: dict[str, Any], candidates: list[Candidate]) -> tuple[int, int, int, int, int, str]:
    room_priority = 1 if str(pattern.get("required_room_type") or "") == "机房" else 0
    return (
        -_safe_int(pattern.get("weekly_slot_count")),
        -_safe_int(pattern.get("consecutive_slots")),
        -_safe_int(pattern.get("duration_weeks")),
        -room_priority,
        len(candidates),
        str(pattern.get("source_key") or ""),
    )


def _segments(day: int, period: int, consecutive_slots: int) -> list[tuple[int, int]]:
    if consecutive_slots <= 0 or period <= 0 or period + consecutive_slots - 1 > MAX_PERIOD_INDEX:
        return []
    # 连续课段必须在自然边界上起始。如 2 课时块只能从第 1、3 节开始，不能从第 2、4 节开始
    if consecutive_slots > 1 and (period - 1) % consecutive_slots != 0:
        return []
    return [(day, period + offset) for offset in range(consecutive_slots)]


def _fragment_to_pattern(fragment: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_key": fragment["source_key"],
        "teacher_name": fragment.get("teacher_name"),
        "class_name": fragment.get("class_name"),
        "class_names": fragment.get("class_names") or fragment.get("class_name"),
        "consecutive_slots": fragment.get("consecutive_slots"),
        "duration_weeks": fragment.get("duration_weeks"),
        "session_hours": fragment.get("session_hours"),
        "week_mask": fragment.get("week_mask"),
    }


def _candidate_from_fragment(fragment: dict[str, Any]) -> Candidate:
    return Candidate(
        resource_key=str(fragment["resource_key"]),
        classroom_name=str(fragment["classroom_name"]),
        day_of_week=int(fragment["day_of_week"]),
        period_index=int(fragment["period_index"]),
        score=float(fragment.get("score") or 0),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _class_names(row: dict[str, Any]) -> list[str]:
    raw = row.get("class_names") or row.get("class_group_names") or row.get("class_name") or ""
    text = str(raw).replace("，", ",").replace("、", ",").replace(";", ",").replace("|", ",")
    seen: set[str] = set()
    result: list[str] = []
    for item in text.split(","):
        name = item.strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build V3.5 template v1.")
    parser.add_argument("--patterns", default=str(DEFAULT_PATTERNS_PATH))
    parser.add_argument("--model-dir", default=str(SINGLE_MODEL_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--unresolved", default=str(DEFAULT_UNRESOLVED_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--top-k", type=int, default=80)
    parser.add_argument("--repair-depth", type=int, default=0)
    parser.add_argument("--disable-fallback", action="store_true")
    args = parser.parse_args()

    report = build_template(
        patterns_path=Path(args.patterns),
        model_dir=Path(args.model_dir),
        output_path=Path(args.output),
        unresolved_path=Path(args.unresolved),
        report_path=Path(args.report),
        top_k=args.top_k,
        repair_depth=args.repair_depth,
        enable_fallback=not args.disable_fallback,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "unresolved_preview"}, ensure_ascii=False, indent=2))
    print(f"output: {args.output}")
    print(f"unresolved: {args.unresolved}")
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
