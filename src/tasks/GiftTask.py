from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.gift import GiftRuntime
from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask


class GiftTask(NTEOneTimeTask, BaseNTETask):
    """赠送礼物自动化任务.

    默认关闭真实赠送动作, 仅在用户显式启用 ``CONF_SEND_GIFT`` 后才会
    点击 "赠送" 按钮. 缺失配置项视为关闭.
    """

    supported_languages = ["zh_CN"]

    CONF_SEND_GIFT = "赠送礼物"
    CONF_SEND_COUNT = "赠送次数"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "每日赠礼"
        self.description = "自动给当前角色赠送一份每日礼物 (默认关闭)"
        self.icon = FluentIcon.SEND
        self.default_config.update(
            {
                self.CONF_SEND_GIFT: False,
                self.CONF_SEND_COUNT: 1,
            }
        )
        self.config_description.update(
            {
                self.CONF_SEND_GIFT: "启用后才会真实点击 '赠送'; 关闭时只检测不动作",
                self.CONF_SEND_COUNT: "本次赠送次数 (当前仅支持 1)",
            }
        )
        self.config_type.update(
            {
                self.CONF_SEND_COUNT: {"type": "drop_down", "options": ["1"]},
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
            self.log_error("GiftTask error", e)
            raise

    def _config_value(self, key, default=None):
        config = getattr(self, "config", None)
        getter = getattr(config, "get", None)
        if callable(getter):
            return getter(key, default)
        try:
            return config[key]
        except (KeyError, TypeError):
            return default

    def do_run(self):
        if not bool(self._config_value(self.CONF_SEND_GIFT, False)):
            self.log_info("每日赠礼未启用, 跳过")
            return True

        try:
            send_count = int(self._config_value(self.CONF_SEND_COUNT, 1) or 1)
        except (TypeError, ValueError):
            send_count = 1

        runtime = GiftRuntime(self)
        result = runtime.run(send_count=send_count, allow_real_send=True)

        if result.get("ok") and result.get("task_completed"):
            self.log_info("每日赠礼完成")
            return True
        if result.get("ok"):
            reason = result.get("reason") or "no_action"
            self.log_info(f"每日赠礼无动作: {reason}")
            return True

        reason = result.get("reason") or "gift_failed"
        self.log_error(f"每日赠礼失败: {reason}")
        return False
