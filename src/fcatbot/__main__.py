import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import ClassVar, Optional

from fcatbot.connection.websocket import AsyncWebSocketClient, ListenerId
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.runtime.bus import Bus
from fcatbot.plugkit.runtime.lifecycle import LifecycleManager
from fcatbot.plugkit.runtime.loader import PluginLoader
from fcatbot.utils.logger import setup_logging

setup_logging()
log = logging.getLogger("Bot")


class ConnectionService:
    """受控 WS 发送服务"""

    version = "1.0.0"

    def __init__(self, ws: AsyncWebSocketClient):
        self._ws = ws
        self.uri = ws.config.uri

    async def send_raw(self, payload: str | bytes) -> None:
        """发送原始 WS 帧（只写）"""
        await self._ws.send(payload)

    @property
    def connected(self) -> bool:
        return self._ws._running


class Bot:
    """Fcatbot 统一入口 —— 纯同步初始化，异步阶段再启动各组件。"""

    running: ClassVar[bool] = False

    def __init__(
        self,
        root_id: int | str,
        url: str,
        token: Optional[str] = None,
        plugin_dir: Optional[Path | str] = None,
        data_dir: Path | str = "data",
        debug: bool = False,
        dev: bool = False,
    ):
        self.debug = debug
        self.dev = dev
        self.root_id = str(root_id)
        self.url = url
        self.token = token
        self.data_dir = Path(data_dir)

        # ---------- HTTP API（纯同步创建） ----------
        http_url = url
        if url.startswith("ws://"):
            http_url = "http://" + url[5:]
        elif url.startswith("wss://"):
            http_url = "https://" + url[6:]

        log.debug("HTTP API 基地址: %s", http_url)

        # ---------- WebSocket（仅保存配置，不连接） ----------
        headers = {}
        if token:
            headers["Authorization"] = token

        self._ws = AsyncWebSocketClient(
            uri=url,
            headers=headers,
            logger=logging.getLogger("WS"),
            reconnect_attempts=20,
        )

        # 以下成员在 run_async() 中初始化
        self._bus: Optional[Bus] = None
        self._plugin_manager: Optional[LifecycleManager] = None
        self._loader: Optional[PluginLoader] = None

        self._plugin_dirs: list[Path] = []
        sys_dir = Path(__file__).resolve().parent / "sys_plugin"
        if sys_dir.exists():
            self._plugin_dirs.append(sys_dir)
        if plugin_dir:
            self._plugin_dirs.append(Path(plugin_dir))

        self._listener_id: Optional[ListenerId] = None
        self._stop_event = asyncio.Event()

    # ==================== 同步入口 ====================

    def run(self) -> None:
        """阻塞式启动，支持嵌套事件循环。"""

        logging.basicConfig(
            level=logging.DEBUG if self.debug else logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            stream=sys.stdout,
        )

        async def _runner() -> None:
            try:
                await self.run_async()
                await self._stop_event.wait()  # 等 stop() 或 finally 里 set
            except asyncio.CancelledError:
                log.info("Bot 任务被取消")
            except Exception:
                log.exception("Bot 运行异常")
            finally:
                await self.stop()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_runner())
        else:
            loop.run_until_complete(_runner())

    # ==================== 异步入口 ====================

    async def run_async(self) -> None:
        if Bot.running:
            raise RuntimeError("Bot 实例已经在运行")
        Bot.running = True
        self._stop_event.clear()

        try:
            await self._ws.start()
            self._listener_id = await self._ws.create_listener()

            self._bus = Bus(max_queue=1000, workers=4)
            self._bus.start()

            self._loader = PluginLoader(self._plugin_dirs)
            self._plugin_manager = LifecycleManager(
                bus=self._bus,
                data_root=self.data_dir,
                loader=self._loader,
                debug=self.debug,
                dev=self.dev,
                plugin_dirs=self._plugin_dirs,
            )

            # 注册到注册表
            self._plugin_manager._registry.register(
                name="bot.ws.connection",
                instance=ConnectionService(self._ws),
                provider="Bot",
                version=ConnectionService.version,
            )

            plugin_classes = self._discover_plugins()
            if plugin_classes:
                await self._plugin_manager.load_all(plugin_classes)
                for name in self._plugin_manager.list_names():
                    await self._plugin_manager.start(name)

            log.info("Bot 启动完成，开始接收事件 ...")

            serve_task = asyncio.create_task(
                self._plugin_manager.serve(), name="plugin-serve"
            )

            try:
                while not self._stop_event.is_set() and self._ws.running:
                    await self._cat()
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                pass
            finally:
                print()

            serve_task.cancel()
            try:
                await serve_task
            except asyncio.CancelledError:
                pass

        except KeyboardInterrupt:
            pass
        except Exception as e:
            if self.debug:
                raise
            log.error("Bot 异常: %s", e)
        finally:
            try:
                await self._ws.stop()
            except Exception as exc:
                log.error("WS 关闭异常: %s", exc)
            Bot.running = False
            self._stop_event.set()  # ← 关键：释放 _runner 的 wait()
            log.info("Bot 已完全停止")

    # ==================== 内部运行循环 ====================

    async def _cat(self) -> None:
        """从 WS 读取原始消息，以最小开销发布到总线。"""
        if self._listener_id is None:
            await asyncio.sleep(0.05)
            return

        try:
            msg, msg_type = await self._ws.get_message(self._listener_id, timeout=1.0)
        except asyncio.TimeoutError:
            return
        except Exception as exc:
            log.debug("WS 接收异常: %s", exc)
            return

        # 不解析、不过滤，直接包装为原始事件
        event = Event(
            name="sdk.raw",  # 统一原始事件名
            data=msg,  # 原始字符串 / bytes
            source="sdk",
            metadata={
                "msg_type": (
                    msg_type.name if hasattr(msg_type, "name") else str(msg_type)
                )
            },
        )
        if self._bus is not None:
            await self._bus.publish(event)

    # ==================== 优雅退出 ====================

    async def stop(self) -> None:
        if not Bot.running and self._stop_event.is_set():
            return

        self._stop_event.set()
        print()
        log.info("Bot 正在退出 ...")

        if self._plugin_manager is not None:
            try:
                await self._plugin_manager.shutdown()
            except Exception as exc:
                log.error("插件系统关闭异常: %s", exc)

        try:
            await self._ws.stop()
        except Exception as exc:
            log.error("WS 关闭异常: %s", exc)

        Bot.running = False
        log.info("Bot 已完全停止")

    # ==================== 工具 ====================

    def _request_shutdown(self) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()

    def _discover_plugins(self) -> list[type[Plugin]]:
        """扫描 plugin_dirs，返回所有 Plugin 子类。"""
        classes: list[type[Plugin]] = []
        if self._loader is None:
            return classes
        for directory in self._plugin_dirs:
            if not directory.exists():
                continue
            for entry in directory.iterdir():
                name: Optional[str] = None
                if entry.is_dir() and (entry / "__init__.py").exists():
                    name = entry.name
                elif (
                    entry.is_file()
                    and entry.suffix == ".py"
                    and entry.stem != "__init__"
                ):
                    name = entry.stem

                if not name:
                    continue

                try:
                    cls = self._loader.load_class(name)
                    classes.append(cls)
                    log.debug("发现插件: %s", name)
                except Exception as exc:
                    # from fcatbot.plugkit.runtime.loader import No
                    log.warning("加载插件 %s 失败: %s", name, exc)
                    # raise exc
        return classes


# ==================== CLI ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="fcatbot", description="Fcatbot CLI：启动 Bot。"
    )
    sub = parser.add_subparsers(dest="cmd", help="子命令")

    p_start = sub.add_parser("start", help="启动 Bot")
    p_start.add_argument("-u", "--url", required=True, help="WebSocket 地址")
    p_start.add_argument("-t", "--token", help="鉴权 token")
    p_start.add_argument("-p", "--plugin-dir", type=Path, help="额外插件目录")
    p_start.add_argument("--data-dir", type=Path, default="data", help="数据目录")
    p_start.add_argument(
        "--debug", action="store_true", help="调试模式（详细日志+异常透传）"
    )
    p_start.add_argument(
        "--dev", action="store_true", help="开发模式（插件热重载+文件监视）"
    )

    args = parser.parse_args()

    if args.cmd == "start":
        bot = Bot(
            root_id=0,
            url=args.url,
            token=args.token,
            plugin_dir=args.plugin_dir,
            data_dir=args.data_dir,
            debug=args.debug,
            dev=args.dev,
        )
        try:
            bot.run()
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        parser.print_help()
