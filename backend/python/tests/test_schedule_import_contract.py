"""导入链路的领域契约测试。

课表是"周 × 星期 × 大节"的网格。这一层最容易出的错是把大节当成一个原子小节、
或者把网格本来就说清楚的教学节奏丢掉，两者都不会报错，只会让下游的课时算错。
"""

from __future__ import annotations

import unittest

from ingest.apply_import_review import _categorize, _importable_pattern
from ingest.parse_schedule_excel import (
    Cell,
    Occurrence,
    _clean_course_name,
    _derive_pattern,
    _extract_occurrences,
    _is_non_teaching_marker,
    _parse_timetable_cell,
    _span_from_column_header,
    _split_period_annotation,
    _trainable_verdict,
)


def occurrence(code: str, week: int, day: int = 1, period: int = 1, span: int = 2) -> Occurrence:
    return Occurrence(
        class_name="软工1班", course_code=code, classroom_name="A101",
        day_of_week=day, period_index=period, consecutive_slots=span,
        week_index=week, row_index=week + 4, col_index=3,
        sheet_name="推荐课表", raw_cell="",
    )


class BlockSpanTest(unittest.TestCase):
    def test_day_blocks_carry_their_real_length(self) -> None:
        self.assertEqual(_span_from_column_header("12"), 2)
        self.assertEqual(_span_from_column_header("34"), 2)
        self.assertEqual(_span_from_column_header("56"), 2)
        self.assertEqual(_span_from_column_header("78"), 2)

    def test_the_evening_block_is_three_periods(self) -> None:
        """晚上 19:10-21:35 是三节，不是两节；按两节算会漏掉第 11 节。"""
        self.assertEqual(_span_from_column_header("91011"), 3)
        self.assertEqual(_span_from_column_header("9、10、11"), 3)


class DerivedPatternTest(unittest.TestCase):
    def test_a_regular_course_yields_its_weekly_rhythm(self) -> None:
        occurrences = [occurrence("C1", week) for week in range(1, 9)]
        occurrences += [occurrence("C1", week, day=3) for week in range(1, 9)]

        pattern = _derive_pattern("C1", occurrences)

        self.assertEqual(pattern["sessions_per_week"], 2)
        self.assertEqual(pattern["duration_weeks"], 8)
        self.assertEqual(pattern["session_slots"], 2)
        self.assertEqual(pattern["observed_hours"], 32)
        self.assertEqual(pattern["pattern_regular"], "true")
        self.assertEqual(pattern["pattern_source"], "timetable")

    def test_uneven_weeks_are_reported_as_irregular_not_averaged(self) -> None:
        """有的周停课，各周次数不同。取众数可以，但必须标成不规则交人工确认。"""
        occurrences = [occurrence("C2", 1), occurrence("C2", 1, day=3), occurrence("C2", 2)]

        pattern = _derive_pattern("C2", occurrences)

        self.assertEqual(pattern["pattern_regular"], "false")
        self.assertEqual(pattern["duration_weeks"], 2)
        self.assertEqual(pattern["observed_hours"], 6)

    def test_active_weeks_are_kept_exactly_not_as_a_range(self) -> None:
        occurrences = [occurrence("C3", week) for week in (1, 2, 5, 9)]

        self.assertEqual(_derive_pattern("C3", occurrences)["active_weeks"], "1,2,5,9")

    def test_a_course_without_occurrences_reports_no_pattern(self) -> None:
        self.assertEqual(_derive_pattern("C4", [])["sessions_per_week"], "")


class CourseNameTest(unittest.TestCase):
    def test_class_size_annotation_from_the_previous_course_is_stripped(self) -> None:
        """课程说明连排成一行，`【专】48人` 是上一门课的标注，会粘到下一门课名前面。"""
        self.assertEqual(_clean_course_name("【专】48人游戏策划与运营"), "游戏策划与运营")
        self.assertEqual(_clean_course_name("48人计算机图形学"), "计算机图形学")

    def test_a_clean_name_is_left_alone(self) -> None:
        self.assertEqual(_clean_course_name("Linux操作系统"), "Linux操作系统")


