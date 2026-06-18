import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.gift import GiftRuntime
from src.tasks.GiftTask import GiftTask


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


class TestGiftRuntimeConfigGate(unittest.TestCase):
    """category 1: config-gate."""

    def test_unsupported_send_count_skips_immediately(self):
        runtime = GiftRuntime(_runtime_task())
        result = runtime.run(send_count=2, allow_real_send=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "unsupported_gift_count")
        self.assertFalse(result["mutation_performed"])

    def test_runtime_default_disables_real_send_before_panel_open(self):
        task = _runtime_task()
        runtime = GiftRuntime(task)
        result = runtime.run()
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "gift_real_send_not_allowed")
        self.assertFalse(result["mutation_performed"])
        task.openF1panel.assert_not_called()
        task.operate_click.assert_not_called()


class TestGiftRuntimeActionGating(unittest.TestCase):
    """category 2: action-gating + post-click verification."""

    def test_panel_open_failure_returns_action_failed(self):
        task = _runtime_task(panel_opened=False)
        runtime = GiftRuntime(task)
        result = runtime.run(allow_real_send=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], "f1_panel_not_opened")
        self.assertFalse(result["mutation_performed"])

    def test_no_gift_card_returns_skipped(self):
        boxes = [_make_box("生命补给", x=200, y=400)]
        task = _runtime_task(ocr_boxes=boxes)
        runtime = GiftRuntime(task)
        result = runtime.run(allow_real_send=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "no_gift_daily_task")
        self.assertFalse(result["mutation_performed"])

    def test_low_confidence_box_blocked_pre_click(self):
        runtime = GiftRuntime(_runtime_task())
        low_conf = _make_box("赠送", x=400, y=600, confidence=0.4)
        details = runtime._click_with_verify(
            low_conf,
            recognized_ui="gift_send_button",
            verifier=lambda: True,
            wait_seconds=0,
        )
        self.assertFalse(details["mutation_performed"])
        self.assertFalse(details["mutation_verified"])
        self.assertEqual(details["reject_reason"], "low_confidence")

    def test_missing_box_blocked_pre_click(self):
        runtime = GiftRuntime(_runtime_task())
        details = runtime._click_with_verify(
            None,
            recognized_ui="gift_default_item",
            verifier=lambda: True,
            wait_seconds=0,
        )
        self.assertFalse(details["mutation_performed"])
        self.assertEqual(details["reject_reason"], "evidence_box_missing")


class TestGiftRuntimeParsing(unittest.TestCase):
    """category 3: parsing-recognition boundaries."""

    def test_gift_card_recognized_when_title_contains_keys(self):
        boxes = [
            _make_box("赠送 1 次礼物", x=300, y=420),
            _make_box("前往", x=900, y=420),
        ]
        runtime = GiftRuntime(_runtime_task(ocr_boxes=boxes))
        card = runtime._find_gift_task_card()
        self.assertIsNotNone(card)
        self.assertIn("赠送", card["title"])

    def test_unrelated_text_not_recognized_as_gift_card(self):
        boxes = [_make_box("赠送收益", x=300, y=420)]
        runtime = GiftRuntime(_runtime_task(ocr_boxes=boxes))
        card = runtime._find_gift_task_card()
        self.assertIsNone(card)

    def test_action_box_only_paired_when_same_row(self):
        title = _make_box("赠送 1 次礼物", x=300, y=420)
        nearby_go = _make_box("前往", x=900, y=440, w=80, h=30)
        far_go = _make_box("前往", x=900, y=900, w=80, h=30)
        boxes = [title, nearby_go, far_go]
        runtime = GiftRuntime(_runtime_task(ocr_boxes=boxes, height=1600))
        card = runtime._find_gift_task_card()
        action_box = runtime._find_card_action_box(card, ("前往",))
        self.assertIsNotNone(action_box)
        self.assertEqual(action_box.y, 440)

    def test_gift_item_click_uses_quantity_box_center(self):
        title = _make_box("赠送 1 次礼物", x=300, y=420)
        go = _make_box("前往", x=900, y=430, w=80, h=30)
        gift_page = [
            _make_box("羁遇", x=100, y=100),
            _make_box("赠礼", x=1700, y=120),
            _make_box("角色喜爱", x=1300, y=520),
            _make_box("今日还能赠送", x=1500, y=520),
        ]
        gift_item = _make_box("300", x=1600, y=800, w=60, h=30)
        send_button = _make_box("赠送", x=1700, y=1300, w=120, h=48)
        task = _runtime_task()
        task.ocr_ui.side_effect = [
            [title],
            [title, go],
            gift_page,
            gift_page,
            gift_page + [gift_item],
            gift_page + [send_button],
            gift_page + [send_button],
            gift_page,
            gift_page,
            gift_page,
            gift_page,
            gift_page,
            gift_page,
            gift_page,
        ]
        runtime = GiftRuntime(task)

        with patch.object(GiftRuntime, "GIFT_PAGE_WAIT_SECONDS", 0.01), patch.object(
            GiftRuntime, "GIFT_SEND_VERIFY_WAIT_SECONDS", 0.3
        ), patch.object(GiftRuntime, "POST_CLICK_SETTLE", 0.01):
            result = runtime.run(allow_real_send=True)

        self.assertTrue(result["ok"])
        self.assertIn(
            ((1630, 815), {"hcenter": False, "vcenter": False}),
            [(call.args, call.kwargs) for call in task.operate_click.call_args_list],
        )


