from collections import OrderedDict
from pathlib import Path

from PySide6.QtWidgets import QMessageBox
import pytest

from src.backend.media_search import MediaSearchBackEnd
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.exceptions import MediaSearchError, MediaSearchUnavailableError
from src.frontend.wizards.media_search import (
    MediaSearch,
    MediaSearchJobResult,
    _run_media_search_job,
)
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.plugins.api import (
    MetadataTransformRequest,
    PluginDefinition,
)


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


def _media_search_page_with_selected_row(
    tmp_path: Path,
    media_type: str,
    genre_ids: list[TMDBGenreIDsMovies | TMDBGenreIDsSeries],
) -> MediaSearch:
    page = _make_page(tmp_path)
    item_name = "1) Selected (2020)"
    page.backend.media_data = {
        item_name: {
            "media_type": MediaType.strict_search_type(media_type).value,
            "title": "Selected",
            "year": "2020",
            "original_title": "Selected",
            "genre_ids": genre_ids,
            "raw_data": {"id": 123, "original_language": "ja"},
        }
    }
    page.listbox.clear()
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    return page


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


def test_manual_id_lookup_failure_keeps_current_selection(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    page.loading_complete = True
    page.other_ids_parsed = True
    item_name = "1) Movie (2024)"
    page.backend.media_data = {item_name: {"title": "Movie"}}
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    page.context.media_search.title = "Movie"
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    page._handle_id_parse_failed(MediaSearchError("TMDB metadata lookup failed"))

    assert page.loading_complete is True
    assert page.other_ids_parsed is False
    assert page.backend.media_data == {item_name: {"title": "Movie"}}
    assert page.context.media_search.title == "Movie"
    assert page.listbox.item(0).text() == item_name
    assert warnings[0][0] == "Metadata Lookup Failed"
    assert "current search selection was kept" in warnings[0][1]


def test_unavailable_manual_id_lookup_keeps_destructive_network_path(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    page.context.media_search.title = "Movie"
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)

    page._handle_id_parse_failed(MediaSearchUnavailableError("TVDB offline"))

    assert page.loading_complete is False
    assert page.context.media_search.title is None


def test_transformer_failure_warns_and_continues_with_tmdb(
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
            "metadata_transformation": {
                "success": False,
                "error": "Provider offline",
            }
        }
    )

    assert should_continue is True
    assert warnings == [
        (
            "Metadata Transformer Unavailable",
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


def test_selected_metadata_transformer_is_only_used_when_plugins_are_enabled(
    tmp_path: Path,
) -> None:
    page = _make_page(tmp_path)

    def transformer(
        _request: MetadataTransformRequest,
    ) -> MediaSearchPayload | None:
        return None

    page.config.plugin_manager.register(
        "provider",
        PluginDefinition(
            display_name="Provider",
            version="1.0.0",
            metadata_transformer=transformer,
        ),
        "test",
    )
    page.config.settings.plugins.metadata_transformer = "provider"

    page.config.settings.general.enable_plugins = False
    assert page._get_metadata_transformer_id() is None

    page.config.settings.general.enable_plugins = True
    assert page._get_metadata_transformer_id() == "provider"


def test_id_validation_accepts_supported_manual_id_shapes(tmp_path: Path) -> None:
    page = _make_page(tmp_path)
    page.imdb_id_entry.setText("tt1234567")
    page.tmdb_id_entry.setText("123")
    page.tvdb_id_entry.setText("456")

    assert page._has_invalid_id_formats() is False

    page.imdb_id_entry.setText("1234567")
    assert page._has_invalid_id_formats() is True

    page.imdb_id_entry.setText("tt1234567")
    page.tmdb_id_entry.setText("²")
    assert page._has_invalid_id_formats() is True


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../person/1234",  # path traversal into another TMDB endpoint
        "123&api_key=x",  # query-parameter injection
    ],
)
def test_hostile_tmdb_id_shapes_are_rejected(bad_id: str, tmp_path: Path) -> None:
    page = _make_page(tmp_path)
    page.imdb_id_entry.setText("tt1234567")
    page.tvdb_id_entry.setText("456")
    page.tmdb_id_entry.setText(bad_id)

    assert page._has_invalid_id_formats() is True


