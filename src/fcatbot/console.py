"""
交互式控制台 —— ConsoleApp + ConsoleMixin 自动化挂载
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import types
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from fcatbot.plugkit.protocol.plugin import Plugin, PluginMixin
from fcatbot.utils.cmdparse import CommandApp, ParseError
from fcatbot.utils.color import Color

if TYPE_CHECKING:
    from fcatbot.__main__ import Bot

log = logging.getLogger("Console")


# ==================== ConsoleApp ====================


class ConsoleApp:
    """控制台命令应用，基于 cmdparse 构建命令树，并暴露 mount/unmount 能力。"""

    def __init__(self, bot: "Bot"):
        self.bot = bot
        self.app = CommandApp(Name="fcatbot", Description="FcatBot 交互式控制台")
        self._register_builtin()

    def _register_builtin(self) -> None:
        @self.app.command(description="显示帮助信息")
        async def help() -> str:
            return self.app._format_help(self.app._node)

        @self.app.command(description="停止 Bot")
        async def stop() -> str:
            asyncio.create_task(self.bot.stop())
            return f"{Color.Yellow}正在停止 Bot ...{Color.Reset}"

        @self.app.command(description="查看插件状态")
        async def status() -> str:
            pm = self.bot._plugin_manager
            if pm is None:
                return f"{Color.Red}插件管理器尚未初始化{Color.Reset}"
            lines = [f"{Color.Bold}插件状态:{Color.Reset}"]
            for name in pm.list_names():
                plugin = pm.get(name)
                if plugin is None:
                    continue
                st = plugin.status
                color = Color.Green if st.state.name == "Running" else Color.Yellow
                lines.append(
                    f"  {color}{name:<20}{Color.Reset} {st.state.name} "
                    f"{Color.Gray}(ver {plugin.version}){Color.Reset}"
                )
            return "\n".join(lines)

        @self.app.command(description="重载指定插件")
        async def reload(name: str) -> str:
            pm = self.bot._plugin_manager
            if pm is None:
                return f"{Color.Red}插件管理器尚未初始化{Color.Reset}"
            try:
                await pm.reload(name)
                return f"{Color.Green}{name} 重载成功{Color.Reset}"
            except Exception as e:
                return f"{Color.Red}重载失败: {e}{Color.Reset}"

        @self.app.command(description="列出已加载插件")
        async def plugins() -> str:
            pm = self.bot._plugin_manager
            if pm is None:
                return f"{Color.Red}插件管理器尚未初始化{Color.Reset}"
            names = pm.list_names()
            return (
                f"已加载 {len(names)} 个插件: {', '.join(names) if names else '(无)'}"
            )

        @self.app.command(description="发送原始 WS 消息（调试）")
        async def send(payload: str) -> str:
            try:
                await self.bot._ws.send(payload)
                return "已发送"
            except Exception as e:
                return f"{Color.Red}发送失败: {e}{Color.Reset}"

        @self.app.command(description="手动发布事件（调试）")
        async def event(name: str, payload: str = "") -> str:
            from fcatbot.plugkit.protocol.event import Event

            bus = self.bot._bus
            if bus is None:
                return f"{Color.Red}事件总线尚未初始化{Color.Reset}"
            await bus.publish(Event(name=name, data=payload, source="console"))
            return f"事件 {name} 已发布"

    def mount(self, cmd_app: CommandApp) -> None:
        """将插件的 CommandApp 作为子命令组挂载到根命令树。"""
        self.app._node.AddSubcommand(cmd_app._node)
        log.info("Console mounted: %s", cmd_app._node.Name)

    def unmount(self, name: str) -> None:
        """按名称移除子命令组。"""
        removed = self.app._node.Subcommands.pop(name, None)
        if removed:
            log.info("Console unmounted: %s", name)

    async def execute(self, text: str) -> Any:
        """解析并执行控制台命令。"""
        return await self.app.run(text)


# ==================== ConsoleMixin ====================


class ConsoleMixin(PluginMixin):
    """控制台命令混入类。

    插件继承此类并定义 ``commands`` 类属性（CommandApp 实例），
    加载时自动注册到全局控制台，卸载时自动移除。
    """

    commands: ClassVar[CommandApp | None] = None

    async def on_mixin_load(self, plugin: Plugin, env: Any) -> None:
        """self 与 plugin 为同一实例，可直接使用 self 访问插件属性。"""
        if self.commands is None:
            return
        try:
            console: ConsoleApp = self.registry.require("console.app")
        except Exception:
            log.debug("Plugin %s: console.app not available", self.name)
            return

        # 绑定类体函数为实例方法，使 handler 内 self 指向当前插件
        for sub in self.commands._node.Subcommands.values():
            if sub.Handler is None:
                continue
            if not inspect.ismethod(sub.Handler):
                qualname = getattr(sub.Handler, "__qualname__", "")
                if "." in qualname:
                    sub.Handler = types.MethodType(sub.Handler, self)

        console.mount(self.commands)

    async def on_mixin_unload(self, plugin: Plugin, env: Any) -> None:
        if self.commands is None:
            return
        try:
            console: ConsoleApp = self.registry.require("console.app")
        except Exception:
            return
        console.unmount(self.commands._node.Name)


# ==================== PromptToolkitConsole ====================


class _PromptToolkitLogHandler(logging.Handler):
    """通过 print_formatted_text 输出日志，正确解析 ANSI 并重绘输入行。

    在 patch_stdout 上下文中调用时，prompt_toolkit 会自动同步光标位置，
    避免输入行被日志覆盖。
    """

    def __init__(self, app, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            from prompt_toolkit.formatted_text import ANSI
            from prompt_toolkit.shortcuts import print_formatted_text

            # ANSI() 将 \x1b[36m 等转义序列转换为 prompt_toolkit 内部样式
            print_formatted_text(ANSI(msg), output=self.app.output, end="\n")
        except Exception:
            self.handleError(record)


class PromptToolkitConsole:
    """基于 prompt_toolkit 的交互式控制台。"""

    def __init__(self, bot: "Bot", console: ConsoleApp):
        self.bot = bot
        self.console = console
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._old_console_handlers: list[logging.StreamHandler] = []
        self._pt_handler: Optional[_PromptToolkitLogHandler] = None

    async def start(self) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.patch_stdout import patch_stdout
        from prompt_toolkit.shortcuts import print_formatted_text

        session = PromptSession("> ")
        _print = print_formatted_text

        # ---------- 关键改动：准备 PromptToolkit 专用日志处理器 ----------
        # 收集现有的 console StreamHandler（通常是带 ANSI 颜色的那个）
        for handler in logging.root.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                self._old_console_handlers.append(handler)

        self._pt_handler = _PromptToolkitLogHandler(session.app)
        if self._old_console_handlers:
            # 继承原有 console handler 的级别和格式（保留颜色模板）
            self._pt_handler.setLevel(self._old_console_handlers[0].level)
            self._pt_handler.setFormatter(self._old_console_handlers[0].formatter)
        else:
            self._pt_handler.setLevel(logging.INFO)

        logging.root.addHandler(self._pt_handler)
        # --------------------------------------------------------------

        async def _loop() -> None:
            with patch_stdout():
                # 在 patch_stdout 内部临时移除旧 console handler，避免重复输出
                for h in self._old_console_handlers:
                    logging.root.removeHandler(h)

                try:
                    while not self._stop_event.is_set():
                        try:
                            text = await session.prompt_async()
                            result = await self.console.execute(text)
                            if result is not None:
                                _print(
                                    ANSI(f"{Color.Cyan}[Console]{Color.Reset} {result}")
                                )
                        except ParseError as e:
                            _print(ANSI(f"{Color.Red}ParseError{Color.Reset}: {e}"))
                        except EOFError:
                            asyncio.create_task(self.bot.stop())
                            break
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            log.exception("Console execute failed")
                            _print(ANSI(f"{Color.Red}Error{Color.Reset}: {e}"))
                finally:
                    # 恢复原有 handler
                    for h in self._old_console_handlers:
                        logging.root.addHandler(h)
                    if self._pt_handler:
                        logging.root.removeHandler(self._pt_handler)

        self._task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def attach_console(bot: "Bot", console: ConsoleApp) -> PromptToolkitConsole:
    """工厂函数。"""
    return PromptToolkitConsole(bot, console)
