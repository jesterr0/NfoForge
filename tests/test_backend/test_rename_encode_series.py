from pathlib import Path

from src.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.media_type import MediaType
from src.enums.token_replacer import ColonReplace
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


def _minimal_series_payload() -> MediaInputPayload:
    file_path = Path("Show.S01.mkv")
    return MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
    )


def _empty_series_search() -> MediaSearchPayload:
    return MediaSearchPayload(media_type=MediaType.SERIES, tvdb_data={"episodes": []})


def test_series_folder_renamer_renders_multi_season_range() -> None:
    backend = RenameEncodeSeriesBackEnd()
    result = backend.series_folder_renamer(
        media_input_obj=_minimal_series_payload(),
        token="S{season_number|zfill(2)}",
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=_empty_series_search(),
        season_num=1,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        season_end=5,
    )
    assert result == Path("S01-S05")


def test_series_folder_renamer_single_season_includes_title() -> None:
    backend = RenameEncodeSeriesBackEnd()
    result = backend.series_folder_renamer(
        media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
        token="{title_clean} S{season_number|zfill(2)}",
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=EXAMPLE_SEARCH_PAYLOAD,
        season_num=3,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        season_end=3,
    )
    assert result == Path("Series.Name.S03")


def test_series_folder_renamer_omits_episode_context() -> None:
    backend = RenameEncodeSeriesBackEnd()
    result = backend.series_folder_renamer(
        media_input_obj=_minimal_series_payload(),
        token="S{season_number|zfill(2)}{:opt=E:episode_number|zfill(2)}",
        colon_replacement=ColonReplace.REPLACE_WITH_DASH,
        media_search_payload=_empty_series_search(),
        season_num=1,
        title_clean_rules=None,
        video_dynamic_range=None,
        user_tokens=None,
        season_end=1,
    )
    assert result == Path("S01")
