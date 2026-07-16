from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.backend.process import ProcessBackEnd
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.payloads.media_inputs import MediaInputPayload
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
