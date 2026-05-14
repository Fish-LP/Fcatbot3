"""
交互式控制台 —— ConsoleApp + ConsoleMixin 自动化挂载
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import print_formatted_text

from fcatbot.plugkit.protocol.plugin import Plugin, PluginMixin
from fcatbot.utils.cmdparse import (
    CommandApp,
    CommandContext,
    ParseError,
    on_command,
)
from fcatbot.utils.color import Color

if TYPE_CHECKING:
    from fcatbot.__main__ import Bot

log = logging.getLogger("Console")

# ==================== ConsoleApp ====================


class ConsoleApp:
    """控制台命令应用。

    基于 ``cmdparse`` 构建全局命令树。内置命令直接注册在根节点下；
    插件通过 ``ConsoleMixin`` 触发 ``register_instance`` / ``unregister``，
    自动扫描实例方法、合并到根树、并按提供者记录以便卸载。
    """

    def __init__(self, bot: "Bot"):
        self.bot = bot
        self.app = CommandApp(
            Name="ConsoleRoot",
            Description="FcatBot 交互式控制台",
            colorize=True,
        )
        self._registered: dict[str, list[str]] = {}  # provider -> [cmd_names]
        self._register_builtin()

    def _register_builtin(self) -> None:
        """注册内置控制台命令。"""
        for func in (
            self._help,
            self._stop,
            self._status,
            # self._reload,
        ):
            self.app.register(func)

    # ---------- 内置命令 ----------
    @on_command(description="显示帮助信息")
    async def _help(self, ctx: CommandContext, raw: str = "") -> str:
        """显示帮助信息。

        不带参数时显示全局命令列表，带参数时显示指定命令的详细帮助。

        Args:
            ctx: 命令上下文。
            raw: 目标命令路径，为空时显示全局帮助。

        Return:
            格式化后的帮助文本。
        """
        app: CommandApp = self.app
        node = app.node
        if raw.strip():
            for part in raw.strip().split():
                if part in node.Subcommands:
                    node = node.Subcommands[part]
                else:
                    return f"{Color.Red}未知命令: {raw}{Color.Reset}"
        return app._format_help(node)

    @on_command(description="停止 Bot")
    async def _stop(self, ctx: CommandContext) -> str:
        """停止 Bot。

        Args:
            ctx: 命令上下文。

        Return:
            停止提示文本。
        """
        app: ConsoleApp = self
        if app is None:
            return f"{Color.Red}内部错误{Color.Reset}"
        asyncio.create_task(app.bot.stop())
        return f"{Color.Yellow}正在停止 Bot ...{Color.Reset}"

    @on_command(description="查看插件状态")
    async def _status(self, ctx: CommandContext) -> str:
        """查看插件状态。

        Args:
            ctx: 命令上下文。

        Return:
            各插件状态列表。
        """
        app: ConsoleApp = self
        if app is None:
            return f"{Color.Red}内部错误{Color.Reset}"
        pm = app.bot._plugin_manager
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

    @on_command(description="重载指定插件")
    async def _reload(self, ctx: CommandContext, raw: str = "") -> str:
        """重载指定插件。

        Args:
            ctx: 命令上下文。
            raw: 原始参数字符串，首个词为插件名。

        Return:
            重载结果提示。
        """
        app: ConsoleApp = self
        if app is None:
            return f"{Color.Red}内部错误{Color.Reset}"
        pm = app.bot._plugin_manager
        if pm is None:
            return f"{Color.Red}插件管理器尚未初始化{Color.Reset}"
        parts = raw.split()
        if not parts:
            return "Usage: reload <plugin_name>"
        name = parts[0]
        try:
            await pm.reload(name)
            return f"{Color.Green}{name} 重载成功{Color.Reset}"
        except Exception as e:
            return f"{Color.Red}重载失败: {e}{Color.Reset}"

    # ---------- 插件注册接口 ----------
    def register_instance(self, instance: Any, provider: str) -> None:
        """扫描实例上的命令方法，注册到全局命令树。

        Args:
            instance: 插件实例（或任何包含命令方法的对象）。
            provider: 提供者标识，用于后续卸载。

        Return:
            None
        """
        if provider in self._registered:
            log.debug("Console register skipped: %s already registered", provider)
            return

        cmd_app = CommandApp(Name=provider, Description=f"{provider} commands")
        cmd_app.register_instance(instance)

        if not cmd_app._node.Subcommands:
            return

        self._merge(cmd_app, provider)

    def _merge(self, cmd_app: CommandApp, provider: str) -> None:
        """将 ``cmd_app`` 的子命令/子组合并到根命令树，并记录 provider 映射。

        Args:
            cmd_app: 插件提供的命令应用。
            provider: 插件名称。

        Return:
            None
        """
        node = cmd_app._node
        registered_names: list[str] = []

        seen_nodes: set[int] = set()
        for name, sub_node in list(node.Subcommands.items()):
            if id(sub_node) in seen_nodes:
                continue
            seen_nodes.add(id(sub_node))

            if name in self.app._node.Subcommands:
                log.warning(
                    "Command name conflict: %s (from %s), skipped", name, provider
                )
                continue

            self.app._node.AddSubcommand(sub_node)
            registered_names.append(name)

        self._registered[provider] = registered_names
        log.info(
            "Console registered %d command(s) from %s", len(registered_names), provider
        )

    def unregister(self, provider: str) -> None:
        """按提供者移除已注册的命令/子组。

        Args:
            provider: 插件名称。

        Return:
            None
        """
        names = self._registered.pop(provider, [])
        for name in names:
            self.app._node.Subcommands.pop(name, None)
            alt = name.replace("-", "_")
            if alt != name:
                self.app._node.Subcommands.pop(alt, None)

        log.info("Console unregistered %d command(s) from %s", len(names), provider)

    async def execute(self, text: str) -> Any:
        """解析并执行控制台命令。

        Args:
            text: 用户输入的原始命令行。

        Return:
            命令执行结果。
        """
        return await self.app.run(text, "console")


# ==================== ConsoleMixin ====================


class ConsoleMixin(PluginMixin):
    """控制台命令混入类。

    插件继承此类并在实例方法上使用 ``@on_command`` 或 ``_cmd_`` 前缀命名，
    加载时自动扫描、绑定并合并到全局控制台根命令树，卸载时自动移除。
    """

    async def on_mixin_load(self, plugin: Plugin, env: Any) -> None:
        """将本插件实例注册到全局控制台。

        Args:
            plugin: 当前插件实例（与 self 为同一对象）。
            env: 加载环境。

        Return:
            None
        """
        try:
            console: ConsoleApp = self.registry.require("console.app")
        except Exception:
            log.debug("Plugin %s: console.app not available", self.name)
            return

        console.register_instance(self, provider=self.name)

    async def on_mixin_unload(self, plugin: Plugin, env: Any) -> None:
        """从全局控制台移除本插件的命令。

        Args:
            plugin: 当前插件实例。
            env: 卸载环境。

        Return:
            None
        """
        try:
            console: ConsoleApp = self.registry.require("console.app")
        except Exception:
            return
        console.unregister(self.name)


# ==================== PromptToolkitConsole ====================


class _PromptToolkitLogHandler(logging.Handler):
    """通过 ``print_formatted_text`` 输出日志，正确解析 ANSI 并重绘输入行。

    在 ``patch_stdout`` 上下文中调用时，prompt_toolkit 会自动同步光标位置，
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

        session = PromptSession("> ")
        _print = print_formatted_text

        # 准备 PromptToolkit 专用日志处理器（暂不挂载到 root）
        self._old_console_handlers.clear()
        for handler in logging.root.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                self._old_console_handlers.append(handler)

        self._pt_handler = _PromptToolkitLogHandler(session.app)
        if self._old_console_handlers:
            self._pt_handler.setLevel(self._old_console_handlers[0].level)
            self._pt_handler.setFormatter(self._old_console_handlers[0].formatter)
        else:
            self._pt_handler.setLevel(logging.INFO)

        async def _cleanup_loop() -> None:
            """后台任务：定期清理动态添加的 console StreamHandler，防止重复输出和 ANSI 乱码。"""
            while not self._stop_event.is_set():
                for h in logging.root.handlers[:]:
                    if (
                        isinstance(h, logging.StreamHandler)
                        and not isinstance(h, logging.FileHandler)
                        and h is not self._pt_handler
                    ):
                        if h not in self._old_console_handlers:
                            self._old_console_handlers.append(h)
                        logging.root.removeHandler(h)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass

        async def _loop() -> None:
            with patch_stdout():
                # 在 patch_stdout 保护下挂载 pt_handler，并移除所有其他 console StreamHandler
                logging.root.addHandler(self._pt_handler)
                for h in logging.root.handlers[:]:
                    if (
                        isinstance(h, logging.StreamHandler)
                        and not isinstance(h, logging.FileHandler)
                        and h is not self._pt_handler
                    ):
                        if h not in self._old_console_handlers:
                            self._old_console_handlers.append(h)
                        logging.root.removeHandler(h)

                cleanup_task = asyncio.create_task(_cleanup_loop())
                try:
                    while not self._stop_event.is_set():
                        try:
                            text = await session.prompt_async()
                            result = await self.console.execute(text)
                            if result is not None:
                                _print(
                                    # ANSI(f"{Color.Cyan}[Console]{Color.Reset} {result}")
                                    ANSI(result)
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
                    cleanup_task.cancel()
                    try:
                        await cleanup_task
                    except asyncio.CancelledError:
                        pass
                    if self._pt_handler and self._pt_handler in logging.root.handlers:
                        logging.root.removeHandler(self._pt_handler)
                    for h in self._old_console_handlers:
                        if h not in logging.root.handlers:
                            logging.root.addHandler(h)

        self._task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        """停止控制台输入循环。"""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def attach_console(bot: "Bot", console: ConsoleApp) -> PromptToolkitConsole:
    """工厂函数：创建并返回 PromptToolkitConsole 实例。

    Args:
        bot: Bot 主实例。
        console: 已初始化的 ConsoleApp。

    Return:
        PromptToolkitConsole 实例。
    """
    return PromptToolkitConsole(bot, console)
