from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple, get_type_hints

# ==================== 运行时模型层 ====================


class Arity(Enum):
    Flag = auto()
    Required = auto()
    ZeroOrMore = auto()
    OneOrMore = auto()


@dataclass
class Argument:
    Name: str
    Aliases: Tuple[str, ...] = ()
    Arity: Arity = Arity.Required
    Type: Callable[[str], Any] = str
    Default: Any = None
    Help: str = ""
    Required: bool = False

    @property
    def DisplayNames(self) -> str:
        return ", ".join(self.Aliases) if self.Aliases else self.Name

    @property
    def PrimaryAlias(self) -> str:
        """返回主别名（最长的那个，通常是 --long-form）"""
        if not self.Aliases:
            return self.Name
        return max(self.Aliases, key=len)


@dataclass
class ParseResult:
    CommandPath: List[str] = field(default_factory=list)
    PositionalArgs: List[Any] = field(default_factory=list)
    NamedArgs: Dict[str, Any] = field(default_factory=dict)
    Flags: Dict[str, bool] = field(default_factory=dict)


class CommandNode:
    def __init__(
        self,
        Name: str,
        Description: str = "",
        *,
        Handler: Optional[Callable[..., Any]] = None,
        Doc: str = "",
    ):
        self.Name = Name
        self.Description = Description  # 单行摘要，用于列表/概览，用户显式设置
        self.Handler = Handler
        self.Doc = Doc  # 完整文档字符串，描述命令用途
        self.Arguments: Dict[str, Argument] = {}
        self.Positional: List[Argument] = []
        self.Subcommands: Dict[str, CommandNode] = {}
        self.Parent: Optional[CommandNode] = None

    def AddArgument(self, arg: Argument) -> CommandNode:
        self.Arguments[arg.Name] = arg
        return self

    def AddPositional(self, arg: Argument) -> CommandNode:
        self.Positional.append(arg)
        return self

    def AddSubcommand(self, node: CommandNode) -> CommandNode:
        node.Parent = self
        self.Subcommands[node.Name] = node
        return self

    def GetCommandPath(self) -> List[str]:
        path, cur = [], self
        while cur:
            path.append(cur.Name)
            cur = cur.Parent
        return list(reversed(path))


# ==================== 词法/语法层 ====================


class CommandLexer:
    TokenPattern = re.compile(
        r'(?:[^\s"\'\\]+|\\.)+' r'|"(?:[^"\\]|\\.)*"' r"|'(?:[^'\\]|\\.)*'", re.VERBOSE
    )

    @classmethod
    def Split(cls, text: str) -> List[str]:
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
    pass


class _HelpRequest(Exception):
    def __init__(self, node: CommandNode):
        self.Node = node


class CommandParser:
    def __init__(self, root: CommandNode):
        self.Root = root

    def Parse(self, tokens: List[str]) -> Tuple[CommandNode, ParseResult]:
        if not tokens:
            raise ParseError("Empty command")

        current, result, idx = self.Root, ParseResult(), 0

        while idx < len(tokens) and tokens[idx] in current.Subcommands:
            current = current.Subcommands[tokens[idx]]
            result.CommandPath.append(tokens[idx])
            idx += 1

        consumed_positional = 0
        while idx < len(tokens):
            token = tokens[idx]

            if token in ("--help", "-h"):
                raise _HelpRequest(current)

            if token.startswith("--") and "=" in token:
                key, _, val = token.partition("=")
                idx = self._ConsumeNamed(current, result, tokens, key, val, idx)
                idx += 1
                continue

            if token.startswith("--"):
                idx = self._ConsumeNamed(current, result, tokens, token, None, idx)
                idx += 1
                continue

            if token.startswith("-") and len(token) > 2 and not token.startswith("--"):
                tokens = tokens[:idx] + [f"-{c}" for c in token[1:]] + tokens[idx + 1 :]
                continue

            if token.startswith("-") and len(token) == 2:
                idx = self._ConsumeNamed(current, result, tokens, token, None, idx)
                idx += 1
                continue

            if consumed_positional < len(current.Positional):
                arg_def = current.Positional[consumed_positional]
                result.PositionalArgs.append(self._Convert(arg_def, token))
                consumed_positional += 1
                idx += 1
            else:
                raise ParseError(f"Unexpected positional argument: {token}")

        self._Validate(current, result)
        return current, result

    def _ConsumeNamed(self, node, result, tokens, key, inline, idx):
        arg_def = None
        for a in node.Arguments.values():
            if key == a.Name or key in a.Aliases:
                arg_def = a
                break
        if not arg_def:
            raise ParseError(f"Unknown argument: {key}")

        if arg_def.Arity == Arity.Flag:
            result.Flags[arg_def.Name] = True
            return idx

        if inline is not None:
            val = inline
        else:
            if idx + 1 < len(tokens):
                nxt = tokens[idx + 1]
                is_opt = nxt.startswith("-") and any(
                    nxt == x.Name or nxt in x.Aliases for x in node.Arguments.values()
                )
                if not is_opt:
                    val = nxt
                    idx += 1
                else:
                    raise ParseError(f"Argument {key} requires a value")
            else:
                raise ParseError(f"Argument {key} requires a value")

        converted = self._Convert(arg_def, val)
        if arg_def.Arity in (Arity.ZeroOrMore, Arity.OneOrMore):
            result.NamedArgs.setdefault(arg_def.Name, []).append(converted)
        else:
            result.NamedArgs[arg_def.Name] = converted
        return idx

    def _Convert(self, arg_def, raw):
        try:
            return arg_def.Type(raw)
        except Exception as e:
            raise ParseError(f"Invalid value '{raw}' for {arg_def.Name}: {e}")

    def _Validate(self, node, result):
        for name, arg in node.Arguments.items():
            if (
                arg.Required
                and name not in result.NamedArgs
                and name not in result.Flags
            ):
                raise ParseError(f"Missing required argument: {arg.DisplayNames}")


