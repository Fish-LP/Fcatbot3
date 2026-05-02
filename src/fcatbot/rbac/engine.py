# -*- coding: utf-8 -*-
"""
RBAC 引擎层：上下文、权限匹配、权限持有者公共逻辑
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set


# ---------- 上下文 ----------
class _Context:
    """表示一个权限检查上下文。

    上下文支持键值对匹配，用于区分不同场景的权限判断。
    """

    __slots__ = ("_data",)

    def __init__(self, data: Optional[Dict[str, str]] = None) -> None:
        """初始化上下文。"""
        self._data: Dict[str, str] = dict(data) if data else {}

    @property
    def is_global(self) -> bool:
        """返回当前上下文是否为全局上下文（无任何键值）。"""
        return not self._data

    def matches(self, other: _Context) -> bool:
        """判断当前上下文是否匹配另一个上下文。

        Args:
            other: 用于匹配的另一个上下文对象。

        Returns:
            bool: 若当前上下文包含的所有键值均与 other 匹配，则返回 True。
        """
        if not self._data:
            return True
        return all(other._data.get(k) == v for k, v in self._data.items())

    @classmethod
    def of(cls, **kwargs: str) -> _Context:
        """创建一个由关键字参数构造的上下文。"""
        return cls(kwargs)

    def __eq__(self, other: object) -> bool:
        """比较两个上下文是否相等。"""
        return isinstance(other, _Context) and self._data == other._data

    def __hash__(self) -> int:
        """返回上下文的哈希值。"""
        return hash(tuple(sorted(self._data.items())))


# ---------- 权限匹配 ----------
class _PermissionMatcher:
    """权限匹配器，支持精确匹配、通配符与正则表达式。

    匹配规则：
    - 精确匹配: ``system.config``
    - 单星通配: ``*`` 匹配任意单段（不含 ``.``）
    - 双星通配: ``**`` 匹配任意多段（含 ``.``）
    - 正则模式: ``[regex_here]``
    """

    @staticmethod
    @lru_cache(maxsize=512)
    def _compile_pattern(pattern: str) -> re.Pattern[str]:
        """编译权限模式为正则表达式。

        Args:
            pattern: 权限模式字符串。

        Returns:
            re.Pattern: 编译后的正则对象。
        """
        # 正则模式：[regex]
        if pattern.startswith("[") and pattern.endswith("]"):
            return re.compile(pattern[1:-1])

        regex = re.escape(pattern)
        # **后面跟着. → (?:.*\.)?
        regex = regex.replace(r"\*\*\.", "(?:.*\\.)?")
        # **前面跟着. → (?:\..*)?
        regex = regex.replace(r"\.\*\*", "(?:\\..*)?")
        # 单独的** → .*
        regex = regex.replace(r"\*\*", ".*")
        # 单星 → [^.]*
        regex = regex.replace(r"\*", "[^.]*")
        return re.compile(f"^{regex}$")

    @staticmethod
    def match(pattern: str, perm: str) -> bool:
        """判断权限模式是否匹配目标权限。

        Args:
            pattern: 权限模式，支持精确匹配、通配符或正则。
            perm: 待匹配的实际权限字符串。

        Returns:
            bool: 当 pattern 与 perm 匹配时返回 True。
        """
        compiled = _PermissionMatcher._compile_pattern(pattern)
        return compiled.fullmatch(perm) is not None


# ---------- 角色 ----------
@dataclass(unsafe_hash=True)
class _Role:
    """角色定义，包含权限集合和父角色继承关系。"""

    name: str
    permissions: Set[str] = field(default_factory=set, compare=False, hash=False)
    parents: List[_Role] = field(default_factory=list, compare=False, hash=False)

    def add_permission(self, perm: str) -> None:
        """添加权限到角色。"""
        self.permissions.add(perm)

    def remove_permission(self, perm: str) -> None:
        """从角色移除指定权限。

        Args:
            perm: 待移除的权限字符串。
        """
        self.permissions.discard(perm)

    def inherit_from(self, parent: _Role) -> None:
        """继承另一个角色的权限。"""
        self.parents.append(parent)

    def remove_parent(self, parent: _Role) -> None:
        """移除与指定父角色的继承关系。

        Args:
            parent: 待移除的父角色对象。
        """
        if parent in self.parents:
            self.parents.remove(parent)

    def has_permission(self, perm_str: str) -> bool:
        """检查角色是否拥有指定权限。

        Args:
            perm_str: 待检查的权限字符串。

        Returns:
            bool: 如果当前角色或任意父角色匹配该权限则返回 True。
        """
        if any(_PermissionMatcher.match(p, perm_str) for p in self.permissions):
            return True
        return any(parent.has_permission(perm_str) for parent in self.parents)


# ---------- 上下文条目 ----------
@dataclass
class _ContextualEntry:
    """表示上下文条件下的单个权限条目。"""

    perm: str
    context: _Context
    expiry: Optional[float] = None

    def is_active(self, check_ctx: _Context, now: float) -> bool:
        """判断该上下文条目是否在当前检查时有效。"""
        if self.expiry is not None and now > self.expiry:
            return False
        return self.context.matches(check_ctx)


@dataclass
class _RoleBinding:
    """表示上下文条件下的角色绑定。"""

    role: _Role
    context: _Context
    expiry: Optional[float] = None

    def is_active(self, check_ctx: _Context, now: float) -> bool:
        """判断该角色绑定是否在当前检查时有效。"""
        if self.expiry is not None and now > self.expiry:
            return False
        return self.context.matches(check_ctx)


# ---------- 权限持有者公共基类 ----------
class _PermissionHolder:
    """表示具有权限、黑白名单和角色绑定能力的对象。"""

    def __init__(self) -> None:
        """初始化权限持有者的内部数据结构。"""
        self._roles: Set[_Role] = set()
        self._whitelist: Set[str] = set()
        self._blacklist: Set[str] = set()
        self._ctx_whitelist: List[_ContextualEntry] = []
        self._ctx_blacklist: List[_ContextualEntry] = []
        self._ctx_roles: List[_RoleBinding] = []
        self._metadata: Dict[str, Any] = {}
        self._lock: threading.RLock = threading.RLock()

    def set_meta(self, key: str, value: Any) -> None:
        """设置元数据键值。"""
        with self._lock:
            self._metadata[key] = value

    def get_meta(self, key: str, default: Any = None) -> Any:
        """获取元数据值。"""
        with self._lock:
            return self._metadata.get(key, default)

    def permit(
        self,
        perm: str,
        context: Optional[_Context] = None,
        duration: Optional[float] = None,
    ) -> None:
        """允许特定权限。

        Args:
            perm: 权限字符串。
            context: 可选的上下文约束。
            duration: 可选的有效期，单位秒。
        """
        if context is None and duration is None:
            with self._lock:
                self._whitelist.add(perm)
            return
        ctx = context or _Context()
        expiry = time.time() + duration if duration else None
        with self._lock:
            self._ctx_whitelist.append(_ContextualEntry(perm, ctx, expiry))

    def deny(
        self,
        perm: str,
        context: Optional[_Context] = None,
        duration: Optional[float] = None,
    ) -> None:
        """拒绝特定权限。

        Args:
            perm: 权限字符串。
            context: 可选的上下文约束。
            duration: 可选的有效期，单位秒。
        """
        if context is None and duration is None:
            with self._lock:
                self._blacklist.add(perm)
            return
        ctx = context or _Context()
        expiry = time.time() + duration if duration else None
        with self._lock:
            self._ctx_blacklist.append(_ContextualEntry(perm, ctx, expiry))

    def unpermit(self, perm: str, context: Optional[_Context] = None) -> None:
        """移除特定权限允许条目。

        Args:
            perm: 权限字符串。
            context: 若提供，仅移除匹配该上下文的条目；否则移除全局白名单条目。
        """
        if context is None:
            with self._lock:
                self._whitelist.discard(perm)
            return
        with self._lock:
            self._ctx_whitelist = [
                e
                for e in self._ctx_whitelist
                if not (e.perm == perm and e.context == context)
            ]

    def undeny(self, perm: str, context: Optional[_Context] = None) -> None:
        """移除特定权限拒绝条目。

        Args:
            perm: 权限字符串。
            context: 若提供，仅移除匹配该上下文的条目；否则移除全局黑名单条目。
        """
        if context is None:
            with self._lock:
                self._blacklist.discard(perm)
            return
        with self._lock:
            self._ctx_blacklist = [
                e
                for e in self._ctx_blacklist
                if not (e.perm == perm and e.context == context)
            ]

    def add_role(
        self,
        role: _Role,
        context: Optional[_Context] = None,
        duration: Optional[float] = None,
    ) -> None:
        """添加角色到持有者。

        Args:
            role: 需要绑定的角色对象。
            context: 可选的上下文约束。
            duration: 可选的有效期，单位秒。
        """
        if context is None and duration is None:
            with self._lock:
                self._roles.add(role)
            return
        ctx = context or _Context()
        expiry = time.time() + duration if duration else None
        with self._lock:
            self._ctx_roles.append(_RoleBinding(role, ctx, expiry))

    def remove_role(self, role: _Role) -> None:
        """移除持有的角色（同时清理全局角色与上下文角色绑定）。"""
        with self._lock:
            self._roles.discard(role)
            self._ctx_roles = [b for b in self._ctx_roles if b.role != role]

    def has_role(self, name: str) -> bool:
        """判断是否拥有指定名称的角色（包括全局角色与任意活跃上下文绑定）。"""
        for r in self._roles:
            if r.name == name:
                return True
        now = time.time()
        for binding in self._ctx_roles:
            if binding.expiry is None or binding.expiry > now:
                if binding.role.name == name:
                    return True
        return False

    def check(
        self, perm_str: str, context: Optional[_Context] = None
    ) -> Optional[bool]:
        """检查权限是否被允许或拒绝。

        Args:
            perm_str: 待检查的权限字符串。
            context: 可选的上下文约束。

        Returns:
            Optional[bool]: 返回 True 表示允许，False 表示拒绝，None 表示未明确授权。
        """
        ctx = context or _Context()
        now = time.time()
        with self._lock:
            for entry in self._ctx_blacklist:
                if entry.is_active(ctx, now) and _PermissionMatcher.match(
                    entry.perm, perm_str
                ):
                    return False
            for entry in self._ctx_whitelist:
                if entry.is_active(ctx, now) and _PermissionMatcher.match(
                    entry.perm, perm_str
                ):
                    return True
            for p in self._blacklist:
                if _PermissionMatcher.match(p, perm_str):
                    return False
            for p in self._whitelist:
                if _PermissionMatcher.match(p, perm_str):
                    return True
            for binding in self._ctx_roles:
                if binding.is_active(ctx, now) and binding.role.has_permission(
                    perm_str
                ):
                    return True
            for r in self._roles:
                if r.has_permission(perm_str):
                    return True
            return None

    def can(self, perm_str: str, context: Optional[_Context] = None) -> bool:
        """判断是否拥有指定权限。"""
        return self.check(perm_str, context) is True

    def cleanup(self) -> None:
        """清理已过期的上下文权限和角色绑定。"""
        now = time.time()
        with self._lock:
            self._ctx_whitelist = [
                e for e in self._ctx_whitelist if e.expiry is None or e.expiry > now
            ]
            self._ctx_blacklist = [
                e for e in self._ctx_blacklist if e.expiry is None or e.expiry > now
            ]
            self._ctx_roles = [
                e for e in self._ctx_roles if e.expiry is None or e.expiry > now
            ]
