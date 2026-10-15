from dataclasses import dataclass

import pytest

from nfoforge.config.tv_tokens import (
    SUPPORTED_TVR_FORMATS,
    get_tvr_episode_token,
    get_tvr_title_token,
    resolve_season_subfolder_token,
    set_tvr_episode_token,
    set_tvr_title_token,
)
from nfoforge.enums.series import EpisodeFormat


def test_blank_subfolder_token_falls_back_to_the_season_folder_token() -> None:
    # In a single-season pack the opened folder IS the season folder, so one
    # token covers both. The two diverge only for a nested pack.
    folder_token = "{title_clean} S{season_number|zfill(2)}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential

    assert resolve_season_subfolder_token("", folder_token) == folder_token


def test_a_whitespace_only_subfolder_token_falls_back_too() -> None:
    # A field holding spaces is a field the user left alone.
    assert resolve_season_subfolder_token("   ", "{title_clean}") == "{title_clean}"


def test_a_configured_subfolder_token_wins() -> None:
    assert (
        resolve_season_subfolder_token("Season {season_number}", "{title_clean}")
        == "Season {season_number}"
    )


def test_a_configured_subfolder_token_is_stripped() -> None:
    # Space around the token is not part of it. Both call sites already
    # tested emptiness against the stripped value and then used it.
    assert (
        resolve_season_subfolder_token("  Season {season_number}  ", "{title_clean}")
        == "Season {season_number}"
    )


@dataclass
class _Payload:
    """Stand-in for SeriesSettings, carrying only the token fields."""

    standard_episode_token: str = "standard ep"  # noqa: S105 - a naming template, not a credential
    daily_episode_token: str = "daily ep"  # noqa: S105 - a naming template, not a credential
    anime_episode_token: str = "anime ep"  # noqa: S105 - a naming template, not a credential
    dvd_episode_token: str = "dvd ep"  # noqa: S105 - a naming template, not a credential
    standard_title_token: str = "standard title"  # noqa: S105 - a naming template, not a credential
    daily_title_token: str = "daily title"  # noqa: S105 - a naming template, not a credential
    anime_title_token: str = "anime title"  # noqa: S105 - a naming template, not a credential
    dvd_title_token: str = "dvd title"  # noqa: S105 - a naming template, not a credential


@pytest.mark.parametrize(
    ("episode_format", "episode_token", "title_token"),
    [
        (EpisodeFormat.STANDARD, "standard ep", "standard title"),
        (EpisodeFormat.DAILY_DATE, "daily ep", "daily title"),
        (EpisodeFormat.ANIME_ABSOLUTE, "anime ep", "anime title"),
        (EpisodeFormat.DVD, "dvd ep", "dvd title"),
    ],
)
def test_every_supported_format_reads_its_own_tokens(
    episode_format: EpisodeFormat, episode_token: str, title_token: str
) -> None:
    """DVD used to fall through to the standard pair.

    Choosing DVD Order therefore had no effect on naming, silently, because
    the enum member existed but was not in the supported set.
    """
    payload = _Payload()

    assert get_tvr_episode_token(payload, episode_format) == episode_token
    assert get_tvr_title_token(payload, episode_format) == title_token


@pytest.mark.parametrize("episode_format", SUPPORTED_TVR_FORMATS)
def test_every_supported_format_writes_back_where_it_reads(
    episode_format: EpisodeFormat,
) -> None:
    """A format that wrote to one field and read from another would look
    like an edit that silently did nothing."""
    payload = _Payload()

    set_tvr_episode_token(payload, episode_format, "new episode")
    set_tvr_title_token(payload, episode_format, "new title")

    assert get_tvr_episode_token(payload, episode_format) == "new episode"
    assert get_tvr_title_token(payload, episode_format) == "new title"


def test_dvd_is_offered_as_a_release_format() -> None:
    assert EpisodeFormat.DVD in SUPPORTED_TVR_FORMATS
