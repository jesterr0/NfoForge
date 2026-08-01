from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.exceptions import PluginError
from src.plugins.loader import PluginLoader
from src.plugins.metadata_provider import MetadataProviderResult
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


def test_metadata_provider_contract_is_accepted() -> None:
    def metadata_provider(
        *,
        config: ConfigManager,
        context: ProcessingContext,
        imdb_id: str,
        tmdb_data: Mapping[str, Any],
        media_type: MediaType,
        timeout: int,
        **kwargs: object,
    ) -> MetadataProviderResult | None:
        del config, context, imdb_id, tmdb_data, media_type, timeout, kwargs
        return None

    loader = PluginLoader(None)  # type: ignore[arg-type]

    loader._check_plugin(
        PluginPayload(name="Metadata provider", metadata_provider=metadata_provider)
    )


def test_metadata_provider_contract_requires_forward_compatible_kwargs() -> None:
    def metadata_provider(
        *,
        config: ConfigManager,
        context: ProcessingContext,
        imdb_id: str,
        tmdb_data: Mapping[str, Any],
        media_type: MediaType,
        timeout: int,
    ) -> MetadataProviderResult | None:
        del config, context, imdb_id, tmdb_data, media_type, timeout
        return None

    loader = PluginLoader(None)  # type: ignore[arg-type]

    try:
        loader._check_plugin(
            PluginPayload(name="Metadata provider", metadata_provider=metadata_provider)
        )
    except PluginError as error:
        assert "must accept '**kwargs'" in str(error)
    else:
        raise AssertionError("Expected an incompatible provider to be rejected")
