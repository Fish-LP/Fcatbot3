#!/usr/bin/env python3
"""
WebSocket Client 异步测试套件（同步测试已注释，避免耗时）
运行方式:
    pytest tests/test_ws_client.py -v
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

from fcatbot.connection.websocket import (
    AioHttpWebSocketConnection,
    AsyncWebSocketClient,
    ListenerClosedError,
    ListenerEvictedError,
    MessageType,
    ReconnectionStrategy,
    SyncWebSocketClient,
    WebSocketConfig,
    WebSocketListener,
    WebSocketState,
    WSConnectionError,
)


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("pytest")


@pytest.fixture
def mock_ws() -> AsyncMock:
    ws = AsyncMock(spec=ClientWebSocketResponse)
    ws.closed = False
    ws.close = AsyncMock()
    ws.send_str = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws


@pytest.fixture
def mock_session(mock_ws: AsyncMock) -> AsyncMock:
    session = AsyncMock(spec=ClientSession)
    session.ws_connect = AsyncMock(return_value=mock_ws)
    session.close = AsyncMock()
    return session


# -----------------------------------------------------------------------------
# WebSocketConfig
# -----------------------------------------------------------------------------


def test_config_defaults():
    cfg = WebSocketConfig(uri="wss://example.com/ws")
    assert cfg.uri == "wss://example.com/ws"
    assert cfg.heartbeat == 30.0
    assert cfg.reconnect_attempts == 5
    assert cfg.compression == 0
    assert cfg.backoff_max == 60.0


def test_config_invalid_uri():
    with pytest.raises(ValueError, match="URI 必须以 ws:// 或 wss:// 开头"):
        WebSocketConfig(uri="http://example.com")


def test_config_negative_heartbeat():
    with pytest.raises(ValueError, match="心跳值不能为负数"):
        WebSocketConfig(uri="ws://localhost", heartbeat=-1)


def test_config_compression_out_of_range():
    with pytest.raises(ValueError, match="压缩级别必须在 0 到 9 之间"):
        WebSocketConfig(uri="ws://localhost", compression=15)


# -----------------------------------------------------------------------------
# WebSocketListener
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_put_and_get():
    listener = WebSocketListener(buffer_size=3)
    assert await listener.put("msg1", MessageType.Text) is True

    msg, typ = await listener.get(timeout=1)
    assert msg == "msg1"
    assert typ == MessageType.Text


@pytest.mark.asyncio
async def test_listener_queue_overflow_discards_oldest():
    listener = WebSocketListener(buffer_size=2)
    await listener.put("old", MessageType.Text)
    await listener.put("mid", MessageType.Text)
    await listener.put("new", MessageType.Text)  # "old" 被丢弃

    msg, _ = await listener.get(timeout=1)
    assert msg == "mid"
    msg, _ = await listener.get(timeout=1)
    assert msg == "new"


@pytest.mark.asyncio
async def test_listener_get_nowait():
    listener = WebSocketListener()
    assert await listener.get_nowait() is None

    await listener.put("x", MessageType.Binary)
    msg, typ = await listener.get_nowait()
    assert msg == "x"
    assert typ == MessageType.Binary


@pytest.mark.asyncio
async def test_listener_close_wakes_blocked_consumer():
    listener = WebSocketListener()

    async def consumer():
        with pytest.raises(ListenerClosedError):
            await listener.get(timeout=5)

    async def closer():
        await asyncio.sleep(0.05)
        listener.close()

    await asyncio.gather(consumer(), closer())


@pytest.mark.asyncio
async def test_listener_async_iteration():
    """先正常消费消息，再 close() 验证迭代立即结束"""
    listener = WebSocketListener()
    await listener.put("a", MessageType.Text)
    await listener.put("b", MessageType.Text)

    items = []
    async for item in listener:
        items.append(item)
        if len(items) >= 2:
            break

    assert len(items) == 2
    assert items[0] == ("a", MessageType.Text)
    assert items[1] == ("b", MessageType.Text)

    # 关闭后再迭代应立即结束（不会取到任何消息）
    listener.close()
    post_close = []
    async for item in listener:
        post_close.append(item)
    assert len(post_close) == 0


@pytest.mark.asyncio
async def test_listener_get_raises_after_close():
    listener = WebSocketListener()
    listener.close()

    with pytest.raises(ListenerClosedError):
        await listener.get(timeout=1)

    with pytest.raises(ListenerClosedError):
        await listener.get_nowait()


# -----------------------------------------------------------------------------
# ReconnectionStrategy
# -----------------------------------------------------------------------------


def test_reconnect_delay_exponential():
    cfg = WebSocketConfig(
        uri="ws://localhost", backoff_base=1.0, backoff_max=10.0, jitter_factor=0
    )
    strat = ReconnectionStrategy(cfg)

    strat.on_attempt()
    assert strat.get_delay() == 1.0
    strat.on_attempt()
    assert strat.get_delay() == 2.0
    strat.on_attempt()
    assert strat.get_delay() == 4.0
    strat.on_attempt()
    strat.on_attempt()
    assert strat.get_delay() == 10.0  # 被 max 截断


def test_reconnect_infinite_attempts():
    cfg = WebSocketConfig(uri="ws://localhost", reconnect_attempts=0)
    strat = ReconnectionStrategy(cfg)

    for _ in range(100):
        assert strat.should_reconnect() is True
        strat.on_attempt()


def test_reconnect_resets_on_success():
    cfg = WebSocketConfig(uri="ws://localhost", reconnect_attempts=3)
    strat = ReconnectionStrategy(cfg)

    strat.on_attempt()
    strat.on_attempt()
    assert strat.attempt_count == 2

    strat.on_success()
    assert strat.attempt_count == 0
    assert strat.should_reconnect() is True


# -----------------------------------------------------------------------------
# AioHttpWebSocketConnection
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_connect_success(
    mock_session: AsyncMock, mock_ws: AsyncMock, logger: logging.Logger
):
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        cfg = WebSocketConfig(uri="ws://localhost")
        conn = AioHttpWebSocketConnection(cfg, logger)

        await conn.connect()
        assert conn.state == WebSocketState.Connected
        assert conn.metrics["connection_attempts"] == 1
        assert conn.metrics["successful_connections"] == 1
        mock_session.ws_connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_connection_connect_failure(
    mock_session: AsyncMock, logger: logging.Logger
):
    mock_session.ws_connect = AsyncMock(side_effect=OSError("Connection refused"))

    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        cfg = WebSocketConfig(uri="ws://localhost")
        conn = AioHttpWebSocketConnection(cfg, logger)

        with pytest.raises(WSConnectionError, match="连接失败"):
            await conn.connect()

        assert conn.state == WebSocketState.Disconnected
        assert conn.metrics["failed_connections"] == 1


@pytest.mark.asyncio
async def test_connection_send_str(
    mock_session: AsyncMock, mock_ws: AsyncMock, logger: logging.Logger
):
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        cfg = WebSocketConfig(uri="ws://localhost")
        conn = AioHttpWebSocketConnection(cfg, logger)
        await conn.connect()

        await conn.send("hello")
        mock_ws.send_str.assert_awaited_once_with("hello")
        assert conn.metrics["messages_sent"] == 1
        assert conn.metrics["bytes_sent"] == 5


@pytest.mark.asyncio
async def test_connection_send_dict(
    mock_session: AsyncMock, mock_ws: AsyncMock, logger: logging.Logger
):
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        cfg = WebSocketConfig(uri="ws://localhost")
        conn = AioHttpWebSocketConnection(cfg, logger)
        await conn.connect()

        await conn.send({"key": "value"})
        mock_ws.send_str.assert_awaited_once()
        call_arg = mock_ws.send_str.call_args[0][0]
        assert '"key": "value"' in call_arg


@pytest.mark.asyncio
async def test_connection_receive_text(
    mock_session: AsyncMock, mock_ws: AsyncMock, logger: logging.Logger
):
    fake_msg = MagicMock()
    fake_msg.type = WSMsgType.TEXT
    fake_msg.data = "hello"
    mock_ws.receive = AsyncMock(return_value=fake_msg)

    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        cfg = WebSocketConfig(uri="ws://localhost")
        conn = AioHttpWebSocketConnection(cfg, logger)
        await conn.connect()

        data, typ = await conn.receive()
        assert data == "hello"
        assert typ == MessageType.Text
        assert conn.metrics["messages_received"] == 1
        assert conn.metrics["bytes_received"] == 5


@pytest.mark.asyncio
async def test_connection_close(
    mock_session: AsyncMock, mock_ws: AsyncMock, logger: logging.Logger
):
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        cfg = WebSocketConfig(uri="ws://localhost")
        conn = AioHttpWebSocketConnection(cfg, logger)
        await conn.connect()

        await conn.close()
        assert conn.state == WebSocketState.Closed
        mock_ws.close.assert_awaited_once()
        mock_session.close.assert_awaited_once()


# -----------------------------------------------------------------------------
# AsyncWebSocketClient
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_client_listener_management():
    client = AsyncWebSocketClient("ws://localhost", max_listeners=3)

    lid1 = await client.create_listener()
    lid2 = await client.create_listener(buffer_size=50)
    assert lid1 != lid2
    assert lid1 in client._listeners
    assert client._listeners[lid2].queue.maxsize == 50

    await client.remove_listener(lid1)
    assert lid1 not in client._listeners

    # 重复移除不应抛异常
    await client.remove_listener(lid1)


@pytest.mark.asyncio
async def test_async_client_listener_eviction():
    client = AsyncWebSocketClient("ws://localhost", max_listeners=2)
    lid1 = await client.create_listener()
    await asyncio.sleep(0.01)
    lid2 = await client.create_listener()
    await asyncio.sleep(0.01)
    lid3 = await client.create_listener()

    assert lid1 not in client._listeners
    assert lid2 in client._listeners
    assert lid3 in client._listeners


@pytest.mark.asyncio
async def test_async_client_broadcast():
    client = AsyncWebSocketClient("ws://localhost")
    lid1 = await client.create_listener()
    lid2 = await client.create_listener()

    await client._broadcast_message("broadcast", MessageType.Text)

    r1 = await client.get_message_nowait(lid1)
    r2 = await client.get_message_nowait(lid2)
    assert r1 == ("broadcast", MessageType.Text)
    assert r2 == ("broadcast", MessageType.Text)


@pytest.mark.asyncio
async def test_async_client_get_message_not_found():
    client = AsyncWebSocketClient("ws://localhost")
    with pytest.raises(ListenerEvictedError, match="未找到"):
        await client.get_message("non-existent-id")


@pytest.mark.asyncio
async def test_async_client_send_not_running():
    client = AsyncWebSocketClient("ws://localhost")
    with pytest.raises(WSConnectionError, match="客户端未运行"):
        await client.send("hello")


@pytest.mark.asyncio
async def test_async_client_send_queue_full():
    client = AsyncWebSocketClient("ws://localhost", send_queue_size=1)
    client._running = True
    client._send_queue.put_nowait("block")

    with pytest.raises(Exception, match="发送队列已满"):
        await client.send("overflow")


@pytest.mark.asyncio
async def test_async_client_metrics():
    client = AsyncWebSocketClient("ws://localhost", max_listeners=5)
    await client.create_listener()
    await client.create_listener()

    # 注意：若源码中 get_metrics 为普通方法，去掉下面的 await
    metrics = await client.get_metrics()
    assert metrics["listeners"]["active"] == 2
    assert metrics["listeners"]["max"] == 5
    assert metrics["running"] is False


@pytest.mark.asyncio
async def test_async_client_remove_listener_wakes_consumer():
    client = AsyncWebSocketClient("ws://localhost")
    lid = await client.create_listener()

    async def getter():
        with pytest.raises((ListenerClosedError, ListenerEvictedError)):
            await client.get_message(lid, timeout=2)

    async def remover():
        await asyncio.sleep(0.05)
        await client.remove_listener(lid)

    await asyncio.gather(getter(), remover())


@pytest.mark.asyncio
async def test_async_client_context_manager():
    client = AsyncWebSocketClient("ws://localhost")
    entered = await client.__aenter__()
    assert entered is client
    assert client._running is True

    await client.__aexit__(None, None, None)
    assert client._running is False


# =============================================================================
# 同步测试
# =============================================================================


def test_sync_client_start_stop(mock_session: AsyncMock, mock_ws: AsyncMock):
    async def slow_receive(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(type=WSMsgType.TEXT, data="never")

    mock_ws.receive = AsyncMock(side_effect=slow_receive)
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        client = SyncWebSocketClient("ws://localhost", reconnect_attempts=1)
        client.start()
        assert client._running is True
        client.create_listener()
        client.send("test")
        metrics = client.get_metrics()
        assert metrics["running"] is True
        client.stop()
        assert client._running is False


def test_sync_client_idempotent_start_stop(mock_session: AsyncMock, mock_ws: AsyncMock):
    async def slow_receive(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(type=WSMsgType.TEXT, data="never")

    mock_ws.receive = AsyncMock(side_effect=slow_receive)
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        client = SyncWebSocketClient("ws://localhost", reconnect_attempts=1)
        client.start()
        client.start()
        client.stop()
        client.stop()
        assert client._running is False


def test_sync_client_get_message(mock_session: AsyncMock, mock_ws: AsyncMock):
    async def controlled_receive(*args, **kwargs):
        await asyncio.sleep(0.1)
        return MagicMock(type=WSMsgType.TEXT, data="sync_hello")

    mock_ws.receive = AsyncMock(side_effect=controlled_receive)
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        client = SyncWebSocketClient("ws://localhost", reconnect_attempts=1)
        client.start()
        lid = client.create_listener()
        msg, typ = client.get_message(lid, timeout=5)
        assert msg == "sync_hello"
        assert typ == MessageType.Text
        client.stop()


def test_sync_client_get_message_nowait(mock_session: AsyncMock, mock_ws: AsyncMock):
    async def slow_receive(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(type=WSMsgType.TEXT, data="never")

    mock_ws.receive = AsyncMock(side_effect=slow_receive)
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        client = SyncWebSocketClient("ws://localhost", reconnect_attempts=1)
        client.start()
        lid = client.create_listener()
        assert client.get_message_nowait(lid) is None
        client.stop()


def test_sync_client_context_manager(mock_session: AsyncMock, mock_ws: AsyncMock):
    async def slow_receive(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(type=WSMsgType.TEXT, data="never")

    mock_ws.receive = AsyncMock(side_effect=slow_receive)
    with patch("fcatbot.connection.websocket.ClientSession", return_value=mock_session):
        with SyncWebSocketClient("ws://localhost", reconnect_attempts=1) as client:
            assert client._running is True
        assert client._running is False
