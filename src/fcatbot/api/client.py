"""
纯通信层 - 只负责发送和自动包装，不定义具体接口
"""
import functools
import inspect
import types
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass, field
from typing import (
    Any, Awaitable, Dict, Generic, Optional, TypeVar, Union
)


T = TypeVar("T")


@dataclass
class ApiRequest:
    """API请求定义"""
    activity: str
    data: Dict[str, Any] = field(default_factory=dict)
    headers: Optional[Dict[str, str]] = None


def _extract_invoke_return(cls) -> Any:
    """从类的 __orig_bases__ 中提取 APIClient[T] 的泛型参数 T"""
    for base in getattr(cls, "__orig_bases__", ()):
        origin = getattr(base, "__origin__", None)
        # 注意：Python 3.9+ 的 GenericAlias 与 typing.Generic 行为略有不同
        if origin is APIClient and hasattr(base, "__args__"):
            return base.__args__[0]
    return Any


class ApiMeta(ABCMeta):
    """API元类 - 自动包装所有公共实例方法到 invoke"""
    
    def __new__(mcs, name, bases, namespace, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        
        # 跳过 APIClient 自身
        if not bases:
            return cls
        
        # 推断 invoke 的实际返回类型
        invoke_return = _extract_invoke_return(cls)
        
        for attr_name, attr_value in namespace.items():
            if attr_name.startswith("_") or attr_name in ("invoke", "call"):
                continue
            if not inspect.isfunction(attr_value):
                continue
            
            wrapper = mcs._make_wrapper(attr_value)
            if wrapper is not None:
                # 运行时重写 wrapper 的返回注解，改善 IDE/REPL 体验
                wrapper.__annotations__["return"] = Awaitable[invoke_return]
                functools.update_wrapper(wrapper, attr_value)
                setattr(cls, attr_name, wrapper)
        
        return cls
    
    @staticmethod
    def _make_wrapper(orig):
        is_coro = inspect.iscoroutinefunction(orig)
        
        if is_coro:
            @functools.wraps(orig)
            async def wrapper(self: "APIClient", *args, **kwargs):
                result = await orig(self, *args, **kwargs)
                return await self._dispatch_result(result)
            return wrapper
        else:
            @functools.wraps(orig)
            async def wrapper(self: "APIClient", *args, **kwargs):
                result = orig(self, *args, **kwargs)
                return await self._dispatch_result(result)
            return wrapper


class APIClient(ABC, Generic[T], metaclass=ApiMeta):
    """
    纯通信层基类
    泛型参数 T = invoke 的实际返回类型（如 dict、UserModel 等）
    """
    
    @abstractmethod
    async def invoke(self, request: ApiRequest) -> T:
        """执行API调用 - 子类必须实现"""
        pass

    async def call(
        self,
        activity: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> T:
        """直接调用 activity"""
        return await self.invoke(ApiRequest(activity, data or {}, headers))

    async def _dispatch_result(self, result: Any) -> T:
        """
        将方法返回值路由到 invoke。
        支持: ApiRequest / str(activity) / tuple(activity, data, headers)
        """
        if isinstance(result, ApiRequest):
            return await self.invoke(result)
        elif isinstance(result, str):
            return await self.invoke(ApiRequest(result))
        elif isinstance(result, tuple) and 1 <= len(result) <= 3:
            return await self.invoke(ApiRequest(*result))
        else:
            # 原始方法已自行处理请求，直接透传
            return result  # type: ignore[return-value]

    def __getattr__(self, name: str) -> Any:
        """动态调用任意 API 方法"""
        if name.startswith("_"):
            raise AttributeError(f"{self.__class__.__name__!r} object has no attribute {name!r}")
        
        async def method(**kwargs) -> T:
            return await self.invoke(ApiRequest(name, kwargs))
        
        bound_method = types.MethodType(method, self)
        object.__setattr__(self, name, bound_method)
        return bound_method



# class UserClient(APIClient[dict]):
#     """
#     声明 invoke 最终返回 dict。
#     子类方法的返回类型应写 T（即 dict），而非 ApiRequest。
#     """

#     async def get_user(self, user_id: int) -> dict:
#         # type: ignore[return-value]
#         return ApiRequest("get_user", {"id": user_id}) # pyright: ignore[reportReturnType]

#     async def update_user(self, user_id: int, name: str) -> dict:
#         # type: ignore[return-value]
#         return ("update_user", {"id": user_id, "name": name}) # pyright: ignore[reportReturnType]

#     async def delete_user(self, user_id: int) -> dict:
#         return f"delete_user:{user_id}"  # pyright: ignore[reportReturnType]