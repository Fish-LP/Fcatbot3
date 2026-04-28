from dataclasses import dataclass
from enum import Enum, auto

class PluginState(Enum):
    Unloaded = auto()
    Loaded = auto()
    Running = auto()
    Stopping = auto()
    Stopped = auto()
    Failed = auto()

@dataclass(frozen=True)
class PluginStatus:
    state: PluginState = PluginState.Unloaded
    error: Exception | None = None
    loaded_at: float | None = None
    started_at: float | None = None
    stopped_at: float | None = None

    def replace(self, **kwargs):
        return PluginStatus(
            state=kwargs.get('state', self.state),
            error=kwargs.get('error', self.error),
            loaded_at=kwargs.get('loaded_at', self.loaded_at),
            started_at=kwargs.get('started_at', self.started_at),
            stopped_at=kwargs.get('stopped_at', self.stopped_at),
        )