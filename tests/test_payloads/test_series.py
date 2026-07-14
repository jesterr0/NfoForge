from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.backend.process import ProcessBackEnd
from src.enums.media_type import MediaType
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

    assert ProcessBackEnd._release_info_token_kwargs(release_info) == {
        "season_number": 2,
        "episode_number": None,
        "episode_format": EpisodeFormat.STANDARD,
    }


def test_is_valid_rejects_duplicate_episode_targets() -> None:
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    # both files mapped to S01E01
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 1},
    }
    assert mapper.is_valid() is False
