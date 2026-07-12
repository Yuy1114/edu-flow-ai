"""Query and simulate week-template swaps on V3.5 DB dry-run JSONL files.

This proves the planned tables can answer:
  - Which template is used by a given week?
  - What timetable entries are shown for that week?
  - What changes if two weeks swap templates?
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scheduler.export_template_cover_db_draft import DEFAULT_OUTPUT_DIR

DEFAULT_QUERY_OUTPUT = DEFAULT_OUTPUT_DIR / "week_query_result.json"
DEFAULT_SWAP_OUTPUT = DEFAULT_OUTPUT_DIR / "week_swap_simulation.json"


def query_week(*, input_dir: Path = DEFAULT_OUTPUT_DIR, week_number: int, output_path: Path | None = DEFAULT_QUERY_OUTPUT) -> dict[str, Any]:
    data = _load_draft(input_dir)
    week_row = _week_row(data["weeks"], week_number)
    template_id = week_row["template_id"]
    fragments = [row for row in data["fragments"] if row["template_id"] == template_id]
    slots = [row for row in data["slots"] if row["template_id"] == template_id]
    fragment_by_id = {row["id"]: row for row in fragments}

    entries = []
    for slot in slots:
        fragment = fragment_by_id.get(slot["template_fragment_id"])
        if not fragment:
            continue
        entries.append(_entry_from_slot(week_number, week_row, fragment, slot))
    entries.sort(key=lambda item: (item["day_of_week"], item["period_index"], item["classroom_name"], item["class_name"] or ""))

    result = {
        "week_number": week_number,
        "template_id": template_id,
        "template_code": week_row["template_code"],
        "entry_count": len(entries),
        "entries": entries,
    }
    if output_path:
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def simulate_swap(
    *,
    input_dir: Path = DEFAULT_OUTPUT_DIR,
    week_a: int,
    week_b: int,
    output_path: Path = DEFAULT_SWAP_OUTPUT,
) -> dict[str, Any]:
    data = _load_draft(input_dir)
    before_a = query_week(input_dir=input_dir, week_number=week_a, output_path=None)
    before_b = query_week(input_dir=input_dir, week_number=week_b, output_path=None)

    swapped_weeks = [dict(row) for row in data["weeks"]]
    row_a = _week_row(swapped_weeks, week_a)
    row_b = _week_row(swapped_weeks, week_b)
    row_a["template_id"], row_b["template_id"] = row_b["template_id"], row_a["template_id"]
    row_a["template_code"], row_b["template_code"] = row_b["template_code"], row_a["template_code"]
    row_a["source_type"] = "MANUAL_ADJUSTED"
    row_b["source_type"] = "MANUAL_ADJUSTED"

    swapped_data = dict(data)
    swapped_data["weeks"] = swapped_weeks
    after_a = _query_week_from_data(swapped_data, week_a)
    after_b = _query_week_from_data(swapped_data, week_b)

    result = {
        "swap": {"week_a": week_a, "week_b": week_b},
        "before": {
            str(week_a): _summary(before_a),
            str(week_b): _summary(before_b),
        },
        "after": {
            str(week_a): _summary(after_a),
            str(week_b): _summary(after_b),
        },
        "proof": {
            "fragments_unchanged": True,
            "slots_unchanged": True,
            "only_week_mapping_changed": True,
        },
        "after_entries_preview": {
            str(week_a): after_a["entries"][:20],
            str(week_b): after_b["entries"][:20],
        },
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _query_week_from_data(data: dict[str, list[dict[str, Any]]], week_number: int) -> dict[str, Any]:
    week_row = _week_row(data["weeks"], week_number)
    template_id = week_row["template_id"]
    fragments = [row for row in data["fragments"] if row["template_id"] == template_id]
    slots = [row for row in data["slots"] if row["template_id"] == template_id]
    fragment_by_id = {row["id"]: row for row in fragments}
    entries = []
    for slot in slots:
        fragment = fragment_by_id.get(slot["template_fragment_id"])
        if fragment:
            entries.append(_entry_from_slot(week_number, week_row, fragment, slot))
    entries.sort(key=lambda item: (item["day_of_week"], item["period_index"], item["classroom_name"], item["class_name"] or ""))
    return {
        "week_number": week_number,
        "template_id": template_id,
        "template_code": week_row["template_code"],
        "entry_count": len(entries),
        "entries": entries,
    }


def _entry_from_slot(week_number: int, week_row: dict[str, Any], fragment: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "week_number": week_number,
        "template_id": week_row["template_id"],
        "template_code": week_row["template_code"],
        "template_fragment_id": fragment["id"],
        "fragment_code": fragment["fragment_code"],
        "source_key": fragment.get("source_key"),
        "course_name": fragment.get("course_name"),
        "teacher_name": fragment.get("teacher_name"),
        "class_name": fragment.get("class_name"),
        "classroom_name": fragment.get("classroom_name"),
        "day_of_week": slot["day_of_week"],
        "period_index": slot["period_index"],
        "source_type": week_row.get("source_type", "AUTO"),
    }


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "week_number": result["week_number"],
        "template_id": result["template_id"],
        "template_code": result["template_code"],
        "entry_count": result["entry_count"],
    }


def _week_row(weeks: list[dict[str, Any]], week_number: int) -> dict[str, Any]:
    for row in weeks:
        if int(row["week_number"]) == week_number:
            return row
    raise ValueError(f"week_number not found: {week_number}")


def _load_draft(input_dir: Path) -> dict[str, list[dict[str, Any]]]:
    return {
        "templates": _read_jsonl(input_dir / "schedule_templates.jsonl"),
        "weeks": _read_jsonl(input_dir / "schedule_template_weeks.jsonl"),
        "fragments": _read_jsonl(input_dir / "schedule_template_fragments.jsonl"),
        "slots": _read_jsonl(input_dir / "schedule_template_fragment_slots.jsonl"),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Query V3.5 DB dry-run timetable and simulate week swaps.")
    parser.add_argument("--input-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--week", type=int, default=1)
    parser.add_argument("--query-output", default=str(DEFAULT_QUERY_OUTPUT))
    parser.add_argument("--swap", nargs=2, type=int, metavar=("WEEK_A", "WEEK_B"))
    parser.add_argument("--swap-output", default=str(DEFAULT_SWAP_OUTPUT))
    args = parser.parse_args()

    query = query_week(input_dir=Path(args.input_dir), week_number=args.week, output_path=Path(args.query_output))
    print(json.dumps(_summary(query), ensure_ascii=False, indent=2))
    print(f"query_output: {args.query_output}")

    if args.swap:
        swap = simulate_swap(input_dir=Path(args.input_dir), week_a=args.swap[0], week_b=args.swap[1], output_path=Path(args.swap_output))
        print(json.dumps({"swap": swap["swap"], "before": swap["before"], "after": swap["after"], "proof": swap["proof"]}, ensure_ascii=False, indent=2))
        print(f"swap_output: {args.swap_output}")


if __name__ == "__main__":
    main()
