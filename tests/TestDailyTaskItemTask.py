import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.daily_items import DailyTaskItemRuntime
from src.tasks.DailyTaskItemTask import DailyTaskItemTask


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


def _runtime_task(ocr_boxes=None, panel_opened=True, width=2560, height=1600):
    task = Mock()
    task.config = {}
    task.width = width
    task.height = height
    task.ocr_ui = Mock(return_value=list(ocr_boxes or []))
    task.openF1panel = Mock()
    task.operate_click = Mock()
    task.sleep = Mock()
    task.wait_panel = Mock(return_value=True)
    task.find_one = Mock(return_value=None)
    task.retry_on_action = Mock(side_effect=lambda action, recover: action() if panel_opened else False)
    task.ensure_main = Mock()
    task.log_info = Mock()
    task.log_error = Mock()
    return task


class TestDailyTaskItemRuntimeConfigGate(unittest.TestCase):
    """category 1: config-gate."""

    def test_runtime_default_disables_before_panel_open(self):
        boxes = [
            _make_box("赠送 1 次礼物", x=300, y=420),
            _make_box("领取", x=900, y=420),
        ]
        task = _runtime_task(ocr_boxes=boxes)
        runtime = DailyTaskItemRuntime(task)
        result = runtime.run(max_claims=1)
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["claimed_count"], 0)
        self.assertEqual(result["reason"], "daily_task_item_claim_not_allowed")
        task.openF1panel.assert_not_called()
        task.operate_click.assert_not_called()

    def test_zero_max_claims_skips_before_panel_open_when_enabled(self):
        task = _runtime_task(
            ocr_boxes=[
                _make_box("赠送 1 次礼物", x=300, y=420),
                _make_box("领取", x=900, y=420),
            ]
        )
        runtime = DailyTaskItemRuntime(task)
        result = runtime.run(max_claims=0, allow_real_claim=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claimed_count"], 0)
        self.assertEqual(result["reason"], "max_claims_not_positive")
        task.openF1panel.assert_not_called()
        task.operate_click.assert_not_called()


class TestDailyTaskItemRuntimeActionGating(unittest.TestCase):
    """category 2: action-gating."""

    def test_panel_open_failure(self):
        task = _runtime_task(panel_opened=False)
        runtime = DailyTaskItemRuntime(task)
        result = runtime.run(allow_real_claim=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], "f1_panel_not_opened")

    def test_no_claim_button_returns_no_op(self):
        boxes = [_make_box("拍照任务", x=200, y=300)]
        runtime = DailyTaskItemRuntime(_runtime_task(ocr_boxes=boxes))
        result = runtime.run(allow_real_claim=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "no_claimable_completed_task_item")
        self.assertFalse(result["mutation_performed"])

    def test_low_confidence_blocked_pre_click(self):
        runtime = DailyTaskItemRuntime(_runtime_task())
        details = runtime._click_with_verify(
            _make_box("领取", x=900, y=420, confidence=0.4),
            recognized_ui="daily_task_item_claim",
            verifier=lambda: True,
            wait_seconds=0,
        )
        self.assertFalse(details["mutation_performed"])
        self.assertEqual(details["reject_reason"], "low_confidence")


class TestDailyTaskItemRuntimeParsing(unittest.TestCase):
    """category 3: parsing-recognition."""

    def test_card_paired_with_same_row_claim_button(self):
        title = _make_box("拍照任务", x=300, y=420)
        same_row_btn = _make_box("领取", x=900, y=435, w=80, h=30)
        far_row_btn = _make_box("领取", x=900, y=900, w=80, h=30)
        boxes = [title, same_row_btn, far_row_btn]
        runtime = DailyTaskItemRuntime(_runtime_task(ocr_boxes=boxes, height=1600))
        card = runtime._first_claimable_card()
        self.assertIsNotNone(card)
        self.assertEqual(card["action_box"].y, 435)

    def test_nearby_progress_text_is_not_paired_as_card_title(self):
        progress = _make_box("1/1", x=760, y=420)
        same_row_btn = _make_box("领取", x=900, y=435, w=80, h=30)
        boxes = [progress, same_row_btn]
        runtime = DailyTaskItemRuntime(_runtime_task(ocr_boxes=boxes, height=1600))
        self.assertIsNone(runtime._first_claimable_card())

    def test_card_with_no_claim_button_is_skipped(self):
        title = _make_box("拍照任务", x=300, y=420)
        runtime = DailyTaskItemRuntime(_runtime_task(ocr_boxes=[title]))
        self.assertIsNone(runtime._first_claimable_card())


