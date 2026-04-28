# -*- coding: utf-8 -*-
"""
RBAC 管理层 —— 现代类型设计
"""
from __future__ import annotations

import threading
from typing import (
    Any,
    Dict,
    List,
    TypeGuard,
)

from fcatbot.rbac.engine import _PermissionHolder, _Role


class Role(_Role):
    def __repr__(self) -> str:
        return f"<Role {self.name!r} perms={len(self.permissions)}>"


class Track:
    def __init__(self, name: str, path: List[str]) -> None:
        self.name: str = name
        self._path: List[str] = list(path)
        self._role_map: Dict[str, Role] = {}

    def __repr__(self) -> str:
        return f"<Track {self.name!r} path={' -> '.join(self._path)}>"

    def bind_role(self, name: str, role: Role) -> None:
        self._role_map[name] = role

    def get_current(self, holder: Any) -> str | None:
        from fcatbot.rbac.engine import _PermissionHolder
        if not isinstance(holder, _PermissionHolder):
            return None
        for name in reversed(self._path):
            if holder.has_role(name):
                return name
        return None

    def promote(self, holder: Any) -> str | None:
        from fcatbot.rbac.engine import _PermissionHolder
        if not isinstance(holder, _PermissionHolder):
            return None
        current = self.get_current(holder)
        if current is None and self._path:
            first = self._path[0]
            if first in self._role_map:
                holder.add_role(self._role_map[first])
            return first
        if current and current in self._path:
            idx = self._path.index(current)
            if idx + 1 < len(self._path):
                next_name = self._path[idx + 1]
                if current in self._role_map:
                    holder.remove_role(self._role_map[current])
                if next_name in self._role_map:
                    holder.add_role(self._role_map[next_name])
                return next_name
        return None

    def demote(self, holder: Any) -> str | None:
        from fcatbot.rbac.engine import _PermissionHolder
        if not isinstance(holder, _PermissionHolder):
            return None
        current = self.get_current(holder)
        if current is None:
            return None
        idx = self._path.index(current)
        if idx > 0:
            prev_name = self._path[idx - 1]
            if current in self._role_map:
                holder.remove_role(self._role_map[current])
            if prev_name in self._role_map:
                holder.add_role(self._role_map[prev_name])
            return prev_name
        return None


# ---------- TypeGuard：运行时 + 静态双重收窄 ----------

def is_role(obj: Role | None) -> TypeGuard[Role]:
    """TypeGuard：将 Role | None 收窄为 Role"""
    return obj is not None


def is_track(obj: Track | None) -> TypeGuard[Track]:
    return obj is not None


# ---------- 管理器 ----------

class RBACManager:
    def __init__(self, name: str = "default") -> None:
        self.name: str = name
        self._roles: Dict[str, Role] = {}
        self._tracks: Dict[str, Track] = {}
        self._lock: threading.RLock = threading.RLock()

    def create_role(self, name: str) -> Role:
        with self._lock:
            if name in self._roles:
                raise ValueError(f"角色<{name}> 已存在")
            role = Role(name)
            self._roles[name] = role
            return role

    def get_role(self, name: str) -> Role | None:
        """安全查询。返回 None 表示未找到。"""
        return self._roles.get(name)

    def role(self, name: str) -> Role:
        """
        强制获取。类型纯 Role，无需 Optional 处理。
        找不到时抛 KeyError。
        """
        if name not in self._roles:
            raise KeyError(f"角色<{name}> 不存在")
        return self._roles[name]

    def has_role(self, name: str) -> bool:
        return name in self._roles

    def create_track(self, name: str, path: List[str]) -> Track:
        with self._lock:
            if name in self._tracks:
                raise ValueError(f"轨道<{name}> 已存在")
            track = Track(name, path)
            for role_name in path:
                role = self._roles.get(role_name)
                if role:
                    track.bind_role(role_name, role)
            self._tracks[name] = track
            return track

    def get_track(self, name: str) -> Track | None:
        return self._tracks.get(name)

    def track(self, name: str) -> Track:
        if name not in self._tracks:
            raise KeyError(f"轨道<{name}> 不存在")
        return self._tracks[name]

    def has_track(self, name: str) -> bool:
        return name in self._tracks

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "roles": [
                {
                    "name": r.name,
                    "permissions": list(r.permissions),
                    "parents": [p.name for p in r.parents],
                }
                for r in self._roles.values()
            ],
            "tracks": {name: track._path for name, track in self._tracks.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RBACManager:
        mgr = cls(data.get("name", "loaded"))
        for r_data in data.get("roles", []):
            role = mgr.create_role(r_data["name"])
            for perm in r_data.get("permissions", []):
                role.add_permission(perm)
        for r_data in data.get("roles", []):
            role = mgr._roles[r_data["name"]]
            for parent_name in r_data.get("parents", []):
                parent = mgr._roles.get(parent_name)
                if parent:
                    role.inherit_from(parent)
        for name, path in data.get("tracks", {}).items():
            mgr.create_track(name, path)
        return mgr