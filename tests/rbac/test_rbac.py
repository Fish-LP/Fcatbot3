# -*- coding: utf-8 -*-
"""
RBAC 完整测试套件 —— 覆盖引擎层、管理层、容器层及边界异常
通配符语义严格遵循旧版设计：
  *   → 单段通配 [^.]*
  **  → 多段通配 .*
  **. → 前缀任意层级 (?:.*\.)?
  .** → 后缀任意层级 (?:\..*)?
  [regex] → 原生正则
运行: pytest -q tests/rbac/test_rbac.py
"""
from __future__ import annotations

import threading
import time

import pytest

from fcatbot.rbac.engine import (
    _Context,
    _PermissionHolder,
    _PermissionMatcher,
    _Role,
)
from fcatbot.rbac.manager import RBACManager, Role, Track

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def holder() -> _PermissionHolder:
    return _PermissionHolder()


@pytest.fixture
def role_admin() -> _Role:
    r = _Role("admin")
    r.add_permission("group.**")
    return r


@pytest.fixture
def role_mod() -> _Role:
    r = _Role("mod")
    r.add_permission("group.mute")
    r.add_permission("group.kick")
    return r


@pytest.fixture
def manager() -> RBACManager:
    return RBACManager("test")


@pytest.fixture
def rbac_with_roles(manager: RBACManager) -> RBACManager:
    admin = manager.create_role("admin")
    admin.add_permission("group.**")
    mod = manager.create_role("mod")
    mod.add_permission("group.mute")
    return manager


# ============================================================
# 引擎层 —— _PermissionMatcher 通配符匹配（旧版语义）
# ============================================================


class TestPermissionMatcher:
    def test_exact_match(self) -> None:
        assert _PermissionMatcher.match("system.config", "system.config")
        assert not _PermissionMatcher.match("system.config", "system.other")

    def test_single_star_segment(self) -> None:
        """* 只匹配单段（不含 .）"""
        assert _PermissionMatcher.match("*", "anything")
        assert not _PermissionMatcher.match("*", "a.b.c")
        assert _PermissionMatcher.match("user.*.delete", "user.alice.delete")
        assert not _PermissionMatcher.match("user.*.delete", "user.a.b.delete")

    def test_double_star_multi_level(self) -> None:
        """** 匹配任意多段（含 .）"""
        assert _PermissionMatcher.match("**", "a.b.c")
        assert _PermissionMatcher.match("**", "anything")
        assert _PermissionMatcher.match("plugin.**", "plugin.a.b")
        assert _PermissionMatcher.match("plugin.**", "plugin.a")
        assert _PermissionMatcher.match("plugin.**", "plugin")

    def test_double_star_prefix(self) -> None:
        """**. 匹配前缀任意层级"""
        assert _PermissionMatcher.match("**.log", "error.log")
        assert _PermissionMatcher.match("**.log", "a.b.error.log")
        assert not _PermissionMatcher.match("**.log", "error.log.extra")

    def test_double_star_suffix(self) -> None:
        """.** 匹配后缀任意层级"""
        assert _PermissionMatcher.match("plugin.**", "plugin")
        assert _PermissionMatcher.match("plugin.**", "plugin.chatgpt")
        assert _PermissionMatcher.match("plugin.**", "plugin.a.b.c")

    def test_prefix_single_star(self) -> None:
        """plugin.* 只匹配 plugin 的直接子级"""
        assert _PermissionMatcher.match("plugin.*", "plugin.chatgpt")
        assert _PermissionMatcher.match("plugin.*", "plugin.game")
        assert not _PermissionMatcher.match("plugin.*", "plugin")  # 不匹配自身
        assert not _PermissionMatcher.match("plugin.*", "plugin.a.b")  # 不匹配多级
        assert not _PermissionMatcher.match("plugin.*", "other.chatgpt")

    def test_regex_pattern(self) -> None:
        """[regex] 模式使用原生正则"""
        assert _PermissionMatcher.match("[plugin\.(chatgpt|game)]", "plugin.chatgpt")
        assert _PermissionMatcher.match("[plugin\.(chatgpt|game)]", "plugin.game")
        assert not _PermissionMatcher.match("[plugin\.(chatgpt|game)]", "plugin.other")

    def test_mixed_wildcards(self) -> None:
        """混合使用 * 与 **"""
        assert _PermissionMatcher.match("*.**", "a.b.c")
        assert _PermissionMatcher.match("*.*", "a.b")
        assert not _PermissionMatcher.match("*.*", "a.b.c")


