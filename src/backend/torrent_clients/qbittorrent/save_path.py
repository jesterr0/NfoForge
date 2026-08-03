from pathlib import PureWindowsPath
import re
from urllib.parse import urlsplit

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, Tokens, TokenSelection
from src.config.models import AppConfig
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)
from src.exceptions import TrackerClientError
from src.payloads.series import build_series_release_info

_UNRESOLVED_TOKEN_PATTERN = re.compile(r"{[^{}]+}")
_FLAT_TOKEN_PATTERN = re.compile(r"{(?::opt=([^:}]*):)?([^}]+?)(?::opt=([^:}]*):)?}")
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_windows_destination(path_text: str) -> bool:
    """True when a save-path root points at a Windows filesystem.

    Drive-letter and UNC roots both mean the destination cannot contain `:`
    in a path component, so a title like `Mission: Impossible` must have its
    colon replaced rather than kept.
    """
    stripped = path_text.strip()
    return bool(_WINDOWS_DRIVE_PATH.match(stripped)) or stripped.startswith(
        (r"\\", "//")
    )


def get_qbittorrent_save_path_warning(
    host: str | None,
    save_path: str | None,
) -> str | None:
    """Return a warning for a local Windows path sent to a remote qBittorrent.

    qBittorrent interprets ``save_path`` on the machine running qBittorrent,
    not on the NfoForge host.  A drive-letter path is therefore almost always
    a configuration mistake when the API host is not local.
    """

    if not save_path or not _is_windows_destination(save_path):
        return None

    host_value = (host or "").strip()
    parsed = urlsplit(host_value if "://" in host_value else f"//{host_value}")
    hostname = (parsed.hostname or "").casefold()
    if hostname in _LOOPBACK_HOSTS:
        return None

    return (
        "The qBittorrent save location is a local Windows drive path, but the "
        "qBittorrent host is remote. qBittorrent may interpret this as a "
        "different path; configure the destination using the remote host's "
        "path mapping."
    )


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
        input_path = context.media_input.require_input_path()
        path_text = str(input_path)
        if _is_windows_destination(path_text):
            return str(PureWindowsPath(path_text).parent)
        return str(input_path.parent)

    return _render_save_path_template(
        config,
        context,
        qbit_config.save_path_template,
    )


def _colon_replace_for_destination(
    config: AppConfig,
    context: ProcessingContext,
) -> ColonReplace:
    """Pick the configured colon-replacement rule for the current media type.

    Movies and series each carry their own ``filename_colon_replace``
    setting, so the save-path renderer defers to whichever one matches the
    media currently being processed.
    """
    media_type = context.media_input.require_media_type()
    if media_type is MediaType.SERIES:
        return config.series.filename_colon_replace
    return config.movie.filename_colon_replace


def _split_windows_anchor(template: str) -> tuple[str, str]:
    """Split a Windows-style template into its literal anchor and the rest.

    The anchor (a drive letter such as ``D:\\`` or a UNC ``\\\\server\\share\\``
    root) is structural, not user-supplied text, and its own colon must
    survive colon replacement untouched. Only the remainder -- where tokens
    are substituted -- should have ``colon_replace`` applied to it.
    """
    anchor = PureWindowsPath(template).anchor
    return anchor, template[len(anchor) :]


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

    if _is_windows_destination(template):
        anchor, template_body = _split_windows_anchor(template)
        colon_replace = _colon_replace_for_destination(config, context)
    else:
        anchor, template_body = "", template
        colon_replace = ColonReplace.KEEP

    renderer = TokenReplacer(
        media_input_obj=context.media_input,
        token_string=template_body,
        colon_replace=colon_replace,
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
    return anchor + output.strip()
