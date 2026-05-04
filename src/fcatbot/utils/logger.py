# -------------------------
# @Author       : Fish-LP fish.zh@outlook.com
# @Date         : 2025-02-12 13:41:02
# @LastEditors  : Fish-LP fish.zh@outlook.com
# @LastEditTime : 2025-06-22 21:51:42
# @Description  : 日志格式化 (Modernized + PascalCase)
# @Copyright (c) 2025 by Fish-LP, MIT 使用许可协议
# -------------------------

from __future__ import annotations

import json
import logging
import os
import re
import warnings
from contextvars import ContextVar
from dataclasses import dataclass, field
from logging.handlers import QueueListener, TimedRotatingFileHandler
from queue import Queue
from typing import Any, Dict, List, Optional, Union, cast

from fcatbot.utils.color import Color

try:
    from tqdm import tqdm as tqdm_original  # type: ignore
except ImportError:
    tqdm_original = None

__author__ = "Fish-LP <Fish.zh@outlook.com>"
__version__ = "3.0.0"

# 上下文变量（PascalCase 模块常量）
RequestId: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
TraceId: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def set_request_id(rid: str) -> None:
    RequestId.set(rid)


def set_trace_id(tid: str) -> None:
    TraceId.set(tid)


@dataclass
class LogConfig:
    console_level: Union[int, str] = "INFO"
    file_level: Union[int, str] = "DEBUG"
    log_dir: str = "./logs"
    file_name: str = "bot.log"
    backup_count: int = 7
    use_color: bool = True
    use_json: bool = False
    utc: bool = True
    redirect_rules: Dict[str, str] = field(default_factory=dict)
    queue_size: int = 1000

    def __post_init__(self) -> None:
        if isinstance(self.console_level, str):
            self.console_level = self._parse_level(self.console_level, logging.INFO)
        if isinstance(self.file_level, str):
            self.file_level = self._parse_level(self.file_level, logging.DEBUG)
        if self.backup_count < 0:
            raise ValueError("backup_count 不能为负数")

    @staticmethod
    def _parse_level(level: str, default: int) -> int:
        val = getattr(logging, level.upper(), None)
        if not isinstance(val, int):
            warnings.warn(f"日志级别 '{level}' 无效，使用默认值。")
            return default
        return val

    @classmethod
    def from_env(cls) -> LogConfig:
        redirect = os.getenv("LOG_REDIRECT_RULES", "{}")
        try:
            redirect_rules = json.loads(redirect)
        except json.JSONDecodeError:
            redirect_rules = {}
            warnings.warn("LOG_REDIRECT_RULES 格式无效，使用空规则")

        return cls(
            console_level=os.getenv("LOG_LEVEL", "INFO"),
            file_level=os.getenv("FILE_LOG_LEVEL", "DEBUG"),
            log_dir=os.getenv("LOG_FILE_PATH", "./logs"),
            file_name=os.getenv("LOG_FILE_NAME", "bot.log"),
            backup_count=int(os.getenv("BACKUP_COUNT", "7")),
            use_json=os.getenv("LOG_JSON_FORMAT", "false").lower() == "true",
            redirect_rules=redirect_rules,
        )


# ---------- tqdm 扩展 ----------
if tqdm_original is not None:

    class tqdm(tqdm_original):
        _StyleMap = {
            "BLACK": Color.Black,
            "RED": Color.Red,
            "GREEN": Color.Green,
            "YELLOW": Color.Yellow,
            "BLUE": Color.Blue,
            "MAGENTA": Color.Magenta,
            "CYAN": Color.Cyan,
            "WHITE": Color.White,
        }

        def __init__(self, *args, **kwargs):
            self._custom_colour = kwargs.get("colour", "GREEN")
            kwargs.setdefault(
                "bar_format",
                f"{Color.Cyan}{{desc}}{Color.Reset} "
                f"{Color.White}{{percentage:3.0f}}%{Color.Reset} "
                f"{Color.Gray}[{{n_fmt}}]{Color.Reset}"
                f"{Color.White}|{{bar:20}}|{Color.Reset}"
                f"{Color.Blue}[{{elapsed}}]{Color.Reset}",
            )
            kwargs.setdefault("ncols", 80)
            kwargs.setdefault("colour", None)
            super().__init__(*args, **kwargs)
            self.colour = self._custom_colour

        @property
        def colour(self):
            return self._colour

        @colour.setter
        def colour(self, color):
            if not color:
                color = "GREEN"
            color_upper = color.upper()
            valid_color = self._StyleMap.get(color_upper, "GREEN")
            self._colour = color_upper
            if self.desc:
                self.desc = f"{getattr(Color, valid_color)}{self.desc}{Color.Reset}"