class TestGiftRuntimeMutationSemantics(unittest.TestCase):
    """category 4: mutation/no-op semantics."""

    def test_verifier_pass_marks_mutation_verified(self):
        runtime = GiftRuntime(_runtime_task())
        ok_box = _make_box("前往", x=900, y=440, w=80, h=30, confidence=0.9)
        details = runtime._click_with_verify(
            ok_box,
            recognized_ui="gift_default_item",
            verifier=lambda: True,
            wait_seconds=0.05,
        )
        self.assertTrue(details["mutation_performed"])
        self.assertTrue(details["mutation_verified"])

    def test_verifier_fail_keeps_mutation_unverified(self):
        runtime = GiftRuntime(_runtime_task())
        ok_box = _make_box("赠送", x=900, y=1200, w=80, h=30, confidence=0.9)
        details = runtime._click_with_verify(
            ok_box,
            recognized_ui="gift_send_button",
            verifier=lambda: False,
            wait_seconds=0.05,
        )
        self.assertTrue(details["mutation_performed"])
        self.assertFalse(details["mutation_verified"])

    def test_gift_page_marker_check_short_circuits_when_partial(self):
        boxes = [_make_box("羁遇", x=100, y=100)]
        runtime = GiftRuntime(_runtime_task(ocr_boxes=boxes))
        self.assertFalse(runtime._gift_page_reached())

    def test_send_dispatch_without_post_action_state_change_fails_result(self):
        title = _make_box("赠送 1 次礼物", x=300, y=420)
        go = _make_box("前往", x=900, y=430, w=80, h=30)
        gift_page = [
            _make_box("羁遇", x=100, y=100),
            _make_box("赠礼", x=1700, y=120),
            _make_box("角色喜爱", x=1300, y=520),
            _make_box("今日还能赠送", x=1500, y=520),
        ]
        gift_item = _make_box("300", x=1600, y=800, w=60, h=30)
        send_button = _make_box("赠送", x=1700, y=1300, w=120, h=48)
        task = _runtime_task()
        task.ocr_ui.side_effect = [
            [title],
            [title, go],
            gift_page,
            gift_page,
            gift_page + [gift_item],
            gift_page + [send_button],
            gift_page + [send_button],
        ]
        runtime = GiftRuntime(task)
        with patch.object(GiftRuntime, "GIFT_PAGE_WAIT_SECONDS", 0.01), patch.object(
            GiftRuntime, "GIFT_SEND_VERIFY_WAIT_SECONDS", 0.01
        ):
            result = runtime.run(allow_real_send=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])
        self.assertEqual(result["reason"], "gift_send_post_action_unverified")

    def test_send_completion_requires_stable_post_send_grid(self):
        gift_page = [
            _make_box("羁遇", x=100, y=100),
            _make_box("赠礼", x=1700, y=120),
            _make_box("角色喜爱", x=1300, y=520),
            _make_box("今日还能赠送", x=1500, y=520),
        ]
        task = _runtime_task()
        task.ocr_ui.side_effect = [gift_page, gift_page]
        runtime = GiftRuntime(task)

        self.assertFalse(runtime._gift_send_completion_observed())
        self.assertTrue(runtime._gift_send_completion_observed())

    def test_entry_dispatch_without_post_verification_preserves_performed(self):
        title = _make_box("赠送 1 次礼物", x=300, y=420)
        go = _make_box("前往", x=900, y=430, w=80, h=30)
        task = _runtime_task()
        task.ocr_ui.side_effect = [[title], [title, go], []]
        runtime = GiftRuntime(task)
        with patch.object(GiftRuntime, "GIFT_PAGE_WAIT_SECONDS", 0.01):
            result = runtime.run(allow_real_send=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], "gift_page_not_reached")
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])

    def test_item_dispatch_without_post_verification_preserves_performed(self):
        title = _make_box("赠送 1 次礼物", x=300, y=420)
        go = _make_box("前往", x=900, y=430, w=80, h=30)
        gift_page = [
            _make_box("羁遇", x=100, y=100),
            _make_box("赠礼", x=1700, y=120),
            _make_box("角色喜爱", x=1300, y=520),
            _make_box("今日还能赠送", x=1500, y=520),
        ]
        gift_item = _make_box("300", x=1600, y=800, w=60, h=30)
        task = _runtime_task()
        task.ocr_ui.side_effect = [
            [title],
            [title, go],
            gift_page,
            gift_page,
            gift_page + [gift_item],
            gift_page + [gift_item],
        ]
        runtime = GiftRuntime(task)
        with patch.object(GiftRuntime, "GIFT_PAGE_WAIT_SECONDS", 0.01), patch.object(
            GiftRuntime, "GIFT_TAB_WAIT_SECONDS", 0.01
        ):
            result = runtime.run(allow_real_send=True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["action_failed"])
        self.assertEqual(result["reason"], "gift_item_not_found")
        self.assertTrue(result["mutation_performed"])
        self.assertFalse(result["mutation_verified"])

    def test_full_runtime_success_requires_observed_post_send_state(self):
        title = _make_box("赠送 1 次礼物", x=300, y=420)
        go = _make_box("前往", x=900, y=430, w=80, h=30)
        gift_page = [
            _make_box("羁遇", x=100, y=100),
            _make_box("赠礼", x=1700, y=120),
            _make_box("角色喜爱", x=1300, y=520),
            _make_box("今日还能赠送", x=1500, y=520),
        ]
        gift_item = _make_box("300", x=1600, y=800, w=60, h=30)
        send_button = _make_box("赠送", x=1700, y=1300, w=120, h=48)
        task = _runtime_task()
        task.ocr_ui.side_effect = [
            [title],
            [title, go],
            gift_page,
            gift_page,
            gift_page + [gift_item],
            gift_page + [send_button],
            gift_page + [send_button],
            gift_page,
            gift_page,
            gift_page,
            gift_page,
            gift_page,
            gift_page,
            gift_page,
        ]
        runtime = GiftRuntime(task)
        with patch.object(GiftRuntime, "GIFT_PAGE_WAIT_SECONDS", 0.01), patch.object(
            GiftRuntime, "GIFT_SEND_VERIFY_WAIT_SECONDS", 0.3
        ), patch.object(GiftRuntime, "POST_CLICK_SETTLE", 0.01):
            result = runtime.run(allow_real_send=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["mutation_performed"])
        self.assertTrue(result["mutation_verified"])
        self.assertTrue(result["task_completed"])
        self.assertEqual(result["reason"], "gift_send_clicked")

    def test_confirm_button_success_requires_positive_grid_evidence(self):
        task = _runtime_task()
        confirm = _make_box("确认", x=1400, y=900, w=100, h=40)
        gift_page = [
            _make_box("角色喜爱", x=1300, y=520),
            _make_box("今日还能赠送", x=1500, y=520),
        ]
        task.ocr_ui.side_effect = [[confirm], gift_page]
        runtime = GiftRuntime(task)
        with patch.object(GiftRuntime, "POST_CLICK_SETTLE", 0.01):
            details = runtime._confirm_if_present()
        self.assertIsNotNone(details)
        self.assertTrue(details["mutation_performed"])
        self.assertTrue(details["mutation_verified"])

    def test_confirm_button_empty_ocr_is_unverified(self):
        task = _runtime_task()
        confirm = _make_box("确认", x=1400, y=900, w=100, h=40)
        task.ocr_ui.side_effect = [[confirm], []]
        runtime = GiftRuntime(task)
        with patch.object(GiftRuntime, "POST_CLICK_SETTLE", 0.01):
            details = runtime._confirm_if_present()
        self.assertIsNotNone(details)
        self.assertTrue(details["mutation_performed"])
        self.assertFalse(details["mutation_verified"])

    def test_confirm_button_remaining_is_unverified(self):
        task = _runtime_task()
        confirm = _make_box("确认", x=1400, y=900, w=100, h=40)
        task.ocr_ui.return_value = [confirm]
        runtime = GiftRuntime(task)
        with patch.object(GiftRuntime, "POST_CLICK_SETTLE", 0.01):
            details = runtime._confirm_if_present()
        self.assertIsNotNone(details)
        self.assertTrue(details["mutation_performed"])
        self.assertFalse(details["mutation_verified"])