class ImportablePatternTest(unittest.TestCase):
    def base(self, **overrides) -> dict[str, str]:
        row = {"sessions_per_week": "2", "duration_weeks": "8", "session_slots": "2",
               "observed_hours": "32", "pattern_regular": "true"}
        row.update(overrides)
        return row

    def test_a_self_consistent_rhythm_is_written_to_the_task(self) -> None:
        pattern = _importable_pattern(self.base(), 32)

        self.assertEqual(pattern["sessions_per_week"], 2)
        self.assertEqual(pattern["duration_weeks"], 8)

    def test_declared_hours_disagreeing_with_the_timetable_leaves_the_rhythm_empty(self) -> None:
        """真实数据里约四成任务对不上。写入一个不自洽的 pattern 会让课时审计一开始就错。"""
        pattern = _importable_pattern(self.base(), 40)

        self.assertIsNone(pattern["sessions_per_week"])
        self.assertIn("不一致", pattern["note"])

    def test_an_irregular_rhythm_is_left_to_a_human(self) -> None:
        pattern = _importable_pattern(self.base(pattern_regular="false"), 32)

        self.assertIsNone(pattern["sessions_per_week"])
        self.assertIn("不规则", pattern["note"])

    def test_a_rhythm_that_does_not_multiply_out_is_refused(self) -> None:
        pattern = _importable_pattern(self.base(sessions_per_week="3"), 32)

        self.assertIsNone(pattern["sessions_per_week"])
        self.assertIn("不自洽", pattern["note"])


class TrainableVerdictTest(unittest.TestCase):
    def course(self, **overrides) -> dict[str, object]:
        row = {"schedulable": "true", "exclude_reason": "", "required_hours": "32"}
        row.update(overrides)
        return row

    def pattern(self, **overrides) -> dict[str, object]:
        row = {"sessions_per_week": 2, "observed_hours": 32, "pattern_regular": "true"}
        row.update(overrides)
        return row

    def test_a_clean_course_is_trainable(self) -> None:
        verdict = _trainable_verdict(self.course(), self.pattern())

        self.assertEqual(verdict["trainable"], "true")
        self.assertEqual(verdict["untrainable_reason"], "")

    def test_an_unschedulable_course_is_not_training_data(self) -> None:
        """毕业实习这类课程由虚拟教师带、不占常规教室，学不出排课行为。"""
        verdict = _trainable_verdict(
            self.course(schedulable="false", exclude_reason="毕业实习无需排课"), self.pattern())

        self.assertEqual(verdict["trainable"], "false")
        self.assertIn("毕业实习", verdict["untrainable_reason"])

    def test_hours_that_disagree_with_the_timetable_need_a_human_first(self) -> None:
        verdict = _trainable_verdict(self.course(), self.pattern(observed_hours=48))

        self.assertEqual(verdict["trainable"], "false")
        self.assertIn("48", verdict["untrainable_reason"])

    def test_an_irregular_rhythm_needs_a_human_first(self) -> None:
        verdict = _trainable_verdict(self.course(), self.pattern(pattern_regular="false"))

        self.assertEqual(verdict["trainable"], "false")


class ImportOutcomeTest(unittest.TestCase):
    def test_the_five_categories_separate_a_human_skip_from_a_system_anomaly(self) -> None:
        """跳过是人工说"不动"，异常是系统没能应用。混成一类，异常就看不见了。"""
        review_items = [{"review_type": "conflict"}, {"review_type": "conflict"}, {"review_type": "new_item"}]
        plan = [
            {"action": "create:course"},
            {"action": "update:classroom.capacity"},
            {"action": "keep_db:classroom"},
            {"action": "ignore:course"},
        ]
        skipped = [{"reason": "dependencies not resolved"}]

        outcome = _categorize(review_items, plan, skipped)

        self.assertEqual(outcome, {
            "created": 1, "updated": 1, "conflicts": 2, "anomalies": 1, "skipped": 2,
        })


