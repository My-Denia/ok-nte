from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.periodic_rewards import PeriodicRewardsRuntime
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class PeriodicRewardsTask(NTEOneTimeTask, BaseNTETask):
    """环期任务奖励领取.

    依赖简体中文 OCR 文案 ("领取" / "全部领取"), 默认关闭真实点击.
    """

    supported_languages = ["zh_CN"]

    CONF_CLAIM_PERIODIC_REWARDS = "领取环期任务奖励"
    CONF_MAX_MISSION_CLAIMS = "单次最大环期任务领取数量"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "环期任务奖励领取"
        self.description = "在 F2 环期任务面板领取可领取奖励 (默认关闭)"
        self.icon = FluentIcon.ACCEPT
        self.default_config.update(
            {
                self.CONF_CLAIM_PERIODIC_REWARDS: False,
                self.CONF_MAX_MISSION_CLAIMS: 5,
            }
        )
        self.config_description.update(
            {
                self.CONF_CLAIM_PERIODIC_REWARDS: "启用后才会真实点击 '领取' / '全部领取'",
                self.CONF_MAX_MISSION_CLAIMS: "单次最多领取的环期任务条目数量",
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
            self.log_error("PeriodicRewardsTask error", e)
            raise

    def do_run(self):
        if not bool(self._config_value(self.CONF_CLAIM_PERIODIC_REWARDS, False)):
            self.log_info("环期任务奖励领取未启用, 跳过")
            return True

        raw_max_claims = self._config_value(self.CONF_MAX_MISSION_CLAIMS, 5)
        if raw_max_claims is None:
            raw_max_claims = 5
        try:
            max_mission_claims = int(raw_max_claims)
        except (TypeError, ValueError):
            max_mission_claims = 5
        max_mission_claims = max(0, min(50, max_mission_claims))

        runtime = PeriodicRewardsRuntime(self)
        result = runtime.run(
            max_mission_claims=max_mission_claims,
            allow_real_claim=True,
        )

        if result.get("ok") and result.get("task_completed"):
            self.log_info("环期任务奖励领取完成")
            return True
        if result.get("ok"):
            reason = result.get("reason") or "no_action"
            self.log_info(f"环期任务奖励无可领取: {reason}")
            return True

        reason = result.get("reason") or "periodic_rewards_failed"
        self.log_error(f"环期任务奖励领取失败: {reason}")
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
