"""Gift 赠礼运行时. 不依赖 Daily Flow 链, 直接接收 task 对象.

策略 (在 plan v3 M0-extension 中决议为 G2):

* 通过 F1 活跃度面板进入 (``task.openF1panel`` -> 点击日常 tab -> ``wait_panel``).
* 在面板上以 OCR 扫描标题包含 "赠送" 的卡片, 横向找同行的 "前往" 按钮.
* 点击 "前往" 后 OCR 验证进入了角色赠礼页 (``GIFT_PAGE_MARKERS`` 全部命中).
* 在赠礼页内执行 send: 选 tab -> 选第一个礼物 -> 点 "赠送" -> 处理 "确认".

返回的 ``dict`` 与 :mod:`src.coffee.runtime` 风格一致, 用普通键, 不引入 dataclass.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from src.Labels import Labels


_GIFT_TASK_TITLE_KEYS = ("赠送", "礼物")
_GIFT_PAGE_MARKERS = ("羁遇", "赠礼")
_GIFT_GRID_MARKERS = ("角色喜爱", "今日还能赠送")
_GIFT_CONFIRM_TEXTS = ("确认", "确定")
_GIFT_GO_BUTTON_TEXTS = ("前往",)

_F1_DAILY_TAB_POSITION = (0.0551, 0.3833)


class GiftRuntime:
    """Gift runtime that operates via the owning task's UI helpers.

    Returns plain ``dict`` from public methods, mirroring Coffee runtime style.
    """

    GIFT_PAGE_WAIT_SECONDS = 4.0
    GIFT_TAB_WAIT_SECONDS = 2.5
    GIFT_SEND_VERIFY_WAIT_SECONDS = 2.0
    POST_CLICK_SETTLE = 0.6
    OCR_MIN_CONFIDENCE = 0.6

    def __init__(self, task):
        self.task = task
        self.actions: list[dict[str, Any]] = []
        self._post_send_grid_seen = False

    # --------------------------------------------------------------- entrypoint

    def run(self, *, send_count: int = 1, allow_real_send: bool = False) -> dict[str, Any]:
        """Execute one gift-send cycle.

        ``send_count`` currently only supports ``1``. Larger values cause an
        early skip with reason ``unsupported_gift_count`` to keep behaviour
        predictable; the upstream maintainer prefers small features.
        """
        self.actions = []

        if int(send_count or 0) != 1:
            return self._build_result(
                ok=False, skipped=True, reason="unsupported_gift_count"
            )
        if not allow_real_send:
            return self._build_result(
                ok=True, skipped=True, reason="gift_real_send_not_allowed"
            )

        panel_opened = self._open_activity_panel()
        if not panel_opened:
            return self._build_result(
                ok=False, action_failed=True, reason="f1_panel_not_opened"
            )

        gift_card = self._find_gift_task_card()
        if gift_card is None:
            return self._build_result(
                ok=True, skipped=True, reason="no_gift_daily_task"
            )

        gift_action_box = self._find_card_action_box(gift_card, _GIFT_GO_BUTTON_TEXTS)
        if gift_action_box is None:
            return self._build_result(
                ok=True, skipped=True, reason="gift_task_already_completed"
            )

        entry = self._click_with_verify(
            gift_action_box,
            recognized_ui="daily_task_item_gift_go",
            verifier=self._gift_page_reached,
            wait_seconds=self.GIFT_PAGE_WAIT_SECONDS,
        )
        if not entry["mutation_verified"]:
            return self._build_result(
                ok=False, action_failed=True, reason="gift_page_not_reached"
            )

        if not self._ensure_gift_tab_selected():
            return self._build_result(
                ok=False, action_failed=True, reason="gift_page_not_reached"
            )

        item_box = self._first_gift_item_box()
        if item_box is None:
            return self._build_result(
                ok=False, action_failed=True, reason="gift_item_not_found"
            )

        item = self._click_with_verify(
            item_box,
            recognized_ui="gift_default_item",
            verifier=lambda: self._send_button_box() is not None,
            wait_seconds=self.GIFT_TAB_WAIT_SECONDS,
        )
        if not item["mutation_verified"]:
            return self._build_result(
                ok=False, action_failed=True, reason="gift_item_not_found"
            )

        send_box = self._send_button_box()
        if send_box is None:
            return self._build_result(
                ok=False, action_failed=True, reason="gift_send_button_not_found"
            )
        send = self._click_with_verify(
            send_box,
            recognized_ui="gift_send_button",
            verifier=self._gift_send_post_click_state_observed,
            wait_seconds=self.GIFT_SEND_VERIFY_WAIT_SECONDS,
        )
        if not send["mutation_performed"]:
            return self._build_result(
                ok=False, action_failed=True, reason="gift_send_button_not_found"
            )
        if not send["mutation_verified"]:
            return self._build_result(
                ok=False,
                action_failed=True,
                reason="gift_send_post_action_unverified",
                mutation_performed=True,
            )

        confirm = self._confirm_if_present()
        if confirm is not None and not confirm["mutation_verified"]:
            return self._build_result(
                ok=False, action_failed=True, reason="gift_confirm_unverified",
                mutation_performed=True,
            )
        if confirm is None and not self._gift_send_completion_observed():
            return self._build_result(
                ok=False,
                action_failed=True,
                reason="gift_send_post_action_unverified",
                mutation_performed=True,
            )

        return self._build_result(
            ok=True,
            mutation_performed=True,
            mutation_verified=True,
            task_completed=True,
            sent_total=1,
            reason="gift_send_clicked",
        )

    # ----------------------------------------------------------- F1 navigation

    def _open_activity_panel(self) -> bool:
        def action():
            self.task.openF1panel()
            self.task.operate_click(*_F1_DAILY_TAB_POSITION)
            self.task.sleep(0.5)
            return self.task.wait_panel(Labels.f1_activity_panel)

        ensure = getattr(self.task, "ensure_main", lambda: None)
        result = self.task.retry_on_action(action, ensure)
        return bool(result)

    def _find_gift_task_card(self) -> dict[str, Any] | None:
        boxes = list(self._ocr_full_screen())
        for box in boxes:
            text = self._box_text(box)
            if all(key in text for key in _GIFT_TASK_TITLE_KEYS):
                return {
                    "title": text,
                    "title_box": box,
                }
        return None

    def _find_card_action_box(
        self, card: dict[str, Any], action_texts: tuple[str, ...]
    ) -> Any | None:
        title_box = card.get("title_box")
        if title_box is None:
            return None
        anchor_y_center = self._box_center_y(title_box)
        boxes = list(self._ocr_full_screen())
        for box in boxes:
            text = self._box_text(box).strip()
            if text not in action_texts:
                continue
            box_y = self._box_center_y(box)
            if abs(box_y - anchor_y_center) > self._screen_height() * 0.06:
                continue
            return box
        return None

    # ---------------------------------------------------------- gift page work

    def _gift_page_reached(self) -> bool:
        texts = self._ocr_texts()
        return all(any(marker in text for text in texts) for marker in _GIFT_PAGE_MARKERS)

    def _ensure_gift_tab_selected(self) -> bool:
        boxes = list(self._ocr_full_screen())
        if self._has_gift_grid(boxes):
            return True
        tab = self._find_text_box(boxes, "赠礼", min_x_ratio=0.60, max_y_ratio=0.25)
        if tab is None:
            return False
        gate = self._click_with_verify(
            tab,
            recognized_ui="gift_tab",
            verifier=lambda: self._has_gift_grid(list(self._ocr_full_screen())),
            wait_seconds=self.GIFT_TAB_WAIT_SECONDS,
        )
        return bool(gate.get("mutation_verified"))

    def _first_gift_item_box(self) -> Any | None:
        boxes = list(self._ocr_full_screen())
        width = self._screen_width()
        height = self._screen_height()
        candidates = []
        for box in boxes:
            text = self._box_text(box)
            if not text.isdigit():
                continue
            x = int(getattr(box, "x", 0) or 0)
            y = int(getattr(box, "y", 0) or 0)
            if not (width * 0.50 <= x <= width * 0.88 and height * 0.38 <= y <= height * 0.72):
                continue
            confidence = float(getattr(box, "confidence", 1.0) or 0.0)
            if confidence < self.OCR_MIN_CONFIDENCE:
                continue
            value = int(text)
            priority = 0 if value >= 300 else 1
            candidates.append((priority, y, x, box))
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item[:3])[0][3]

    def _send_button_box(self) -> Any | None:
        return self._send_button_box_from_boxes(list(self._ocr_full_screen()))

    def _send_button_box_from_boxes(self, boxes) -> Any | None:
        width = self._screen_width()
        height = self._screen_height()
        candidates = []
        for box in boxes:
            text = self._box_text(box)
            if "赠送" not in text:
                continue
            x = int(getattr(box, "x", 0) or 0)
            y = int(getattr(box, "y", 0) or 0)
            if x < width * 0.55 or y < height * 0.70:
                continue
            candidates.append((y, x, box))
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item[0], item[1]))[0][2]

    def _confirm_button_box(self) -> Any | None:
        boxes = list(self._ocr_full_screen())
        for needle in _GIFT_CONFIRM_TEXTS:
            confirm = self._find_text_box(boxes, needle, min_y_ratio=0.35)
            if confirm is not None:
                return confirm
        return None

    def _confirm_if_present(self) -> dict[str, Any] | None:
        confirm = self._confirm_button_box()
        if confirm is not None:
            return self._click_with_verify(
                confirm,
                recognized_ui="gift_confirm_button",
                verifier=self._confirm_completed_observed,
                wait_seconds=self.POST_CLICK_SETTLE,
            )
        return None

    def _confirm_completed_observed(self) -> bool:
        boxes = list(self._ocr_full_screen())
        for needle in _GIFT_CONFIRM_TEXTS:
            if self._find_text_box(boxes, needle, min_y_ratio=0.35) is not None:
                return False
        return self._has_gift_grid(boxes)

    def _gift_send_post_click_state_observed(self) -> bool:
        if self._confirm_button_box() is not None:
            return True
        return self._gift_send_completion_observed()

    def _gift_send_completion_observed(self) -> bool:
        boxes = list(self._ocr_full_screen())
        if self._send_button_box_from_boxes(boxes) is not None:
            self._post_send_grid_seen = False
            return False
        grid_seen = self._has_gift_grid(boxes)
        verified = self._post_send_grid_seen and grid_seen
        self._post_send_grid_seen = grid_seen
        return verified

    # ---------------------------------------------------------- gating helpers

    def _click_with_verify(
        self,
        box,
        *,
        recognized_ui: str,
        verifier: Callable[[], bool],
        wait_seconds: float,
        target_offset: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        """Pre-gate, dispatch click, post-verify.

        Refuse if no evidence box, dispatch via ``task.operate_click``, then
        poll the verifier predicate for a bounded time.
        """
        if box is None:
            return self._gate_blocked(recognized_ui, "evidence_box_missing")

        confidence = float(getattr(box, "confidence", 1.0) or 0.0)
        if confidence < self.OCR_MIN_CONFIDENCE:
            return self._gate_blocked(recognized_ui, "low_confidence", confidence=confidence)

        x = self._box_center_x(box)
        y = self._box_center_y(box)
        if target_offset:
            x += int(target_offset[0])
            y += int(target_offset[1])
        try:
            self.task.operate_click(int(x), int(y), hcenter=False, vcenter=False)
        except TypeError:
            self.task.operate_click(int(x), int(y))
        mutation_performed = True

        deadline = time.time() + max(0.0, float(wait_seconds))
        verified = False
        while time.time() < deadline:
            try:
                if verifier():
                    verified = True
                    break
            except Exception:
                pass
            self.task.sleep(0.25)

        details = {
            "recognized_ui": recognized_ui,
            "target_point": [int(x), int(y)],
            "confidence": confidence,
            "mutation_performed": mutation_performed,
            "mutation_verified": verified,
        }
        self.actions.append(details)
        return details

    def _gate_blocked(self, recognized_ui: str, reason: str, **extra) -> dict[str, Any]:
        details = {
            "recognized_ui": recognized_ui,
            "mutation_performed": False,
            "mutation_verified": False,
            "reject_reason": reason,
        }
        details.update(extra)
        self.actions.append(details)
        return details

    # ------------------------------------------------------------ OCR + frames

    def _ocr_full_screen(self):
        ocr = getattr(self.task, "ocr_ui", None)
        if not callable(ocr):
            ocr = getattr(self.task, "ocr", None)
        if not callable(ocr):
            return []
        try:
            result = ocr(0, 0, 1, 1)
        except Exception:
            return []
        if result is None or isinstance(result, (str, bytes)):
            return []
        try:
            return list(result)
        except TypeError:
            return []

    def _ocr_texts(self) -> list[str]:
        return [self._box_text(box) for box in self._ocr_full_screen()]

    def _has_gift_grid(self, boxes) -> bool:
        texts = [self._box_text(box) for box in boxes]
        return all(any(marker in text for text in texts) for marker in _GIFT_GRID_MARKERS)

    def _find_text_box(
        self, boxes, needle: str, *, min_x_ratio=0.0, max_y_ratio=1.0, min_y_ratio=0.0
    ):
        width = self._screen_width()
        height = self._screen_height()
        candidates = []
        for box in boxes:
            text = self._box_text(box)
            if needle not in text:
                continue
            confidence = float(getattr(box, "confidence", 1.0) or 0.0)
            if confidence < self.OCR_MIN_CONFIDENCE:
                continue
            x = int(getattr(box, "x", 0) or 0)
            y = int(getattr(box, "y", 0) or 0)
            if x < width * min_x_ratio or y > height * max_y_ratio or y < height * min_y_ratio:
                continue
            candidates.append((y, x, box))
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item[0], item[1]))[0][2]

    # --------------------------------------------------------------- geometry

    @staticmethod
    def _box_text(box) -> str:
        return str(
            getattr(box, "name", "") or getattr(box, "text", "") or ""
        ).strip()

    @staticmethod
    def _box_center_x(box) -> float:
        return float(getattr(box, "x", 0) or 0) + float(getattr(box, "width", 0) or 0) / 2

    @staticmethod
    def _box_center_y(box) -> float:
        return float(getattr(box, "y", 0) or 0) + float(getattr(box, "height", 0) or 0) / 2

    def _screen_width(self) -> int:
        return int(getattr(self.task, "width", 0) or 0)

    def _screen_height(self) -> int:
        return int(getattr(self.task, "height", 0) or 0)

    # --------------------------------------------------------------- bookkeep

    def _build_result(
        self,
        *,
        ok: bool = True,
        skipped: bool = False,
        action_failed: bool = False,
        mutation_performed: bool = False,
        mutation_verified: bool = False,
        task_completed: bool = False,
        sent_total: int = 0,
        reason: str = "",
    ) -> dict[str, Any]:
        mutation_performed = mutation_performed or any(
            action.get("mutation_performed") for action in self.actions
        )
        return {
            "ok": ok,
            "skipped": skipped,
            "action_failed": action_failed,
            "mutation_performed": mutation_performed,
            "mutation_verified": mutation_verified,
            "task_completed": task_completed,
            "sent_total": sent_total,
            "reason": reason,
            "actions": list(self.actions),
        }
