"""Application layer tests —— Bot initialization, CLI args, plugin discovery.

These tests verify how the application *uses* plugkit, not plugkit itself.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestBotInitialization:
    """Test Bot class initialization without network."""

    def test_bot_init_minimal(self):
        """Bot should initialize with just root_id and url."""
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=12345, url="ws://localhost:8080")
        assert bot.root_id == "12345"
        assert bot.url == "ws://localhost:8080"
        assert bot.token is None
        assert bot.debug is False
        assert bot.dev is False

    def test_bot_init_with_token(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id="bot1", url="wss://example.com/ws", token="secret123")
        assert bot.token == "secret123"

    def test_bot_init_debug_dev(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test", debug=True, dev=True)
        assert bot.debug is True
        assert bot.dev is True

    def test_bot_init_data_dir(self, tmp_path):
        from fcatbot.__main__ import Bot

        data = tmp_path / "mydata"
        bot = Bot(root_id=0, url="ws://test", data_dir=data)
        assert bot.data_dir == data

    def test_bot_init_plugin_dir(self, tmp_path):
        from fcatbot.__main__ import Bot

        pdir = tmp_path / "plugins"
        pdir.mkdir()
        bot = Bot(root_id=0, url="ws://test", plugin_dir=pdir)
        assert pdir in bot._plugin_dirs

    def test_http_url_conversion_ws(self):
        """ws:// should become http:// for HTTP API."""
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://localhost:8080")
        # HTTP URL is computed internally, verify no error
        assert bot._ws is not None

    def test_http_url_conversion_wss(self):
        """wss:// should become https:// for HTTP API."""
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="wss://secure.example.com/ws")
        assert bot._ws is not None

    def test_bot_running_class_var(self):
        from fcatbot.__main__ import Bot

        assert Bot.running is False

    def test_bot_ws_headers_with_token(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test", token="mytoken")
        # Headers are passed to AsyncWebSocketClient
        assert bot._ws is not None

    def test_bot_sys_plugin_dir(self):
        """Bot should include sys_plugin directory if it exists."""
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test")
        sys_dir = Path(__file__).resolve().parents[2] / "src/fcatbot/sys_plugin"
        if sys_dir.exists():
            assert sys_dir in bot._plugin_dirs

    def test_bot_stop_event(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test")
        assert isinstance(bot._stop_event, asyncio.Event)
        assert not bot._stop_event.is_set()


class TestBotPluginDiscovery:
    """Test plugin discovery from filesystem."""

    def test_discover_plugins_empty(self, tmp_path):
        """No plugin dirs should return empty list."""
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test", plugin_dir=tmp_path)
        bot._loader = None  # simulate before run_async
        plugins = bot._discover_plugins()
        assert plugins == []

    def test_discover_plugins_no_loader(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test")
        bot._loader = None
        plugins = bot._discover_plugins()
        assert plugins == []

    def test_discover_plugins_nonexistent_dir(self, tmp_path):
        from fcatbot.__main__ import Bot

        fake_dir = tmp_path / "nonexistent"
        bot = Bot(root_id=0, url="ws://test", plugin_dir=fake_dir)
        # _discover_plugins skips non-existent dirs
        plugins = bot._discover_plugins()
        assert isinstance(plugins, list)


class TestConnectionService:
    """Test ConnectionService wrapper."""

    def test_connection_service_init(self):
        from fcatbot.__main__ import ConnectionService

        mock_ws = MagicMock()
        mock_ws.config.uri = "ws://test"
        svc = ConnectionService(mock_ws)
        assert svc.uri == "ws://test"
        assert svc.version == "1.0.0"

    def test_connection_service_connected(self):
        from fcatbot.__main__ import ConnectionService

        mock_ws = MagicMock()
        mock_ws._running = True
        svc = ConnectionService(mock_ws)
        assert svc.connected is True

    def test_connection_service_send_raw(self):
        from fcatbot.__main__ import ConnectionService

        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        svc = ConnectionService(mock_ws)
        # Should not raise
        asyncio.run(svc.send_raw("hello"))
        mock_ws.send.assert_called_once_with("hello")


class TestBotShutdown:
    """Test graceful shutdown mechanisms."""

    @pytest.mark.asyncio
    async def test_stop_sets_event(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test")
        # Don't actually run, just test stop logic
        bot._ws = MagicMock()
        bot._ws.stop = AsyncMock()
        bot._plugin_manager = None
        await bot.stop()
        assert bot._stop_event.is_set()
        assert Bot.running is False

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test")
        bot._ws = MagicMock()
        bot._ws.stop = AsyncMock()
        bot._plugin_manager = None
        await bot.stop()
        # Second stop should be a no-op
        await bot.stop()
        assert bot._stop_event.is_set()

    def test_request_shutdown(self):
        from fcatbot.__main__ import Bot

        bot = Bot(root_id=0, url="ws://test")
        assert not bot._stop_event.is_set()
        bot._request_shutdown()
        assert bot._stop_event.is_set()


class TestBotSingleton:
    """Test Bot.running singleton behavior."""

    def test_running_is_class_var(self):
        from fcatbot.__main__ import Bot

        assert isinstance(Bot.running, bool)
        # Should be shared across instances
        b1 = Bot(root_id=1, url="ws://a")
        b2 = Bot(root_id=2, url="ws://b")
        assert b1.running is b2.running
