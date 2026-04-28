from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import Callable, TYPE_CHECKING, Any, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

if TYPE_CHECKING:
    from .lifecycle import LifecycleManager

logger = logging.getLogger("plugkit.watcher")


class _DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Path], None], delay: float = 0.5,
                 loop: asyncio.AbstractEventLoop | None = None):
        self._callback = callback
        self._delay = delay
        self._tasks: dict[str, asyncio.Task] = {}
        self._loop = loop
        self._shutdown = False

    def on_modified(self, event):
        if event.is_directory:
            return
        self._trigger(Path(str(event.src_path)))

    def on_created(self, event):
        if event.is_directory:
            return
        self._trigger(Path(str(event.src_path)))

    def on_moved(self, event):
        if event.is_directory:
            return
        # dest_path 是重命名后的最终文件路径
        self._trigger(Path(str(event.dest_path)))

    def _trigger(self, path: Path):
        if self._shutdown:
            return
        key = str(path)

        def schedule():
            if self._shutdown:
                return
            if key in self._tasks:
                self._tasks[key].cancel()

            async def delayed():
                try:
                    await asyncio.sleep(self._delay)
                    self._callback(path)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Debounced callback failed for %s", path)
                finally:
                    self._tasks.pop(key, None)

            try:
                self._tasks[key] = asyncio.create_task(delayed())
            except RuntimeError as exc:
                logger.error("Cannot create task in thread (no event loop?): %s", exc)

        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(schedule)
        else:
            # 兜底：如果已经在事件循环线程，直接走；否则报错
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    schedule()
                else:
                    logger.warning("No event loop available for watchdog callback")
            except RuntimeError:
                logger.warning("No event loop available for watchdog callback")

    def stop(self):
        self._shutdown = True
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()


class PluginWatcher:
    def __init__(self, manager: "LifecycleManager", *, delay: float = 0.5):
        self._manager = manager
        self._observer = Observer()
        self._delay = delay
        self._running = False
        self._handlers: dict[str, tuple[_DebouncedHandler, Any]] = {}
        self._reload_tasks: dict[str, asyncio.Task] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    def start(self):
        # 关键：启动前必须拿到正确的事件循环
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("Watchdog start: no running event loop found")

        # 回写给所有已注册的 handler
        for _, (handler, _) in self._handlers.items():
            handler._loop = self._loop

        self._observer.start()
        self._running = True
        logger.info("Watchdog started (dev mode)")

    def stop(self):
        if not self._running:
            return
        for key, (handler, watch) in list(self._handlers.items()):
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass
            handler.stop()
        self._handlers.clear()

        for task in list(self._reload_tasks.values()):
            if not task.done():
                task.cancel()
        self._reload_tasks.clear()

        self._observer.stop()
        self._observer.join()
        self._running = False
        logger.info("Watchdog stopped")

    def add_plugin(self, plugin, *, code_path: Path | None = None):
        name = plugin.name

        # 如果 start() 已执行，self._loop 已就绪；否则为 None，等 start() 回写
        loop = self._loop if (self._loop and not self._loop.is_closed()) else None

        config_dir = plugin.get_config_path("").parent
        config_dir.mkdir(parents=True, exist_ok=True)
        config_handler = _DebouncedHandler(
            lambda p: self._on_config_changed(name, p), self._delay, loop
        )
        config_watch = self._observer.schedule(
            config_handler, str(config_dir), recursive=False
        )
        self._handlers[f"{name}:config"] = (config_handler, config_watch)

        if code_path and code_path.exists():
            if code_path.suffix == ".zip":
                return
            watch_path = str(code_path.parent if code_path.is_file() else code_path)
            code_handler = _DebouncedHandler(
                lambda p: self._on_code_changed(name, p), self._delay, loop
            )
            code_watch = self._observer.schedule(
                code_handler, watch_path, recursive=True
            )
            self._handlers[f"{name}:code"] = (code_handler, code_watch)

    def remove_plugin(self, name: str):
        for suffix in ("config", "code"):
            key = f"{name}:{suffix}"
            if key not in self._handlers:
                continue
            handler, watch = self._handlers.pop(key)
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass
            handler.stop()

        task = self._reload_tasks.pop(name, None)
        if task is not None and not task.done():
            task.cancel()

    def _on_config_changed(self, plugin_name: str, path: Path):
        if path.suffix not in (".yml", ".yaml"):
            return
        self._manager.notify_config_file_change(plugin_name, path)

    def _on_code_changed(self, plugin_name: str, path: Path):
        if path.suffix != ".py":
            return
        logger.info("Dev auto-reload triggered: %s (%s)", plugin_name, path.name)

        if plugin_name in self._reload_tasks:
            logger.debug("Reload already in progress for %s, skipping", plugin_name)
            return

        # _on_code_changed 已被 call_soon_threadsafe 投递到主循环线程，
        # 这里可以直接 create_task
        task = asyncio.create_task(self._safe_reload(plugin_name))
        self._reload_tasks[plugin_name] = task
        task.add_done_callback(lambda _f, n=plugin_name: self._reload_tasks.pop(n, None))

    async def _safe_reload(self, name: str):
        try:
            await self._manager.reload(name)
            logger.info("Dev reload success: %s", name)
        except asyncio.CancelledError:
            logger.debug("Dev reload cancelled: %s", name)
            raise
        except Exception:
            logger.exception("Dev reload failed: %s", name)