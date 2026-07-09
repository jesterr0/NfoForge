from pathlib import Path

from src.exceptions import PluginError
from src.plugins.loader import PluginLoader
from src.plugins.plugin_payload import PluginPayload


def test_load_plugins_skips_failures_and_continues(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = tmp_path / "plugins"
    bad_plugin = plugin_dir / "plugin_bad"
    good_plugin = plugin_dir / "plugin_good"
    ignored_dir = plugin_dir / "not_a_plugin"
    for directory in (bad_plugin, good_plugin, ignored_dir):
        directory.mkdir(parents=True)

    loader = PluginLoader(None)  # type: ignore[arg-type]
    loader.plugin_dir = plugin_dir
    attempted: list[Path] = []

    def handle_dir(item: Path) -> None:
        attempted.append(item)
        if item == bad_plugin:
            raise PluginError("invalid payload")
        loader.plugins["Good"] = PluginPayload(name="Good")

    monkeypatch.setattr(loader, "_handle_dir", handle_dir)

    plugins = loader.load_plugins()

    assert plugins == {"Good": PluginPayload(name="Good")}
    assert attempted == [bad_plugin, good_plugin]
    assert len(loader.failures) == 1
    assert loader.failures[0].plugin_path == bad_plugin
    assert loader.failures[0].reason == "invalid payload"


def test_load_plugins_records_unexpected_errors(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin = plugin_dir / "plugin_broken_import"
    plugin.mkdir(parents=True)

    loader = PluginLoader(None)  # type: ignore[arg-type]
    loader.plugin_dir = plugin_dir
    monkeypatch.setattr(
        loader,
        "_handle_dir",
        lambda _item: (_ for _ in ()).throw(ImportError("missing dependency")),
    )

    assert loader.load_plugins() == {}
    assert str(loader.failures[0]) == "plugin_broken_import: missing dependency"
