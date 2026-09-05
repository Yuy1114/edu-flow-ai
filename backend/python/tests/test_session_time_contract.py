from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scheduler.pattern_builder import build_patterns
from scheduler.validate_patterns import validate


class SessionTimeContractTest(unittest.TestCase):
    def test_room_type_does_not_change_session_duration(self) -> None:
        tasks = [
            {
                "source_key": "theory-in-computer-room",
                "course_type": "理论课",
                "required_room_type": "机房",
                "total_hours": 32,
                "class_name": "A",
            },
            {
                "source_key": "experiment-in-ordinary-room",
                "course_type": "实验课",
                "required_room_type": "普通教室",
                "total_hours": 32,
                "class_name": "B",
            },
        ]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tasks.jsonl"
            patterns_path = root / "patterns.jsonl"
            source.write_text(
                "".join(json.dumps(task, ensure_ascii=False) + "\n" for task in tasks),
                encoding="utf-8",
            )
            build_patterns(
                input_path=source,
                output_path=patterns_path,
                dropped_path=root / "dropped.jsonl",
                report_path=root / "pattern-report.json",
            )
            patterns = {
                row["source_key"]: row
                for row in (
                    json.loads(line)
                    for line in patterns_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            }
            report = validate(
                input_path=patterns_path,
                report_path=root / "validation-report.json",
            )

        self.assertEqual(patterns["theory-in-computer-room"]["consecutive_slots"], 2)
        self.assertEqual(patterns["experiment-in-ordinary-room"]["consecutive_slots"], 4)
        self.assertEqual(report["invalid_count"], 0, report["invalid_preview"])


if __name__ == "__main__":
    unittest.main()
