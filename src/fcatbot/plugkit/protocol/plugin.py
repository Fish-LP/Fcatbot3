import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, ClassVar, Protocol

from fcatbot.plugkit.protocol.exceptions import (
    PluginEventLoopError,
    PluginNotLoadedError,
)
from fcatbot.plugkit.protocol.service import ServiceRegistry

from .bus import EventBus
from .data import PluginConfig
from .state import PluginStatus


class PluginMixin(Protocol):
    """Plugin 混入类协议。

    继承此协议的类可通过多重继承与 ``Plugin`` 组合，以扩展插件功能。
    生命周期管理器会在插件加载和卸载时自动调用以下类方法钩子。
    """

    if TYPE_CHECKING:
        name: ClassVar[str]
        version: ClassVar[str]
        dependencies: ClassVar[dict[str, str]] = {}
        provides: ClassVar[dict[str, Any]] = {}
        mixins: ClassVar[list[type["PluginMixin"]] | None] = None

        _status: PluginStatus = PluginStatus()
        _tasks: set[asyncio.Task] = set()
        _handler_tokens: list[str] = []

        # 由 PluginLoader 在加载时注入：文件系统层面的真实模块名
        _plugin_source_name: ClassVar[str] = ""
        # 由 LifecycleManager 注入
        _debug: bool | None = None
        _bus: EventBus | None = None
        _data_root: Path | None = None
        _registry: ServiceRegistry | None = None

    @property
    def bus(self) -> EventBus:
        if self._bus is None:
            raise PluginNotLoadedError(self.name)
        return self._bus

    @property
    def debug(self) -> bool:
        if self._debug is None:
            raise PluginNotLoadedError(self.name)
        return self._debug

    @property
    def status(self) -> PluginStatus:
        return self._status

    @property
    def registry(self) -> ServiceRegistry:
        """获取当前插件绑定的服务注册表。

        Returns:
            绑定的 ServiceRegistry 实例。

        Raises:
            PluginNotLoadedError: 若 LifecycleManager 尚未完成注入。
        """
        if self._registry is None:
            raise PluginNotLoadedError(self.name, "has no registry bound")
        return self._registry

    def on_mixin_load(self, plugin: "Plugin", env: Any) -> None | Awaitable[None]:
        """插件加载时调用。

        这是一个实例方法，self 是混入类在目标插件实例上的绑定实例。

        Args:
            plugin: 被混入的目标插件实例（与 self 为同一对象）。
            env: 包含 ``data_root`` 和 ``bus`` 属性的环境对象。
        """
        ...

    def on_mixin_unload(self, plugin: "Plugin", env: Any) -> None | Awaitable[None]:
        """插件卸载时调用。

        这是一个实例方法，self 是混入类在目标插件实例上的绑定实例。

        Args:
            plugin: 被混入的目标插件实例。
            env: 卸载环境（当前为 ``None``）。
        """
        ...


class Plugin(ABC):
    name: ClassVar[str]
    version: ClassVar[str]
    dependencies: ClassVar[dict[str, str]] = {}
    provides: ClassVar[dict[str, Any]] = {}
    mixins: ClassVar[list[type[PluginMixin]] | None] = None

    _status: PluginStatus = PluginStatus()
    _tasks: set[asyncio.Task] = set()
    _handler_tokens: list[str] = []

    # 由 PluginLoader 在加载时注入：文件系统层面的真实模块名
    _plugin_source_name: ClassVar[str] = ""
    # 由 LifecycleManager 注入
    _debug: bool | None = None
    _bus: EventBus | None = None
    _data_root: Path | None = None
    _registry: ServiceRegistry | None = None

    def __init__(self):
        self._tasks: set[asyncio.Task] = set()
        self._handler_tokens = []

    @abstractmethod
    def on_load(self) -> None | Awaitable[None]:
        """插件被加载到内存时调用（此时 bus / data_root(属性) 已绑定）"""
        raise NotImplementedError

    def on_start(self) -> None | Awaitable[None]:
        """插件被启动（进入事件循环）时调用"""
        pass

    def on_stop(self) -> None | Awaitable[None]:
        """插件被停止时调用（事件循环仍在运行）"""
        pass

    def on_unload(self) -> None | Awaitable[None]:
        """插件被卸载时调用（bus 即将解绑）"""
        pass

    async def run(self) -> None:
        """插件主协程，生命周期内持续运行"""
        pass

    # ---------- reload 生命周期钩子 ----------

    def on_before_reload(self) -> None | Awaitable[None]:
        """热重载前调用：可在此保存临时状态"""
        pass

    def on_after_reload(self) -> None | Awaitable[None]:
        """热重载后调用：新实例已替换旧实例，可在此恢复状态"""
        pass

    def on_config_change(
        self, name: str, config: PluginConfig
    ) -> None | Awaitable[None]:
        """外部配置文件被修改时调用"""
        config.reload()

    @property
    def bus(self) -> EventBus:
        if self._bus is None:
            raise PluginNotLoadedError(self.name)
        return self._bus

    @property
    def debug(self) -> bool:
        if self._debug is None:
            raise PluginNotLoadedError(self.name)
        return self._debug

    @property
    def status(self) -> PluginStatus:
        return self._status

    @property
    def registry(self) -> ServiceRegistry:
        """获取当前插件绑定的服务注册表。

        Returns:
            绑定的 ServiceRegistry 实例。

        Raises:
            PluginNotLoadedError: 若 LifecycleManager 尚未完成注入。
        """
        if self._registry is None:
            raise PluginNotLoadedError(self.name, "has no registry bound")
        return self._registry

    def create_task(self, coro, *, name: str | None = None) -> asyncio.Task:
        """创建绑定到插件生命周期的后台任务"""  # 兼容测试等非运行 loop 场景
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop_policy().get_event_loop()
            except RuntimeError:
                loop = None

        if loop is None or loop.is_closed():
            raise PluginEventLoopError(
                f"No active event loop to create task for plugin '{self.name}'"
            )

        task = loop.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _cancel_all_tasks(self) -> None:
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()

    def get_data_path(self, name: str) -> Path:
        if self._data_root is None:
            raise PluginNotLoadedError(self.name)
        return self._data_root / self.name / "data" / f"{name}.yml"

    def get_config_path(self, name: str) -> Path:
        if self._data_root is None:
            raise PluginNotLoadedError(self.name)
        return self._data_root / self.name / "config" / f"{name}.yml"
