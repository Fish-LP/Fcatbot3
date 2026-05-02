"""
Plugkit 运行时层
"""

from fcatbot.plugkit.runtime.bus import BackpressureError, Bus
from fcatbot.plugkit.runtime.decorators import on_event
from fcatbot.plugkit.runtime.lifecycle import LifecycleManager
from fcatbot.plugkit.runtime.loader import PluginLoader
from fcatbot.plugkit.runtime.registry import PluginServiceRegistry
from fcatbot.plugkit.runtime.resolver import resolve_load_order
from fcatbot.plugkit.runtime.watcher import PluginWatcher

__all__ = [
    "Bus",
    "BackpressureError",
    "on_event",
    "LifecycleManager",
    "PluginLoader",
    "PluginServiceRegistry",
    "resolve_load_order",
    "PluginWatcher",
]
