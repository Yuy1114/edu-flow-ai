"""方案级画像满足度的落库契约：导出写文件、导入按列插入、计数校验。

这里用假连接而不是真 MySQL：要验的是"列名对得上、表在截断清单里、
计数校验能发现差异"这三件代码契约，真 MySQL 留给容器栈上的端到端验收。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scheduler.export_template_cover_db_draft import export_db_draft
from scheduler.import_db_draft_to_mysql import TABLE_FILES, import_draft
from scheduler.pattern_builder import build_patterns
from scheduler.phase_scheduler import build_phase_cover
from scheduler.teacher_preferences import build_index, satisfaction_report, template_satisfaction_rows
from scheduler.validate_db_draft_export import validate_export

SATISFACTION_TABLE = "schedule_teacher_satisfaction"


class _FakeCursor:
    def __init__(self, state: dict) -> None:
        self.state = state
        self._result: list[dict] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params=None) -> None:
        self.state["statements"].append((sql, params))
        normalized = " ".join(sql.split())
        if normalized.upper().startswith("SHOW TABLES"):
            self._result = [{"Tables_in_test": name} for name in self.state["tables"]]
            return
        if normalized.upper().startswith("SELECT LAST_INSERT_ID"):
            self.state["last_id"] += 1
            self._result = [{"id": self.state["last_id"]}]
            return
        match = re.search(r"SELECT COUNT\(\*\) AS count FROM (\w+)", normalized)
        if match:
            self._result = [{"count": self.state["inserted"].get(match.group(1), 0)}]
            return
        if normalized.upper().startswith("DELETE FROM"):
            self.state["deleted"].append(normalized.split()[2])
            return
        insert = re.match(r"INSERT INTO (\w+) \(([^)]*)\)", normalized)
        if insert:
            self.state["inserted"][insert.group(1)] = self.state["inserted"].get(insert.group(1), 0) + 1
            self.state["insert_columns"][insert.group(1)] = [
                column.strip() for column in insert.group(2).split(",")
            ]

    def fetchall(self) -> list[dict]:
        return self._result

    def executemany(self, sql: str, values) -> None:
        for params in values:
            self.execute(sql, params)

    def fetchone(self) -> dict:
        return self._result[0] if self._result else {}


class _FakeConnection:
    def __init__(self, tables: list[str]) -> None:
        self.state = {
            "tables": tables,
            "statements": [],
            "inserted": {},
            "insert_columns": {},
            "deleted": [],
            "last_id": 0,
        }

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.state)

    def commit(self) -> None:
        self.state["committed"] = True

    def rollback(self) -> None:
        self.state["rolled_back"] = True

    def close(self) -> None:
        return None


def _draft(root: Path, *, preferences: dict | None) -> Path:
    """跑真实的 pattern → cover → 导出链路，产出一份 db_draft 目录。"""
    source = root / "tasks.jsonl"
    patterns_path = root / "patterns.jsonl"
    rooms_path = root / "rooms.json"
    source.write_text(json.dumps({
        "source_key": "t1", "course_name": "操作系统", "course_type": "理论课",
        "teacher_name": "张老师", "class_names": "一班", "required_room_type": "普通教室",
        "total_hours": 8, "sessions_per_week": 1, "duration_weeks": 4, "student_count": 30,
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    rooms_path.write_text(json.dumps([
        {"id": 1, "name": "A101", "classroom_type": "普通教室", "capacity": 60, "status": "ACTIVE"},
    ], ensure_ascii=False), encoding="utf-8")
    build_patterns(
        input_path=source, output_path=patterns_path,
        dropped_path=root / "dropped.jsonl", report_path=root / "pattern_report.json",
    )
    cover_path = root / "cover.json"
    cover_report = build_phase_cover(
        patterns_path=patterns_path,
        output_path=cover_path,
        report_path=root / "cover_report.json",
        unresolved_path=root / "unresolved.jsonl",
        phase_weeks=(4,),
        rooms_path=rooms_path,
        use_model=False,
        teacher_preferences=preferences,
    )
    draft_dir = root / "db_draft"
    export_db_draft(
        cover_path=cover_path,
        output_dir=draft_dir,
        allocation_task_id=7,
        total_weeks=4,
        generation_run_id="v35-7-test",
        rooms_path=rooms_path,
        profile_satisfaction_templates=cover_report.get("profile_satisfaction_templates"),
    )
    return draft_dir


def _rows(draft_dir: Path) -> list[dict]:
    path = draft_dir / "schedule_teacher_satisfaction.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class SatisfactionExportTest(unittest.TestCase):
    def test_rows_are_written_per_template_and_teacher(self) -> None:
        with TemporaryDirectory() as directory:
            draft_dir = _draft(Path(directory), preferences={"张老师": {"avoid_early_period": True}})
            rows = _rows(draft_dir)
            template_codes = {
                json.loads(line)["template_code"]
                for line in (draft_dir / "schedule_templates.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            }

        self.assertTrue(rows)
        self.assertTrue({row["template_code"] for row in rows} <= template_codes)
        self.assertEqual({row["teacher_name"] for row in rows}, {"张老师"})
        for row in rows:
            self.assertEqual(row["allocation_task_id"], 7)
            self.assertEqual(row["generation_run_id"], "v35-7-test")
            self.assertTrue(0.0 <= row["satisfaction_score"] <= 1.0)
            self.assertTrue(0.0 <= row["preference_score"] <= 1.0)
            self.assertEqual(json.loads(row["declared_dimensions_json"]), ["early_period"])
            self.assertIn("early_period", json.loads(row["components_json"]))
            self.assertIn(row["low_satisfaction"], (0, 1))
            self.assertEqual(row["low_satisfaction"], 1 if row["preference_score"] < 0.7 else 0)
            self.assertEqual(row["teacher_key"], "name:张老师")

    def test_an_empty_file_is_written_when_no_teacher_has_a_profile(self) -> None:
        with TemporaryDirectory() as directory:
            draft_dir = _draft(Path(directory), preferences=None)
            path = draft_dir / "schedule_teacher_satisfaction.jsonl"

            self.assertTrue(path.exists(), "一张表一个文件的契约：没有画像也要有空文件")
            self.assertEqual(_rows(draft_dir), [])


class SatisfactionImportTest(unittest.TestCase):
    def test_import_inserts_the_rows_under_the_declared_columns(self) -> None:
        with TemporaryDirectory() as directory:
            draft_dir = _draft(Path(directory), preferences={"张老师": {"avoid_early_period": True}})
            expected_rows = len(_rows(draft_dir))
            connection = _FakeConnection(sorted(TABLE_FILES))
            report = import_draft(input_dir=draft_dir, execute=True, truncate=True, connection=connection)

            self.assertEqual(report["status"], "inserted")
            self.assertEqual(report["persisted_counts"][SATISFACTION_TABLE], expected_rows)
            self.assertIn(SATISFACTION_TABLE, connection.state["deleted"])
            self.assertEqual(
                connection.state["insert_columns"][SATISFACTION_TABLE],
                [
                    "allocation_task_id", "generation_run_id", "template_code", "teacher_key", "teacher_id",
                    "teacher_name", "item_count", "days_used", "satisfaction_score", "preference_score",
                    "low_satisfaction", "declared_dimensions_json", "components_json", "evidence_json",
                ],
            )

    def test_a_folder_missing_the_new_table_is_reported_not_silently_imported(self) -> None:
        with TemporaryDirectory() as directory:
            draft_dir = _draft(Path(directory), preferences={"张老师": {"avoid_early_period": True}})
            connection = _FakeConnection(sorted(set(TABLE_FILES) - {SATISFACTION_TABLE}))
            report = import_draft(input_dir=draft_dir, execute=False, connection=connection)

            self.assertEqual(report["status"], "missing_tables")
            self.assertEqual(report["missing_tables"], [SATISFACTION_TABLE])


class SatisfactionValidationTest(unittest.TestCase):
    def test_a_clean_draft_raises_no_satisfaction_issue(self) -> None:
        with TemporaryDirectory() as directory:
            draft_dir = _draft(Path(directory), preferences={"张老师": {"avoid_early_period": True}})
            report = validate_export(input_dir=draft_dir, report_path=Path(directory) / "validation.json")

            self.assertEqual(report["counts"]["teacher_satisfaction"], len(_rows(draft_dir)))
            satisfaction_issues = [
                issue for issue in report["issues_preview"]
                if issue["issue"] in {
                    "missing_reference", "duplicate_teacher_satisfaction", "score_out_of_range",
                    "non_positive_item_count", "invalid_low_satisfaction_flag", "missing_teacher_name",
                } and issue.get("row_type", "teacher_satisfaction") == "teacher_satisfaction"
            ]
            self.assertEqual(satisfaction_issues, [])

    def test_a_tampered_row_is_reported_before_it_reaches_the_database(self) -> None:
        with TemporaryDirectory() as directory:
            draft_dir = _draft(Path(directory), preferences={"张老师": {"avoid_early_period": True}})
            path = draft_dir / "schedule_teacher_satisfaction.jsonl"
            rows = _rows(draft_dir)
            broken = dict(rows[0])
            broken["preference_score"] = 1.4
            broken["item_count"] = 0
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows + [rows[0], broken]) + "\n",
                encoding="utf-8",
            )
            report = validate_export(input_dir=draft_dir, report_path=Path(directory) / "validation.json")

            issue_counts = report["issue_counts"]
            # broken 是 rows[0] 的副本，键相同：加上 rows[0] 自身共 3 行同键 → 2 条重复告警。
            self.assertEqual(issue_counts.get("duplicate_teacher_satisfaction"), 2)
            self.assertEqual(issue_counts.get("score_out_of_range"), 1)
            self.assertEqual(issue_counts.get("non_positive_item_count"), 1)


class SatisfactionNamingTest(unittest.TestCase):
    """片段只带一个 teacher_name（主讲）：助教不能被贴上主讲的名字。"""

    def _fragment(self) -> dict:
        return {
            "fragment_id": "f1", "primary_teacher_id": 11, "assistant_teacher_id": 12,
            "teacher_name": "主讲老师", "day_of_week": 1, "period_index": 3,
            "consecutive_slots": 2, "classroom_name": "A101", "week_mask": [1],
        }

    def test_only_the_teacher_a_fragment_names_gets_that_name(self) -> None:
        index = build_index({"11": {"preferred_weekdays": [1]}, "12": {"preferred_weekdays": [1]}})
        report = satisfaction_report(index=index, fragments=[self._fragment()])

        self.assertEqual(
            {teacher["teacher_key"]: teacher["teacher_name"] for teacher in report["teachers"]},
            {"id:11": "主讲老师", "id:12": None},
        )

    def test_the_export_fills_the_assistant_name_from_task_metadata(self) -> None:
        index = build_index({"11": {"preferred_weekdays": [1]}, "12": {"preferred_weekdays": [1]}})
        report = satisfaction_report(index=index, fragments=[self._fragment()])

        rows = template_satisfaction_rows(
            {"dynamic_template_01": report},
            allocation_task_id=1,
            generation_run_id="run-1",
            teacher_names_by_id={12: "助教老师"},
        )

        self.assertEqual(
            {row["teacher_key"]: row["teacher_name"] for row in rows},
            {"id:11": "主讲老师", "id:12": "助教老师"},
        )
        # 没有元数据时退回 key，也不能把主讲的名字安到助教头上。
        fallback = template_satisfaction_rows(
            {"dynamic_template_01": report}, allocation_task_id=1, generation_run_id="run-1",
        )
        self.assertEqual(
            {row["teacher_key"]: row["teacher_name"] for row in fallback},
            {"id:11": "主讲老师", "id:12": "id:12"},
        )


if __name__ == "__main__":
    unittest.main()
