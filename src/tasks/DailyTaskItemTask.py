from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.daily_items import DailyTaskItemRuntime
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class DailyTaskItemTask(NTEOneTimeTask, BaseNTETask):
    """每日已完成任务奖励领取.

    扫描 F1 活跃度面板里待领取的任务卡片, 点击 "领取" 按钮并验证.
    默认关闭, 缺失配置项视为关闭.
    """

    supported_languages = ["zh_CN"]

    CONF_CLAIM_TASK_ITEMS = "领取已完成每日任务"
    CONF_MAX_CLAIMS = "单次最大领取数量"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "已完成每日任务领取"
        self.description = "在 F1 活跃度面板里领取标记为已完成的每日子任务奖励 (默认关闭)"
        self.icon = FluentIcon.ACCEPT
        self.default_config.update(
            {
                self.CONF_CLAIM_TASK_ITEMS: False,
                self.CONF_MAX_CLAIMS: 10,
            }
        )
        self.config_description.update(
            {
                self.CONF_CLAIM_TASK_ITEMS: "启用后才会真实点击 '领取'; 关闭时只检测不动作",
                self.CONF_MAX_CLAIMS: "单次最多领取的任务卡片数量",
            }
        )
        self.add_exit_after_config()

    def run(self):
        super().run()
        try:
            return self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("DailyTaskItemTask error", e)
            raise

    def do_run(self):
        if not bool(self._config_value(self.CONF_CLAIM_TASK_ITEMS, False)):
            self.log_info("已完成每日任务领取未启用, 跳过")
            return True

        raw_max_claims = self._config_value(self.CONF_MAX_CLAIMS, 10)
        if raw_max_claims is None:
            raw_max_claims = 10
        try:
            max_claims = int(raw_max_claims)
        except (TypeError, ValueError):
            max_claims = 10
        max_claims = max(0, min(50, max_claims))

        runtime = DailyTaskItemRuntime(self)
        result = runtime.run(max_claims=max_claims, allow_real_claim=True)

        if result.get("ok") and result.get("task_completed"):
            self.log_info(
                f"已完成每日任务奖励领取完成: {result.get('claimed_count', 0)} 张"
            )
            return True
        if result.get("ok"):
            reason = result.get("reason") or "no_action"
            self.log_info(f"已完成每日任务无可领取: {reason}")
            return True

        reason = result.get("reason") or "claim_failed"
        self.log_error(f"已完成每日任务领取失败: {reason}")
        return False

    def _config_value(self, key, default=None):
        config = getattr(self, "config", None)
        if config is None:
            return default
        getter = getattr(config, "get", None)
        if callable(getter):
            return getter(key, default)
        try:
            return config[key]
        except (KeyError, TypeError, AttributeError):
            return default
