from datetime import date, datetime
from pathlib import Path

from PySide6.QtGui import QColor
import pytest

from src.backend.process import ProcessBackEnd
from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.frontend.custom_widgets.series_episode_mapper import (
    NO_TVDB_EPISODE_DATA_MESSAGE,
    SeriesEpisodeMapper,
    match_by_absolute,
    match_by_air_date,
)
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload
from src.payloads.series import (
    SeriesReleaseInfo,
    build_series_release_info,
    describe_missing_upload_fields,
    describe_multi_season_pack,
)


def _make_mapper_with_files(file_list: list[Path]) -> SeriesEpisodeMapper:
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


def test_season_tag_with_season_end_none_direct_construction() -> None:
    # build_series_release_info always sets season_end (via max()), so this
    # exercises SeriesReleaseInfo's own season_tag/is_special defaults when
    # constructed directly with season_end left at None -- a specials
    # season (0) must still render "S00" and be flagged special, and a
    # normal season must still render its own tag, not blow up on the
    # missing season_end.
    specials = SeriesReleaseInfo(
        media_type=MediaType.SERIES,
        input_path=None,
        primary_file=None,
        title_path=None,
        season=0,
        season_end=None,
    )
    assert specials.season_tag == "S00"
    assert specials.is_special is True

    season_two = SeriesReleaseInfo(
        media_type=MediaType.SERIES,
        input_path=None,
        primary_file=None,
        title_path=None,
        season=2,
        season_end=None,
    )
    assert season_two.season_tag == "S02"
    assert season_two.is_special is False


def test_build_series_release_info_multi_season_pack_renders_season_range() -> None:
    # a pack spanning multiple seasons (e.g. S01-S05) must keep the season
    # span instead of collapsing to the lowest season via min()
    file_one = Path("Show.S01E01.mkv")
    file_two = Path("Show.S05E10.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show Seasons 1-5"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        series_episode_map={
            file_one: {"season": 1, "episode": 1},
            file_two: {"season": 5, "episode": 10},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == 1
    assert release_info.season_end == 5
    assert release_info.display_tag == "S01-S05"


def test_build_series_release_info_single_season_pack_tag_unchanged() -> None:
    # a pack confined to a single season must still render "S02", not a
    # degenerate "S02-S02" range
    file_one = Path("Show.S02E01.mkv")
    file_two = Path("Show.S02E02.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show Season 2"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        series_episode_map={
            file_one: {"season": 2, "episode": 1},
            file_two: {"season": 2, "episode": 2},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == 2
    assert release_info.season_end in (2, None)
    assert release_info.display_tag == "S02"


def test_build_series_release_info_single_episode_season_end_unchanged() -> None:
    # a single episode (not a pack) must render exactly as before
    file_path = Path("Show.S01E01.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_map={file_path: {"season": 1, "episode": 1}},
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == 1
    assert release_info.season_end in (1, None)
    assert release_info.display_tag == "S01E01"


def test_build_series_release_info_pure_specials_pack_is_special() -> None:
    # a pack where every season is 0 is a genuine specials pack
    file_one = Path("Show.S00E01.mkv")
    file_two = Path("Show.S00E02.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show Specials"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        series_episode_map={
            file_one: {"season": 0, "episode": 1},
            file_two: {"season": 0, "episode": 2},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == 0
    assert release_info.season_end == 0
    assert release_info.is_special is True


def test_build_series_release_info_mixed_specials_and_season_pack_not_special() -> None:
    # a pack containing season 0 alongside a real season must NOT be flagged
    # special -- season == 0 only because min() picks the specials season
    file_one = Path("Show.S00E01.mkv")
    file_two = Path("Show.S01E01.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show Season 1 Plus Specials"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        series_episode_map={
            file_one: {"season": 0, "episode": 1},
            file_two: {"season": 1, "episode": 1},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == 0
    assert release_info.season_end == 1
    assert release_info.is_special is False


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
        "season_end": 2,
        "episode_number": None,
        "episode_format": EpisodeFormat.STANDARD,
        "multi_episode_style": MultiEpisodeStyle.RANGE,
    }


def test_release_info_token_kwargs_multi_season_pack_feeds_range_into_token_replacer() -> (
    None
):
    # end-to-end proof of the bug this task fixes: a complete-series pack
    # spanning seasons 1-5 must title/NFO as "S01-S05", not collapse to just
    # the lowest season ("S01"). release_info -> _release_info_token_kwargs
    # -> TokenReplacer -> the default series token shape
    # ("S{season_number|zfill(2)}").
    file_one = Path("Show.S01E01.mkv")
    file_two = Path("Show.S05E10.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show Seasons 1-5"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        series_episode_map={
            file_one: {"season": 1, "episode": 1},
            file_two: {"season": 5, "episode": 10},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )
    release_info = build_series_release_info(media_input)

    kwargs = ProcessBackEnd._release_info_token_kwargs(
        release_info, MultiEpisodeStyle.RANGE
    )
    assert kwargs["season_number"] == 1
    assert kwargs["season_end"] == 5

    output = TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=MediaSearchPayload(media_type=MediaType.SERIES),
        token_string="S{season_number|zfill(2)}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        **kwargs,
    ).get_output()

    assert output == "S01-S05"


def test_is_valid_rejects_duplicate_episode_targets() -> None:
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    # both files mapped to S01E01
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 1},
    }
    assert mapper.is_valid() is False


def test_is_valid_rejects_overlapping_multi_episode_ranges() -> None:
    # file A claims S01E01-E02 (a multi-episode range) and file B claims
    # S01E02 alone -- their start tuples (1, 1) and (1, 2) differ, so an
    # exact-duplicate-only check would wrongly pass this, even though both
    # files claim S01E02.
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1, "episode_end": 2},
        Path("b.mkv"): {"season": 1, "episode": 2},
    }
    assert mapper.is_valid() is False


def test_is_valid_accepts_non_overlapping_multi_episode_ranges() -> None:
    # two files, each spanning a distinct pair of episodes -- no overlap
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1, "episode_end": 2},
        Path("b.mkv"): {"season": 1, "episode": 3, "episode_end": 4},
    }
    assert mapper.is_valid() is True


def test_is_valid_accepts_normal_single_episode_pack() -> None:
    # a normal pack where every file maps to exactly one, distinct episode
    # (no episode_end set) must still validate as before
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 2},
    }
    assert mapper.is_valid() is True


