import asyncio
import dataclasses
import inspect
import logging
import secrets
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fcatbot.plugkit.protocol.bus import (
    EventBus,
    EventHandler,
    GlobalInterceptor,
    HandlerInterceptor,
)
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.protocol.exceptions import BusClosedError

logger = logging.getLogger("plugkit.bus")


@dataclass
class _Subscription:
    token: str
    event_spec: str | type
    handler: EventHandler
    priority: int
    once: bool


class BackpressureError(Exception):
    pass


class Bus(EventBus):
    def __init__(
        self, *, max_queue: int = 1000, max_concurrent: int = 100, workers: int = 4
    ):
        if max_queue <= 0:
            raise ValueError("max_queue must be a positive integer")
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._subs: dict = defaultdict(list)
        self._token_map: dict = {}
        self._global_interceptors: list[GlobalInterceptor] = []
        self._handler_interceptors: list[HandlerInterceptor] = []
        self._worker_tasks: list[asyncio.Task] = []
        self._workers = workers
        self._closed = False
        self._started = False

    def add_global_interceptor(self, interceptor: GlobalInterceptor) -> None:
        self._global_interceptors.append(interceptor)

    def add_handler_interceptor(self, interceptor: HandlerInterceptor) -> None:
        self._handler_interceptors.append(interceptor)

    def subscribe(
        self,
        event_spec: str | type,
        handler: EventHandler,
        *,
        priority: int = 50,
        once: bool = False,
    ) -> str:
        if self._closed:
            raise BusClosedError("Bus closed")
        token = secrets.token_hex(8)
        sub = _Subscription(token, event_spec, handler, priority, once)
        self._subs[event_spec].append(sub)
        self._subs[event_spec].sort(key=lambda s: s.priority, reverse=True)
        self._token_map[token] = sub
        return token

    def unsubscribe(self, token: str) -> bool:
        sub = self._token_map.pop(token, None)
        if not sub:
            return False
        bucket = self._subs.get(sub.event_spec, [])
        if sub in bucket:
            bucket.remove(sub)
            if not bucket:
                del self._subs[sub.event_spec]
        return True

    async def publish(self, event: Any) -> None:
        if self._closed:
            raise BusClosedError("Bus closed")

        if isinstance(event, Event):
            event = dataclasses.replace(event, _cancelled=False)
        elif isinstance(event, dict):
            event = Event(name=event.get("event", ""), data=event, metadata=event)
        else:
            event = Event(data=event)

        for gi in self._global_interceptors:
            if not await gi.intercept(event):
                return

        subs = self._resolve_subs(event)
        if not subs:
            return

        try:
            self._queue.put_nowait((event, subs))
        except asyncio.QueueFull:
            raise BackpressureError("Queue full")

    async def drain(self) -> None:
        await self._queue.join()

    def start(self) -> None:
        if self._closed or self._started:
            return
        self._started = True
        for _ in range(self._workers):
            self._worker_tasks.append(asyncio.create_task(self._worker_loop()))

    async def close(self) -> None:
        self._closed = True
        await self.drain()
        for t in self._worker_tasks:
            t.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()

    def _resolve_subs(self, event: Any) -> list[_Subscription]:
        specs: list = []
        seen: set = set()
        result: list[_Subscription] = []

        if isinstance(event, Event):  # 空字符串是合法的
            specs.append(event.name)
        elif isinstance(event, dict) and "event" in event:
            specs.append(event["event"])
        else:
            typ = type(event)
            if typ is not Event and typ is not dict:
                specs.append(typ)

        for spec in specs:
            for sub in self._subs.get(spec, []):
                if sub.token not in seen:
                    seen.add(sub.token)
                    result.append(sub)
        result.sort(key=lambda s: s.priority, reverse=True)
        return result

    async def _worker_loop(self) -> None:
        while True:
            event_subs = None
            try:
                event_subs = await self._queue.get()
            except asyncio.CancelledError:
                break

            event, subs = event_subs
            try:
                async with self._semaphore:
                    await self._dispatch(event, subs)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker dispatch failed")
            finally:
                self._queue.task_done()

    async def _dispatch(self, event: Any, subs: list[_Subscription]) -> None:
        for sub in subs:
            if sub.token not in self._token_map:
                continue
            if sub.once:
                self.unsubscribe(sub.token)

            blocked = False
            for hi in self._handler_interceptors:
                if not await hi.intercept(event, sub.handler):
                    blocked = True
                    break
            if blocked:
                continue

            try:
                if inspect.iscoroutinefunction(sub.handler):
                    await sub.handler(event)
                else:
                    sub.handler(event)
            except Exception:
                logger.exception("Handler failed: token=%s", sub.token)
                continue

            if isinstance(event, Event) and event.cancelled:
                break
