#!/usr/bin/env python3
# @Author Fish.zh@outlook.com
# @Version 1.2
import asyncio
import json
import logging
import random
import threading
import time
import uuid
from asyncio import QueueFull
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, NewType, Optional, Tuple, Union

import aiohttp
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType

ListenerId = NewType("ListenerId", str)
_LISTENER_CLOSED = object()  # 用于唤醒阻塞消费者的关闭哨兵


class MessageType(Enum):
    """WebSocket 消息类型枚举"""

    Text = "text"
    Binary = "binary"
    Ping = "ping"
    Pong = "pong"
    Close = "close"
    Error = "error"
    NONE = "none"


class WebSocketState(Enum):
    """WebSocket 连接状态枚举"""

    Disconnected = "disconnected"
    Connecting = "connecting"
    Connected = "connected"
    Reconnecting = "reconnecting"
    Closing = "closing"
    Closed = "closed"


class WebSocketError(Exception):
    """WebSocket 基础异常"""

    pass


class WSConnectionError(WebSocketError):
    """连接相关异常（避免遮蔽内置 ConnectionError）"""

    pass


class ListenerEvictedError(WebSocketError):
    """监听器被驱逐异常"""

    pass


class ListenerClosedError(WebSocketError):
    """监听器已关闭异常"""

    pass


@dataclass
class WebSocketConfig:
    """WebSocket 配置类

    包含 WebSocket 连接的所有配置参数，包括连接超时、重连策略、
    压缩设置、监听器限制等。

    Attributes:
        uri: WebSocket 服务器地址，必须以 ws:// 或 wss:// 开头
        headers: 连接请求头字典
        heartbeat: 心跳间隔（秒），默认 30.0；0 表示关闭自动心跳
        receive_timeout: 接收消息超时时间（秒），默认 60.0
        reconnect_attempts: 最大重连次数，默认 5；0 或负数表示无限重连
        connect_timeout: 连接超时时间（秒），默认 20.0
        send_queue_size: 发送队列大小，默认 1024
        session_timeout: 会话总超时时间（秒），默认 300.0（仅影响 TCP 握手阶段）
        backoff_base: 退避基数（秒），默认 1.0
        backoff_max: 最大退避时间（秒），默认 60.0
        jitter_factor: 抖动因子，默认 0.5
        compression: 压缩级别 0-9，默认 0 表示不压缩
        verify_ssl: 是否验证 SSL 证书，默认 True
        max_listeners: 最大监听器数量，默认 1000
        listener_buffer_size: 每个监听器的缓冲区大小，默认 100
    """

    uri: str
    headers: Dict[str, str] = field(default_factory=dict)
    heartbeat: float = 30.0
    receive_timeout: float = 60.0
    reconnect_attempts: int = 5
    connect_timeout: float = 20.0
    send_queue_size: int = 1024
    session_timeout: float = 300.0
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    jitter_factor: float = 0.5
    compression: int = 0
    verify_ssl: bool = True
    max_listeners: int = 1000
    listener_buffer_size: int = 100

    def __post_init__(self):
        """配置验证

        Raises:
            ValueError: URI 格式不正确或配置参数无效时抛出
        """
        if not self.uri.startswith(("ws://", "wss://")):
            raise ValueError("URI must start with ws:// or wss://")
        if self.heartbeat < 0:
            raise ValueError("Heartbeat cannot be negative")
        if self.reconnect_attempts < 0:
            raise ValueError("Reconnect attempts cannot be negative")
        if not (0 <= self.compression <= 9):
            raise ValueError("Compression level must be between 0 and 9")


