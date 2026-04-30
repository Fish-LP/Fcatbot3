# src/protocol/data.py
import copy
from collections.abc import MutableMapping
from pathlib import Path
from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    Self,
    TypeVar,
    overload,
)

from .storage import StorageBackend, YAMLBackend

T = TypeVar("T")
TSection = TypeVar("TSection", bound="ConfigSection")


class _MISSING:
    __slots__ = ()


MISSING = _MISSING()


# ==================== Value 描述符 ====================


class Value(Generic[T]):
    def __init__(
        self,
        default: T = MISSING,  # type: ignore[assignment]
        *,
        default_factory: Callable[[], T] | None = None,
        readonly: bool = False,
        repr: bool = True,
    ):
        if default is not MISSING and default_factory is not None:
            raise ValueError("Cannot specify both default and default_factory")
        self.default = default
        self.default_factory = default_factory
        self.readonly = readonly
        self.repr = repr
        self.name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def _get_default(self) -> T:
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is MISSING:
            raise ValueError(f"Field '{self.name}' has no default value")
        return copy.deepcopy(self.default)

    @overload
    def __get__(self, instance: None, owner: type) -> Self: ...

    @overload
    def __get__(self, instance: "ConfigSection", owner: type) -> T: ...

    def __get__(self, instance: Optional["ConfigSection"], owner: type) -> T | Self:
        if instance is None:
            return self
        if self.name not in instance._storage:
            instance._storage[self.name] = self._get_default()

        val = instance._storage[self.name]
        # 懒转换兜底：如果之前存进去的是原生 dict，现在补转
        if isinstance(val, dict) and not isinstance(val, ConfigSection):
            coerced = type(instance)._coerce(self.name, val)
            if coerced is not val:
                instance._storage[self.name] = coerced
                val = coerced
        return val

    def __set__(self, instance: "ConfigSection", value: T) -> None:
        if self.readonly:
            raise AttributeError(f"Cannot set read-only field '{self.name}'")
        coerced = type(instance)._coerce(self.name, value)
        instance._storage[self.name] = coerced


# ==================== 工厂函数 ====================


def value(
    default: T = MISSING,  # type: ignore[assignment]
    *,
    default_factory: Callable[[], T] | None = None,
    readonly: bool = False,
    repr: bool = True,
) -> Any:
    return Value(default, default_factory=default_factory, readonly=readonly, repr=repr)


def section(
    *,
    default_factory: Callable[[], TSection],
    readonly: bool = False,
    repr: bool = True,
) -> Any:
    return Value(
        default=MISSING, default_factory=default_factory, readonly=readonly, repr=repr
    )


# ==================== ConfigSection ====================


class ConfigSection(MutableMapping[str, Any]):
    """
    结构化配置节。支持声明式 Value 字段、点号访问、递归序列化。
    list/dict 不拦截修改，不自动保存。
    """

    def __init__(self, **kwargs: Any) -> None:
        object.__setattr__(self, "_storage", {})
        for k, v in kwargs.items():
            setattr(self, k, v)

    @classmethod
    def _coerce(cls, name: str, value: Any) -> Any:
        """
        根据类上的 Value 描述符，把 dict 转换为声明的 ConfigSection 子类。
        不依赖 get_type_hints，因为 section() 返回 Any 会擦除类型信息。
        """
        if not isinstance(value, dict) or isinstance(value, ConfigSection):
            return value

        # 在类及父类上查找 Value 描述符
        desc = getattr(cls, name, None)
        if isinstance(desc, Value) and desc.default_factory is not None:
            factory = desc.default_factory
            # 情况 A：default_factory 直接是 ConfigSection 子类（如 WSConfig）
            if isinstance(factory, type) and issubclass(factory, ConfigSection):
                return factory.from_dict(value)
            # 情况 B：default_factory 是 lambda / 函数，尝试调用一次推断类型
            # 为了安全，只处理明显返回 ConfigSection 的情况
            try:
                sample = factory()
                if isinstance(sample, ConfigSection):
                    return type(sample).from_dict(value)
            except Exception:
                pass

        return value

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        desc = getattr(type(self), name, None)
        if isinstance(desc, Value):
            desc.__set__(self, value)
            return

        # 动态字段也走强制转换（如果类上有对应的 Value 声明）
        self._storage[name] = type(self)._coerce(name, value)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

        desc = getattr(type(self), name, None)
        if isinstance(desc, Value):
            return desc.__get__(self, type(self))

        try:
            val = self._storage[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' has no attribute '{name}'"
            ) from None

        # 懒转换兜底
        if isinstance(val, dict) and not isinstance(val, ConfigSection):
            coerced = type(self)._coerce(name, val)
            if coerced is not val:
                self._storage[name] = coerced
                val = coerced
        return val

    # ---------- MutableMapping 兼容 ----------
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __delitem__(self, key: str) -> None:
        if isinstance(getattr(type(self), key, None), Value):
            raise AttributeError(f"Cannot delete declared field '{key}'")
        del self._storage[key]

    def __iter__(self):
        keys = set(self._storage.keys())
        for k in dir(type(self)):
            if isinstance(getattr(type(self), k, None), Value):
                keys.add(k)
        return iter(keys)

    def __len__(self) -> int:
        return len(list(self.__iter__()))

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in self._storage or isinstance(getattr(type(self), key, None), Value)

    def __repr__(self) -> str:
        cls = type(self)
        fields = []
        for k in self:
            v = self[k]
            desc = getattr(cls, k, None)
            if isinstance(desc, Value) and desc.repr:
                fields.append(f"{k}={v!r}")
            elif not isinstance(desc, Value):
                fields.append(f"{k}={v!r}")
        return f"{cls.__name__}({', '.join(fields)})"

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in self._storage.items():
            if isinstance(v, ConfigSection):
                result[k] = v.to_dict()
            elif isinstance(v, list):
                result[k] = [
                    x.to_dict() if isinstance(x, ConfigSection) else x for x in v
                ]
            else:
                result[k] = v
        return result

    @classmethod
    def from_dict(cls: type[TSection], data: dict[str, Any]) -> TSection:
        inst = cls.__new__(cls)
        object.__setattr__(inst, "_storage", {})

        for k, v in data.items():
            inst._storage[k] = cls._coerce(k, v)
        return inst  # type: ignore[return-value]


# ==================== PluginData / PluginConfig ====================


class PluginData(ConfigSection):
    _name: str
    _path: Path | None
    _backend: StorageBackend

    def __init__(
        self,
        name: str = "",
        *,
        autosave: bool = False,  # 保留签名兼容旧代码，内部已废弃
        backend: StorageBackend | None = None,
    ):
        super().__init__()
        object.__setattr__(self, "_name", name or type(self).__name__)
        object.__setattr__(self, "_path", None)
        object.__setattr__(self, "_backend", backend or YAMLBackend())

    def _bind(self, path: Path) -> None:
        self._path = path.with_suffix(f".{self._backend.extension}")
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        if self._path is None:
            raise RuntimeError("PluginData not bound")
        raw = self._backend.load(self._path)
        if not isinstance(raw, dict):
            raw = {}
        loaded = self.from_dict(raw)
        self._storage = loaded._storage

    def save(self) -> None:
        if self._path is None:
            raise RuntimeError("PluginData not bound")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._backend.save(self._path, self.to_dict())

    def reload(self) -> None:
        if self._path and self._path.exists():
            self._load()


class PluginConfig(PluginData):
    """用户可修改的配置。强制 YAML 后端。"""

    def __init__(self, name: str = "", *, autosave: bool = False):
        super().__init__(name, autosave=autosave, backend=YAMLBackend())