def test_is_valid_accepts_same_episode_number_across_different_seasons() -> None:
    # two files sharing the same episode number but in DIFFERENT seasons
    # (e.g. S01E01 and S02E01) must not be treated as a collision -- the
    # claimed-targets check keys on the (season, episode) pair, not the
    # episode number alone.
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 2, "episode": 1},
    }
    assert mapper.is_valid() is True


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


def test_auto_match_records_the_selected_episode_ordering() -> None:
    # The row must carry which TVDB ordering its payload came from, so a
    # later lookup for a different episode reads the same list.
    file_path = Path("Show.S01E01.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper.media_search_payload = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
        tvdb_data={
            "episodes_by_type": {
                4: {
                    "type_name": "DVD Order",
                    "type": "dvd",
                    "episodes": [
                        {"seasonNumber": 1, "number": 1, "name": "Pilot"},
                    ],
                }
            }
        },
    )
    mapper._load_episode_data()
    mapper._populate_files_table()

    mapper._auto_match_files()

    assert mapper.file_episode_mappings[file_path]["episode_order_type_id"] == 4


def test_manual_assignment_records_the_selected_episode_ordering() -> None:
    # The manual edit path stores its own row and must record the ordering
    # too, otherwise a hand-corrected episode silently loses it.
    file_path = Path("Show.S01E01.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper.media_search_payload = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
        tvdb_data={
            "episodes_by_type": {
                4: {
                    "type_name": "DVD Order",
                    "type": "dvd",
                    "episodes": [
                        {"seasonNumber": 1, "number": 1, "name": "Pilot"},
                        {"seasonNumber": 1, "number": 2, "name": "Second"},
                    ],
                }
            }
        },
    )
    mapper._load_episode_data()
    mapper._populate_files_table()

    season_item = mapper.files_table.item(0, 1)
    episode_item = mapper.files_table.item(0, 2)
    assert season_item is not None
    assert episode_item is not None
    season_item.setText("1")
    episode_item.setText("2")
    mapper._on_table_item_changed(episode_item)

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["episode"] == 2
    assert mapping["episode_order_type_id"] == 4