def test_search_other_ids_is_not_reached_when_id_formats_are_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_has_invalid_id_formats` is what actually keeps a hostile manual TMDB
    ID from reaching `_search_other_ids` -- and, through it, the URL-path
    interpolation in `MediaSearchBackEnd.fetch_complete_tmdb_data_for_selection`.
    `MediaSearchBackEnd._validate_tmdb_id` is the second line of defence; this
    asserts the first one, which is what keeps the backend unreachable here.
    """
    page = _make_page(tmp_path)
    page.loading_complete = True
    item_name = "1) Movie (2024)"
    page.backend.media_data = {item_name: {"title": "Movie"}}
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    page.tmdb_id_entry.setText("../../person/1234")

    called = False

    def record_call() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(page, "_search_other_ids", record_call)

    result = page.validatePage()

    assert called is False
    assert result is False


def test_backend_rejects_a_traversal_id_even_if_the_ui_is_bypassed() -> None:
    # Defence in depth: `_validate_tmdb_id` is called directly by
    # `fetch_complete_tmdb_data_for_selection` before it builds the request
    # URL, so it must reject a hostile shape on its own even if a caller
    # (or a future code path) skips the UI guard above.
    with pytest.raises(MediaSearchError):
        MediaSearchBackEnd._validate_tmdb_id("../../person/1234")


def test_payload_update_commits_transformed_metadata(
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
    complete_tmdb = {
        "id": 123,
        "title": "TMDb title",
        "original_title": "TMDb original",
        "release_date": "2024-01-01",
        "overview": "Complete metadata",
        "poster_path": "/tmdb-poster.jpg",
        "genres": [{"id": 1, "name": "TMDb Genre"}],
    }
    transformed = MediaSearchPayload(
        media_type=MediaType.MOVIE,
        imdb_id="tt1234567",
        tmdb_id="123",
        tvdb_id="456",
        tmdb_data=complete_tmdb,
        title="Provider Localized",
        original_title="Provider Original",
        year=2025,
        plot="Provider plot",
        poster_url="https://provider.example/poster.jpg",
        genre_names=("Provider Genre",),
    )

    page._update_payload_data(
        {
            "tmdb_complete_data": {
                "success": True,
                "result": complete_tmdb,
            },
            "resolved_ids": {
                "success": True,
                "result": {"imdb_id": "tt1234567", "tvdb_id": 456},
            },
            "metadata_transformation": {"success": True, "result": transformed},
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
    assert page.context.media_search.title == "Provider Localized"
    assert page.context.media_search.original_title == "Provider Original"
    assert page.context.media_search.year == 2025
    assert page.context.media_search.plot == "Provider plot"
    assert page.context.media_search.poster_url == (
        "https://provider.example/poster.jpg"
    )
    assert page.context.media_search.genre_names == ("Provider Genre",)


def test_manual_tmdb_id_refreshes_genres_to_match_genre_names(tmp_path: Path) -> None:
    # A manually entered TMDB ID fetches a complete record whose `genres` can
    # differ from the search row's `genre_ids` (here: the row is Action, the
    # fetched record is Animation). `genres` must track the record
    # `populate_from_tmdb` uses to build `genre_names`, not the stale row --
    # downstream anime/genre-aware logic reads `genres` directly.
    page = _make_page(tmp_path)
    item_name = "1) Anime Movie (2024)"
    page.backend.media_data = {
        item_name: {
            "media_type": "Movie",
            "title": "Anime Movie",
            "year": "2024",
            "original_title": "Anime Movie",
            "genre_ids": [TMDBGenreIDsMovies.ACTION],
            "raw_data": {"id": 123, "genre_ids": [28]},
        }
    }
    page.listbox.clear()
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    page.tmdb_id_entry.setText("123")
    complete_tmdb = {
        "id": 123,
        "title": "Anime Movie",
        "genres": [{"id": 16, "name": "Animation"}],
    }

    page._update_payload_data(
        {"tmdb_complete_data": {"success": True, "result": complete_tmdb}}
    )

    assert page.context.media_search.genres == [TMDBGenreIDsMovies.ANIMATION]
    assert page.context.media_search.genre_names == ("Animation",)


def test_manual_tmdb_id_with_no_genres_does_not_fall_back_to_the_stale_row(
    tmp_path: Path,
) -> None:
    # TMDB legitimately returns `genres: []` for some titles. A present-but-
    # empty list must be accepted as-is, not treated as "missing" and
    # backfilled with the previous, unrelated search row's genres.
    page = _make_page(tmp_path)
    item_name = "1) Some Movie (2024)"
    page.backend.media_data = {
        item_name: {
            "media_type": "Movie",
            "title": "Some Movie",
            "year": "2024",
            "original_title": "Some Movie",
            "genre_ids": [TMDBGenreIDsMovies.ACTION],
            "raw_data": {"id": 123, "genre_ids": [28]},
        }
    }
    page.listbox.clear()
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    page.tmdb_id_entry.setText("123")
    complete_tmdb = {
        "id": 123,
        "title": "Some Movie",
        "genres": [],
    }

    page._update_payload_data(
        {"tmdb_complete_data": {"success": True, "result": complete_tmdb}}
    )

    assert page.context.media_search.genres == []
    assert page.context.media_search.genre_names == ()


def test_user_entered_mal_id_survives_metadata_transformer_commit(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    item_name = "1) Anime Series (2024)"
    page.backend.media_data = {
        item_name: {
            "media_type": "Series",
            "title": "Anime Series",
            "year": "2024",
            "original_title": "Anime Series",
            "genre_ids": [],
            "raw_data": {"id": 123, "name": "Anime Series"},
        }
    }
    page.listbox.clear()
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    page.tmdb_id_entry.setText("123")
    transformed = MediaSearchPayload(
        media_type=MediaType.SERIES,
        tmdb_id="123",
        title="Provider Anime Title",
    )
    monkeypatch.setattr(page, "_ask_user_for_id", lambda _source: 4242)

    page._update_payload_data(
        {
            "ani_list_data": {"success": True, "result": None},
            "metadata_transformation": {"success": True, "result": transformed},
        }
    )

    assert page.context.media_search.title == "Provider Anime Title"
    assert page.context.media_search.anilist_data == {
        "id": "4242",
        "idMal": "4242",
    }
    assert page.context.media_search.anilist_id == "4242"
    assert page.context.media_search.mal_id == "4242"
    assert page.mal_id_entry.text() == "4242"


def test_cancelled_mal_prompt_does_not_store_a_fake_zero_id(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    item_name = "1) Anime Series (2024)"
    page.backend.media_data = {
        item_name: {
            "media_type": "Series",
            "title": "Anime Series",
            "year": "2024",
            "original_title": "Anime Series",
            "genre_ids": [],
            "raw_data": {"id": 123, "name": "Anime Series"},
        }
    }
    page.listbox.addItem(item_name)
    page.listbox.setCurrentRow(0)
    page.tmdb_id_entry.setText("123")
    monkeypatch.setattr(page, "_ask_user_for_id", lambda _source: None)

    page._update_payload_data({"ani_list_data": {"success": True, "result": None}})

    assert page.context.media_search.anilist_data is None
    assert page.context.media_search.anilist_id is None
    assert page.context.media_search.mal_id is None
    assert page.mal_id_entry.text() == ""


def test_series_row_genres_reach_the_id_parse_worker(
    monkeypatch, tmp_path: Path
) -> None:
    """A series row's genres are TMDBGenreIDsSeries members. Filtering for
    TMDBGenreIDsMovies dropped every one of them, so anime series never
    reached the AniList lookup."""
    captured: dict[str, object] = {}

    class _StubSignal:
        def connect(self, *_args: object, **_kwargs: object) -> None:
            return None

    class _CapturingWorker:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.job_finished = _StubSignal()
            self.job_failed = _StubSignal()

        def start(self) -> None:
            return None

    monkeypatch.setattr(
        "src.frontend.wizards.media_search.IDParseWorker", _CapturingWorker
    )

    page = _media_search_page_with_selected_row(
        tmp_path,
        media_type="tv",
        genre_ids=[TMDBGenreIDsSeries.ANIMATION],
    )
    page._search_other_ids()

    assert TMDBGenreIDsSeries.ANIMATION in captured["tmdb_genres"]  # type: ignore[operator]


def test_reset_page_restores_tmdb_placeholder(tmp_path: Path) -> None:
    page = _make_page(tmp_path)
    page.tmdb_id_entry.setPlaceholderText("Requires ID")

    page.reset_page()

    assert page.tmdb_id_entry.placeholderText() == "Automatic"
