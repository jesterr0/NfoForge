from copy import deepcopy
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import cast

import pytest

from src.backend.torrent_clients.qbittorrent.save_path import (
    _colon_replace_for_destination,
    _is_windows_destination,
    _split_windows_anchor,
    get_qbittorrent_save_path_warning,
    resolve_qbittorrent_save_path,
)
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.models import AppConfig
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.token_replacer import ColonReplace
from src.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)
from src.exceptions import TrackerClientError
from src.payloads.clients import QBittorrentConfig
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


def _config(
    mode: QBittorrentSavePathMode,
    template: str = "",
    user_tokens: dict[str, tuple[str, object]] | None = None,
    movie_colon_replace: ColonReplace = ColonReplace.KEEP,
    series_colon_replace: ColonReplace = ColonReplace.KEEP,
) -> AppConfig:
    return cast(
        AppConfig,
        SimpleNamespace(
            torrent_clients=SimpleNamespace(
                qbittorrent=QBittorrentConfig(
                    enabled=True,
                    category="Movies",
                    super_seeding=False,
                    save_path_mode=mode,
                    save_path_template=template,
                )
            ),
            user_tokens=SimpleNamespace(tokens=user_tokens or {}),
            general=SimpleNamespace(releasers_name="", release_group=""),
            global_management=SimpleNamespace(
                title_clean_rules=[],
                video_dynamic_range=None,
            ),
            movie=SimpleNamespace(filename_colon_replace=movie_colon_replace),
            series=SimpleNamespace(
                multi_episode_style=MultiEpisodeStyle.RANGE,
                filename_colon_replace=series_colon_replace,
            ),
        ),
    )


def _movie_context() -> ProcessingContext:
    return ProcessingContext(
        media_input=deepcopy(EXAMPLE_MEDIA_INPUT_PAYLOAD),
        media_search=deepcopy(EXAMPLE_SEARCH_PAYLOAD),
    )


@pytest.mark.parametrize(
    ("input_path", "expected"),
    [
        (
            PureWindowsPath(r"\\plex_server\movies\Cleaner (2025)\Cleaner.2025.mkv"),
            r"\\plex_server\movies\Cleaner (2025)",
        ),
        (
            PureWindowsPath(r"\\plex_server\movies\Cleaner (2025)"),
            "\\\\plex_server\\movies\\",
        ),
    ],
)
def test_source_mode_uses_input_parent_for_file_and_directory(
    input_path: PureWindowsPath,
    expected: str,
) -> None:
    context = ProcessingContext(
        media_input=MediaInputPayload(
            input_path=cast(Path, input_path),
            file_list=[cast(Path, input_path)],
        )
    )

    assert (
        resolve_qbittorrent_save_path(
            _config(QBittorrentSavePathMode.SOURCE),
            context,
        )
        == expected
    )


def test_client_default_leaves_destination_to_qbittorrent() -> None:
    assert (
        resolve_qbittorrent_save_path(
            _config(QBittorrentSavePathMode.CLIENT_DEFAULT),
            _movie_context(),
        )
        is None
    )


def test_template_uses_existing_file_tokens_and_preserves_literal_path() -> None:
    context = _movie_context()
    template = r"D:\Media  Library\{title_exact} {release_year_parentheses}"

    assert resolve_qbittorrent_save_path(
        _config(QBittorrentSavePathMode.TEMPLATE, template),
        context,
    ) == (rf"D:\Media  Library\Movie Name ({context.media_search.year})")


def test_template_accepts_video_dimensions_as_file_tokens() -> None:
    assert (
        resolve_qbittorrent_save_path(
            _config(
                QBittorrentSavePathMode.TEMPLATE,
                r"D:\Media\{video_width}x{video_height}",
            ),
            _movie_context(),
        )
        == r"D:\Media\3840x2160"
    )


