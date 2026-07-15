from pathlib import Path

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, TokenData
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIAINFO_OBJ,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.enums.media_type import MediaType
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.nf_jinja2 import Jinja2TemplateEngine
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


def _series_replacer(token: str) -> TokenReplacer:
    file_path = Path("Show.S01E02.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 1,
                    "episode": 2,
                    "episode_name": "Selected Order Title",
                    "episode_data": {
                        "seasonNumber": 1,
                        "number": 2,
                        "absoluteNumber": 22,
                        "name": "Selected Order Title",
                        "aired": "2024-02-03",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tvdb_data={
                "firstAired": "2019-04-01",
                "episodes": [
                    {
                        "seasonNumber": 1,
                        "number": 2,
                        "absoluteNumber": 2,
                        "name": "Default Order Title",
                        "aired": "2020-01-02",
                    }
                ]
            },
        ),
        token_string=token,
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=1,
        episode_number=2,
    )


def _series_replacer_with_special() -> TokenReplacer:
    file_path = Path("Show.S00E05.mkv")
    return TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 0,
                    "episode": 5,
                    "episode_name": "Special Episode",
                    "episode_data": {
                        "seasonNumber": 0,
                        "number": 5,
                        "name": "Special Episode",
                        "aired": "2024-05-01",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(media_type=MediaType.SERIES),
        token_string="{episode_metadata}",
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=0,
        episode_number=5,
    )


def test_episode_metadata_includes_season_zero_label() -> None:
    replacer = _series_replacer_with_special()
    out = replacer._episode_metadata(token_data=TokenData())

    assert "Season 00" in out
    assert "Episode 05" in out


def test_episode_tokens_prefer_selected_series_mapping() -> None:
    output = _series_replacer(
        "{episode_title_exact} {episode_air_date} {episode_number_absolute}"
    ).get_output()

    assert output == "Selected Order Title 2024-02-03 22"


def test_episode_number_absolute_falls_back_when_tvdb_value_is_zero() -> None:
    # TVDB commonly stores absoluteNumber: 0 for non-anime episodes; that
    # should be treated as "no absolute number" and fall back to the
    # season-relative episode number instead of rendering "0"/"000".
    file_path = Path("Show.S02E05.mkv")
    replacer = TokenReplacer(
        media_input_obj=MediaInputPayload(
            input_path=file_path,
            media_type=MediaType.SERIES,
            file_list=[file_path],
            series_episode_map={
                file_path: {
                    "season": 2,
                    "episode": 5,
                    "episode_name": "Non-Anime Episode",
                    "episode_data": {
                        "seasonNumber": 2,
                        "number": 5,
                        "absoluteNumber": 0,
                        "name": "Non-Anime Episode",
                        "aired": "2024-05-01",
                    },
                }
            },
        ),
        media_search_obj=MediaSearchPayload(
            media_type=MediaType.SERIES,
            tvdb_data={
                "episodes": [
                    {
                        "seasonNumber": 2,
                        "number": 5,
                        "absoluteNumber": 0,
                        "name": "Non-Anime Episode",
                        "aired": "2024-05-01",
                    }
                ]
            },
        ),
        token_string="{episode_number_absolute}",
        colon_replace=ColonReplace.REPLACE_WITH_DASH,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
        season_number=2,
        episode_number=5,
    )

    assert replacer.get_output() == "5"


def test_air_date_is_series_level_first_aired_distinct_from_episode_air_date() -> None:
    # {air_date} is series-level (parallels the movie {release_date} token) and
    # must differ from {episode_air_date}, which stays the selected episode's
    # own air date.
    output = _series_replacer("{air_date} {episode_air_date}").get_output()

    assert output == "2019-04-01 2024-02-03"


