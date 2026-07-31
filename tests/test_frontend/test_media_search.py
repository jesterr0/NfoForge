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
