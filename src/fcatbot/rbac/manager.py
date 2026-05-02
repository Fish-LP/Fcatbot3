# -*- coding: utf-8 -*-
"""
RBAC 管理层 —— 现代类型设计 + ANSI 可视化（基于 Color 类，树状图风格）
"""
from __future__ import annotations

import threading
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    TypeGuard,
)

from fcatbot.rbac.engine import _PermissionHolder, _Role

# 请根据实际项目路径调整以下导入
from fcatbot.utils.color import Color


class Role(_Role):
    """表示一个角色，继承自 RBAC 引擎层的 _Role。"""

    def __repr__(self) -> str:
        """返回角色的字符串表示。"""
        return f"<Role {self.name!r} perms={len(self.permissions)}>"


class Track:
    """表示角色晋升/降级轨道。"""

    def __init__(self, name: str, path: List[str]) -> None:
        """初始化轨道。

        Args:
            name: 轨道名称。
            path: 按顺序排列的角色名称列表。
        """
        self.name: str = name
        self._path: List[str] = list(path)
        self._role_map: Dict[str, Role] = {}

    def __repr__(self) -> str:
        """返回轨道的字符串表示。"""
        return f"<Track {self.name!r} path={' -> '.join(self._path)}>"

    def bind_role(self, name: str, role: Role) -> None:
        """将角色绑定到轨道中的名称。"""
        self._role_map[name] = role

    def get_current(self, holder: Any) -> str | None:
        """获取持有者当前所在轨道中的角色。

        Args:
            holder: 待检测的权限持有者。

        Returns:
            str | None: 当前角色名称，若持有者不在轨道内或类型不匹配则返回 None。
        """
        if not isinstance(holder, _PermissionHolder):
            return None
        for name in reversed(self._path):
            if holder.has_role(name):
                return name
        return None

    def promote(self, holder: Any) -> str | None:
        """将持有者提升到轨道中的下一个角色。

        Args:
            holder: 待提升的权限持有者。

        Returns:
            str | None: 提升后的角色名称，若无法提升则返回 None。
        """
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
        """将持有者降级到轨道中的前一个角色。

        Args:
            holder: 待降级的权限持有者。

        Returns:
            str | None: 降级后的角色名称，若无法降级则返回 None。
        """
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


# ---------- TypeGuard ----------


def is_role(obj: Role | None) -> TypeGuard[Role]:
    """判断对象是否为 Role 类型。"""
    return obj is not None


def is_track(obj: Track | None) -> TypeGuard[Track]:
    """判断对象是否为 Track 类型。"""
    return obj is not None


# ---------- 管理器 + 可视化 ----------


