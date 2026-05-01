from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

from src.Labels import Labels


class DailyActivityState(str, Enum):
    UNKNOWN = "unknown"
    PANEL_NOT_FOUND = "panel_not_found"
    DAILY_TAB_OPENED = "daily_tab_opened"
    ACTIVITY_FULL = "activity_full"
    ALL_DAILY_DONE = "all_daily_done"
    HAS_GO_BUTTON = "has_go_button"
    HAS_CLAIMABLE_REWARD = "has_claimable_reward"
    NO_CLAIMABLE_REWARD = "no_claimable_reward"
    NO_ACTION_NEEDED = "no_action_needed"


@dataclass
class DailyActivityAnalysis:
    state: DailyActivityState
    panel_detected: bool
    daily_tab_detected: bool
    activity_full: bool
    all_daily_done: bool
    has_go_button: bool
    has_claimable_reward: bool
    no_claimable_reward: bool
    reason: str = ""

    def to_dict(self):
        return {
            "state": self.state.value,
            "panel_detected": self.panel_detected,
            "daily_tab_detected": self.daily_tab_detected,
            "activity_full": self.activity_full,
            "all_daily_done": self.all_daily_done,
            "has_go_button": self.has_go_button,
            "has_claimable_reward": self.has_claimable_reward,
            "no_claimable_reward": self.no_claimable_reward,
            "reason": self.reason,
        }


@dataclass
class RegionBox:
    name: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0


class DailyActivityAnalyzer:
    """Read-only state analyzer for the F1 daily activity tab."""

    DONE_REASON = "今日活跃度已完成"
    UNKNOWN_REASON = "缺少未完成/前往按钮/可领取状态特征"
    ACTIVITY_REWARD_REGION = (0.3427, 0.2009, 0.5292, 0.0454)
    COMPLETED_REWARD_MARKERS = 5
    MIN_MARKER_AREA = 80
    PINK_HSV_LOWER = np.array([145, 80, 120], dtype=np.uint8)
    PINK_HSV_UPPER = np.array([175, 255, 255], dtype=np.uint8)

    def __init__(self, task):
        self.task = task

    def analyze(self, frame=None, panel_detected=None):
        frame = self.task.frame if frame is None else frame
        panel_detected = self._detect_panel() if panel_detected is None else bool(panel_detected)
        daily_tab_detected = panel_detected

        if not panel_detected:
            return DailyActivityAnalysis(
                state=DailyActivityState.PANEL_NOT_FOUND,
                panel_detected=False,
                daily_tab_detected=False,
                activity_full=False,
                all_daily_done=False,
                has_go_button=False,
                has_claimable_reward=False,
                no_claimable_reward=False,
                reason="未检测到每日活跃度面板",
            )

        has_claimable_reward = self._detect_claimable_reward(frame)
        activity_full = self._detect_activity_full(frame)
        all_daily_done = activity_full
        has_go_button = False
        no_claimable_reward = not has_claimable_reward

        if has_claimable_reward:
            state = DailyActivityState.HAS_CLAIMABLE_REWARD
            reason = "检测到可领取活跃度奖励"
        elif activity_full or all_daily_done:
            state = DailyActivityState.NO_ACTION_NEEDED
            reason = self.DONE_REASON
        else:
            state = DailyActivityState.UNKNOWN
            reason = self.UNKNOWN_REASON

        return DailyActivityAnalysis(
            state=state,
            panel_detected=panel_detected,
            daily_tab_detected=daily_tab_detected,
            activity_full=activity_full,
            all_daily_done=all_daily_done,
            has_go_button=has_go_button,
            has_claimable_reward=has_claimable_reward,
            no_claimable_reward=no_claimable_reward,
            reason=reason,
        )

    def _detect_panel(self):
        finder = getattr(self.task, "find_one", None)
        if finder is None:
            return False
        return bool(finder(Labels.f1_activity_panel))

    def _detect_claimable_reward(self, frame):
        # No claimable reward sample is available yet; keep this conservative.
        return False

    def _detect_activity_full(self, frame):
        if frame is None:
            return False

        reward_box = self._get_reward_box()
        reward_frame = self._crop(frame, reward_box)
        if reward_frame.size == 0:
            return False

        return self._count_completed_reward_markers(reward_frame) >= self.COMPLETED_REWARD_MARKERS

    def _get_reward_box(self):
        getter = getattr(self.task, "get_box_by_name", None)
        if getter is not None:
            box = getter(Labels.box_f1_activity_reward)
            if box is not None:
                return box

        width = int(getattr(self.task, "width", 0))
        height = int(getattr(self.task, "height", 0))
        x, y, w, h = self.ACTIVITY_REWARD_REGION
        return RegionBox(
            name=str(Labels.box_f1_activity_reward),
            x=int(width * x),
            y=int(height * y),
            width=int(width * w),
            height=int(height * h),
        )

    @staticmethod
    def _crop(frame, box):
        x = max(0, int(getattr(box, "x", 0)))
        y = max(0, int(getattr(box, "y", 0)))
        width = max(0, int(getattr(box, "width", 0)))
        height = max(0, int(getattr(box, "height", 0)))
        return frame[y : y + height, x : x + width]

    def _count_completed_reward_markers(self, reward_frame):
        hsv = cv2.cvtColor(reward_frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.PINK_HSV_LOWER, self.PINK_HSV_UPPER)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        components = 0
        for index in range(1, count):
            if stats[index, cv2.CC_STAT_AREA] >= self.MIN_MARKER_AREA:
                components += 1
        return components
