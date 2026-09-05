"""Run the scheduler end-to-end on generated synthetic data.

This is the first-stage feedback loop: no database and no placement model are
needed. It proves data generation, pattern construction, placement and audits
can be exercised together before real import is introduced.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scheduler.generate_synthetic_data import GeneratorConfig, generate, resource_capacity_preflight
from scheduler.pattern_builder import build_patterns
from scheduler.phase_scheduler import build_phase_cover
from scheduler.validate_patterns import validate


def run(*, config: GeneratorConfig, output_dir: Path, source_dir: Path | None = None) -> dict:
    """Run the synthetic pipeline, optionally reusing an already generated input set."""
    source_dir = source_dir or output_dir / "source"
    manifest_path = source_dir / "manifest.json"
    if manifest_path.exists():
        generated = json.loads(manifest_path.read_text(encoding="utf-8"))
        # A persisted simulation directory may move between processes. Always
        # resolve the two source files from the manifest's current directory.
        generated["paths"] = {
            "teaching_tasks": str(source_dir / "teaching_tasks.jsonl"),
            "classrooms": str(source_dir / "classrooms.json"),
        }
    else:
        generated = generate(config=config, output_dir=source_dir)
    source_tasks = [
        json.loads(line)
        for line in Path(generated["paths"]["teaching_tasks"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source_rooms = json.loads(Path(generated["paths"]["classrooms"]).read_text(encoding="utf-8"))
    capacity_preflight = resource_capacity_preflight(source_tasks, source_rooms)
    patterns_path = output_dir / "task_patterns.jsonl"
    pattern_report = build_patterns(
        input_path=Path(generated["paths"]["teaching_tasks"]),
        output_path=patterns_path,
        dropped_path=output_dir / "dropped_task_patterns.jsonl",
        report_path=output_dir / "pattern_report.json",
    )
    pattern_validation = validate(input_path=patterns_path, report_path=output_dir / "pattern_validation_report.json")
    cover_report = build_phase_cover(
        patterns_path=patterns_path,
        output_path=output_dir / "phase_cover.json",
        report_path=output_dir / "phase_cover_report.json",
        unresolved_path=output_dir / "unresolved.jsonl",
        rooms_path=Path(generated["paths"]["classrooms"]),
        use_model=False,
    )
    hard_conflict_count = sum(
        sum(int(value) for value in audit.values())
        for audit in cover_report["conflicts"].values()
    )
    hour_audit = {
        "required_total_hours": int(cover_report.get("required_total_hours") or 0),
        "scheduled_total_hours": int(cover_report.get("scheduled_total_hours") or 0),
        "delta_total_hours": int(cover_report.get("hour_delta_total") or 0),
        "exact_task_count": int(cover_report.get("conservation_ok") or 0),
        "over_task_count": int(cover_report.get("hour_over_task_count") or 0),
        "under_task_count": int(cover_report.get("hour_under_task_count") or 0),
        "over_hours": int(cover_report.get("hour_over_total") or 0),
        "under_hours": int(cover_report.get("hour_under_total") or 0),
        "mismatch_count": int(cover_report.get("conservation_mismatch") or 0),
        "tasks": cover_report.get("hour_audit_tasks") or [],
    }
    report = {
        "config": generated["config"],
        "generated": generated["counts"],
        "patterns": {"count": pattern_report["pattern_count"], "invalid": pattern_validation["invalid_count"]},
        "resource_capacity_preflight": capacity_preflight,
        "schedule": {
            "completed": cover_report["completed_task_count"],
            "remaining": cover_report["remaining_task_count"],
            "conflicts": cover_report["conflicts"],
            "conservation_mismatch": cover_report["conservation_mismatch"],
            "capacity_mismatch": cover_report.get("capacity_mismatch_count", 0),
            "unresolved_reason_counts": cover_report.get("unresolved_reason_counts", {}),
            "template_count": int(cover_report.get("template_count") or 0),
            "hard_conflict_count": hard_conflict_count,
            "hour_audit": hour_audit,
        },
    }
    hard_error_count = (
        int(report["patterns"]["invalid"])
        + int(report["schedule"]["capacity_mismatch"])
        + hard_conflict_count
    )
    report["hard_constraint_error_count"] = hard_error_count
    report["needs_manual_review"] = bool(
        report["schedule"]["remaining"]
        or hour_audit["mismatch_count"]
        or not capacity_preflight["feasible"]
    )
    report["status"] = (
        "invalid" if hard_error_count
        else "needs_manual_review" if report["needs_manual_review"]
        else "ok"
    )
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a database-free synthetic scheduler pipeline.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--courses", type=int, default=1964)
    parser.add_argument("--teachers", type=int, default=541)
    parser.add_argument("--class-groups", type=int, default=362)
    parser.add_argument("--classrooms", type=int, default=320)
    parser.add_argument(
        "--profile", choices=["balanced", "formal-mix", "lab-heavy", "constrained"], default="balanced",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run(config=GeneratorConfig(
        seed=args.seed, courses=args.courses, teachers=args.teachers,
        class_groups=args.class_groups, classrooms=args.classrooms, profile=args.profile,
    ), output_dir=output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # A reviewable result is still a valid experiment artifact. Only an output
    # that violates hard constraints should fail the standalone command.
    if report["status"] == "invalid":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
