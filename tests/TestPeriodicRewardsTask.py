import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.periodic_rewards import PeriodicRewardsRuntime
from src.tasks.DailyTask import DailyTask
from src.tasks.PeriodicRewardsTask import PeriodicRewardsTask


def _make_box(text, x=0, y=0, w=40, h=20, confidence=0.95):
    return SimpleNamespace(
        text=text,
        name=text,
        x=x,
        y=y,
        width=w,
        height=h,
        confidence=confidence,
    )


def _runtime_task(ocr_boxes=None, panel_ready=True):
    task = Mock()
    task.config = {}
    task.frame = None
    task.width = 2560
    task.height = 1440
    task.ocr_ui = Mock(return_value=list(ocr_boxes or []))
    task.openF2panel = Mock()
    task.operate_click = Mock()
    task.sleep = Mock()
    task.next_frame = Mock()
    task.wait_panel = Mock(return_value=panel_ready)
    task.find_one = Mock(return_value=None)
    task.retry_on_action = Mock(side_effect=lambda action, recover: action())
    task.ensure_main = Mock()
    task.log_info = Mock()
    task.log_error = Mock()
    return task


class TestPeriodicRewardsRuntimeGate(unittest.TestCase):
    def test_runtime_default_disables_before_panel_open(self):
        task = _runtime_task(ocr_boxes=[_make_box("领取", x=900, y=420)])
        runtime = PeriodicRewardsRuntime(task)

        result = runtime.run()

        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], PeriodicRewardsRuntime.PERIODIC_CLAIM_NOT_ALLOWED)
        task.openF2panel.assert_not_called()
        task.operate_click.assert_not_called()

    def test_panel_open_failure_is_failed_no_claim_action(self):
        task = _runtime_task(panel_ready=False)
        runtime = PeriodicRewardsRuntime(task)

        result = runtime.run(allow_real_claim=True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], PeriodicRewardsRuntime.PERIODIC_PANEL_NOT_FOUND)
        self.assertFalse(result["mutation_performed"])

    def test_no_claimable_reward_is_no_op(self):
        runtime = PeriodicRewardsRuntime(_runtime_task(ocr_boxes=[]))

        result = runtime.run(allow_real_claim=True, claim_reward_track=False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], PeriodicRewardsRuntime.NO_CLAIMABLE_PERIODIC_REWARD)
        self.assertFalse(result["mutation_performed"])

    def test_pre_click_ocr_failure_is_failed_not_no_op(self):
        task = _runtime_task(panel_ready=True)
        task.ocr_ui = Mock(side_effect=RuntimeError("ocr unavailable"))
        runtime = PeriodicRewardsRuntime(task)

        result = runtime.run(allow_real_claim=True, claim_reward_track=False)

        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], PeriodicRewardsRuntime.PERIODIC_REWARD_OCR_UNAVAILABLE)
        self.assertFalse(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])

    def test_low_confidence_blocks_pre_click(self):
        task = _runtime_task()
        runtime = PeriodicRewardsRuntime(task)

        details = runtime._click_with_verify(
            _make_box("领取", x=900, y=420, confidence=0.4),
            reward_type="periodic_mission",
            button_text="领取",
            region=PeriodicRewardsRuntime.MISSION_CLAIM_REGION,
        )

        self.assertFalse(details["mutation_performed"])
        self.assertFalse(details["mutation_verified"])
        self.assertEqual(details["reason"], "low_confidence")
        task.operate_click.assert_not_called()


class TestPeriodicRewardsRuntimeActions(unittest.TestCase):
    def test_individual_claim_success_requires_button_disappear(self):
        title = _make_box("每日任务", x=300, y=420)
        button = _make_box("领取", x=900, y=420, w=80, h=30)
        task = _runtime_task(panel_ready=True)
        task.ocr_ui = Mock(side_effect=[[], [title, button], [], []])
        runtime = PeriodicRewardsRuntime(task)
        runtime.CLAIM_VERIFY_TIMEOUT_SECONDS = 0

        result = runtime.run(
            allow_real_claim=True,
            claim_reward_track=False,
            max_mission_claims=3,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["claimed"])
        self.assertEqual(result["mission_claim_attempts"], 1)
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])
        self.assertTrue(result["task_completed"])

    def test_click_without_post_verification_is_failed_not_success(self):
        button = _make_box("领取", x=900, y=420, w=80, h=30)
        task = _runtime_task(panel_ready=True)
        task.ocr_ui = Mock(side_effect=[[], [button], [button]])
        runtime = PeriodicRewardsRuntime(task)
        runtime.CLAIM_VERIFY_TIMEOUT_SECONDS = 0

        result = runtime.run(
            allow_real_claim=True,
            claim_reward_track=False,
            max_mission_claims=3,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(
            result["reason"],
            PeriodicRewardsRuntime.PERIODIC_REWARD_CLAIM_POST_ACTION_FAILED,
        )
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])
        self.assertFalse(result["task_completed"])

    def test_post_click_ocr_failure_is_not_verified(self):
        button = _make_box("领取", x=900, y=420, w=80, h=30)
        task = _runtime_task(panel_ready=True)
        task.ocr_ui = Mock(side_effect=[[], [button], RuntimeError("ocr unavailable")])
        runtime = PeriodicRewardsRuntime(task)
        runtime.CLAIM_VERIFY_TIMEOUT_SECONDS = 0

        result = runtime.run(
            allow_real_claim=True,
            claim_reward_track=False,
            max_mission_claims=3,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])
        self.assertFalse(result["task_completed"])

    def test_claim_text_matching_boundaries(self):
        self.assertTrue(PeriodicRewardsRuntime._claim_text_matches("领取奖励", "领取"))
        self.assertTrue(PeriodicRewardsRuntime._claim_text_matches("全部领取", "全部领取"))
        self.assertFalse(PeriodicRewardsRuntime._claim_text_matches("已领取", "领取"))
        self.assertFalse(PeriodicRewardsRuntime._claim_text_matches("已全部领取", "全部领取"))


