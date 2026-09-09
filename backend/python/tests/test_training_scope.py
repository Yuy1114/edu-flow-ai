"""可训练范围的判定契约。

第二阶段只学常规课堂排课。历史课表里混着集中实践、团队授课和不支持的课程
类型，它们都是真数据但不是"常规排课行为"。判错的代价是不对称的：漏掉一门
正常课只是少些样本，放进一门整周占满的课程设计，模型会学到"铺满一整周"
是合法落位。
"""

from __future__ import annotations

import unittest

from ingest.label_training_scope import _judge_task


def occurrences(
    *,
    weeks: dict[int, int],
    teachers: str = "张老师",
) -> list[dict[str, str]]:
    """按 {周次: 该周上课次数} 造出一组 occurrence。"""
    rows: list[dict[str, str]] = []
    for week, sessions in weeks.items():
        for _ in range(sessions):
            rows.append({"week_index": str(week), "teacher_name": teachers})
    return rows


def theory(name: str = "高等数学") -> dict[str, str]:
    return {"course_type": "理论课", "course_name": name}


def lab(name: str = "大学物理实验") -> dict[str, str]:
    return {"course_type": "上机课", "course_name": name}


class RegularCourseTest(unittest.TestCase):
    def test_a_weekly_theory_course_is_trainable(self) -> None:
        verdict = _judge_task(theory(), occurrences(weeks={w: 2 for w in range(1, 17)}))
        self.assertEqual(verdict["trainable"], "true")
        self.assertEqual(verdict["rhythm_class"], "regular")
        self.assertEqual(verdict["untrainable_reason"], "")

    def test_a_twice_weekly_lab_is_not_mistaken_for_concentrated_practice(self) -> None:
        """实验课一次连上 4 节。判定必须按"每周几次"，不能按占用节次数，
        否则每周两次的实验课会被当成一周八节的集中实践误伤。"""
        verdict = _judge_task(lab(), occurrences(weeks={w: 2 for w in range(1, 13)}))
        self.assertEqual(verdict["trainable"], "true")
        self.assertEqual(verdict["peak_sessions_per_week"], 2)


class ConcentratedPracticeTest(unittest.TestCase):
    def test_a_week_filling_block_is_excluded(self) -> None:
        """周一到周五每天两大节、只持续两周，是集中实践而不是常规课。"""
        verdict = _judge_task(theory("水电站设计"), occurrences(weeks={1: 10, 2: 10}))
        self.assertEqual(verdict["trainable"], "false")
        self.assertEqual(verdict["rhythm_class"], "block")
        self.assertIn("整周块状占用", verdict["untrainable_reason"])

    def test_a_practice_named_course_is_excluded_whatever_its_rhythm(self) -> None:
        """名称判定和节奏判定互为补充：有的课程设计节奏看着很正常。"""
        verdict = _judge_task(theory("机械设计课程设计"), occurrences(weeks={1: 2, 2: 2}))
        self.assertEqual(verdict["rhythm_class"], "regular")
        self.assertEqual(verdict["trainable"], "false")
        self.assertEqual(verdict["untrainable_reason"], "集中实践类课程")

    def test_an_intensive_rhythm_is_held_for_a_human(self) -> None:
        """6-7 次/周里正常密集课和实践课都有，不自动归类。"""
        verdict = _judge_task(theory(), occurrences(weeks={w: 6 for w in range(1, 8)}))
        self.assertEqual(verdict["rhythm_class"], "intensive")
        self.assertEqual(verdict["trainable"], "false")
        self.assertIn("高频节奏待人工确认", verdict["untrainable_reason"])


class TeacherIdentityTest(unittest.TestCase):
    def test_a_lecturer_and_assistant_are_split_and_kept(self) -> None:
        verdict = _judge_task(theory(), occurrences(weeks={1: 2}, teachers="曹瑞翔,乔鹏程"))
        self.assertEqual(verdict["trainable"], "true")
        self.assertEqual(verdict["primary_teacher"], "曹瑞翔")
        self.assertEqual(verdict["assistant_teachers"], "乔鹏程")

    def test_a_teaching_team_cannot_carry_a_preference(self) -> None:
        """九个人的组合没有"避开早课"可言；留着它会污染教师画像。"""
        verdict = _judge_task(theory(), occurrences(weeks={1: 2}, teachers="甲,乙,丙,丁"))
        self.assertEqual(verdict["teacher_count"], 4)
        self.assertEqual(verdict["trainable"], "false")
        self.assertIn("团队授课", verdict["untrainable_reason"])


class UnsupportedTypeTest(unittest.TestCase):
    def test_a_course_type_outside_the_engine_is_excluded(self) -> None:
        verdict = _judge_task(
            {"course_type": "实践课", "course_name": "军事训练"},
            occurrences(weeks={1: 2}),
        )
        self.assertEqual(verdict["trainable"], "false")
        self.assertIn("不在本阶段支持范围", verdict["untrainable_reason"])


if __name__ == "__main__":
    unittest.main()