class TestGiftRuntimeRegression(unittest.TestCase):
    """category 5: regression-risk."""

    def test_empty_ocr_does_not_raise(self):
        runtime = GiftRuntime(_runtime_task(ocr_boxes=[]))
        result = runtime.run(allow_real_send=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])

    def test_smoke_import_gift_task(self):
        from src.tasks.GiftTask import GiftTask as ImportedGiftTask  # noqa: F401

    def test_unrecognized_legacy_keys_do_not_raise(self):
        # Defaults already empty; do_run reads only the two CONF keys.
        with patch.object(GiftTask, "__init__", return_value=None):
            task = GiftTask()
        task.config = {
            "送出礼物": False,                       # earlier candidate name
            "daily_task_only": True,                  # integrate-era key
            GiftTask.CONF_SEND_GIFT: False,
        }
        task.log_info = Mock()
        task.log_error = Mock()
        ret = GiftTask.do_run(task)
        self.assertTrue(ret)


class TestGiftTaskConfigDefaults(unittest.TestCase):
    def test_supported_languages_is_zh_cn_only(self):
        self.assertEqual(GiftTask.supported_languages, ["zh_CN"])

    def test_defaults_disabled(self):
        # Inspect class-level defaults by reading source of __init__'s default_config.update
        # without actually constructing the OneTimeTask hierarchy.
        with patch.object(GiftTask, "__init__", return_value=None):
            inst = GiftTask()
        inst.default_config = {}
        inst.config_description = {}
        inst.config_type = {}
        inst.add_exit_after_config = Mock()

        # Re-execute the body of __init__ in a controlled way: call the unbound real __init__
        # via super-bypass is not portable; instead we rely on the design contract that
        # CONF_SEND_GIFT default is False — checked below via do_run gating.
        task = GiftTask.__new__(GiftTask)
        task.config = {}  # missing key
        task.log_info = Mock()
        task.log_error = Mock()
        # Default-disabled: do_run with no config key set must skip without raising.
        ret = GiftTask.do_run(task)
        self.assertTrue(ret)
        task.log_info.assert_called()

    def test_disabled_skips_runtime(self):
        with patch.object(GiftTask, "__init__", return_value=None):
            task = GiftTask()
        task.config = {GiftTask.CONF_SEND_GIFT: False}
        task.log_info = Mock()
        task.log_error = Mock()
        ret = GiftTask.do_run(task)
        self.assertTrue(ret)
        task.log_info.assert_called()

    def test_none_config_skips_runtime(self):
        task = GiftTask.__new__(GiftTask)
        task.config = None
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.GiftTask.GiftRuntime") as runtime_cls:
            ret = GiftTask.do_run(task)
        self.assertTrue(ret)
        runtime_cls.assert_not_called()


