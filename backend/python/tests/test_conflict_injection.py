"""冲突注入实验的单测：逐类注入必须检出，合法课表必须零误报。

用构造的小课表而不是真实 cover，测的是"检测器认不认得出这七类错"这条契约；真实 cover 的
端到端验证在 `scripts/audit_conflict_injection.py` 里跑（那边读真实产物）。
"""

from __future__ import annotations

import unittest

from scheduler.conflict_injection import run_injection_experiment


def _fragment(**overrides):
    fragment = {
        "uid": "T000001",
        "room": "A101",
        "day": 1,
        "start": 1,
        "consecutive": 2,
        "week_mask": [1, 2, 3, 4, 5, 6, 7, 8],
        "teacher_keys": ["张老师"],
        "class_keys": ["2024级软件工程1班"],
        "required_room_type": "普通教室",
        "student_count": 50,
    }
    fragment.update(overrides)
    return fragment


def _cover(fragments):
    return {"templates": [{"template_id": "dynamic_template_01", "fragments": [
        {
            "fragment_id": f"{fragment['uid']}#frag1",
            "source_key": fragment["uid"],
            "classroom_name": fragment["room"],
            "day_of_week": fragment["day"],
            "period_index": fragment["start"],
            "consecutive_slots": fragment["consecutive"],
            "week_mask": fragment["week_mask"],
            "template_week_mask": fragment["week_mask"],
            "teacher_name": fragment["teacher_keys"][0],
            "class_names": ",".join(fragment["class_keys"]),
            "required_room_type": fragment["required_room_type"],
            "student_count": fragment["student_count"],
        }
        for fragment in fragments
    ]}]}


def _pattern(**overrides):
    # 与片段自洽：每周 1 次 × 8 周 × 每次 2 节 = 16 课时。fixture 不自洽的话"合法课表零误报"
    # 这条断言测的就是 fixture 而不是检测器了。
    pattern = {
        "uid": "T000001",
        "session_hours": 2,
        "consecutive_slots": 2,
        "weekly_slot_count": 1,
        "duration_weeks": 8,
        "total_hours": 16,
    }
    pattern.update(overrides)
    return pattern


def _rooms():
    return {
        "room_capacity_by_name": {"A101": 60, "B201": 60},
        "room_type_by_name": {"A101": "普通教室", "B201": "机房"},
        "all_types": ["普通教室", "机房"],
        "total_weeks": 18,
        "automatic_periods": [1, 2, 3, 4, 5, 6, 7, 8],
    }


class ConflictInjectionTest(unittest.TestCase):
    def _run(self, fragments, patterns):
        return run_injection_experiment(_cover(fragments), patterns=patterns, rooms=_rooms())

    def test_a_legal_timetable_has_no_false_positives(self):
        report = self._run([_fragment()], [_pattern()])

        self.assertEqual(report["false_positives_on_clean_schedule"], {})
        self.assertEqual(report["clean_schedule"]["total"], 0)
        self.assertEqual(report["clean_schedule"]["hour_mismatch"], 0)

    def test_every_constraint_class_is_detected(self):
        report = self._run([_fragment()], [_pattern()])

        self.assertEqual(report["skipped_count"], 0)
        self.assertEqual(report["detected_count"], report["injected_count"])
        self.assertEqual(report["detection_rate"], 1.0)
        self.assertTrue(report["passed"])
        self.assertEqual({item["name"] for item in report["injections"]},
                         {"teacher_occupancy", "class_occupancy", "room_occupancy", "room_type", "capacity",
                          "hour_shortage", "hour_excess", "period_axis", "weekday_axis", "week_axis",
                          "automatic_domain"})

    def test_teacher_injection_does_not_only_show_up_as_a_room_conflict(self):
        report = self._run([_fragment()], [_pattern()])
        teacher = next(item for item in report["injections"] if item["name"] == "teacher_occupancy")

        # 计数是"重复占用的坐标数"（8 周 × 2 连续节 = 16 处），不是片段数。
        self.assertGreaterEqual(teacher["observed_target"]["teacher"], 1)
        self.assertNotIn("class", teacher["side_effects"])
        self.assertNotIn("room", teacher["side_effects"])

    def test_hour_shortage_is_reported_as_a_shortage_not_an_excess(self):
        report = self._run([_fragment()], [_pattern()])
        shortage = next(item for item in report["injections"] if item["name"] == "hour_shortage")

        self.assertGreaterEqual(shortage["observed_target"]["hour_mismatch"], 1)
        self.assertTrue(shortage["detected"])

    def test_an_empty_cover_is_reported_as_unusable_instead_of_silently_passing(self):
        report = self._run([], [_pattern()])

        # 没有可注入的片段时必须显式跳过，而不是报"检出率 100%"。
        self.assertGreater(report["skipped_count"], 0)
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