# ============================================================
# 引擎层 —— _Context
# ============================================================


class TestContext:
    def test_global_matches_anything(self) -> None:
        global_ctx = _Context()
        specific = _Context.of(group_id="123")
        assert global_ctx.matches(specific)
        assert global_ctx.is_global

    def test_specific_requires_exact_match(self) -> None:
        ctx = _Context.of(group_id="123")
        assert ctx.matches(_Context.of(group_id="123"))
        assert not ctx.matches(_Context.of(group_id="456"))
        assert not ctx.matches(_Context())

    def test_multi_key_superset_match(self) -> None:
        ctx = _Context.of(group_id="123", platform="qq")
        assert ctx.matches(_Context.of(group_id="123", platform="qq", extra="x"))
        assert not ctx.matches(_Context.of(group_id="123"))

    def test_hash_and_eq(self) -> None:
        a = _Context.of(group_id="123")
        b = _Context.of(group_id="123")
        c = _Context.of(group_id="456")
        assert a == b
        assert a != c
        assert hash(a) == hash(b)


# ============================================================
# 引擎层 —— _Role 权限与继承
# ============================================================


class TestRole:
    def test_direct_permission(self) -> None:
        r = _Role("test")
        r.add_permission("plugin.chatgpt")
        assert r.has_permission("plugin.chatgpt")
        assert not r.has_permission("plugin.game")

    def test_wildcard_permission(self) -> None:
        r = _Role("test")
        r.add_permission("plugin.*")
        assert r.has_permission("plugin.chatgpt")
        assert r.has_permission("plugin.game")
        assert not r.has_permission("other.game")
        assert not r.has_permission("plugin.a.b")  # 单星不匹配多级

    def test_double_star_in_role(self) -> None:
        r = _Role("super")
        r.add_permission("**")
        assert r.has_permission("anything")
        assert r.has_permission("a.b.c")
        assert r.has_permission("plugin.chatgpt")

    def test_double_star_prefix_in_role(self) -> None:
        r = _Role("logger")
        r.add_permission("**.log")
        assert r.has_permission("error.log")
        assert r.has_permission("a.b.error.log")
        assert not r.has_permission("error.log.extra")

    def test_double_star_suffix_in_role(self) -> None:
        r = _Role("plugin_admin")
        r.add_permission("plugin.**")
        assert r.has_permission("plugin.chatgpt")
        assert r.has_permission("plugin.a.b.c")
        assert r.has_permission("plugin")
        assert not r.has_permission("other.chatgpt")

    def test_middle_single_star_in_role(self) -> None:
        r = _Role("test")
        r.add_permission("user.*.delete")
        assert r.has_permission("user.alice.delete")
        assert not r.has_permission("user.alice.bob.delete")
        assert not r.has_permission("user.delete")

    def test_regex_in_role(self) -> None:
        r = _Role("regex_test")
        r.add_permission("[plugin\.(chatgpt|game)]")
        assert r.has_permission("plugin.chatgpt")
        assert r.has_permission("plugin.game")
        assert not r.has_permission("plugin.other")

    def test_remove_permission(self) -> None:
        r = _Role("test")
        r.add_permission("plugin.chatgpt")
        assert r.has_permission("plugin.chatgpt")
        r.remove_permission("plugin.chatgpt")
        assert not r.has_permission("plugin.chatgpt")
        # 移除不存在的权限不报错
        r.remove_permission("not.exist")

    def test_inheritance(self) -> None:
        parent = _Role("parent")
        parent.add_permission("parent.perm")
        child = _Role("child")
        child.inherit_from(parent)
        assert child.has_permission("parent.perm")
        assert not parent.has_permission("child.perm")

    def test_remove_parent(self) -> None:
        parent = _Role("parent")
        parent.add_permission("parent.perm")
        child = _Role("child")
        child.inherit_from(parent)
        assert child.has_permission("parent.perm")
        child.remove_parent(parent)
        assert not child.has_permission("parent.perm")

    def test_multi_level_inheritance(self) -> None:
        grand = _Role("grand")
        grand.add_permission("a")
        parent = _Role("parent")
        parent.inherit_from(grand)
        child = _Role("child")
        child.inherit_from(parent)
        assert child.has_permission("a")

    def test_inheritance_wildcard(self) -> None:
        parent = _Role("parent")
        parent.add_permission("group.**")
        child = _Role("child")
        child.inherit_from(parent)
        assert child.has_permission("group.kick")
        assert child.has_permission("group.deep.nested.action")


