# -*- coding: utf-8 -*-
"""
实体容器层：User、GroupUser、Group
内嵌 RBAC 能力（继承 _PermissionHolder）与 API 操作。
API 延迟获取：避免测试和独立使用时必须 set_api()
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple, Union

from fcatbot.core.client import (
    GroupInfo,
    GroupMemberInfo,
    MessageData,
    NapCatApiError,
    NapCatClient,
    StrangerInfo,
    get_api,
)
from fcatbot.models.message import AtSeg, MsgChain
from fcatbot.rbac.engine import _Context, _PermissionHolder
from fcatbot.rbac.manager import RBACManager, Role


class User(_PermissionHolder):
    def __init__(self, user_id: int, nickname: str = "", remark: str = "") -> None:
        super().__init__()
        self.user_id: int = user_id
        self.nickname: str = nickname
        self.remark: str = remark
        self._api_cache: Optional[NapCatClient] = None

    @property
    def _api(self) -> NapCatClient:
        if self._api_cache is None:
            self._api_cache = get_api()
        return self._api_cache

    @property
    def id(self) -> int:
        return self.user_id

    @property
    def display_name(self) -> str:
        return self.nickname or self.remark or str(self.user_id)

    async def send(self, chain: MsgChain) -> MessageData:
        return await chain.send_private(self.user_id, self._api)

    async def send_text(self, text: str) -> MessageData:
        return await self.send(MsgChain.from_text(text))

    async def fetch_info(self) -> StrangerInfo:
        raw = await self._api.get_stranger_info(self.user_id)
        if isinstance(raw, dict):
            return StrangerInfo.from_dict(raw)
        raise NapCatApiError(-1, "获取用户信息失败")

    async def kick(self, group_id: Union[int, str], reject_add_request: bool = False) -> Dict[str, Any]:
        return await self._api.set_group_kick(
            group_id=group_id, user_id=self.user_id, reject_add_request=reject_add_request
        )

    async def mute(self, group_id: Union[int, str], duration: int = 60) -> Dict[str, Any]:
        return await self._api.set_group_ban(
            group_id=group_id, user_id=self.user_id, duration=duration
        )

    def add_role_name(
        self,
        name: str,
        rbac: Optional[RBACManager] = None,
        context: Optional[_Context] = None,
        duration: Optional[float] = None,
    ) -> None:
        if rbac is None:
            raise RuntimeError("add_role_name 需要传入 RBACManager")
        role = rbac.get_role(name)
        if role is None:
            raise KeyError(f"角色<{name}> 不存在")
        self.add_role(role, context, duration)

    def __repr__(self) -> str:
        return f"<User id={self.user_id} name={self.display_name!r}>"


class GroupUser(User):
    def __init__(
        self,
        user_id: int,
        group_id: int,
        nickname: str = "",
        card: str = "",
        role: str = "member",
        title: str = "",
        level: str = "1",
        **extra: Any,
    ) -> None:
        super().__init__(user_id, nickname, card)
        self.group_id: int = group_id
        self.card: str = card
        self.role_name: str = role
        self.title: str = title
        self.level: str = level
        self._extra: Dict[str, Any] = extra

    @property
    def display_name(self) -> str:
        return self.card or self.nickname or str(self.user_id)

    @property
    def is_owner(self) -> bool:
        return self.role_name == "owner"

    @property
    def is_admin(self) -> bool:
        return self.role_name in ("admin", "owner")

    async def kick(self, reject_add_request: bool = False) -> Dict[str, Any]:
        return await self._api.set_group_kick(
            group_id=self.group_id, user_id=self.user_id, reject_add_request=reject_add_request
        )

    async def mute(self, duration: int = 60) -> Dict[str, Any]:
        return await self._api.set_group_ban(
            group_id=self.group_id, user_id=self.user_id, duration=duration
        )

    async def set_card(self, card: str) -> Dict[str, Any]:
        return await self._api.set_group_card(
            group_id=self.group_id, user_id=self.user_id, card=card
        )

    async def set_special_title(self, title: str, duration: int = -1) -> Dict[str, Any]:
        return await self._api.set_group_special_title(
            group_id=self.group_id, user_id=self.user_id, special_title=title, duration=duration
        )

    async def admin_promote(self) -> Dict[str, Any]:
        return await self._api.set_group_admin(
            group_id=self.group_id, user_id=self.user_id, enable=True
        )

    async def admin_dismiss(self) -> Dict[str, Any]:
        return await self._api.set_group_admin(
            group_id=self.group_id, user_id=self.user_id, enable=False
        )

    async def poke(self) -> Dict[str, Any]:
        return await self._api.send_group_msg(
            group_id=self.group_id,
            message=[{"type": "poke", "data": {"qq": str(self.user_id)}}],
        )

    def check(self, perm_str: str, context: Optional[_Context] = None) -> Optional[bool]:
        """群成员权限检查：自动注入本群 group_id，但保留全局权限链"""
        if context is None:
            context = _Context.of(group_id=str(self.group_id))
        return super().check(perm_str, context)

    def can(self, perm_str: str, context: Optional[_Context] = None) -> bool:
        if context is None:
            context = _Context.of(group_id=str(self.group_id))
        return super().can(perm_str, context)

    async def send(self, chain: MsgChain) -> MessageData:
        at_chain = MsgChain.of(AtSeg(self.user_id)) + chain
        return await at_chain.send_group(self.group_id, self._api)

    async def send_text(self, text: str) -> MessageData:
        return await self.send(MsgChain.from_text(text))

    @classmethod
    def from_member_info(cls, info: GroupMemberInfo) -> GroupUser:
        return cls(
            user_id=info.user_id,
            group_id=info.group_id,
            nickname=info.nickname,
            card=info.card,
            role=info.role,
            title=info.title,
            level=info.level,
            join_time=info.join_time,
            last_sent_time=info.last_sent_time,
        )

    def __repr__(self) -> str:
        return (
            f"<GroupUser id={self.user_id} group={self.group_id} "
            f"role={self.role_name} card={self.card!r}>"
        )


class Group(_PermissionHolder):
    def __init__(self, group_id: int, group_name: str = "") -> None:
        super().__init__()
        self.group_id: int = group_id
        self.group_name: str = group_name
        self._api_cache: Optional[NapCatClient] = None

    @property
    def _api(self) -> NapCatClient:
        if self._api_cache is None:
            self._api_cache = get_api()
        return self._api_cache

    @property
    def id(self) -> int:
        return self.group_id

    @property
    def name(self) -> str:
        return self.group_name or f"群 {self.group_id}"

    def can(self, perm_str: str) -> bool:
        return super().can(perm_str)

    def check_member(self, user: Union[User, GroupUser, int], perm: str) -> bool:
        ctx = _Context.of(group_id=str(self.group_id))
        if isinstance(user, int):
            return False
        if isinstance(user, GroupUser):
            return user.can(perm)
        return user.can(perm, ctx)

    async def send(self, chain: MsgChain) -> MessageData:
        return await chain.send_group(self.group_id, self._api)

    async def send_text(self, text: str) -> MessageData:
        return await self.send(MsgChain.from_text(text))

    async def get_member(self, user_id: int, no_cache: bool = False) -> GroupUser:
        raw = await self._api.get_group_member_info(self.group_id, user_id, no_cache)
        if not isinstance(raw, dict):
            raise NapCatApiError(-1, "获取群成员信息失败")
        info = GroupMemberInfo.from_dict(raw)
        return GroupUser.from_member_info(info)

    async def get_member_list(self) -> Tuple[GroupMemberInfo, ...]:
        raw = await self._api.get_group_member_list(self.group_id)
        if isinstance(raw, list):
            return tuple(GroupMemberInfo.from_dict(x) for x in raw)
        raise NapCatApiError(-1, "获取成员列表失败")

    async def mute_all(self, enable: bool = True) -> Dict[str, Any]:
        return await self._api.set_group_whole_ban(self.group_id, enable)

    async def set_name(self, name: str) -> Dict[str, Any]:
        return await self._api.set_group_name(self.group_id, name)

    async def quit(self, dismiss: bool = False) -> Dict[str, Any]:
        return await self._api.set_group_leave(self.group_id, dismiss)

    async def recall(self, message_id: Union[int, str]) -> Dict[str, Any]:
        return await self._api.delete_msg(message_id)

    async def fetch_info(self) -> GroupInfo:
        raw = await self._api.get_group_info(self.group_id)
        if isinstance(raw, dict):
            return GroupInfo.from_dict(raw)
        raise NapCatApiError(-1, "获取群信息失败")

    def __repr__(self) -> str:
        return f"<Group id={self.group_id} name={self.name!r}>"