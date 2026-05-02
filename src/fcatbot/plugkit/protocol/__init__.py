"""
Plugkit 协议层
"""

from fcatbot.plugkit.protocol.bus import EventBus, GlobalInterceptor, HandlerInterceptor
from fcatbot.plugkit.protocol.data import ConfigSection, PluginConfig, PluginData, Value
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.protocol.exceptions import (
    BusClosedError,
    PluginDataError,
    PluginDependencyError,
    PluginError,
    PluginEventLoopError,
    PluginFatalError,
    PluginLoadError,
    PluginNotLoadedError,
    PluginStateError,
)
from fcatbot.plugkit.protocol.manager import PluginManager
from fcatbot.plugkit.protocol.plugin import Plugin, PluginMixin
from fcatbot.plugkit.protocol.service import (
    ServiceConflict,
    ServiceError,
    ServiceInfo,
    ServiceNotFound,
    ServiceRegistry,
    VersionMismatch,
)
from fcatbot.plugkit.protocol.state import PluginState, PluginStatus
from fcatbot.plugkit.protocol.storage import (
    JSONBackend,
    PickleBackend,
    StorageBackend,
    YAMLBackend,
)

__all__ = [
    # bus
    "EventBus",
    "GlobalInterceptor",
    "HandlerInterceptor",
    # data
    "ConfigSection",
    "PluginConfig",
    "PluginData",
    "Value",
    # event
    "Event",
    # exceptions
    "BusClosedError",
    "PluginDataError",
    "PluginDependencyError",
    "PluginError",
    "PluginEventLoopError",
    "PluginFatalError",
    "PluginLoadError",
    "PluginNotLoadedError",
    "PluginStateError",
    # manager
    "PluginManager",
    # plugin
    "Plugin",
    "PluginMixin",
    # service
    "ServiceConflict",
    "ServiceError",
    "ServiceInfo",
    "ServiceNotFound",
    "ServiceRegistry",
    "VersionMismatch",
    # state
    "PluginState",
    "PluginStatus",
    # storage
    "JSONBackend",
    "PickleBackend",
    "StorageBackend",
    "YAMLBackend",
]
