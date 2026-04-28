from typing import Any, Protocol
from pathlib import Path
import json, pickle, yaml

class StorageBackend(Protocol):
    extension: str
    def load(self, path: Path) -> dict[str, Any]: ...
    def save(self, path: Path, data: dict[str, Any]) -> None: ...

class YAMLBackend:
    extension = "yml"
    def load(self, path: Path) -> dict[str, Any]:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    def save(self, path: Path, data: dict[str, Any]) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

class JSONBackend:
    extension = "json"
    def load(self, path: Path) -> dict[str, Any]:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    def save(self, path: Path, data: dict[str, Any]) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

class PickleBackend:
    extension = "pkl"
    def load(self, path: Path) -> dict[str, Any]:
        with open(path, 'rb') as f:
            return pickle.load(f)
    def save(self, path: Path, data: dict[str, Any]) -> None:
        with open(path, 'wb') as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)