def test_template_applies_processing_context_flat_filters() -> None:
    context = _movie_context()

    def folder_name(value: str, *_args: object) -> str:
        return value.replace(" ", "_")

    context.flat_filters["folder_name"] = folder_name

    assert (
        resolve_qbittorrent_save_path(
            _config(
                QBittorrentSavePathMode.TEMPLATE,
                r"D:\Media\{title_exact|folder_name}",
            ),
            context,
        )
        == r"D:\Media\Movie_Name"
    )


def test_file_token_user_tokens_are_supported_in_templates() -> None:
    context = _movie_context()
    config = _config(
        QBittorrentSavePathMode.TEMPLATE,
        r"{usr_media_root}\{title_exact}",
        {
            "usr_media_root": (
                r"\\plex_server\movies",
                "FileToken",
            )
        },
    )

    assert resolve_qbittorrent_save_path(config, context) == (
        r"\\plex_server\movies\Movie Name"
    )


def test_unknown_template_token_is_rejected() -> None:
    with pytest.raises(TrackerClientError, match="unknown_title"):
        resolve_qbittorrent_save_path(
            _config(
                QBittorrentSavePathMode.TEMPLATE,
                r"\\server\movies\{unknown_title}",
            ),
            _movie_context(),
        )


def test_nfo_token_is_rejected_in_file_token_template() -> None:
    with pytest.raises(TrackerClientError, match="media_info"):
        resolve_qbittorrent_save_path(
            _config(
                QBittorrentSavePathMode.TEMPLATE,
                r"\\server\movies\{media_info}",
            ),
            _movie_context(),
        )


def test_run_override_wins_over_invalid_configured_template() -> None:
    context = _movie_context()
    context.torrent_client_options.save_path_overrides[
        TorrentClientSelection.QBITTORRENT
    ] = "/remote/media/Movie Name"

    assert (
        resolve_qbittorrent_save_path(
            _config(QBittorrentSavePathMode.TEMPLATE),
            context,
        )
        == "/remote/media/Movie Name"
    )


def test_windows_destination_replaces_colons_in_save_path() -> None:
    """The final segment must be read with Windows separator rules.

    Plain `Path` is `PosixPath` off Windows, where a backslash is an ordinary
    character, so `.name` returns the whole template and the drive letter's
    own `:` fails the assertion on a Linux runner.
    """
    context = _movie_context()
    context.media_search.title = "Mission: Impossible"

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            r"D:\Media\Movies\{title_exact}",
            movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        ),
        context,
    )

    assert path is not None
    assert ":" not in PureWindowsPath(path).name


def test_windows_destination_preserves_drive_letter_colon() -> None:
    """Colon replacement must not corrupt the drive letter's own `:`."""
    context = _movie_context()
    context.media_search.title = "Mission: Impossible"

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            r"D:\Media\Movies\{title_exact}",
            movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        ),
        context,
    )

    assert path is not None
    assert path.startswith("D:\\")


def test_linux_destination_keeps_colons_in_save_path() -> None:
    context = _movie_context()
    context.media_search.title = "Mission: Impossible"

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            "/media/movies/{title_exact}",
            movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        ),
        context,
    )

    assert path is not None
    assert "Mission: Impossible" in path


@pytest.mark.parametrize(
    ("root", "expected"),
    [
        ("D:\\Media", True),
        ("d:/media", True),
        ("/media/movies", False),
        ("", False),
        ("relative/path", False),
    ],
)
def test_windows_destination_detection(root: str, expected: bool) -> None:
    assert _is_windows_destination(root) is expected


def test_colon_replace_for_destination_uses_movie_setting_for_movies() -> None:
    context = _movie_context()
    config = _config(
        QBittorrentSavePathMode.TEMPLATE,
        movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        series_colon_replace=ColonReplace.DELETE,
    )

    assert (
        _colon_replace_for_destination(config, context)
        is ColonReplace.REPLACE_WITH_DASH
    )


