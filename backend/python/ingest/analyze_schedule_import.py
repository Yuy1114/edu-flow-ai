"""Analyze parsed schedule import data against current DB master data.

Input: a directory produced by parse_schedule_excel.py / csv_to_jsonl.py.
Output:
- import_conflicts.csv: same business key but different important fields
- import_new_items.csv: parsed items not found in DB
- import_matched_items.csv: parsed items matched with DB rows
- import_analysis_report.json: counts and summary

This script is read-only. It does not insert/update/delete database rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402


CONFLICT_FIELDS = {
    "course": [
        ("course_name", "name", "课程名称"),
        ("credits", "credits", "学分"),
        ("required_hours", "required_hours", "课时"),
        ("course_type", "course_type", "课程类型"),
        ("required_room_type", "required_room_type", "要求教室类型"),
    ],
    "teacher": [
        ("department", "department", "院系"),
        ("title", "title", "职称"),
    ],
    "classroom": [
        ("classroom_type", "classroom_type", "教室类型"),
        ("capacity", "capacity", "容量"),
        ("status", "status", "状态"),
    ],
    "class_group": [
        ("major", "major", "专业"),
        ("department", "department", "院系"),
        ("grade", "grade", "年级"),
        ("student_count", "student_count", "人数"),
    ],
}


def analyze(*, input_dir: Path, output_dir: Path | None = None) -> dict[str, Any]:
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input-dir not found: {input_dir}")
    output_dir = output_dir or input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    parsed = {
        "course": _read_csv(input_dir / "courses.csv"),
        "teacher": _read_csv(input_dir / "teachers.csv"),
        "classroom": _read_csv(input_dir / "classrooms.csv"),
        "class_group": _read_csv(input_dir / "class_groups.csv"),
        "teaching_task": _read_csv(input_dir / "teaching_tasks.csv"),
    }

    conn = connect(load_db_config())
    try:
        db = _load_db_master_data(conn)
    finally:
        conn.close()

    matched: list[dict[str, Any]] = []
    new_items: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    _analyze_entity(
        entity_type="course",
        import_rows=parsed["course"],
        db_by_key=db["course"],
        key_field="course_code",
        display_field="course_name",
        matched=matched,
        new_items=new_items,
        conflicts=conflicts,
    )
    _analyze_entity(
        entity_type="teacher",
        import_rows=parsed["teacher"],
        db_by_key=db["teacher"],
        key_field="teacher_name",
        display_field="teacher_name",
        matched=matched,
        new_items=new_items,
        conflicts=conflicts,
    )
    _analyze_entity(
        entity_type="classroom",
        import_rows=parsed["classroom"],
        db_by_key=db["classroom"],
        key_field="classroom_name",
        display_field="classroom_name",
        matched=matched,
        new_items=new_items,
        conflicts=conflicts,
    )
    _analyze_entity(
        entity_type="class_group",
        import_rows=parsed["class_group"],
        db_by_key=db["class_group"],
        key_field="class_name",
        display_field="class_name",
        matched=matched,
        new_items=new_items,
        conflicts=conflicts,
    )

    task_analysis = _analyze_teaching_tasks(parsed["teaching_task"], db)
    new_items.extend(task_analysis["new_items"])
    matched.extend(task_analysis["matched"])
    conflicts.extend(task_analysis["conflicts"])

    _write_csv(output_dir / "import_conflicts.csv", conflicts, [
        "entity_type", "entity_key", "display_name", "field_name", "field_label", "db_value", "import_value",
        "db_id", "severity", "suggested_action", "reason",
    ])
    _write_csv(output_dir / "import_new_items.csv", new_items, [
        "entity_type", "entity_key", "display_name", "suggested_action", "reason",
    ])
    _write_csv(output_dir / "import_matched_items.csv", matched, [
        "entity_type", "entity_key", "db_id", "display_name", "status",
    ])

    report = {
        "status": "needs_review" if conflicts or new_items else "ok",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "counts": {
            "matched": len(matched),
            "new_items": len(new_items),
            "conflicts": len(conflicts),
            "teaching_task_rows": len(parsed["teaching_task"]),
        },
        "conflict_counts": dict(Counter(row["entity_type"] for row in conflicts).most_common()),
        "new_item_counts": dict(Counter(row["entity_type"] for row in new_items).most_common()),
        "matched_counts": dict(Counter(row["entity_type"] for row in matched).most_common()),
        "files": {
            "conflicts": str(output_dir / "import_conflicts.csv"),
            "new_items": str(output_dir / "import_new_items.csv"),
            "matched_items": str(output_dir / "import_matched_items.csv"),
        },
        "conflicts_preview": conflicts[:50],
        "new_items_preview": new_items[:50],
    }
    (output_dir / "import_analysis_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _analyze_entity(
    *,
    entity_type: str,
    import_rows: list[dict[str, str]],
    db_by_key: dict[str, dict[str, Any]],
    key_field: str,
    display_field: str,
    matched: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> None:
    seen = set()
    for row in import_rows:
        key = _clean(row.get(key_field))
        if not key or key in seen:
            continue
        seen.add(key)
        display_name = _clean(row.get(display_field)) or key
        db_row = db_by_key.get(key)
        if not db_row:
            new_items.append({
                "entity_type": entity_type,
                "entity_key": key,
                "display_name": display_name,
                "suggested_action": "create",
                "reason": "数据库中未找到同自然键记录",
            })
            continue
        matched.append({
            "entity_type": entity_type,
            "entity_key": key,
            "db_id": db_row.get("id"),
            "display_name": display_name,
            "status": "matched",
        })
        for import_field, db_field, label in CONFLICT_FIELDS.get(entity_type, []):
            import_value = _normalize_for_compare(row.get(import_field))
            db_value = _normalize_for_compare(db_row.get(db_field))
            if _is_blank(import_value):
                continue
            if _is_blank(db_value):
                continue
            if import_value != db_value:
                conflicts.append(_conflict(
                    entity_type=entity_type,
                    entity_key=key,
                    display_name=display_name,
                    field_name=import_field,
                    field_label=label,
                    db_value=db_value,
                    import_value=import_value,
                    db_id=db_row.get("id"),
                    reason="同自然键记录字段不一致",
                ))


def _analyze_teaching_tasks(parsed_tasks: list[dict[str, str]], db: dict[str, dict[str, dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    matched = []
    new_items = []
    conflicts = []
    # We currently only verify dependency resolution. Real teaching_task comparison can be added
    # after import review decisions are persisted.
    for row in parsed_tasks:
        course_code = _clean(row.get("course_code"))
        class_names = [_clean(item) for item in re_split_names(row.get("class_names") or row.get("class_name")) if _clean(item)]
        teacher_names = [_clean(item) for item in re_split_names(row.get("teacher_name")) if _clean(item)]
        classroom_names = _classrooms_from_resource_signature(row.get("resource_signature"))
        class_key = ",".join(class_names)
        task_key = f"{course_code}|{class_key}|{','.join(teacher_names)}"
        unresolved = []
        if course_code and course_code not in db["course"]:
            unresolved.append(f"课程 {course_code} 不存在")
        missing_classes = [name for name in class_names if name not in db["class_group"]]
        if missing_classes:
            unresolved.append("班级不存在: " + ",".join(missing_classes))
        missing_teachers = [name for name in teacher_names if name not in db["teacher"]]
        if missing_teachers:
            unresolved.append("教师不存在: " + ",".join(missing_teachers))
        if unresolved:
            new_items.append({
                "entity_type": "teaching_task",
                "entity_key": task_key,
                "display_name": f"{row.get('course_name')} / {class_key}",
                "suggested_action": "review_dependencies",
                "reason": "；".join(unresolved + [_dependency_note(course_code, teacher_names, classroom_names)]),
            })
        else:
            matched.append({
                "entity_type": "teaching_task",
                "entity_key": task_key,
                "db_id": "",
                "display_name": f"{row.get('course_name')} / {class_key}",
                "status": "dependencies_resolved",
            })
    return {"matched": matched, "new_items": new_items, "conflicts": conflicts}


def _dependency_note(course_code: str, teacher_names: list[str], classroom_names: list[str]) -> str:
    parts = [f"course={course_code}"]
    if teacher_names:
        parts.append("teachers=" + "|".join(teacher_names))
    if classroom_names:
        parts.append("classrooms=" + "|".join(classroom_names))
    return "依赖: " + "; ".join(parts)


def _classrooms_from_resource_signature(value: str | None) -> list[str]:
    classrooms = set()
    for slot in str(value or "").split(";"):
        parts = [part.strip() for part in slot.split("|")]
        if len(parts) >= 4 and parts[3]:
            classrooms.add(parts[3])
    return sorted(classrooms)


def _load_db_master_data(conn) -> dict[str, dict[str, dict[str, Any]]]:
    with conn.cursor() as cur:
        courses = _fetch(cur, "SELECT id, code, name, credits, course_type, required_room_type, required_hours, status FROM course")
        teachers = _fetch(cur, "SELECT id, name, department, title, status FROM teacher")
        classrooms = _fetch(cur, "SELECT id, name, classroom_type, capacity, status FROM classroom")
        class_groups = _fetch(cur, "SELECT id, name, major, department, grade, student_count FROM class_group")
    return {
        "course": {_clean(row.get("code")): row for row in courses if _clean(row.get("code"))},
        "teacher": {_clean(row.get("name")): row for row in teachers if _clean(row.get("name"))},
        "classroom": {_clean(row.get("name")): row for row in classrooms if _clean(row.get("name"))},
        "class_group": {_clean(row.get("name")): row for row in class_groups if _clean(row.get("name"))},
    }


def _fetch(cur, sql: str) -> list[dict[str, Any]]:
    cur.execute(sql)
    return list(cur.fetchall())


def _conflict(**kwargs: Any) -> dict[str, Any]:
    return {
        **kwargs,
        "severity": "warning",
        "suggested_action": "review",
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def re_split_names(value: str | None) -> list[str]:
    text = str(value or "")
    return [item for item in text.replace("，", ",").replace("、", ",").split(",")]


def _normalize_for_compare(value: Any) -> str:
    text = _normalize_org_name(_clean(value))
    if text == "":
        return ""
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
        return str(number)
    except ValueError:
        return text


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalize_org_name(value: str) -> str:
    return value.replace("(学院)", "").replace("（学院）", "").strip()


def _is_blank(value: Any) -> bool:
    return _clean(value) == ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze parsed schedule import CSVs against DB master data.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    report = analyze(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    print(json.dumps({k: v for k, v in report.items() if k not in {"conflicts_preview", "new_items_preview"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
