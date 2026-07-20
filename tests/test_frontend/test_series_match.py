from pathlib import Path

from src.enums.media_type import MediaType
from src.frontend.custom_widgets.series_episode_mapper import SeriesEpisodeMapper
from src.frontend.wizards.series_match import _incomplete_mapping_message
from src.payloads.media_inputs import MediaInputPayload


def _make_mapper_with_files(file_list: list[Path]) -> SeriesEpisodeMapper:
    mapper = SeriesEpisodeMapper()
    mapper.media_input_payload = MediaInputPayload(
        input_path=Path("Show Season 1"),
        media_type=MediaType.SERIES,
        file_list=file_list,
    )
    return mapper


def test_incomplete_mapping_message_when_tvdb_has_no_episodes() -> None:
    # TVDB returned no episode data at all and the file is still unmapped --
    # the user needs to know they must enter season/episode manually rather
    # than just "finish mapping"
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv")])

    message = _incomplete_mapping_message(mapper)

    assert "TVDB returned no episode data" in message
    assert "manually" in message


def test_incomplete_mapping_message_for_plain_unmapped_files_with_tvdb_data() -> None:
    # TVDB has episode data, but the user simply hasn't finished mapping
    # every file yet -- this must use the generic "finish mapping" message
    mapper = _make_mapper_with_files([Path("Show.S01E01.mkv"), Path("Show.S01E02.mkv")])
    mapper.episodes_by_type = {
        0: {
            "type_name": "Aired Order",
            "episodes": [{"seasonNumber": 1, "number": 1}],
        }
    }
    mapper.file_episode_mappings = {
        Path("Show.S01E01.mkv"): {"season": 1, "episode": 1}
    }

    message = _incomplete_mapping_message(mapper)

    assert "TVDB returned no episode data" not in message
    assert "properly mapped" in message


def test_incomplete_mapping_message_for_duplicate_targets_with_tvdb_data() -> None:
    # is_valid() also fails when every file IS mapped but two files target
    # the same episode. has_unmapped_files() is False in that case, so the
    # "enter manually" message must not apply even without TVDB data.
    mapper = _make_mapper_with_files([Path("a.mkv"), Path("b.mkv")])
    mapper.file_episode_mappings = {
        Path("a.mkv"): {"season": 1, "episode": 1},
        Path("b.mkv"): {"season": 1, "episode": 1},
    }
    assert mapper.is_valid() is False
    assert mapper.has_unmapped_files() is False

    message = _incomplete_mapping_message(mapper)

    assert "TVDB returned no episode data" not in message
    assert "properly mapped" in message
