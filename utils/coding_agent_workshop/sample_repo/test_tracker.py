"""TASK-001's regression tests; two deliberately fail in the starter app."""

import unittest
from datetime import date

from tracker import overdue_tasks


class OverdueTasksTests(unittest.TestCase):
    today = date(2026, 1, 15)

    def test_unfinished_past_task_is_overdue(self):
        task = {"id": "a", "due": "2026-01-14", "completed": False}
        self.assertEqual(overdue_tasks([task], self.today), [task])

    def test_due_today_is_not_overdue(self):
        task = {"id": "b", "due": "2026-01-15", "completed": False}
        self.assertEqual(overdue_tasks([task], self.today), [])

    def test_completed_task_is_not_overdue(self):
        task = {"id": "c", "due": "2026-01-10", "completed": True}
        self.assertEqual(overdue_tasks([task], self.today), [])

    def test_future_task_is_not_overdue(self):
        task = {"id": "d", "due": "2026-01-16", "completed": False}
        self.assertEqual(overdue_tasks([task], self.today), [])


if __name__ == "__main__":
    unittest.main()