def test_absolute_match_records_the_absolute_list_it_matched_against() -> None:
    # The absolute matcher deliberately scans every season type regardless
    # of the combo, so its row came from a different list than its
    # neighbours. A session-level value would be wrong here; the row must
    # carry the absolute list's own type id.
    file_path = Path("[Group] Show - 025.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper.media_search_payload = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
        tvdb_data={
            "episodes_by_type": {
                0: {
                    "type_name": "Aired Order",
                    "type": "official",
                    "episodes": [
                        {"seasonNumber": 2, "number": 4, "name": "Later"},
                    ],
                },
                3: {
                    "type_name": "Absolute Order",
                    "type": "absolute",
                    "episodes": [
                        {
                            "seasonNumber": 2,
                            "number": 4,
                            "absoluteNumber": 25,
                            "name": "Later",
                        },
                    ],
                },
            }
        },
    )
    mapper._load_episode_data()
    mapper._set_release_format(EpisodeFormat.ANIME_ABSOLUTE, manually_selected=True)
    mapper._populate_files_table()

    mapper._auto_match_files()

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["assignment_method"] == "absolute"
    assert mapping["episode_order_type_id"] == 3


def test_fuzzy_match_falls_back_to_filename_without_episode_title() -> None:
    file_path = Path("Show.S01.Some.Episode.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper.media_search_payload = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
    )
    mapper.available_episodes = {1: {1: {"name": "Some Episode"}}}

    result = mapper._fuzzy_match_episode_name(
        file_path.stem,
        season=1,
        parsed_data={"season": 1},
    )

    assert result == (1, 1, 1.0)


def test_auto_match_fuzzy_respects_parsed_season_for_duplicate_episode_names() -> None:
    # Episode names are often repeated across seasons ("Pilot", "Finale",
    # etc.). When the filename carries a season but no episode number, fuzzy
    # matching must stay within that season instead of selecting whichever
    # season happened to be inserted first.
    file_path = Path("Show.S01.Pilot.2160p.WEB-DL.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper.media_search_payload = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
    )
    mapper._populate_files_table()
    mapper.available_episodes = {
        2: {1: {"name": "Pilot"}},
        1: {1: {"name": "Pilot"}},
    }

    mapper._auto_match_files()

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 1
    assert mapping["episode"] == 1
    assert mapping["assignment_method"] == "fuzzy"


def test_fuzzy_match_fills_episode_for_season_only_row() -> None:
    # The manual fuzzy action must not treat a season-only row as complete.
    # Entering the season first is useful for constraining ambiguous episode
    # names and was previously skipped because the action only checked the
    # season column.
    file_path = Path("Show.S01.Some.Episode.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper.media_search_payload = MediaSearchPayload(
        media_type=MediaType.SERIES,
        title="Show",
    )
    mapper._populate_files_table()
    mapper.available_episodes = {1: {1: {"name": "Some Episode"}}}

    season_item = mapper.files_table.item(0, 1)
    assert season_item is not None
    season_item.setText("1")

    mapper._fuzzy_match_unassigned()

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 1
    assert mapping["episode"] == 1
    assert mapping["assignment_method"] == "fuzzy"


