from __future__ import annotations

import unittest

from app.db.repositories import ensure_default_time_slots


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        if "COUNT(*)" in sql:
            self._result = [{"cnt": self.connection.existing_count}]
            self.rowcount = 1
            return
        self.connection.inserted.append(params)
        self.rowcount = 1

    def fetchall(self):
        return getattr(self, "_result", [])


class FakeConnection:
    def __init__(self):
        self.existing_count = 0
        self.inserted = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


class DbRepositoriesTest(unittest.TestCase):
    def test_ensure_default_time_slots_seeds_empty_table(self):
        conn = FakeConnection()

        inserted = ensure_default_time_slots(conn, weeks=2, weekdays=2, periods=2)

        self.assertEqual(inserted, 8)
        self.assertEqual(len(conn.inserted), 8)
        self.assertEqual(conn.commits, 1)

    def test_ensure_default_time_slots_does_not_modify_existing_table(self):
        conn = FakeConnection()
        conn.existing_count = 3

        inserted = ensure_default_time_slots(conn)

        self.assertEqual(inserted, 0)
        self.assertEqual(conn.inserted, [])
        self.assertEqual(conn.commits, 0)

    def test_default_time_axis_is_eighteen_weeks_by_eleven_atomic_periods(self):
        """晚间是 19:10-21:35 的三节大块，所以一天 11 节而不是 10 节。"""
        conn = FakeConnection()

        inserted = ensure_default_time_slots(conn)

        self.assertEqual(inserted, 18 * 7 * 11)
        self.assertEqual(conn.inserted[0], (1, 1, 1, "第1周 周1 第1节"))
        self.assertEqual(conn.inserted[-1], (18, 7, 11, "第18周 周7 第11节"))


if __name__ == "__main__":
    unittest.main()
