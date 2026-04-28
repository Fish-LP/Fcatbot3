# -*- coding: utf-8 -*-
"""
纯通信层 + API 返回数据模型
只负责：连接、发送、自动包装、返回结构化数据
"""
from __future__ import annotations

import functools
import inspect
import types
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, TypeVar, Union

T = TypeVar("T")


# ---------- 请求定义 ----------
@dataclass(frozen=True)
class ApiRequest:
    activity: str
    data: Dict[str, Any] = field(default_factory=dict)
    headers: Optional[Dict[str, str]] = None


# ---------- 通用响应 ----------
@dataclass(frozen=True, slots=True)
class ApiResponse:
    status: Literal["ok", "async", "failed"]
    retcode: int
    data: Any
    message: str = ""
    wording: str = ""
    echo: Optional[str] = None
    stream: Optional[str] = None

    @property
    def is_ok(self) -> bool:
        return self.status == "ok" and self.retcode == 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ApiResponse:
        return cls(
            status=d.get("status", "failed"),
            retcode=d.get("retcode", -1),
            data=d.get("data"),
            message=d.get("message", ""),
            wording=d.get("wording", ""),
            echo=d.get("echo"),
            stream=d.get("stream"),
        )


# ---------- 用户相关 ----------
@dataclass(frozen=True, slots=True)
class LoginInfo:
    user_id: int
    nickname: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> LoginInfo:
        return cls(user_id=int(d.get("user_id", 0)), nickname=d.get("nickname", ""))


@dataclass(frozen=True, slots=True)
class StrangerInfo:
    user_id: int
    nickname: str
    sex: Literal["male", "female", "unknown"] = "unknown"
    age: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> StrangerInfo:
        return cls(
            user_id=int(d.get("user_id", 0)),
            nickname=d.get("nickname", ""),
            sex=d.get("sex", "unknown"),
            age=int(d.get("age", 0)),
        )


@dataclass(frozen=True, slots=True)
class FriendInfo:
    user_id: int
    nickname: str
    remark: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> FriendInfo:
        return cls(
            user_id=int(d.get("user_id", 0)),
            nickname=d.get("nickname", ""),
            remark=d.get("remark", ""),
        )


