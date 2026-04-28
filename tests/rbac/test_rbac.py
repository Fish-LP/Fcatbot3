# -*- coding: utf-8 -*-
"""
RBAC 完整测试套件
运行: pytest -q tests/rbac/test_rbac.py
"""
from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from fcatbot.core.client import NapCatClient, set_api
from fcatbot.rbac.engine import _Context, _PermissionHolder, _Role
from fcatbot.rbac.manager import RBACManager, Role, Track


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _mock_api():
    """所有测试自动初始化 mock API，避免容器层 RuntimeError"""
    set_api(NapCatClient("http://localhost:3000"))


@pytest.fixture
def holder() -> _PermissionHolder:
    return _PermissionHolder()


@pytest.fixture
def role_admin() -> _Role:
    r = _Role("admin")
    r.add_permission("group.*")
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
    admin.add_permission("group.*")
    mod = manager.create_role("mod")
    mod.add_permission("group.mute")
    return manager


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

    def test_inheritance(self) -> None:
        parent = _Role("parent")
        parent.add_permission("parent.perm")
        child = _Role("child")
        child.inherit_from(parent)
        assert child.has_permission("parent.perm")
        assert not parent.has_permission("child.perm")

    def test_multi_level_inheritance(self) -> None:
        grand = _Role("grand")
        grand.add_permission("a")
        parent = _Role("parent")
        parent.inherit_from(grand)
        child = _Role("child")
        child.inherit_from(parent)
        assert child.has_permission("a")


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
        holder.permit("plugin.*")
        holder.deny("plugin.chatgpt")
        assert not holder.can("plugin.chatgpt")
        assert holder.check("plugin.chatgpt") is False

    def test_role_permission(self, holder: _PermissionHolder, role_admin: _Role) -> None:
        holder.add_role(role_admin)
        assert holder.can("group.kick")
        assert holder.can("group.mute")
        assert not holder.can("other.perm")

    def test_role_inheritance_via_holder(self, holder: _PermissionHolder, role_mod: _Role) -> None:
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


# ============================================================
# 引擎层 —— _PermissionHolder 上下文权限
# ============================================================

class TestPermissionHolderContext:
    def test_ctx_whitelist(self, holder: _PermissionHolder) -> None:
        ctx = _Context.of(group_id="123")
        holder.permit("plugin.game", context=ctx)
        assert holder.can("plugin.game", ctx)
        assert not holder.can("plugin.game")

    def test_ctx_blacklist_overrides_ctx_whitelist(self, holder: _PermissionHolder) -> None:
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

    def test_ctx_blacklist_overrides_global_whitelist(self, holder: _PermissionHolder) -> None:
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


# ============================================================
# 管理层 —— RBACManager
# ============================================================

class TestRBACManager:
    def test_create_role(self, manager: RBACManager) -> None:
        role = manager.create_role("admin")
        assert role.name == "admin"
        assert manager.get_role("admin") is role

    def test_create_duplicate_role(self, manager: RBACManager) -> None:
        manager.create_role("admin")
        with pytest.raises(ValueError, match="已存在"):
            manager.create_role("admin")

    def test_create_track(self, manager: RBACManager) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        assert track.name == "staff"
        assert manager.get_track("staff") is track

    def test_track_bind_role(self, manager: RBACManager) -> None:
        member = manager.create_role("member")
        mod = manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        assert track._role_map["member"] is member
        assert track._role_map["mod"] is mod

    def test_serialize_roundtrip(self, manager: RBACManager) -> None:
        admin = manager.create_role("admin")
        admin.add_permission("group.*")
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


# ============================================================
# 管理层 —— Track 晋升轨道
# ============================================================

class TestTrack:
    def test_promote_from_nothing(self, manager: RBACManager, holder: _PermissionHolder) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        result = track.promote(holder)
        assert result == "member"
        assert holder.has_role("member")

    def test_promote_step(self, manager: RBACManager, holder: _PermissionHolder) -> None:
        manager.create_role("member")
        manager.create_role("mod")
        track = manager.create_track("staff", ["member", "mod"])
        track.promote(holder)
        result = track.promote(holder)
        assert result == "mod"
        assert not holder.has_role("member")
        assert holder.has_role("mod")

    def test_promote_at_top(self, manager: RBACManager, holder: _PermissionHolder) -> None:
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

    def test_demote_at_bottom(self, manager: RBACManager, holder: _PermissionHolder) -> None:
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


# ============================================================
# 容器层 —— User / GroupUser / Group
# ============================================================

class TestUserContainer:
    def test_group_user_auto_context(self) -> None:
        from fcatbot.models.entity import GroupUser
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
        from fcatbot.models.entity import GroupUser
        gu = GroupUser(123, 456)
        assert gu.check("unknown") is None
        assert not gu.can("unknown")

    def test_group_can(self) -> None:
        from fcatbot.models.entity import Group
        g = Group(123, "测试群")
        g.permit("plugin.chatgpt")
        assert g.can("plugin.chatgpt")
        g.deny("plugin.game")
        assert not g.can("plugin.game")

    def test_group_check_member(self) -> None:
        from fcatbot.models.entity import Group, GroupUser, User
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

    def test_group_check_member_int_fallback(self) -> None:
        from fcatbot.models.entity import Group
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
        assert r.has_permission("plugin.a.b")
        assert not r.has_permission("plugin")  # plugin.* 不匹配 plugin 本身
        r.add_permission("exact")
        assert r.has_permission("exact")
        assert not r.has_permission("exact.suffix")

    def test_empty_holder(self, holder: _PermissionHolder) -> None:
        assert holder.check("anything") is None
        assert not holder.can("anything")
        assert not holder.has_role("anything")

    def test_metadata(self, holder: _PermissionHolder) -> None:
        holder.set_meta("prefix", "[Admin]")
        assert holder.get_meta("prefix") == "[Admin]"
        assert holder.get_meta("missing", "default") == "default"

    def test_context_of_kwargs(self) -> None:
        ctx = _Context.of(group_id="123", channel="main")
        assert ctx._data == {"group_id": "123", "channel": "main"}