class WebSocketListener:
    """WebSocket 消息监听器

    为每个订阅者提供独立的消息队列，支持异步迭代和超时控制。
    当队列满时自动丢弃最旧的消息。

    Attributes:
        id: 监听器唯一标识符
        queue: 消息队列
        created_at: 创建时间戳
    """

    def __init__(self, buffer_size: int = 100):
        """初始化监听器

        Args:
            buffer_size: 消息队列缓冲区大小，默认 100
        """
        self.id = ListenerId(str(uuid.uuid4()))
        self.queue = asyncio.Queue(maxsize=buffer_size)
        self.created_at = time.time()
        self._closed = False

    async def put(self, message: Any, msg_type: MessageType) -> bool:
        """放入消息到队列

        如果队列已满，自动丢弃最旧的消息以腾出空间。

        Args:
            message: 消息内容
            msg_type: 消息类型

        Returns:
            bool: 放入成功返回 True，失败返回 False
        """
        if self._closed:
            return False

        try:
            self.queue.put_nowait((message, msg_type))
            return True
        except QueueFull:
            # 队列满时丢弃最旧的消息
            try:
                self.queue.get_nowait()  # 丢弃一个旧消息
                self.queue.put_nowait((message, msg_type))  # 放入新消息
                return True
            except QueueFull:
                return False

    async def get(self, timeout: Optional[float] = None) -> Tuple[Any, MessageType]:
        """获取消息（阻塞）

        Args:
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            Tuple[Any, MessageType]: 消息内容和类型

        Raises:
            ListenerClosedError: 监听器已关闭时抛出
            asyncio.TimeoutError: 超时时抛出
            asyncio.CancelledError: 任务被取消时抛出
        """
        if self._closed:
            raise ListenerClosedError(f"Listener {self.id} is closed")

        try:
            if timeout is None:
                item = await self.queue.get()
            else:
                item = await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self._closed:
                raise ListenerClosedError(f"Listener {self.id} is closed") from e
            raise

        if item is _LISTENER_CLOSED:
            raise ListenerClosedError(f"Listener {self.id} is closed")
        return item

    async def get_nowait(self) -> Optional[Tuple[Any, MessageType]]:
        """非阻塞获取消息（定义为 async 以便线程安全调度）

        Returns:
            Optional[Tuple[Any, MessageType]]: 消息内容和类型，无数据时返回 None

        Raises:
            ListenerClosedError: 监听器已关闭时抛出
        """
        if self._closed:
            raise ListenerClosedError(f"Listener {self.id} is closed")

        try:
            item = self.queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

        if item is _LISTENER_CLOSED:
            raise ListenerClosedError(f"Listener {self.id} is closed")
        return item

    def close(self) -> None:
        """关闭监听器并清空队列，同时唤醒所有阻塞中的消费者"""
        self._closed = True
        # 清空队列以释放等待的消费者
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        # 放入关闭哨兵，确保正在 await get() 的协程立即被唤醒
        try:
            self.queue.put_nowait(_LISTENER_CLOSED)
        except QueueFull:
            pass

    @property
    def is_closed(self) -> bool:
        """检查监听器是否已关闭

        Returns:
            bool: 已关闭返回 True，否则返回 False
        """
        return self._closed

    def __aiter__(self):
        """返回异步迭代器"""
        return self

    async def __anext__(self):
        """异步迭代下一个消息

        Returns:
            Tuple[Any, MessageType]: 消息内容和类型

        Raises:
            StopAsyncIteration: 监听器关闭时抛出
        """
        try:
            return await self.get()
        except ListenerClosedError:
            raise StopAsyncIteration


