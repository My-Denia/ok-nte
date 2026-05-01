import unittest
from unittest.mock import Mock, PropertyMock, call, patch

import numpy as np

from src.Labels import Labels
from src.tasks.DailyActivityAnalyzer import DailyActivityAnalysis, DailyActivityState
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.DailyTask import DailyTask
from src.tasks.F1PanelDetector import DailyPanelOpenResult


def make_analysis(state=DailyActivityState.UNKNOWN, reason="缺少未完成/前往按钮/可领取状态特征"):
    return DailyActivityAnalysis(
        state=state,
        panel_detected=state != DailyActivityState.PANEL_NOT_FOUND,
        daily_tab_detected=state != DailyActivityState.PANEL_NOT_FOUND,
        activity_full=state == DailyActivityState.NO_ACTION_NEEDED,
        all_daily_done=state == DailyActivityState.NO_ACTION_NEEDED,
        has_go_button=False,
        has_claimable_reward=state == DailyActivityState.HAS_CLAIMABLE_REWARD,
        no_claimable_reward=state != DailyActivityState.HAS_CLAIMABLE_REWARD,
        reason=reason,
    )


def make_open_result(detected=True, reason="每日活跃度面板已识别"):
    return DailyPanelOpenResult(
        f1_panel_opened=True,
        daily_tab_clicked=True,
        daily_activity_panel_detected=detected,
        layout_profile="native_16_9",
        reason=reason,
    )


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
        task.task_skip_reasons = {}
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
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis())
        task._record_daily_activity_analysis = Mock()
        task._claim_visible_activity_missions = Mock(return_value=0)
        task.task_status = {"success": []}
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_called_once_with(
            "每日活跃度缺失特征",
            DailyTask.DAILY_ACTIVITY_MISSING_FEATURES,
        )
        self.assertEqual(
            task.task_skip_reasons["完成每日活跃度"],
            "缺少未完成/前往按钮/可领取状态特征",
        )

    def test_complete_daily_activities_skips_when_activity_done_by_analysis(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(
            return_value=make_analysis(DailyActivityState.NO_ACTION_NEEDED, "今日活跃度已完成")
        )
        task._record_daily_activity_analysis = Mock()
        task._claim_visible_activity_missions = Mock()
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task._claim_visible_activity_missions.assert_not_called()
        self.assertEqual(task.task_skip_reasons["完成每日活跃度"], "今日活跃度已完成")
        task.log_info.assert_any_call("今日活跃度已完成")

    def test_open_activity_panel_clicks_daily_second_tab(self):
        task = object.__new__(DailyTask)
        task.openF1panel = Mock()
        task.click_ui = Mock()
        task.find_one = Mock(return_value=object())
        task.get_ui_layout_profile = Mock(return_value="native_16_9")
        task._executor = Mock(method=Mock(width=2560, height=1440))
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask._open_activity_panel(task)

        self.assertTrue(result)
        task.info_set.assert_any_call("每日活跃度目标栏目", "第2栏目")
        task.click_ui.assert_called_once_with(*DailyTask.DAILY_ACTIVITY_TAB_POSITION, after_sleep=1)

    def test_complete_daily_activities_reports_completed_simple_actions(self):
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._analyze_daily_activity = Mock(return_value=make_analysis())
        task._record_daily_activity_analysis = Mock()
        task._claim_visible_activity_missions = Mock(return_value=0)
        task.task_status = {"success": ["领取邮件", "领取环期任务奖励"]}
        task.task_skip_reasons = {}
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
        task.task_skip_reasons = {}
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
        task._open_activity_panel_result = Mock(return_value=make_open_result())
        task._claim_visible_activity_missions = Mock(return_value=0)
        task._get_activity_reward_box = Mock(return_value=None)
        task.task_skip_reasons = {}
        task.info_set = Mock()
        task.log_info = Mock()

        result = DailyTask.claim_activity_rewards(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        task.info_set.assert_called_once_with(
            "活跃度奖励状态",
            DailyTask.ACTIVITY_REWARD_UNAVAILABLE,
        )
        self.assertEqual(
            task.task_skip_reasons["领取活跃度奖励"],
            DailyTask.ACTIVITY_REWARD_UNAVAILABLE,
        )
        task.log_info.assert_any_call(DailyTask.ACTIVITY_REWARD_UNAVAILABLE)

    def test_daily_task_skips_when_16x10_template_missing(self):
        reason = (
            "当前分辨率为 2560x1600 native_16_10，F1 面板已打开并已点击每日第2栏目，"
            "但 f1_activity_panel 模板未命中；等待 16:10 面板检测适配。"
        )
        task = object.__new__(DailyTask)
        task._open_activity_panel_result = Mock(
            return_value=DailyPanelOpenResult(
                f1_panel_opened=True,
                daily_tab_clicked=True,
                daily_activity_panel_detected=False,
                layout_profile="native_16_10",
                reason=reason,
            )
        )
        task._analyze_daily_activity = Mock()
        task._claim_visible_activity_missions = Mock()
        task.task_skip_reasons = {}
        task.log_info = Mock()

        result = DailyTask.complete_daily_activities(task)

        self.assertIs(result, DailyTask.TASK_SKIPPED)
        self.assertEqual(task.task_skip_reasons["完成每日活跃度"], reason)
        task._analyze_daily_activity.assert_not_called()

    def test_open_esc_panel_does_not_wait_for_settle(self):
        task = object.__new__(DailyTask)
        task.reset_to_false = Mock()
        task.in_team_and_world = Mock(return_value=True)
        task.send_key = Mock()
        task.log_info = Mock()
        task._wait_esc_panel = Mock(return_value=object())
        task._send_foreground_key = Mock()

        DailyTask.openESCpanel(task)

        task._wait_esc_panel.assert_called_once()
        task._send_foreground_key.assert_not_called()

    def test_open_esc_panel_uses_foreground_key_fallback(self):
        task = object.__new__(DailyTask)
        task.reset_to_false = Mock()
        task.in_team_and_world = Mock(return_value=True)
        task.send_key = Mock()
        task.log_info = Mock()
        panel = object()
        task._wait_esc_panel = Mock(side_effect=[None, panel])
        task._send_foreground_key = Mock(return_value=True)

        result = DailyTask.openESCpanel(task)

        self.assertIs(result, panel)
        task._send_foreground_key.assert_called_once_with("esc", after_sleep=1)
        self.assertEqual(task._wait_esc_panel.call_count, 2)

    def test_open_mail_panel_clicks_verified_mail_button_center(self):
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openESCpanel = Mock()
        task.click_ui = Mock()
        task.wait_panel = Mock(return_value=object())

        result = DailyTask._open_mail_panel(task)

        self.assertTrue(result)
        task.openESCpanel.assert_called_once()
        task.click_ui.assert_called_once_with(*DailyTask.MAIL_BUTTON_POSITION, after_sleep=1)
        task.wait_panel.assert_called_once_with(Labels.mail_panel)

    def test_claim_battle_pass_uses_named_positions_and_structure_wait(self):
        task = object.__new__(DailyTask)
        task.log_info = Mock()
        task.openF2panel = Mock()
        task.click_ui = Mock()
        task.sleep = Mock()
        task._wait_battle_pass_mission_panel = Mock(return_value=object())

        result = DailyTask.claim_battle_pass_rewards(task)

        self.assertTrue(result)
        task.openF2panel.assert_called_once()
        task.click_ui.assert_has_calls(
            [
                call(*DailyTask.BATTLE_PASS_REWARD_POSITION),
                call(*DailyTask.BATTLE_PASS_MISSION_TAB_POSITION),
                call(*DailyTask.BATTLE_PASS_CLAIM_POSITION),
            ]
        )
        task._wait_battle_pass_mission_panel.assert_called_once()

    def test_find_battle_pass_mission_panel_prefers_existing_template(self):
        task = object.__new__(DailyTask)
        panel = object()
        task.find_one = Mock(return_value=panel)
        task._find_battle_pass_mission_panel_structure = Mock()

        result = DailyTask._find_battle_pass_mission_panel(task)

        self.assertIs(result, panel)
        task.find_one.assert_called_once_with(Labels.f2_mission_panel)
        task._find_battle_pass_mission_panel_structure.assert_not_called()

    def test_find_battle_pass_mission_panel_detects_selected_task_card(self):
        task = object.__new__(DailyTask)
        frame = np.full((1600, 2560, 3), 40, dtype=np.uint8)
        frame[432:624, 435:870] = (255, 0, 255)
        task.box_of_ui = Mock(return_value="mission_panel")

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=frame):
            result = DailyTask._find_battle_pass_mission_panel_structure(task)

        self.assertEqual(result, "mission_panel")
        task.box_of_ui.assert_called_once()

    def test_find_battle_pass_mission_panel_rejects_unselected_page(self):
        task = object.__new__(DailyTask)
        frame = np.full((1600, 2560, 3), 40, dtype=np.uint8)

        with patch.object(DailyTask, "frame", new_callable=PropertyMock, return_value=frame):
            result = DailyTask._find_battle_pass_mission_panel_structure(task)

        self.assertIsNone(result)

    def test_wait_esc_panel_uses_stricter_threshold(self):
        task = object.__new__(BaseNTETask)
        task._find_esc_panel = Mock(return_value="panel")
        task.wait_until = Mock(return_value="panel")

        result = BaseNTETask._wait_esc_panel(task)

        self.assertEqual(result, "panel")
        condition = task.wait_until.call_args.args[0]
        self.assertEqual(condition(), "panel")
        self.assertEqual(task.wait_until.call_args.kwargs["settle_time"], 0)

    def test_find_esc_panel_prefers_existing_template(self):
        task = object.__new__(BaseNTETask)
        panel = object()
        task.find_one = Mock(return_value=panel)
        task._find_esc_phone_menu = Mock()

        result = BaseNTETask._find_esc_panel(task)

        self.assertIs(result, panel)
        task.find_one.assert_called_once_with(
            Labels.esc_option,
            box=Labels.box_all_esc_options,
            threshold=BaseNTETask.ESC_PANEL_THRESHOLD,
        )
        task._find_esc_phone_menu.assert_not_called()

    def test_find_esc_phone_menu_detects_dark_phone_panel(self):
        task = object.__new__(BaseNTETask)
        frame = np.full((1600, 2560, 3), 220, dtype=np.uint8)
        frame[192:1488, 1792:2508] = 60
        frame[1264:1488, 1792:2508] = 50

        with patch.object(BaseNTETask, "frame", new_callable=PropertyMock, return_value=frame):
            result = BaseNTETask._find_esc_phone_menu(task)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "esc_phone_menu")

    def test_find_esc_phone_menu_rejects_world_frame(self):
        task = object.__new__(BaseNTETask)
        frame = np.full((1600, 2560, 3), 220, dtype=np.uint8)

        with patch.object(BaseNTETask, "frame", new_callable=PropertyMock, return_value=frame):
            result = BaseNTETask._find_esc_phone_menu(task)

        self.assertIsNone(result)

    def test_send_foreground_key_attempts_direct_input_without_foreground_confirmation(self):
        task = object.__new__(BaseNTETask)
        hwnd_window = Mock()
        hwnd_window.is_foreground.return_value = False
        task.bring_to_front = Mock()
        task._send_pydirect_key = Mock(return_value=True)
        task._send_pynput_key = Mock()
        task.sleep = Mock()
        task.log_info = Mock()

        with (
            patch.object(BaseNTETask, "hwnd", new_callable=PropertyMock, return_value=hwnd_window),
            patch("src.tasks.BaseNTETask.time.sleep"),
        ):
            result = BaseNTETask._send_foreground_key(task, "esc", after_sleep=1)

        self.assertTrue(result)
        task._send_pydirect_key.assert_called_once_with("esc", 0.05)
        task._send_pynput_key.assert_not_called()
        task.sleep.assert_called_once_with(1)

    def test_bring_to_front_unwraps_hwnd_window_handle(self):
        task = object.__new__(BaseNTETask)
        hwnd_window = Mock(hwnd=12345)
        task._executor = Mock(device_manager=Mock(hwnd_window=hwnd_window))

        with (
            patch("src.tasks.BaseNTETask.win32api.GetCurrentThreadId", return_value=1),
            patch(
                "src.tasks.BaseNTETask.win32process.GetWindowThreadProcessId",
                return_value=(1, 999),
            ) as get_thread,
            patch("src.tasks.BaseNTETask.win32gui.GetForegroundWindow", return_value=0),
            patch("src.tasks.BaseNTETask.win32gui.IsIconic", return_value=False),
            patch("src.tasks.BaseNTETask.win32gui.BringWindowToTop") as bring_top,
            patch("src.tasks.BaseNTETask.win32gui.SetForegroundWindow") as set_foreground,
        ):
            BaseNTETask.bring_to_front(task)

        get_thread.assert_called_once_with(12345)
        bring_top.assert_called_once_with(12345)
        set_foreground.assert_called_once_with(12345)

    def test_wait_panel_uses_custom_settle_time(self):
        task = object.__new__(BaseNTETask)
        task.find_one = Mock(return_value="panel")
        task.wait_until = Mock(return_value="panel")

        result = BaseNTETask.wait_panel(task, Labels.esc_option, settle_time=0)

        self.assertEqual(result, "panel")
        self.assertEqual(task.wait_until.call_args.kwargs["settle_time"], 0)


if __name__ == "__main__":
    unittest.main()