def test_auto_match_files_exact_matches_season_zero_special() -> None:
    # regression guard: TVDB uses season 0 for specials, and `season == 0`
    # is falsy in Python. Stage 1's exact-match gate used truthiness
    # (`season and episode`), so a genuinely parsed "Show.S00E05.mkv"
    # (season=0, episode=5) was skipped even though TVDB has that exact
    # S00E05 entry in `available_episodes`, wrongly degrading a
    # high-confidence exact match down to fuzzy/unmatched.
    file_path = Path("Show.S00E05.mkv")
    mapper = _make_mapper_with_files([file_path])
    mapper._populate_files_table()
    mapper.available_episodes = {0: {5: {"name": "Special Episode"}}}

    mapper._auto_match_files()

    mapping = mapper.file_episode_mappings[file_path]
    assert mapping["season"] == 0
    assert mapping["episode"] == 5
    assert mapping["assignment_method"] == "regex"


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
    mapper.media_search_payload = MediaSearchPayload(tvdb_data={"episodes_by_type": {}})

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


def test_load_episode_data_no_tvdb_data_applies_warning_style() -> None:
    # the "no episode data" status shares a plain label with the generic
    # stats message -- it needs a visible emphasis so it isn't missed
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv")])
    mapper.media_search_payload = MediaSearchPayload(tvdb_data=None)

    mapper._load_episode_data()

    style = mapper.episodes_stats_label.styleSheet()
    assert style != ""
    assert "color" in style.lower()


def test_load_episode_data_resets_warning_style_when_data_present() -> None:
    # the warning emphasis must not stick once real TVDB episode data loads
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv")])
    mapper.media_search_payload = MediaSearchPayload(tvdb_data=None)
    mapper._load_episode_data()
    assert mapper.episodes_stats_label.styleSheet() != ""

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

    assert mapper.episodes_stats_label.styleSheet() == ""


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

    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapping = mapper.file_episode_mappings.get(file_path)
    assert mapping is None or mapping["assignment_method"] != "daily"


def test_auto_match_files_does_not_daily_match_special_episode() -> None:
    # regression guard: TVDB uses season 0 for specials, and `season == 0`
    # is falsy in Python. A truthiness guard (`not (season and episode)`)
    # would treat a genuinely parsed "Show.S00E01.2024.05.01.mkv"
    # (season=0, episode=1, date=2024-05-01) as if it had no season/episode
    # at all, letting stage 1c reinterpret it by date and silently hijack it
    # onto an unrelated episode that happens to share that air date. TVDB
    # has no S00E01 entry here, so the file must fall through to
    # fuzzy/unmatched instead of ever being stored via the "daily" method.
    file_path = Path("Show.S00E01.2024.05.01.mkv")
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

    mapper = SeriesEpisodeMapper()
    mapper.load_data(media_input, media_search)

    mapping = mapper.file_episode_mappings.get(file_path)
    assert mapping is None or mapping["assignment_method"] != "daily"


@pytest.mark.parametrize(
    ("file_name", "expected_season", "expected_episode"),
    [
        # guessit reads the leading "0" of the absolute number "087" as a
        # season; UNIT3D renders season 0 as "Special {episode}", so trusting
        # it would upload absolute-numbered anime mis-categorized as a special
        # rather than failing loudly. Season must come back unresolved instead.
        ("Anime.Title.-.087.1080p.BluRay.x264-GROUP.mkv", None, 87),
        # bracketed absolute forms give guessit no season at all
        ("[Group] Anime Title - 087 [1080p][HEVC].mkv", None, 87),
        ("[Group] Anime Title - 12 (1080p) [ABCD1234].mkv", None, 12),
        # the conventional form survives the fallback intact
        ("Anime.Title.S02E11.1080p.BluRay.x264-GROUP.mkv", 2, 11),
        # ...and so does a genuine specials release, whose filename actually
        # names the specials season
        ("Show.Name.S00E03.1080p.WEB-DL.x264-GROUP.mkv", 0, 3),
        # a date-based episode yields neither
        ("The.Daily.Show.2024.01.15.1080p.WEB.h264-GROUP.mkv", None, None),
    ],
)
def test_build_series_release_info_fallback_season_episode(
    file_name: str, expected_season: int | None, expected_episode: int | None
) -> None:
    file_path = Path(file_name)
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == expected_season
    assert release_info.episode_start == expected_episode


