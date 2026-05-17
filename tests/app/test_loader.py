"""Application tests for PluginLoader —— how the app loads plugins.

PluginLoader is part of plugkit runtime, but these tests verify the
loading behavior from the application perspective.
"""

import sys

import pytest

from fcatbot.plugkit.runtime.loader import PluginLoader

# ---------- Fixture: create a fake plugin file ----------


@pytest.fixture
def plugin_dir(tmp_path):
    """Create a temporary plugin directory."""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


@pytest.fixture
def make_plugin_file(plugin_dir):
    """Factory to create plugin files in the plugin directory."""

    def _make(name, content, is_package=False):
        if is_package:
            pkg = plugin_dir / name
            pkg.mkdir()
            init = pkg / "__init__.py"
            init.write_text(content, encoding="utf-8")
            return pkg
        else:
            f = plugin_dir / f"{name}.py"
            f.write_text(content, encoding="utf-8")
            return f

    return _make


# ---------- Plugin Discovery ----------


class TestPluginDiscovery:
    """Test that loader finds plugins in directories."""

    def test_find_source_file(self, plugin_dir, make_plugin_file):
        """Loader should find .py files."""
        make_plugin_file("hello", "x = 1\n")
        loader = PluginLoader([plugin_dir])
        result = loader._find_source("hello")
        assert result is not None
        path, kind = result
        assert kind == "file"
        assert path.name == "hello.py"

    def test_find_source_package(self, plugin_dir, make_plugin_file):
        """Loader should find packages with __init__.py."""
        make_plugin_file("mypkg", "x = 1\n", is_package=True)
        loader = PluginLoader([plugin_dir])
        result = loader._find_source("mypkg")
        assert result is not None
        path, kind = result
        assert kind == "package"

    def test_find_source_missing(self, plugin_dir):
        """Loader should return None for missing plugins."""
        loader = PluginLoader([plugin_dir])
        result = loader._find_source("nonexistent")
        assert result is None

    def test_find_source_legacy_name(self, plugin_dir, make_plugin_file):
        """Loader should find legacy named plugins."""
        f = plugin_dir / "plugkit_plugin_legacy.py"
        f.write_text("x = 1\n", encoding="utf-8")
        loader = PluginLoader([plugin_dir])
        result = loader._find_source("legacy")
        assert result is not None
        path, kind = result
        assert kind == "file"

    def test_get_source_path(self, plugin_dir, make_plugin_file):
        make_plugin_file("test", "x = 1\n")
        loader = PluginLoader([plugin_dir])
        path = loader.get_source_path("test")
        assert path is not None
        assert path.name == "test.py"

    def test_get_source_path_missing(self, plugin_dir):
        loader = PluginLoader([plugin_dir])
        path = loader.get_source_path("missing")
        assert path is None

    def test_find_source_multiple_dirs(self, tmp_path, plugin_dir, make_plugin_file):
        """Loader should search all directories."""
        dir2 = tmp_path / "plugins2"
        dir2.mkdir()
        make_plugin_file("in_first", "x = 1\n")

        f2 = dir2 / "in_second.py"
        f2.write_text("y = 2\n", encoding="utf-8")

        loader = PluginLoader([plugin_dir, dir2])
        r1 = loader._find_source("in_first")
        r2 = loader._find_source("in_second")
        assert r1 is not None
        assert r2 is not None


# ---------- Cache Management ----------


