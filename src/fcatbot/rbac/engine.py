# -*- coding: utf-8 -*-
"""
RBAC 引擎层：上下文、权限匹配、权限持有者公共逻辑
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union


# ---------- 上下文 ----------
class _Context:
    __slots__ = ("_data",)

    def __init__(self, data: Optional[Dict[str, str]] = None) -> None:
        self._data: Dict[str, str] = dict(data) if data else {}

    @property
    def is_global(self) -> bool:
        return not self._data

    def matches(self, other: _Context) -> bool:
        if not self._data:
            return True
        return all(other._data.get(k) == v for k, v in self._data.items())

    @classmethod
    def of(cls, **kwargs: str) -> _Context:
        return cls(kwargs)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Context) and self._data == other._data

    def __hash__(self) -> int:
        return hash(tuple(sorted(self._data.items())))


# ---------- 权限匹配 ----------
class _PermissionMatcher:
    @staticmethod
    def match(pattern: str, perm: str) -> bool:
        if pattern == perm:
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            # plugin.* 匹配 plugin.a 但不匹配 plugin 本身
            return perm.startswith(prefix + ".")
        return False


# ---------- 角色（修复：添加 unsafe_hash，使 set[_Role] 可用） ----------
@dataclass(unsafe_hash=True)
class _Role:
    name: str
    permissions: Set[str] = field(default_factory=set, compare=False, hash=False)
    parents: List[_Role] = field(default_factory=list, compare=False, hash=False)

    def add_permission(self, perm: str) -> None:
        self.permissions.add(perm)

    def inherit_from(self, parent: _Role) -> None:
        self.parents.append(parent)

    def has_permission(self, perm_str: str) -> bool:
        if any(_PermissionMatcher.match(p, perm_str) for p in self.permissions):
            return True
        return any(parent.has_permission(perm_str) for parent in self.parents)


# ---------- 上下文条目 ----------
@dataclass
class _ContextualEntry:
    perm: str
    context: _Context
    expiry: Optional[float] = None

    def is_active(self, check_ctx: _Context, now: float) -> bool:
        if self.expiry is not None and now > self.expiry:
            return False
        return self.context.matches(check_ctx)


@dataclass
class _RoleBinding:
    role: _Role
    context: _Context
    expiry: Optional[float] = None

    def is_active(self, check_ctx: _Context, now: float) -> bool:
        if self.expiry is not None and now > self.expiry:
            return False
        return self.context.matches(check_ctx)


# ---------- 权限持有者公共基类 ----------
class _PermissionHolder:
    def __init__(self) -> None:
        self._roles: Set[_Role] = set()
        self._whitelist: Set[str] = set()
        self._blacklist: Set[str] = set()
        self._ctx_whitelist: List[_ContextualEntry] = []
        self._ctx_blacklist: List[_ContextualEntry] = []
        self._ctx_roles: List[_RoleBinding] = []
        self._metadata: Dict[str, Any] = {}
        self._lock: threading.RLock = threading.RLock()

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:
            self._metadata[key] = value

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._metadata.get(key, default)

    def permit(
        self,
        perm: str,
        context: Optional[_Context] = None,
        duration: Optional[float] = None,
    ) -> None:
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
        if context is None and duration is None:
            with self._lock:
                self._blacklist.add(perm)
            return
        ctx = context or _Context()
        expiry = time.time() + duration if duration else None
        with self._lock:
            self._ctx_blacklist.append(_ContextualEntry(perm, ctx, expiry))

    def add_role(
        self,
        role: _Role,
        context: Optional[_Context] = None,
        duration: Optional[float] = None,
    ) -> None:
        if context is None and duration is None:
            with self._lock:
                self._roles.add(role)
            return
        ctx = context or _Context()
        expiry = time.time() + duration if duration else None
        with self._lock:
            self._ctx_roles.append(_RoleBinding(role, ctx, expiry))

    def remove_role(self, role: _Role) -> None:
        with self._lock:
            self._roles.discard(role)

    def has_role(self, name: str) -> bool:
        for r in self._roles:
            if r.name == name:
                return True
        return False

    def check(self, perm_str: str, context: Optional[_Context] = None) -> Optional[bool]:
        ctx = context or _Context()
        now = time.time()
        with self._lock:
            for entry in self._ctx_blacklist:
                if entry.is_active(ctx, now) and _PermissionMatcher.match(entry.perm, perm_str):
                    return False
            for entry in self._ctx_whitelist:
                if entry.is_active(ctx, now) and _PermissionMatcher.match(entry.perm, perm_str):
                    return True
            for p in self._blacklist:
                if _PermissionMatcher.match(p, perm_str):
                    return False
            for p in self._whitelist:
                if _PermissionMatcher.match(p, perm_str):
                    return True
            for binding in self._ctx_roles:
                if binding.is_active(ctx, now) and binding.role.has_permission(perm_str):
                    return True
            for r in self._roles:
                if r.has_permission(perm_str):
                    return True
            return None

    def can(self, perm_str: str, context: Optional[_Context] = None) -> bool:
        return self.check(perm_str, context) is True

    def cleanup(self) -> None:
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