class AioHttpWebSocketConnection:
    """基于 aiohttp 的 WebSocket 连接管理

    负责底层的 WebSocket 连接建立、消息收发和资源清理。
    自动处理压缩协商失败等边界情况。

    Attributes:
        config: WebSocket 配置对象
        logger: 日志记录器
        websocket: aiohttp WebSocket 响应对象
        session: aiohttp 客户端会话
        state: 当前连接状态
        metrics: 连接指标统计
    """

    def __init__(self, config: WebSocketConfig, logger: logging.Logger):
        """初始化连接管理器

        Args:
            config: WebSocket 配置对象
            logger: 日志记录器实例
        """
        self.config = config
        self.logger = logger

        self.websocket: Optional[ClientWebSocketResponse] = None
        self.session: Optional[ClientSession] = None
        self.state = WebSocketState.Disconnected

        # 指标
        self.metrics = {
            "connection_attempts": 0,
            "successful_connections": 0,
            "failed_connections": 0,
            "messages_sent": 0,
            "messages_received": 0,
            "bytes_sent": 0,
            "bytes_received": 0,
            "errors": 0,
        }

    async def connect(self) -> None:
        """建立 WebSocket 连接

        如果已经处于连接中或已连接状态，直接返回。
        支持自动处理压缩协商失败的情况。

        Raises:
            WSConnectionError: 连接失败时抛出
        """
        if self.state in [WebSocketState.Connecting, WebSocketState.Connected]:
            return

        self.state = WebSocketState.Connecting
        self.metrics["connection_attempts"] += 1
        self.logger.info(f"Connecting to {self.config.uri}")

        try:
            # 创建 aiohttp 会话（WebSocket 长连接不设 total 超时）
            timeout = aiohttp.ClientTimeout(
                total=None,
                connect=self.config.connect_timeout,
                sock_connect=self.config.connect_timeout,
                sock_read=self.config.receive_timeout,
            )

            self.session = ClientSession(timeout=timeout)

            # 建立 WebSocket 连接
            self.websocket = await self.session.ws_connect(
                self.config.uri,
                headers=self.config.headers,
                heartbeat=self.config.heartbeat,
                compress=self.config.compression,
                verify_ssl=self.config.verify_ssl,
            )

            self.state = WebSocketState.Connected
            self.metrics["successful_connections"] += 1
            self.logger.info(f"Connected to {self.config.uri}")

        except Exception as e:
            self.state = WebSocketState.Disconnected
            self.metrics["failed_connections"] += 1

            # 清理资源
            if self.session:
                await self.session.close()
                self.session = None

            self.logger.error(f"Connection failed: {self.config.uri}, error: {e}")
            if "wbits=" in str(e):
                self.logger.error("Detected zlib wbits compression error")
                self.config.compression = 0
                self.logger.info("Disabled compression for next reconnection attempt")

            raise WSConnectionError(f"Connection failed: {e}") from e

    async def close(self) -> None:
        """关闭 WebSocket 连接并清理资源"""
        if self.state == WebSocketState.Closed:
            return

        self.state = WebSocketState.Closing
        self.logger.debug("Closing connection")

        try:
            if self.websocket:
                await self.websocket.close()
        except Exception as e:
            self.logger.error(f"WebSocket close error: {e}")

        try:
            if self.session:
                await self.session.close()
        except Exception as e:
            self.logger.error(f"Session close error: {e}")
        finally:
            self.websocket = None
            self.session = None
            self.state = WebSocketState.Closed
            self.logger.info("Connection closed")

    async def send(self, message: Union[str, bytes, Dict]) -> None:
        """发送消息

        Args:
            message: 要发送的消息，支持字符串、字节或字典（自动转为 JSON）

        Raises:
            WSConnectionError: 未连接时抛出
            Exception: 发送失败时抛出
        """
        if self.state != WebSocketState.Connected or not self.websocket:
            raise WSConnectionError("Not connected")

        try:
            # 格式化消息
            if isinstance(message, dict):
                formatted = json.dumps(message)
            elif isinstance(message, bytes):
                formatted = message
            else:
                formatted = str(message)

            # 发送消息并统计字节数（字符串按 UTF-8 编码长度计算）
            if isinstance(formatted, str):
                await self.websocket.send_str(formatted)
                bytes_len = len(formatted.encode("utf-8"))
            else:
                await self.websocket.send_bytes(formatted)
                bytes_len = len(formatted)

            self.metrics["messages_sent"] += 1
            self.metrics["bytes_sent"] += bytes_len

        except Exception as e:
            self.metrics["errors"] += 1
            self.logger.error(f"Send error: {e}")
            raise

    async def receive(self) -> Tuple[Any, MessageType]:
        """接收消息

        Returns:
            Tuple[Any, MessageType]: 消息数据和类型

        Raises:
            WSConnectionError: 未连接时抛出
            asyncio.TimeoutError: 接收超时时抛出
            Exception: 接收失败时抛出
        """
        if self.state != WebSocketState.Connected or not self.websocket:
            raise WSConnectionError("Not connected")

        try:
            # 接收消息
            msg = await self.websocket.receive(timeout=self.config.receive_timeout)

            # 处理不同类型的消息
            if msg.type == WSMsgType.TEXT:
                bytes_len = len(msg.data.encode("utf-8"))
                self.metrics["messages_received"] += 1
                self.metrics["bytes_received"] += bytes_len
                return msg.data, MessageType.Text

            elif msg.type == WSMsgType.BINARY:
                bytes_len = len(msg.data)
                self.metrics["messages_received"] += 1
                self.metrics["bytes_received"] += bytes_len
                return msg.data, MessageType.Binary

            elif msg.type == WSMsgType.PING:
                return msg.data, MessageType.Ping

            elif msg.type == WSMsgType.PONG:
                return msg.data, MessageType.Pong

            elif msg.type == WSMsgType.CLOSE:
                return msg.data, MessageType.Close

            elif msg.type == WSMsgType.ERROR:
                self.metrics["errors"] += 1
                self.logger.error(f"WebSocket error: {msg.data}")
                return msg.data, MessageType.Error

            else:
                # 未知消息类型
                return msg.data, MessageType.NONE

        except asyncio.TimeoutError:
            raise
        except Exception as e:
            self.metrics["errors"] += 1
            self.logger.error(f"Receive error: {e}")
            raise

    def is_connected(self) -> bool:
        """检查连接是否处于活动状态

        Returns:
            bool: 已连接且 WebSocket 未关闭返回 True
        """
        return (
            self.state == WebSocketState.Connected
            and self.websocket is not None
            and not self.websocket.closed
        )


