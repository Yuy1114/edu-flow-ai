"""Run the dynamic absolute-week scheduling pipeline end-to-end.

All artifacts are written to a run-specific directory under runs/<run_id>.
Each pipeline run is fully isolated — no shared intermediate files.

Default mode is rules-only and regenerates all scheduling artifacts:
  pattern -> template cover -> DB draft -> validations.

Use --train-model to retrain the single LightGBM placement model and enable
its soft candidate guidance for that same run.
Use --import-db to insert DB draft rows into MySQL after validation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from scheduler.clean_training_samples import clean as clean_training_samples
from scheduler.clean_training_samples import DEFAULT_OUTPUT_PATH as CLEAN_SAMPLES_PATH
from scheduler.clean_training_samples import DEFAULT_REPORT_PATH as CLEAN_REPORT_PATH
from scheduler.export_template_as_scheme import import_template_schemes
from scheduler.export_template_cover_db_draft import export_db_draft
from scheduler.fetch_allocation_teaching_tasks import (
    enrich_patterns_with_constraints,
    fetch as fetch_allocation_tasks,
)
from scheduler.import_db_draft_to_mysql import import_draft
from scheduler.pattern_builder import build_patterns
from scheduler.paths import OUTPUT_DIR as PLACEMENT_OUTPUT_DIR
from scheduler.placement_single_model import OUTPUT_DIR as SINGLE_MODEL_DIR
from scheduler.placement_single_model import train as train_single_model
from scheduler.phase_scheduler import build_phase_cover
from scheduler.query_db_draft_timetable import query_week, simulate_swap
from scheduler.validate_db_draft_export import validate_export
from scheduler.validate_patterns import validate as validate_patterns

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.db.session import connect, load_db_config  # noqa: E402

PIPELINE_RUNS_DIR = PLACEMENT_OUTPUT_DIR / "runs"


def _load_allowed_config(
    task_id: int,
) -> tuple[frozenset[int] | None, frozenset[int] | None, frozenset[int] | None]:
    """Read the absolute week/day/atomic-period scheduling domain."""
    conn = connect(load_db_config())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT allowed_weeks, allowed_weekdays, allowed_periods "
                "FROM allocation_task_generation_config WHERE task_id = %s",
                (task_id,),
            )
            row = cur.fetchone()
            if row:
                def _parse_csv(value: str) -> frozenset[int]:
                    return frozenset(int(x.strip()) for x in value.split(",") if x.strip())
                weeks = _parse_csv(row.get("allowed_weeks") or "")
                weekdays = _parse_csv(row.get("allowed_weekdays") or "")
                periods = _parse_csv(row.get("allowed_periods") or "")
                return weeks, weekdays, periods
            return None, None, None
    finally:
        conn.close()


def run_pipeline(
    *,
    allocation_task_id: int = 1,
    total_weeks: int = 18,
    top_k: int = 300,
    max_templates: int = 8,  # deprecated: dynamic templates are derived from active week sets
    phase_weeks: tuple[int, ...] | None = None,
    train_model: bool = False,
    model_rounds: int = 160,
    import_db: bool = False,
    truncate_db: bool = False,
    snapshot: bool = True,
    teacher_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    # Include both microseconds and a random suffix.  Fast retries can start in the
    # same clock tick (especially in tests/containers), and must never reuse an
    # artifact directory or generation batch identifier.
    run_token = uuid.uuid4().hex[:8]
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_id = f"{run_timestamp}_{run_token}"
    generation_run_id = f"v35-{allocation_task_id}-{run_timestamp.replace('_', '')}-{run_token}"
    run_dir = PIPELINE_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 画像随作业一起落盘：排课结果的可复现证据，而不是只留在调用方的内存里。
    if teacher_profiles:
        (run_dir / "teacher_profiles.json").write_text(
            json.dumps(teacher_profiles, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    steps: list[dict[str, Any]] = []
    clean_report: dict[str, Any] = {"skipped": True, "reason": "not training, skipping clean"}

    # --- Fetch teaching tasks and the hard scheduling domain ---
    allowed_weeks, allowed_weekdays, allowed_periods = _load_allowed_config(allocation_task_id)
    _validate_allowed_config(
        allowed_weeks=allowed_weeks,
        allowed_weekdays=allowed_weekdays,
        allowed_periods=allowed_periods,
        total_weeks=total_weeks,
    )
    allocation_tasks_path = run_dir / "allocation_tasks.jsonl"
    active_rooms_path = run_dir / "active_classrooms.json"
    allocation_context_path = run_dir / "allocation_context.json"
    excluded_tasks_path = run_dir / "excluded_teaching_tasks.jsonl"
    allocation_report = _step(steps, "fetch_allocation_teaching_tasks",
        lambda: fetch_allocation_tasks(
            allocation_task_id=allocation_task_id,
            output_path=allocation_tasks_path,
            rooms_path=active_rooms_path,
            context_path=allocation_context_path,
            excluded_path=excluded_tasks_path,
            allowed_weeks=allowed_weeks,
        ),
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
    constraint_enrichment = _step(steps, "enrich_patterns_with_constraints", lambda: enrich_patterns_with_constraints(
        patterns_path=patterns_path,
        task_source_path=allocation_tasks_path,
        allowed_weeks=allowed_weeks,
    ))

    # --- Validate patterns ---
    pattern_validation_path = run_dir / "pattern_validation_report.json"
    pattern_validation = _step(steps, "validate_patterns", lambda: validate_patterns(
        input_path=patterns_path, report_path=pattern_validation_path,
    ))

    # --- Build absolute-week schedule and derive dynamic templates ---
    resolved_phase_weeks = phase_weeks or _default_phase_weeks(total_weeks)
    cover_path = run_dir / "phase_cover.json"
    cover_report_path = run_dir / "phase_cover_report.json"
    unresolved_path = run_dir / "phase_cover_unresolved.jsonl"
    cover_report = _step(steps, "build_phase_cover", lambda: build_phase_cover(
        patterns_path=patterns_path,
        model_dir=SINGLE_MODEL_DIR,
        output_path=cover_path,
        report_path=cover_report_path,
        unresolved_path=unresolved_path,
        phase_weeks=resolved_phase_weeks,
        top_k=top_k,
        allowed_weekdays=allowed_weekdays,
        allowed_periods=allowed_periods,
        rooms_path=active_rooms_path,
        use_model=train_model,
        teacher_preferences=teacher_profiles,
    ))

    # --- Export DB draft ---
    db_draft_dir = run_dir / "db_draft"
    export_report = _step(steps, "export_db_draft", lambda: export_db_draft(
        cover_path=cover_path,
        output_dir=db_draft_dir,
        allocation_task_id=allocation_task_id,
        total_weeks=total_weeks,
        generation_run_id=generation_run_id,
        task_source_path=allocation_tasks_path,
        rooms_path=active_rooms_path,
    ))

    # --- Validate DB draft ---
    db_draft_validation = _step(steps, "validate_db_draft", lambda: validate_export(
        input_dir=db_draft_dir,
        report_path=db_draft_dir / "validation_report.json",
    ))

    overall_hour_audit = _overall_hour_audit(
        cover_report=cover_report,
        excluded_tasks_path=excluded_tasks_path,
    )

    publication_gate = _publication_gate(
        allocation_report=allocation_report,
        pattern_report=pattern_report,
        pattern_validation=pattern_validation,
        constraint_enrichment=constraint_enrichment,
        cover_report=cover_report,
        db_draft_validation=db_draft_validation,
        overall_hour_audit=overall_hour_audit,
    )

    # --- Simulate ---
    preview_week = min(5, max(1, total_weeks))
    swap_week = min(8, max(1, total_weeks))
    if db_draft_validation.get("issue_count", 0):
        week_query = {"status": "skipped", "reason": "db_draft_validation_failed", "entry_count": 0}
        week_swap = {"status": "skipped", "reason": "db_draft_validation_failed", "proof": None}
    else:
        week_query = _step(steps, f"query_db_draft_week_{preview_week}", lambda: query_week(
            input_dir=db_draft_dir, week_number=preview_week,
        ))
        if preview_week == swap_week:
            week_swap = {"status": "skipped", "reason": "semester_has_only_one_preview_week", "proof": None}
        else:
            week_swap = _step(steps, f"simulate_db_draft_week_swap_{preview_week}_{swap_week}", lambda: simulate_swap(
                input_dir=db_draft_dir, week_a=preview_week, week_b=swap_week,
            ))

    # --- Import to DB (optional) ---
    import_report = None
    scheme_import_report = None
    imported_for_review = False
    if import_db and publication_gate["can_import_candidate"]:
        batch_connection = connect(load_db_config())
        try:
            batch_connection.begin()
            import_report = _step(steps, "import_db_draft_to_mysql", lambda: import_draft(
                input_dir=db_draft_dir, execute=True, truncate=truncate_db,
                connection=batch_connection, commit=False,
            ))
            _require_import_status(import_report, step="import_db_draft_to_mysql")
            scheme_import_report = _step(steps, "import_template_schemes", lambda: import_template_schemes(
                cover_path=cover_path,
                allocation_task_id=allocation_task_id,
                generation_run_id=generation_run_id,
                report_path=run_dir / "scheme_import_report.json",
                validation_report_path=cover_report_path,
                publication_gate=publication_gate,
                execute=True,
                truncate=False,
                connection=batch_connection,
                commit=False,
            ))
            _require_import_status(scheme_import_report, step="import_template_schemes")
            batch_connection.commit()
        except Exception:
            batch_connection.rollback()
            raise
        finally:
            batch_connection.close()
        imported_for_review = publication_gate["status"] == "NEEDS_MANUAL_REVIEW"
    elif import_db:
        import_report = {
            "status": "skipped_by_publication_gate",
            "pipeline_status": publication_gate["status"],
            "hard_blockers": publication_gate["hard_blockers"],
            "manual_reviews": publication_gate["manual_reviews"],
        }
    publication_gate["imported_for_review"] = imported_for_review

    # --- Summary ---
    summary_path = run_dir / "pipeline_summary.json"
    summary = {
        "pipeline": "v3.6-dynamic-week",
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run_dir": str(run_dir),
        "run_id": run_id,
        "params": {
            "allocation_task_id": allocation_task_id,
            "generation_run_id": generation_run_id,
            "allowed_weeks": sorted(allowed_weeks) if allowed_weeks else None,
            "allowed_weekdays": sorted(allowed_weekdays) if allowed_weekdays else None,
            "allowed_periods": sorted(allowed_periods) if allowed_periods else None,
            "total_weeks": total_weeks,
            "phase_weeks": list(resolved_phase_weeks),
            "top_k": top_k,
            "train_model": train_model,
            "model_guidance_enabled": train_model,
            "model_rounds": model_rounds,
            "import_db": import_db,
            "truncate_db": truncate_db,
            "teacher_profile_count": len(teacher_profiles or {}),
        },
        "status": publication_gate["status"],
        "publication_gate": publication_gate,
        "metrics": {
            "allocation": {k: allocation_report.get(k) for k in [
                "task_count", "bound_task_count", "excluded_task_count",
                "active_classroom_count", "hard_issue_count", "warning_count",
                "course_types", "room_types",
            ]},
            "clean": clean_report.get("counts", {}),
            "patterns": {
                "pattern_count": pattern_report.get("pattern_count"),
                "dropped_count": pattern_report.get("dropped_count"),
                "warning_count": pattern_report.get("warning_count"),
                "warning_reason_counts": pattern_report.get("warning_reason_counts"),
                "validation_invalid_count": pattern_validation.get("invalid_count"),
                "constraint_enriched_count": constraint_enrichment.get("enriched_count"),
                "constraint_missing_source_count": constraint_enrichment.get("missing_source_count"),
            },
            "cover": {
                "initial_task_count": cover_report.get("initial_task_count"),
                "completed_task_count": cover_report.get("completed_task_count"),
                "remaining_task_count": cover_report.get("remaining_task_count"),
                "template_count": cover_report.get("template_count"),
                "phase_weeks": cover_report.get("phase_weeks"),
                "merged_section_count": cover_report.get("merged_section_count"),
                "model_hit_rate": cover_report.get("model_hit_rate"),
                "conflicts": cover_report.get("conflicts"),
                "conservation_mismatch": cover_report.get("conservation_mismatch"),
                "validation_issue_count": cover_report.get("validation_issue_count"),
                "required_total_hours": cover_report.get("required_total_hours"),
                "scheduled_total_hours": cover_report.get("scheduled_total_hours"),
                "hour_delta_total": cover_report.get("hour_delta_total"),
                "hour_over_task_count": cover_report.get("hour_over_task_count"),
                "hour_under_task_count": cover_report.get("hour_under_task_count"),
                "overall_bound_required_hours": overall_hour_audit["overall_bound_required_hours"],
                "overall_scheduled_hours": overall_hour_audit["overall_scheduled_hours"],
                "overall_delta_hours": overall_hour_audit["overall_delta_hours"],
                "overall_under_task_count": overall_hour_audit["overall_under_task_count"],
                "profile_satisfaction": cover_report.get("profile_satisfaction"),
            },
            "db_draft": {
                "counts": export_report.get("counts", {}),
                "validation_issue_count": db_draft_validation.get("issue_count"),
                "preview_week": preview_week,
                "preview_week_entry_count": week_query.get("entry_count"),
                "swap_proof": week_swap.get("proof"),
            },
            "db_import": {
                "template_import": import_report,
                "scheme_import": scheme_import_report,
                "imported_for_review": imported_for_review,
            } if import_report is not None else None,
        },
        "steps": steps,
        "artifacts": {
            "allocation_tasks": str(allocation_tasks_path),
            "allocation_context": str(allocation_context_path),
            "active_classrooms": str(active_rooms_path),
            "excluded_teaching_tasks": str(excluded_tasks_path),
            "patterns": str(patterns_path),
            "dropped_task_patterns": str(dropped_patterns_path),
            "pattern_report": str(pattern_report_path),
            "template_cover": str(cover_path),
            "cover_report": str(cover_report_path),
            "unresolved_tasks": str(unresolved_path),
            "db_draft_dir": str(db_draft_dir),
            "db_draft_validation": str(db_draft_dir / "validation_report.json"),
            "summary": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _default_phase_weeks(total_weeks: int) -> tuple[int, ...]:
    """Compatibility carrier for semester length; templates are derived dynamically."""
    return (max(1, total_weeks),)


def _validate_allowed_config(
    *,
    allowed_weeks: frozenset[int] | None,
    allowed_weekdays: frozenset[int] | None,
    allowed_periods: frozenset[int] | None,
    total_weeks: int,
) -> None:
    configured_domains = {
        "allowed_weeks": (allowed_weeks, set(range(1, total_weeks + 1))),
        "allowed_weekdays": (allowed_weekdays, set(range(1, 8))),
        "allowed_periods": (allowed_periods, set(range(1, 12))),
    }
    for name, (values, legal) in configured_domains.items():
        if values is None:
            continue  # no generation-config row: engine defaults are authoritative
        if not values:
            raise ValueError(f"{name} must not be empty")
        invalid = sorted(set(values) - legal)
        if invalid:
            raise ValueError(f"{name} contains values outside the scheduling domain: {invalid}")


def _overall_hour_audit(
    *,
    cover_report: dict[str, Any],
    excluded_tasks_path: Path,
) -> dict[str, Any]:
    excluded_rows = _read_jsonl(excluded_tasks_path) if excluded_tasks_path.exists() else []
    excluded_tasks = []
    for row in excluded_rows:
        required = int(row.get("total_hours") or 0)
        excluded_tasks.append({
            "source_key": row.get("source_key"),
            "teaching_task_id": row.get("teaching_task_id"),
            "course_name": row.get("course_name"),
            "required_hours": required,
            "scheduled_hours": 0,
            "delta_hours": -required,
            "status": "under" if required > 0 else "ok",
            "reason": row.get("exclusion_reason") or "explicitly_excluded",
        })
    cover_required = int(cover_report.get("required_total_hours") or 0)
    scheduled = int(cover_report.get("scheduled_total_hours") or 0)
    excluded_required = sum(row["required_hours"] for row in excluded_tasks)
    overall_required = cover_required + excluded_required
    return {
        "cover_required_hours": cover_required,
        "excluded_required_hours": excluded_required,
        "overall_bound_required_hours": overall_required,
        "overall_scheduled_hours": scheduled,
        "overall_delta_hours": scheduled - overall_required,
        "overall_over_task_count": int(cover_report.get("hour_over_task_count") or 0),
        "overall_under_task_count": (
            int(cover_report.get("hour_under_task_count") or 0)
            + sum(row["status"] == "under" for row in excluded_tasks)
        ),
        "excluded_task_audit": excluded_tasks,
    }


def _publication_gate(
    *,
    allocation_report: dict[str, Any],
    pattern_report: dict[str, Any],
    pattern_validation: dict[str, Any],
    constraint_enrichment: dict[str, Any],
    cover_report: dict[str, Any],
    db_draft_validation: dict[str, Any],
    overall_hour_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Separate unsafe output from a usable draft that needs human completion."""
    hard_blockers: list[str] = []
    manual_reviews: list[str] = []

    if allocation_report.get("hard_issue_count", 0):
        hard_blockers.append(f"invalid active-resource references={allocation_report['hard_issue_count']}")
    if pattern_report.get("dropped_count", 0):
        hard_blockers.append(f"silently dropped task patterns={pattern_report['dropped_count']}")
    if pattern_validation.get("invalid_count", 0):
        hard_blockers.append(f"invalid patterns={pattern_validation['invalid_count']}")
    if constraint_enrichment.get("missing_source_count", 0):
        hard_blockers.append(f"patterns missing constraint source={constraint_enrichment['missing_source_count']}")

    bound_count = int(allocation_report.get("bound_task_count") or 0)
    input_count = int(allocation_report.get("task_count") or 0)
    excluded_count = int(allocation_report.get("excluded_task_count") or 0)
    if bound_count and bound_count != input_count + excluded_count:
        hard_blockers.append(
            f"teaching task accounting mismatch={bound_count}-{input_count}-{excluded_count}"
        )
    raw_pattern_count = int(pattern_report.get("raw_pattern_count") or 0)
    if input_count != raw_pattern_count:
        hard_blockers.append(f"task-to-pattern accounting mismatch={input_count}-{raw_pattern_count}")

    conflict_count = sum(sum(audit.values()) for audit in (cover_report.get("conflicts") or {}).values())
    if conflict_count:
        hard_blockers.append(f"hard conflicts={conflict_count}")
    if cover_report.get("capacity_mismatch_count", 0):
        hard_blockers.append(f"classroom capacity violations={cover_report['capacity_mismatch_count']}")
    if db_draft_validation.get("issue_count", 0):
        hard_blockers.append(f"db draft issues={db_draft_validation['issue_count']}")

    if excluded_count:
        manual_reviews.append(f"explicitly excluded tasks={excluded_count}")
    if pattern_report.get("warning_count", 0):
        manual_reviews.append(f"irregular task patterns={pattern_report['warning_count']}")
    if cover_report.get("remaining_task_count", 0):
        manual_reviews.append(f"unplaced tasks={cover_report['remaining_task_count']}")
    if cover_report.get("conservation_mismatch", 0):
        manual_reviews.append(f"hour audit mismatches={cover_report['conservation_mismatch']}")

    if hard_blockers:
        status = "BLOCKED"
    elif manual_reviews:
        status = "NEEDS_MANUAL_REVIEW"
    else:
        status = "OK"
    return {
        "status": status,
        "can_publish": status == "OK",
        "can_import_candidate": status != "BLOCKED",
        "requires_manual_review": status == "NEEDS_MANUAL_REVIEW",
        "hard_blocker_count": len(hard_blockers),
        "manual_review_count": len(manual_reviews),
        "hard_blockers": hard_blockers,
        "manual_reviews": manual_reviews,
        "overall_hour_audit": overall_hour_audit or {},
    }


