"""Pytest 配置 — 共享的 fixtures 和清理逻辑。"""

import asyncio
import gc
import warnings

import pytest


@pytest.fixture(autouse=True)
def cleanup_pending_tasks():
    """每个测试结束后自动清理挂起的 asyncio 任务。

    防止因 WebSocket 后台协程生命周期超出测试范围而产生的
    'Task was destroyed but it is pending!' 警告。
    """
    yield
    # 每个测试后，取消并排空所有残留任务
    try:
        loop = asyncio.get_running_loop()
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            for task in pending:
                task.cancel()
            # 短暂等待，让取消操作传播完成
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    except RuntimeError:
        # 没有运行中的事件循环 — 无需清理
        pass
    # 强制垃圾回收，清除已销毁任务的引用
    gc.collect()


# 静默来自后台任务清理的 asyncio 警告
warnings.filterwarnings(
    "ignore",
    message="Task was destroyed but it is pending!",
    category=RuntimeWarning,
)
