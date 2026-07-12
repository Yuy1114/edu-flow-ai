"""Run V3.5 scheduling pipeline end-to-end.

All artifacts are written to a run-specific directory under runs/<run_id>.
Each pipeline run is fully isolated — no shared intermediate files.

Default mode reuses the existing single placement model and regenerates all
post-model artifacts:
  pattern -> template cover -> DB draft -> validations.

Use --train-model to retrain the single LightGBM placement model first.
Use --import-db to insert DB draft rows into MySQL after validation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scheduler.clean_training_samples import clean as clean_training_samples
from scheduler.clean_training_samples import DEFAULT_OUTPUT_PATH as CLEAN_SAMPLES_PATH
from scheduler.clean_training_samples import DEFAULT_REPORT_PATH as CLEAN_REPORT_PATH
from scheduler.export_template_as_scheme import import_template_schemes
from scheduler.export_template_cover_db_draft import export_db_draft
from scheduler.fetch_allocation_teaching_tasks import fetch as fetch_allocation_tasks
from scheduler.import_db_draft_to_mysql import import_draft
from scheduler.pattern_builder import build_patterns
from scheduler.paths import OUTPUT_DIR as PLACEMENT_OUTPUT_DIR
from scheduler.placement_single_model import OUTPUT_DIR as SINGLE_MODEL_DIR
from scheduler.placement_single_model import train as train_single_model
from scheduler.query_db_draft_timetable import query_week, simulate_swap
from scheduler.template_cover_v1 import build_cover
from scheduler.validate_db_draft_export import validate_export
from scheduler.validate_patterns import validate as validate_patterns
from scheduler.validate_template_cover_v1 import validate_cover

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402

PIPELINE_RUNS_DIR = PLACEMENT_OUTPUT_DIR / "runs"


def _load_allowed_config(task_id: int) -> tuple[frozenset[int] | None, frozenset[int] | None]:
    """Read allowed_weekdays and allowed_periods from allocation_task_generation_config."""
    try:
        conn = connect(load_db_config())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT allowed_weekdays, allowed_periods FROM allocation_task_generation_config WHERE task_id = %s",
                    (task_id,),
                )
                row = cur.fetchone()
                if row:
                    def _parse_csv(value: str) -> frozenset[int]:
                        return frozenset(int(x.strip()) for x in value.split(",") if x.strip())
                    weekdays = _parse_csv(row["allowed_weekdays"]) if row.get("allowed_weekdays") else None
                    periods = _parse_csv(row["allowed_periods"]) if row.get("allowed_periods") else None
                    return weekdays, periods
                return None, None
        finally:
            conn.close()
    except Exception:
        return None, None


def run_pipeline(
    *,
    allocation_task_id: int = 1,
    total_weeks: int = 18,
    top_k: int = 300,
    max_templates: int = 8,
    train_model: bool = False,
    model_rounds: int = 160,
    import_db: bool = False,
    truncate_db: bool = False,
    snapshot: bool = True,
) -> dict[str, Any]:
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    generation_run_id = f"v35-{allocation_task_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    run_dir = PIPELINE_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, Any]] = []
    clean_report: dict[str, Any] = {"skipped": True, "reason": "not training, skipping clean"}

    # --- Fetch teaching tasks ---
    allocation_tasks_path = run_dir / "allocation_tasks.jsonl"
    allocation_report = _step(steps, "fetch_allocation_teaching_tasks",
        lambda: fetch_allocation_tasks(allocation_task_id=allocation_task_id, output_path=allocation_tasks_path),
    )

    # --- Train (optional) ---
    if train_model:
        clean_report = _step(steps, "clean_training_samples", lambda: clean_training_samples())
        _step(steps, "train_single_placement_model", lambda: train_single_model(
            data_path=CLEAN_SAMPLES_PATH, output_dir=SINGLE_MODEL_DIR, rounds=model_rounds,
        ))
    else:
        print("Skipping clean_training_samples and training (--train-model not set)", flush=True)

    # --- Build patterns ---
    patterns_path = run_dir / "task_patterns.jsonl"
    dropped_patterns_path = run_dir / "dropped_task_patterns.jsonl"
    pattern_report_path = run_dir / "pattern_report.json"
    pattern_report = _step(steps, "build_patterns", lambda: build_patterns(
        input_path=allocation_tasks_path,
        output_path=patterns_path,
        dropped_path=dropped_patterns_path,
        report_path=pattern_report_path,
    ))

    # --- Validate patterns ---
    pattern_validation_path = run_dir / "pattern_validation_report.json"
    pattern_validation = _step(steps, "validate_patterns", lambda: validate_patterns(
        input_path=patterns_path, report_path=pattern_validation_path,
    ))

    # --- Build template cover ---
    allowed_weekdays, allowed_periods = _load_allowed_config(allocation_task_id)
    cover_path = run_dir / "template_cover_v1.json"
    cover_report_path = run_dir / "template_cover_v1_report.json"
    unresolved_path = run_dir / "template_cover_v1_unresolved.jsonl"
    cover_report = _step(steps, "build_template_cover", lambda: build_cover(
        patterns_path=patterns_path,
        model_dir=SINGLE_MODEL_DIR,
        output_path=cover_path,
        report_path=cover_report_path,
        unresolved_path=unresolved_path,
        top_k=top_k,
        max_templates=max_templates,
        enable_fallback=True,
        allowed_weekdays=allowed_weekdays,
        allowed_periods=allowed_periods,
    ))

    # --- Validate cover ---
    cover_validation_path = run_dir / "template_cover_v1_validation_report.json"
    cover_validation = _step(steps, "validate_template_cover", lambda: validate_cover(
        cover_path=cover_path, report_path=cover_validation_path,
    ))

    # --- Export DB draft ---
    db_draft_dir = run_dir / "db_draft"
    export_report = _step(steps, "export_db_draft", lambda: export_db_draft(
        cover_path=cover_path,
        output_dir=db_draft_dir,
        allocation_task_id=allocation_task_id,
        total_weeks=total_weeks,
        generation_run_id=generation_run_id,
    ))

    # --- Validate DB draft ---
    db_draft_validation = _step(steps, "validate_db_draft", lambda: validate_export(
        input_dir=db_draft_dir,
        report_path=db_draft_dir / "validation_report.json",
    ))

    # --- Simulate ---
    week_query = _step(steps, "query_db_draft_week_5", lambda: query_week(
        input_dir=db_draft_dir, week_number=5,
    ))
    week_swap = _step(steps, "simulate_db_draft_week_swap_5_8", lambda: simulate_swap(
        input_dir=db_draft_dir, week_a=5, week_b=8,
    ))

    # --- Import to DB (optional) ---
    import_report = None
    if import_db:
        import_report = _step(steps, "import_db_draft_to_mysql", lambda: import_draft(
            input_dir=db_draft_dir, execute=True, truncate=truncate_db,
        ))
        _step(steps, "import_template_schemes", lambda: import_template_schemes(
            cover_path=cover_path,
            allocation_task_id=allocation_task_id,
            generation_run_id=generation_run_id,
            execute=True,
            truncate=False,
        ))

    # --- Summary ---
    summary_path = run_dir / "pipeline_summary.json"
    summary = {
        "pipeline": "v3.5",
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run_dir": str(run_dir),
        "run_id": run_id,
        "params": {
            "allocation_task_id": allocation_task_id,
            "generation_run_id": generation_run_id,
            "allowed_weekdays": sorted(allowed_weekdays) if allowed_weekdays else None,
            "allowed_periods": sorted(allowed_periods) if allowed_periods else None,
            "total_weeks": total_weeks,
            "top_k": top_k,
            "max_templates": max_templates,
            "train_model": train_model,
            "model_rounds": model_rounds,
            "import_db": import_db,
            "truncate_db": truncate_db,
        },
        "status": "ok",
        "metrics": {
            "allocation": {k: allocation_report.get(k) for k in ["task_count", "course_types", "room_types"]},
            "clean": clean_report.get("counts", {}),
            "patterns": {
                "pattern_count": pattern_report.get("pattern_count"),
                "dropped_count": pattern_report.get("dropped_count"),
                "validation_invalid_count": pattern_validation.get("invalid_count"),
            },
            "cover": {
                "initial_task_count": cover_report.get("initial_task_count"),
                "completed_task_count": cover_report.get("completed_task_count"),
                "remaining_task_count": cover_report.get("remaining_task_count"),
                "template_count": cover_report.get("template_count"),
                "validation_issue_count": cover_validation.get("issue_count"),
            },
            "db_draft": {
                "counts": export_report.get("counts", {}),
                "validation_issue_count": db_draft_validation.get("issue_count"),
                "week5_entry_count": week_query.get("entry_count"),
                "swap_proof": week_swap.get("proof"),
            },
            "db_import": import_report,
        },
        "steps": steps,
        "artifacts": {
            "allocation_tasks": str(allocation_tasks_path),
            "patterns": str(patterns_path),
            "template_cover": str(cover_path),
            "db_draft_dir": str(db_draft_dir),
            "summary": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _step(steps: list[dict[str, Any]], name: str, fn: Callable[[], Any]) -> Any:
    start = time.time()
    result = fn()
    duration_ms = round((time.time() - start) * 1000, 2)
    steps.append({"name": name, "duration_ms": duration_ms, "status": "ok"})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V3.5 scheduling pipeline.")
    parser.add_argument("--allocation-task-id", type=int, default=1)
    parser.add_argument("--total-weeks", type=int, default=18)
    parser.add_argument("--top-k", type=int, default=300)
    parser.add_argument("--max-templates", type=int, default=8)
    parser.add_argument("--train-model", action="store_true")
    parser.add_argument("--model-rounds", type=int, default=160)
    parser.add_argument("--import-db", action="store_true")
    parser.add_argument("--truncate-db", action="store_true")
    args = parser.parse_args()
    if args.truncate_db and not args.import_db:
        raise SystemExit("--truncate-db requires --import-db")

    summary = run_pipeline(
        allocation_task_id=args.allocation_task_id,
        total_weeks=args.total_weeks,
        top_k=args.top_k,
        max_templates=args.max_templates,
        train_model=args.train_model,
        model_rounds=args.model_rounds,
        import_db=args.import_db,
        truncate_db=args.truncate_db,
    )
    print(json.dumps({
        "status": summary["status"],
        "params": summary["params"],
        "metrics": summary["metrics"],
        "summary": summary["artifacts"]["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
