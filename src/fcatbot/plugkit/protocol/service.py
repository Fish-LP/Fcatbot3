"""
PlugKit 服务注册协议层。

本模块定义了服务注册表的契约、元数据模型及异常体系。
插件可通过声明式或命令式方式注册和消费服务。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from packaging.specifiers import SpecifierSet
from packaging.version import Version


# ---------- 异常体系 ----------
class ServiceError(RuntimeError):
    """服务注册表操作失败基类。"""

    pass


class ServiceNotFound(ServiceError):
    """请求的服务在注册表中不存在时抛出。

    Attributes:
        name: 缺失的服务名。
        available: 当前可用的服务名列表。
    """

    def __init__(self, name: str, *, available: list[str] | None = None):
        """初始化异常。

        Args:
            name: 缺失的服务名。
            available: 当前可用的服务名列表，用于提示。
        """
        msg = f"服务 '{name}' 未找到"
        if available:
            msg += f"。可用服务: {available}"
        super().__init__(msg)
        self.name = name
        self.available = available or []


class ServiceConflict(ServiceError):
    """尝试覆盖已注册且未设置 force 的服务时抛出。

    Attributes:
        name: 发生冲突的服务名。
        existing_provider: 已注册该服务的插件名。
    """

    def __init__(self, name: str, existing_provider: str):
        """初始化异常。

        Args:
            name: 发生冲突的服务名。
            existing_provider: 已注册该服务的插件名。
        """
        super().__init__(
            f"服务 '{name}' 已被插件 '{existing_provider}' 注册。"
            f"使用 force=True 覆盖。"
        )
        self.name = name
        self.existing_provider = existing_provider


class VersionMismatch(ServiceError):
    """服务版本与约束不匹配时抛出。

    Attributes:
        required: 请求的版本约束。
        actual: 实际注册的版本。
    """

    def __init__(self, name: str, required: str, actual: str):
        """初始化异常。

        Args:
            name: 服务名。
            required: 请求的版本约束。
            actual: 实际注册的版本。
        """
        super().__init__(f"服务 '{name}' 版本不匹配：要求 {required}，实际 {actual}")
        self.required = required
        self.actual = actual


# ---------- 元数据 ----------
@dataclass(frozen=True)
class ServiceInfo:
    """已注册服务的元数据快照。

    Attributes:
        name: 服务名。
        provider: 注册该服务的插件名。
        instance: 实际的服务实例（任意 Python 对象）。
        version: 服务版本，默认 "1.0.0"。
        metadata: 附加元数据字典。
    """

    name: str
    provider: str
    instance: Any
    version: str = "1.0.0"
    metadata: dict = field(default_factory=dict)

    def match_version(self, constraint: str) -> bool:
        """检查当前版本是否满足约束。

        Args:
            constraint: 版本约束字符串。

        Return:
            若满足约束则返回 True，否则返回 False。
        """
        if not constraint or not constraint.strip():
            return False

        operators = ("==", "!=", "<=", ">=", "<", ">", "~=", "===")
        normalized_parts = []

        for part in constraint.split(","):
            part = part.strip()
            if not part:
                continue
            # 裸版本号前自动加 ==
            if not any(part.startswith(op) for op in operators):
                part = f"=={part}"
            normalized_parts.append(part)

        try:
            spec = SpecifierSet(",".join(normalized_parts))
            return Version(self.version) in spec
        except Exception:
            return False


# ---------- 监听器 ----------
ServiceEvent = Literal["register", "unregister"]
"""注册表事件类型：服务注册或服务注销。"""

ServiceListener = Callable[[ServiceEvent, ServiceInfo], None]
"""注册表监听器回调签名。"""


# ---------- 协议 ----------
class ServiceRegistry(Protocol):
    """服务注册表协议。

    实现该协议的对象为插件提供服务的注册、查询、枚举及变更监听能力。
    """

    # ----- 注册/注销 -----
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
        ...

    def unregister(self, name: str, *, provider: str) -> ServiceInfo | None:
        """注销指定服务。

        provider 必须匹配，防止误删其他插件注册的服务。

        Args:
            name: 服务名。
            provider: 注册该服务的插件名。

        Returns:
            被注销的服务元数据；若服务不存在或 provider 不匹配则返回 None。
        """
        ...

    def unregister_by_provider(self, provider: str) -> list[ServiceInfo]:
        """批量注销某插件注册的全部服务。

        插件卸载时由 LifecycleManager 调用。

        Args:
            provider: 插件名。

        Returns:
            被注销的服务元数据列表。
        """
        ...

    # ----- 查询 -----
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
            version: 若指定，则进行版本匹配。

        Returns:
            匹配的服务实例；若无匹配则返回 None。
        """
        ...

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
        ...

    def resolve_info(self, name: str) -> ServiceInfo | None:
        """获取完整元数据。

        Args:
            name: 服务名。

        Returns:
            包含 provider、version 等字段的 ServiceInfo；若不存在则返回 None。
        """
        ...

    def has(self, name: str, *, version: str | None = None) -> bool:
        """检查服务是否存在且可选地满足版本约束。

        Args:
            name: 服务名。
            version: 可选的版本约束。

        Returns:
            若存在且满足约束则返回 True，否则返回 False。
        """
        ...

    def check(self, *names: str) -> list[str]:
        """批量检查服务存在性。

        Args:
            *names: 要检查的服务名。

        Returns:
            缺失的服务名列表；空列表表示全部存在。
        """
        ...

    # ----- 枚举 -----
    def list_services(self) -> list[ServiceInfo]:
        """返回全部注册服务快照。

        Returns:
            当前所有已注册 ServiceInfo 的列表。
        """
        ...

    def list_by_provider(self, provider: str) -> list[ServiceInfo]:
        """返回指定插件提供的全部服务。

        Args:
            provider: 插件名。

        Returns:
            该插件注册的所有 ServiceInfo 列表。
        """
        ...

    def find(
        self,
        predicate: Callable[[ServiceInfo], bool],
    ) -> list[ServiceInfo]:
        """按自定义条件过滤服务。

        Args:
            predicate: 接收 ServiceInfo 并返回 bool 的过滤函数。

        Returns:
            满足条件的 ServiceInfo 列表。
        """
        ...

    # ----- 监听 -----
    def add_listener(self, callback: ServiceListener) -> str:
        """订阅注册表变化。

        典型用途：业务插件等待 "napcat.api" 等服务注册后再初始化。

        Args:
            callback: 事件回调，签名应为 (event, info) -> None。

        Returns:
            用于 remove_listener 的 token 字符串。
        """
        ...

    def remove_listener(self, token: str) -> bool:
        """移除监听器。

        Args:
            token: add_listener 返回的 token。

        Returns:
            若成功移除返回 True；若 token 不存在返回 False。
        """
        ...
