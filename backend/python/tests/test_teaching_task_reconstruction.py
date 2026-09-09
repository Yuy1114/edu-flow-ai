"""从分班课表还原教学任务的契约。

Excel 是一个班一份课表，合班课会在每个参与班的课表里各出现一次。还原错了有
两种方向，代价都很大：合过头，会把两个平行班的独立授课并成一个任务；合不够，
同一次课被数 N 遍，容量和课时统计跟着错 N 倍。
"""

from __future__ import annotations

import unittest

from ingest.build_teaching_tasks import _group_into_tasks, _merge_into_sessions


def occurrence(
    *,
    class_name: str,
    course_code: str = "B317",
    course_name: str = "BIM应用技术",
    classroom: str = "92404",
    week: str = "1",
    day: str = "4",
    period: str = "1",
    teacher: str = "王锋",
) -> dict[str, str]:
    return {
        "source_semester": "2023-2024学年1学期总课表",
        "source_schedule": f"{class_name}课表",
        "class_name": class_name,
        "course_code": course_code,
        "course_name": course_name,
        "classroom_name": classroom,
        "day_of_week": day,
        "period_index": period,
        "consecutive_slots": "2",
        "week_index": week,
        "teacher_name": teacher,
    }


class SessionMergeTest(unittest.TestCase):
    def test_the_same_lesson_seen_from_two_class_files_is_one_session(self) -> None:
        sessions = _merge_into_sessions([
            occurrence(class_name="2021级工程管理1班"),
            occurrence(class_name="2021级工程管理2班"),
        ])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["class_count"], 2)
        self.assertEqual(
            sessions[0]["class_names"],
            "2021级工程管理1班,2021级工程管理2班",
        )

    def test_the_same_course_in_different_rooms_stays_two_sessions(self) -> None:
        """平行班同一时刻各自上课，是两次授课，不是合班。"""
        sessions = _merge_into_sessions([
            occurrence(class_name="甲班", classroom="92404"),
            occurrence(class_name="乙班", classroom="92405"),
        ])
        self.assertEqual(len(sessions), 2)
        self.assertEqual({item["class_count"] for item in sessions}, {1})

    def test_a_different_period_stays_a_separate_session(self) -> None:
        sessions = _merge_into_sessions([
            occurrence(class_name="甲班", period="1"),
            occurrence(class_name="甲班", period="3"),
        ])
        self.assertEqual(len(sessions), 2)

    def test_teacher_is_not_part_of_the_key_but_disagreement_is_recorded(self) -> None:
        """同课同室同时刻不可能是两次课。教师名不一致要留痕，不能据此拆事件。"""
        sessions = _merge_into_sessions([
            occurrence(class_name="甲班", teacher="付涛"),
            occurrence(class_name="乙班", teacher="邓杨桦"),
        ])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["teacher_count"], 2)
        self.assertEqual(sessions[0]["teacher_name_conflict"], "true")


class TaskGroupingTest(unittest.TestCase):
    SEMESTER = "2023-2024学年1学期总课表"
    COURSES = {
        (SEMESTER, "B317"): {"course_type": "理论课", "course_name": "BIM应用技术",
                             "required_room_type": "普通教室"},
    }
    SIZES = {(SEMESTER, "甲班"): 30, (SEMESTER, "乙班"): 27}

    def _tasks(self, occurrences: list[dict[str, str]]):
        sessions = _merge_into_sessions(occurrences)
        tasks, _ = _group_into_tasks(sessions, self.COURSES, self.SIZES)
        return tasks

    def test_a_joint_task_carries_both_classes_and_their_combined_size(self) -> None:
        """合班要的教室得装得下两个班之和，所以人数按班级求和。"""
        tasks = self._tasks([
            occurrence(class_name="甲班"),
            occurrence(class_name="乙班"),
        ])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["class_count"], 2)
        self.assertEqual(tasks[0]["is_joint_class"], "true")
        self.assertEqual(tasks[0]["student_count_total"], 57)
        self.assertEqual(tasks[0]["student_count_complete"], "true")

    def test_different_class_sets_are_different_tasks(self) -> None:
        """同一门课的多个平行班是互不相干的教学任务，不能并成一个。"""
        tasks = self._tasks([
            occurrence(class_name="甲班", classroom="92404"),
            occurrence(class_name="乙班", classroom="92405"),
        ])
        self.assertEqual(len(tasks), 2)
        self.assertEqual({task["is_joint_class"] for task in tasks}, {"false"})

    def test_a_missing_class_size_is_flagged_rather_than_guessed(self) -> None:
        tasks = self._tasks([
            occurrence(class_name="甲班"),
            occurrence(class_name="丙班"),
        ])
        self.assertEqual(tasks[0]["student_count_complete"], "false")
        self.assertEqual(tasks[0]["student_count_total"], 30)

    def test_sessions_of_one_task_are_counted_once_not_per_class(self) -> None:
        """两个班各一行、同一次课：session_count 必须是 1，不是 2。"""
        tasks = self._tasks([
            occurrence(class_name="甲班", week="1"),
            occurrence(class_name="乙班", week="1"),
            occurrence(class_name="甲班", week="2"),
            occurrence(class_name="乙班", week="2"),
        ])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["session_count"], 2)
        self.assertEqual(tasks[0]["total_periods"], 4)


if __name__ == "__main__":
    unittest.main()
