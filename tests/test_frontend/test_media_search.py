from collections import OrderedDict
from pathlib import Path

from PySide6.QtWidgets import QMessageBox
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.exceptions import MediaParsingError
from src.frontend.wizards.media_search import MediaSearch
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


def test_title_guess_uses_first_title_when_guessit_returns_a_list(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    monkeypatch.setattr(
        "src.frontend.wizards.media_search.guessit",
        lambda *_args, **_kwargs: {"title": ["Primary", "Alternative"], "year": 2024},
    )

    assert page._get_title_only(Path("ignored.mkv")) == "Primary 2024"


def test_title_guess_uses_guessit_title_without_year(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    monkeypatch.setattr(
        "src.frontend.wizards.media_search.guessit",
        lambda *_args, **_kwargs: {"title": "Movie"},
    )

    assert page._get_title_only(Path("Movie.mkv")) == "Movie"


def test_title_guess_raises_when_guessit_has_no_title(
    monkeypatch, tmp_path: Path
) -> None:
    page = _make_page(tmp_path)
    monkeypatch.setattr(
        "src.frontend.wizards.media_search.guessit",
        lambda *_args, **_kwargs: {"year": 2024},
    )

    with pytest.raises(MediaParsingError):
        page._get_title_only(Path("1080p.BluRay.mkv"))


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