class TestDailyTaskItemRuntimeMutation(unittest.TestCase):
    """category 4: mutation/no-op semantics."""

    def test_single_card_mvp_claims_then_stops(self):
        # Only one claimable card; after click, button disappears.
        title = _make_box("拍照任务", x=300, y=420)
        button = _make_box("领取", x=900, y=435, w=80, h=30)
        task = _runtime_task(ocr_boxes=[title, button], height=1600)
        # First scan: card present. Subsequent scans (verifier and re-poll): card gone.
        scans = [[title, button], [title], []]

        def ocr(*_a, **_kw):
            return scans.pop(0) if scans else []

        task.ocr_ui = Mock(side_effect=ocr)
        runtime = DailyTaskItemRuntime(task)
        result = runtime.run(max_claims=3, allow_real_claim=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claimed_count"], 1)
        self.assertTrue(result["task_completed"])
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])

    def test_post_click_verifier_failure_returns_action_failed(self):
        title = _make_box("拍照任务", x=300, y=420)
        button = _make_box("领取", x=900, y=435, w=80, h=30)
        task = _runtime_task(ocr_boxes=[title, button], height=1600)
        # Every scan returns the same boxes -> button never disappears.
        task.ocr_ui = Mock(return_value=[title, button])
        runtime = DailyTaskItemRuntime(task)
        result = runtime.run(max_claims=3, allow_real_claim=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], "claim_post_action_verification_failed")
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])

    def test_post_click_empty_ocr_is_not_verified(self):
        title = _make_box("拍照任务", x=300, y=420)
        button = _make_box("领取", x=900, y=435, w=80, h=30)
        task = _runtime_task(height=1600)
        task.ocr_ui = Mock(side_effect=[[title, button], []])
        runtime = DailyTaskItemRuntime(task)
        runtime.CLAIM_VERIFY_TIMEOUT = 0.01

        result = runtime.run(max_claims=1, allow_real_claim=True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], "claim_post_action_verification_failed")
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])

    def test_second_claim_failure_does_not_verify_top_level_result(self):
        first_title = _make_box("拍照任务", x=300, y=420)
        first_button = _make_box("领取", x=900, y=435, w=80, h=30)
        second_title = _make_box("赠送 1 次礼物", x=300, y=620)
        second_button = _make_box("领取", x=900, y=635, w=80, h=30)
        first_scan = [first_title, first_button, second_title, second_button]
        first_verified = [first_title, second_title, second_button]
        second_scan = [second_title, second_button]
        scans = [first_scan, first_verified, second_scan]

        def ocr(*_a, **_kw):
            if scans:
                return scans.pop(0)
            return second_scan

        task = _runtime_task(height=1600)
        task.ocr_ui = Mock(side_effect=ocr)
        runtime = DailyTaskItemRuntime(task)
        runtime.CLAIM_VERIFY_TIMEOUT = 0.01

        result = runtime.run(max_claims=2, allow_real_claim=True)

        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["claimed_count"], 1)
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])
        self.assertEqual(len(result["actions"]), 2)
        self.assertTrue(result["actions"][0]["mutation_verified"])
        self.assertFalse(result["actions"][1]["mutation_verified"])


class TestDailyTaskItemRuntimeRegression(unittest.TestCase):
    """category 5: regression-risk."""

    def test_supported_languages_is_zh_cn_only(self):
        self.assertEqual(DailyTaskItemTask.supported_languages, ["zh_CN"])

    def test_empty_ocr_does_not_raise(self):
        runtime = DailyTaskItemRuntime(_runtime_task(ocr_boxes=[]))
        result = runtime.run(allow_real_claim=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["task_completed"])

    def test_smoke_import_task(self):
        from src.tasks.DailyTaskItemTask import DailyTaskItemTask as _Imported  # noqa: F401

    def test_disabled_skips_runtime(self):
        with patch.object(DailyTaskItemTask, "__init__", return_value=None):
            task = DailyTaskItemTask()
        task.config = {}
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.DailyTaskItemTask.DailyTaskItemRuntime") as runtime_cls:
            ret = DailyTaskItemTask.do_run(task)
        self.assertTrue(ret)
        task.log_info.assert_called()
        runtime_cls.assert_not_called()

    def test_none_config_skips_runtime(self):
        with patch.object(DailyTaskItemTask, "__init__", return_value=None):
            task = DailyTaskItemTask()
        task.config = None
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.DailyTaskItemTask.DailyTaskItemRuntime") as runtime_cls:
            ret = DailyTaskItemTask.do_run(task)
        self.assertTrue(ret)
        runtime_cls.assert_not_called()

    def test_enabled_task_passes_explicit_runtime_permission(self):
        with patch.object(DailyTaskItemTask, "__init__", return_value=None):
            task = DailyTaskItemTask()
        task.config = {
            DailyTaskItemTask.CONF_CLAIM_TASK_ITEMS: True,
            DailyTaskItemTask.CONF_MAX_CLAIMS: "7",
        }
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.DailyTaskItemTask.DailyTaskItemRuntime") as runtime_cls:
            runtime = runtime_cls.return_value
            runtime.run.return_value = {"ok": True, "task_completed": True, "claimed_count": 2}
            ret = DailyTaskItemTask.do_run(task)
        self.assertTrue(ret)
        runtime_cls.assert_called_once_with(task)
        runtime.run.assert_called_once_with(max_claims=7, allow_real_claim=True)

    def test_enabled_task_preserves_zero_max_claims_no_op(self):
        with patch.object(DailyTaskItemTask, "__init__", return_value=None):
            task = DailyTaskItemTask()
        task.config = {
            DailyTaskItemTask.CONF_CLAIM_TASK_ITEMS: True,
            DailyTaskItemTask.CONF_MAX_CLAIMS: 0,
        }
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.DailyTaskItemTask.DailyTaskItemRuntime") as runtime_cls:
            runtime = runtime_cls.return_value
            runtime.run.return_value = {
                "ok": True,
                "task_completed": False,
                "reason": "max_claims_not_positive",
            }
            ret = DailyTaskItemTask.do_run(task)
        self.assertTrue(ret)
        runtime.run.assert_called_once_with(max_claims=0, allow_real_claim=True)


class TestDailyTaskItemOcrFallback(unittest.TestCase):
    """ocr_ui 缺失时回退到 task.ocr (对齐 src/coffee/runtime.py 的 _task_ocr)."""

    def test_ocr_full_screen_uses_task_ocr_when_ocr_ui_absent(self):
        task = _runtime_task()
        task.ocr_ui = None
        task.ocr = Mock(return_value=[_make_box("领取")])
        runtime = DailyTaskItemRuntime(task)

        boxes = runtime._ocr_full_screen()

        task.ocr.assert_called_once()
        self.assertEqual([b.text for b in boxes], ["领取"])


if __name__ == "__main__":
    unittest.main()