# ---------- 格式化器与过滤器 ----------
class _AnsiStripper:
    AnsiRe = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    @classmethod
    def strip(cls, text: str) -> str:
        return cls.AnsiRe.sub("", text)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = RequestId.get() or ""
        record.trace_id = TraceId.get() or ""
        return True


class DynamicFormatter(logging.Formatter):
    LevelColors = {
        "DEBUG": Color.Cyan,
        "INFO": Color.Green,
        "WARNING": Color.Yellow,
        "ERROR": Color.Red,
        "CRITICAL": Color.Magenta + Color.Bold,
    }

    def __init__(
        self,
        fmt_dict: Dict[str, str],
        datefmt: Optional[str] = None,
        use_color: bool = True,
        strip_ansi_for_file: bool = False,
    ):
        super().__init__(datefmt=datefmt)
        self.use_color = use_color
        self.strip_ansi = strip_ansi_for_file
        self._formatters: Dict[str, logging.Formatter] = {
            level: logging.Formatter(fmt, datefmt=datefmt)
            for level, fmt in fmt_dict.items()
        }
        self._default = next(iter(self._formatters.values()))

    def format(self, record: logging.LogRecord) -> str:
        extras: Dict[str, Any] = {}
        if self.use_color:
            color = self.LevelColors.get(record.levelname, "")
            extras["colored_levelname"] = f"{color}{record.levelname:8}{Color.Reset}"
            extras["colored_name"] = f"{Color.Magenta}{record.name}{Color.Reset}"
        else:
            extras["colored_levelname"] = record.levelname
            extras["colored_name"] = record.name

        original_dict = record.__dict__.copy()
        record.__dict__.update(extras)

        formatter = self._formatters.get(record.levelname, self._default)
        try:
            msg = formatter.format(record)
        finally:
            record.__dict__ = original_dict

        if self.strip_ansi:
            msg = _AnsiStripper.strip(msg)
        return msg


class JsonFormatter(logging.Formatter):
    def __init__(
        self,
        fmt_dict: Optional[Dict[str, str]] = None,
        datefmt: Optional[str] = None,
        extra_fields: Optional[List[str]] = None,
    ):
        super().__init__(datefmt=datefmt)
        self.extra_fields = extra_fields or [
            "request_id",
            "trace_id",
            "funcName",
            "threadName",
        ]

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "filename": record.filename,
            "lineno": record.lineno,
        }
        for key in self.extra_fields:
            value = getattr(record, key, None)
            if value:
                log_obj[key] = value
        if hasattr(record, "extra"):
            log_obj.update(record.extra)  # type: ignore
        return json.dumps(log_obj, ensure_ascii=False, default=str)


# ---------- 格式模板 ----------
def _make_formats(use_color: bool) -> Dict[str, Dict[str, str]]:
    c = (
        Color
        if use_color
        else type("NoColor", (), {k: "" for k in dir(Color) if not k.startswith("_")})
    )  # type: ignore
    c = cast(Color, c)
    return {
        "console": {
            "DEBUG": (
                f"{c.Cyan}[%(asctime)s.%(msecs)s]{c.Reset} "
                f"{c.Blue}%(colored_levelname)-8s{c.Reset} "
                f"{c.Gray}[%(threadName)s|%(processName)s]{c.Reset} "
                f"{c.Magenta}%(colored_name)s{c.Reset} "
                f"{c.Yellow}%(filename)s:%(lineno)d %(funcName)s{c.Reset} "
                f"| %(message)s"
            ),
            "INFO": (
                f"{c.Cyan}[%(asctime)s]{c.Reset} "
                f"{c.Green}%(colored_levelname)-8s{c.Reset} "
                f"{c.Magenta}%(colored_name)s{c.Reset} ➜ %(message)s"
            ),
            "WARNING": (
                f"{c.Cyan}[%(asctime)s]{c.Reset} "
                f"{c.Yellow}%(colored_levelname)-8s{c.Reset} "
                f"{c.Magenta}%(colored_name)s{c.Reset} "
                f"{c.Yellow}➜{c.Reset} %(message)s"
            ),
            "ERROR": (
                f"{c.Cyan}[%(asctime)s]{c.Reset} "
                f"{c.Red}%(colored_levelname)-8s{c.Reset} "
                f"{c.Gray}[%(filename)s:%(lineno)d]{c.Reset} "
                f"{c.Magenta}%(colored_name)s{c.Reset} "
                f"{c.Red}➜{c.Reset} %(message)s"
            ),
            "CRITICAL": (
                f"{c.Cyan}[%(asctime)s]{c.Reset} "
                f"{c.Red}{c.Bold}%(colored_levelname)-8s{c.Reset} "
                f"{c.Gray}{{%(module)s}}{c.Reset} "
                f"{c.Magenta}[%(filename)s]{c.Reset} "
                f"{c.Magenta}%(colored_name)s{c.Reset}:{c.Magenta}%(lineno)d{c.Reset} "
                f"{c.Red}➜{c.Reset} %(message)s"
            ),
        },
        "file": {
            "DEBUG": "[%(asctime)s] %(levelname)-8s [%(threadName)s|%(processName)s] %(name)s (%(filename)s:%(funcName)s:%(lineno)d) | %(message)s",
            "INFO": "[%(asctime)s] %(levelname)-8s %(name)s ➜ %(message)s",
            "WARNING": "[%(asctime)s] %(levelname)-8s %(name)s ➜ %(message)s",
            "ERROR": "[%(asctime)s] %(levelname)-8s [%(filename)s]%(name)s:%(lineno)d ➜ %(message)s",
            "CRITICAL": "[%(asctime)s] %(levelname)-8s {%(module)s}[%(filename)s]%(name)s:%(lineno)d ➜ %(message)s",
        },
    }


