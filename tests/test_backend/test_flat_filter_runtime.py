from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import pytest

from src.backend.process import ProcessBackEnd
from src.backend.trackers.title_rules import TITLE_RULES, Separator
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


def _renders_the_users_template() -> TrackerSelection:
    """Any tracker with no composition of its own, spaced.

    Spaced because the expectation below is a spaced string;
    SeedPool defers to the user too but renders the release form.
    """
    for tracker, entry in TITLE_RULES.items():
        if (
            entry.composition is None
            and entry.has_release_name_field
            and entry.normalisation.separator is Separator.SPACED
        ):
            return tracker
    pytest.fail(
        "Every tracker composes now, so a plugin flat filter can no longer "
        "reach a tracker title. Decide whether filters should reach a "
        "composition rather than deleting this test."
    )


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
                    claims=SimpleNamespace(enabled=True),
                ),
                series=SimpleNamespace(
                    multi_episode_style=MultiEpisodeStyle.RANGE,
                    claims=SimpleNamespace(enabled=True),
                ),
                user_tokens=SimpleNamespace(tokens={}),
                global_management=SimpleNamespace(
                    title_clean_rules=None,
                    video_dynamic_range=None,
                ),
            )
        ),
    )

    # A plugin filter can only reach a title through the user's global
    # template: an entry's composition carries fixed components with no
    # user filters in them. So this needs a tracker without one, and which
    # tracker that is must not be written down -- naming one would break
    # the day it gains rules.
    output = backend.generate_tracker_title(
        _renders_the_users_template(),
        TrackerInfo(),
        context,
        build_series_release_info(context.media_input),
    )

    assert output == "Movie NamePlugin"
