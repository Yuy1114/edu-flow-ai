"""在真实课表上跑冲突注入实验：逐类注入已知冲突，要求全部检出、合法课表零误报。

读的是 `bench_scale_promise.py` 产出的真实算例产物（cover + pattern + 教室池），所以
结论对应的是"100 门课程 / 50 间教室"那份课表，而不是构造的小样本。

用法：
    python scripts/audit_conflict_injection.py \
        --cover  backend/data/analysis/promise_scale/phase_cover_promise_run1.json \
        --patterns backend/data/analysis/promise_scale/task_patterns.jsonl \
        --rooms backend/data/analysis/promise_scale/rooms_promise.json \
        --out backend/data/analysis/promise_scale/conflict_injection_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "python"))

from scheduler.conflict_injection import run_injection_experiment  # noqa: E402

DEFAULT_COVER = REPO_ROOT / "backend" / "data" / "analysis" / "promise_scale" / "phase_cover_promise_run1.json"
DEFAULT_COVER_REPORT = REPO_ROOT / "backend" / "data" / "analysis" / "promise_scale" / "cover_report_promise_run1.json"
DEFAULT_PATTERNS = REPO_ROOT / "backend" / "data" / "analysis" / "promise_scale" / "task_patterns.jsonl"
DEFAULT_ROOMS = REPO_ROOT / "backend" / "data" / "analysis" / "promise_scale" / "rooms_promise.json"
DEFAULT_OUT = REPO_ROOT / "backend" / "data" / "analysis" / "promise_scale" / "conflict_injection_report.json"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def room_context(cover: dict, rooms: list[dict]) -> dict:
    return {
        "room_capacity_by_name": {str(room["name"]): int(room.get("capacity") or 0) for room in rooms},
        "room_type_by_name": {str(room["name"]): str(room.get("classroom_type") or "") for room in rooms},
        "all_types": sorted({str(room.get("classroom_type") or "") for room in rooms}),
        "total_weeks": int(cover.get("total_weeks") or 0) or None,
        "automatic_periods": list((cover.get("time_axis") or {}).get("automatic_periods") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Conflict-injection audit on a real cover.")
    parser.add_argument("--cover", default=str(DEFAULT_COVER))
    parser.add_argument("--cover-report", default=str(DEFAULT_COVER_REPORT),
                        help="生成侧的 cover 报告，用来对齐课时守恒读数（conservation_mismatch）")
    parser.add_argument("--patterns", default=str(DEFAULT_PATTERNS))
    parser.add_argument("--rooms", default=str(DEFAULT_ROOMS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    cover = json.loads(Path(args.cover).read_text(encoding="utf-8"))
    patterns = _read_jsonl(Path(args.patterns))
    rooms = json.loads(Path(args.rooms).read_text(encoding="utf-8"))
    context = room_context(cover, rooms)
    cover_report = json.loads(Path(args.cover_report).read_text(encoding="utf-8")) \
        if Path(args.cover_report).exists() else {}

    report = run_injection_experiment(
        cover, patterns=patterns, rooms=context,
        # 课时守恒对齐生成侧：未排任务与"规则表近似"的课时差本来就不该是 0。
        expected_clean={"hour_mismatch": int(cover_report.get("conservation_mismatch") or 0)},
    )
    fragment_count = sum(len(template.get("fragments") or []) for template in cover.get("templates") or [])
    report["source"] = {
        "cover": args.cover,
        "template_count": len(cover.get("templates") or []),
        "fragment_count": fragment_count,
        "pattern_count": len(patterns),
        "room_count": len(rooms),
        "rooms_by_type": dict(Counter(room.get("classroom_type") for room in rooms)),
        "teacher_keys_scope": "cover 片段只带主讲姓名，教师占用按主讲姓名判定（生成侧另有 ID 口径）",
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "source": report["source"],
        "clean_schedule": report["clean_schedule"],
        "false_positives_on_clean_schedule": report["false_positives_on_clean_schedule"],
        "detection_rate": report["detection_rate"],
        "detected": f"{report['detected_count']}/{report['injected_count']}",
        "skipped_count": report["skipped_count"],
        "passed": report["passed"],
        "injections": [
            {"name": item["name"], "expected": item["expected"], "observed": item.get("observed_target"),
             "detected": item["detected"], "side_effects": item.get("side_effects") or {}, "skipped": item.get("skipped")}
            for item in report["injections"]
        ],
        "out": args.out,
    }, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
