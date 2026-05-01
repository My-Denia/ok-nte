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
        task._ensure_daily_main = Mock()
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
        task.task_status = {"success": []}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_called_once_with(
            "每日活跃度缺失特征",
            DailyTask.DAILY_ACTIVITY_MISSING_FEATURES,
        )

    def test_complete_daily_activities_reports_completed_simple_actions(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel = Mock(return_value=True)
        task._claim_visible_activity_missions = Mock(return_value=0)
        task.task_status = {"success": ["领取邮件", "领取环期任务奖励"]}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_has_calls(
            [
                call("每日活跃度已尝试动作", "领取邮件/领取环期任务奖励"),
                call("每日活跃度缺失特征", DailyTask.DAILY_ACTIVITY_MISSING_FEATURES),
            ]
        )

    def test_do_run_claims_simple_rewards_before_activity_reward(self):
        task = object.__new__(DailyTask)
        task.config = {
            "领取邮件": True,
            "领取环期任务奖励": True,
            "完成每日活跃度": True,
            "领取活跃度奖励": True,
        }
        task.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}
        task.current_task_key = None
        task._ensure_daily_main = Mock()
        task.info_set = Mock()
        task.log_info = Mock()

        order = []
        task.claim_mail = Mock(side_effect=lambda: order.append("领取邮件") or True)
        task.claim_battle_pass_rewards = Mock(
            side_effect=lambda: order.append("领取环期任务奖励") or True
        )
        task.complete_daily_activities = Mock(
            side_effect=lambda: order.append("完成每日活跃度") or True
        )
        task.claim_activity_rewards = Mock(
            side_effect=lambda: order.append("领取活跃度奖励") or True
        )

        DailyTask.do_run(task)

        self.assertEqual(
            order,
            ["领取邮件", "领取环期任务奖励", "完成每日活跃度", "领取活跃度奖励"],
        )

    def test_ensure_daily_main_uses_world_features_without_login_ocr(self):
        task = object.__new__(DailyTask)
        task._logged_in = False
        task.wait_until = Mock(return_value=True)
        task.in_team_and_world = Mock()
        task.handle_monthly_card = Mock()
        task.back = Mock()
        task.sleep = Mock()
        task.info_set = Mock()

        result = DailyTask._ensure_daily_main(task)

        self.assertTrue(result)
        self.assertTrue(task._logged_in)
        task.wait_until.assert_called_once()
        _, kwargs = task.wait_until.call_args
        self.assertEqual(kwargs["time_out"], 30)
        self.assertFalse(kwargs["raise_if_not_found"])

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

    def test_claim_activity_rewards_skips_when_no_reward_available(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel = Mock(return_value=True)
        task._claim_visible_activity_missions = Mock(return_value=0)
        task._get_activity_reward_box = Mock(return_value=None)
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.claim_activity_rewards(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_called_once_with(
            "活跃度奖励状态",
            DailyTask.ACTIVITY_REWARD_UNAVAILABLE,
        )
        task.log_info.assert_any_call(DailyTask.ACTIVITY_REWARD_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
