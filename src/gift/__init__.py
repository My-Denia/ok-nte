"""赠送礼物业务模块.

与 BaseTask 解耦的运行时, 由 :class:`src.tasks.GiftTask` 调用.
"""

from src.gift.runtime import GiftRuntime

__all__ = ["GiftRuntime"]