class TestPeriodicRewardsTaskEntrypoint(unittest.TestCase):
    def test_supported_languages_is_zh_cn_only(self):
        self.assertEqual(PeriodicRewardsTask.supported_languages, ["zh_CN"])

    def test_none_config_skips_runtime(self):
        with patch.object(PeriodicRewardsTask, "__init__", return_value=None):
            task = PeriodicRewardsTask()
        task.config = None
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.PeriodicRewardsTask.PeriodicRewardsRuntime") as runtime_cls:
            ret = PeriodicRewardsTask.do_run(task)
        self.assertTrue(ret)
        runtime_cls.assert_not_called()

    def test_missing_config_skips_runtime(self):
        with patch.object(PeriodicRewardsTask, "__init__", return_value=None):
            task = PeriodicRewardsTask()
        task.config = {}
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.PeriodicRewardsTask.PeriodicRewardsRuntime") as runtime_cls:
            ret = PeriodicRewardsTask.do_run(task)
        self.assertTrue(ret)
        runtime_cls.assert_not_called()

    def test_enabled_task_passes_explicit_runtime_permission(self):
        with patch.object(PeriodicRewardsTask, "__init__", return_value=None):
            task = PeriodicRewardsTask()
        task.config = {
            PeriodicRewardsTask.CONF_CLAIM_PERIODIC_REWARDS: True,
            PeriodicRewardsTask.CONF_MAX_MISSION_CLAIMS: "0",
        }
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.PeriodicRewardsTask.PeriodicRewardsRuntime") as runtime_cls:
            runtime = runtime_cls.return_value
            runtime.run.return_value = {
                "ok": True,
                "task_completed": False,
                "reason": PeriodicRewardsRuntime.NO_CLAIMABLE_PERIODIC_REWARD,
            }
            ret = PeriodicRewardsTask.do_run(task)
        self.assertTrue(ret)
        runtime_cls.assert_called_once_with(task)
        runtime.run.assert_called_once_with(max_mission_claims=0, allow_real_claim=True)


class TestDailyTaskPeriodicDelegate(unittest.TestCase):
    def test_daily_task_does_not_import_periodic_runtime(self):
        import importlib

        daily_task_module = importlib.import_module("src.tasks.DailyTask")
        self.assertFalse(hasattr(daily_task_module, "PeriodicRewardsRuntime"))

    def test_daily_task_enabled_periodic_path_keeps_legacy_simple_flow(self):
        task = object.__new__(DailyTask)
        task.config = {DailyTask.CONF_CLAIM_BP: True}
        task.log_info = Mock()
        task.log_error = Mock()
        task.openF2panel = Mock()
        task.operate_click = Mock()
        task.sleep = Mock()
        task.wait_panel = Mock(return_value=True)
        task.ensure_main = Mock()
        task.retry_on_action = Mock(side_effect=lambda action, recover: action())

        ret = DailyTask.claim_battle_pass_rewards(task)

        self.assertTrue(ret)
        task.openF2panel.assert_called_once()
        self.assertEqual(task.operate_click.call_count, 4)

    def test_daily_task_execute_task_missing_periodic_key_skips(self):
        task = object.__new__(DailyTask)
        task.config = {}
        task.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": [DailyTask.CONF_CLAIM_BP],
        }
        task.current_task_key = None
        func = Mock(return_value=True)

        DailyTask.execute_task(task, DailyTask.CONF_CLAIM_BP, False, func)

        func.assert_not_called()
        self.assertIn(DailyTask.CONF_CLAIM_BP, task.task_status["skipped"])
        self.assertNotIn(DailyTask.CONF_CLAIM_BP, task.task_status["pending"])


class TestPeriodicRewardsConfig(unittest.TestCase):
    def test_periodic_rewards_task_is_registered(self):
        from src.config import config

        self.assertIn(
            ["src.tasks.PeriodicRewardsTask", "PeriodicRewardsTask"],
            config["onetime_tasks"],
        )


class TestPeriodicRewardsOcrFallback(unittest.TestCase):
    """ocr_ui 缺失时回退到 task.ocr (对齐 src/coffee/runtime.py 的 _task_ocr)."""

    def test_ocr_region_uses_task_ocr_when_ocr_ui_absent(self):
        task = _runtime_task()
        task.ocr_ui = None
        task.ocr = Mock(return_value=[_make_box("领取", x=900, y=420)])
        runtime = PeriodicRewardsRuntime(task)

        runtime._ocr_region((0, 0, 1, 1))

        task.ocr.assert_called_once()


if __name__ == "__main__":
    unittest.main()
