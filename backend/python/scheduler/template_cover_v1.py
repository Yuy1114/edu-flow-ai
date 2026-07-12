"""Iterative template cover v1.

Each iteration builds a new weekly template for remaining tasks only. Previous
iteration templates are kept unchanged; completed tasks are removed from the
next iteration's input.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from scheduler.pattern_builder import DEFAULT_OUTPUT_PATH as DEFAULT_PATTERNS_PATH
from scheduler.paths import OUTPUT_DIR as PLACEMENT_OUTPUT_DIR
from scheduler.placement_single_model import OUTPUT_DIR as SINGLE_MODEL_DIR
from scheduler.template_builder_v1 import build_template

DEFAULT_OUTPUT_PATH = PLACEMENT_OUTPUT_DIR / "template_cover_v1.json"
DEFAULT_REPORT_PATH = PLACEMENT_OUTPUT_DIR / "template_cover_v1_report.json"
DEFAULT_UNRESOLVED_PATH = PLACEMENT_OUTPUT_DIR / "template_cover_v1_unresolved.jsonl"


def build_cover(
    *,
    patterns_path: Path = DEFAULT_PATTERNS_PATH,
    model_dir: Path = SINGLE_MODEL_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    unresolved_path: Path = DEFAULT_UNRESOLVED_PATH,
    top_k: int = 300,
    max_templates: int = 8,
    enable_fallback: bool = True,
    allowed_weekdays: frozenset[int] | None = None,
    allowed_periods: frozenset[int] | None = None,
) -> dict[str, Any]:
    all_patterns = _read_jsonl(patterns_path)
    remaining_by_key = {str(pattern["source_key"]): pattern for pattern in all_patterns}
    templates: list[dict[str, Any]] = []
    iteration_reports: list[dict[str, Any]] = []
    all_unresolved: list[dict[str, Any]] = []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v35_template_cover_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for iteration in range(1, max_templates + 1):
            if not remaining_by_key:
                break
            iteration_patterns = list(remaining_by_key.values())
            iteration_patterns_path = tmp_root / f"patterns_{iteration}.jsonl"
            iteration_template_path = output_path.parent / f"template_cover_v1_template_{iteration}.json"
            iteration_unresolved_path = output_path.parent / f"template_cover_v1_unresolved_{iteration}.jsonl"
            iteration_report_path = output_path.parent / f"template_cover_v1_report_{iteration}.json"
            _write_jsonl(iteration_patterns_path, iteration_patterns)

            report = build_template(
                patterns_path=iteration_patterns_path,
                model_dir=model_dir,
                output_path=iteration_template_path,
                unresolved_path=iteration_unresolved_path,
                report_path=iteration_report_path,
                top_k=top_k,
                repair_depth=0,
                enable_fallback=enable_fallback,
                allowed_weekdays=allowed_weekdays,
                allowed_periods=allowed_periods,
            )
            template_doc = json.loads(iteration_template_path.read_text(encoding="utf-8"))
            template_doc["template_id"] = f"cover_v1_template_{iteration}"
            for fragment in template_doc.get("fragments", []):
                fragment["template_id"] = template_doc["template_id"]
            iteration_template_path.write_text(json.dumps(template_doc, ensure_ascii=False, indent=2), encoding="utf-8")

            completed_keys = _completed_keys(iteration_patterns, template_doc.get("fragments", []))
            placed_keys = {str(fragment.get("source_key")) for fragment in template_doc.get("fragments", [])}
            unresolved_rows = _read_jsonl(iteration_unresolved_path) if iteration_unresolved_path.exists() else []
            all_unresolved = unresolved_rows
            iteration_summary = {
                "iteration": iteration,
                "template_id": template_doc["template_id"],
                "input_task_count": len(iteration_patterns),
                "placed_task_count": len(placed_keys),
                "completed_task_count": len(completed_keys),
                "remaining_task_count": len(iteration_patterns) - len(completed_keys),
                "fragment_count": len(template_doc.get("fragments", [])),
                "unresolved_fragment_count": len(unresolved_rows),
                "fallback_successes": report.get("fallback_successes", 0),
                "template_path": str(iteration_template_path),
                "report_path": str(iteration_report_path),
                "unresolved_path": str(iteration_unresolved_path),
            }
            iteration_reports.append(iteration_summary)
            templates.append(template_doc)

            if not completed_keys:
                break
            for source_key in completed_keys:
                remaining_by_key.pop(source_key, None)

    final_unresolved = [dict(pattern, reason="not_completed_after_cover") for pattern in remaining_by_key.values()]
    _write_jsonl(unresolved_path, final_unresolved)
    cover_doc = {
        "cover_id": "template_cover_v1",
        "template_count": len(templates),
        "templates": templates,
    }
    output_path.write_text(json.dumps(cover_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "cover_id": "template_cover_v1",
        "initial_task_count": len(all_patterns),
        "completed_task_count": len(all_patterns) - len(remaining_by_key),
        "remaining_task_count": len(remaining_by_key),
        "template_count": len(templates),
        "top_k": top_k,
        "max_templates": max_templates,
        "enable_fallback": enable_fallback,
        "iterations": iteration_reports,
        "remaining_preview": final_unresolved[:50],
        "output_path": str(output_path),
        "unresolved_path": str(unresolved_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _completed_keys(patterns: list[dict[str, Any]], fragments: list[dict[str, Any]]) -> set[str]:
    needed = {str(pattern["source_key"]): _safe_int(pattern.get("weekly_slot_count")) for pattern in patterns}
    counts: dict[str, int] = {}
    for fragment in fragments:
        source_key = str(fragment.get("source_key"))
        counts[source_key] = counts.get(source_key, 0) + 1
    return {source_key for source_key, need in needed.items() if counts.get(source_key, 0) >= need}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build iterative V3.5 template cover v1.")
    parser.add_argument("--patterns", default=str(DEFAULT_PATTERNS_PATH))
    parser.add_argument("--model-dir", default=str(SINGLE_MODEL_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--unresolved", default=str(DEFAULT_UNRESOLVED_PATH))
    parser.add_argument("--top-k", type=int, default=300)
    parser.add_argument("--max-templates", type=int, default=8)
    parser.add_argument("--disable-fallback", action="store_true")
    args = parser.parse_args()

    report = build_cover(
        patterns_path=Path(args.patterns),
        model_dir=Path(args.model_dir),
        output_path=Path(args.output),
        report_path=Path(args.report),
        unresolved_path=Path(args.unresolved),
        top_k=args.top_k,
        max_templates=args.max_templates,
        enable_fallback=not args.disable_fallback,
    )
    print(json.dumps({k: v for k, v in report.items() if k not in {"remaining_preview", "iterations"}}, ensure_ascii=False, indent=2))
    print("iterations:")
    for item in report["iterations"]:
        print(json.dumps(item, ensure_ascii=False))
    print(f"output: {args.output}")
    print(f"report: {args.report}")
    print(f"unresolved: {args.unresolved}")


if __name__ == "__main__":
    main()
