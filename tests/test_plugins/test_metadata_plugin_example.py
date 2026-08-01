import importlib
from pathlib import Path

import pytest

from src.plugins.metadata_provider import MetadataMediaKind


def _load_example_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(Path("plugins/metadata_plugin_example")))
    return importlib.import_module("plugin_metadata_example.example")


def test_metadata_plugin_example_returns_deterministic_dictionary_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_example_module(monkeypatch)
    result = module.metadata_provider(
        config=None,  # type: ignore[arg-type]
        context=None,  # type: ignore[arg-type]
        imdb_id="tt1254207",
        tmdb_data={},
        media_type=None,  # type: ignore[arg-type]
        timeout=1,
    )

    assert result is module.EXAMPLE_METADATA["tt1254207"]
    assert result is not None
    assert result.original_title == "Big Buck Bunny"
    assert result.year == 2008
    assert result.media_kind is MetadataMediaKind.MOVIE

    uppercase_result = module.metadata_provider(
        config=None,  # type: ignore[arg-type]
        context=None,  # type: ignore[arg-type]
        imdb_id="TT1254207",
        tmdb_data={},
        media_type=None,  # type: ignore[arg-type]
        timeout=1,
    )
    assert uppercase_result is result


def test_metadata_plugin_example_returns_none_for_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_example_module(monkeypatch)
    result = module.metadata_provider(
        config=None,  # type: ignore[arg-type]
        context=None,  # type: ignore[arg-type]
        imdb_id="tt0000000",
        tmdb_data={},
        media_type=None,  # type: ignore[arg-type]
        timeout=1,
    )

    assert result is None
