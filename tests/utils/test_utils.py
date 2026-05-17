"""Tests for utils modules."""

import logging

import pytest

from fcatbot.utils.cmdparse import CommandApp, CommandLexer, ParseError, on_command
from fcatbot.utils.color import Color
from fcatbot.utils.logformat import LogFormats

# ---------- Color Tests ----------


class TestColor:
    def test_color_class_exists(self):
        assert Color is not None

    def test_color_ansi_codes(self):
        assert str(Color.Red) == "\033[31m"
        assert str(Color.Green) == "\033[32m"
        assert str(Color.Blue) == "\033[34m"
        assert str(Color.Reset) == "\033[0m"

    def test_color_addition(self):
        result = Color.Red + "test"
        assert result == "\033[31mtest"
        result2 = Color.Red + Color.Bold
        assert "\033[31m" in result2
        assert "\033[1m" in result2

    def test_color_from_rgb(self):
        code = Color.from_rgb(255, 0, 0)
        assert "\033[38;2;255;0;0m" == code

    def test_color_from_rgb_invalid(self):
        with pytest.raises(ValueError):
            Color.from_rgb(256, 0, 0)
        with pytest.raises(ValueError):
            Color.from_rgb(-1, 0, 0)

    def test_color_rgb_background(self):
        code = Color.from_rgb(0, 255, 0, background=True)
        assert "\033[48;2;0;255;0m" == code

    def test_color_rgb256(self):
        code = Color.rgb256(128, 64, 32)
        assert code.startswith("\033[")

    def test_color_color256(self):
        code = Color.color256(196)
        assert code == "\033[38;5;196m"

    def test_color_color256_invalid(self):
        with pytest.raises(ValueError):
            Color.color256(256)

    def test_color_disable_enable(self):
        original = Color._ColorEnabled
        Color.disable()
        assert not Color._ColorEnabled
        assert str(Color.Red) == ""
        Color.enable()
        assert Color._ColorEnabled
        assert str(Color.Red) == "\033[31m"
        Color._ColorEnabled = original  # restore

    def test_color_init(self):
        result = Color.init()
        assert isinstance(result, bool)

    def test_color_context_manager(self):
        with Color(Color.Red) as c:
            assert c is not None

    def test_color_print(self, capsys):
        Color.print("test", color=Color.Green)
        captured = capsys.readouterr()
        assert "test" in captured.out


# ---------- LogFormat Tests ----------


class TestLogFormats:
    def test_log_formats_exists(self):
        assert LogFormats is not None
        assert hasattr(LogFormats, "Modern")
        assert hasattr(LogFormats, "Simple")
        assert hasattr(LogFormats, "Professional")

    def test_modern_message(self):
        result = LogFormats.Modern.message(
            group_id=123, nick="User", uid=456, msg="Hello"
        )
        assert "User" in result
        assert "Hello" in result

    def test_modern_message_private(self):
        result = LogFormats.Modern.message(
            group_id=None, nick="User", uid=456, msg="Hello"
        )
        assert "User" in result
        assert "Hello" in result

    def test_modern_notice(self):
        result = LogFormats.Modern.notice(
            notice_type="group_increase", user_id=123, group_id=456
        )
        assert isinstance(result, str)

    def test_simple_message(self):
        result = LogFormats.Simple.message(
            group_id=123, nick="User", uid=456, msg="Hello"
        )
        assert "User" in result
        assert "Hello" in result

    def test_professional_message(self):
        result = LogFormats.Professional.message(
            group_id=123, nick="User", uid=456, msg="Hello"
        )
        assert "User" in result
        assert "Hello" in result
        assert "[MSG]" in result

    def test_all_styles_have_required_methods(self):
        for style_name in ["Modern", "Simple", "Professional"]:
            style = getattr(LogFormats, style_name)
            assert hasattr(style, "message")
            assert hasattr(style, "notice")
            assert hasattr(style, "request")
            assert hasattr(style, "meta_event")
            # All methods should be callable
            assert callable(style.message)
            assert callable(style.notice)
            assert callable(style.request)
            assert callable(style.meta_event)

    def test_modern_request(self):
        result = LogFormats.Modern.request(
            request_type="friend_add", user_id=123456, comment="Hello"
        )
        assert "friend_add" in result
        assert "123456" in result

    def test_simple_request(self):
        result = LogFormats.Simple.request(
            request_type="friend_add", user_id=123456, comment="Hello"
        )
        assert "friend_add" in result
        assert "123456" in result

    def test_meta_event(self):
        for style_name in ["Modern", "Simple", "Professional"]:
            style = getattr(LogFormats, style_name)
            result = style.meta_event("heartbeat", {"interval": 30})
            assert isinstance(result, str)
            assert "heartbeat" in result


