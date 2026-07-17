from datetime import date, datetime
from pathlib import Path

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from src.backend.process import ProcessBackEnd
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.frontend.custom_widgets.series_episode_mapper import (
    NO_TVDB_EPISODE_DATA_MESSAGE,
    SeriesEpisodeMapper,
    match_by_absolute,
    match_by_air_date,
)
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.series import build_series_release_info


def _make_mapper_with_files(file_list: list[Path]) -> SeriesEpisodeMapper:
    # a QApplication instance is required to construct any QWidget
    QApplication.instance() or QApplication([])
    mapper = SeriesEpisodeMapper()
    mapper.media_input_payload = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=file_list,
    )
    return mapper


def test_build_series_release_info_uses_episode_mapping_for_pack() -> None:
    file_one = Path("Show.S02E03.mkv")
    file_two = Path("Show.S02E04.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show Season 2"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        series_episode_map={
            file_one: {"season": 2, "episode": 3},
            file_two: {"season": 2, "episode": 4},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.is_series is True
    assert release_info.is_pack is True
    assert release_info.season == 2
    assert release_info.episode_start == 3
    assert release_info.episode_end == 4
    assert release_info.display_tag == "S02"


def test_build_series_release_info_detects_special() -> None:
    file_path = Path("Show.S00E01.Special.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
    )

    release_info = build_series_release_info(media_input)

    assert release_info.is_special is True
    assert release_info.display_tag == "S00E01"


def test_release_info_token_kwargs_omit_episode_for_pack() -> None:
    file_one = Path("Show.S02E03.mkv")
    file_two = Path("Show.S02E04.mkv")
    release_info = build_series_release_info(
        MediaInputPayload(
            input_path=Path("Show Season 2"),
            media_type=MediaType.SERIES,
            file_list=[file_one, file_two],
            series_episode_map={
                file_one: {"season": 2, "episode": 3},
                file_two: {"season": 2, "episode": 4},
            },
            series_episode_format=EpisodeFormat.STANDARD,
        )
    )

    assert ProcessBackEnd._release_info_token_kwargs(
        release_info, MultiEpisodeStyle.RANGE
    ) == {
        "season_number": 2,
        "episode_number": None,
        "episode_format": EpisodeFormat.STANDARD,
        "multi_episode_style": MultiEpisodeStyle.RANGE,
    }


def test_is_valid_rejects_duplicate_episode_targets() -> None:
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    # both files mapped to S01E01
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 1},
    }
    assert mapper.is_valid() is False


def test_auto_match_files_carries_episode_range_for_multi_episode_file() -> None:
    # a single file spanning multiple episodes (e.g. "S01E01E02", common for
    # anime) should keep the full range instead of collapsing to episode 1
    file_path = Path("Show.S01E01E02.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {
        1: {
            1: {"name": "Episode One"},
            2: {"name": "Episode Two"},
        }
    }

    mapper._auto_match_files()

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 1
    assert mapping["episode"] == 1
    assert mapping["episode_end"] == 2