# ============================================================
# 引擎层 —— _PermissionHolder 全局权限
# ============================================================


class TestPermissionHolderGlobal:
    def test_whitelist_allow(self, holder: _PermissionHolder) -> None:
        holder.permit("plugin.chatgpt")
        assert holder.can("plugin.chatgpt")
        assert holder.check("plugin.chatgpt") is True

    def test_blacklist_deny(self, holder: _PermissionHolder) -> None:
        holder.deny("plugin.chatgpt")
        assert not holder.can("plugin.chatgpt")
        assert holder.check("plugin.chatgpt") is False

    def test_blacklist_overrides_whitelist(self, holder: _PermissionHolder) -> None:
        holder.permit("plugin.**")
        holder.deny("plugin.chatgpt")
        assert not holder.can("plugin.chatgpt")
        assert holder.check("plugin.chatgpt") is False

    def test_double_star_whitelist(self, holder: _PermissionHolder) -> None:
        holder.permit("**")
        assert holder.can("anything.at.all")
        assert holder.can("plugin.chatgpt")

    def test_double_star_blacklist(self, holder: _PermissionHolder) -> None:
        holder.permit("**")
        holder.deny("plugin.chatgpt")
        assert not holder.can("plugin.chatgpt")
        assert holder.can("other.permission")

    def test_single_star_whitelist(self, holder: _PermissionHolder) -> None:
        holder.permit("plugin.*")
        assert holder.can("plugin.chatgpt")
        assert not holder.can("plugin.a.b")  # 单星不匹配多级

    def test_role_permission(
        self, holder: _PermissionHolder, role_admin: _Role
    ) -> None:
        holder.add_role(role_admin)
        assert holder.can("group.kick")
        assert holder.can("group.deep.nested")
        assert not holder.can("other.perm")

    def test_role_inheritance_via_holder(
        self, holder: _PermissionHolder, role_mod: _Role
    ) -> None:
        admin = _Role("admin")
        admin.inherit_from(role_mod)
        admin.add_permission("group.set_name")
        holder.add_role(admin)
        assert holder.can("group.mute")
        assert holder.can("group.set_name")

    def test_undefined_returns_none(self, holder: _PermissionHolder) -> None:
        assert holder.check("anything") is None
        assert not holder.can("anything")

    def test_has_role(self, holder: _PermissionHolder, role_admin: _Role) -> None:
        holder.add_role(role_admin)
        assert holder.has_role("admin")
        assert not holder.has_role("mod")

    def test_remove_role(self, holder: _PermissionHolder, role_admin: _Role) -> None:
        holder.add_role(role_admin)
        holder.remove_role(role_admin)
        assert not holder.has_role("admin")
        assert not holder.can("group.kick")

    def test_unpermit(self, holder: _PermissionHolder) -> None:
        holder.permit("plugin.chatgpt")
        assert holder.can("plugin.chatgpt")
        holder.unpermit("plugin.chatgpt")
        assert not holder.can("plugin.chatgpt")

    def test_undeny(self, holder: _PermissionHolder) -> None:
        holder.deny("plugin.chatgpt")
        assert not holder.can("plugin.chatgpt")
        holder.undeny("plugin.chatgpt")
        assert holder.check("plugin.chatgpt") is None

    def test_metadata(self, holder: _PermissionHolder) -> None:
        holder.set_meta("prefix", "[Admin]")
        assert holder.get_meta("prefix") == "[Admin]"
        assert holder.get_meta("missing", "default") == "default"


# ============================================================
# 引擎层 —— _PermissionHolder 上下文权限
# ============================================================


