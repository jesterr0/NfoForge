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
_PATH_SEPARATOR = re.compile(r"[\\/]")
# A drive root reached after the start of the rendered body can only have come
# from a token value, since the template's own root is split off as the anchor.
_EMBEDDED_DRIVE_ROOT = re.compile(r"[\\/][A-Za-z]:[\\/]")


def _path_components(path_text: str) -> list[str]:
    """Split on either separator, dropping empties and no-op `.` segments."""
    return [
        component
        for component in _PATH_SEPARATOR.split(path_text)
        if component and component != "."
    ]


def _resolve_components(path_text: str) -> list[str] | None:
    """Resolve `..` lexically, or return None if the path walks above its root.

    Lexical rather than filesystem resolution: the destination belongs to
    whatever host runs qBittorrent, so it cannot be stat'd from here.
    """
    resolved: list[str] = []
    for component in _path_components(path_text):
        if component != "..":
            resolved.append(component)
            continue
        if not resolved:
            return None
        resolved.pop()
    return resolved


def _is_absolute(path_text: str) -> bool:
    stripped = path_text.strip()
    return bool(_WINDOWS_DRIVE_PATH.match(stripped)) or stripped.startswith(("\\", "/"))


def _unsafe_save_path_error() -> TrackerClientError:
    return TrackerClientError(
        "The qBittorrent save location template resolved to a path outside the "
        "configured save location. Online metadata for this title contains "
        "path characters; use {title} in the template, which strips them, or "
        "set the save location manually for this upload."
    )


def _ensure_safe_remote_titles(context: ProcessingContext) -> None:
    """Reject remote title metadata that would restructure the save path.

    `title` and `original_title` come straight off the TMDB API, and TMDB
    entries are community editable, so they are untrusted input. They reach
    the path through `{title_exact}`, `{title_clean}`, and `{original_title}`,
    which -- unlike `{title}` -- are not run through `_TITLE_UNSAFE_CHARS`.

    A separator on its own is left alone: `Face/Off` is a real title, and
    nesting a directory deeper is still inside the configured root. Only `..`
    segments and a title carrying its own drive/share root are refused, since
    only those relocate the write outside that root. Values supplied by user
    tokens are deliberately not checked -- those are local configuration, and
    a user token holding a UNC root is a supported way to write the template.
    """
    media_search = context.media_search
    if media_search is None:
        return

    for value in (media_search.title, media_search.original_title):
        if not value:
            continue
        if _is_absolute(value) or _EMBEDDED_DRIVE_ROOT.search(value):
            raise _unsafe_save_path_error()
        if any(component == ".." for component in _path_components(value)):
            raise _unsafe_save_path_error()


def _ensure_within_save_root(full_output: str, template: str) -> None:
    """Defence in depth: confirm the rendered path never climbs above its root.

    `_ensure_safe_remote_titles` is the primary control. This catches any
    other token that expands to a `..` segment, so the rendered destination
    still has to start with the literal directory the template named.
    """
    resolved = _resolve_components(full_output)
    root = _resolve_components(template.split("{", maxsplit=1)[0])
    if resolved is None or root is None or resolved[: len(root)] != root:
        raise _unsafe_save_path_error()


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
    """Return a warning for a Windows-style path that may not resolve as intended.

    qBittorrent interprets ``save_path`` on the machine running qBittorrent,
    not on the NfoForge host. A drive-letter path is host-specific and is
    therefore almost always a configuration mistake when the API host is not
    local. A UNC path is different: it can resolve identically from any
    Windows host on the network, so it is flagged only as a "confirm this is
    reachable from qBittorrent's host" reminder, not as a likely mistake.
    """

    if not save_path or not _is_windows_destination(save_path):
        return None

    host_value = (host or "").strip()
    parsed = urlsplit(host_value if "://" in host_value else f"//{host_value}")
    hostname = (parsed.hostname or "").casefold()
    if hostname in _LOOPBACK_HOSTS:
        return None

    if _WINDOWS_DRIVE_PATH.match(save_path.strip()):
        return (
            "The qBittorrent save location is a local Windows drive path, but the "
            "qBittorrent host is remote. qBittorrent may interpret this as a "
            "different path; configure the destination using the remote host's "
            "path mapping."
        )
    return (
        "The qBittorrent save location is a Windows UNC path. qBittorrent "
        "resolves this from its own host, so confirm the share is reachable "
        "from wherever qBittorrent is actually running, not just from this "
        "computer."
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
    """Split a Windows-style template into its literal root and the rest.

    The root (a drive letter such as ``D:\\`` or a UNC ``\\\\server\\share\\``
    prefix) is structural, not user-supplied text: its own colon must survive
    colon replacement untouched, and its own separators must survive exactly
    as written (a POSIX-style ``//server/share`` root must not come back with
    backslashes). Only the remainder -- where tokens are substituted -- should
    have ``colon_replace`` applied to it.

    ``PureWindowsPath.anchor`` is used only to measure how many leading
    characters belong to the root; its own value is never reused, since it
    normalizes separators to backslash and, for a bare UNC root with no
    trailing separator (e.g. ``\\\\nas\\movies``), reports one character more
    than the template actually has. Slicing the original string by that
    length -- tolerant of running past the end -- keeps every original
    character (including a trailing separator that was never there) intact
    and yields an empty remainder rather than an out-of-range error for a
    root-only template.
    """
    anchor_length = len(PureWindowsPath(template).anchor)
    return template[:anchor_length], template[anchor_length:]


def _render_save_path_template(
    config: AppConfig,
    context: ProcessingContext,
    template: str,
) -> str:
    # Strip once, up front, and use this value everywhere below.
    # `_is_windows_destination` and `_split_windows_anchor` must never be
    # asked to agree on two different strings -- a leading/trailing-space
    # template would otherwise be classified as Windows by one and not the
    # other, leaving colon replacement applied to an un-split (and thus
    # un-protected) drive/UNC root.
    template = template.strip()
    _ensure_safe_remote_titles(context)
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
        if not template_body.strip():
            # Root-only template (e.g. `\\nas\movies` or `D:\`) -- nothing to
            # render, and `_split_windows_anchor` may even report an anchor
            # longer than the template itself (a bare UNC root with no
            # trailing separator). There are no tokens to fill and no colon
            # replacement to apply to a structural root, so resolve directly
            # to the literal root rather than handing an empty string to
            # `TokenReplacer`, which would otherwise reject it as "resolved
            # to an empty path".
            return anchor
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
        custom_edition_info=context.custom_edition_info,
        custom_cut_names=context.custom_cut_names,
    )
    output = renderer.get_output() or ""
    full_output = anchor + output
    if not full_output.strip():
        raise TrackerClientError(
            "The qBittorrent save location template resolved to an empty path"
        )

    unresolved = sorted(set(_UNRESOLVED_TOKEN_PATTERN.findall(output)))
    if unresolved:
        raise TrackerClientError(
            "Unknown or unsupported token(s) in qBittorrent save location "
            f"template: {', '.join(unresolved)}"
        )

    # The rendered body must not carry a drive root of its own. The anchor
    # split above took the only legitimate one, so a second can only have
    # come out of a token. `_ensure_safe_remote_titles` catches this for the
    # two TMDB title fields it knows about; checking the rendered string
    # covers every token instead of a list that has to be kept in step with
    # which tokens happen to emit raw metadata.
    if _EMBEDDED_DRIVE_ROOT.search(output) or _WINDOWS_DRIVE_PATH.match(output.strip()):
        raise _unsafe_save_path_error()

    _ensure_within_save_root(full_output, template)
    return full_output.strip()
