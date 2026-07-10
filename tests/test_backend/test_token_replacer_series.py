from pathlib import Path

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken
from src.enums.media_type import MediaType
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
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


def test_episode_tokens_prefer_selected_series_mapping() -> None:
    output = _series_replacer(
        "{episode_title_exact} {episode_air_date} {episode_number_absolute}"
    ).get_output()

    assert output == "Selected Order Title 2024-02-03 22"


def test_air_date_token_prefers_selected_series_mapping() -> None:
    output = _series_replacer("{air_date}").get_output()

    assert output == "2024-02-03"