class TestPermissionHolderContext:
    def test_ctx_whitelist(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx)
        assert holder.can("plugin.game", ctx)
        assert not holder.can("plugin.game")

    def test_ctx_blacklist_overrides_ctx_whitelist(
        self, holder: _PermissionHolder
    ) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx)
        holder.deny("plugin.game", context=ctx)
        assert not holder.can("plugin.game", ctx)

    def test_ctx_overrides_global(self, holder: _PermissionHolder) -> None:
        holder.deny("plugin.game")
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx)
        assert not holder.can("plugin.game")
        assert holder.can("plugin.game", ctx)

    def test_ctx_role(self, holder: _PermissionHolder, role_admin: _Role) -> None:
        ctx = _Context.of(group_id="123")
        holder.add_role(role_admin, context=ctx)
        assert holder.can("group.kick", ctx)
        assert not holder.can("group.kick")

    def test_ctx_blacklist_overrides_global_whitelist(
        self, holder: _PermissionHolder
    ) -> None:
        holder.permit("plugin.game")
        ctx = _Context.of(group_id="123")
        holder.deny("plugin.game", context=ctx)
        assert holder.can("plugin.game")
        assert not holder.can("plugin.game", ctx)

    def test_ctx_expired(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx, duration=0.01)
        assert holder.can("plugin.game", ctx)
        time.sleep(0.02)
        assert not holder.can("plugin.game", ctx)

    def test_ctx_role_expired(
        self, holder: _PermissionHolder, role_admin: _Role
    ) -> None:
        ctx = _Context.of(group_id="123")
        holder.add_role(role_admin, context=ctx, duration=0.01)
        assert holder.can("group.kick", ctx)
        time.sleep(0.02)
        assert not holder.can("group.kick", ctx)

    def test_cleanup_removes_expired(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx, duration=0.01)
        holder.deny("plugin.other", context=ctx, duration=0.01)
        holder.add_role(_Role("tmp"), context=ctx, duration=0.01)
        time.sleep(0.02)
        holder.cleanup()
        assert not holder._ctx_whitelist
        assert not holder._ctx_blacklist
        assert not holder._ctx_roles

    def test_global_fallback_after_ctx_expired(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx, duration=0.01)
        holder.permit("plugin.game")
        time.sleep(0.02)
        assert holder.can("plugin.game")

    def test_ctx_unpermit_specific(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx)
        assert holder.can("plugin.game", ctx)
        holder.unpermit("plugin.game", context=ctx)
        assert not holder.can("plugin.game", ctx)

    def test_ctx_undeny_specific(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.deny("plugin.game", context=ctx)
        assert not holder.can("plugin.game", ctx)
        holder.undeny("plugin.game", context=ctx)
        assert holder.check("plugin.game", ctx) is None


# ============================================================
# 引擎层 —— 完整优先级链
# ============================================================


class TestPermissionPriority:
    def test_full_priority_chain(self, holder: _PermissionHolder) -> None:
        role = _Role("test_role")
        role.add_permission("test.perm")

        # 6. 全局角色
        holder.add_role(role)
        assert holder.check("test.perm") is True

        # 5. 上下文角色（覆盖全局角色）
        ctx = _Context.of(group_id="123")
        ctx_role = _Role("ctx_admin")
        ctx_role.add_permission("test.perm")
        holder.add_role(ctx_role, context=ctx)
        assert holder.check("test.perm", ctx) is True

        # 4. 全局白名单
        holder.permit("test.perm")
        assert holder.check("test.perm") is True

        # 3. 全局黑名单
        holder.deny("test.perm")
        assert holder.check("test.perm") is False

        # 2. 上下文白名单
        holder.permit("test.perm", context=ctx)
        assert holder.check("test.perm", ctx) is True

        # 1. 上下文黑名单
        holder.deny("test.perm", context=ctx)
        assert holder.check("test.perm", ctx) is False

    def test_wildcard_priority(self, holder: _PermissionHolder) -> None:
        holder.permit("plugin.**")
        holder.deny("plugin.chatgpt")
        assert not holder.can("plugin.chatgpt")
        assert holder.can("plugin.game")

    def test_ctx_wildcard_priority(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.**", context=ctx)
        holder.deny("plugin.chatgpt", context=ctx)
        assert not holder.can("plugin.chatgpt", ctx)
        assert holder.can("plugin.game", ctx)


# ============================================================
# 引擎层 —— 并发安全
# ============================================================


class TestConcurrency:
    def test_concurrent_permit(self, holder: _PermissionHolder) -> None:
        def worker() -> None:
            for i in range(50):
                holder.permit(f"perm.{i}")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(50):
            assert holder.can(f"perm.{i}")

    def test_concurrent_check_and_modify(self, holder: _PermissionHolder) -> None:
        holder.permit("base.perm")
        errors: list[Exception] = []

        def modifier() -> None:
            try:
                for i in range(100):
                    holder.permit(f"perm.{i}")
                    holder.can("base.perm")
                    holder.unpermit(f"perm.{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=modifier) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ============================================================
# 管理层 —— RBACManager 角色 CRUD
# ============================================================


class TestRBACManagerRole:
    def test_create_role(self, manager: RBACManager) -> None:
        role = manager.create_role("admin")
        assert role.name == "admin"
        assert manager.get_role("admin") is role
        assert isinstance(role, Role)

    def test_create_duplicate_role(self, manager: RBACManager) -> None:
        manager.create_role("admin")
        with pytest.raises(ValueError, match="已存在"):
            manager.create_role("admin")

    def test_remove_role(self, manager: RBACManager) -> None:
        manager.create_role("admin")
        manager.remove_role("admin")
        assert manager.get_role("admin") is None
        assert not manager.has_role("admin")

    def test_remove_role_not_found(self, manager: RBACManager) -> None:
        with pytest.raises(KeyError, match="不存在"):
            manager.remove_role("ghost")

    def test_remove_role_cleans_inheritance(self, manager: RBACManager) -> None:
        parent = manager.create_role("parent")
        child = manager.create_role("child")
        child.inherit_from(parent)
        manager.remove_role("parent")
        assert not child.has_permission("any")

    def test_get_role_none(self, manager: RBACManager) -> None:
        assert manager.get_role("none") is None

    def test_role_force(self, manager: RBACManager) -> None:
        manager.create_role("admin")
        assert manager.role("admin").name == "admin"
        with pytest.raises(KeyError, match="不存在"):
            manager.role("none")

    def test_has_role(self, manager: RBACManager) -> None:
        manager.create_role("admin")
        assert manager.has_role("admin")
        assert not manager.has_role("mod")


# ============================================================
# 管理层 —— RBACManager 角色权限管理
# ============================================================


class TestRBACManagerPermission:
    def test_add_permission(self, manager: RBACManager) -> None:
        manager.create_role("admin")
        manager.add_permission("admin", "group.**")
        assert manager.role("admin").has_permission("group.kick")
        assert manager.role("admin").has_permission("group.deep.nested")

    def test_add_permission_role_not_found(self, manager: RBACManager) -> None:
        with pytest.raises(KeyError, match="不存在"):
            manager.add_permission("ghost", "perm")

    def test_remove_permission(self, manager: RBACManager) -> None:
        manager.create_role("admin")
        manager.add_permission("admin", "group.kick")
        assert manager.role("admin").has_permission("group.kick")
        manager.remove_permission("admin", "group.kick")
        assert not manager.role("admin").has_permission("group.kick")

    def test_remove_permission_role_not_found(self, manager: RBACManager) -> None:
        with pytest.raises(KeyError, match="不存在"):
            manager.remove_permission("ghost", "perm")

    def test_add_parent(self, manager: RBACManager) -> None:
        parent = manager.create_role("parent")
        parent.add_permission("parent.perm")
        child = manager.create_role("child")
        manager.add_parent("child", "parent")
        assert child.has_permission("parent.perm")

    def test_add_parent_not_found(self, manager: RBACManager) -> None:
        manager.create_role("child")
        with pytest.raises(KeyError, match="不存在"):
            manager.add_parent("child", "ghost")

    def test_add_parent_role_not_found(self, manager: RBACManager) -> None:
        manager.create_role("parent")
        with pytest.raises(KeyError, match="不存在"):
            manager.add_parent("ghost", "parent")

    def test_remove_parent(self, manager: RBACManager) -> None:
        parent = manager.create_role("parent")
        parent.add_permission("parent.perm")
        child = manager.create_role("child")
        manager.add_parent("child", "parent")
        assert child.has_permission("parent.perm")
        manager.remove_parent("child", "parent")
        assert not child.has_permission("parent.perm")

    def test_remove_parent_role_not_found(self, manager: RBACManager) -> None:
        manager.create_role("parent")
        with pytest.raises(KeyError, match="不存在"):
            manager.remove_parent("ghost", "parent")

    def test_cycle_detection_direct(self, manager: RBACManager) -> None:
        a = manager.create_role("a")
        b = manager.create_role("b")
        a.inherit_from(b)
        with pytest.raises(ValueError, match="循环"):
            manager.add_parent("b", "a")

    def test_cycle_detection_indirect(self, manager: RBACManager) -> None:
        manager.create_role("a")
        manager.create_role("b")
        manager.create_role("c")
        manager.add_parent("b", "a")
        manager.add_parent("c", "b")
        with pytest.raises(ValueError, match="循环"):
            manager.add_parent("a", "c")

    def test_no_false_cycle(self, manager: RBACManager) -> None:
        a = manager.create_role("a")
        manager.create_role("b")
        manager.create_role("c")
        manager.add_parent("b", "a")
        manager.add_parent("c", "b")
        # c -> b -> a, 再让 d 继承 c 是正常的
        d = manager.create_role("d")
        manager.add_parent("d", "c")
        assert d.has_permission("any") == a.has_permission("any")


# ============================================================
# 管理层 —— RBACManager 轨道 CRUD
# ============================================================


class TestRBACManagerTrack:
    def test_create_track(self, manager: RBACManager) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        assert track.name == "staff"
        assert manager.get_track("staff") is track

    def test_create_duplicate_track(self, manager: RBACManager) -> None:
        manager.create_role("member")
        manager.create_track("staff", ["member"])
        with pytest.raises(ValueError, match="已存在"):
            manager.create_track("staff", ["member"])

    def test_remove_track(self, manager: RBACManager) -> None:
        manager.create_role("member")
        manager.create_track("staff", ["member"])
        manager.remove_track("staff")
        assert not manager.has_track("staff")

    def test_remove_track_not_found(self, manager: RBACManager) -> None:
        with pytest.raises(KeyError, match="不存在"):
            manager.remove_track("ghost")

    def test_track_bind_role(self, manager: RBACManager) -> None:
        member = manager.create_role("member")
        mod = manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        assert track._role_map["member"] is member
        assert track._role_map["mod"] is mod

    def test_track_missing_role(self, manager: RBACManager) -> None:
        manager.create_role("member")
        track = manager.create_track("staff", ["member", "mod"])
        assert "mod" not in track._role_map


# ============================================================
# 管理层 —— 序列化与反序列化
# ============================================================


class TestSerialization:
    def test_serialize_roundtrip(self, manager: RBACManager) -> None:
        admin = manager.create_role("admin")
        admin.add_permission("group.**")
        mod = manager.create_role("mod")
        mod.add_permission("group.mute")
        mod.inherit_from(admin)
        manager.create_track("staff", ["mod", "admin"])

        data = manager.to_dict()
        restored = RBACManager.from_dict(data)

        assert restored.name == "test"
        assert restored.get_role("admin") is not None
        assert restored.get_role("mod") is not None
        assert restored.get_track("staff") is not None
        assert restored.role("mod").has_permission("group.mute")
        assert any(p.name == "admin" for p in restored.role("mod").parents)
        assert restored.role("admin").has_permission("group.deep.nested")

    def test_serialize_empty_manager(self, manager: RBACManager) -> None:
        data = manager.to_dict()
        restored = RBACManager.from_dict(data)
        assert restored.name == "test"
        assert not restored._roles
        assert not restored._tracks

    def test_serialize_with_wildcard(self, manager: RBACManager) -> None:
        admin = manager.create_role("admin")
        admin.add_permission("**")
        data = manager.to_dict()
        restored = RBACManager.from_dict(data)
        assert restored.role("admin").has_permission("anything.deep.nested")

    def test_from_dict_custom_name(self) -> None:
        data = {"name": "custom", "roles": [], "tracks": {}}
        restored = RBACManager.from_dict(data)
        assert restored.name == "custom"


# ============================================================
# 管理层 —— Track 晋升轨道
# ============================================================


class TestTrack:
    def test_promote_from_nothing(
        self, manager: RBACManager, holder: _PermissionHolder
    ) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        result = track.promote(holder)
        assert result == "member"
        assert holder.has_role("member")

    def test_promote_step(
        self, manager: RBACManager, holder: _PermissionHolder
    ) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        track.promote(holder)
        result = track.promote(holder)
        assert result == "mod"
        assert not holder.has_role("member")
        assert holder.has_role("mod")

    def test_promote_at_top(
        self, manager: RBACManager, holder: _PermissionHolder
    ) -> None:
        manager.create_role("member")
        track = manager.create_track("staff", ["member"])
        track.promote(holder)
        assert track.promote(holder) is None

    def test_demote(self, manager: RBACManager, holder: _PermissionHolder) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        track.promote(holder)
        track.promote(holder)
        result = track.demote(holder)
        assert result == "member"
        assert holder.has_role("member")
        assert not holder.has_role("mod")

    def test_demote_at_bottom(
        self, manager: RBACManager, holder: _PermissionHolder
    ) -> None:
        manager.create_role("member")
        track = manager.create_track("staff", ["member"])
        track.promote(holder)
        assert track.demote(holder) is None

    def test_get_current(self, manager: RBACManager, holder: _PermissionHolder) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        assert track.get_current(holder) is None
        track.promote(holder)
        assert track.get_current(holder) == "member"
        track.promote(holder)
        assert track.get_current(holder) == "mod"

    def test_promote_non_holder(self, manager: RBACManager) -> None:
        manager.create_role("member")
        track = manager.create_track("staff", ["member"])
        assert track.promote("not_a_holder") is None

    def test_demote_non_holder(self, manager: RBACManager) -> None:
        manager.create_role("member")
        track = manager.create_track("staff", ["member"])
        assert track.demote("not_a_holder") is None


# ============================================================
# 容器层 —— User / GroupUser / Group
# ============================================================


class TestUserContainer:
    def test_group_user_auto_context(self) -> None:
        from plugins.adapter.napcat.core.entity import GroupUser

        gu = GroupUser(123, 456, nickname="Bob", role="member")
        r = _Role("mod")
        r.add_permission("group.kick")

        # 1. 全局角色在群内生效（符合直觉）
        gu.add_role(r)
        assert gu.can("group.kick")

        # 2. 群上下文黑名单覆盖全局权限
        gu.deny("group.kick", context=_Context.of(group_id="456"))
        assert not gu.can("group.kick")

        # 3. 群上下文角色补充全局权限
        gu2 = GroupUser(123, 789, role="member")
        gu2.add_role(r, context=_Context.of(group_id="789"))
        assert gu2.can("group.kick")  # 仅在群789生效

    def test_group_user_check_returns_tristate(self) -> None:
        from plugins.adapter.napcat.core.entity import GroupUser

        gu = GroupUser(123, 456)
        assert gu.check("unknown") is None
        assert not gu.can("unknown")

    def test_group_can(self) -> None:
        from plugins.adapter.napcat.core.entity import Group

        g = Group(123, "测试群")
        g.permit("plugin.chatgpt")
        assert g.can("plugin.chatgpt")
        g.deny("plugin.game")
        assert not g.can("plugin.game")

    def test_group_check_member(self) -> None:
        from plugins.adapter.napcat.core.entity import Group, GroupUser, User

        g = Group(456, "测试群")

        # User 全局有权限，在群内检查应生效
        u = User(123, nickname="Alice")
        r = _Role("admin")
        r.add_permission("group.kick")
        u.add_role(r)
        assert g.check_member(u, "group.kick")

        # GroupUser 全局角色生效
        gu = GroupUser(123, 456, role="member")
        gu.add_role(r)
        assert g.check_member(gu, "group.kick")

        # GroupUser 群上下文黑名单可覆盖
        gu.deny("group.kick", context=_Context.of(group_id="456"))
        assert not g.check_member(gu, "group.kick")

        # GroupUser 在其他群的上下文角色，不应使用自身 group_id 进行检查
        gu2 = GroupUser(123, 789, role="member")
        gu2.add_role(r, context=_Context.of(group_id="456"))
        assert g.check_member(gu2, "group.kick")

    def test_group_check_member_int_fallback(self) -> None:
        from plugins.adapter.napcat.core.entity import Group

        g = Group(456)
        assert not g.check_member(123, "any.perm")


# ============================================================
# 边界与异常
# ============================================================


class TestEdgeCases:
    def test_cross_manager_inheritance(self) -> None:
        mgr1 = RBACManager("m1")
        mgr2 = RBACManager("m2")
        r1 = mgr1.create_role("r1")
        r2 = mgr2.create_role("r2")
        r2.inherit_from(r1)
        assert r2.has_permission("any") == r1.has_permission("any")

    def test_wildcard_edge_cases(self) -> None:
        r = _Role("test")
        r.add_permission("plugin.*")
        assert r.has_permission("plugin.a.b") is False  # 单星不匹配多级
        assert not r.has_permission("plugin")  # plugin.* 不匹配 plugin 本身
        r.add_permission("exact")
        assert r.has_permission("exact")
        assert not r.has_permission("exact.suffix")

    def test_double_star_edge_cases(self) -> None:
        r = _Role("test")
        r.add_permission("plugin.**")
        assert r.has_permission("plugin.a.b")  # 双星匹配多级
        assert r.has_permission("plugin")  # 双星也匹配自身
        r.add_permission("**.log")
        assert r.has_permission("error.log")
        assert r.has_permission("a.b.error.log")

    def test_empty_holder(self, holder: _PermissionHolder) -> None:
        assert holder.check("anything") is None
        assert not holder.can("anything")
        assert not holder.has_role("anything")

    def test_context_of_kwargs(self) -> None:
        ctx = _Context.of(group_id="123", channel="main")
        assert ctx._data == {"group_id": "123", "channel": "main"}

    def test_role_repr(self, manager: RBACManager) -> None:
        role = manager.create_role("admin")
        role.add_permission("group.**")
        assert repr(role) == "<Role 'admin' perms=1>"

    def test_track_repr(self, manager: RBACManager) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        assert repr(track) == "<Track 'staff' path=member -> mod>"

    def test_permission_holder_lock(self, holder: _PermissionHolder) -> None:
        # 验证锁存在且可重入
        with holder._lock:
            holder.permit("test")
            assert holder.can("test")

    def test_contextual_entry_expiry_none(self) -> None:
        from fcatbot.rbac.engine import _ContextualEntry

        entry = _ContextualEntry("perm", _Context(), expiry=None)
        assert entry.is_active(_Context(), time.time())

    def test_role_binding_expiry_none(self) -> None:
        from fcatbot.rbac.engine import _RoleBinding

        binding = _RoleBinding(_Role("test"), _Context(), expiry=None)
        assert binding.is_active(_Context(), time.time())

    def test_is_role_typeguard(self) -> None:
        from fcatbot.rbac.manager import is_role

        r = Role("test")
        assert is_role(r)
        assert not is_role(None)

    def test_is_track_typeguard(self) -> None:
        from fcatbot.rbac.manager import is_track

        t = Track("test", ["a"])
        assert is_track(t)
        assert not is_track(None)

    def test_regex_edge_cases(self) -> None:
        """正则模式边界：特殊字符、锚点"""
        # [.*] → 正则 .* 匹配任意字符串（含 a.b）
        assert _PermissionMatcher.match("[.*]", ".*")
        assert _PermissionMatcher.match("[.*]", "a.b")
        assert _PermissionMatcher.match("[.*]", "anything")
        # 使用锚点限制匹配
        assert _PermissionMatcher.match("[plugin\.chatgpt$]", "plugin.chatgpt")
        assert not _PermissionMatcher.match(
            "[plugin\.chatgpt$]", "plugin.chatgpt.extra"
        )
        # 精确锚点测试
        assert _PermissionMatcher.match("[^abc$]", "abc")
        assert not _PermissionMatcher.match("[^abc$]", "abcd")
        # 字符类测试
        assert _PermissionMatcher.match("[plugin\.(chatgpt|game)]", "plugin.chatgpt")
        assert _PermissionMatcher.match("[plugin\.(chatgpt|game)]", "plugin.game")
        assert not _PermissionMatcher.match("[plugin\.(chatgpt|game)]", "plugin.other")

    def test_lru_cache_consistency(self) -> None:
        """验证缓存不会导致跨模式污染"""
        assert _PermissionMatcher.match("plugin.*", "plugin.a")
        assert _PermissionMatcher.match("plugin.**", "plugin.a.b")
        assert _PermissionMatcher.match("plugin.*", "plugin.b")  # 缓存后仍正确