def test_auto_match_files_single_episode_has_no_episode_end() -> None:
    file_path = Path("Show.S01E01.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {1: {1: {"name": "Episode One"}}}

    mapper._auto_match_files()

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 1
    assert mapping["episode"] == 1
    assert mapping["episode_end"] is None


def test_build_series_release_info_reads_episode_end_from_single_file_mapping() -> None:
    # a single file's multi-episode range (not a multi-file pack) should
    # still surface via SeriesReleaseInfo.episode_end
    file_path = Path("Show.S01E01E02.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_map={
            file_path: {"season": 1, "episode": 1, "episode_end": 2},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == 1
    assert release_info.episode_start == 1
    assert release_info.episode_end == 2
    assert release_info.is_pack is False
    assert release_info.display_tag == "S01E01-E02"


def test_build_series_release_info_single_episode_mapping_unchanged() -> None:
    # mappings without an "episode_end" key still behave as a normal
    # single episode
    file_path = Path("Show.S01E01.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_map={file_path: {"season": 1, "episode": 1}},
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.episode_start == 1
    assert release_info.episode_end == 1
    assert release_info.display_tag == "S01E01"


def test_typed_episode_without_tvdb_data_still_stores_manual_mapping() -> None:
    # when TVDB has no episode data at all (or not for this specific
    # season/episode), a user-typed season/episode must still be stored
    # instead of the row being cleared -- otherwise is_valid() can never
    # be satisfied and the wizard has no Back button to escape the wall
    file_path = Path("Show.S05E12.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {}  # no TVDB episode data whatsoever

    season_item = mapper.files_table.item(0, 1)
    episode_item = mapper.files_table.item(0, 2)
    season_item.setText("5")
    episode_item.setText("12")

    assert file_path in mapper.file_episode_mappings
    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 5
    assert mapping["episode"] == 12
    assert mapping["episode_data"] == {
        "season": 5,
        "episode": 12,
        "name": None,
        "aired": None,
    }
    assert mapping["assignment_method"] == "manual"
    assert mapping["confidence"] == 1.0
    assert mapper.is_valid() is True


def test_typed_episode_present_in_tvdb_data_still_stores_as_before() -> None:
    # regression guard: an episode that DOES exist in the TVDB payload must
    # keep using the real episode_data, not the synthesized fallback
    file_path = Path("Show.S01E01.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {1: {1: {"name": "Pilot", "aired": "2020-01-01"}}}

    season_item = mapper.files_table.item(0, 1)
    episode_item = mapper.files_table.item(0, 2)
    season_item.setText("1")
    episode_item.setText("1")

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 1
    assert mapping["episode"] == 1
    assert mapping["episode_data"] == {"name": "Pilot", "aired": "2020-01-01"}
    assert mapping["episode_name"] == "Pilot"
    assert mapping["assignment_method"] == "manual"
    assert mapping["confidence"] == 1.0


def test_load_episode_data_shows_status_when_tvdb_episodes_empty() -> None:
    # TVDB returned a payload but with no episodes at all for this series --
    # the tree would otherwise stay empty with no explanation
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv")])
    mapper.media_search_payload = MediaSearchPayload(
        tvdb_data={"episodes_by_type": {}}
    )

    mapper._load_episode_data()

    assert mapper.episodes_stats_label.text() == NO_TVDB_EPISODE_DATA_MESSAGE
    assert mapper.has_tvdb_episode_data() is False


def test_load_episode_data_shows_status_when_tvdb_data_missing() -> None:
    # no TVDB lookup happened at all (tvdb_data is None)
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv")])
    mapper.media_search_payload = MediaSearchPayload(tvdb_data=None)

    mapper._load_episode_data()

    assert mapper.episodes_stats_label.text() == NO_TVDB_EPISODE_DATA_MESSAGE
    assert mapper.has_tvdb_episode_data() is False


def test_load_episode_data_populates_normally_when_tvdb_has_episodes() -> None:
    # sanity check: the status message must not leak into the normal path
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv")])
    mapper.media_search_payload = MediaSearchPayload(
        tvdb_data={
            "episodes_by_type": {
                0: {
                    "type_name": "Aired Order",
                    "episodes": [
                        {"seasonNumber": 1, "number": 1, "name": "Pilot"},
                    ],
                }
            }
        }
    )

    mapper._load_episode_data()

    assert mapper.has_tvdb_episode_data() is True
    assert mapper.episodes_stats_label.text() != NO_TVDB_EPISODE_DATA_MESSAGE
    assert "1 available" in mapper.episodes_stats_label.text()


def test_has_unmapped_files_reflects_mapping_completeness() -> None:
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    assert mapper.has_unmapped_files() is True

    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 2},
    }
    assert mapper.has_unmapped_files() is False


def test_on_table_item_changed_logs_instead_of_swallowing_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.frontend.custom_widgets import series_episode_mapper as mapper_module

    file_path = Path("Show.S01E01.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mapper, "_store_mapping", _boom)

    logged: list[str] = []
    monkeypatch.setattr(
        mapper_module.LOG,
        "warning",
        lambda source, message: logged.append(message),
    )

    season_item = mapper.files_table.item(0, 1)
    episode_item = mapper.files_table.item(0, 2)
    season_item.setText("1")
    episode_item.setText("1")

    assert len(logged) == 1
    assert "boom" in logged[0]
    assert file_path.name in logged[0]


def test_match_by_absolute_maps_files_to_absolute_numbered_episodes() -> None:
    files_parsed = {"ep25.mkv": 25, "ep26.mkv": 26}
    absolute_episodes = [
        {"seasonNumber": 2, "number": 3, "absoluteNumber": 25, "name": "Ep 25"},
        {"seasonNumber": 2, "number": 4, "absoluteNumber": 26, "name": "Ep 26"},
    ]

    matches = match_by_absolute(files_parsed, absolute_episodes)

    assert matches["ep25.mkv"]["seasonNumber"] == 2
    assert matches["ep25.mkv"]["number"] == 3
    assert matches["ep26.mkv"]["seasonNumber"] == 2
    assert matches["ep26.mkv"]["number"] == 4


def test_match_by_absolute_skips_unmatched_absolute_numbers() -> None:
    files_parsed = {"ep99.mkv": 99}
    absolute_episodes = [{"seasonNumber": 2, "number": 3, "absoluteNumber": 25}]

    assert match_by_absolute(files_parsed, absolute_episodes) == {}


def test_match_by_absolute_skips_files_with_no_parsed_number() -> None:
    files_parsed = {"no_number.mkv": None}
    absolute_episodes = [{"seasonNumber": 1, "number": 1, "absoluteNumber": 1}]

    assert match_by_absolute(files_parsed, absolute_episodes) == {}


def test_match_by_absolute_handles_empty_inputs() -> None:
    assert match_by_absolute({}, []) == {}
    assert match_by_absolute({"ep1.mkv": 1}, []) == {}
    assert match_by_absolute({}, [{"absoluteNumber": 1}]) == {}


def test_auto_match_files_matches_anime_absolute_numbered_file() -> None:
    # anime/absolute releases like "[Group] Show - 025.mkv" carry no season,
    # only an absolute episode number -- these should auto-match against
    # TVDB's absolute-order episode list when the Anime/Absolute release
    # format is active, even though the currently selected TVDB order
    # (defaulted to the first available type) is "Aired Order"
    file_path = Path("[Group] Show - 025.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show"),
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_format=EpisodeFormat.ANIME_ABSOLUTE,
    )
    media_search = MediaSearchPayload(
        tvdb_data={
            "episodes_by_type": {
                1: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": [
                        {
                            "seasonNumber": 2,
                            "number": 3,
                            "absoluteNumber": 25,
                            "name": "Ep 25",
                        },
                        {
                            "seasonNumber": 2,
                            "number": 4,
                            "absoluteNumber": 26,
                            "name": "Ep 26",
                        },
                    ],
                },
                3: {
                    "type_name": "Absolute Order",
                    "type": "absolute",
                    "episodes": [
                        {
                            "seasonNumber": 2,
                            "number": 3,
                            "absoluteNumber": 25,
                            "name": "Ep 25",
                        },
                        {
                            "seasonNumber": 2,
                            "number": 4,
                            "absoluteNumber": 26,
                            "name": "Ep 26",
                        },
                    ],
                },
            }
        }
    )

    QApplication.instance() or QApplication([])
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 2
    assert mapping["episode"] == 3
    assert mapping["assignment_method"] == "absolute"


def test_auto_match_files_does_not_absolute_match_real_season_not_in_tvdb() -> None:
    # a file with a REAL parsed season (e.g. "Show.S05E03.mkv") that TVDB has
    # no data for must NOT be reinterpreted as an absolute-numbered anime
    # file just because its episode digit collides with some unrelated
    # absoluteNumber elsewhere in the series -- absolute matching is only
    # for genuinely season-less parses. A season that fails stage 1 must
    # fall through to fuzzy/unmatched, never get hijacked by stage 1b.
    file_path = Path("Show.S05E03.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show"),
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_format=EpisodeFormat.ANIME_ABSOLUTE,
    )
    media_search = MediaSearchPayload(
        tvdb_data={
            "episodes_by_type": {
                1: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": [
                        {
                            "seasonNumber": 1,
                            "number": 1,
                            "absoluteNumber": 1,
                            "name": "Totally Unrelated Episode",
                        },
                    ],
                },
                3: {
                    "type_name": "Absolute Order",
                    "type": "absolute",
                    "episodes": [
                        {
                            "seasonNumber": 1,
                            "number": 3,
                            "absoluteNumber": 3,
                            "name": "Totally Unrelated Episode",
                        },
                    ],
                },
            }
        }
    )

    QApplication.instance() or QApplication([])
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapping = mapper.file_episode_mappings.get(file_path)
    assert mapping is None or mapping["assignment_method"] != "absolute"


