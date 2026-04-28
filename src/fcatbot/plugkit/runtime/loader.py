# runtime/loader.py
import inspect
import importlib
import importlib.util
import sys
import zipfile
from pathlib import Path
from typing import Type, Any

from ..protocol.plugin import Plugin


class PluginLoader:
    def __init__(self, plugin_dirs: list[Path]):
        self._plugin_dirs = [Path(d) for d in plugin_dirs]

    def _find_source(self, name: str) -> tuple[Path, str] | None:
        """查找插件源。返回 (path, kind)，kind 为 'file'|'package'|'zip'"""
        for directory in self._plugin_dirs:
            pkg = directory / name
            if (pkg / "__init__.py").exists():
                return (pkg, "package")

            single = directory / f"{name}.py"
            if single.exists():
                return (single, "file")

            zip_pkg = directory / f"{name}.zip"
            if zip_pkg.exists() and self._is_valid_zip(zip_pkg):
                return (zip_pkg, "zip")

            legacy = directory / f"plugkit_plugin_{name}.py"
            if legacy.exists():
                return (legacy, "file")
        return None

    def get_source_path(self, name: str) -> Path | None:
        result = self._find_source(name)
        return result[0] if result else None

    def _is_valid_zip(self, zip_path: Path) -> bool:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                return any(n.endswith("__init__.py") for n in zf.namelist())
        except (zipfile.BadZipFile, OSError):
            return False

    def _clear_pycache(self, path: Path) -> None:
        if path.is_file():
            pycache = path.parent / "__pycache__"
            stem = path.stem
        else:
            pycache = path / "__pycache__"
            stem = "__init__"
        if not pycache.exists():
            return
        for pyc in pycache.glob(f"{stem}.*.pyc"):
            pyc.unlink(missing_ok=True)

    def _clean_module_cache(self, module_name: str) -> None:
        """彻底清理 sys.modules 中的旧模块及子模块"""
        if module_name in sys.modules:
            del sys.modules[module_name]
        prefix = f"{module_name}."
        for key in list(sys.modules.keys()):
            if key.startswith(prefix):
                del sys.modules[key]
        importlib.invalidate_caches()

    def load_class(self, name: str) -> Type[Plugin]:
        found = self._find_source(name)
        if found is None:
            raise RuntimeError(f"Plugin module {name} not found")

        path, kind = found

        if kind == "zip":
            # ZIP 必须使用原始包名（与 ZIP 内部目录名一致）
            module = self._load_from_zip(path, name)
            module_name = name
        else:
            module_name = name
            self._clean_module_cache(module_name)
            self._clear_pycache(path)

            if kind == "file":
                spec = importlib.util.spec_from_file_location(module_name, path)
            else:
                spec = importlib.util.spec_from_file_location(
                    module_name, path / "__init__.py",
                    submodule_search_locations=[str(path)]
                )
            if spec is None:
                raise RuntimeError(f"Cannot create module spec for {name}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # type: ignore[union-attr]

        # --- 新增：显式导出 __plugins__ ---
        explicit_plugins = getattr(module, "__plugins__", None)
        if explicit_plugins is not None:
            if not isinstance(explicit_plugins, (list, tuple)):
                raise RuntimeError(
                    f"Plugin {name}: __plugins__ must be list or tuple, "
                    f"got {type(explicit_plugins).__name__}"
                )
            for cls in explicit_plugins:
                if not isinstance(cls, type):
                    continue
                if (
                    isinstance(cls, type)
                    and not inspect.isabstract(cls)
                    and hasattr(cls, "name")
                ):
                    cls._plugin_source_name = name
                    return cls
            print(explicit_plugins)
            raise RuntimeError(
                f"Plugin {name}: __plugins__ has no valid Plugin subclass"
            )

        # --- 回退：自动扫描模块内所有 Plugin 子类 ---
        candidates = []
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Plugin)
                and obj is not Plugin
                and not inspect.isabstract(obj)
            ):
                candidates.append(obj)

        if not candidates:
            raise RuntimeError(f"No Plugin subclass found in {name}")
        if len(candidates) > 1:
            for c in candidates:
                if getattr(c, 'name', None) == name:
                    c._plugin_source_name = name
                    return c
            candidates[0]._plugin_source_name = name
            return candidates[0]
        candidates[0]._plugin_source_name = name
        return candidates[0]

    def _load_from_zip(self, zip_path: Path, module_name: str) -> Any:
        """ZIP 加载：将 ZIP 加入 sys.path 后用原始包名导入"""
        zip_str = str(zip_path)

        # 清理旧模块（用原始名）
        self._clean_module_cache(module_name)

        inserted = False
        if zip_str not in sys.path:
            sys.path.insert(0, zip_str)
            inserted = True
        try:
            module = importlib.import_module(module_name)
            return module
        finally:
            if inserted and zip_str in sys.path:
                sys.path.remove(zip_str)