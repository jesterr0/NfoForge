"""Renaming a series pack without the Rename page."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from nfoforge.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from nfoforge.config.config import ConfigManager
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.core.rename.choices import RenameChoices, common_value
from nfoforge.core.rename.series import (
    NoEpisodeNamesError,
    SeriesNotMappedError,
    build_series_rename,
    commit_series_rename,
    detect_episode_claims,
    detect_series_choices,
    detected_episode_claims,
)
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.rename import QualitySelection
from nfoforge.enums.series import EpisodeFormat
from nfoforge.payloads.media_inputs import MediaInputPayload
from nfoforge.payloads.media_search import MediaSearchPayload
from tests.repo_paths import build_app_paths

TOKEN = "{title_clean} S{season_number|zfill(2)}E{episode_number|zfill(2)}"  # noqa: S105 - token template, not a credential


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", build_app_paths(tmp_path / "config"))


def _context(
    episodes: dict[Path, tuple[int, int]], input_path: Path = Path("Show")
) -> ProcessingContext:
    return ProcessingContext(
        media_input=MediaInputPayload(
            input_path=input_path,
            media_type=MediaType.SERIES,
            file_list=list(episodes),
            series_episode_map={
                path: {"season": season, "episode": episode}
                for path, (season, episode) in episodes.items()
            },
            series_episode_format=EpisodeFormat.STANDARD,
        ),
        media_search=MediaSearchPayload(media_type=MediaType.SERIES, title="Show"),
    )


# --------------------------------------------------------------------------
# pack choices
# --------------------------------------------------------------------------
def test_a_claim_is_the_packs_only_when_every_episode_agrees(
    config: ConfigManager,
) -> None:
    context = _context(
        {
            Path("Show.S01E01.REPACK.1080p.BluRay.REMUX-GRP.mkv"): (1, 1),
            Path("Show.S01E02.720p.WEB-DL-OTHER.mkv"): (1, 2),
        }
    )

    choices = detect_series_choices(context, config.settings)

    assert choices.re_release == ""
    assert choices.remux is False
    assert choices.quality is None


def test_an_agreed_quality_is_the_packs(config: ConfigManager) -> None:
    context = _context(
        {
            Path("Show.S01E01.1080p.BluRay.x264-GRP.mkv"): (1, 1),
            Path("Show.S01E02.1080p.BluRay.x264-GRP.mkv"): (1, 2),
        }
    )

    assert detect_series_choices(context, config.settings).quality is (
        QualitySelection.BLURAY
    )


def test_common_value() -> None:
    assert common_value([1, 1, 1]) == 1
    assert common_value([1, 2]) is None
    assert common_value([]) is None


# --------------------------------------------------------------------------
# episode claims
# --------------------------------------------------------------------------
def test_episodes_are_ordered_by_season_then_episode(config: ConfigManager) -> None:
    context = _context(
        {
            Path("b.S02E01.mkv"): (2, 1),
            Path("a.S01E02.mkv"): (1, 2),
            Path("c.S01E01.mkv"): (1, 1),
        }
    )

    ordered = [path.name for path, _ in detect_episode_claims(context, config.settings)]

    assert ordered == ["c.S01E01.mkv", "a.S01E02.mkv", "b.S02E01.mkv"]


def test_each_episode_keeps_its_own_claims(config: ConfigManager) -> None:
    repack = Path("Show.S01E01.REPACK.1080p.WEB-DL-GRP.mkv")
    plain = Path("Show.S01E02.1080p.WEB-DL-GRP.mkv")
    context = _context({repack: (1, 1), plain: (1, 2)})

    claims = detected_episode_claims(context, config.settings)

    assert claims(repack).get("re_release") == "REPACK"
    assert "re_release" not in claims(plain)
    assert claims(Path("unmapped.mkv")) == {}


# --------------------------------------------------------------------------
# rename targets
# --------------------------------------------------------------------------
def _episodes_on_disk(tmp_path: Path, *names: str) -> dict[Path, tuple[int, int]]:
    folder = tmp_path / "Show.Pack"
    folder.mkdir()
    episodes = {}
    for index, name in enumerate(names, start=1):
        path = folder / name
        path.touch()
        episodes[path] = (1, index)
    return episodes


def test_every_episode_and_its_sidecars_are_renamed(
    tmp_path: Path, config: ConfigManager
) -> None:
    config.settings.series.season_folder_token = ""
    episodes = _episodes_on_disk(tmp_path, "ep1.mkv", "ep2.mkv")
    first = next(iter(episodes))
    first.with_suffix(".en.srt").touch()
    context = _context(episodes, input_path=first.parent)

    targets = build_series_rename(
        context,
        config.settings,
        RenameEncodeSeriesBackEnd(),
        token=TOKEN,
        episode_claims=lambda _path: {},
    )

    names = sorted(target.name for target in targets.files.values())
    assert names == ["Show.S01E01.en.srt", "Show.S01E01.mkv", "Show.S01E02.mkv"]
    assert targets.failed == []


def test_an_episode_without_a_name_is_left_and_reported(
    tmp_path: Path, config: ConfigManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    episodes = _episodes_on_disk(tmp_path, "ep1.mkv", "ep2.mkv")
    bad = list(episodes)[1]
    real = RenameEncodeSeriesBackEnd.series_renamer

    def renamer(self: Any, **kwargs: Any) -> Path | None:
        return None if kwargs["media_file"] == bad else real(self, **kwargs)

    monkeypatch.setattr(RenameEncodeSeriesBackEnd, "series_renamer", renamer)

    targets = build_series_rename(
        _context(episodes, input_path=bad.parent),
        config.settings,
        RenameEncodeSeriesBackEnd(),
        token=TOKEN,
        episode_claims=lambda _path: {},
    )

    assert targets.failed == [bad]
    assert bad not in targets.files


def test_no_names_at_all_is_an_error(
    tmp_path: Path, config: ConfigManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    episodes = _episodes_on_disk(tmp_path, "ep1.mkv")
    monkeypatch.setattr(
        RenameEncodeSeriesBackEnd, "series_renamer", lambda self, **_k: None
    )

    with pytest.raises(NoEpisodeNamesError, match="ep1.mkv"):
        build_series_rename(
            _context(episodes),
            config.settings,
            RenameEncodeSeriesBackEnd(),
            token=TOKEN,
            episode_claims=lambda _path: {},
        )


def test_an_unmapped_pack_is_an_error(config: ConfigManager) -> None:
    context = _context({})

    with pytest.raises(SeriesNotMappedError):
        build_series_rename(
            context,
            config.settings,
            RenameEncodeSeriesBackEnd(),
            token=TOKEN,
            episode_claims=lambda _path: {},
        )


# --------------------------------------------------------------------------
# committing
# --------------------------------------------------------------------------
def test_commit_records_overrides_and_the_reason_pattern() -> None:
    context = _context({})
    added: dict[str, str] = {}
    context.jinja_engine = cast(
        Any, SimpleNamespace(add_global=lambda k, v, _o: added.__setitem__(k, v))
    )

    commit_series_rename(
        context,
        RenameChoices(frame_size="IMAX", proper_reason="Proper for superior audio"),
        {"release_group": "GRP"},
    )

    dynamic = context.shared_data.dynamic_data
    assert dynamic["frame_size_override"] == "IMAX"
    assert dynamic["override_tokens"] == {"release_group": "GRP"}
    assert added == {
        "proper_reason": "Proper for superior audio",
        "proper_pattern": r"(proper\d*)",
    }
