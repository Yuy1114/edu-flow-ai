"""Backfill classroom capacity defaults for base-data freeze.

Default rules:
- 普通教室: 80
- 机房: 80
- explicitly listed large labs: 120

Dry-run by default. Use --execute to write DB changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402


def backfill(
    *,
    normal_capacity: int = 80,
    lab_capacity: int = 80,
    large_lab_capacity: int = 120,
    large_lab_names: set[str] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    large_lab_names = large_lab_names or set()
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, classroom_type, capacity
                FROM classroom
                WHERE capacity IS NULL OR capacity <= 0
                ORDER BY classroom_type, name
            """)
            rows = list(cur.fetchall())
            updates = []
            for row in rows:
                classroom_type = str(row.get("classroom_type") or "").strip()
                name = str(row.get("name") or "").strip()
                capacity = None
                if classroom_type == "普通教室":
                    capacity = normal_capacity
                elif classroom_type == "机房":
                    capacity = large_lab_capacity if name in large_lab_names else lab_capacity
                if capacity is not None:
                    updates.append({
                        "id": row["id"],
                        "name": name,
                        "classroom_type": classroom_type,
                        "old_capacity": row.get("capacity"),
                        "new_capacity": capacity,
                    })
            if execute:
                for item in updates:
                    cur.execute("UPDATE classroom SET capacity = %s WHERE id = %s", (item["new_capacity"], item["id"]))
                conn.commit()
            else:
                conn.rollback()
            return {
                "status": "updated" if execute else "dry_run_ok",
                "execute": execute,
                "rules": {
                    "普通教室": normal_capacity,
                    "机房": lab_capacity,
                    "large_lab_capacity": large_lab_capacity,
                    "large_lab_names": sorted(large_lab_names),
                },
                "matched_count": len(updates),
                "preview": updates[:80],
                "counts_by_new_capacity": _counts(updates, "new_capacity"),
            }
    finally:
        conn.close()


def _counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field))
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill classroom capacity defaults.")
    parser.add_argument("--normal-capacity", type=int, default=80)
    parser.add_argument("--lab-capacity", type=int, default=80)
    parser.add_argument("--large-lab-capacity", type=int, default=120)
    parser.add_argument("--large-lab", action="append", default=[], help="Large lab classroom name. Can be repeated.")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = backfill(
        normal_capacity=args.normal_capacity,
        lab_capacity=args.lab_capacity,
        large_lab_capacity=args.large_lab_capacity,
        large_lab_names={str(item).strip() for item in args.large_lab if str(item).strip()},
        execute=args.execute,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