# ---------- 核心安装函数 ----------
def setup_logging(config: Optional[LogConfig] = None) -> Optional[QueueListener]:
    if config is None:
        config = LogConfig.from_env()

    os.makedirs(config.log_dir, exist_ok=True)
    formats = _make_formats(use_color=config.use_color and Color._ColorEnabled)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console_fmt = DynamicFormatter(
        fmt_dict=formats["console"],
        datefmt="%H:%M:%S",
        use_color=config.use_color,
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(config.console_level)
    console_handler.setFormatter(console_fmt)
    console_handler.addFilter(ContextFilter())
    _replace_or_add_handler(root, logging.StreamHandler, console_handler)

    root_file_path = os.path.join(config.log_dir, config.file_name)
    if config.use_json:
        file_formatter: logging.Formatter = JsonFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    else:
        file_formatter = DynamicFormatter(
            fmt_dict=formats["file"],
            datefmt="%Y-%m-%d %H:%M:%S",
            use_color=False,
            strip_ansi_for_file=True,
        )

    file_handler = TimedRotatingFileHandler(
        filename=root_file_path,
        when="midnight",
        interval=1,
        backupCount=config.backup_count,
        encoding="utf-8",
        utc=config.utc,
    )
    file_handler.setLevel(config.file_level)
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(ContextFilter())
    _replace_or_add_handler(root, TimedRotatingFileHandler, file_handler)

    for logger_name, filename in config.redirect_rules.items():
        redirect_path = os.path.join(config.log_dir, filename)
        redirect_handler = TimedRotatingFileHandler(
            filename=redirect_path,
            when="midnight",
            interval=1,
            backupCount=config.backup_count,
            encoding="utf-8",
            utc=config.utc,
        )
        redirect_handler.setLevel(config.file_level)
        redirect_handler.setFormatter(file_formatter)
        redirect_handler.addFilter(ContextFilter())

        logger = logging.getLogger(logger_name)
        logger.setLevel(config.file_level)
        logger.handlers.clear()
        logger.addHandler(redirect_handler)
        logger.propagate = False

    if config.queue_size > 0:
        from logging.handlers import QueueHandler, QueueListener
        from queue import Queue

        log_queue: Queue = Queue(maxsize=config.queue_size)
        queue_handler = QueueHandler(log_queue)

        # 精确区分：FileHandler（文件日志）走后台线程，
        # StreamHandler（控制台）留在 root 同步输出，供 patch_stdout 捕获
        console_handlers: list[logging.Handler] = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        file_handlers: list[logging.Handler] = [
            h for h in root.handlers if isinstance(h, logging.FileHandler)
        ]

        root.handlers.clear()
        for h in console_handlers:
            root.handlers.append(h)
        root.handlers.append(queue_handler)

        listener = QueueListener(log_queue, *file_handlers, respect_handler_level=True)
        listener.start()
        return listener

    return None


def _replace_or_add_handler(
    logger: logging.Logger,
    handler_type: type,
    new_handler: logging.Handler,
) -> None:
    for i, h in enumerate(logger.handlers):
        if isinstance(h, handler_type):
            logger.handlers[i] = new_handler
            return
    logger.addHandler(new_handler)


def get_logger(
    name: str, extra: Optional[Dict[str, Any]] = None
) -> logging.LoggerAdapter:
    logger = logging.getLogger(name)
    if extra:
        return logging.LoggerAdapter(logger, extra)
    return logging.LoggerAdapter(logger, {})


# ---------- 示例 ----------
if __name__ == "__main__":
    Color.init()
    cfg = LogConfig(console_level="DEBUG", use_json=False)
    listener = setup_logging(cfg)

    log = get_logger("modern_logger")
    set_request_id("req-0426-001")
    set_trace_id("trace-abc-123")

    log.debug("调试信息，带文件位置")
    log.info("普通信息，简洁格式")
    log.warning("警告信息")
    log.error("错误信息")
    log.critical("严重错误")

    if listener:
        listener.stop()
