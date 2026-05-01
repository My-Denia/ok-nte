import unittest
from unittest.mock import Mock, call

from src.tasks.DailyTask import DailyTask


class TestDailyTask(unittest.TestCase):
    def make_task(self):
        task = object.__new__(DailyTask)
        task.config = {"测试任务": True}
        task.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": ["测试任务"],
        }
        task.current_task_key = None
        task.ensure_main = Mock()
        task.screenshot = Mock()
        task.log_info = Mock()
        return task

    def test_execute_task_records_runtime_skip(self):
        task = self.make_task()

        task.execute_task("测试任务", Mock(return_value=DailyTask.TASK_SKIPPED))

        self.assertEqual(task.task_status["success"], [])
        self.assertEqual(task.task_status["failed"], [])
        self.assertEqual(task.task_status["skipped"], ["测试任务"])
        self.assertEqual(task.task_status["pending"], [])
        self.assertIsNone(task.current_task_key)

    def test_execute_task_resets_current_task_after_failure(self):
        task = self.make_task()

        task.execute_task("测试任务", Mock(return_value=False))

        self.assertEqual(task.task_status["failed"], ["测试任务"])
        self.assertIsNone(task.current_task_key)
        task.screenshot.assert_called_once_with("fail_测试任务")

    def test_complete_daily_activities_skips_when_no_claimable_mission(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel = Mock(return_value=True)
        task._claim_visible_activity_missions = Mock(return_value=0)
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_called_once_with(
            "每日活跃度缺失特征",
            DailyTask.DAILY_ACTIVITY_MISSING_FEATURES,
        )

    def test_claim_visible_activity_missions_clicks_until_missing(self):
        task = object.__new__(DailyTask)
        first_target = object()
        second_target = object()
        task.find_one = Mock(side_effect=[first_target, second_target, None])
        task.click = Mock()
        task.sleep = Mock()

        claimed = DailyTask._claim_visible_activity_missions(task, max_clicks=5)

        self.assertEqual(claimed, 2)
        task.click.assert_has_calls([call(first_target), call(second_target)])
        self.assertEqual(task.sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
