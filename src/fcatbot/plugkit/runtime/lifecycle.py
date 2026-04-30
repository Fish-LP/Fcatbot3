# runtime/lifecycle.py
import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from fcatbot.plugkit.protocol.bus import EventBus
from fcatbot.plugkit.protocol.data import PluginConfig, PluginData
from fcatbot.plugkit.protocol.exceptions import PluginFatalError
from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.protocol.state import PluginState
from fcatbot.plugkit.runtime.registry import PluginServiceRegistry

from .resolver import resolve_load_order
from .watcher import PluginWatcher

logger = logging.getLogger("plugkit.lifecycle")


@dataclass
class _Entry:
    plugin: Plugin
    fw_state: PluginState = PluginState.Unloaded
    run_task: Optional[asyncio.Task] = None


class LifecycleManager:
    def __init__(
        self,
        bus: EventBus,
        data_root: Path,
        loader=None,
        *,
        strict: bool = False,
        dev: bool = False,
        debug: bool = False,
        plugin_dirs: Optional[list[Path]] = None,
    ):
        self._bus = bus
        self._data_root = Path(data_root)
        self._loader = loader
        self._strict = strict
        self._dev = dev
        self._debug = debug
        self._plugin_dirs = [Path(d) for d in plugin_dirs] if plugin_dirs else []
        self._plugins: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._fatal_error: Optional[asyncio.Future] = None
        self._watcher: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._registry = PluginServiceRegistry()

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        self._watcher = PluginWatcher(self) if dev else None

        if hasattr(bus, "start") and not getattr(bus, "_started", False):
            bus.start()

    async def load(self, plugin_cls: type[Plugin]) -> Plugin:
        async with self._lock:
            return await self._load_locked(plugin_cls)

    async def unload(self, name: str) -> None:
        async with self._lock:
            await self._unload_locked(name)

    async def start(self, name: str) -> None:
        async with self._lock:
            await self._start_locked(name)

    @staticmethod
    def _collect_mixins(plugin_cls: type[Plugin]) -> list[type]:
        if "mixins" in plugin_cls.__dict__:
            explicit = plugin_cls.__dict__["mixins"]
            if explicit is None:
                return []
            else:
                for m in explicit:
                    if m not in plugin_cls.__mro__:
                        raise TypeError(
                            f"{plugin_cls.__name__} declares {m.__name__} in mixins "
                            f"but does not inherit it"
                        )
                return list(explicit)

        mixins = []
        for cls in plugin_cls.__mro__:
            if cls is Plugin or cls is object:
                continue
            if hasattr(cls, "on_mixin_load") or hasattr(cls, "on_mixin_unload"):
                mixins.append(cls)
        return mixins

    @staticmethod
    def _call_mixin_method(
        mixin: type, method_name: str, plugin: Plugin, env: Any
    ) -> Any:
        """
        @classmethod / 设计文档约定: on_mixin_load(cls, plugin, env)
        """
        method = getattr(mixin, method_name, None)
        if method is None:
            return None

        return method(plugin, env)

    async def _load_locked(self, plugin_cls: type[Plugin]) -> Plugin:
        if plugin_cls.name in self._plugins:
            raise RuntimeError(f"Plugin {plugin_cls.name} already loaded")

        if self._strict:
            for dep_name in plugin_cls.dependencies:
                if dep_name not in self._plugins:
                    raise RuntimeError(
                        f"Strict mode: dependency '{dep_name}' required by "
                        f"'{plugin_cls.name}' is not loaded"
                    )

        self._check_plugin_dependencies(plugin_cls)
        plugin = plugin_cls()

        # 注入
        plugin._bus = self._bus
        plugin._debug = self._debug
        plugin._data_root = self._data_root

        entry = _Entry(plugin=plugin, fw_state=PluginState.Loaded)
        self._plugins[plugin.name] = entry
        self._set_status(plugin, PluginState.Loaded, loaded_at=time.time())

        try:
            # 服务注册注入
            plugin._registry = self._registry
            await self._auto_register_services(plugin)

            # 先绑定数据路径，再调用 on_load，允许用户在 on_load 中操作数据
            await self._bind_data(plugin)
            env = type(
                "Env",
                (),
                {
                    "data_root": self._data_root,
                    "bus": self._bus,
                },
            )()

            for mixin in self._collect_mixins(plugin_cls):
                if hasattr(mixin, "on_mixin_load"):
                    await self._run_async(
                        self._call_mixin_method(mixin, "on_mixin_load", plugin, env)
                    )

            await self._run_async(plugin.on_load())
            await self._bind_data(plugin)  # 二次绑定处理 on_load 动态添加的配置
            await self._bind_events(plugin)

            if self._watcher:
                source_name = getattr(
                    plugin_cls, "_plugin_source_name", plugin_cls.name
                )
                code_path = (
                    self._loader.get_source_path(source_name) if self._loader else None
                )
                self._watcher.add_plugin(plugin, code_path=code_path)

            return plugin
        except Exception:
            # 加载中途失败，自清理，防止状态泄漏
            self._registry.unregister_by_provider(plugin.name)
            self._plugins.pop(plugin.name, None)
            raise

    async def _auto_register_services(self, plugin: Plugin) -> None:
        """将插件声明的 provides 自动注册到注册表。

        扫描 Plugin.provides 字典，将每个服务名与对应实例注册到
        LifecycleManager 内部的 PluginServiceRegistry。

        Args:
            plugin: 已实例化且已完成 on_load 的插件对象。
        """
        cls = type(plugin)
        if not cls.provides:
            return

        for svc_name, _contract in cls.provides.items():
            instance = None
            short_name = svc_name.split(".")[-1]

            # 1. 尝试完整属性名（如 self."demo.echo" —— 通常因含点号而失败）
            instance = getattr(plugin, svc_name, None)

            # 2. 尝试短名（如 demo.echo → echo）
            if instance is None and short_name != svc_name:
                instance = getattr(plugin, short_name, None)

            # 3. 契约是类时自动实例化，并挂载到短名属性供插件访问
            # if instance is None and isinstance(_contract, type):
            #     try:
            #         instance = _contract()
            #         setattr(plugin, short_name, instance)
            #     except Exception:
            #         pass

            # 4. 最终回退到插件自身
            if instance is None:
                instance = plugin
                logger.debug(
                    "Plugin '%s' provides '%s' using self (no attribute '%s')",
                    plugin.name,
                    svc_name,
                    svc_name,
                )

            self._registry.register(
                name=svc_name,
                instance=instance,
                provider=plugin.name,
                version=getattr(instance, "__version__", plugin.version),
            )

    async def load_all(self, plugin_classes: list[type[Plugin]]) -> None:
        graph = {}
        all_names = {cls.name for cls in plugin_classes}
        loaded_names = set(self._plugins.keys())
        loaded_in_batch: list[str] = []

        for cls in plugin_classes:
            deps = set(cls.dependencies.keys()) & all_names
            external = set(cls.dependencies.keys()) - all_names - loaded_names
            if external:
                if self._strict:
                    raise RuntimeError(
                        f"Strict mode: plugin '{cls.name}' has unloaded "
                        f"dependencies: {external}"
                    )
                logger.warning(
                    "Plugin %s depends on %s which are not in load_all batch "
                    "and not already loaded",
                    cls.name,
                    external,
                )
            graph[cls.name] = deps

        order = resolve_load_order(graph)
        name_cls = {cls.name: cls for cls in plugin_classes}

        try:
            for name in order:
                loaded_in_batch.append(name)  # ← 先记录
                await self.load(name_cls[name])  # ← 再加载
        except Exception:
            logger.exception("load_all failed, rolling back batch")
            for name in reversed(loaded_in_batch):
                try:
                    await self.unload(name)
                except Exception:
                    logger.exception("Rollback unload failed: %s", name)
            raise

    async def _start_locked(self, name: str) -> None:
        entry = self._plugins.get(name)
        if not entry or entry.fw_state != PluginState.Loaded:
            raise RuntimeError(f"Cannot start {name}: not Loaded")
        plugin = entry.plugin
        await self._run_async(plugin.on_start())
        if inspect.iscoroutinefunction(plugin.run):
            entry.run_task = asyncio.create_task(self._wrap_run(entry))
        self._set_status(plugin, PluginState.Running, started_at=time.time())
        entry.fw_state = PluginState.Running

    async def stop(self, name: str, timeout: float = 30.0) -> None:
        async with self._lock:
            entry = self._plugins.get(name)
            if not entry or entry.fw_state != PluginState.Running:
                return
            await self._do_stop(entry, timeout)

    async def _unload_locked(self, name: str) -> None:
        entry = self._plugins.pop(name, None)
        if not entry:
            return

        if self._watcher:
            self._watcher.remove_plugin(name)

        if entry.fw_state == PluginState.Running:
            await self._do_stop(entry, timeout=5.0)
        plugin = entry.plugin

        plugin._cancel_all_tasks()
        self._registry.unregister_by_provider(plugin.name)

        for mixin in reversed(self._collect_mixins(type(plugin))):
            if hasattr(mixin, "on_mixin_unload"):
                await self._run_async(
                    self._call_mixin_method(mixin, "on_mixin_unload", plugin, None)
                )

        for token in plugin._handler_tokens:
            self._bus.unsubscribe(token)
        plugin._handler_tokens.clear()

        for attr_name in dir(plugin):
            attr = getattr(plugin, attr_name, None)
            if isinstance(attr, PluginData):
                try:
                    if (
                        getattr(attr, "_path", None) is not None
                    ):  # 跳过从未绑定路径的数据
                        attr.save()
                except Exception:
                    logger.exception(
                        "Error saving %s.%s during unload", name, attr_name
                    )

        await self._run_async(plugin.on_unload())
        self._set_status(plugin, PluginState.Unloaded, stopped_at=time.time())

    async def reload(self, name: str) -> Plugin:
        async with self._lock:
            entry = self._plugins.get(name)
            if not entry:
                raise RuntimeError(f"Plugin {name} not loaded")
            plugin_cls = type(entry.plugin)
            was_running = entry.fw_state == PluginState.Running

            await self._run_async(entry.plugin.on_before_reload())

            await self._unload_locked(name)
            if not self._loader:
                raise RuntimeError("Reload requires loader")
            source_name = getattr(plugin_cls, "_plugin_source_name", name)
            new_cls = await asyncio.to_thread(self._loader.load_class, source_name)
            plugin = await self._load_locked(new_cls)

            await self._run_async(plugin.on_after_reload())

            if was_running:
                await self._start_locked(name)
            return plugin

    def notify_config_file_change(self, plugin_name: str, path: Path) -> None:
        coro = self._handle_config_file_change(plugin_name, path)
        loop = self._loop
        if loop is not None and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            try:
                loop = asyncio.get_running_loop()
                if not loop.is_closed():
                    loop.create_task(coro)
                else:
                    logger.warning(
                        "Event loop closed, cannot notify config change for %s",
                        plugin_name,
                    )
            except RuntimeError:
                logger.warning(
                    "No event loop available to notify config change for %s",
                    plugin_name,
                )

    async def _handle_config_file_change(self, plugin_name: str, path: Path) -> None:
        plugin = self.get(plugin_name)
        if not plugin:
            return

        config_name = path.stem

        for attr_name in dir(plugin):
            attr = getattr(plugin, attr_name, None)
            if not isinstance(attr, PluginConfig):
                continue
            if attr._name != config_name:
                continue

            logger.info("External config change: %s.%s", plugin_name, attr_name)
            try:
                await self._run_async(plugin.on_config_change(config_name, attr))
            except Exception:
                logger.exception("Config hook failed: %s.%s", plugin_name, attr_name)
            return

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        self._fatal_error = loop.create_future()

        if self._watcher:
            self._watcher.start()

        try:
            await self._fatal_error
        except asyncio.CancelledError:
            logger.info("Serve cancelled, initiating shutdown...")
        finally:
            if self._watcher:
                self._watcher.stop()
            await self.shutdown()

    def _on_fatal(self, plugin_name: str, error: Exception) -> None:
        if self._fatal_error and not self._fatal_error.done():
            exc = PluginFatalError(plugin_name, error)
            self._fatal_error.set_exception(exc)

    async def shutdown(self) -> None:
        names = list(self._plugins.keys())
        for name in reversed(names):  # 逆序
            try:
                await self.unload(name)
            except Exception:
                logger.exception("Error unloading %s during shutdown", name)
        try:
            await self._bus.close()
        except Exception:
            logger.exception("Error closing bus")

    def get(self, name: str) -> Plugin | None:
        entry = self._plugins.get(name)
        return entry.plugin if entry else None

    def list_names(self) -> list[str]:
        return list(self._plugins.keys())

    def is_running(self, name: str) -> bool:
        entry = self._plugins.get(name)
        return entry is not None and entry.fw_state == PluginState.Running

    async def _bind_events(self, plugin: Plugin) -> None:
        cls = type(plugin)
        tokens: list[str] = []
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name, None)
            if attr is None or not hasattr(attr, "__event_spec__"):
                continue
            handler = getattr(plugin, attr_name)

            async def wrapper(event, _handler=handler, _filter=attr.__filter__):
                if _filter and not _filter(event):
                    return
                if inspect.iscoroutinefunction(_handler):
                    await _handler(event)
                else:
                    _handler(event)

            token = self._bus.subscribe(
                attr.__event_spec__,
                wrapper,
                priority=attr.__priority__,
                once=attr.__once__,
            )
            tokens.append(token)
        plugin._handler_tokens = tokens

    async def _bind_data(self, plugin: Plugin) -> None:
        for attr_name in dir(plugin):
            attr = getattr(plugin, attr_name, None)
            if isinstance(attr, PluginData):
                if isinstance(attr, PluginConfig):
                    path = plugin.get_config_path(attr._name)
                else:
                    path = plugin.get_data_path(attr._name)
                attr._bind(path)

    async def _wrap_run(self, entry: _Entry) -> None:
        plugin = entry.plugin
        try:
            await plugin.run()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Plugin %s run() crashed", plugin.name)
            self._set_status(plugin, PluginState.Failed, error=e)
            entry.fw_state = PluginState.Failed  # 同步状态机
            self._on_fatal(plugin.name, e)

    async def _do_stop(self, entry: _Entry, timeout: float) -> None:
        plugin = entry.plugin
        self._set_status(plugin, PluginState.Stopping)
        await self._run_async(plugin.on_stop())
        if entry.run_task and not entry.run_task.done():
            entry.run_task.cancel()
            try:
                await asyncio.wait_for(entry.run_task, timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        entry.run_task = None
        self._set_status(plugin, PluginState.Stopped, stopped_at=time.time())
        entry.fw_state = PluginState.Stopped

        # 停止时自动刷盘
        for attr_name in dir(plugin):
            attr = getattr(plugin, attr_name, None)
            if isinstance(attr, PluginData) and attr.is_bound:
                try:
                    attr.save()
                except Exception:
                    logger.exception(
                        "Auto-save failed for %s.%s", plugin.name, attr_name
                    )

    def _set_status(self, plugin: Plugin, state: PluginState, **kwargs) -> None:
        plugin._status = plugin._status.replace(state=state, **kwargs)

    async def _run_async(self, fn: Any) -> Any:
        if fn is None:
            return None
        if inspect.isawaitable(fn):
            return await fn
        result = fn()
        if inspect.isawaitable(result):
            return await result
        return result

    def resolve_service(self, name: str, **kwargs) -> Any | None:
        """从管理器便捷查询服务实例。

        代理到内部 PluginServiceRegistry.resolve。

        Args:
            name: 服务名。
            **kwargs: 透传给 resolve 的额外参数，如 provider、version。

        Returns:
            匹配的服务实例；若无匹配则返回 None。
        """
        return self._registry.resolve(name, **kwargs)

    def require_service(self, name: str, **kwargs) -> Any:
        """从管理器严格查询服务实例。

        代理到内部 PluginServiceRegistry.require。

        Args:
            name: 服务名。
            **kwargs: 透传给 require 的额外参数，如 provider、version。

        Returns:
            匹配的服务实例。

        Raises:
            ServiceNotFound: 服务不存在时。
            VersionMismatch: 版本约束不满足时。
        """
        return self._registry.require(name, **kwargs)

    def _check_plugin_dependencies(self, plugin_cls: type[Plugin]) -> None:
        """检查插件声明的版本依赖是否满足。

        Args:
            plugin_cls: 待加载的插件类。

        Raises:
            RuntimeError: 版本约束格式非法、目标插件未声明版本号、或版本不匹配时。
        """
        for dep_name, constraint in plugin_cls.dependencies.items():
            entry = self._plugins.get(dep_name)
            if entry is None or not constraint:
                continue

            try:
                spec = SpecifierSet(constraint)
            except InvalidSpecifier as exc:
                raise RuntimeError(
                    f"插件 '{plugin_cls.name}' 对 '{dep_name}' 的版本约束 "
                    f"'{constraint}' 格式非法"
                ) from exc

            dep_version = getattr(entry.plugin, "version", None)
            if dep_version is None:
                raise RuntimeError(
                    f"插件 '{plugin_cls.name}' 依赖 '{dep_name}'，"
                    f"但目标插件未声明版本号"
                )

            try:
                dep_ver = Version(dep_version)
            except InvalidVersion as exc:
                raise RuntimeError(
                    f"插件 '{dep_name}' 的版本号 '{dep_version}' "
                    f"不是合法的 PEP 440 格式"
                ) from exc

            if dep_ver not in spec:
                raise RuntimeError(
                    f"插件 '{plugin_cls.name}' 要求 '{dep_name}{constraint}'，"
                    f"但实际版本为 '{dep_version}'"
                )