# ==================== 统一入口：CommandApp ====================


def _bool_type(s: str) -> bool:
    return s.lower() in ("true", "1", "yes", "on", "y")


class CommandApp:
    def __init__(
        self,
        *,
        Name: str = "root",
        Description: str = "",
        parent: Optional[CommandApp] = None,
    ):
        self._node = CommandNode(Name=Name, Description=Description)
        self._parent = parent
        self._parser: Optional[CommandParser] = None

    def command(self, name: Optional[str] = None, description: Optional[str] = None):
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            node = self._build_node(func, name, description)
            self._node.AddSubcommand(node)
            return func

        return decorator

    def group(self, name: str, description: str = "") -> CommandApp:
        sub = CommandApp(Name=name, Description=description, parent=self)
        self._node.AddSubcommand(sub._node)
        return sub

    async def run(self, command_line: str) -> Any:
        if self._parent is not None:
            raise RuntimeError("Only root CommandApp can run.")

        if self._parser is None:
            self._parser = CommandParser(self._node)

        tokens = CommandLexer.Split(command_line)
        if not tokens:
            raise ParseError("Empty command")

        try:
            node, result = self._parser.Parse(tokens)
        except _HelpRequest as e:
            return self._format_help(e.Node)

        if node.Handler is None:
            raise ParseError(
                f"Command '{' '.join(node.GetCommandPath())}' requires a subcommand."
            )

        bound = self._bind(node.Handler, result)

        if self._is_async(node.Handler):
            return await node.Handler(*bound.args, **bound.kwargs)
        return node.Handler(*bound.args, **bound.kwargs)

    # ----- 内部实现 -----

    def _build_node(self, func, name, description) -> CommandNode:
        node_name = name or func.__name__.lower().replace("_", "-")
        full_doc = inspect.getdoc(func) or ""
        # Description 仅来自装饰器参数；用户不传则留空，框架不主动注入
        desc = description or ""

        node = CommandNode(Name=node_name, Description=desc, Handler=func, Doc=full_doc)

        sig = inspect.signature(func)
        hints = get_type_hints(func)
        is_method = inspect.ismethod(func)

        for i, (pname, param) in enumerate(sig.parameters.items()):
            if is_method and i == 0:
                continue

            hint = hints.get(pname, str)
            has_default = param.default is not inspect.Parameter.empty
            default = param.default if has_default else None
            required = not has_default

            # 1) 位置参数
            if (
                param.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
                and required
            ):
                node.AddPositional(
                    Argument(
                        Name=pname,
                        Type=hint if hint is not inspect.Parameter.empty else str,
                        Required=True,
                    )
                )
                continue

            # 2) Flag
            if hint is bool and has_default and default is False:
                node.AddArgument(
                    Argument(
                        Name=pname,
                        Aliases=(f"--{pname.replace('_', '-')}",),
                        Arity=Arity.Flag,
                    )
                )
                continue

            # 3) 选项
            if param.kind in (
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                long_name = f"--{pname.replace('_', '-')}"
                aliases: List[str] = [long_name]
                if len(pname) > 1:
                    aliases.insert(0, f"-{pname[0]}")

                converter = (
                    _bool_type
                    if hint is bool
                    else (hint if hint is not inspect.Parameter.empty else str)
                )

                node.AddArgument(
                    Argument(
                        Name=pname,
                        Aliases=tuple(aliases),
                        Type=converter,
                        Default=default,
                        Required=required,
                    )
                )

        return node

    def _bind(self, handler, result: ParseResult):
        sig = inspect.signature(handler)
        bound_args: Dict[str, Any] = {}
        pos_queue = list(result.PositionalArgs)

        for name, param in sig.parameters.items():
            if name in result.NamedArgs:
                bound_args[name] = result.NamedArgs[name]
                continue
            if name in result.Flags:
                bound_args[name] = result.Flags[name]
                continue

            if param.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                if pos_queue:
                    bound_args[name] = pos_queue.pop(0)
                    continue

            if param.default is not inspect.Parameter.empty:
                continue

            if param.kind == inspect.Parameter.VAR_POSITIONAL:
                bound_args[name] = tuple(pos_queue)
                pos_queue.clear()
                continue

            if param.kind == inspect.Parameter.VAR_KEYWORD:
                extra = {
                    k: v
                    for k, v in {**result.NamedArgs, **result.Flags}.items()
                    if k not in sig.parameters
                }
                bound_args[name] = extra
                continue

        try:
            b = sig.bind(**bound_args)
            b.apply_defaults()
            return b
        except TypeError as e:
            raise ParseError(f"Argument binding failed: {e}")

    @staticmethod
    def _is_async(handler: Callable[..., Any]) -> bool:
        if inspect.iscoroutinefunction(handler):
            return True
        if hasattr(handler, "__func__"):
            return inspect.iscoroutinefunction(handler.__func__)
        return False

    def _format_help(self, node: CommandNode) -> str:
        """
        生成 Debian 风格的紧凑帮助文本。

        格式：
            Usage: <path> <args_signature>

            <单行 Description>

            Arguments:
              <name>           <help>

            Options:
              <aliases>        <help> (default: <val>)

            Commands:
              <name>           <单行 Description>
        """
        lines: List[str] = []

        # ---- Usage 行（自动生成参数签名）----
        parts = ["Usage:", " ".join(node.GetCommandPath())]

        # 位置参数占位符
        for p in node.Positional:
            parts.append(f"<{p.Name}>")

        # 如果有选项，统一显示 [options] 或逐个显示
        if node.Arguments:
            # 逐个显示更精确
            for a in node.Arguments.values():
                if a.Arity == Arity.Flag:
                    parts.append(f"[{a.PrimaryAlias}]")
                elif a.Required:
                    parts.append(f"{a.PrimaryAlias} <{a.Name}>")
                else:
                    parts.append(f"[{a.PrimaryAlias} <{a.Name}>]")

        lines.append(" ".join(parts))

        # ---- 单行 Description（用户显式传入）----
        if node.Description:
            lines.append(f"\n{node.Description.strip()}")

        # ---- Arguments ----
        if node.Positional:
            lines.append("\nArguments:")
            for a in node.Positional:
                req = " (required)"
                lines.append(f"  {a.Name:<18} {req}")

        # ---- Options ----
        if node.Arguments:
            lines.append("\nOptions:")
            for a in node.Arguments.values():
                meta = ""
                if a.Arity != Arity.Flag:
                    if a.Required:
                        meta = " (required)"
                    elif a.Default is not None:
                        meta = f" (default: {a.Default})"
                lines.append(f"  {a.DisplayNames:<18}{meta}")

        # ---- Subcommands ----
        if node.Subcommands:
            lines.append("\nCommands:")
            for name, sub in node.Subcommands.items():
                # 只显示单行 Description
                desc = sub.Description.strip() if sub.Description else ""
                lines.append(f"  {name:<18} {desc}")

        return "\n".join(lines)


# ==================== 使用示例 ====================


async def main():
    app = CommandApp(Name="kubectl", Description="Kubernetes CLI")

    @app.command(description="部署容器镜像")
    async def deploy(
        image: str,
        *,
        replicas: int = 1,
        namespace: str = "default",
        dry_run: bool = False,
    ):
        """
        部署容器镜像到集群。

        根据指定镜像创建或更新 Deployment。支持指定副本数、命名空间
        以及预览模式。
        """
        mode = "[DRY-RUN] " if dry_run else ""
        return f"{mode}Deploying {image} x{replicas} to '{namespace}'"

    @app.command(description="查看集群状态")
    def status():
        """查看当前集群各组件运行状态"""
        return "All systems operational"

    cfg = app.group("config", description="配置管理")

    @cfg.command(description="读取配置项")
    def get(key: str):
        """读取指定配置键的值"""
        return f"Config {key} = <value>"

    @cfg.command(description="设置配置项")
    def set(key: str, value: str):
        """设置指定配置键的值"""
        return f"Config {key} set to {value}"

    # 测试
    tests = [
        ("deploy nginx:latest --replicas 3", "正常执行"),
        ("deploy --help", "帮助：紧凑格式，单行描述"),
        ("deploy", "缺少参数 → 抛 ParseError"),
        ("--help", "根命令帮助：展示子命令列表及 Description"),
    ]

    for cmd, note in tests:
        print(f"$ {cmd}  # {note}")
        try:
            result = await app.run(cmd)
            print(result)
        except ParseError as e:
            print(f"ParseError: {e}")
        print()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