def test_series_nfo_tokens_render_selected_episode_context() -> None:
    file_path = Path("Show.S01E02.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
        file_list_mediainfo={file_path: EXAMPLE_MEDIAINFO_OBJ},
        series_episode_map={
            file_path: {
                "season": 1,
                "episode": 2,
                "episode_name": "Selected Order Title",
                "episode_data": {
                    "seasonNumber": 1,
                    "number": 2,
                    "absoluteNumber": 22,
                    "name": "Selected Order Title",
                    "aired": "2024-02-03",
                },
            }
        },
    )

    output = TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        token_string=(
            "{{ season_number }}|{{ episode_number }}|"
            "{{ episode_title_exact }}|{{ air_date }}|{{ episode_air_date }}"
        ),
        jinja_engine=Jinja2TemplateEngine(),
        season_number=1,
        episode_number=2,
    ).get_output()

    # EXAMPLE_SEARCH_PAYLOAD's tvdb_data has no flat series-level "firstAired"
    # key (its fixture nests series fields under "series"), so {air_date} is
    # blank here; {episode_air_date} still resolves from the selected episode.
    assert output == "1|2|Selected Order Title||2024-02-03"


def test_series_pack_nfo_single_episode_tokens_stay_blank() -> None:
    file_one = Path("Show.S01E02.mkv")
    file_two = Path("Show.S01E03.mkv")
    media_input = MediaInputPayload(
        input_path=Path("Show.S01"),
        media_type=MediaType.SERIES,
        file_list=[file_one, file_two],
        file_list_mediainfo={
            file_one: EXAMPLE_MEDIAINFO_OBJ,
            file_two: EXAMPLE_MEDIAINFO_OBJ,
        },
        series_episode_map={
            file_one: {
                "season": 1,
                "episode": 2,
                "episode_name": "Episode Two",
                "episode_data": {
                    "seasonNumber": 1,
                    "number": 2,
                    "name": "Episode Two",
                    "aired": "2024-02-03",
                },
            },
            file_two: {
                "season": 1,
                "episode": 3,
                "episode_name": "Episode Three",
                "episode_data": {
                    "seasonNumber": 1,
                    "number": 3,
                    "name": "Episode Three",
                    "aired": "2024-02-10",
                },
            },
        },
    )

    output = TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
        token_string=(
            "{{ season_number }}|{{ episode_number }}|"
            "{{ episode_title_exact }}|{{ episode_metadata }}"
        ),
        jinja_engine=Jinja2TemplateEngine(),
        season_number=1,
        episode_number=None,
    ).get_output()

    assert output is not None
    first_line, metadata = output.split("|", 3)[0:3], output.split("|", 3)[3]
    assert first_line == ["1", "", ""]
    assert "Episode Two" in metadata
    assert "Episode Three" in metadata


def test_flat_token_with_episode_title_clean_only_does_not_return_none() -> None:
    # token string uses {episode_title_clean} but NOT {title_clean}; the
    # substring "title_clean" inside "episode_title_clean" previously caused
    # a KeyError on filled_tokens["title_clean"], swallowed into None output
    output = _series_replacer("{episode_title_clean}").get_output()

    assert output is not None
    assert output == "Selected Order Title"


def test_flat_token_with_imdb_aka_fallback_title_clean_only_does_not_return_none() -> (
    None
):
    # token string uses {imdb_aka_fallback_title_clean} alone; same substring
    # collision as above must not raise a KeyError and return None
    output = _series_replacer("{imdb_aka_fallback_title_clean}").get_output()

    assert output is not None


def test_jinja_nfo_rendering_only_evaluates_referenced_tokens() -> None:
    file_path = Path("Missing.MediaInfo.File.S01E02.mkv")
    media_input = MediaInputPayload(
        input_path=file_path,
        media_type=MediaType.SERIES,
        file_list=[file_path],
    )

    output = TokenReplacer(
        media_input_obj=media_input,
        media_search_obj=MediaSearchPayload(media_type=MediaType.SERIES),
        token_string="{{ title }}",
        jinja_engine=Jinja2TemplateEngine(),
    ).get_output()

    assert output == "Missing MediaInfo File"
