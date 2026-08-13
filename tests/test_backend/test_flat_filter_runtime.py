from copy import deepcopy
from types import SimpleNamespace
from typing import cast

from src.backend.process import ProcessBackEnd
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection
from src.payloads.series import build_series_release_info
from src.payloads.trackers import TrackerInfo


def test_tracker_title_applies_processing_context_flat_filters() -> None:
    def append_marker(value: str, *_args: object) -> str:
        return f"{value}Plugin"

    context = ProcessingContext(
        media_input=deepcopy(EXAMPLE_MEDIA_INPUT_PAYLOAD),
        media_search=deepcopy(EXAMPLE_SEARCH_PAYLOAD),
        flat_filters={"append_marker": append_marker},
    )
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(
        ConfigManager,
        SimpleNamespace(
            settings=SimpleNamespace(
                movie=SimpleNamespace(
                    title_token="{title_clean|append_marker}",  # noqa: S106 - NFO template token string used as test fixture data, not a credential
                    title_colon_replace=ColonReplace.REPLACE_WITH_DASH,
                    parse_filename_attributes=True,
                ),
                series=SimpleNamespace(
                    multi_episode_style=MultiEpisodeStyle.RANGE,
                    parse_filename_attributes=True,
                ),
                user_tokens=SimpleNamespace(tokens={}),
                global_management=SimpleNamespace(
                    title_clean_rules=None,
                    video_dynamic_range=None,
                ),
            )
        ),
    )

    output = backend.generate_tracker_title(
        TrackerSelection.BEYOND_HD,  # FREE policy -- reads tracker_info as before
        TrackerInfo(),
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie NamePlugin"