def test_auto_match_files_translates_episode_end_through_absolute_index() -> None:
    # a multi-episode anime/absolute file (e.g. "[Group] Show - 025-026.mkv")
    # parses to guessit episode=[25, 26] -> episode=25, episode_end=26. Once
    # the absolute stage translates the primary episode (25 -> S02E03), the
    # range end must be translated through the SAME absolute index (26 ->
    # S02E04) instead of being carried through as the raw absolute number 26.
    file_path = Path("[Group] Show - 025-026.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show"),
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_format=EpisodeFormat.ANIME_ABSOLUTE,
    )
    media_search = MediaSearchPayload(
        tvdb_data={
            "episodes_by_type": {
                3: {
                    "type_name": "Absolute Order",
                    "type": "absolute",
                    "episodes": [
                        {
                            "seasonNumber": 2,
                            "number": 3,
                            "absoluteNumber": 25,
                            "name": "Ep 25",
                        },
                        {
                            "seasonNumber": 2,
                            "number": 4,
                            "absoluteNumber": 26,
                            "name": "Ep 26",
                        },
                    ],
                },
            }
        }
    )

    QApplication.instance() or QApplication([])
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 2
    assert mapping["episode"] == 3
    assert mapping["episode_end"] == 4
    assert mapping["assignment_method"] == "absolute"


