from __future__ import annotations

import json
import unittest

from scheduler.fetch_allocation_teaching_tasks import (
    _parse_unavailable_matrix,
    _resource_issues,
)


class FormalInputContractTest(unittest.TestCase):
    def test_malformed_availability_is_rejected_instead_of_becoming_fully_available(self) -> None:
        with self.assertRaisesRegex(ValueError, "5x7, 10x7 or 11x7"):
            _parse_unavailable_matrix(7, json.dumps([[0] * 6 for _ in range(10)]))
        with self.assertRaisesRegex(ValueError, "only accepts"):
            _parse_unavailable_matrix(7, json.dumps([[0] * 7 for _ in range(9)] + [[0, 0, 0, 0, 0, 0, 2]]))

    def test_inactive_bound_teaching_task_is_a_hard_issue(self) -> None:
        row = {
            "teaching_task_status": "INACTIVE",
            "course_status": "ACTIVE",
            "primary_teacher_status": "ACTIVE",
            "candidate_classroom_link_count": 0,
            "active_candidate_classroom_count": 0,
        }
        task = {
            "teaching_task_id": 9,
            "primary_teacher_id": 3,
            "class_group_ids": [5],
        }

        hard, warnings = _resource_issues(row, task)

        self.assertEqual([issue["issue"] for issue in hard], ["inactive_teaching_task"])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