def _validation_errors(
    *,
    pattern_validation: dict[str, Any],
    cover_report: dict[str, Any],
    db_draft_validation: dict[str, Any],
    allocation_report: dict[str, Any] | None = None,
) -> list[str]:
    """Deprecated compatibility helper; run_pipeline uses _publication_gate."""
    errors: list[str] = []
    if allocation_report and allocation_report.get("hard_issue_count", 0):
        errors.append(f"invalid active-resource references={allocation_report['hard_issue_count']}")
    if pattern_validation.get("invalid_count", 0):
        errors.append(f"invalid patterns={pattern_validation['invalid_count']}")
    if cover_report.get("remaining_task_count", 0):
        errors.append(f"unplaced tasks={cover_report['remaining_task_count']}")
    conflict_count = sum(sum(audit.values()) for audit in (cover_report.get("conflicts") or {}).values())
    if conflict_count:
        errors.append(f"hard conflicts={conflict_count}")
    if cover_report.get("conservation_mismatch", 0):
        errors.append(f"hour conservation mismatches={cover_report['conservation_mismatch']}")
    if db_draft_validation.get("issue_count", 0):
        errors.append(f"db draft issues={db_draft_validation['issue_count']}")
    return errors


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _require_import_status(report: dict[str, Any], *, step: str) -> None:
    """An import request may never become a successful pipeline without DB rows."""
    if report.get("status") != "inserted":
        raise RuntimeError(f"{step} did not persist its output: {report}")


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
    parser.add_argument("--max-templates", type=int, default=8,
                        help="已废弃: 动态模板由每周活动集合自动推导")
    parser.add_argument("--phase-weeks", default=None,
                        help="兼容参数；各数字之和仅定义学期总周数")
    parser.add_argument("--train-model", action="store_true")
    parser.add_argument("--model-rounds", type=int, default=160)
    parser.add_argument("--import-db", action="store_true")
    parser.add_argument("--truncate-db", action="store_true")
    parser.add_argument("--teacher-profiles", default=None,
                        help="教师画像软偏好 JSON 文件，{教师ID或姓名: final_profile}")
    args = parser.parse_args()
    if args.truncate_db and not args.import_db:
        raise SystemExit("--truncate-db requires --import-db")
    phase_weeks = (
        tuple(int(x) for x in args.phase_weeks.split(",") if x.strip())
        if args.phase_weeks else None
    )

    summary = run_pipeline(
        allocation_task_id=args.allocation_task_id,
        total_weeks=args.total_weeks,
        top_k=args.top_k,
        max_templates=args.max_templates,
        phase_weeks=phase_weeks,
        train_model=args.train_model,
        model_rounds=args.model_rounds,
        import_db=args.import_db,
        truncate_db=args.truncate_db,
        teacher_profiles=(
            json.loads(Path(args.teacher_profiles).read_text(encoding="utf-8"))
            if args.teacher_profiles else None
        ),
    )
    print(json.dumps({
        "status": summary["status"],
        "params": summary["params"],
        "metrics": summary["metrics"],
        "summary": summary["artifacts"]["summary"],
    }, ensure_ascii=False, indent=2))
    print("EDUFLOW_PIPELINE_RESULT=" + json.dumps({
        "status": summary["status"],
        "summary": summary["artifacts"]["summary"],
    }, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