# ---------- 群相关 ----------
@dataclass(frozen=True, slots=True)
class GroupInfo:
    group_id: int
    group_name: str
    member_count: int = 0
    max_member_count: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GroupInfo:
        return cls(
            group_id=int(d.get("group_id", 0)),
            group_name=d.get("group_name", ""),
            member_count=int(d.get("member_count", 0)),
            max_member_count=int(d.get("max_member_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class GroupMemberInfo:
    group_id: int
    user_id: int
    nickname: str
    card: str = ""
    sex: Literal["male", "female", "unknown"] = "unknown"
    age: int = 0
    area: str = ""
    join_time: int = 0
    last_sent_time: int = 0
    level: str = "1"
    role: Literal["owner", "admin", "member"] = "member"
    unfriendly: bool = False
    title: str = ""
    title_expire_time: int = 0
    card_changeable: bool = True
    shut_up_timestamp: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GroupMemberInfo:
        return cls(
            group_id=int(d.get("group_id", 0)),
            user_id=int(d.get("user_id", 0)),
            nickname=d.get("nickname", ""),
            card=d.get("card", ""),
            sex=d.get("sex", "unknown"),
            age=int(d.get("age", 0)),
            area=d.get("area", ""),
            join_time=int(d.get("join_time", 0)),
            last_sent_time=int(d.get("last_sent_time", 0)),
            level=str(d.get("level", "1")),
            role=d.get("role", "member"),
            unfriendly=bool(d.get("unfriendly", False)),
            title=d.get("title", ""),
            title_expire_time=int(d.get("title_expire_time", 0)),
            card_changeable=bool(d.get("card_changeable", True)),
            shut_up_timestamp=int(d.get("shut_up_timestamp", 0)),
        )


# ---------- 消息相关 ----------
@dataclass(frozen=True, slots=True)
class MessageData:
    message_id: int

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MessageData:
        return cls(message_id=int(d.get("message_id", 0)))


@dataclass(frozen=True, slots=True)
class SenderInfo:
    user_id: int
    nickname: str = ""
    sex: Literal["male", "female", "unknown"] = "unknown"
    age: int = 0
    card: str = ""
    role: Literal["owner", "admin", "member", ""] = ""
    title: str = ""
    area: str = ""
    level: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SenderInfo:
        return cls(
            user_id=int(d.get("user_id", 0)),
            nickname=d.get("nickname", ""),
            sex=d.get("sex", "unknown"),
            age=int(d.get("age", 0)),
            card=d.get("card", ""),
            role=d.get("role", ""),
            title=d.get("title", ""),
            area=d.get("area", ""),
            level=str(d.get("level", "")),
        )


@dataclass(frozen=True, slots=True)
class MessageInfo:
    message_id: int
    real_id: int = 0
    sender: SenderInfo = field(default_factory=lambda: SenderInfo(user_id=0))
    time: int = 0
    message: List[Dict[str, Any]] = field(default_factory=list)
    raw_message: str = ""
    message_type: Literal["private", "group", ""] = ""
    group_id: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MessageInfo:
        return cls(
            message_id=int(d.get("message_id", 0)),
            real_id=int(d.get("real_id", 0)),
            sender=SenderInfo.from_dict(d.get("sender", {})),
            time=int(d.get("time", 0)),
            message=list(d.get("message", [])),
            raw_message=d.get("raw_message", ""),
            message_type=d.get("message_type", ""),
            group_id=int(d.get("group_id", 0)),
        )


# ---------- 文件相关 ----------
@dataclass(frozen=True, slots=True)
class ImageInfo:
    file: str
    url: str = ""
    file_size: str = ""
    file_name: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ImageInfo:
        return cls(
            file=d.get("file", ""),
            url=d.get("url", ""),
            file_size=str(d.get("file_size", "")),
            file_name=d.get("file_name", ""),
        )


@dataclass(frozen=True, slots=True)
class RecordInfo:
    file: str
    url: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RecordInfo:
        return cls(file=d.get("file", ""), url=d.get("url", ""))


@dataclass(frozen=True, slots=True)
class FileInfo:
    file: str
    file_name: str = ""
    file_size: int = 0
    base64: str = ""
    url: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> FileInfo:
        return cls(
            file=d.get("file", ""),
            file_name=d.get("file_name", ""),
            file_size=int(d.get("file_size", 0)),
            base64=d.get("base64", ""),
            url=d.get("url", ""),
        )


@dataclass(frozen=True, slots=True)
class FileUrl:
    url: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> FileUrl:
        return cls(url=d.get("url", ""))


# ---------- 系统相关 ----------
@dataclass(frozen=True, slots=True)
class VersionInfo:
    app_name: str = ""
    app_version: str = ""
    protocol_version: str = ""
    impl: str = ""
    version: str = ""
    onebot_version: str = "11"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> VersionInfo:
        return cls(
            app_name=d.get("app_name", ""),
            app_version=d.get("app_version", ""),
            protocol_version=d.get("protocol_version", ""),
            impl=d.get("impl", ""),
            version=d.get("version", ""),
            onebot_version=d.get("onebot_version", "11"),
        )


@dataclass(frozen=True, slots=True)
class StatusInfo:
    online: bool = False
    good: bool = True

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> StatusInfo:
        return cls(online=bool(d.get("online", False)), good=bool(d.get("good", True)))


# ---------- 异常 ----------
class NapCatApiError(Exception):
    def __init__(self, retcode: int, message: str) -> None:
        self.retcode = retcode
        self.message = message
        super().__init__(f"[{retcode}] {message}")


# ---------- 通信底座 ----------
class ApiMeta(ABCMeta):
    """元类：自动包装所有公共实例方法到 invoke"""

    def __new__(mcs, name: str, bases: tuple, namespace: dict, **kwargs: Any):
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        if not bases:
            return cls
        for attr_name, attr_value in namespace.items():
            if attr_name.startswith("_") or attr_name in ("invoke", "call"):
                continue
            if not inspect.isfunction(attr_value):
                continue
            wrapper = mcs._make_wrapper(attr_value)
            if wrapper is not None:
                setattr(cls, attr_name, wrapper)
        return cls

    @staticmethod
    def _make_wrapper(orig: Callable[..., Any]) -> Optional[Callable[..., Any]]:
        is_coro = inspect.iscoroutinefunction(orig)

        if is_coro:
            @functools.wraps(orig)
            async def wrapper(self: APIClient, *args: Any, **kwargs: Any) -> Any:
                result = await orig(self, *args, **kwargs)
                return await self._dispatch_result(result)
            return wrapper  # type: ignore[return-value]
        else:
            @functools.wraps(orig)
            async def wrapper(self: APIClient, *args: Any, **kwargs: Any) -> Any:
                result = orig(self, *args, **kwargs)
                return await self._dispatch_result(result)
            return wrapper  # type: ignore[return-value]


class APIClient(ABC, metaclass=ApiMeta):
    @abstractmethod
    async def invoke(self, request: ApiRequest) -> Any:
        ...

    async def call(
        self,
        activity: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        return await self.invoke(ApiRequest(activity, data or {}, headers))

    async def _dispatch_result(self, result: Any) -> Any:
        if isinstance(result, ApiRequest):
            return await self.invoke(result)
        elif isinstance(result, str):
            return await self.invoke(ApiRequest(result))
        elif isinstance(result, tuple) and 1 <= len(result) <= 3:
            return await self.invoke(ApiRequest(*result))
        return result

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(f"{self.__class__.__name__!r} object has no attribute {name!r}")

        async def method(**kwargs: Any) -> Any:
            return await self.invoke(ApiRequest(name, kwargs))

        bound_method = types.MethodType(method, self)
        object.__setattr__(self, name, bound_method)
        return bound_method


class NapCatClient(APIClient):
    """NapCat HTTP 客户端"""

    def __init__(self, base_url: str = "http://localhost:3000") -> None:
        self.base_url = base_url.rstrip("/")
        self._session: Optional[Any] = None

    async def _get_session(self) -> Any:
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
        return self._session

    async def invoke(self, request: ApiRequest) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{request.activity}"
        async with session.post(url, json=request.data or {}) as resp:
            result: Dict[str, Any] = await resp.json()
            if result.get("status") != "ok":
                raise NapCatApiError(
                    result.get("retcode", -1),
                    result.get("message", result.get("wording", "unknown")),
                )
            return result.get("data")

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def invoke_typed(self, request: ApiRequest, model_cls: Callable[[Dict[str, Any]], T]) -> T:
        raw = await self.invoke(request)
        if raw is None:
            raise NapCatApiError(-1, "API 返回空数据")
        if isinstance(raw, dict):
            return model_cls(raw)
        raise NapCatApiError(-1, f"无法解析返回类型: {type(raw).__name__}")

    # ---------- 消息 API ----------
    async def send_group_msg(self, message: List[Dict[str, Any]], group_id: Union[int, str], **extra: Any) -> ApiRequest:
        return ApiRequest("/send_group_msg", {"group_id": group_id, "message": message, **extra})

    async def send_private_msg(self, message: List[Dict[str, Any]], user_id: Union[int, str], **extra: Any) -> ApiRequest:
        return ApiRequest("/send_private_msg", {"user_id": user_id, "message": message, **extra})

    async def delete_msg(self, message_id: Union[int, str]) -> ApiRequest:
        return ApiRequest("/delete_msg", {"message_id": message_id})

    async def get_msg(self, message_id: Union[int, str]) -> ApiRequest:
        return ApiRequest("/get_msg", {"message_id": message_id})

    # ---------- 用户 API ----------
    async def get_login_info(self) -> ApiRequest:
        return ApiRequest("/get_login_info")

    async def get_stranger_info(self, user_id: Union[int, str], no_cache: bool = False) -> ApiRequest:
        return ApiRequest("/get_stranger_info", {"user_id": user_id, "no_cache": no_cache})

    async def get_friend_list(self) -> ApiRequest:
        return ApiRequest("/get_friend_list")

    # ---------- 群 API ----------
    async def get_group_info(self, group_id: Union[int, str], no_cache: bool = False) -> ApiRequest:
        return ApiRequest("/get_group_info", {"group_id": group_id, "no_cache": no_cache})

    async def get_group_list(self, no_cache: bool = False) -> ApiRequest:
        return ApiRequest("/get_group_list", {"no_cache": no_cache})

    async def get_group_member_info(self, group_id: Union[int, str], user_id: Union[int, str], no_cache: bool = False) -> ApiRequest:
        return ApiRequest("/get_group_member_info", {"group_id": group_id, "user_id": user_id, "no_cache": no_cache})

    async def get_group_member_list(self, group_id: Union[int, str], no_cache: bool = False) -> ApiRequest:
        return ApiRequest("/get_group_member_list", {"group_id": group_id, "no_cache": no_cache})

    # ---------- 群管理 API ----------
    async def set_group_kick(self, group_id: Union[int, str], user_id: Union[int, str], reject_add_request: bool = False) -> ApiRequest:
        return ApiRequest("/set_group_kick", {"group_id": str(group_id), "user_id": str(user_id), "reject_add_request": reject_add_request})

    async def set_group_ban(self, group_id: Union[int, str], user_id: Union[int, str], duration: int = 60) -> ApiRequest:
        return ApiRequest("/set_group_ban", {"group_id": str(group_id), "user_id": str(user_id), "duration": duration})

    async def set_group_card(self, group_id: Union[int, str], user_id: Union[int, str], card: str) -> ApiRequest:
        return ApiRequest("/set_group_card", {"group_id": str(group_id), "user_id": str(user_id), "card": card})

    async def set_group_special_title(self, group_id: Union[int, str], user_id: Union[int, str], special_title: str, duration: int = -1) -> ApiRequest:
        return ApiRequest("/set_group_special_title", {"group_id": str(group_id), "user_id": str(user_id), "special_title": special_title, "duration": duration})

    async def set_group_admin(self, group_id: Union[int, str], user_id: Union[int, str], enable: bool = True) -> ApiRequest:
        return ApiRequest("/set_group_admin", {"group_id": str(group_id), "user_id": str(user_id), "enable": enable})

    async def set_group_whole_ban(self, group_id: Union[int, str], enable: bool = True) -> ApiRequest:
        return ApiRequest("/set_group_whole_ban", {"group_id": str(group_id), "enable": enable})

    async def set_group_name(self, group_id: Union[int, str], group_name: str) -> ApiRequest:
        return ApiRequest("/set_group_name", {"group_id": str(group_id), "group_name": group_name})

    async def set_group_leave(self, group_id: Union[int, str], is_dismiss: bool = False) -> ApiRequest:
        return ApiRequest("/set_group_leave", {"group_id": str(group_id), "is_dismiss": is_dismiss})

    # ---------- 文件 API ----------
    async def get_image(self, file: Optional[str] = None, file_id: Optional[str] = None) -> ApiRequest:
        return ApiRequest("/get_image", {"file": file, "file_id": file_id})

    async def get_record(self, out_format: str, file: Optional[str] = None, file_id: Optional[str] = None) -> ApiRequest:
        return ApiRequest("/get_record", {"file": file, "file_id": file_id, "out_format": out_format})

    async def get_file(self, file: Optional[str] = None, file_id: Optional[str] = None) -> ApiRequest:
        return ApiRequest("/get_file", {"file": file, "file_id": file_id})

    async def get_group_file_url(self, file_id: str, group_id: Union[int, str]) -> ApiRequest:
        return ApiRequest("/get_group_file_url", {"file_id": file_id, "group_id": str(group_id)})

    async def get_private_file_url(self, file_id: str) -> ApiRequest:
        return ApiRequest("/get_private_file_url", {"file_id": file_id})

    # ---------- 系统 API ----------
    async def get_version_info(self) -> ApiRequest:
        return ApiRequest("/get_version_info")

    async def get_status(self) -> ApiRequest:
        return ApiRequest("/get_status")


# ---------- 全局 API 单例 ----------
_api_instance: Optional[NapCatClient] = None


def set_api(api: NapCatClient) -> None:
    global _api_instance
    _api_instance = api


def get_api() -> NapCatClient:
    if _api_instance is None:
        raise RuntimeError("API 未初始化。请先调用 set_api(NapCatClient(...))")
    return _api_instance