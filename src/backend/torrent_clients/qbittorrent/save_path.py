import re

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, Tokens, TokenSelection
from src.config.models import AppConfig
from src.context.processing_context import ProcessingContext
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)
from src.exceptions import TrackerClientError
from src.payloads.series import build_series_release_info

_UNRESOLVED_TOKEN_PATTERN = re.compile(r"{[^{}]+}")
_FLAT_TOKEN_PATTERN = re.compile(r"{(?::opt=([^:}]*):)?([^}]+?)(?::opt=([^:}]*):)?}")


def resolve_qbittorrent_save_path(
    config: AppConfig,
    context: ProcessingContext,
) -> str | None:
    """Resolve qBittorrent's destination for the current processing run."""
    run_override = context.torrent_client_options.save_path_overrides.get(
        TorrentClientSelection.QBITTORRENT
    )
    if run_override and run_override.strip():
        return run_override.strip()

    return resolve_configured_qbittorrent_save_path(config, context)


def resolve_configured_qbittorrent_save_path(
    config: AppConfig,
    context: ProcessingContext,
) -> str | None:
    """Resolve only the persistent qBittorrent save-path configuration."""
    qbit_config = config.torrent_clients.qbittorrent
    if qbit_config.save_path_mode is QBittorrentSavePathMode.CLIENT_DEFAULT:
        return None

    if qbit_config.save_path_mode is QBittorrentSavePathMode.SOURCE:
        return str(context.media_input.require_input_path().parent)

    return _render_save_path_template(
        config,
        context,
        qbit_config.save_path_template,
    )


def _render_save_path_template(
    config: AppConfig,
    context: ProcessingContext,
    template: str,
) -> str:
    release_info = build_series_release_info(context.media_input)
    user_tokens = {
        key: value
        for key, (value, token_selection) in config.user_tokens.tokens.items()
        if TokenSelection(token_selection) is TokenSelection.FILE_TOKEN
    }
    supported_tokens = Tokens.get_tokens(FileToken) | set(user_tokens)
    unsupported_tokens = sorted(
        {
            match.group(2).split("|", maxsplit=1)[0].strip()
            for match in _FLAT_TOKEN_PATTERN.finditer(template)
            if match.group(2).split("|", maxsplit=1)[0].strip() not in supported_tokens
        }
    )
    if unsupported_tokens:
        raise TrackerClientError(
            "Unknown or unsupported token(s) in qBittorrent save location "
            f"template: {', '.join(unsupported_tokens)}"
        )

    renderer = TokenReplacer(
        media_input_obj=context.media_input,
        token_string=template,
        colon_replace=ColonReplace.KEEP,
        media_search_obj=context.media_search,
        flatten=True,
        file_name_mode=False,
        token_type=FileToken,
        unfilled_token_mode=UnfilledTokenRemoval.KEEP,
        releasers_name=config.general.releasers_name,
        override_tokens=context.shared_data.dynamic_data.get("override_tokens"),
        user_tokens=user_tokens,
        edition_override=context.shared_data.dynamic_data.get("edition_override"),
        frame_size_override=context.shared_data.dynamic_data.get("frame_size_override"),
        title_clean_rules=config.global_management.title_clean_rules,
        video_dynamic_range=config.global_management.video_dynamic_range,
        season_number=release_info.season,
        season_end=release_info.season_end,
        episode_number=(
            release_info.episode_start if not release_info.is_pack else None
        ),
        episode_format=release_info.episode_format,
        multi_episode_style=config.series.multi_episode_style,
        preserve_literal_formatting=True,
        flat_filters=context.flat_filters,
    )
    output = renderer.get_output()
    if not output or not output.strip():
        raise TrackerClientError(
            "The qBittorrent save location template resolved to an empty path"
        )

    unresolved = sorted(set(_UNRESOLVED_TOKEN_PATTERN.findall(output)))
    if unresolved:
        raise TrackerClientError(
            "Unknown or unsupported token(s) in qBittorrent save location "
            f"template: {', '.join(unresolved)}"
        )
    return output.strip()
