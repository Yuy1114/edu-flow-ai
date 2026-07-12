"""Orchestrate the full historical data training pipeline.

Steps:
1. Parse historical .xls files → CSV/JSONL (batch_process, training mode)
2. Extract training samples from parsed data
3. Train LightGBM model

Output: updated model files in models/v3.5/placement_single/
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import connect, load_db_config  # noqa: E402
from ingest.batch_process_schedule_imports import batch_process, DEFAULT_TRAINING_OUTPUT_ROOT
from ingest.extract_training_samples import extract, DEFAULT_OUTPUT_PATH as TRAINING_SAMPLES_PATH
from scheduler.placement_single_model import DATA_PATH as SINGLE_DATA_PATH, train
from ingest.extract_training_samples import DEFAULT_REPORT_PATH as EXTRACT_REPORT_PATH


def train_from_history(
    *,
    raw_dir: Path,
    task_batch: str = "HISTORY",
    rounds: int = 160,
    record_db: bool = False,
    training_type: str = "HISTORY",
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def step(name: str, fn):
        start = time.time()
        try:
            result = fn()
            elapsed_ms = round((time.time() - start) * 1000, 2)
            steps.append({"name": name, "status": "ok", "duration_ms": elapsed_ms})
            return result
        except Exception as exc:
            elapsed_ms = round((time.time() - start) * 1000, 2)
            steps.append({"name": name, "status": "failed", "duration_ms": elapsed_ms, "error": str(exc)})
            raise

    # Step 1: Parse historical .xls files
    batch_result = step("parse_history", lambda: batch_process(
        input_dir=raw_dir,
        task_batch=task_batch,
        training=True,
    ))

    # Step 2: Extract training samples
    extract_result = step("extract_samples", lambda: extract(
        input_dir=DEFAULT_TRAINING_OUTPUT_ROOT,
        output_path=TRAINING_SAMPLES_PATH,
        report_path=EXTRACT_REPORT_PATH,
    ))

    # Step 3: Train model
    model_path = step("train_model", lambda: train(
        data_path=TRAINING_SAMPLES_PATH,
        rounds=rounds,
    ))

    model_path_str = str(model_path)
    training_log_id = None

    if record_db:
        try:
            training_log_id = _record_training_log(
                training_type=training_type,
                started_at=started_at,
                sample_count=extract_result["total_samples"],
                skipped_count=extract_result["skipped_count"],
                model_path=model_path_str,
                status="SUCCEEDED",
            )
        except Exception as exc:
            steps.append({"name": "record_db_log", "status": "failed", "error": str(exc)})

    return {
        "status": "ok",
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "training_type": training_type,
        "params": {
            "raw_dir": str(raw_dir),
            "rounds": rounds,
            "record_db": record_db,
        },
        "parse_result": {
            "file_count": batch_result.get("file_count"),
            "success_count": batch_result.get("success_count"),
            "parse_counts": batch_result.get("aggregate", {}).get("parse_counts", {}),
        },
        "extract_result": {
            "total_samples": extract_result["total_samples"],
            "unique_courses": extract_result["unique_courses"],
            "unique_teachers": extract_result["unique_teachers"],
            "unique_class_groups": extract_result["unique_class_groups"],
        },
        "model_path": model_path_str,
        "training_log_id": training_log_id,
        "steps": steps,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _record_training_log(
    *,
    training_type: str,
    started_at: str,
    sample_count: int,
    skipped_count: int,
    model_path: str,
    status: str,
) -> int | None:
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ml_training_log
                    (training_type, sample_count, positive_count, negative_count, status, message, started_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                training_type,
                sample_count,
                sample_count,
                0,
                status,
                f"Training from history: {skipped_count} skipped",
                started_at,
                time.strftime("%Y-%m-%d %H:%M:%S"),
            ))
            cur.execute("SELECT LAST_INSERT_ID() AS id")
            row_id = cur.fetchone()["id"]
            conn.commit()
            return row_id
    except Exception:
        conn.rollback()
        return None
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Train LightGBM model from historical schedule data.")
    parser.add_argument("--raw-dir", required=True, help="Path to directory containing .xls schedule files")
    parser.add_argument("--task-batch", default="HISTORY")
    parser.add_argument("--rounds", type=int, default=160)
    parser.add_argument("--record-db", action="store_true", help="Record training log in ml_training_log table")
    args = parser.parse_args()

    result = train_from_history(
        raw_dir=Path(args.raw_dir),
        task_batch=args.task_batch,
        rounds=args.rounds,
        record_db=args.record_db,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