class TestGiftRuntimeOcrFallback(unittest.TestCase):
    """ocr_ui 缺失时回退到 task.ocr (对齐 src/coffee/runtime.py 的 _task_ocr)."""

    def test_ocr_full_screen_uses_task_ocr_when_ocr_ui_absent(self):
        task = _runtime_task()
        task.ocr_ui = None  # 真机 BaseTask 无 ocr_ui
        task.ocr = Mock(return_value=[_make_box("赠送")])
        runtime = GiftRuntime(task)

        boxes = runtime._ocr_full_screen()

        task.ocr.assert_called_once()
        self.assertEqual([b.text for b in boxes], ["赠送"])

    def test_ocr_full_screen_empty_when_no_ocr_method(self):
        task = _runtime_task()
        task.ocr_ui = None
        task.ocr = None
        runtime = GiftRuntime(task)

        self.assertEqual(runtime._ocr_full_screen(), [])

    def test_enabled_task_passes_explicit_runtime_permission(self):
        task = GiftTask.__new__(GiftTask)
        task.config = {GiftTask.CONF_SEND_GIFT: True, GiftTask.CONF_SEND_COUNT: 1}
        task.log_info = Mock()
        task.log_error = Mock()
        with patch("src.tasks.GiftTask.GiftRuntime") as runtime_cls:
            runtime = runtime_cls.return_value
            runtime.run.return_value = {
                "ok": True,
                "task_completed": True,
                "reason": "gift_send_verified",
            }
            ret = GiftTask.do_run(task)
        self.assertTrue(ret)
        runtime.run.assert_called_once_with(send_count=1, allow_real_send=True)


if __name__ == "__main__":
    unittest.main()
