from datetime import datetime

from qfluentwidgets import FluentIcon

from ok import TaskDisabledException, find_color_rectangles
from src import text_white_color
from src.Labels import Labels
from src.tasks.DailyActivityAnalyzer import DailyActivityAnalyzer, DailyActivityState
from src.tasks.BaseNTETask import BaseNTETask
from src.utils import image_utils as iu


class DailyTask(BaseNTETask):
    """日常任务执行器"""

    DEFAULT_MOVE = True
    TASK_SKIPPED = object()
    DAILY_ACTIVITY_TAB_INDEX = 2
    DAILY_ACTIVITY_TAB_POSITION = (0.0551, 0.3833)
    ACTIVITY_TAB_POSITION = DAILY_ACTIVITY_TAB_POSITION
    MAX_ACTIVITY_MISSION_CLAIMS = 5
    DAILY_ACTIVITY_MISSING_FEATURES = "任务条目/前往按钮/完成状态"
    ACTIVITY_REWARD_UNAVAILABLE = "未检测到可领取活跃度奖励"
    SIMPLE_ACTIVITY_ACTIONS = ("领取邮件", "领取环期任务奖励")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "日常任务"
        self.description = "暂不可用"
        self.icon = FluentIcon.SYNC
        self.support_schedule_task = False
        self.task_status = {"success": [], "failed": [], "skipped": [], "pending": []}
        self.task_skip_reasons = {}

        self.default_config.update(
            {
                "领取邮件": True,
                "领取环期任务奖励": True,
                "完成每日活跃度": True,
                "领取活跃度奖励": True,
            }
        )
        self.current_task_key = None
        self.add_exit_after_config()

    def run(self):
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self._handle_exception(e)

    def do_run(self):
        """执行日常任务主流程"""
        self.log_info("开始执行日常任务")

        tasks = [
            ("领取邮件", self.claim_mail),
            ("领取环期任务奖励", self.claim_battle_pass_rewards),
            ("完成每日活跃度", self.complete_daily_activities),
            ("领取活跃度奖励", self.claim_activity_rewards),
        ]

        self._reset_task_status(tasks)

        for key, func in tasks:
            self.execute_task(key, func)

        self._ensure_daily_main()
        self._print_result()

    def execute_task(self, key, func):
        """执行单个子任务。

        Args:
            key (str): 任务名称
            func (Callable): 任务执行函数

        根据配置决定是否跳过，并记录执行结果。
        """

        self.task_status["pending"].remove(key)

        # 开关控制
        if not self.config.get(key, False):
            self._mark_skipped(key, "配置已关闭")
            return

        self.current_task_key = key
        self.log_info(f"开始任务: {key}")

        self._ensure_daily_main()

        result = func()

        if result is False:
            self.task_status["failed"].append(key)
            self.screenshot(f"fail_{key}")
            self.log_info(f"任务失败: {key}")
            self.current_task_key = None
            return

        if result is self.TASK_SKIPPED:
            self._mark_skipped(key, self.task_skip_reasons.get(key, ""))
            self.log_info(f"任务跳过: {key}")
            self.current_task_key = None
            return

        self.task_status["success"].append(key)
        self.log_info(f"任务完成: {key}")
        self.current_task_key = None

    def _reset_task_status(self, tasks):
        """重置任务状态。

        Args:
            tasks (list): [(key, func)] 任务列表
        """
        self.task_status = {
            "success": [],
            "failed": [],
            "skipped": [],
            "pending": [t[0] for t in tasks],
        }
        self.task_skip_reasons = {}

    def _set_skip_reason(self, key, reason):
        if reason:
            self.task_skip_reasons[key] = reason

    def _mark_skipped(self, key, reason=""):
        self.task_status["skipped"].append(key)
        self._set_skip_reason(key, reason)

    def _ensure_daily_main(self):
        """回到已登录的主界面，避免 DailyTask 误走登录页 OCR 检测。"""
        self.info_set("current task", "wait daily main esc=True")
        if self.wait_until(
            lambda: self.in_team_and_world() or self.handle_monthly_card(),
            time_out=30,
            raise_if_not_found=False,
            post_action=lambda: self.back(after_sleep=2),
        ):
            self._logged_in = True
            self.sleep(0.5)
            self.info_set("current task", "in daily main")
            return True

        raise Exception("Please start in game world and in team!")

    def _print_result(self):
        """输出任务执行结果。"""
        self.info_set("success", f"{self.task_status['success']}")
        self.info_set("failed", f"{self.task_status['failed']}")
        self.info_set("skipped", f"{self.task_status['skipped']}")
        if self.task_skip_reasons:
            self.info_set("skip_reasons", f"{self.task_skip_reasons}")

    def _handle_exception(self, e):
        """处理执行异常并记录状态。

        Args:
            e (Exception): 捕获到的异常
        """
        self.screenshot(f"{datetime.now().strftime('%Y%m%d')}_exception")

        if self.current_task_key:
            self.info_set("当前失败任务", self.current_task_key)
        self._print_result()
        raise e

    def _open_mail_panel(self):
        """打开mail panel。

        Returns:
            bool: True 表示成功，False 表示失败
        """
        self.log_info("正在打开邮件面板")
        self.openESCpanel()
        self.click_ui(0.8707, 0.8736, after_sleep=1)
        result = self.wait_panel(Labels.mail_panel)
        if not result:
            self.log_error("无法找到邮件面板", notify=True)
            raise Exception("can't find mail panel")
        return result

    def claim_mail(self):
        """领取邮件"""
        self.log_info("正在领取邮件奖励")
        self._open_mail_panel()
        self.click_ui(0.1289, 0.9299)
        self.sleep(1)
        return True

    def _open_activity_panel(self):
        """打开 F1 每日活跃度面板。"""
        self.openF1panel()
        self.info_set("每日活跃度目标栏目", f"第{self.DAILY_ACTIVITY_TAB_INDEX}栏目")
        self.click_ui(*self.DAILY_ACTIVITY_TAB_POSITION, after_sleep=1)
        if not self.wait_panel(Labels.f1_activity_panel):
            self.log_error("无法找到每日活跃度面板", notify=True)
            return False
        return True

    def complete_daily_activities(self):
        """执行操作完成每日活跃度"""
        self.log_info("正在处理每日活跃度任务")
        if not self._open_activity_panel():
            return False

        analysis = self._analyze_daily_activity()
        self._record_daily_activity_analysis(analysis)
        if analysis.state == DailyActivityState.PANEL_NOT_FOUND:
            return False
        if analysis.state == DailyActivityState.NO_ACTION_NEEDED:
            self._set_skip_reason("完成每日活跃度", analysis.reason)
            self.log_info(analysis.reason)
            return self.TASK_SKIPPED

        claimed = self._claim_visible_activity_missions()
        if claimed:
            self.log_info(f"已领取 {claimed} 个已完成的每日活跃度任务")
            return True

        completed_simple_actions = self._completed_simple_activity_actions()
        if completed_simple_actions:
            self.info_set("每日活跃度已尝试动作", "/".join(completed_simple_actions))

        self.info_set("每日活跃度缺失特征", self.DAILY_ACTIVITY_MISSING_FEATURES)
        self._set_skip_reason("完成每日活跃度", analysis.reason)
        self.log_info(
            "未检测到可领取的每日活跃度任务；"
            f"自动完成具体任务仍缺少特征: {self.DAILY_ACTIVITY_MISSING_FEATURES}"
        )
        return self.TASK_SKIPPED

    def _analyze_daily_activity(self):
        return DailyActivityAnalyzer(self).analyze()

    def _record_daily_activity_analysis(self, analysis):
        self.info_set("每日活跃度状态", analysis.state.value)
        self.info_set("每日活跃度状态原因", analysis.reason)

    def _completed_simple_activity_actions(self):
        """返回本轮已经执行过、可能贡献每日活跃度的简单动作。"""
        success = self.task_status.get("success", [])
        return [key for key in self.SIMPLE_ACTIVITY_ACTIONS if key in success]

    def _claim_visible_activity_missions(self, max_clicks=None):
        """领取当前活跃页中已完成、可见的每日任务奖励。"""
        max_clicks = max_clicks or self.MAX_ACTIVITY_MISSION_CLAIMS
        claimed = 0

        for _ in range(max_clicks):
            target = self.find_one(Labels.f1_activity_mission)
            if not target:
                break

            self.click(target)
            claimed += 1
            self.sleep(1)

        if claimed == max_clicks and self.find_one(Labels.f1_activity_mission):
            self.log_warning("每日活跃度任务领取达到上限，可能仍有可领取项目")

        return claimed

    def claim_activity_rewards(self):
        """领取活跃度奖励"""
        self.log_info("正在领取活跃度奖励")
        if not self._open_activity_panel():
            return False

        claimed = self._claim_visible_activity_missions()
        if claimed:
            self.log_info(f"领取活跃度奖励前已先领取 {claimed} 个每日任务奖励")

        if target := self._get_activity_reward_box():
            self.click(target)
            self.sleep(1)
        else:
            self.info_set("活跃度奖励状态", self.ACTIVITY_REWARD_UNAVAILABLE)
            self._set_skip_reason("领取活跃度奖励", self.ACTIVITY_REWARD_UNAVAILABLE)
            self.log_info(self.ACTIVITY_REWARD_UNAVAILABLE)
            return self.TASK_SKIPPED
        return True

    def _get_activity_reward_box(self):
        target = None
        box = self.get_box_by_name(Labels.box_f1_activity_reward)
        mask = iu.binarize_bgr_by_brightness(self.frame, threshold=245, to_bgr=False)
        mask = iu.dilate_mask(mask, kernel_size=7, to_bgr=True)
        reward_boxes = find_color_rectangles(
            mask, color_range=text_white_color, min_width=10, min_height=10, box=box, threshold=0.6
        )
        if reward_boxes:
            target = max(reward_boxes, key=lambda x: x.x)
            self.draw_boxes(boxes=target)
        return target

    def claim_battle_pass_rewards(self):
        """领取环期任务奖励"""
        self.log_info("正在领取环期任务奖励")
        self.openF2panel()
        self.click_ui(0.6934, 0.8229)
        self.sleep(1)
        self.click_ui(0.0570, 0.3451)
        if not self.wait_panel(Labels.f2_mission_panel):
            self.log_error("无法找到环期任务面板")
            return False
        self.click_ui(0.8777, 0.8187)
        self.sleep(1)
        return True