class RBACManager:
    """RBAC 管理器，负责角色和轨道的创建与查询，以及角色权限的增删管理。"""

    def __init__(self, name: str = "default") -> None:
        """初始化 RBAC 管理器。

        Args:
            name: 管理器名称。
        """
        self.name: str = name
        self._roles: Dict[str, Role] = {}
        self._tracks: Dict[str, Track] = {}
        self._lock: threading.RLock = threading.RLock()

    # ---------- 角色 CRUD ----------

    def create_role(self, name: str) -> Role:
        """创建一个新角色。

        Args:
            name: 角色名称。

        Returns:
            Role: 创建的角色对象。

        Raises:
            ValueError: 角色已存在时抛出。
        """
        with self._lock:
            if name in self._roles:
                raise ValueError(f"角色<{name}> 已存在")
            role = Role(name)
            self._roles[name] = role
            return role

    def remove_role(self, name: str) -> None:
        """删除角色，并清理其他角色对其的继承关系。

        Args:
            name: 待删除的角色名称。

        Raises:
            KeyError: 角色不存在时抛出。
        """
        with self._lock:
            role = self._roles.get(name)
            if role is None:
                raise KeyError(f"角色<{name}> 不存在")
            for r in self._roles.values():
                r.remove_parent(role)
            del self._roles[name]

    def get_role(self, name: str) -> Role | None:
        """安全获取角色。"""
        return self._roles.get(name)

    def role(self, name: str) -> Role:
        """强制获取角色，找不到时抛 KeyError。"""
        if name not in self._roles:
            raise KeyError(f"角色<{name}> 不存在")
        return self._roles[name]

    def has_role(self, name: str) -> bool:
        """检查角色是否存在。"""
        return name in self._roles

    # ---------- 角色权限管理 ----------

    def add_permission(self, role_name: str, perm: str) -> None:
        """给指定角色添加权限。

        Args:
            role_name: 角色名称。
            perm: 权限字符串，支持按 '.' 分层及通配符。

        Raises:
            KeyError: 角色不存在时抛出。
        """
        with self._lock:
            role = self._roles.get(role_name)
            if role is None:
                raise KeyError(f"角色<{role_name}> 不存在")
            role.add_permission(perm)

    def remove_permission(self, role_name: str, perm: str) -> None:
        """从指定角色移除权限。

        Args:
            role_name: 角色名称。
            perm: 待移除的权限字符串。

        Raises:
            KeyError: 角色不存在时抛出。
        """
        with self._lock:
            role = self._roles.get(role_name)
            if role is None:
                raise KeyError(f"角色<{role_name}> 不存在")
            role.remove_permission(perm)

    def add_parent(self, role_name: str, parent_name: str) -> None:
        """给角色添加父角色继承关系。

        Args:
            role_name: 子角色名称。
            parent_name: 父角色名称。

        Raises:
            KeyError: 角色或父角色不存在时抛出。
            ValueError: 形成循环继承时抛出。
        """
        with self._lock:
            role = self._roles.get(role_name)
            parent = self._roles.get(parent_name)
            if role is None:
                raise KeyError(f"角色<{role_name}> 不存在")
            if parent is None:
                raise KeyError(f"父角色<{parent_name}> 不存在")
            if self._would_cycle(role, parent):
                raise ValueError(
                    f"无法建立继承：<{role_name}> -> <{parent_name}> 会形成循环"
                )
            role.inherit_from(parent)

    def remove_parent(self, role_name: str, parent_name: str) -> None:
        """移除角色的父角色继承关系。

        Args:
            role_name: 子角色名称。
            parent_name: 父角色名称。

        Raises:
            KeyError: 角色不存在时抛出。
        """
        with self._lock:
            role = self._roles.get(role_name)
            parent = self._roles.get(parent_name)
            if role is None:
                raise KeyError(f"角色<{role_name}> 不存在")
            if parent:
                role.remove_parent(parent)

    def _would_cycle(self, role: Role, parent: Role) -> bool:
        """检测添加 parent 是否会导致循环继承。

        Args:
            role: 待检测的子角色。
            parent: 待添加的父角色。

        Returns:
            bool: 若会形成循环则返回 True。
        """
        visited: set[str] = set()

        def dfs(r: Role) -> bool:
            if r.name == role.name:
                return True
            if r.name in visited:
                return False
            visited.add(r.name)
            return any(dfs(p) for p in r.parents)

        return dfs(parent)

    # ---------- 轨道 CRUD ----------

    def create_track(self, name: str, path: List[str]) -> Track:
        """创建一个新轨道，并将已存在角色绑定到轨道中。

        Args:
            name: 轨道名称。
            path: 角色名称晋升路径。

        Returns:
            Track: 创建的轨道对象。

        Raises:
            ValueError: 轨道已存在时抛出。
        """
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

    def remove_track(self, name: str) -> None:
        """删除指定轨道。

        Args:
            name: 轨道名称。

        Raises:
            KeyError: 轨道不存在时抛出。
        """
        with self._lock:
            if name not in self._tracks:
                raise KeyError(f"轨道<{name}> 不存在")
            del self._tracks[name]

    def get_track(self, name: str) -> Track | None:
        """安全获取轨道。"""
        return self._tracks.get(name)

    def track(self, name: str) -> Track:
        """强制获取轨道，找不到时抛 KeyError。"""
        if name not in self._tracks:
            raise KeyError(f"轨道<{name}> 不存在")
        return self._tracks[name]

    def has_track(self, name: str) -> bool:
        """检查轨道是否存在。"""
        return name in self._tracks

    # ---------- 序列化 ----------

    def to_dict(self) -> Dict[str, Any]:
        """将当前角色与轨道配置序列化为字典。"""
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
        """从字典加载 RBAC 管理器状态。

        Args:
            data: 由 to_dict 生成的字典数据。

        Returns:
            RBACManager: 恢复状态的管理器实例。
        """
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

    # ============================================================
    # ANSI 可视化（基于 Color 类，纯树状图风格，无外框）
    # ============================================================

    def visualize_permission_tree(
        self,
        role_name: str,
        *,
        color: bool = True,
        show_inherited: bool = True,
    ) -> str:
        """以 ANSI 美化树形结构展示角色的权限层级。

        Args:
            role_name: 目标角色名称。
            color: 是否启用 ANSI 颜色（自动兼容 Windows VT 模式）。
            show_inherited: 是否包含继承自父角色的权限。

        Returns:
            str: 格式化后的树形字符串。
        """
        original = Color._ColorEnabled
        Color._ColorEnabled = color and original

        try:
            role = self.get_role(role_name)
            if role is None:
                return f"{Color.Red}角色 <{role_name}> 不存在{Color.Reset}"

            # 收集权限
            perms: Set[str] = set(role.permissions)
            if show_inherited:
                visited: Set[str] = set()
                stack = list(role.parents)
                while stack:
                    r = stack.pop()
                    if r.name in visited:
                        continue
                    visited.add(r.name)
                    perms.update(r.permissions)
                    stack.extend(r.parents)

            if not perms:
                return f"{Color.Yellow}角色 <{role_name}> 无任何权限{Color.Reset}"

            # 构建树
            tree: Dict[str, Any] = {}
            for perm in sorted(perms):
                parts = perm.split(".")
                node = tree
                for part in parts:
                    if part not in node:
                        node[part] = {}
                    node = node[part]

            lines: List[str] = [f"{Color.Bold}{Color.Cyan}{role_name}{Color.Reset}"]

            def _walk(
                node: Dict[str, Any], prefix: str = "", is_last: bool = True
            ) -> None:
                items = list(node.items())
                for i, (key, child) in enumerate(items):
                    is_last_child = i == len(items) - 1
                    branch = (
                        f"{Color.Yellow}└──{Color.Reset}"
                        if is_last_child
                        else f"{Color.Yellow}├──{Color.Reset}"
                    )
                    has_children = bool(child)

                    # 高亮通配符
                    display_key = key.replace("*", f"{Color.Magenta}*{Color.Green}")

                    if has_children:
                        lines.append(
                            f"{prefix}{branch} {Color.Green}{display_key}{Color.Reset}"
                        )
                        ext = (
                            f"{Color.Yellow}    {Color.Reset}"
                            if is_last_child
                            else f"{Color.Yellow}│   {Color.Reset}"
                        )
                        _walk(child, prefix + ext, is_last_child)
                    else:
                        lines.append(
                            f"{prefix}{branch} {Color.Green}{display_key}{Color.Reset}"
                        )

            _walk(tree)
            return "\n".join(lines)
        finally:
            Color._ColorEnabled = original

    def visualize_inheritance_graph(
        self,
        *,
        color: bool = True,
        highlight: Optional[str] = None,
    ) -> str:
        """以 ANSI 美化树状图展示角色继承关系。

        Args:
            color: 是否启用 ANSI 颜色。
            highlight: 高亮显示指定角色的名称。

        Returns:
            str: 格式化后的继承关系字符串。
        """
        original = Color._ColorEnabled
        Color._ColorEnabled = color and original

        try:
            if not self._roles:
                return f"{Color.Yellow}当前管理器无任何角色{Color.Reset}"

            lines: List[str] = [f"{Color.Bold}{Color.Cyan}角色继承结构{Color.Reset}"]

            # 找出根角色（不被任何其他角色继承的顶层）
            all_parents: Set[str] = set()
            for r in self._roles.values():
                for p in r.parents:
                    all_parents.add(p.name)

            roots = [r for r in self._roles.values() if r.name not in all_parents]
            if not roots:
                roots = list(self._roles.values())

            visited: Set[str] = set()

            def _draw(role: Role, prefix: str = "", is_last: bool = True) -> None:
                if role.name in visited:
                    marker = f"{Color.Red}[循环] {Color.Reset}"
                else:
                    marker = ""
                    visited.add(role.name)

                is_hl = highlight and role.name == highlight
                name_fmt = (
                    f"{Color.BgYellow}{Color.Black} {role.name} {Color.Reset}"
                    if is_hl
                    else f"{Color.Green}{role.name}{Color.Reset}"
                )

                lines.append(
                    f"{prefix}{Color.Yellow}{'└── ' if is_last else '├── '}{Color.Reset}{marker}{name_fmt} "
                    f"{Color.Gray}[{len(role.permissions)} perms]{Color.Reset}"
                )

                children = [
                    r
                    for r in self._roles.values()
                    if any(p.name == role.name for p in r.parents)
                ]
                for i, child in enumerate(children):
                    is_last_child = i == len(children) - 1
                    ext = (
                        f"{Color.Yellow}    {Color.Reset}"
                        if is_last
                        else f"{Color.Yellow}│   {Color.Reset}"
                    )
                    _draw(child, prefix + ext, is_last_child)

            for i, root in enumerate(roots):
                _draw(root, "", i == len(roots) - 1)

            return "\n".join(lines)
        finally:
            Color._ColorEnabled = original

    def visualize_all_roles(
        self,
        *,
        color: bool = True,
        show_permissions: bool = True,
    ) -> str:
        """以 ANSI 美化树状图展示所有角色的权限与继承概览。

        Args:
            color: 是否启用 ANSI 颜色。
            show_permissions: 是否列出每个角色的具体权限。

        Returns:
            str: 格式化后的概览字符串。
        """
        original = Color._ColorEnabled
        Color._ColorEnabled = color and original

        try:
            if not self._roles:
                return f"{Color.Yellow}当前管理器无任何角色{Color.Reset}"

            lines: List[str] = [
                f"{Color.Bold}{Color.Cyan}RBAC 角色权限总览{Color.Reset}"
            ]

            for role in self._roles.values():
                # 角色标题行
                lines.append(
                    f"{Color.Bold}{Color.Cyan}├──{Color.Reset} {Color.BgGreen}{Color.Black} {role.name} {Color.Reset}"
                )

                # 继承信息
                if role.parents:
                    parents_str = ", ".join(p.name for p in role.parents)
                    lines.append(
                        f"{Color.Cyan}│   {Color.Reset}{Color.Yellow}↳ 继承: {Color.Reset}{Color.Cyan}{parents_str}{Color.Reset}"
                    )

                # 权限列表
                if show_permissions and role.permissions:
                    perms = sorted(role.permissions)
                    for j, perm in enumerate(perms):
                        is_last_perm = j == len(perms) - 1
                        branch = (
                            f"{Color.Cyan}└──{Color.Reset}"
                            if is_last_perm
                            else f"{Color.Cyan}├──{Color.Reset}"
                        )
                        # 高亮通配符
                        display = perm.replace("*", f"{Color.Magenta}*{Color.Green}")
                        lines.append(
                            f"{Color.Cyan}│   {Color.Reset}{branch} {Color.Green}{display}{Color.Reset}"
                        )

                if not role.permissions:
                    lines.append(
                        f"{Color.Cyan}│   {Color.Reset}{Color.Gray}(无直接权限){Color.Reset}"
                    )

            return "\n".join(lines)
        finally:
            Color._ColorEnabled = original
