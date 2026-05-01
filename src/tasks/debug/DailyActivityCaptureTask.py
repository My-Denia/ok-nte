import json
import os
from datetime import datetime

import cv2
from qfluentwidgets import FluentIcon

from ok import TaskDisabledException
from src.Labels import Labels
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.DailyTask import DailyTask


class DailyActivityCaptureTask(BaseNTETask):
    """采集 F1 每日活跃度面板，用于补充模板特征。"""

    DEFAULT_MOVE = True
    DAILY_ACTIVITY_TAB_INDEX = DailyTask.DAILY_ACTIVITY_TAB_INDEX
    DAILY_ACTIVITY_TAB_POSITION = DailyTask.DAILY_ACTIVITY_TAB_POSITION
    ACTIVITY_TAB_POSITION = DAILY_ACTIVITY_TAB_POSITION
    CAPTURE_NAME_PREFIX = "daily_activity_capture"
    CAPTURE_FOLDER = os.path.join("screenshots", CAPTURE_NAME_PREFIX)
    CANDIDATE_REGION_DEFINITIONS = (
        ("daily_activity_panel", (0.1800, 0.1550, 0.9400, 0.8750)),
        ("daily_activity_score_area", (0.1350, 0.1720, 0.3400, 0.2850)),
        ("daily_task_card_strip", (0.1450, 0.2900, 0.9100, 0.7850)),
        ("daily_task_card_body", (0.1600, 0.3250, 0.8950, 0.7150)),
        ("daily_task_card_footer", (0.1600, 0.7300, 0.9100, 0.8000)),
        ("daily_task_card_action_area", (0.6450, 0.3300, 0.9100, 0.7950)),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "每日活跃度采集"
        self.description = "采集每日活跃度面板截图和候选区域，用于补充识别特征"
        self.icon = FluentIcon.CAMERA
        self.support_schedule_task = False
        self.default_config.update(
            {
                "保存候选区域标注": True,
                "保存OCR结果": False,
            }
        )
        self.add_exit_after_config()

    def run(self):
        try:
            return self.do_run()
        except TaskDisabledException:
            pass

    def do_run(self):
        self.log_info("开始采集每日活跃度面板特征")
        self._ensure_capture_main()
        panel_detected = self._open_activity_panel()
        self._capture_current_activity_panel(self.frame, panel_detected=panel_detected)
        self._ensure_capture_main()
        self.log_info("每日活跃度面板截图已保存")
        return True

    def _ensure_capture_main(self):
        self.info_set("current task", "wait daily capture main esc=True")
        if self.wait_until(
            lambda: self.in_team_and_world() or self.handle_monthly_card(),
            time_out=30,
            raise_if_not_found=False,
            post_action=lambda: self.back(after_sleep=2),
        ):
            self._logged_in = True
            self.sleep(0.5)
            self.info_set("current task", "in daily capture main")
            return True

        raise Exception("Please start in game world and in team!")

    def _open_activity_panel(self):
        self.openF1panel()
        self.info_set("每日活跃度目标栏目", f"第{self.DAILY_ACTIVITY_TAB_INDEX}栏目")
        self.click(*self.DAILY_ACTIVITY_TAB_POSITION, after_sleep=1)
        if not self.wait_panel(Labels.f1_activity_panel):
            self.log_error("无法找到每日活跃度面板", notify=True)
            return False
        return True

    def _capture_current_activity_panel(self, frame, panel_detected=True):
        capture_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate_boxes = self._candidate_region_boxes()
        ocr_boxes = []
        if self.config.get("保存OCR结果", False):
            ocr_boxes = self.ocr(frame=frame, log=True)

        image_paths = self._save_capture_images(capture_id, frame, candidate_boxes, ocr_boxes)
        self.screenshot(f"{self.CAPTURE_NAME_PREFIX}/{capture_id}_panel_clean", frame=frame)

        if self.config.get("保存候选区域标注", True):
            self.clear_box()
            self.draw_boxes("daily_activity_candidate_regions", candidate_boxes, color="blue")
            if ocr_boxes:
                self.draw_boxes("daily_activity_ocr", ocr_boxes, color="green")
            self.screenshot(
                f"{self.CAPTURE_NAME_PREFIX}/{capture_id}_panel_regions",
                frame=frame,
                show_box=True,
            )

        metadata_path = self._write_capture_metadata(
            capture_id,
            candidate_boxes,
            ocr_boxes,
            image_paths,
            panel_detected,
        )
        self.info_set("每日活跃度采集ID", capture_id)
        self.info_set("每日活跃度采集元数据", metadata_path)
        self.info_set("每日活跃度面板特征命中", str(panel_detected))
        return True

    def _save_capture_images(self, capture_id, frame, candidate_boxes, ocr_boxes):
        if frame is None:
            raise ValueError("daily activity capture frame cannot be None")

        os.makedirs(self.CAPTURE_FOLDER, exist_ok=True)
        image_paths = {
            "clean": os.path.join(self.CAPTURE_FOLDER, f"{capture_id}_panel_clean.png"),
            "regions": os.path.join(self.CAPTURE_FOLDER, f"{capture_id}_panel_regions.png"),
        }

        self._write_frame(image_paths["clean"], frame)

        boxed_frame = frame.copy()
        self._draw_box_overlays(boxed_frame, candidate_boxes, (255, 0, 0))
        self._draw_box_overlays(boxed_frame, ocr_boxes, (0, 255, 0))
        self._write_frame(image_paths["regions"], boxed_frame)
        return image_paths

    @staticmethod
    def _write_frame(path, frame):
        if not cv2.imwrite(path, frame):
            raise OSError(f"failed to write screenshot: {path}")

    @staticmethod
    def _draw_box_overlays(frame, boxes, color):
        for box in boxes:
            x = int(getattr(box, "x", 0))
            y = int(getattr(box, "y", 0))
            width = int(getattr(box, "width", 0))
            height = int(getattr(box, "height", 0))
            if width <= 0 or height <= 0:
                continue

            cv2.rectangle(frame, (x, y), (x + width, y + height), color, 2)
            name = str(getattr(box, "name", ""))
            if name:
                cv2.putText(
                    frame,
                    name,
                    (x, max(20, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2,
                    cv2.LINE_AA,
                )

    def _candidate_region_boxes(self):
        boxes = [
            self.box_of_screen(*definition, name=name)
            for name, definition in self.CANDIDATE_REGION_DEFINITIONS
        ]
        boxes.append(self.get_box_by_name(Labels.box_f1_activity_reward))
        return boxes

    def _write_capture_metadata(self, capture_id, candidate_boxes, ocr_boxes, image_paths, panel_detected):
        folder = os.path.join("logs", self.CAPTURE_NAME_PREFIX)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{capture_id}.json")
        payload = {
            "capture_id": capture_id,
            "panel_detected": panel_detected,
            "target_tab": {
                "name": "每日",
                "index": self.DAILY_ACTIVITY_TAB_INDEX,
                "position": {
                    "x": self.DAILY_ACTIVITY_TAB_POSITION[0],
                    "y": self.DAILY_ACTIVITY_TAB_POSITION[1],
                },
            },
            "images": image_paths,
            "screen": {"width": self.width, "height": self.height},
            "candidate_regions": [self._box_to_dict(box) for box in candidate_boxes],
            "ocr": [self._box_to_dict(box) for box in ocr_boxes],
            "missing_features": DailyTask.DAILY_ACTIVITY_MISSING_FEATURES,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def _box_to_dict(box):
        return {
            "name": str(getattr(box, "name", "")),
            "x": getattr(box, "x", None),
            "y": getattr(box, "y", None),
            "width": getattr(box, "width", None),
            "height": getattr(box, "height", None),
            "confidence": getattr(box, "confidence", None),
        }
