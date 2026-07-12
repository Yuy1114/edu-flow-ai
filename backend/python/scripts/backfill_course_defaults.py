"""Backfill temporary course defaults for base-data freeze.

Default rules:
- required_hours: inferred from teaching_task.total_hours when possible, fallback 16
- credits: temporary fixed value 1.0

Dry-run by default. Use --execute to write DB changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402


def backfill(*, fallback_hours: int = 16, credits: float = 1.0, execute: bool = False) -> dict[str, Any]:
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    c.id,
                    c.name,
                    c.code,
                    c.credits,
                    c.required_hours,
                    COALESCE(MAX(tt.total_hours), %s) AS inferred_hours
                FROM course c
                LEFT JOIN teaching_task tt ON tt.course_id = c.id AND tt.total_hours > 0
                WHERE c.credits IS NULL OR c.credits <= 0 OR c.required_hours IS NULL OR c.required_hours <= 0
                GROUP BY c.id
                ORDER BY c.code, c.id
            """, (fallback_hours,))
            rows = list(cur.fetchall())
            updates = []
            for row in rows:
                new_required_hours = _safe_int(row.get("inferred_hours")) or fallback_hours
                updates.append({
                    "id": row["id"],
                    "name": row.get("name"),
                    "code": row.get("code"),
                    "old_credits": row.get("credits"),
                    "new_credits": credits,
                    "old_required_hours": row.get("required_hours"),
                    "new_required_hours": new_required_hours,
                })
            if execute:
                for item in updates:
                    cur.execute(
                        "UPDATE course SET credits = %s, required_hours = %s WHERE id = %s",
                        (item["new_credits"], item["new_required_hours"], item["id"]),
                    )
                conn.commit()
            else:
                conn.rollback()
            return {
                "status": "updated" if execute else "dry_run_ok",
                "execute": execute,
                "rules": {
                    "fallback_hours": fallback_hours,
                    "credits": credits,
                    "required_hours_source": "MAX(teaching_task.total_hours) per course, fallback when missing",
                },
                "matched_count": len(updates),
                "counts_by_required_hours": _counts(updates, "new_required_hours"),
                "counts_by_credits": _counts(updates, "new_credits"),
                "preview": updates[:80],
            }
    finally:
        conn.close()


def _counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field)) for row in rows).items()))


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill temporary course defaults.")
    parser.add_argument("--fallback-hours", type=int, default=16)
    parser.add_argument("--credits", type=float, default=1.0)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = backfill(fallback_hours=args.fallback_hours, credits=args.credits, execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