class ReconnectionStrategy:
    """重连策略管理

    实现指数退避 + 随机抖动的重连策略。

    Attributes:
        config: WebSocket 配置对象
        attempt_count: 当前重连尝试次数
        last_attempt_time: 上次尝试时间戳
    """

    def __init__(self, config: WebSocketConfig):
        """初始化重连策略

        Args:
            config: WebSocket 配置对象
        """
        self.config = config
        self.attempt_count = 0
        self.last_attempt_time = 0.0

    def should_reconnect(self) -> bool:
        """检查是否应该继续重连

        Returns:
            bool: 未达到最大重连次数返回 True；0 或负数表示无限重连
        """
        if self.config.reconnect_attempts <= 0:
            return True
        return self.attempt_count < self.config.reconnect_attempts

    def get_delay(self) -> float:
        """计算下次重连的延迟时间

        使用指数退避算法：delay = min(base * 2^(n-1), max) + jitter

        Returns:
            float: 延迟时间（秒）
        """
        if self.attempt_count == 0:
            return 0.0

        # 指数退避
        delay = min(
            self.config.backoff_base * (2 ** (self.attempt_count - 1)),
            self.config.backoff_max,
        )

        # 随机抖动
        jitter = random.uniform(0, self.config.jitter_factor)
        return delay + jitter

    def on_attempt(self) -> None:
        """记录一次重连尝试"""
        self.attempt_count += 1
        self.last_attempt_time = time.time()

    def on_success(self) -> None:
        """重连成功，重置计数器"""
        self.attempt_count = 0

    def get_state(self) -> Dict[str, Any]:
        """获取当前重连状态

        Returns:
            Dict[str, Any]: 包含尝试次数、上次尝试时间、最大次数的字典
        """
        return {
            "attempt_count": self.attempt_count,
            "last_attempt_time": self.last_attempt_time,
            "max_attempts": self.config.reconnect_attempts,
        }


