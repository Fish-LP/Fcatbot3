"""PlugKit 服务注册表实现。

线程/协程安全由 LifecycleManager 外部的 asyncio.Lock 保证。
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Callable

from fcatbot.plugkit.protocol.service import (
    ServiceConflict,
    ServiceEvent,
    ServiceInfo,
    ServiceListener,
    ServiceNotFound,
    VersionMismatch,
)

logger = logging.getLogger("plugkit.registry")


class PluginServiceRegistry:
    """服务注册表具体实现。

    每个 LifecycleManager 持有一个独立实例，插件通过 Plugin.registry 访问。
    """

    def __init__(self) -> None:
        """初始化空注册表。"""
        # name -> ServiceInfo（同名服务仅保留一个实例，force 可覆盖）
        self._services: dict[str, ServiceInfo] = {}
        # provider -> set of service names
        self._providers: dict[str, set[str]] = {}
        # token -> ServiceListener
        self._listeners: dict[str, ServiceListener] = {}

    # ------------------------------------------------------------------ #
    # 注册 / 注销
    # ------------------------------------------------------------------ #
    def register(
        self,
        name: str,
        instance: Any,
        *,
        provider: str,
        version: str = "1.0.0",
        metadata: dict | None = None,
        force: bool = False,
    ) -> ServiceInfo:
        """注册服务。

        Args:
            name: 服务名。
            instance: 服务实例。
            provider: 注册该服务的插件名。
            version: 服务版本，默认 "1.0.0"。
            metadata: 附加元数据，默认为空。
            force: 是否允许覆盖同名服务。默认拒绝，若同名服务已存在则抛出
                ServiceConflict。

        Returns:
            生成的 ServiceInfo。

        Raises:
            ServiceConflict: 当同名服务已存在且 force 为 False 时。
        """
        if name in self._services and not force:
            existing = self._services[name]
            raise ServiceConflict(name, existing.provider)

        info = ServiceInfo(
            name=name,
            provider=provider,
            instance=instance,
            version=version,
            metadata=metadata or {},
        )

        # 若已存在且 force=True，先清理旧 provider 索引
        if name in self._services:
            old = self._services[name]
            self._providers.get(old.provider, set()).discard(name)

        self._services[name] = info
        self._providers.setdefault(provider, set()).add(name)

        logger.debug("Service registered: %s@%s by %s", name, version, provider)
        self._emit("register", info)
        return info

    def unregister(self, name: str, *, provider: str) -> ServiceInfo | None:
        """注销指定服务。

        provider 必须匹配，防止误删其他插件注册的服务。

        Args:
            name: 服务名。
            provider: 注册该服务的插件名。

        Returns:
            被注销的服务元数据；若服务不存在或 provider 不匹配则返回 None。
        """
        info = self._services.get(name)
        if info is None:
            return None
        if info.provider != provider:
            logger.warning(
                "Service '%s' owned by '%s', cannot unregister from '%s'",
                name,
                info.provider,
                provider,
            )
            return None

        self._services.pop(name, None)
        self._providers.get(provider, set()).discard(name)
        if not self._providers.get(provider):
            self._providers.pop(provider, None)

        logger.debug("Service unregistered: %s by %s", name, provider)
        self._emit("unregister", info)
        return info

    def unregister_by_provider(self, provider: str) -> list[ServiceInfo]:
        """批量注销某插件注册的全部服务。

        插件卸载时由 LifecycleManager 调用。

        Args:
            provider: 插件名。

        Returns:
            被注销的服务元数据列表。
        """
        names = list(self._providers.pop(provider, set()))
        removed: list[ServiceInfo] = []
        for name in names:
            info = self._services.pop(name, None)
            if info is not None:
                removed.append(info)
                self._emit("unregister", info)
        if removed:
            logger.debug(
                "Bulk unregistered %d service(s) from %s", len(removed), provider
            )
        return removed

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def resolve(
        self,
        name: str,
        *,
        provider: str | None = None,
        version: str | None = None,
    ) -> Any | None:
        """宽松获取服务实例。

        当服务不存在或版本不匹配时静默返回 None。

        Args:
            name: 服务名。
            provider: 若指定，则只返回该插件提供的服务。
            version: 若指定，则进行极简版本匹配。

        Returns:
            匹配的服务实例；若无匹配则返回 None。
        """
        info = self._services.get(name)
        if info is None:
            return None
        if provider is not None and info.provider != provider:
            return None
        if version is not None and not info.match_version(version):
            return None
        return info.instance

    def require(
        self,
        name: str,
        *,
        provider: str | None = None,
        version: str | None = None,
    ) -> Any:
        """严格获取服务实例。

        不存在时抛出 ServiceNotFound，版本不匹配时抛出 VersionMismatch。

        Args:
            name: 服务名。
            provider: 若指定，则只返回该插件提供的服务。
            version: 若指定，则进行极简版本匹配。

        Returns:
            匹配的服务实例。

        Raises:
            ServiceNotFound: 服务不存在时。
            VersionMismatch: 版本约束不满足时。
        """
        info = self._services.get(name)
        if info is None:
            available = list(self._services.keys())
            raise ServiceNotFound(name, available=available)

        if provider is not None and info.provider != provider:
            available = [n for n, i in self._services.items() if i.provider == provider]
            raise ServiceNotFound(name, available=available)

        if version is not None and not info.match_version(version):
            raise VersionMismatch(name, version, info.version)

        return info.instance

    def resolve_info(self, name: str) -> ServiceInfo | None:
        """获取完整元数据。

        Args:
            name: 服务名。

        Returns:
            包含 provider、version 等字段的 ServiceInfo；若不存在则返回 None。
        """
        return self._services.get(name)

    def has(self, name: str, *, version: str | None = None) -> bool:
        """检查服务是否存在且可选地满足版本约束。

        Args:
            name: 服务名。
            version: 可选的版本约束。

        Returns:
            若存在且满足约束则返回 True，否则返回 False。
        """
        info = self._services.get(name)
        if info is None:
            return False
        if version is not None:
            return info.match_version(version)
        return True

    def check(self, *names: str) -> list[str]:
        """批量检查服务存在性。

        Args:
            *names: 要检查的服务名。

        Returns:
            缺失的服务名列表；空列表表示全部存在。
        """
        return [n for n in names if n not in self._services]

    # ------------------------------------------------------------------ #
    # 枚举
    # ------------------------------------------------------------------ #
    def list_services(self) -> list[ServiceInfo]:
        """返回全部注册服务快照。

        Returns:
            当前所有已注册 ServiceInfo 的列表。
        """
        return list(self._services.values())

    def list_by_provider(self, provider: str) -> list[ServiceInfo]:
        """返回指定插件提供的全部服务。

        Args:
            provider: 插件名。

        Returns:
            该插件注册的所有 ServiceInfo 列表。
        """
        names = self._providers.get(provider, set())
        return [self._services[n] for n in names if n in self._services]

    def find(self, predicate: Callable[[ServiceInfo], bool]) -> list[ServiceInfo]:
        """按自定义条件过滤服务。

        Args:
            predicate: 接收 ServiceInfo 并返回 bool 的过滤函数。

        Returns:
            满足条件的 ServiceInfo 列表。
        """
        return [info for info in self._services.values() if predicate(info)]

    # ------------------------------------------------------------------ #
    # 监听
    # ------------------------------------------------------------------ #
    def add_listener(self, callback: ServiceListener) -> str:
        """订阅注册表变化。

        典型用途：业务插件等待 "napcat.api" 等服务注册后再初始化。

        Args:
            callback: 事件回调，签名应为 (event, info) -> None。

        Returns:
            用于 remove_listener 的 token 字符串。
        """
        token = secrets.token_hex(8)
        self._listeners[token] = callback
        return token

    def remove_listener(self, token: str) -> bool:
        """移除监听器。

        Args:
            token: add_listener 返回的 token。

        Returns:
            若成功移除返回 True；若 token 不存在返回 False。
        """
        return self._listeners.pop(token, None) is not None

    def _emit(self, event: ServiceEvent, info: ServiceInfo) -> None:
        """向所有监听器广播事件。

        Args:
            event: 事件类型，"register" 或 "unregister"。
            info: 发生变更的服务元数据。
        """
        for cb in list(self._listeners.values()):
            try:
                cb(event, info)
            except Exception:
                logger.exception("Service listener failed for %s", info.name)
