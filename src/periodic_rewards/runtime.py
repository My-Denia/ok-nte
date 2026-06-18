"""环期任务奖励领取运行时.

默认不执行真实点击. 调用方必须显式传入 ``allow_real_claim=True`` 才会打开
F2 面板并点击 "领取" / "全部领取".
"""
from __future__ import annotations

import re
import time
from typing import Any

from src.Labels import Labels


_CLAIM_TEXT = "领取"
_BATCH_CLAIM_TEXT = "全部领取"
_OCR_MIN_CONFIDENCE = 0.6


class PeriodicRewardsRuntime:
    """Runtime for claiming daily periodic reward entries."""

    PERIODIC_CLAIM_NOT_ALLOWED = "periodic_reward_claim_not_allowed"
    PERIODIC_PANEL_NOT_FOUND = "periodic_panel_not_found"
    NO_PERIODIC_CLAIMS_ENABLED = "no_periodic_reward_claims_enabled"
    NO_CLAIMABLE_PERIODIC_REWARD = "no_claimable_periodic_reward"
    PERIODIC_REWARD_OCR_UNAVAILABLE = "periodic_reward_ocr_unavailable"
    PERIODIC_REWARD_CLAIM_POST_ACTION_FAILED = (
        "periodic_reward_claim_post_action_verification_failed"
    )

    MISSION_TAB_POSITION = (0.0570, 0.3451)
    REWARD_TAB_POSITION = (0.0570, 0.2333)
    MISSION_CLAIM_REGION = (0.70, 0.18, 0.96, 0.78)
    REWARD_BUTTON_REGION = (0.76, 0.78, 0.97, 0.93)
    DEFAULT_MAX_MISSION_CLAIMS = 5
    CLAIM_VERIFY_TIMEOUT_SECONDS = 2.5
    CLAIM_VERIFY_POLL_SECONDS = 0.25

    def __init__(self, task):
        self.task = task
        self.actions: list[dict[str, Any]] = []
        self._ocr_unavailable = False

    def run(
        self,
        *,
        max_mission_claims: int = DEFAULT_MAX_MISSION_CLAIMS,
        claim_missions: bool = True,
        claim_reward_track: bool = True,
        allow_real_claim: bool = False,
    ) -> dict[str, Any]:
        self.actions = []
        self._ocr_unavailable = False
        max_mission_claims = max(0, int(max_mission_claims or 0))
        summary = self._summary()

        if not allow_real_claim:
            summary.update({"skipped": True, "reason": self.PERIODIC_CLAIM_NOT_ALLOWED})
            return summary

        if not claim_missions and not claim_reward_track:
            summary.update({"skipped": True, "reason": self.NO_PERIODIC_CLAIMS_ENABLED})
            return summary

        if not self._open_periodic_panel():
            summary.update(
                {"ok": False, "action_failed": True, "reason": self.PERIODIC_PANEL_NOT_FOUND}
            )
            return summary

        mission_claims = 0
        mission_batch_claimed = False
        reward_claimed = False

        if claim_missions and max_mission_claims > 0:
            mission_batch_target = self._find_text_box(
                _BATCH_CLAIM_TEXT,
                self.REWARD_BUTTON_REGION,
            )
            if mission_batch_target is not None:
                action = self._click_with_verify(
                    mission_batch_target,
                    reward_type="periodic_mission",
                    button_text=_BATCH_CLAIM_TEXT,
                    region=self.REWARD_BUTTON_REGION,
                )
                self.actions.append(action)
                if not action["mutation_verified"]:
                    return self._failed_result()
                mission_claims += 1
                mission_batch_claimed = True

            while not mission_batch_claimed and mission_claims < max_mission_claims:
                mission_target = self._find_text_box(_CLAIM_TEXT, self.MISSION_CLAIM_REGION)
                if mission_target is None:
                    break
                action = self._click_with_verify(
                    mission_target,
                    reward_type="periodic_mission",
                    button_text=_CLAIM_TEXT,
                    region=self.MISSION_CLAIM_REGION,
                )
                self.actions.append(action)
                if not action["mutation_verified"]:
                    return self._failed_result()
                mission_claims += 1

        if claim_reward_track:
            self._open_reward_track()
            reward_target = self._find_text_box(_BATCH_CLAIM_TEXT, self.REWARD_BUTTON_REGION)
            if reward_target is not None:
                action = self._click_with_verify(
                    reward_target,
                    reward_type="periodic_reward_track",
                    button_text=_BATCH_CLAIM_TEXT,
                    region=self.REWARD_BUTTON_REGION,
                )
                self.actions.append(action)
                if not action["mutation_verified"]:
                    return self._failed_result()
                reward_claimed = True

        if not self.actions:
            if self._ocr_unavailable:
                return self._ocr_unavailable_result()
            summary.update({"skipped": True, "reason": self.NO_CLAIMABLE_PERIODIC_REWARD})
            return summary

        summary.update(
            {
                "claimed": True,
                "mission_claim_attempts": mission_claims,
                "reward_claimed": reward_claimed,
                "mutation_performed": any(a["mutation_performed"] for a in self.actions),
                "mutation_verified": all(a["mutation_verified"] for a in self.actions),
                "task_completed": all(a["mutation_verified"] for a in self.actions),
                "actions": list(self.actions),
                "details": {
                    "mission": {
                        "claimed_count": mission_claims,
                        "batch_claimed": mission_batch_claimed,
                    },
                    "reward_track": {"claimed": reward_claimed},
                },
            }
        )
        return summary

    def _summary(self) -> dict[str, Any]:
        return {
            "ok": True,
            "claimed": False,
            "mission_claim_attempts": 0,
            "reward_claimed": False,
            "skipped": False,
            "reason": "",
            "mutation_performed": False,
            "mutation_verified": False,
            "task_completed": False,
            "action_failed": False,
            "actions": [],
            "details": {"mission": {}, "reward_track": {}},
        }

    def _failed_result(self) -> dict[str, Any]:
        result = self._summary()
        result.update(
            {
                "ok": False,
                "reason": self.PERIODIC_REWARD_CLAIM_POST_ACTION_FAILED,
                "mutation_performed": any(a["mutation_performed"] for a in self.actions),
                "mutation_verified": False,
                "task_completed": False,
                "action_failed": True,
                "actions": list(self.actions),
            }
        )
        return result

    def _ocr_unavailable_result(self) -> dict[str, Any]:
        result = self._summary()
        result.update(
            {
                "ok": False,
                "reason": self.PERIODIC_REWARD_OCR_UNAVAILABLE,
                "action_failed": True,
            }
        )
        return result

    def _open_periodic_panel(self) -> bool:
        if self._periodic_panel_ready():
            return True

        def action():
            open_panel = getattr(self.task, "openF2panel", None)
            if callable(open_panel):
                open_panel()
            self._click_ratio(*self.MISSION_TAB_POSITION)
            self._sleep(0.5)
            return self._periodic_panel_ready()

        retry = getattr(self.task, "retry_on_action", None)
        ensure = getattr(self.task, "ensure_main", lambda: None)
        try:
            if callable(retry):
                return bool(retry(action, ensure))
            return bool(action())
        except Exception:
            return False

    def _periodic_panel_ready(self) -> bool:
        wait_panel = getattr(self.task, "wait_panel", None)
        if callable(wait_panel):
            try:
                if wait_panel(Labels.f2_mission_panel):
                    return True
            except Exception:
                pass
        find_one = getattr(self.task, "find_one", None)
        if callable(find_one):
            try:
                if find_one(Labels.f2_mission_panel):
                    return True
            except Exception:
                pass
        return False

    def _open_reward_track(self) -> None:
        self._click_ratio(*self.REWARD_TAB_POSITION)
        self._sleep(0.5)

    def _click_ratio(self, x: float, y: float) -> None:
        click = getattr(self.task, "operate_click", None)
        if callable(click):
            click(float(x), float(y))

    def _click_with_verify(self, box, *, reward_type: str, button_text: str, region):
        if box is None:
            return self._action_blocked(reward_type, button_text, box, "evidence_box_missing")

        confidence = float(getattr(box, "confidence", 1.0) or 0.0)
        if confidence < _OCR_MIN_CONFIDENCE:
            return self._action_blocked(
                reward_type,
                button_text,
                box,
                "low_confidence",
                confidence=confidence,
            )

        x = self._box_center_x(box)
        y = self._box_center_y(box)
        click = getattr(self.task, "operate_click", None)
        if not callable(click):
            return self._action_blocked(
                reward_type,
                button_text,
                box,
                "click_unavailable",
                confidence=confidence,
            )
        try:
            click(int(x), int(y), hcenter=False, vcenter=False)
        except TypeError:
            click(int(x), int(y))

        deadline = time.monotonic() + max(0.0, float(self.CLAIM_VERIFY_TIMEOUT_SECONDS))
        verified = False
        while True:
            if self._claim_disappeared(box, button_text, region):
                verified = True
                break
            if time.monotonic() >= deadline:
                break
            self._sleep(self.CLAIM_VERIFY_POLL_SECONDS)
            next_frame = getattr(self.task, "next_frame", None)
            if callable(next_frame):
                try:
                    next_frame()
                except Exception:
                    pass

        return {
            "reward_type": reward_type,
            "button_text": button_text,
            "button_evidence": self._box_details(box),
            "target_point": [int(x), int(y)],
            "confidence": confidence,
            "mutation_performed": True,
            "mutation_verified": verified,
            "reason": "" if verified else "post_verification_failed",
        }

    def _action_blocked(self, reward_type, button_text, box, reason, **extra):
        details = {
            "reward_type": reward_type,
            "button_text": button_text,
            "button_evidence": self._box_details(box),
            "mutation_performed": False,
            "mutation_verified": False,
            "reason": reason,
        }
        details.update(extra)
        return details

    def _claim_disappeared(self, before_box, button_text, region) -> bool:
        boxes = self._find_text_boxes(button_text, region)
        if boxes is None:
            return False
        return not any(
            self._same_box(before_box, candidate)
            for candidate in boxes
        )

    def _find_text_box(self, text: str, region):
        boxes = self._find_text_boxes(text, region)
        return boxes[0] if boxes else None

    def _find_text_boxes(self, text: str, region):
        boxes = self._ocr_region(region)
        if boxes is None:
            return None
        return [
            box
            for box in boxes
            if self._claim_text_matches(self._box_text(box), text)
        ]

    def _ocr_region(self, region):
        ocr = getattr(self.task, "ocr_ui", None)
        if not callable(ocr):
            ocr = getattr(self.task, "ocr", None)
        if not callable(ocr):
            self._ocr_unavailable = True
            return None
        frame = getattr(self.task, "frame", None)
        try:
            result = ocr(*region, frame=frame)
        except TypeError:
            try:
                result = ocr(*region)
            except Exception:
                self._ocr_unavailable = True
                return None
        except Exception:
            self._ocr_unavailable = True
            return None
        if result is None or isinstance(result, (str, bytes)):
            self._ocr_unavailable = True
            return None
        try:
            return list(result)
        except TypeError:
            self._ocr_unavailable = True
            return None

    @staticmethod
    def _claim_text_matches(text: str, expected: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        expected = re.sub(r"\s+", "", str(expected or ""))
        if not normalized or not expected:
            return False
        if "已领取" in normalized or "已全部领取" in normalized:
            return False
        if expected == _CLAIM_TEXT:
            return normalized in {_CLAIM_TEXT, "领取奖励"}
        if expected == _BATCH_CLAIM_TEXT:
            return normalized == _BATCH_CLAIM_TEXT
        return normalized == expected

    @staticmethod
    def _box_text(box) -> str:
        return str(getattr(box, "text", None) or getattr(box, "name", "") or "").strip()

    @staticmethod
    def _box_center_x(box) -> float:
        return float(getattr(box, "x", 0) or 0) + float(getattr(box, "width", 0) or 0) / 2

    @staticmethod
    def _box_center_y(box) -> float:
        return float(getattr(box, "y", 0) or 0) + float(getattr(box, "height", 0) or 0) / 2

    @staticmethod
    def _same_box(first, second, *, tolerance=12) -> bool:
        if first is None or second is None:
            return False
        return (
            abs(int(getattr(first, "x", 0) or 0) - int(getattr(second, "x", 0) or 0)) <= tolerance
            and abs(int(getattr(first, "y", 0) or 0) - int(getattr(second, "y", 0) or 0)) <= tolerance
            and abs(int(getattr(first, "width", 0) or 0) - int(getattr(second, "width", 0) or 0)) <= tolerance
            and abs(int(getattr(first, "height", 0) or 0) - int(getattr(second, "height", 0) or 0)) <= tolerance
        )

    @staticmethod
    def _box_details(box) -> dict[str, Any] | None:
        if box is None:
            return None
        return {
            "name": str(getattr(box, "name", "") or ""),
            "text": str(getattr(box, "text", "") or ""),
            "x": int(getattr(box, "x", 0) or 0),
            "y": int(getattr(box, "y", 0) or 0),
            "width": int(getattr(box, "width", 0) or 0),
            "height": int(getattr(box, "height", 0) or 0),
            "confidence": float(getattr(box, "confidence", 1.0) or 0.0),
        }

    def _sleep(self, seconds: float) -> None:
        sleeper = getattr(self.task, "sleep", None)
        if callable(sleeper):
            sleeper(seconds)