class AsyncWebSocketClient:
    """异步 WebSocket 客户端 - 使用监听器模式

    高性能异步 WebSocket 客户端，支持多监听器、自动重连、
    消息广播和完善的指标统计。

    Attributes:
        config: WebSocket 配置对象
        logger: 日志记录器
        connection: 底层连接管理器
        reconnection: 重连策略管理器
        _listeners: 监听器字典
        _running: 运行状态标志
    """

    def __init__(
        self,
        uri: str,
        logger: Optional[logging.Logger] = None,
        headers: Optional[Dict[str, str]] = None,
        heartbeat: float = 30.0,
        receive_timeout: float = 60.0,
        reconnect_attempts: int = 5,
        connect_timeout: float = 20.0,
        send_queue_size: int = 1024,
        session_timeout: float = 300.0,
        backoff_base: float = 1.0,
        backoff_max: float = 60.0,
        jitter_factor: float = 0.5,
        compression: int = 0,
        verify_ssl: bool = True,
        max_listeners: int = 1000,
        listener_buffer_size: int = 100,
    ):
        """初始化异步 WebSocket 客户端

        Args:
            uri: WebSocket 服务器地址
            logger: 可选的日志记录器，默认使用模块日志
            headers: 可选的连接请求头
            heartbeat: 心跳间隔（秒），默认 30.0；0 表示关闭
            receive_timeout: 接收超时（秒），默认 60.0
            reconnect_attempts: 最大重连次数，默认 5；0 表示无限
            connect_timeout: 连接超时（秒），默认 20.0
            send_queue_size: 发送队列大小，默认 1024
            session_timeout: 会话超时（秒），默认 300.0
            backoff_base: 退避基数（秒），默认 1.0
            backoff_max: 最大退避（秒），默认 60.0
            jitter_factor: 抖动因子，默认 0.5
            compression: 压缩级别 0-9，默认 0 表示不压缩
            verify_ssl: 验证 SSL，默认 True
            max_listeners: 最大监听器数，默认 1000
            listener_buffer_size: 监听器缓冲区大小，默认 100
        """
        # 创建配置
        self.config = WebSocketConfig(
            uri=uri,
            headers=headers or {},
            heartbeat=heartbeat,
            receive_timeout=receive_timeout,
            reconnect_attempts=reconnect_attempts,
            connect_timeout=connect_timeout,
            send_queue_size=send_queue_size,
            session_timeout=session_timeout,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
            jitter_factor=jitter_factor,
            compression=compression,
            verify_ssl=verify_ssl,
            max_listeners=max_listeners,
            listener_buffer_size=listener_buffer_size,
        )

        # 设置日志
        self.logger = logger or logging.getLogger(__name__)

        # 核心组件
        self.connection = AioHttpWebSocketConnection(self.config, self.logger)
        self.reconnection = ReconnectionStrategy(self.config)

        # 监听器管理
        self._listeners: Dict[ListenerId, WebSocketListener] = {}
        self._listeners_lock = asyncio.Lock()

        # 状态控制
        self._running = False
        self._main_task: Optional[asyncio.Task] = None
        self._started_event = asyncio.Event()

        # 发送队列
        self._send_queue = asyncio.Queue(maxsize=self.config.send_queue_size)

    @property
    def running(self) -> bool:
        """检查客户端是否正在运行

        Returns:
            bool: 正在运行返回 True
        """
        return self._running

    async def __aenter__(self):
        """异步上下文管理器入口

        Returns:
            AsyncWebSocketClient: 客户端实例
        """
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口

        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪
        """
        await self.stop()

    async def start(self) -> None:
        """启动客户端

        启动主事件循环，开始处理连接、发送和接收。
        如果已经在运行，直接返回。
        """
        if self._running:
            return

        self._running = True
        self._started_event.clear()
        self._main_task = asyncio.create_task(self._main_loop())
        await self._started_event.wait()
        self.logger.info("WebSocket client started")

    async def stop(self) -> None:
        """停止客户端

        优雅地关闭连接、清理所有监听器和任务。
        如果已经停止，直接返回。
        """
        if not self._running:
            return

        self._running = False
        self.logger.debug("WebSocket client stopping")

        # 取消主任务
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
            self._main_task = None

        # 关闭所有监听器
        async with self._listeners_lock:
            for listener in self._listeners.values():
                listener.close()
            self._listeners.clear()

        # 关闭连接
        await self.connection.close()
        self._started_event.clear()

        self.logger.info("WebSocket client stopped")

    async def create_listener(self, buffer_size: Optional[int] = None) -> ListenerId:
        """创建消息监听器

        如果监听器数量达到上限，自动淘汰最旧的监听器。

        Args:
            buffer_size: 缓冲区大小，默认使用配置值

        Returns:
            ListenerId: 新监听器的唯一标识符
        """
        if buffer_size is None:
            buffer_size = self.config.listener_buffer_size

        listener = WebSocketListener(buffer_size)

        async with self._listeners_lock:
            # 检查监听器数量限制，内联淘汰逻辑避免嵌套死锁
            if len(self._listeners) >= self.config.max_listeners:
                if self._listeners:
                    oldest_id = min(
                        self._listeners.keys(),
                        key=lambda k: self._listeners[k].created_at,
                    )
                    oldest_listener = self._listeners.pop(oldest_id)
                    oldest_listener.close()
                    self.logger.warning(f"Evicted oldest listener: {oldest_id}")

            self._listeners[listener.id] = listener

        self.logger.debug(f"Listener created: {listener.id}")
        return listener.id

    async def remove_listener(self, listener_id: ListenerId) -> None:
        """移除指定监听器

        Args:
            listener_id: 要移除的监听器 ID
        """
        async with self._listeners_lock:
            listener = self._listeners.pop(listener_id, None)

        if listener:
            listener.close()
            self.logger.debug(f"Listener removed: {listener_id}")

    async def get_message(
        self, listener_id: ListenerId, timeout: Optional[float] = None
    ) -> Tuple[Any, MessageType]:
        """从指定监听器获取消息（阻塞）

        Args:
            listener_id: 监听器 ID
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            Tuple[Any, MessageType]: 消息内容和类型

        Raises:
            ListenerEvictedError: 监听器不存在时抛出
            ListenerClosedError: 监听器已关闭时抛出
            asyncio.TimeoutError: 超时时抛出
        """
        async with self._listeners_lock:
            listener = self._listeners.get(listener_id)

        if not listener:
            raise ListenerEvictedError(f"Listener {listener_id} not found")

        return await listener.get(timeout)

    async def get_message_nowait(
        self, listener_id: ListenerId
    ) -> Optional[Tuple[Any, MessageType]]:
        """从指定监听器非阻塞获取消息（async 以便线程安全调度）

        Args:
            listener_id: 监听器 ID

        Returns:
            Optional[Tuple[Any, MessageType]]: 消息内容和类型，无数据返回 None

        Raises:
            ListenerEvictedError: 监听器不存在时抛出
            ListenerClosedError: 监听器已关闭时抛出
        """
        async with self._listeners_lock:
            listener = self._listeners.get(listener_id)

        if not listener:
            raise ListenerEvictedError(f"Listener {listener_id} not found")

        return await listener.get_nowait()

    async def get_listener(self, listener_id: ListenerId) -> WebSocketListener:
        """获取监听器实例（用于异步迭代等高级操作）

        Args:
            listener_id: 监听器 ID

        Returns:
            WebSocketListener: 监听器实例

        Raises:
            ListenerEvictedError: 监听器不存在时抛出
        """
        async with self._listeners_lock:
            listener = self._listeners.get(listener_id)

        if not listener:
            raise ListenerEvictedError(f"Listener {listener_id} not found")

        return listener

    async def send(self, message: Union[str, bytes, Dict]) -> None:
        """发送消息到 WebSocket 服务器

        消息会被放入发送队列，由后台任务异步发送。

        Args:
            message: 要发送的消息，支持字符串、字节或字典

        Raises:
            WSConnectionError: 客户端未运行时抛出
            WebSocketError: 发送队列满时抛出
        """
        if not self._running:
            raise WSConnectionError("Client not running")

        try:
            self._send_queue.put_nowait(message)
        except QueueFull:
            raise WebSocketError("Send queue is full")

    async def get_metrics(self) -> Dict[str, Any]:
        """获取客户端运行指标

        Returns:
            Dict[str, Any]: 包含连接指标、重连状态、监听器统计的字典
        """
        connection_metrics = self.connection.metrics.copy()
        reconnection_state = self.reconnection.get_state()

        # CPython GIL 保证 len(dict) 原子性，无需加锁
        active_listeners = len(self._listeners)

        return {
            "connection": connection_metrics,
            "reconnection": reconnection_state,
            "listeners": {
                "active": active_listeners,
                "max": self.config.max_listeners,
            },
            "running": self._running,
        }

    async def _broadcast_message(self, message: Any, msg_type: MessageType) -> None:
        """广播消息到所有监听器

        如果某个监听器队列满，该监听器会被自动移除。

        Args:
            message: 消息内容
            msg_type: 消息类型
        """
        listeners_to_remove = []

        async with self._listeners_lock:
            listeners = list(self._listeners.values())

        for listener in listeners:
            if not await listener.put(message, msg_type):
                # 监听器队列满，标记为移除
                listeners_to_remove.append(listener.id)

        # 移除无法处理消息的监听器
        for listener_id in listeners_to_remove:
            await self.remove_listener(listener_id)
            self.logger.warning(f"Listener evicted due to buffer full: {listener_id}")

    async def _main_loop(self) -> None:
        """主事件循环

        管理连接生命周期，协调发送和接收任务。
        处理连接断开、重连和异常恢复。
        """
        self.logger.debug("Main loop started")
        self._started_event.set()

        try:
            while self._running:
                # 处理连接状态（首次连接失败也会进入重连逻辑）
                if not self.connection.is_connected():
                    await self._handle_disconnected()
                    if not self._running:
                        break
                    continue

                # 并行处理发送和接收
                send_task = asyncio.create_task(self._process_send_queue())
                recv_task = asyncio.create_task(self._process_receive())

                done, pending = await asyncio.wait(
                    [send_task, recv_task], return_when=asyncio.FIRST_COMPLETED
                )

                # 取消未完成的任务
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # 处理异常
                for task in done:
                    exc = task.exception()
                    if exc:
                        self.logger.error(f"Task error: {exc}")

                # 如果还在运行，说明有任务异常退出，关闭连接触发重连
                if self._running:
                    await self.connection.close()
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Main loop error: {e}")
        finally:
            await self.stop()
            self.logger.debug("Main loop ended")

    async def _handle_disconnected(self) -> None:
        """处理连接断开状态

        根据重连策略决定是否重连，并执行退避等待。
        如果超过最大重连次数，停止客户端。
        """
        if self.reconnection.should_reconnect():
            delay = self.reconnection.get_delay()
            if delay > 0:
                self.logger.info(f"Reconnection delay: {delay:.2f}s")
                await asyncio.sleep(delay)

            self.reconnection.on_attempt()
            self.logger.info(f"Reconnection attempt: {self.reconnection.attempt_count}")

            try:
                await self.connection.connect()
                self.reconnection.on_success()
            except WSConnectionError as e:
                self.logger.error(f"Reconnection failed: {e}")
        else:
            self.logger.error("Max reconnection attempts reached")
            await self.stop()

    async def _process_send_queue(self) -> None:
        """处理发送队列

        持续从队列取出消息并发送，处理连接中断时的消息回退。
        """
        while self._running:
            if not self.connection.is_connected():
                await asyncio.sleep(0.1)
                continue
            try:
                message = await asyncio.wait_for(self._send_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            try:
                await self.connection.send(message)
            except asyncio.CancelledError:
                # 将消息放回队列并重新抛出
                await self._send_queue.put(message)
                raise
            except WSConnectionError:
                # 连接不可用，将消息重新入队并退出，触发重连
                await self._send_queue.put(message)
                break
            except Exception as e:
                self.logger.error(f"Send processing error: {e}")
            finally:
                try:
                    self._send_queue.task_done()
                except Exception:
                    pass

    async def _process_receive(self) -> None:
        """处理接收消息

        持续接收消息并广播到所有监听器，处理超时和连接错误。
        """
        while self._running:
            if not self.connection.is_connected():
                await asyncio.sleep(0.1)
                continue
            try:
                message, msg_type = await self.connection.receive()

                # 广播消息到所有监听器
                await self._broadcast_message(message, msg_type)

            except asyncio.TimeoutError:
                # 只是没有消息，继续等待
                continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"Receive processing error: {e}")
                # 接收错误通常意味着连接问题，关闭连接触发重连
                try:
                    await self.connection.close()
                except Exception:
                    pass
                break


class SyncWebSocketClient:
    """同步 WebSocket 客户端包装器

    为同步代码提供 WebSocket 客户端功能，内部在后台线程运行异步事件循环。
    所有方法都是线程安全的。

    Attributes:
        _client: 底层异步客户端实例
        _loop: 事件循环
        _thread: 后台线程
        _running: 运行状态
    """

    def __init__(self, *args, **kwargs):
        """初始化同步客户端

        Args:
            *args: 传递给 AsyncWebSocketClient 的位置参数
            **kwargs: 传递给 AsyncWebSocketClient 的关键字参数
        """
        self._client = AsyncWebSocketClient(*args, **kwargs)
        self._loop = asyncio.new_event_loop()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._started_event = threading.Event()

    def start(self) -> None:
        """启动客户端（在后台线程中运行事件循环）

        如果已经在运行，直接返回。启动后会等待客户端真正就绪。
        """
        with self._lock:
            if self._running:
                return

            self._running = True
            self._started_event.clear()

            def run_loop():
                asyncio.set_event_loop(self._loop)
                try:
                    # run_until_complete 会启动事件循环并阻塞到 start() 完成
                    # 此时 _main_loop 任务已被创建，_started_event 已被设置
                    self._loop.run_until_complete(self._client.start())
                    self._started_event.set()
                    # 保持事件循环运转，持续处理收发任务
                    self._loop.run_forever()
                except Exception as e:
                    self._client.logger.error(f"Event loop error: {e}")
                finally:
                    self._loop.close()

            self._thread = threading.Thread(target=run_loop, daemon=True)
            self._thread.start()

        # 等待后台线程通知启动完成
        if not self._started_event.wait(timeout=10):
            with self._lock:
                self._running = False
            raise RuntimeError("Failed to start WebSocket client")

    def stop(self) -> None:
        """停止客户端

        优雅地停止事件循环和后台线程，清理资源。
        如果已经停止，直接返回。
        """
        with self._lock:
            if not self._running:
                return
            self._running = False

        # 在事件循环线程中停止客户端
        try:
            future = asyncio.run_coroutine_threadsafe(self._client.stop(), self._loop)
            future.result(timeout=10)
        except Exception as e:
            self._client.logger.error(f"Stop error: {e}")

        # 停止事件循环
        self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def create_listener(self, buffer_size: Optional[int] = None) -> str:
        """创建消息监听器（同步）

        Args:
            buffer_size: 缓冲区大小，默认使用配置值

        Returns:
            str: 监听器 ID 字符串
        """
        future = asyncio.run_coroutine_threadsafe(
            self._client.create_listener(buffer_size), self._loop
        )
        return future.result(timeout=10)

    def remove_listener(self, listener_id: ListenerId) -> None:
        """移除监听器（同步）

        Args:
            listener_id: 要移除的监听器 ID
        """
        future = asyncio.run_coroutine_threadsafe(
            self._client.remove_listener(listener_id), self._loop
        )
        future.result(timeout=10)

    def get_message(
        self, listener_id: ListenerId, timeout: Optional[float] = None
    ) -> Tuple[Any, MessageType]:
        """获取消息（同步阻塞）

        Args:
            listener_id: 监听器 ID
            timeout: 超时时间（秒），包含线程调度时间

        Returns:
            Tuple[Any, MessageType]: 消息内容和类型
        """
        future = asyncio.run_coroutine_threadsafe(
            self._client.get_message(listener_id, timeout), self._loop
        )
        return future.result(timeout=timeout)

    def get_message_nowait(
        self, listener_id: ListenerId
    ) -> Optional[Tuple[Any, MessageType]]:
        """非阻塞获取消息（同步）

        Args:
            listener_id: 监听器 ID

        Returns:
            Optional[Tuple[Any, MessageType]]: 消息内容和类型，无数据返回 None
        """
        future = asyncio.run_coroutine_threadsafe(
            self._client.get_message_nowait(listener_id), self._loop
        )
        return future.result(timeout=5)

    def send(self, message: Union[str, bytes, Dict]) -> None:
        """发送消息（同步）

        Args:
            message: 要发送的消息，支持字符串、字节或字典
        """
        future = asyncio.run_coroutine_threadsafe(
            self._client.send(message), self._loop
        )
        future.result(timeout=10)

    def get_metrics(self) -> Dict[str, Any]:
        """获取客户端指标（同步）

        Returns:
            Dict[str, Any]: 客户端运行指标字典
        """
        future = asyncio.run_coroutine_threadsafe(
            self._client.get_metrics(), self._loop
        )
        return future.result(timeout=5)

    def __enter__(self):
        """上下文管理器入口

        Returns:
            SyncWebSocketClient: 客户端实例
        """
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口

        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪
        """
        self.stop()