class TestCacheManagement:
    """Test module cache cleaning."""

    def test_clean_module_cache(self, plugin_dir, make_plugin_file):
        make_plugin_file("cached", "x = 1\n")
        loader = PluginLoader([plugin_dir])

        # Simulate module in cache
        sys.modules["cached"] = type(sys)("cached")
        sys.modules["cached.sub"] = type(sys)("cached.sub")
        assert "cached" in sys.modules

        loader._clean_module_cache("cached")
        assert "cached" not in sys.modules
        assert "cached.sub" not in sys.modules

    def test_clear_pycache_file(self, plugin_dir, make_plugin_file):
        make_plugin_file("with_pyc", "x = 1\n")
        # Create a fake pyc file
        pycache = plugin_dir / "__pycache__"
        pycache.mkdir()
        pyc = pycache / "with_pyc.cpython-311.pyc"
        pyc.write_text("fake", encoding="utf-8")

        loader = PluginLoader([plugin_dir])
        loader._clear_pycache(plugin_dir / "with_pyc.py")
        assert not pyc.exists()

    def test_clear_pycache_package(self, plugin_dir, make_plugin_file):
        make_plugin_file("pkg", "x = 1\n", is_package=True)
        pycache = plugin_dir / "pkg" / "__pycache__"
        pycache.mkdir()
        pyc = pycache / "__init__.cpython-311.pyc"
        pyc.write_text("fake", encoding="utf-8")

        loader = PluginLoader([plugin_dir])
        loader._clear_pycache(plugin_dir / "pkg")
        assert not pyc.exists()


# ---------- ZIP Plugin Loading ----------


class TestZipPluginLoading:
    """Test ZIP plugin discovery."""

    def test_is_valid_zip_true(self, tmp_path):
        import zipfile

        zf = tmp_path / "valid.zip"
        with zipfile.ZipFile(zf, "w") as z:
            z.writestr("__init__.py", "x = 1\n")

        loader = PluginLoader([tmp_path])
        assert loader._is_valid_zip(zf) is True

    def test_is_valid_zip_no_init(self, tmp_path):
        import zipfile

        zf = tmp_path / "noinit.zip"
        with zipfile.ZipFile(zf, "w") as z:
            z.writestr("module.py", "x = 1\n")

        loader = PluginLoader([tmp_path])
        assert loader._is_valid_zip(zf) is False

    def test_is_valid_zip_bad_file(self, tmp_path):
        bad = tmp_path / "not_a_zip.zip"
        bad.write_text("not zip content", encoding="utf-8")

        loader = PluginLoader([tmp_path])
        assert loader._is_valid_zip(bad) is False

    def test_find_source_zip(self, tmp_path):
        import zipfile

        zf = tmp_path / "myplugin.zip"
        with zipfile.ZipFile(zf, "w") as z:
            z.writestr("__init__.py", "x = 1\n")

        loader = PluginLoader([tmp_path])
        result = loader._find_source("myplugin")
        assert result is not None
        _, kind = result
        assert kind == "zip"


# ---------- Error Handling ----------


class TestLoaderErrors:
    """Test loader error handling."""

    def test_load_class_not_found(self, plugin_dir):
        from fcatbot.plugkit.protocol.exceptions import PluginLoadError

        loader = PluginLoader([plugin_dir])
        with pytest.raises(PluginLoadError):
            loader.load_class("nonexistent")

    def test_load_class_no_plugin_subclass(self, plugin_dir, make_plugin_file):
        from fcatbot.plugkit.protocol.exceptions import PluginLoadError

        # File with no Plugin subclass
        make_plugin_file("noplugin", "x = 1\ny = 2\n")
        loader = PluginLoader([plugin_dir])
        with pytest.raises(PluginLoadError):
            loader.load_class("noplugin")

    def test_load_class_explicit_plugins_bad_type(self, plugin_dir, make_plugin_file):
        from fcatbot.plugkit.protocol.exceptions import PluginLoadError

        # __plugins__ is not a list
        make_plugin_file("badplugins", '__plugins__ = "not a list"\n')
        loader = PluginLoader([plugin_dir])
        with pytest.raises(PluginLoadError):
            loader.load_class("badplugins")

    def test_load_class_explicit_plugins_empty(self, plugin_dir, make_plugin_file):
        from fcatbot.plugkit.protocol.exceptions import PluginLoadError

        make_plugin_file("emptyplugins", "__plugins__ = []\n")
        loader = PluginLoader([plugin_dir])
        with pytest.raises(PluginLoadError):
            loader.load_class("emptyplugins")
