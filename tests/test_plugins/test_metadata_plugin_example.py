import importlib
from pathlib import Path

import pytest

from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import (
    MetadataInputContext,
    MetadataMediaKind,
    MetadataTransformContext,
    MetadataTransformRequest,
)


def _load_example_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(Path("plugins/metadata_plugin_example")))
    return importlib.import_module("plugin_metadata.example")


def _request(imdb_id: str) -> MetadataTransformRequest:
    payload = MediaSearchPayload(imdb_id=imdb_id, title="TMDb fallback")
    return MetadataTransformRequest(
        config=None,  # type: ignore[arg-type]
        context=MetadataTransformContext(
            media_input=MetadataInputContext(
                input_path=None,
                media_type=None,
                working_dir=None,
                files=(),
            ),
            media_search=payload,
        ),
        payload=payload,
        timeout=1,
    )


def test_metadata_plugin_example_transforms_payload_from_dictionary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_example_module(monkeypatch)

    result = module.transform_metadata(_request("TT1254207"))

    assert result is not None
    assert result.original_title == "Big Buck Bunny"
    assert result.year == 2008
    assert result.media_kind is MetadataMediaKind.MOVIE
    assert result.plugin_data["example.metadata"] == {"matched_imdb_id": "tt1254207"}


def test_metadata_plugin_example_returns_none_for_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_example_module(monkeypatch)

    assert module.transform_metadata(_request("tt0000000")) is None
