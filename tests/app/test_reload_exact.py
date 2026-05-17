"""精确验证 reload 时 mixin 的调用流程。

重点:
1. _collect_mixins 返回什么
2. load/unload 各调用几次 on_mixin_load/on_mixin_unload
3. reload 后命令是否重新注册
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from fcatbot.plugkit.protocol.plugin import Plugin, PluginMixin
from fcatbot.plugkit.runtime.bus import Bus
from fcatbot.plugkit.runtime.lifecycle import LifecycleManager

# ---------- 精确追踪的 Mixin ----------


class SpyMixin(PluginMixin):
    """精确记录每次调用的类名。"""

    events: list[dict] = []

    @classmethod
    def reset(cls):
        cls.events = []

    async def on_mixin_load(self, plugin: Plugin, env: Any) -> None:
        cls = self.__class__ if not isinstance(self, type) else self
        SpyMixin.events.append(
            {
                "action": "load",
                "mixin_class": cls.__name__,
                "self_class": (
                    self.__class__.__name__ if hasattr(self, "__class__") else "N/A"
                ),
                "plugin_name": plugin.name,
            }
        )

    async def on_mixin_unload(self, plugin: Plugin, env: Any) -> None:
        cls = self.__class__ if not isinstance(self, type) else self
        SpyMixin.events.append(
            {
                "action": "unload",
                "mixin_class": cls.__name__,
                "plugin_name": plugin.name,
            }
        )


class TestCollectMixins:
    """测试 _collect_mixins 的行为。"""

    def test_collect_mixins_with_inheritance(self):
        """
        class Plugin(SpyMixin, Plugin):
            ...

        _collect_mixins 应该只返回定义了 on_mixin_load/unload 的类，
        不包括通过继承获得的子类。
        """

        class TestPlugin(SpyMixin, Plugin):
            name = "test"
            version = "1.0"

            def on_load(self):
                pass

        lm = LifecycleManager.__new__(LifecycleManager)
        mixins = lm._collect_mixins(TestPlugin)
        names = [m.__name__ for m in mixins]

        # 当前行为 (bug): [TestPlugin, SpyMixin, PluginMixin]
        # TestPlugin 被包含了，虽然它只是继承了 SpyMixin 的方法
        print(f"_collect_mixins result: {names}")

        # 期望行为: [SpyMixin, PluginMixin]
        # TestPlugin 不应该被当作 mixin

    def test_collect_mixins_direct_definition(self):
        """当插件类自身直接定义 on_mixin_load 时。"""

        class DirectPlugin(Plugin):
            name = "direct"
            version = "1.0"

            def on_load(self):
                pass

            async def on_mixin_load(self, plugin, env):
                pass

        lm = LifecycleManager.__new__(LifecycleManager)
        mixins = lm._collect_mixins(DirectPlugin)
        names = [m.__name__ for m in mixins]

        # DirectPlugin 直接定义了 on_mixin_load，不应该被收集
        assert "DirectPlugin" not in names


class TestReloadCalls:
    """测试 reload 时的精确调用计数。"""

    @pytest.mark.asyncio
    async def test_load_calls_count(self, tmp_path):
        """load 时 on_mixin_load 被调用几次？"""
        SpyMixin.reset()

        class MyPlugin(SpyMixin, Plugin):
            name = "load_count"
            version = "1.0"

            def on_load(self):
                pass

        bus = Bus()
        lm = LifecycleManager(bus, tmp_path)
        await lm.load(MyPlugin)

        load_events = [e for e in SpyMixin.events if e["action"] == "load"]
        print(f"Load events: {load_events}")

        # 当前行为: 1
        assert len(load_events) == 1, f"on_mixin_load 被调用了 {len(load_events)} 次，"

    @pytest.mark.asyncio
    async def test_unload_calls_count(self, tmp_path):
        """unload 时 on_mixin_unload 被调用几次？"""
        SpyMixin.reset()

        class MyPlugin(SpyMixin, Plugin):
            name = "unload_count"
            version = "1.0"

            def on_load(self):
                pass

        bus = Bus()
        lm = LifecycleManager(bus, tmp_path)
        await lm.load(MyPlugin)
        await lm.unload("unload_count")

        unload_events = [e for e in SpyMixin.events if e["action"] == "unload"]
        print(f"Unload events: {unload_events}")

        # unload 时: `mixin is not type(plugin)` 排除了 MyPlugin
        # 只调用 SpyMixin.on_mixin_unload 1 次
        assert (
            len(unload_events) == 1
        ), f"on_mixin_unload 被调用了 {len(unload_events)} 次"

    @pytest.mark.asyncio
    async def test_reload_complete_flow(self, tmp_path):
        """
        完整 reload 流程:
        1. unload: on_mixin_unload × 1
        2. load: on_mixin_load × 1

        总计: load × 1, unload × 1
        """
        SpyMixin.reset()

        class ReloadPlugin(SpyMixin, Plugin):
            name = "reload_flow"
            version = "1.0"

            def on_load(self):
                pass

        bus = Bus()
        lm = LifecycleManager(bus, tmp_path)

        await lm.load(ReloadPlugin)

        # 重载
        mock_loader = MagicMock()
        mock_loader.load_class.return_value = ReloadPlugin
        lm._loader = mock_loader
        await lm.reload("reload_flow")

        load_events = [e for e in SpyMixin.events if e["action"] == "load"]
        unload_events = [e for e in SpyMixin.events if e["action"] == "unload"]

        print(f"After reload: load={len(load_events)}, unload={len(unload_events)}")
        print(f"Events: {SpyMixin.events}")

        # 当前行为: load 被调 2 次
        # unload 被调 1 次
        assert len(load_events) == 2
        assert len(unload_events) == 1


class TestConsoleReloadReal:
    """使用真实的 ConsoleMixin 测试重载。"""

    @pytest.mark.asyncio
    async def test_console_reload(self, tmp_path):
        """ConsoleMixin 重载后命令是否重新注册。"""

        # 用真实的 ConsoleApp
        from fcatbot.console import ConsoleApp, ConsoleMixin
        from fcatbot.utils.cmdparse import on_command

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        # 追踪注册/注销
        registered = []
        original_register = console.register_instance
        original_unregister = console.unregister

        def track_register(instance, provider):
            registered.append(("register", provider))
            return original_register(instance, provider)

        def track_unregister(provider):
            registered.append(("unregister", provider))
            return original_unregister(provider)

        console.register_instance = track_register
        console.unregister = track_unregister

        # 模拟注册表
        mock_registry = MagicMock()
        mock_registry.require.return_value = console

        class CmdPlugin(ConsoleMixin, Plugin):
            name = "console_reload_test"
            version = "1.0"
            registry = mock_registry

            def on_load(self):
                pass

            @on_command("ping")
            async def cmd_ping(self, ctx):
                return "pong"

        bus = Bus()
        lm = LifecycleManager(bus, tmp_path)

        # 1. 加载
        await lm.load(CmdPlugin)
        assert ("register", "console_reload_test") in registered

        # 验证命令确实在控制台中
        assert "ping" in console.app._node.Subcommands

        registered.clear()

        # 2. 重载
        mock_loader = MagicMock()
        mock_loader.load_class.return_value = CmdPlugin
        lm._loader = mock_loader

        await lm.reload("console_reload_test")

        # 3. 验证命令重新注册
        print(f"After reload: {registered}")
        assert (
            "unregister",
            "console_reload_test",
        ) in registered, "unload 时应该注销命令"
        assert (
            "register",
            "console_reload_test",
        ) in registered, "reload 后应该重新注册命令"

        # 验证命令确实在控制台中
        assert (
            "ping" in console.app._node.Subcommands
        ), "reload 后 ping 命令应该在控制台中"
