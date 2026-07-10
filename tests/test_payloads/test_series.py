from pathlib import Path

from src.enums.media_type import MediaType
from src.enums.series import EpisodeFormat
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.series import build_series_release_info


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
