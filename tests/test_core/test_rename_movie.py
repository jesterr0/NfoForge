"""Renaming a movie without the Rename page."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from pymediainfo import MediaInfo
import pytest

from nfoforge.config.config import ConfigManager
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.rename.movie import (
    MovieRenameChoices,
    commit_movie_rename,
    detect_movie_choices,
    movie_name_problems,
    movie_override_tokens,
    movie_quality_problem,
    movie_rename_map,
)
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.rename import QualitySelection
from nfoforge.payloads.media_inputs import MediaInputPayload
from nfoforge.payloads.media_search import MediaSearchPayload
from tests.repo_paths import build_app_paths


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", build_app_paths(tmp_path))


def _context(*files: str, input_path: Path = Path("Movie Folder")) -> ProcessingContext:
    return ProcessingContext(
        media_input=MediaInputPayload(
            input_path=input_path,
            media_type=MediaType.MOVIE,
            file_list=[Path(name) for name in files],
        ),
        media_search=MediaSearchPayload(media_type=MediaType.MOVIE, title="Movie"),
    )


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------
def test_claims_become_choices(config: ConfigManager) -> None:
    context = _context("Movie.2024.Directors.Cut.IMAX.REPACK.1080p.BluRay.x264-GRP.mkv")

    choices = detect_movie_choices(context, config.settings)

    assert choices.edition == "Directors Cut"
    assert choices.frame_size == "IMAX"
    assert choices.re_release == "REPACK"
    assert choices.quality is QualitySelection.BLURAY


def test_only_the_film_is_read_not_its_extras(config: ConfigManager) -> None:
    context = _context(
        "Movie.2024.1080p.BluRay.REMUX.AVC-GRP.mkv", "Deleted-Scenes.mkv"
    )

    assert detect_movie_choices(context, config.settings).remux is True


def test_remux_needs_a_disc_source(config: ConfigManager) -> None:
    context = _context("Movie.2024.1080p.WEB-DL.REMUX.x264-GRP.mkv")

    choices = detect_movie_choices(context, config.settings)

    assert choices.quality is QualitySelection.WEB_DL
    assert choices.remux is False


def test_a_plugin_localization_beats_the_filename(config: ConfigManager) -> None:
    context = _context("Movie.2024.DUBBED.1080p.BluRay.x264-GRP.mkv")
    context.shared_data.dynamic_data["localization_override"] = "Subbed"

    assert detect_movie_choices(context, config.settings).localization == "Subbed"


def test_a_plugin_value_the_page_would_not_offer_is_ignored(
    config: ConfigManager,
) -> None:
    context = _context("Movie.2024.1080p.BluRay.x264-GRP.mkv")
    context.shared_data.dynamic_data["localization_override"] = "Klingon"

    assert detect_movie_choices(context, config.settings).localization == ""


def test_the_configured_group_beats_the_detected_one(config: ConfigManager) -> None:
    config.settings.general.release_group = "MINE"
    context = _context("Movie.2024.1080p.BluRay.x264-THEIRS.mkv")

    assert detect_movie_choices(context, config.settings).release_group == "MINE"


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------
def test_blank_choices_are_left_out_but_the_group_is_always_there() -> None:
    tokens = movie_override_tokens(MovieRenameChoices(hybrid=True))

    assert tokens == {"hybrid": "HYBRID", "release_group": ""}


# --------------------------------------------------------------------------
# checks and the rename map
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("", "empty"),
        ("Movie.2024.Subbed.Dubbed", "'Subbed' and 'Dubbed'"),
        ("Movie.2024.IMAX.Open.Matte", "'IMAX' and 'Open Matte'"),
    ],
)
def test_name_problems(name: str, problem: str) -> None:
    problems = movie_name_problems(name, Path("x.mkv"))

    assert problems and problem in problems[0]


def test_a_good_name_has_no_problems() -> None:
    assert movie_name_problems("Movie.2024.1080p", Path("x.mkv")) == []
    assert movie_name_problems("Movie", Path("no-extension")) != []


def test_only_standard_definition_qualities_are_checked() -> None:
    media = Path("Movie.mkv")
    media_input = MediaInputPayload(
        input_path=media,
        file_list=[media],
        file_list_mediainfo={
            media: cast(
                MediaInfo,
                SimpleNamespace(
                    video_tracks=[SimpleNamespace(width=1920, height=1080)],
                    general_tracks=[SimpleNamespace()],
                ),
            )
        },
    )

    assert movie_quality_problem(QualitySelection.BLURAY, media_input) is None
    assert movie_quality_problem(None, media_input) is None


def test_a_folder_holding_the_film_is_renamed_with_it(tmp_path: Path) -> None:
    folder = tmp_path / "Old"
    folder.mkdir()
    film = folder / "old.mkv"
    context = _context(str(film), input_path=folder)

    assert movie_rename_map(context.media_input, "Movie.2020") == {
        film: tmp_path / "Movie.2020" / "Movie.2020.mkv"
    }


def test_a_single_file_is_renamed_in_place(tmp_path: Path) -> None:
    film = tmp_path / "old.mkv"
    context = _context(str(film), input_path=film)

    assert movie_rename_map(context.media_input, "Movie.2020") == {
        film: tmp_path / "Movie.2020.mkv"
    }
    assert movie_rename_map(context.media_input, "old") == {}


# --------------------------------------------------------------------------
# committing
# --------------------------------------------------------------------------
def test_commit_records_overrides_and_reason_globals() -> None:
    context = _context("x.mkv")
    added: dict[str, str] = {}
    context.jinja_engine = cast(
        Any, SimpleNamespace(add_global=lambda k, v, _o: added.__setitem__(k, v))
    )

    commit_movie_rename(
        context,
        MovieRenameChoices(
            edition="Directors Cut",
            repack_reason="Repacked due to audio issues",
            proper_reason="ignored, repack wins",
        ),
        {"edition": "Directors Cut", "release_group": "GRP"},
        "Movie.2024.REPACK2.1080p",
    )

    dynamic = context.shared_data.dynamic_data
    assert dynamic["edition_override"] == "Directors Cut"
    assert "frame_size_override" not in dynamic
    assert dynamic["override_tokens"] == {
        "edition": "Directors Cut",
        "release_group": "GRP",
    }
    assert added == {
        "repack_reason": "Repacked due to audio issues",
        "repack_n": "REPACK2",
    }
