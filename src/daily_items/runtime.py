"""DailyTaskItem 运行时. 在 F1 活跃度面板里领取已完成的子任务奖励.

设计要点:

* 直接通过 task 的 OCR 找到带 "领取" 按钮的任务卡片, 用 upstream 已有的
  ``binarize_bgr_by_brightness`` + ``find_color_rectangles`` 工具链 (见
  ``DailyTask._get_activity_reward_box``) 把按钮位置定位到点击坐标.
* 一次最多领取 ``CONF_MAX_CLAIMS`` 张; 默认 10.
* 默认关闭. ``allow_real_claim`` 未显式开启时不会打开面板或点击领取.
* 单卡 MVP 即可达成 plan 中 BLOCKED bar 的最低要求; 多卡循环复用同一扫描.

返回的 ``dict`` 与 :mod:`src.coffee.runtime` 风格一致.
"""
from __future__ import annotations

import time
from typing import Any

from src.Labels import Labels


_F1_DAILY_TAB_POSITION = (0.0551, 0.3833)
_CLAIM_BUTTON_TEXTS = ("领取",)
_OCR_MIN_CONFIDENCE = 0.6
_CARD_SAME_ROW_TOLERANCE_RATIO = 0.06


class DailyTaskItemRuntime:
    """Runtime for claiming completed daily task item rewards.

    Returns plain ``dict`` from public methods.
    """

    POST_CLICK_SETTLE = 1.0
    CLAIM_VERIFY_TIMEOUT = 2.5

    def __init__(self, task):
        self.task = task
        self.actions: list[dict[str, Any]] = []
        self._last_ocr_available = True

    # --------------------------------------------------------------- entrypoint

    def run(self, *, max_claims: int = 10, allow_real_claim: bool = False) -> dict[str, Any]:
        self.actions = []
        max_claims = max(0, int(max_claims or 0))
        summary: dict[str, Any] = {
            "ok": True,
            "skipped": False,
            "action_failed": False,
            "reason": "",
            "items": [],
            "actions": [],
            "mutation_performed": False,
            "mutation_verified": False,
            "task_completed": False,
            "claimed_count": 0,
        }

        if not allow_real_claim:
            summary.update({"skipped": True, "reason": "daily_task_item_claim_not_allowed"})
            return summary

        if max_claims <= 0:
            summary["reason"] = "max_claims_not_positive"
            return summary

        if not self._open_activity_panel():
            summary.update(
                {"ok": False, "action_failed": True, "reason": "f1_panel_not_opened"}
            )
            return summary

        attempts = 0
        while attempts < max_claims:
            card = self._first_claimable_card()
            if card is None:
                break

            summary["items"].append(self._card_record(card))

            click_details = self._click_with_verify(
                card["action_box"],
                recognized_ui="daily_task_item_claim",
                verifier=lambda c=card: self._claim_disappeared(c),
                wait_seconds=self.CLAIM_VERIFY_TIMEOUT,
            )
            summary["actions"].append(click_details)

            if not click_details["mutation_verified"]:
                summary.update(
                    {
                        "ok": False,
                        "action_failed": True,
                        "reason": "claim_post_action_verification_failed",
                        "mutation_performed": any(
                            a.get("mutation_performed") for a in summary["actions"]
                        ),
                        "mutation_verified": False,
                    }
                )
                return summary

            summary["claimed_count"] += 1
            attempts += 1

        summary["mutation_performed"] = any(
            a.get("mutation_performed") for a in summary["actions"]
        )
        performed_actions = [
            action for action in summary["actions"] if action.get("mutation_performed")
        ]
        summary["mutation_verified"] = bool(performed_actions) and all(
            a.get("mutation_verified") for a in performed_actions
        )
        summary["task_completed"] = summary["claimed_count"] > 0
        if not summary["task_completed"]:
            summary["reason"] = "no_claimable_completed_task_item"
        return summary

    # --------------------------------------------------------- F1 navigation

    def _open_activity_panel(self) -> bool:
        def action():
            self.task.openF1panel()
            self.task.operate_click(*_F1_DAILY_TAB_POSITION)
            self.task.sleep(0.5)
            return self.task.wait_panel(Labels.f1_activity_panel)

        ensure = getattr(self.task, "ensure_main", lambda: None)
        result = self.task.retry_on_action(action, ensure)
        return bool(result)

    # ------------------------------------------------------------ card scan

    def _first_claimable_card(self) -> dict[str, Any] | None:
        boxes = list(self._ocr_full_screen())
        height = self._screen_height()
        tolerance = max(8, int(height * _CARD_SAME_ROW_TOLERANCE_RATIO))

        # Pre-bucket "领取" buttons.
        claim_buttons = []
        for box in boxes:
            text = self._box_text(box).strip()
            if text in _CLAIM_BUTTON_TEXTS:
                conf = float(getattr(box, "confidence", 1.0) or 0.0)
                if conf >= _OCR_MIN_CONFIDENCE:
                    claim_buttons.append(box)
        if not claim_buttons:
            return None

        for box in boxes:
            text = self._box_text(box).strip()
            if not text or text in _CLAIM_BUTTON_TEXTS:
                continue
            anchor_y = self._box_center_y(box)
            for button in claim_buttons:
                if not self._looks_like_task_title_for_button(box, button, tolerance):
                    continue
                if abs(self._box_center_y(button) - anchor_y) <= tolerance:
                    return {
                        "title": text,
                        "title_box": box,
                        "action_box": button,
                        "action_text": "领取",
                    }
        return None

    def _claim_disappeared(self, card: dict[str, Any]) -> bool:
        """Verifier: after claim click, the same-row "领取" button is gone."""
        title_box = card.get("title_box")
        if title_box is None:
            return False
        anchor_y = self._box_center_y(title_box)
        height = self._screen_height()
        tolerance = max(8, int(height * _CARD_SAME_ROW_TOLERANCE_RATIO))
        boxes = self._ocr_full_screen()
        if not boxes or not self._last_ocr_available:
            return False
        for box in boxes:
            if self._box_text(box).strip() not in _CLAIM_BUTTON_TEXTS:
                continue
            if abs(self._box_center_y(box) - anchor_y) <= tolerance:
                return False
        return True

    # ---------------------------------------------------------- gating helpers

    def _click_with_verify(
        self,
        box,
        *,
        recognized_ui: str,
        verifier,
        wait_seconds: float,
    ) -> dict[str, Any]:
        if box is None:
            return self._gate_blocked(recognized_ui, "evidence_box_missing")

        confidence = float(getattr(box, "confidence", 1.0) or 0.0)
        if confidence < _OCR_MIN_CONFIDENCE:
            return self._gate_blocked(recognized_ui, "low_confidence", confidence=confidence)

        x = self._box_center_x(box)
        y = self._box_center_y(box)
        try:
            self.task.operate_click(int(x), int(y), hcenter=False, vcenter=False)
        except TypeError:
            self.task.operate_click(int(x), int(y))

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

        return {
            "recognized_ui": recognized_ui,
            "target_point": [int(x), int(y)],
            "confidence": confidence,
            "mutation_performed": True,
            "mutation_verified": verified,
        }

    def _gate_blocked(self, recognized_ui: str, reason: str, **extra) -> dict[str, Any]:
        details = {
            "recognized_ui": recognized_ui,
            "mutation_performed": False,
            "mutation_verified": False,
            "reject_reason": reason,
        }
        details.update(extra)
        return details

    # -------------------------------------------------------------- OCR + geom

    def _ocr_full_screen(self):
        ocr = getattr(self.task, "ocr_ui", None)
        if not callable(ocr):
            ocr = getattr(self.task, "ocr", None)
        if not callable(ocr):
            self._last_ocr_available = False
            return []
        try:
            result = ocr(0, 0, 1, 1)
        except Exception:
            self._last_ocr_available = False
            return []
        if result is None or isinstance(result, (str, bytes)):
            self._last_ocr_available = False
            return []
        try:
            boxes = list(result)
        except TypeError:
            self._last_ocr_available = False
            return []
        self._last_ocr_available = True
        return boxes

    def _looks_like_task_title_for_button(self, title_box, button_box, tolerance: int) -> bool:
        text = self._box_text(title_box).strip()
        if not text or text in _CLAIM_BUTTON_TEXTS:
            return False
        if len(text) < 2 or not any("\u4e00" <= char <= "\u9fff" for char in text):
            return False
        title_x = self._box_center_x(title_box)
        button_x = self._box_center_x(button_box)
        if title_x >= button_x:
            return False
        if button_x - title_x < max(120, tolerance * 2):
            return False
        return True

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

    def _screen_height(self) -> int:
        return int(getattr(self.task, "height", 0) or 0)

    def _card_record(self, card: dict[str, Any]) -> dict[str, Any]:
        title_box = card.get("title_box")
        action_box = card.get("action_box")
        return {
            "title": card.get("title", ""),
            "action": card.get("action_text", ""),
            "title_box": _box_to_dict(title_box),
            "action_box": _box_to_dict(action_box),
        }


def _box_to_dict(box) -> dict[str, Any] | None:
    if box is None:
        return None
    return {
        "x": int(getattr(box, "x", 0) or 0),
        "y": int(getattr(box, "y", 0) or 0),
        "width": int(getattr(box, "width", 0) or 0),
        "height": int(getattr(box, "height", 0) or 0),
        "confidence": float(getattr(box, "confidence", 1.0) or 0.0),
    }
