from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scheduler.clean_training_samples import _drop_reasons
from scheduler.placement_single_model import TIME_AXIS_VERSION, V35SinglePlacementModel


class PlacementModelTimeAxisTest(unittest.TestCase):
    def test_training_cleaner_accepts_tenth_atomic_period_and_rejects_eleventh(self) -> None:
        base = {
            "source_key": "task:1",
            "resource_key": "A101|1|10",
            "course_name": "课程",
            "course_code": "C1",
            "class_name": "班级1",
            "required_room_type": "普通教室",
            "classroom_name": "A101",
            "classroom_type": "普通教室",
            "course_type": "理论课",
            "day_of_week": 1,
            "period_index": 10,
        }
        self.assertNotIn("invalid_period_index", _drop_reasons(base))
        self.assertIn("invalid_period_index", _drop_reasons({**base, "period_index": 11}))

    def test_legacy_model_without_atomic_time_contract_is_rejected_before_loading(self) -> None:
        with TemporaryDirectory() as directory:
            model_dir = Path(directory)
            (model_dir / "placement_single_meta.json").write_text(
                json.dumps({"model_path": "/old/absolute/model.txt"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, TIME_AXIS_VERSION):
                V35SinglePlacementModel.load(model_dir)


if __name__ == "__main__":
    unittest.main()
