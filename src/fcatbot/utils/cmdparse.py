from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

# ==================== 装饰器层 ====================


class GroupBuilder:
    """Group 装饰器构建器，用于创建命令分组。

    通过该类可以将多个相关命令组织到一个分组下，形成层级命令结构。
    被装饰的函数将成为该分组的根节点，其下的子命令通过 `.command()` 注册。

    Args:
        name: 分组名称，若未指定则使用被装饰函数的函数名。
        description: 分组描述信息。
    """

    def __init__(self, name: Optional[str] = None, *, description: str = ""):
        self.name = name
        self.description = description

    def __call__(
        self,
        func: Optional[Callable[..., Any]] = None,
        *,
        description: str = "",
    ) -> Any:
        """使实例可被直接调用作为装饰器。

        支持无参数装饰器用法 `@group` 或有参数用法 `@group(...)`。

        Args:
            func: 被装饰的函数，若为 None 则返回一个真正的装饰器函数。
            description: 针对该具体命令节点的描述，优先级高于构造时的 description。

        Return:
            被标记后的原函数，或一个待应用的装饰器函数。
        """
        desc = description or self.description
        if func is not None:
            return self._mark(func, desc)

        def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
            return self._mark(f, desc)

        return decorator

    def _mark(self, func: Callable[..., Any], description: str) -> Callable[..., Any]:
        """在函数上标记分组根节点的元数据。

        Args:
            func: 目标函数。
            description: 描述文本。

        Return:
            被标记后的原函数。
        """
        func.__command_group_name__ = self.name or func.__name__
        func.__command_group_description__ = self.description
        func.__command_description__ = description
        func.__command_is_group_root__ = True
        return func

    def command(
        self,
        name: Optional[str] = None,
        *,
        description: str = "",
        aliases: Optional[Sequence[str]] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """返回一个装饰器，用于将函数注册为当前分组下的子命令。

        Args:
            name: 子命令名称。若为 None，则自动从函数名推导（去除 _cmd_ 或 _ 前缀）。
            description: 子命令描述。
            aliases: 子命令别名列表。

        Return:
            一个装饰器函数，接收原函数并返回标记后的函数。
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            node_name = name
            if node_name is None:
                node_name = func.__name__
                if node_name.startswith("_cmd_"):
                    node_name = node_name[5:]
                if node_name.startswith("_"):
                    node_name = node_name[1:]
            func.__command_name__ = node_name
            func.__command_description__ = description
            func.__command_group__ = self.name
            func.__command_aliases__ = list(aliases) if aliases else []
            return func

        return decorator


class _OnCommand:
    """单命令装饰器入口，提供命令注册与分组构建能力。

    通过 `on_command` 单例使用：
    - `@on_command()` 注册单个命令。
    - `@on_command.group()` 创建命令分组。
    """

    def __call__(
        self,
        name: Optional[str] = None,
        *,
        description: str = "",
        aliases: Optional[Sequence[str]] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """注册单个命令的装饰器。

        Args:
            name: 命令名称。若为 None，则自动从函数名推导（去除 _cmd_ 或 _ 前缀）。
            description: 命令描述。
            aliases: 命令别名列表。

        Return:
            一个装饰器函数，用于标记目标函数。
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            node_name = name
            if node_name is None:
                node_name = func.__name__
                if node_name.startswith("_cmd_"):
                    node_name = node_name[5:]
                elif node_name.startswith("_"):
                    node_name = node_name[1:]
            func.__command_name__ = node_name
            func.__command_description__ = description
            func.__command_aliases__ = list(aliases) if aliases else []
            return func

        return decorator

    def group(
        self, name: Optional[str] = None, *, description: str = ""
    ) -> GroupBuilder:
        """创建一个命令分组构建器。

        Args:
            name: 分组名称。
            description: 分组描述。

        Return:
            GroupBuilder 实例，可用于进一步注册子命令。
        """
        return GroupBuilder(name=name, description=description)


on_command = _OnCommand()


# ==================== 上下文模型层 ====================


@dataclass
class CommandContext:
    """命令执行上下文，封装一次命令调用所需的原始信息。

    Args:
        RawText: 原始命令行文本。
        RawTokens: 经词法分析后的令牌列表。
        Source: 命令来源标识，例如 "console"、"qq" 等。
        metadata: 额外元数据字典，供扩展使用。
    """

    RawText: str
    RawTokens: List[str]
    Source: str
    metadata: Dict[str, Any] = field(default_factory=dict)


# ==================== 运行时模型 ====================


class CommandNode:
    """命令树节点，代表一个命令或命令分组。

    通过 Subcommands 字典维护子命令关系，形成树形命令结构。

    Args:
        Name: 节点名称。
        Description: 节点描述。
        Handler: 命令处理函数，若为 None 则表示该节点为中间分组节点。
        Doc: 处理函数的文档字符串，用于帮助信息展示。
        Aliases: 命令别名列表。
    """

    def __init__(
        self,
        Name: str,
        Description: str = "",
        *,
        Handler: Optional[Callable[..., Any]] = None,
        Doc: str = "",
        Aliases: Optional[Sequence[str]] = None,
    ):
        """初始化命令节点。

        Args:
            Name: 节点名称。
            Description: 节点描述。
            Handler: 命令处理函数。
            Doc: 文档字符串。
            Aliases: 命令别名列表。
        """
        self.Name = Name
        self.Description = Description
        self.Handler = Handler
        self.Doc = Doc
        self.Aliases: List[str] = list(Aliases) if Aliases else []
        self.Subcommands: Dict[str, CommandNode] = {}
        self.Parent: Optional[CommandNode] = None

    def AddSubcommand(self, node: CommandNode) -> CommandNode:
        """添加子命令节点，并自动建立父子关系。

        同时会为节点名称中的连字符 "-" 生成下划线 "_" 的别名，
        并注册节点自定义 Aliases 中声明的所有别名，以支持多种风格的命令输入。

        Args:
            node: 待添加的子命令节点。

        Return:
            当前节点自身，支持链式调用。
        """
        node.Parent = self
        self.Subcommands[node.Name] = node

        # 自动别名：连字符与下划线互换
        alt = node.Name.replace("-", "_")
        if alt != node.Name and alt not in self.Subcommands:
            self.Subcommands[alt] = node

        alt2 = node.Name.replace("_", "-")
        if alt2 != node.Name and alt2 not in self.Subcommands:
            self.Subcommands[alt2] = node

        # 注册用户自定义别名
        for alias in node.Aliases:
            if alias and alias not in self.Subcommands:
                self.Subcommands[alias] = node

        return self

    def GetCommandPath(self) -> List[str]:
        """获取从根节点到当前节点的完整路径。

        Return:
            由各级节点名称组成的列表，从根到当前节点顺序排列。
        """
        path, cur = [], self
        while cur:
            path.append(cur.Name)
            cur = cur.Parent
        return list(reversed(path))


# ==================== 词法层 ====================


class CommandLexer:
    """命令词法分析器，负责将原始命令行文本拆分为令牌列表。

    支持双引号、单引号包裹的字符串，以及反斜杠转义。
    """

    TokenPattern = re.compile(
        r'(?:[^\s"\'\\]+|\\.)+' r'|"(?:[^"\\]|\\.)*"' r"|'(?:[^'\\]|\\.)*'", re.VERBOSE
    )

    @classmethod
    def Split(cls, text: str) -> List[str]:
        """将输入文本拆分为令牌列表。

        处理规则：
        - 按空白字符分割。
        - 支持 "..." 和 \'...\' 包裹的字符串（去除引号）。
        - 支持 \\\\, \\\", \\\' 的转义序列还原。

        Args:
            text: 原始命令行文本。

        Return:
            清洗后的令牌字符串列表。
        """
        tokens = cls.TokenPattern.findall(text)
        cleaned = []
        for tok in tokens:
            if (tok.startswith('"') and tok.endswith('"')) or (
                tok.startswith("'") and tok.endswith("'")
            ):
                tok = tok[1:-1]
            tok = tok.replace("\\ ", " ").replace('\\"', '"').replace("\\'", "'")
            cleaned.append(tok)
        return cleaned


class ParseError(Exception):
    """命令解析或执行过程中出现的错误。"""

    pass


# ==================== 统一入口：CommandApp ====================


class CommandApp:
    """命令应用主入口，负责命令注册、路由分发与执行。

    支持层级命令结构，自动注入 CommandContext 与 raw 文本参数，
    并可根据处理函数签名推导帮助信息。

    Args:
        Name: 应用根节点名称。
        Description: 应用描述。
        parent: 父应用实例，用于子应用场景；根应用应为 None。
        colorize: 是否启用 ANSI 颜色输出。
    """

    def __init__(
        self,
        *,
        Name: str = "root",
        Description: str = "",
        parent: Optional[CommandApp] = None,
        colorize: bool = False,
    ):
        """初始化命令应用。

        Args:
            Name: 根节点名称。
            Description: 应用描述。
            parent: 父应用引用。
            colorize: 是否启用彩色输出。
        """
        self._node = CommandNode(Name=Name, Description=Description)
        self._parent = parent
        self._colorize = colorize
        self._help_aliases: set[str] = {"help", "--help", "-h"}
        self._c = (
            {
                "reset": "\x1b[0m",
                "bold": "\x1b[1m",
                "cyan": "\x1b[36m",
                "yellow": "\x1b[33m",
                "green": "\x1b[32m",
                "gray": "\x1b[90m",
                "red": "\x1b[31m",
            }
            if colorize
            else {
                k: ""
                for k in ("reset", "bold", "cyan", "yellow", "green", "gray", "red")
            }
        )

    def add_help_alias(self, *aliases: str) -> None:
        """为内置 help 触发词添加别名。

        当用户输入的剩余令牌匹配这些别名时，将显示对应节点的帮助信息。
        若已通过 `@on_command("help", aliases=[...])` 显式注册 help 命令，
        则显式命令优先，此内置别名仅在未命中显式命令时生效。

        Args:
            aliases: 要添加的 help 别名，例如 "h", "?"。
        """
        self._help_aliases.update(aliases)

    def register(
        self, func: Callable[..., Any], command_name: str | None = None
    ) -> None:
        """注册单个函数为命令或命令分组根节点。

        自动识别 `@on_command.group()` 标记的分组根节点，或普通命令节点。

        Args:
            func: 被装饰的处理函数。
            command_name: 强制指定的命令名称，若为 None 则读取函数上的元数据。
        """
        underlying = getattr(func, "__func__", func)

        if getattr(underlying, "__command_is_group_root__", False):
            group_name = getattr(underlying, "__command_group_name__")
            group_desc = getattr(underlying, "__command_group_description__", "")
            cmd_desc = getattr(underlying, "__command_description__", group_desc)
            aliases = getattr(underlying, "__command_aliases__", [])

            node = CommandNode(
                Name=group_name,
                Description=cmd_desc,
                Handler=func,
                Doc=inspect.getdoc(underlying) or "",
                Aliases=aliases,
            )
            self._node.AddSubcommand(node)
            return

        cmd_name = command_name or getattr(underlying, "__command_name__", None)
        if cmd_name is None:
            raise ValueError(f"{func!r} 未被 @on_command 或 GroupBuilder 装饰")

        cmd_desc = getattr(underlying, "__command_description__", "")
        aliases = getattr(underlying, "__command_aliases__", [])

        node = CommandNode(
            Name=cmd_name,
            Description=cmd_desc,
            Handler=func,
            Doc=inspect.getdoc(underlying) or "",
            Aliases=aliases,
        )
        self._node.AddSubcommand(node)

    @property
    def node(self) -> CommandNode:
        """获取根命令节点。

        Return:
            根 CommandNode 实例。
        """
        return self._node

    def register_instance(self, instance: Any) -> None:
        """扫描实例上的所有方法，自动注册为命令或命令分组。

        注册规则：
        - 带有 `__command_name__` 或 `__command_is_group_root__` 标记的方法。
        - 名称以 `_cmd_` 开头的方法。
        - 分组根节点优先注册，随后将其子命令挂载到对应分组下。

        Args:
            instance: 包含命令方法的类实例。
        """
        candidates: List[tuple[str, Callable[..., Any]]] = []
        for attr_name in dir(instance):
            if attr_name.startswith("__"):
                continue
            try:
                member = inspect.getattr_static(instance, attr_name)
            except AttributeError:
                continue
            if not inspect.isfunction(member):
                continue

            is_marked = hasattr(member, "__command_name__") or hasattr(
                member, "__command_is_group_root__"
            )
            is_prefixed = attr_name.startswith("_cmd_")

            if is_marked or is_prefixed:
                bound = member.__get__(instance, instance.__class__)
                candidates.append((attr_name, bound))

        groups: Dict[str, CommandNode] = {}
        for attr_name, bound in candidates:
            underlying = getattr(bound, "__func__", bound)
            if not getattr(underlying, "__command_is_group_root__", False):
                continue

            group_name = getattr(underlying, "__command_group_name__")
            group_desc = getattr(underlying, "__command_group_description__", "")
            cmd_desc = getattr(underlying, "__command_description__", group_desc)
            aliases = getattr(underlying, "__command_aliases__", [])

            node = CommandNode(
                Name=group_name,
                Description=cmd_desc,
                Handler=bound,
                Doc=inspect.getdoc(underlying) or "",
                Aliases=aliases,
            )
            self._node.AddSubcommand(node)
            groups[group_name] = node

        for attr_name, bound in candidates:
            underlying = getattr(bound, "__func__", bound)
            if getattr(underlying, "__command_is_group_root__", False):
                continue

            cmd_name = getattr(underlying, "__command_name__", None)
            if cmd_name is None and attr_name.startswith("_cmd_"):
                cmd_name = attr_name[5:]
            if cmd_name is None:
                cmd_name = attr_name

            cmd_desc = getattr(underlying, "__command_description__", "")
            if not cmd_desc:
                doc = inspect.getdoc(underlying)
                if doc:
                    cmd_desc = doc.strip().splitlines()[0]

            group_name = getattr(underlying, "__command_group__", None)
            aliases = getattr(underlying, "__command_aliases__", [])

            node = CommandNode(
                Name=cmd_name,
                Description=cmd_desc,
                Handler=bound,
                Doc=inspect.getdoc(underlying) or "",
                Aliases=aliases,
            )

            if group_name and group_name in groups:
                groups[group_name].AddSubcommand(node)
            else:
                self._node.AddSubcommand(node)

    async def execute(self, ctx: CommandContext) -> Any:
        """执行一次命令调用。

        路由逻辑：
        1. 若令牌为空，抛出 ParseError。
        2. 按令牌逐层匹配子命令树（支持别名）。
        3. 若剩余令牌匹配 help 别名集合，返回匹配到的节点的帮助信息。
        4. 若匹配到的节点无处理函数，返回帮助信息。
        5. 根据处理函数签名注入参数（ctx、raw、其余默认值参数），并调用处理函数。

        Args:
            ctx: 命令执行上下文。

        Return:
            处理函数的返回值。

        Raises:
            RuntimeError: 若当前实例不是根应用时调用。
            ParseError: 命令为空、参数缺少默认值，或其他解析错误。
        """
        if self._parent is not None:
            raise RuntimeError("Only root CommandApp can execute.")

        tokens = ctx.RawTokens
        if not tokens:
            raise ParseError("Empty command")

        node = self._node
        idx = 0
        while idx < len(tokens) and tokens[idx] in node.Subcommands:
            node = node.Subcommands[tokens[idx]]
            idx += 1

        remaining = tokens[idx:]
        raw_text = " ".join(remaining)

        if remaining and remaining[0] in self._help_aliases:
            return self._format_help(node)

        if node.Handler is None:
            return self._format_help(node)

        sig = inspect.signature(node.Handler)
        params = list(sig.parameters.items())
        kwargs: Dict[str, Any] = {}

        if len(params) > 0:
            name0, _ = params[0]
            kwargs[name0] = ctx
            params = params[1:]

        if len(params) > 0:
            name1, _ = params[0]
            kwargs[name1] = raw_text
            params = params[1:]

        for name, param in params:
            if param.default is inspect.Parameter.empty:
                raise ParseError(
                    f"Command '{node.Name}' parameter '{name}' has no default value. "
                    f"Only the first two parameters (ctx, raw) are injected by the framework."
                )
            kwargs[name] = param.default

        bound = sig.bind(**kwargs)
        bound.apply_defaults()

        if self._is_async(node.Handler):
            return await node.Handler(*bound.args, **bound.kwargs)
        return node.Handler(*bound.args, **bound.kwargs)

    async def run(self, command_line: str, source: str) -> Any:
        """便捷方法：从原始命令行字符串直接构建上下文并执行。

        Args:
            command_line: 原始命令行文本。
            source: 命令来源标识。

        Return:
            命令处理函数的返回值。
        """
        tokens = CommandLexer.Split(command_line)
        ctx = CommandContext(
            RawText=command_line,
            RawTokens=tokens,
            Source=source,
        )
        return await self.execute(ctx)

    @staticmethod
    def _is_async(handler: Callable[..., Any]) -> bool:
        """判断处理函数是否为异步函数（协程）。

        Args:
            handler: 待检测的函数。

        Return:
            若为协程函数则返回 True，否则返回 False。
        """
        if inspect.iscoroutinefunction(handler):
            return True
        if hasattr(handler, "__func__"):
            return inspect.iscoroutinefunction(handler.__func__)  # type: ignore
        return False

    # ==================== Help 格式化（Mirai 风格）====================

    def _format_help(self, node: CommandNode) -> str:
        """格式化指定节点的帮助信息，输出 Mirai 风格的文本。

        包含 Usage、描述、文档字符串及子命令列表（同行显示别名）。

        Args:
            node: 目标命令节点。

        Return:
            格式化后的帮助文本字符串。
        """
        lines: List[str] = []
        C = self._c

        # Usage
        path = node.GetCommandPath()
        display_path = path[1:] if len(path) > 1 else []
        cmd_path = " ".join(display_path)

        if node.Handler:
            usage = self._format_usage(node)
        else:
            usage = f"{cmd_path} <command>" if cmd_path else "<command>"

        lines.append(
            f"{C['bold']}{C['cyan']}Usage:{C['reset']} "
            f"{C['bold']}{usage}{C['reset']}"
        )

        # 别名展示（仅当前节点自身）
        if node.Aliases:
            alias_str = ", ".join(node.Aliases)
            lines.append(
                f"{C['bold']}{C['gray']}Aliases:{C['reset']} "
                f"{C['gray']}{alias_str}{C['reset']}"
            )

        doc = (node.Doc or "").strip()
        if doc and doc != (node.Description or "").strip():
            lines.append(f"\n{C['gray']}{node.Name}{C['reset']}")
            lines.append(f"\n{doc}")

        elif node.Description:
            lines.append(f"\n{node.Description.strip()}")

        if node.Subcommands:
            lines.append(f"\n{C['bold']}{C['yellow']}Commands:{C['reset']}")

            # 反向映射：CommandNode -> 所有能触发它的名称（主名+别名）
            node_names: Dict[CommandNode, List[str]] = {}
            for name, sub in node.Subcommands.items():
                node_names.setdefault(sub, []).append(name)

            for sub, names in node_names.items():
                # 去重排序：主名在前，其余按字典序
                unique_names: List[str] = []
                if sub.Name in names:
                    unique_names.append(sub.Name)
                for n in sorted(names):
                    if n != sub.Name and n not in unique_names:
                        unique_names.append(n)

                names_str = ", ".join(unique_names)
                desc = sub.Description.strip() if sub.Description else ""

                usage_hint = self._format_usage(sub, brief=True)
                if usage_hint:
                    cmd_line = f"{names_str} {usage_hint}"
                else:
                    cmd_line = names_str

                lines.append(
                    f"  {C['bold']}{C['green']}{cmd_line:<30}{C['reset']} {desc}"
                )

        return "\n".join(lines)

    def _format_usage(self, node: CommandNode, brief: bool = False) -> str:
        """根据 Handler 签名推导 Mirai 风格用法字符串。

        框架注入约定：
        - 第1参数：CommandContext（不显示）
        - 第2参数：raw 字符串（显示为 [raw]）
        - 其余参数：必须有默认值（显示为 [name=default]）

        Args:
            node: 目标命令节点。
            brief: 若为 True，仅返回参数部分，不包含命令路径前缀。

        Return:
            用法字符串。
        """
        if not node.Handler:
            if brief:
                return "<command>"
            path = " ".join(node.GetCommandPath()[1:])
            return f"{path} <command>" if path else "<command>"

        path = " ".join(node.GetCommandPath()[1:])
        sig = inspect.signature(node.Handler)
        params = list(sig.parameters.items())

        # 跳过 self/cls
        idx = 0
        if params and params[0][0] in ("self", "cls"):
            idx += 1

        # 跳过 ctx（框架注入，不显示）
        if len(params) > idx:
            idx += 1

        parts: List[str] = []

        # raw 参数（第2个注入参数）
        if len(params) > idx:
            raw_name, raw_param = params[idx]
            if raw_param.default is inspect.Parameter.empty:
                parts.append(f"<{raw_name}>")
            else:
                parts.append(f"[{raw_name}]")
            idx += 1

        # 其余参数：框架要求必须有默认值，显示为 [name=default]
        for i in range(idx, len(params)):
            name, param = params[i]
            if param.default is not inspect.Parameter.empty:
                default = param.default
                if isinstance(default, str) and default:
                    parts.append(f'[{name}="{default}"]')
                elif default is None or default == "":
                    parts.append(f"[{name}]")
                else:
                    parts.append(f"[{name}={default}]")
            else:
                parts.append(f"<{name}>")

        if brief:
            return " ".join(parts)

        full = ([path] if path else []) + parts
        return " ".join(full) if full else (path or "")


# ==================== 适配器层 ====================


async def console_adapter(app: CommandApp):
    """控制台适配器，提供交互式命令行界面。

    持续读取用户输入，通过 app.execute 执行命令，并输出结果。
    支持 `help` 查看帮助，`exit` / `quit` 退出，以及 `/` 前缀的命令。

    Args:
        app: 已注册好命令的 CommandApp 根实例。
    """
    print(f"Welcome to {app._node.Name}! Type 'help' or 'exit'.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if line in ("exit", "quit"):
            break
        if not line:
            continue

        if line.startswith("/"):
            line = line[1:]

        tokens = CommandLexer.Split(line)
        ctx = CommandContext(
            RawText=line,
            RawTokens=tokens,
            Source="console",
        )

        try:
            result = await app.execute(ctx)
            if result is not None:
                print(result)
        except ParseError as e:
            print(f"ParseError: {e}")
