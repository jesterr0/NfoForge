"""Shared anime detection for the release being processed.

Lives here rather than in `process.py` because `token_replacer.py` needs it
too, and `process.py` imports `TokenReplacer` -- importing back the other way
would be circular.
"""

from src.enums.series import EpisodeFormat
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


def is_anime_release(
    media_input: MediaInputPayload, media_search: MediaSearchPayload
) -> bool:
    """Return whether confirmed metadata or user-selected mapping marks anime."""
    return bool(
        media_search.anilist_id
        or media_search.anilist_data
        or media_input.series_episode_format is EpisodeFormat.ANIME_ABSOLUTE
    )