if __name__ == "__main__":
    unittest.main()


class EveningSubRangeTest(unittest.TestCase):
    """晚间大节是三节，但只上两节的课在格子里写成 高166(9-10)。

    这个标注曾经让整条记录消失：课程代码带上括号后匹配不了 COURSE_CODE_PATTERN，
    _parse_timetable_cell 返回空列表，而质量分照样是 100。抽样 120 份历史课表就有
    924 个这样的格子，全部是晚间课——训练集因此一条晚间样本都没有，"避开晚课"
    这类教师偏好永远学不出来。
    """

    def test_annotation_is_stripped_and_kept(self) -> None:
        self.assertEqual(_split_period_annotation("高166(9-10)"), ("高166", (9, 2)))
        self.assertEqual(_split_period_annotation("高166"), ("高166", None))

    def test_annotated_cell_still_yields_the_course(self) -> None:
        self.assertEqual(
            _parse_timetable_cell("高166(9-10)\r\n08203"),
            [("高166", "08203", (9, 2))],
        )

    def test_sub_range_narrows_the_span_inside_the_evening_block(self) -> None:
        """列头说 9-11 共三节，格子说只用 9-10，最终应落成第 9 节起两节。"""
        cells = [Cell(row=5, col=7, value="高166(9-10)\r\n08203")]
        occurrences, unparsed, non_teaching = _extract_occurrences(
            cells, "推荐课表", "软工1班", {}, {}, {7: (1, 9, 3)},
        )
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0].period_index, 9)
        self.assertEqual(occurrences[0].consecutive_slots, 2)
        self.assertEqual((unparsed, non_teaching), ([], []))

    def test_unannotated_evening_cell_keeps_all_three_periods(self) -> None:
        cells = [Cell(row=5, col=7, value="高166\r\n08203")]
        occurrences, _, _ = _extract_occurrences(
            cells, "推荐课表", "软工1班", {}, {}, {7: (1, 9, 3)},
        )
        self.assertEqual(occurrences[0].period_index, 9)
        self.assertEqual(occurrences[0].consecutive_slots, 3)

    def test_sub_range_outside_the_block_defers_to_the_column_header(self) -> None:
        """标注和列头冲突时以列头为准，不能让一个坏标注把课排到别的大节去。"""
        cells = [Cell(row=5, col=7, value="高166(1-2)\r\n08203")]
        occurrences, _, _ = _extract_occurrences(
            cells, "推荐课表", "软工1班", {}, {}, {7: (1, 9, 3)},
        )
        self.assertEqual(occurrences[0].period_index, 9)
        self.assertEqual(occurrences[0].consecutive_slots, 3)


class GridDropVisibilityTest(unittest.TestCase):
    """解析不出来的格子必须留下痕迹。静默丢弃是最贵的失败方式。"""

    def test_exam_and_holiday_cells_are_not_parse_failures(self) -> None:
        for marker in ["考试", "期末考试", "国庆节", "报到注册", "运动会"]:
            self.assertTrue(_is_non_teaching_marker(marker), marker)
        self.assertFalse(_is_non_teaching_marker("高166"))

    def test_unexplained_cell_is_recorded_rather_than_dropped(self) -> None:
        cells = [
            Cell(row=5, col=7, value="考试"),
            Cell(row=6, col=7, value="某种没见过的东西"),
        ]
        occurrences, unparsed, non_teaching = _extract_occurrences(
            cells, "推荐课表", "软工1班", {}, {}, {7: (1, 9, 3)},
        )
        self.assertEqual(occurrences, [])
        self.assertEqual([item["value"] for item in non_teaching], ["考试"])
        self.assertEqual([item["value"] for item in unparsed], ["某种没见过的东西"])