def test_build_series_release_info_fallback_only_fills_missing_dimension() -> None:
    # the mapping supplies seasons but no episode numbers. The filename-parsing
    # fallback must backfill episodes only -- appending its own seasons on top
    # of the mapped ones would widen season_end to a value the user never
    # chose (here S03 from file_two's name, over the mapped S01).
    file_one = Path("Show.S03E01.mkv")
    file_two = Path("Show.S03E02.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        series_episode_map={
            file_one: {"season": 1, "episode": None},
            file_two: {"season": 1, "episode": None},
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )

    release_info = build_series_release_info(media_input)

    assert release_info.season == 1
    assert release_info.season_end == 1
    assert release_info.episode_start == 1
    assert release_info.episode_end == 2


def test_missing_upload_fields_pack_needs_only_a_season() -> None:
    # UNIT3D expresses a pack as episode 0, so a pack with no resolvable
    # episode number is complete as long as it has a season.
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

    assert release_info.is_pack is True
    assert release_info.missing_upload_fields() == ()
    assert describe_missing_upload_fields(release_info) is None


def test_missing_upload_fields_single_episode_needs_both() -> None:
    file_path = Path("Show.S01E01.mkv")
    complete = build_series_release_info(
        MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={file_path: {"season": 1, "episode": 1}},
            series_episode_format=EpisodeFormat.STANDARD,
        )
    )
    assert complete.missing_upload_fields() == ()

    # a date-based episode the fallback can't read, mapped by neither season
    # nor episode -- the exact shape that reached UNIT3D with the fields
    # silently dropped from the payload.
    unresolved_path = Path("The.Daily.Show.2024.01.15.1080p.WEB.h264-GROUP.mkv")
    unresolved = build_series_release_info(
        MediaInputPayload(
            input_path=unresolved_path,
            media_type=MediaType.SERIES,
            file_list=[unresolved_path],
            series_episode_map={unresolved_path: {"season": None, "episode": None}},
            series_episode_format=EpisodeFormat.STANDARD,
        )
    )
    assert unresolved.missing_upload_fields() == ("season", "episode")
    message = describe_missing_upload_fields(unresolved)
    assert message is not None
    assert "season number and episode number" in message


def test_missing_upload_fields_ignores_movies() -> None:
    movie_path = Path("Example.Movie.2024.1080p.WEB-DL.H.264.mkv")
    release_info = build_series_release_info(
        MediaInputPayload(
            input_path=movie_path,
            media_type=MediaType.MOVIE,
            file_list=[movie_path],
        )
    )

    assert release_info.missing_upload_fields() == ()
    assert describe_missing_upload_fields(release_info) is None


def _release(seasons: dict[Path, int]) -> SeriesReleaseInfo:
    media_input = MediaInputPayload(
        input_path=Path("Show Pack"),
        media_type=MediaType.SERIES,
        file_list=list(seasons),
        series_episode_map={
            path: {"season": season, "episode": index}
            for index, (path, season) in enumerate(seasons.items(), start=1)
        },
        series_episode_format=EpisodeFormat.STANDARD,
    )
    return build_series_release_info(media_input)


def test_describe_multi_season_pack_names_both_bounds() -> None:
    message = describe_multi_season_pack(
        _release({Path("Show.S01E01.mkv"): 1, Path("Show.S05E10.mkv"): 5})
    )

    assert message is not None
    assert "seasons 1 to 5" in message
    # the season it will actually be filed under has to be stated outright
    assert "file it under season 1" in message


def test_describe_multi_season_pack_silent_for_single_season() -> None:
    assert (
        describe_multi_season_pack(
            _release({Path("Show.S01E01.mkv"): 1, Path("Show.S01E02.mkv"): 1})
        )
        is None
    )


def test_describe_multi_season_pack_silent_for_single_episode() -> None:
    assert describe_multi_season_pack(_release({Path("Show.S01E01.mkv"): 1})) is None


def test_describe_multi_season_pack_silent_for_movies() -> None:
    media_input = MediaInputPayload(
        input_path=Path("Movie.2024.mkv"),
        media_type=MediaType.MOVIE,
        file_list=[Path("Movie.2024.mkv")],
    )
    assert describe_multi_season_pack(build_series_release_info(media_input)) is None