def test_match_by_absolute_duplicate_absolute_numbers_first_wins() -> None:
    # if TVDB data ever contains two entries sharing the same absoluteNumber
    # (e.g. a data glitch or overlapping season types), the first one seen
    # must win rather than being silently overwritten by a later duplicate.
    files_parsed = {"ep25.mkv": 25}
    absolute_episodes = [
        {"seasonNumber": 2, "number": 3, "absoluteNumber": 25, "name": "First"},
        {"seasonNumber": 9, "number": 9, "absoluteNumber": 25, "name": "Second"},
    ]

    matches = match_by_absolute(files_parsed, absolute_episodes)

    assert matches["ep25.mkv"]["name"] == "First"
    assert matches["ep25.mkv"]["seasonNumber"] == 2
    assert matches["ep25.mkv"]["number"] == 3


def test_correcting_unverified_episode_to_tvdb_match_clears_amber_cells() -> None:
    # typing an episode with no TVDB match paints the season/episode cells
    # amber (unverified). Correcting the value to one that DOES exist in
    # TVDB must clear that amber so the row no longer looks unverified.
    unverified_color = QColor(255, 205, 120)
    file_path = Path("Show.S05E12.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {1: {1: {"name": "Pilot", "aired": "2020-01-01"}}}

    season_item = mapper.files_table.item(0, 1)
    episode_item = mapper.files_table.item(0, 2)

    # step 1: type a season/episode with no TVDB match -> amber
    season_item.setText("5")
    episode_item.setText("12")
    assert season_item.background().color() == unverified_color
    assert episode_item.background().color() == unverified_color

    # step 2: correct it to a season/episode that DOES exist in TVDB ->
    # amber must be cleared (season/episode cells no longer stale)
    season_item.setText("1")
    episode_item.setText("1")
    assert season_item.background().color() != unverified_color
    assert episode_item.background().color() != unverified_color

    # step 3: blank the fields -> amber must also be cleared
    season_item.setText("5")
    episode_item.setText("12")
    assert season_item.background().color() == unverified_color

    season_item.setText("")
    episode_item.setText("")
    assert season_item.background().color() != unverified_color
    assert episode_item.background().color() != unverified_color


def test_match_by_air_date_matches_file_parsed_date_to_episode_aired_date() -> None:
    files_parsed = {"Show.2024.05.01.mkv": date(2024, 5, 1)}
    episodes = [
        {"seasonNumber": 1, "number": 1, "aired": "2024-05-01", "name": "Day One"},
        {"seasonNumber": 1, "number": 2, "aired": "2024-05-02", "name": "Day Two"},
    ]

    matches = match_by_air_date(files_parsed, episodes)

    assert matches["Show.2024.05.01.mkv"]["seasonNumber"] == 1
    assert matches["Show.2024.05.01.mkv"]["number"] == 1
    assert matches["Show.2024.05.01.mkv"]["name"] == "Day One"


def test_match_by_air_date_normalizes_datetime_against_iso_string() -> None:
    # guessit can return either a `datetime.date` or `datetime.datetime` for
    # a parsed date; the episode's "aired" field is always an ISO
    # "YYYY-MM-DD" string. Both must normalize to the same comparison key.
    files_parsed = {"a.mkv": datetime(2024, 5, 1, 0, 0, 0), "b.mkv": date(2024, 5, 1)}
    episodes = [{"seasonNumber": 1, "number": 1, "aired": "2024-05-01"}]

    matches = match_by_air_date(files_parsed, episodes)

    assert matches["a.mkv"]["number"] == 1
    assert matches["b.mkv"]["number"] == 1


def test_match_by_air_date_skips_unmatched_dates() -> None:
    files_parsed = {"Show.2024.12.25.mkv": date(2024, 12, 25)}
    episodes = [{"seasonNumber": 1, "number": 1, "aired": "2024-05-01"}]

    assert match_by_air_date(files_parsed, episodes) == {}


def test_match_by_air_date_skips_files_with_no_parsed_date() -> None:
    files_parsed = {"no_date.mkv": None}
    episodes = [{"seasonNumber": 1, "number": 1, "aired": "2024-05-01"}]

    assert match_by_air_date(files_parsed, episodes) == {}


def test_match_by_air_date_handles_empty_inputs() -> None:
    assert match_by_air_date({}, []) == {}
    assert match_by_air_date({"a.mkv": date(2024, 5, 1)}, []) == {}
    assert match_by_air_date({}, [{"aired": "2024-05-01"}]) == {}


def test_auto_match_files_matches_daily_date_release() -> None:
    # a daily/date release like "Show.2024.05.01.mkv" carries no
    # season/episode -- only a date -- so stage 1 never matches it. With
    # the Daily/Date release format active, it should auto-match against
    # the episode whose "aired" field equals the parsed date.
    file_path = Path("Show.2024.05.01.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show"),
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_format=EpisodeFormat.DAILY_DATE,
    )
    media_search = MediaSearchPayload(
        tvdb_data={
            "episodes_by_type": {
                0: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": [
                        {
                            "seasonNumber": 1,
                            "number": 1,
                            "aired": "2024-05-01",
                            "name": "Day One",
                        },
                        {
                            "seasonNumber": 1,
                            "number": 2,
                            "aired": "2024-05-02",
                            "name": "Day Two",
                        },
                    ],
                },
            }
        }
    )

    QApplication.instance() or QApplication([])
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 1
    assert mapping["episode"] == 1
    assert mapping["assignment_method"] == "daily"


def test_auto_match_files_does_not_daily_match_file_with_real_season_episode() -> None:
    # regression guard (mirrors the absolute-matching hijack bug): a normal
    # "Show.S02E03.mkv" file must NOT be reinterpreted as a daily/date
    # release just because the Daily/Date release format happens to be
    # active. TVDB has no data for this exact season/episode (so stage 1
    # can't match it either), but the file still carries a genuinely
    # parsed season+episode, so it must fall through to fuzzy/unmatched
    # instead of ever being stored via the "daily" method.
    file_path = Path("Show.S02E03.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show"),
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_format=EpisodeFormat.DAILY_DATE,
    )
    media_search = MediaSearchPayload(
        tvdb_data={
            "episodes_by_type": {
                0: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": [
                        {
                            "seasonNumber": 1,
                            "number": 1,
                            "aired": "2024-05-01",
                            "name": "Totally Unrelated Episode",
                        },
                    ],
                },
            }
        }
    )

    QApplication.instance() or QApplication([])
    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapping = mapper.file_episode_mappings.get(file_path)
    assert mapping is None or mapping["assignment_method"] != "daily"
