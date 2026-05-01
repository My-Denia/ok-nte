import json
import unittest

import cv2
import numpy as np

from src.Labels import Labels
from src.tasks.DailyActivityAnalyzer import DailyActivityAnalyzer, DailyActivityState


class FakeBox:
    def __init__(self, name, x=0, y=0, width=1, height=1, confidence=1.0):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.confidence = confidence


class FakeDailyActivityTask:
    width = 1920
    height = 1080

    def __init__(self, frame, panel_detected=True):
        self.frame = frame
        self.panel_detected = panel_detected
        self.reward_box = FakeBox(Labels.box_f1_activity_reward.value, 658, 217, 1016, 49)

    def find_one(self, label):
        if label == Labels.f1_activity_panel and self.panel_detected:
            return FakeBox(label.value, 288, 217, 65, 66)
        return None

    def get_box_by_name(self, label):
        if label == Labels.box_f1_activity_reward:
            return self.reward_box
        return None


class TestDailyActivityAnalyzer(unittest.TestCase):
    def make_frame(self, full_activity=False):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        if full_activity:
            for x in (684, 926, 1165, 1404, 1646):
                cv2.circle(frame, (x, 242), 18, (180, 40, 255), -1)
        return frame

    def test_analyze_full_activity_panel(self):
        task = FakeDailyActivityTask(self.make_frame(full_activity=True))

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.state, DailyActivityState.NO_ACTION_NEEDED)
        self.assertTrue(analysis.panel_detected)
        self.assertTrue(analysis.daily_tab_detected)
        self.assertTrue(analysis.activity_full)
        self.assertTrue(analysis.all_daily_done)
        self.assertFalse(analysis.has_go_button)
        self.assertTrue(analysis.no_claimable_reward)
        self.assertEqual(analysis.reason, "今日活跃度已完成")

    def test_analyze_panel_detected(self):
        task = FakeDailyActivityTask(self.make_frame())

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertTrue(analysis.panel_detected)
        self.assertTrue(analysis.daily_tab_detected)
        self.assertEqual(analysis.state, DailyActivityState.UNKNOWN)

    def test_analyze_panel_not_found(self):
        task = FakeDailyActivityTask(self.make_frame(), panel_detected=False)

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.state, DailyActivityState.PANEL_NOT_FOUND)
        self.assertFalse(analysis.panel_detected)
        self.assertFalse(analysis.daily_tab_detected)

    def test_unknown_state_does_not_guess_claimable_reward(self):
        task = FakeDailyActivityTask(self.make_frame())

        analysis = DailyActivityAnalyzer(task).analyze()

        self.assertEqual(analysis.state, DailyActivityState.UNKNOWN)
        self.assertFalse(analysis.has_claimable_reward)
        self.assertTrue(analysis.no_claimable_reward)

    def test_analysis_result_serializable(self):
        task = FakeDailyActivityTask(self.make_frame(full_activity=True))

        payload = DailyActivityAnalyzer(task).analyze().to_dict()

        self.assertEqual(payload["state"], "no_action_needed")
        self.assertIn("activity_full", payload)
        json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