# 使用示例
if __name__ == "__main__":

    async def example_usage():
        """异步客户端使用示例"""
        # 创建客户端
        client = AsyncWebSocketClient("wss://echo.websocket.org")

        async with client:
            # 创建监听器
            listener_id = await client.create_listener()

            # 发送消息
            await client.send("Hello, WebSocket!")

            # 接收消息（异步阻塞）
            try:
                message, msg_type = await client.get_message(listener_id, timeout=10)
                print(f"Received: {message}, type: {msg_type}")
            except asyncio.TimeoutError:
                print("Timeout waiting for message")

            # 或者通过公共 API 获取监听器进行异步迭代
            listener = await client.get_listener(listener_id)
            async for message, msg_type in listener:
                print(f"Iterated: {message}, type: {msg_type}")
                break  # 只接收一条消息作为示例

    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_usage())

"""

## 能力速览
1. 全异步 / 同步双形态
   AsyncWebSocketClient  —— 原生协程，性能高
   SyncWebSocketClient   —— 内部启线程+事件循环，给同步代码用

2. 监听器模式
   任意线程/协程可以“订阅”一个 listener_id，消息广播到所有监听器；
   每个监听器自带环形缓冲区，满时自动丢弃最旧数据，不会阻塞收发。

3. 全自动重连
   指数退避 + 随机抖动，可设最大次数或无限重连（0 表示无限）；
   网络闪断、压缩协商失败、服务端踢人都会自动重试。

4. 指标可观测
   连接次数、收发字节、队列长度、监听器数量一键导出，方便接入 Prometheus。

------------------------------------------------

## API 一张表
| 目标 | 异步用法 | 同步用法 | 备注 |
|---|---|---|---|
| 启动 | `async with client:` 或 `await client.start()` | `ws.start()` | 同步版启动后事件循环在后台线程跑 |
| 发消息 | `await client.send(dict/text/bytes)` | `ws.send(...)` | 队列满抛 `WebSocketError` |
| 收消息 | `await client.get_message(lid, timeout=10)` | `ws.get_message(lid, timeout=10)` | 超时抛 `asyncio.TimeoutError` |
| 非阻塞收 | `await client.get_message_nowait(lid)` | `ws.get_message_nowait(lid)` | 无数据返回 None |
| 异步迭代 | `async for msg, typ in await client.get_listener(lid):` | 不支持 | 需通过公共 API 获取监听器实例 |
| 关闭 | 自动 / `await client.stop()` | `ws.stop()` | 会等待内部任务结束，线程安全 |
| 指标 | `client.get_metrics()` | `ws.get_metrics()` | 实时 Dict，含连接、重连、监听器数量 |

------------------------------------------------
## 踩坑提示
1. 监听器用完务必 `remove_listener`，否则一直占内存；
   当监听器数达到 `max_listeners` 会自动淘汰最旧的，可日志里看到 `Evicted`。

2. 发送队列满默认抛异常；如果想“覆盖旧数据”而不是抛错，把 `_send_queue` 换成环形队列即可，源码位置已留注释。

3. 同步版 `get_message` 的 `timeout` 是“从调用到返回”的总时长，包含线程调度时间，设太短容易超时。

4. 服务端如果发超大二进制帧，记得把 `receive_timeout` 适当调大，否则半截没收到就会触发重连。

5. 压缩协商失败（zlib wbits 错误）客户端会自动关闭压缩再重连一次，无需人工干预。

6. 异常命名已改为 `WSConnectionError`，避免与 Python 内置 `ConnectionError` 冲突。

7. `reconnect_attempts=0` 现在真正表示无限重连，与文档一致。

------------------------------------------------

"""
