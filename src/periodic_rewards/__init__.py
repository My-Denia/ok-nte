"""环期任务奖励领取业务模块.

与 BaseTask 解耦的运行时, 由 :class:`src.tasks.PeriodicRewardsTask` 调用.
"""

from src.periodic_rewards.runtime import PeriodicRewardsRuntime

__all__ = ["PeriodicRewardsRuntime"]
