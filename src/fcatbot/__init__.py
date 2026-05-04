"""
Fcatbot —— 异步 Bot 框架统一入口
"""

from fcatbot.__main__ import Bot, ConnectionService
from fcatbot.utils.logger import setup_logging

setup_logging()
__all__ = ["Bot", "ConnectionService"]
