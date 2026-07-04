from typing import Protocol

from src.enums.series import EpisodeFormat


class TVTokenPayload(Protocol):
    standard_episode_token: str
    daily_episode_token: str
    anime_episode_token: str
    standard_title_token: str
    daily_title_token: str
    anime_title_token: str


def get_tvr_episode_token(
    payload: TVTokenPayload, episode_format: EpisodeFormat
) -> str:
    """Return the configured episode filename token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        return payload.daily_episode_token
    if episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        return payload.anime_episode_token
    return payload.standard_episode_token


def set_tvr_episode_token(
    payload: TVTokenPayload,
    episode_format: EpisodeFormat,
    token_string: str,
) -> None:
    """Assign an episode filename token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        payload.daily_episode_token = token_string
    elif episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        payload.anime_episode_token = token_string
    else:
        payload.standard_episode_token = token_string


def get_tvr_title_token(payload: TVTokenPayload, episode_format: EpisodeFormat) -> str:
    """Return the configured tracker title token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        return payload.daily_title_token
    if episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        return payload.anime_title_token
    return payload.standard_title_token


def set_tvr_title_token(
    payload: TVTokenPayload,
    episode_format: EpisodeFormat,
    token_string: str,
) -> None:
    """Assign a tracker title token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        payload.daily_title_token = token_string
    elif episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        payload.anime_title_token = token_string
    else:
        payload.standard_title_token = token_string
