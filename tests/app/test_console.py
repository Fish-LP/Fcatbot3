"""Application tests for ConsoleApp and ConsoleMixin.

Tests how the application layer manages console commands from plugins.
"""

from unittest.mock import MagicMock

import pytest

from fcatbot.utils.cmdparse import CommandApp, on_command

# ---------- ConsoleApp Tests ----------


class TestConsoleApp:
    """Test console command registration and management."""

    def test_console_init(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        assert console.bot is mock_bot
        assert isinstance(console.app, CommandApp)
        assert "help" in console.app._node.Subcommands

    def test_register_instance(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        # Create a mock instance with a command
        class PluginInstance:
            @on_command("hello")
            async def cmd_hello(self, ctx):
                return "Hello!"

        instance = PluginInstance()
        console.register_instance(instance, provider="test_plugin")

        assert "test_plugin" in console._registered
        assert "hello" in console._registered["test_plugin"]

    def test_register_instance_no_commands(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        class EmptyPlugin:
            pass

        instance = EmptyPlugin()
        # Should not raise, should not register anything
        console.register_instance(instance, provider="empty")
        assert "empty" not in console._registered

    def test_register_duplicate_provider(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        class PluginA:
            @on_command("cmd1")
            async def cmd1(self, ctx):
                return "cmd1"

        instance = PluginA()
        console.register_instance(instance, provider="dup")
        # Second register should be skipped
        console.register_instance(instance, provider="dup")
        assert len(console._registered["dup"]) == 1

    def test_unregister(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        class PluginB:
            @on_command("goodbye")
            async def cmd_goodbye(self, ctx):
                return "Goodbye!"

        instance = PluginB()
        console.register_instance(instance, provider="test")
        assert "goodbye" in console.app._node.Subcommands

        console.unregister("test")
        assert "goodbye" not in console.app._node.Subcommands
        assert "test" not in console._registered

    def test_unregister_nonexistent(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        # Should not raise
        console.unregister("nonexistent")

    def test_builtin_help_command(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        assert "help" in console.app._node.Subcommands

    def test_builtin_stop_command(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        assert "stop" in console.app._node.Subcommands
        # Also check aliases
        node = console.app._node.Subcommands["stop"]
        assert "exit" in node.Aliases
        assert "bye" in node.Aliases

    def test_builtin_status_command(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        assert "status" in console.app._node.Subcommands

    def test_registered_dict(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        assert isinstance(console._registered, dict)


# ---------- ConsoleMixin Tests ----------


class TestConsoleMixin:
    """Test ConsoleMixin plugin integration."""

    @pytest.mark.asyncio
    async def test_mixin_load_registers_commands(self):
        from fcatbot.console import ConsoleApp, ConsoleMixin

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        class TestPlugin(ConsoleMixin):
            name = "test"
            registry = MagicMock()

            @on_command("greet")
            async def cmd_greet(self, ctx):
                return "Hi!"

        plugin = TestPlugin()
        plugin.registry.require.return_value = console

        await plugin.on_mixin_load(plugin, None)
        assert "greet" in console.app._node.Subcommands

    @pytest.mark.asyncio
    async def test_mixin_load_no_console(self):
        from fcatbot.console import ConsoleMixin

        class TestPlugin(ConsoleMixin):
            name = "test"
            registry = MagicMock()

        plugin = TestPlugin()
        plugin.registry.require.side_effect = Exception("no console")

        # Should not raise
        await plugin.on_mixin_load(plugin, None)

    @pytest.mark.asyncio
    async def test_mixin_unload_removes_commands(self):
        from fcatbot.console import ConsoleApp, ConsoleMixin

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        class TestPlugin(ConsoleMixin):
            name = "unload_test"
            registry = MagicMock()

            @on_command("temp")
            async def cmd_temp(self, ctx):
                return "temp"

        plugin = TestPlugin()
        plugin.registry.require.return_value = console

        await plugin.on_mixin_load(plugin, None)
        assert "temp" in console.app._node.Subcommands

        await plugin.on_mixin_unload(plugin, None)
        assert "temp" not in console.app._node.Subcommands

    @pytest.mark.asyncio
    async def test_mixin_unload_no_console(self):
        from fcatbot.console import ConsoleMixin

        class TestPlugin(ConsoleMixin):
            name = "test"
            registry = MagicMock()

        plugin = TestPlugin()
        plugin.registry.require.side_effect = Exception("no console")

        # Should not raise
        await plugin.on_mixin_unload(plugin, None)


# ---------- Command Conflict Tests ----------


class TestCommandConflicts:
    """Test command name conflict handling."""

    def test_conflict_same_name_different_plugins(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        class PluginA:
            @on_command("shared")
            async def cmd(self, ctx):
                return "A"

        class PluginB:
            @on_command("shared")
            async def cmd(self, ctx):
                return "B"

        console.register_instance(PluginA(), provider="pA")
        console.register_instance(PluginB(), provider="pB")

        # Only first should be registered
        names = console._registered.get("pB", [])
        assert "shared" not in names

    def test_unique_commands(self):
        from fcatbot.console import ConsoleApp

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)

        class PluginA:
            @on_command("cmd_a")
            async def cmd_a(self, ctx):
                return "A"

        class PluginB:
            @on_command("cmd_b")
            async def cmd_b(self, ctx):
                return "B"

        console.register_instance(PluginA(), provider="pA")
        console.register_instance(PluginB(), provider="pB")

        assert "cmd_a" in console.app._node.Subcommands
        assert "cmd_b" in console.app._node.Subcommands


# ---------- PromptToolkitConsole (mocked) ----------


class TestPromptToolkitConsole:
    """Test PromptToolkitConsole initialization."""

    def test_init(self):
        from fcatbot.console import ConsoleApp, PromptToolkitConsole

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        pt = PromptToolkitConsole(mock_bot, console)
        assert pt.bot is mock_bot
        assert pt.console is console
        assert pt._task is None
        assert not pt._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_stop(self):
        from fcatbot.console import ConsoleApp, PromptToolkitConsole

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        pt = PromptToolkitConsole(mock_bot, console)
        await pt.stop()
        assert pt._stop_event.is_set()

    def test_attach_console(self):
        from fcatbot.console import ConsoleApp, attach_console

        mock_bot = MagicMock()
        console = ConsoleApp(mock_bot)
        pt = attach_console(mock_bot, console)
        assert isinstance(pt, type(pt))  # Just verify it returns something
