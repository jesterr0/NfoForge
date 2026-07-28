from copy import deepcopy
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import cast

import pytest

from src.backend.torrent_clients.qbittorrent.save_path import (
    resolve_qbittorrent_save_path,
)
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.models import AppConfig
from src.context.processing_context import ProcessingContext
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)
from src.exceptions import TrackerClientError
from src.payloads.clients import QBittorrentConfig
from src.payloads.media_inputs import MediaInputPayload


def _config(
    mode: QBittorrentSavePathMode,
    template: str = "",
    user_tokens: dict[str, tuple[str, object]] | None = None,
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
            general=SimpleNamespace(releasers_name=""),
            global_management=SimpleNamespace(
                title_clean_rules=[],
                video_dynamic_range=None,
            ),
            series=SimpleNamespace(
                multi_episode_style=MultiEpisodeStyle.RANGE,
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