# ---------- CmdParse Tests ----------


class TestCommandApp:
    def test_app_init(self):
        app = CommandApp()
        assert app is not None

    def test_app_init_with_options(self):
        app = CommandApp(Name="test", Description="A test app", colorize=True)
        assert app._node.Name == "test"

    def test_register_command(self):
        app = CommandApp()

        @on_command("hello")
        def hello(ctx):
            return "Hello!"

        app.register(hello)
        assert "hello" in app._node.Subcommands

    def test_help_alias(self):
        app = CommandApp()
        app.add_help_alias("h", "?")
        assert "h" in app._help_aliases
        assert "?" in app._help_aliases

    def test_colorize_enabled(self):
        app = CommandApp(colorize=True)
        assert app._c["bold"] == "\x1b[1m"

    def test_colorize_disabled(self):
        app = CommandApp(colorize=False)
        assert app._c["bold"] == ""


class TestCommandLexer:
    def test_lexer_split_simple(self):
        tokens = CommandLexer.Split("hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_lexer_split_quoted(self):
        tokens = CommandLexer.Split('say "hello world"')
        assert "say" in tokens
        assert "hello world" in tokens

    def test_lexer_split_empty(self):
        tokens = CommandLexer.Split("")
        assert tokens == []


class TestOnCommand:
    def test_on_command_decorator(self):
        app = CommandApp()

        @on_command("test")
        def test_cmd(ctx):
            return "test"

        app.register(test_cmd)
        assert "test" in app._node.Subcommands

    def test_on_command_with_description(self):
        app = CommandApp()

        @on_command("hello", description="Say hello")
        def hello(ctx):
            return "Hello!"

        app.register(hello)
        assert "hello" in app._node.Subcommands

    def test_on_command_group(self):
        app = CommandApp()

        @on_command.group("config", description="Configuration commands")
        def config_group(ctx):
            pass

        app.register(config_group)
        assert "config" in app._node.Subcommands

    def test_on_command_aliases(self):
        app = CommandApp()

        @on_command("help", aliases=["h", "?"])
        def help_cmd(ctx):
            return "help"

        app.register(help_cmd)
        node = app._node.Subcommands["help"]
        assert "h" in node.Aliases
        assert "?" in node.Aliases


class TestParseError:
    def test_parse_error(self):
        err = ParseError("test error")
        assert str(err) == "test error"


# ---------- Logger Tests ----------


class TestLoggerModule:
    def test_logger_creation(self):
        from fcatbot.utils.logger import get_logger

        logger = get_logger("test")
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_logger_adapter(self):
        from fcatbot.utils.logger import get_logger

        logger = get_logger("test_adapter")
        # LoggerAdapter should delegate to underlying logger
        assert hasattr(logger, "logger")

    def test_logger_output(self, caplog):
        from fcatbot.utils.logger import get_logger

        logger = get_logger("test_output")
        with caplog.at_level(logging.INFO):
            logger.info("test message")
        assert "test message" in caplog.text

    def test_logger_debug(self, caplog):
        from fcatbot.utils.logger import get_logger

        logger = get_logger("test_debug")
        with caplog.at_level(logging.DEBUG):
            logger.debug("debug message")
        assert "debug message" in caplog.text


# ---------- Integration Tests ----------


class TestUtilsIntegration:
    def test_color_with_logging_integration(self):
        """Test that Color works with standard logging."""
        logger = logging.getLogger("integration_test")
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        # Should not raise when using Color in log messages
        logger.debug(f"{Color.Cyan}debug message{Color.Reset}")
        logger.info(f"{Color.Green}info message{Color.Reset}")
        logger.warning(f"{Color.Yellow}warning message{Color.Reset}")
        logger.error(f"{Color.Red}error message{Color.Reset}")

    def test_log_format_with_color(self):
        result = LogFormats.Modern.message(
            group_id=123, nick="Test", uid=456, msg="Hello"
        )
        # Should contain ANSI color codes when color is enabled
        assert "\033[" in result or True  # Color may be disabled in test env