def test_colon_replace_for_destination_uses_series_setting_for_series() -> None:
    context = ProcessingContext(
        media_input=MediaInputPayload(media_type=MediaType.SERIES),
    )
    config = _config(
        QBittorrentSavePathMode.TEMPLATE,
        movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        series_colon_replace=ColonReplace.DELETE,
    )

    assert _colon_replace_for_destination(config, context) is ColonReplace.DELETE


@pytest.mark.parametrize(
    ("template", "expected_root", "expected_body"),
    [
        (r"\\nas\movies", r"\\nas\movies", ""),
        ("D:\\", "D:\\", ""),
        (r"D:\Media\{title_exact}", "D:\\", r"Media\{title_exact}"),
        ("//media/movies/{title_exact}", "//media/movies/", "{title_exact}"),
    ],
)
def test_split_windows_anchor_preserves_original_characters(
    template: str, expected_root: str, expected_body: str
) -> None:
    """The root must be a verbatim slice, not pathlib's normalized anchor.

    A bare UNC root with no trailing separator (``\\\\nas\\movies``) must not
    raise despite `PureWindowsPath.anchor` reporting one character more than
    the template has, and a POSIX-style ``//`` root must come back with its
    own forward slashes, never rewritten to backslashes.
    """
    assert _split_windows_anchor(template) == (expected_root, expected_body)


def test_unc_root_with_body_renders_and_replaces_only_the_title_colon() -> None:
    context = _movie_context()
    context.media_search.title = "Mission: Impossible"

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            r"\\nas\movies\{title_exact}",
            movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        ),
        context,
    )

    assert path == r"\\nas\movies\Mission- Impossible"


def test_unc_root_only_template_resolves_instead_of_raising() -> None:
    """A "dump everything in the share root" configuration is valid input."""
    context = _movie_context()

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            r"\\nas\movies",
            movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        ),
        context,
    )

    assert path == r"\\nas\movies"


def test_drive_root_only_template_resolves_instead_of_raising() -> None:
    context = _movie_context()

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            "D:\\",
            movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        ),
        context,
    )

    assert path == "D:\\"


def test_padded_windows_template_preserves_drive_letter_colon() -> None:
    """Leading/trailing whitespace must not desync detection from splitting."""
    context = _movie_context()
    context.media_search.title = "Mission: Impossible"

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            "  D:\\Media\\{title_exact}  ",
            movie_colon_replace=ColonReplace.REPLACE_WITH_DASH,
        ),
        context,
    )

    assert path == r"D:\Media\Mission- Impossible"


def test_posix_double_slash_template_stays_forward_slashed_and_keeps_colon() -> None:
    """A `//`-rooted template must not have its separators rewritten.

    With the (default) `ColonReplace.KEEP` setting this also confirms the
    title's colon survives, matching the pre-anchor-splitting behaviour for
    this shape.
    """
    context = _movie_context()
    context.media_search.title = "Mission: Impossible"

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            "//media/movies/{title_exact}",
        ),
        context,
    )

    assert path == "//media/movies/Mission: Impossible"
    assert "\\" not in (path or "")


def test_remote_qbittorrent_unc_warning_does_not_call_it_a_drive_path() -> None:
    """A UNC path is machine-independent; the wording must not overclaim."""
    warning = get_qbittorrent_save_path_warning(
        "https://seedbox.example",
        r"\\nas\movies",
    )

    assert warning is not None
    assert "drive path" not in warning
    assert "UNC" in warning


