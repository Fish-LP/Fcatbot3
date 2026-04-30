from typing import Any, Awaitable, Callable, Protocol

EventHandler = Callable[[Any], None | Awaitable[None]]


class GlobalInterceptor(Protocol):
    async def intercept(self, event: Any) -> bool: ...


class HandlerInterceptor(Protocol):
    async def intercept(self, event: Any, handler: EventHandler) -> bool: ...


class EventBus(Protocol):
    def subscribe(
        self,
        event_spec: str | type,
        handler: EventHandler,
        *,
        priority: int = 50,
        once: bool = False,
    ) -> str: ...
    def unsubscribe(self, token: str) -> bool: ...
    async def publish(self, event: Any) -> None: ...
    async def drain(self) -> None: ...
    def start(self) -> None: ...
    async def close(self) -> None: ...
