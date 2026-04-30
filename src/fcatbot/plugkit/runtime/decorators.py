from typing import Any, Callable


def on_event(
    event_spec: str | type,
    *,
    priority: int = 50,
    once: bool = False,
    filter: Callable[[Any], bool] | None = None,
):
    def decorator(func: Callable):
        func.__event_spec__ = event_spec  # type: ignore
        func.__priority__ = priority  # type: ignore
        func.__once__ = once  # type: ignore
        func.__filter__ = filter  # type: ignore
        return func

    return decorator
