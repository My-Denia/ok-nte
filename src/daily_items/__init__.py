"""每日已完成任务领取业务模块.

与 BaseTask 解耦的运行时, 由 :class:`src.tasks.DailyTaskItemTask` 调用.
"""

from src.daily_items.runtime import DailyTaskItemRuntime

__all__ = ["DailyTaskItemRuntime"]
