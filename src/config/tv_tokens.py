from typing import Protocol

from src.enums.series import EpisodeFormat


class TVTokenPayload(Protocol):
    tvr_standard_episode_token: str
    tvr_daily_episode_token: str
    tvr_anime_episode_token: str
    tvr_standard_title_token: str
    tvr_daily_title_token: str
    tvr_anime_title_token: str


def get_tvr_episode_token(
    payload: TVTokenPayload, episode_format: EpisodeFormat
) -> str:
    """Return the configured episode filename token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        return payload.tvr_daily_episode_token
    if episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        return payload.tvr_anime_episode_token
    return payload.tvr_standard_episode_token


def set_tvr_episode_token(
    payload: TVTokenPayload,
    episode_format: EpisodeFormat,
    token_string: str,
) -> None:
    """Assign an episode filename token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        payload.tvr_daily_episode_token = token_string
    elif episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        payload.tvr_anime_episode_token = token_string
    else:
        payload.tvr_standard_episode_token = token_string


def get_tvr_title_token(payload: TVTokenPayload, episode_format: EpisodeFormat) -> str:
    """Return the configured tracker title token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        return payload.tvr_daily_title_token
    if episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        return payload.tvr_anime_title_token
    return payload.tvr_standard_title_token


def set_tvr_title_token(
    payload: TVTokenPayload,
    episode_format: EpisodeFormat,
    token_string: str,
) -> None:
    """Assign a tracker title token for a series format."""
    episode_format = EpisodeFormat(episode_format)
    if episode_format is EpisodeFormat.DAILY_DATE:
        payload.tvr_daily_title_token = token_string
    elif episode_format is EpisodeFormat.ANIME_ABSOLUTE:
        payload.tvr_anime_title_token = token_string
    else:
        payload.tvr_standard_title_token = token_string


def resolve_tvr_token(value: str, default: str) -> str:
    """Replace a blank token with the TOML-backed default."""
    return value or default
