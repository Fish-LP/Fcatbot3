from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T_co = TypeVar("T_co", covariant=True)


@dataclass
class Event(Generic[T_co]):  # T 仅方便使用
    name: str = ""
    data: T_co | Any = None
    source: str = ""
    metadata: dict = field(default_factory=dict)
    _cancelled: bool = field(default=False, repr=False)

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def __str__(self) -> str:
        src = self.source or "None"
        cancel = " [CANCELLED]" if self._cancelled else ""
        data_repr = repr(self.data)
        return f"Event({self.name!r}, src={src!r}{cancel}, data={data_repr})"
