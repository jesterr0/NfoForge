"""Matching a series pack's files to TVDB episodes without the mapper widget."""

from pathlib import Path

from nfoforge.core.series.match import (
    EpisodeMatcher,
    coerce_season,
    episodes_for_ordering,
    parse_episode_file,
)
from nfoforge.enums.series import EpisodeFormat


def test_the_episode_title_comes_from_the_filename_not_its_directory() -> None:
    """GuessIt was handed the whole path, so the folders competed for it.

    For a pack inside a folder carrying its own release info, the grandparent
    was read as the show and every file's episode title came back as the
    containing directory's name -- the same wrong value for the whole pack,
    invisible until fuzzy matching read it.
    """
    parsed = parse_episode_file(
        Path(
            "C:/Users/someone/Downloads/Show.S01.BluRay.1080p.x264-G/Show.S01E03.Starstruck.1080p.mkv"
        )
    )

    assert parsed["episode_title"] == "Starstruck"
    assert parsed["season"] == 1
    assert parsed["episode"] == 3


def test_a_season_carried_only_by_a_parent_folder_is_still_found() -> None:
    """Nested packs keep bare filenames under a ``Season NN`` directory."""
    parsed = parse_episode_file(Path("X:/Show/Season 02/ep05.mkv"))

    assert parsed["season"] == 2
    assert parsed["episode"] == 5


def _episode(season: int, number: int, name: str, **extra: object) -> dict:
    return {"seasonNumber": season, "number": number, "name": name, **extra}


AIRED = [
    _episode(1, 1, "Pilot", aired="2024-01-01", absoluteNumber=1),
    _episode(1, 2, "Lost & Found", aired="2024-01-08", absoluteNumber=2),
    _episode(1, 3, "Starstruck", aired="2024-01-15", absoluteNumber=3),
]


def _matcher(**kwargs: object) -> EpisodeMatcher:
    matcher = EpisodeMatcher(
        episodes_by_type={
            1: {"type": "default", "type_name": "Aired Order", "episodes": AIRED},
            2: {"type": "absolute", "type_name": "Absolute", "episodes": AIRED},
        },
        show_title="Show",
        **kwargs,  # type: ignore[arg-type]
    )
    matcher.use_ordering(1)
    return matcher


def test_coerce_season() -> None:
    assert coerce_season(2) == 2
    assert coerce_season([3, 4]) == 3
    assert coerce_season([]) is None
    assert coerce_season("2") is None


def test_episodes_for_ordering() -> None:
    episodes = episodes_for_ordering({1: {"episodes": AIRED}}, 1)

    assert sorted(episodes[1]) == [1, 2, 3]
    assert episodes_for_ordering({1: {"episodes": AIRED}}, 9) == {}


def test_a_stated_number_the_ordering_lists_is_a_regex_match() -> None:
    matcher = _matcher()
    file = Path("Show.S01E02.Lost.and.Found.1080p.mkv")

    counts = matcher.match_files([file])

    mapping = matcher.mappings[file]
    assert (counts.matched, counts.fuzzy) == (1, 0)
    assert (mapping["season"], mapping["episode"]) == (1, 2)
    assert mapping["assignment_method"] == "regex"
    assert mapping["verified"] is True
    assert mapping["episode_order_type_id"] == 1


def test_a_multi_episode_file_keeps_its_span() -> None:
    matcher = _matcher()
    file = Path("Show.S01E01E02.mkv")

    matcher.match_files([file])

    assert matcher.mappings[file]["episode_list"] == [1, 2]
    assert matcher.mappings[file]["episode_end"] == 2


def test_a_number_the_ordering_lacks_is_kept_unverified() -> None:
    matcher = _matcher()
    file = Path("Show.S01E98.Something.Else.mkv")

    matcher.match_files([file])

    mapping = matcher.mappings[file]
    assert mapping["episode"] == 98
    assert mapping["verified"] is False


def test_a_title_naming_a_listed_episode_rescues_a_wrong_number() -> None:
    matcher = _matcher()
    file = Path("Show.S01E97.Starstruck.mkv")

    matcher.match_files([file])

    assert matcher.mappings[file]["episode"] == 3
    assert matcher.mappings[file]["assignment_method"] == "title"


def test_absolute_numbers_match_in_absolute_format() -> None:
    matcher = _matcher(series_format=EpisodeFormat.ANIME_ABSOLUTE)
    file = Path("[Group] Show - 003.mkv")

    matcher.match_files([file])

    mapping = matcher.mappings[file]
    assert (mapping["season"], mapping["episode"]) == (1, 3)
    assert mapping["assignment_method"] == "absolute"
    assert mapping["episode_order_type_id"] == 2


def test_air_dates_match_in_daily_format() -> None:
    matcher = _matcher(series_format=EpisodeFormat.DAILY_DATE)
    file = Path("Show.2024.01.08.mkv")

    matcher.match_files([file])

    assert matcher.mappings[file]["episode"] == 2
    assert matcher.mappings[file]["assignment_method"] == "daily"


def test_a_title_alone_is_a_fuzzy_match() -> None:
    matcher = _matcher()
    file = Path("Show - Starstruck.mkv")

    counts = matcher.match_files([file])

    assert counts.fuzzy == 1
    assert matcher.mappings[file]["episode"] == 3
    assert matcher.mappings[file]["assignment_method"] == "fuzzy"


def test_fuzzy_matching_can_be_switched_off() -> None:
    matcher = _matcher(fuzzy_enabled=False)
    file = Path("Show - Starstruck.mkv")

    matcher.match_files([file])

    assert file not in matcher.mappings


def test_existing_mappings_can_be_preserved() -> None:
    matcher = _matcher()
    file = Path("Show.S01E02.mkv")
    matcher.mappings[file] = {"season": 1, "episode": 3, "episode_list": [3]}

    matcher.match_files([file], preserve_existing=True)
    assert matcher.mappings[file]["episode"] == 3

    matcher.match_files([file])
    assert matcher.mappings[file]["episode"] == 2


def test_nothing_is_matched_without_episodes() -> None:
    matcher = EpisodeMatcher()

    assert matcher.match_files([Path("Show.S01E01.mkv")]).matched == 0
    assert matcher.mappings == {}
