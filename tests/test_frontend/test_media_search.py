from collections import OrderedDict
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.frontend.wizards.media_search import (
    MediaSearch,
    MediaSearchJobResult,
    _run_media_search_job,
)
from src.payloads.media_inputs import MediaInputPayload
from src.plugins.metadata_provider import MetadataProviderResult
from src.plugins.plugin_payload import PluginPayload


def _config_paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = Path("runtime/config/defaults")
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (source_defaults / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (source_defaults / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def _make_page(tmp_path: Path) -> MediaSearch:
    config = ConfigManager("test", _config_paths(tmp_path))
    context = ProcessingContext(
        media_input=MediaInputPayload(input_path=tmp_path / "Movie.mkv")
    )
    return MediaSearch(config, context, None)  # type: ignore[reportArgumentType]


def test_empty_search_result_does_not_complete_page(tmp_path: Path) -> None:
    page = _make_page(tmp_path)

    page._handle_search_result(OrderedDict())

    assert page.loading_complete is False
    assert page.isComplete() is False
    assert page.listbox.item(0) is not None
    assert page.listbox.item(0).text() == "No results, try again..."


def test_automatic_search_uses_inferred_title_and_selected_files(
    monkeypatch, tmp_path: Path
) -> None:
    input_path = tmp_path / "input"
    selected_file = input_path / "Movie.mkv"
    selected_file.parent.mkdir()
    selected_file.write_bytes(b"")
    calls: list[tuple[Path, tuple[Path, ...]]] = []

    class FakeInferer:
        def infer(self, path: Path, video_files: tuple[Path, ...]):
            calls.append((path, video_files))
            return type("Result", (), {"title": "Inferred Movie", "confidence": 1.0})()

    class FakeBackend:
        def _parse_tmdb_api(self, media_str: str):
            return OrderedDict([(media_str, {"title": media_str})])

    monkeypatch.setattr(
        "src.frontend.wizards.media_search.MediaTitleInferer", FakeInferer
    )

    result = _run_media_search_job(
        FakeBackend(),
        None,
        input_path,
        (selected_file,),
    )

    assert result == MediaSearchJobResult(
        query="Inferred Movie",
        results=OrderedDict([("Inferred Movie", {"title": "Inferred Movie"})]),
    )
    assert calls == [(input_path, (selected_file,))]


def test_manual_search_bypasses_title_inference(monkeypatch) -> None:
    class FailingInferer:
        def __init__(self) -> None:
            raise AssertionError("manual searches must not infer a title")

    class FakeBackend:
        def _parse_tmdb_api(self, media_str: str):
            return OrderedDict([(media_str, {"title": media_str})])

    monkeypatch.setattr(
        "src.frontend.wizards.media_search.MediaTitleInferer", FailingInferer
    )

    result = _run_media_search_job(FakeBackend(), "Manual Movie", None, tuple())

    assert result.query == "Manual Movie"
    assert list(result.results) == ["Manual Movie"]
    assert result.title_error is None


def test_title_inference_failure_returns_manual_search_error(
    monkeypatch, tmp_path: Path
) -> None:
    class FailingInferer:
        def infer(self, *_args, **_kwargs):
            raise ValueError("No usable title evidence")

    class FakeBackend:
        def _parse_tmdb_api(self, media_str: str):
            return OrderedDict([(media_str, {"title": media_str})])

    monkeypatch.setattr(
        "src.frontend.wizards.media_search.MediaTitleInferer", FailingInferer
    )

    result = _run_media_search_job(
        FakeBackend(),
        None,
        tmp_path,
        tuple(),
    )

    assert result.query is None
    assert not result.results
    assert result.title_error == "No usable title evidence"


def test_failed_search_clears_payload_and_preserves_query(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    page.search_entry.setText("Movie 2024")
    page.context.media_search.media_type = MediaType.MOVIE
    page.context.media_search.tmdb_id = "123"
    page.context.media_search.title = "Movie"

    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
    page._failed_search("TMDB search is unavailable")

    assert page.loading_complete is False
    assert page.other_ids_parsed is False
    assert page.context.media_search.tmdb_id is None
    assert page.search_entry.text() == "Movie 2024"
    assert page.listbox.item(0) is not None
    assert page.listbox.item(0).text().startswith("Search unavailable:")


def test_provider_failure_warns_and_continues_with_tmdb(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    page.context.media_search.media_type = MediaType.MOVIE
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    should_continue = page._handle_metadata_failures(
        {
            "provider_metadata": {
                "success": False,
                "error": "Provider offline",
            }
        }
    )

    assert should_continue is True
    assert warnings == [
        (
            "Metadata Provider Unavailable",
            "Provider offline\n\nTMDb metadata will be used instead.",
        )
    ]


def test_series_tvdb_failure_uses_retry_or_manual_choice(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    page.context.media_search.media_type = MediaType.SERIES
    prompts: list[str] = []
    monkeypatch.setattr(
        page,
        "_ask_to_continue_without_tvdb",
        lambda details: prompts.append(details) or False,
    )

    should_continue = page._handle_metadata_failures(
        {"tvdb_data": {"success": False, "error": "TVDB offline"}}
    )

    assert should_continue is False
    assert "TVDB offline" in prompts[0]

    monkeypatch.setattr(page, "_ask_to_continue_without_tvdb", lambda _details: True)
    assert (
        page._handle_metadata_failures(
            {"tvdb_data": {"success": False, "error": "TVDB offline"}}
        )
        is True
    )


def test_selected_metadata_provider_is_only_used_when_plugins_are_enabled(
    tmp_path: Path,
) -> None:
    page = _make_page(tmp_path)

    def provider(**_kwargs: object) -> MetadataProviderResult | None:
        return None

    page.config.plugin_registry.plugins["Provider"] = PluginPayload(
        name="Provider", metadata_provider=provider
    )
    page.config.settings.plugins.metadata_provider = "Provider"

    page.config.settings.general.enable_plugins = False
    assert page._get_metadata_provider() is None

    page.config.settings.general.enable_plugins = True
    assert page._get_metadata_provider() is provider


def test_id_validation_accepts_supported_manual_id_shapes(tmp_path: Path) -> None:
    page = _make_page(tmp_path)
    page.imdb_id_entry.setText("tt1234567")
    page.tmdb_id_entry.setText("123")
    page.tvdb_id_entry.setText("456")

    assert page._has_invalid_id_formats() is False

    page.imdb_id_entry.setText("1234567")
    assert page._has_invalid_id_formats() is True


def test_payload_update_stores_resolved_ids_and_provider_metadata(
    tmp_path: Path,
) -> None:
    page = _make_page(tmp_path)
    item_name = "1) Movie (2024)"
    page.backend.media_data = {
        item_name: {
            "media_type": "Movie",
            "title": "Movie",
            "year": "2024",
            "original_title": "Original Movie",
            "genre_ids": [],
            "raw_data": {"id": 123},
        }
    }
    page.listbox.clear()
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    page.tmdb_id_entry.setText("123")
    provider_result = MetadataProviderResult(
        original_title="Provider Original",
        localized_title="Provider Localized",
        year=2025,
        plot="Provider plot",
        poster_url="https://provider.example/poster.jpg",
        genres=("Provider Genre",),
    )

    page._update_payload_data(
        {
            "tmdb_complete_data": {
                "success": True,
                "result": {
                    "id": 123,
                    "title": "TMDb title",
                    "original_title": "TMDb original",
                    "release_date": "2024-01-01",
                    "overview": "Complete metadata",
                    "poster_path": "/tmdb-poster.jpg",
                    "genres": [{"id": 1, "name": "TMDb Genre"}],
                },
            },
            "resolved_ids": {
                "success": True,
                "result": {"imdb_id": "tt1234567", "tvdb_id": 456},
            },
            "provider_metadata": {"success": True, "result": provider_result},
        }
    )

    assert page.context.media_search.tmdb_data == {
        "id": 123,
        "title": "TMDb title",
        "original_title": "TMDb original",
        "release_date": "2024-01-01",
        "overview": "Complete metadata",
        "poster_path": "/tmdb-poster.jpg",
        "genres": [{"id": 1, "name": "TMDb Genre"}],
    }
    assert page.context.media_search.imdb_id == "tt1234567"
    assert page.context.media_search.tvdb_id == "456"
    assert page.context.media_search.provider_metadata is provider_result
    assert page.context.media_search.title == "Provider Localized"
    assert page.context.media_search.original_title == "Provider Original"
    assert page.context.media_search.year == 2025
    assert page.context.media_search.plot == "Provider plot"
    assert page.context.media_search.poster_url == (
        "https://provider.example/poster.jpg"
    )
    assert page.context.media_search.genre_names == ("Provider Genre",)