@pytest.mark.parametrize(
    ("template", "hostile_title"),
    [
        (r"D:\Media\{title_exact}", r"..\..\..\Windows\Temp\pwn"),
        (r"D:\Media\{title_clean}", r"..\..\..\Windows\Temp\pwn"),
        ("/mnt/media/{title_exact}", "../../../etc/cron.d/pwn"),
        (r"\nas\movies\{title_exact}", r"..\..\..\Users\Public\Startup\pwn"),
        ("{title_exact}", "../../../etc/cron.d/pwn"),
    ],
)
def test_template_rejects_remote_title_that_escapes_the_save_root(
    template: str,
    hostile_title: str,
) -> None:
    """A TMDB-supplied title must not walk out of the configured save root.

    `title` comes straight off the TMDB HTTP API and TMDB entries are
    community editable, so a poisoned title is remote input. It reaches the
    save path through the raw `{title_exact}`/`{title_clean}` tokens, which
    -- unlike `{title}` -- do not pass through `_TITLE_UNSAFE_CHARS`.
    """
    context = _movie_context()
    context.media_search.title = hostile_title

    with pytest.raises(TrackerClientError, match="outside the configured"):
        resolve_qbittorrent_save_path(
            _config(QBittorrentSavePathMode.TEMPLATE, template),
            context,
        )


def test_template_rejects_remote_title_that_injects_an_absolute_root() -> None:
    """A title expanding to its own drive root must not redirect the path."""
    context = _movie_context()
    context.media_search.title = r"C:\Windows\Temp\pwn"

    with pytest.raises(TrackerClientError, match="outside the configured"):
        resolve_qbittorrent_save_path(
            _config(
                QBittorrentSavePathMode.TEMPLATE,
                r"D:\Media\{title_exact}",
                movie_colon_replace=ColonReplace.KEEP,
            ),
            context,
        )


def _series_context_with_episode_title(name: str) -> ProcessingContext:
    path = Path("Show.S01E02.mkv")
    return ProcessingContext(
        media_input=MediaInputPayload(
            input_path=path,
            media_type=MediaType.SERIES,
            file_list=[path],
            series_episode_map={
                path: {
                    "season": 1,
                    "episode": 2,
                    "episode_name": name,
                    "episode_data": {
                        "seasonNumber": 1,
                        "number": 2,
                        "name": name,
                    },
                }
            },
        ),
        media_search=MediaSearchPayload(
            media_type=MediaType.SERIES,
            title="Show",
            tvdb_data={"episodes": [{"seasonNumber": 1, "number": 2, "name": name}]},
        ),
    )


def test_template_rejects_an_episode_title_that_injects_a_drive_root() -> None:
    """The guard cannot be a list of the metadata fields it happens to know.

    `_ensure_safe_remote_titles` inspects TMDB's title and original_title.
    An episode name is TVDB metadata reaching the path through
    {episode_title_exact}, which applies no formatting -- so the check that
    catches this has to run on the rendered string, not on an enumeration
    of fields that has to be kept in step with which tokens emit raw values.
    """
    context = _series_context_with_episode_title(r"C:\Windows\Temp\pwn")

    with pytest.raises(TrackerClientError, match="outside the configured"):
        resolve_qbittorrent_save_path(
            _config(
                QBittorrentSavePathMode.TEMPLATE,
                r"D:\Media\{episode_title_exact}",
                series_colon_replace=ColonReplace.KEEP,
            ),
            context,
        )


def test_template_allows_an_ordinary_punctuated_episode_title() -> None:
    """The guard must not refuse titles that are merely punctuated.

    A question mark is not a path instruction, and after the exact token
    stopped stripping it this is the common case rather than the odd one.
    """
    context = _series_context_with_episode_title("Who Are You?")

    path = resolve_qbittorrent_save_path(
        _config(
            QBittorrentSavePathMode.TEMPLATE,
            "/mnt/media/{episode_title_exact}",
        ),
        context,
    )

    assert path == "/mnt/media/Who Are You?"


def test_template_allows_a_separator_in_a_title_that_stays_under_the_root() -> None:
    """`Face/Off` is a real title; nesting under the root is not an escape."""
    context = _movie_context()
    context.media_search.title = "Face/Off"

    path = resolve_qbittorrent_save_path(
        _config(QBittorrentSavePathMode.TEMPLATE, "/mnt/media/{title_exact}"),
        context,
    )

    assert path == "/mnt/media/Face/Off"
