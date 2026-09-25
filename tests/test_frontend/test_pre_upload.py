from pathlib import Path
from types import SimpleNamespace
from typing import cast

from PySide6.QtWidgets import QWidget
import pytest

from nfoforge.config.config import ConfigManager
from nfoforge.config.paths import ConfigPaths
from nfoforge.context.processing_context import ProcessingContext
from nfoforge.enums.media_type import MediaType
from nfoforge.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)
from nfoforge.enums.tracker_selection import TrackerSelection
from nfoforge.enums.wizard import WizardPages
from nfoforge.frontend.custom_widgets.client_listbox import (
    DelugeClientEdit,
    QBittorrentClientEdit,
    RTorrentClientEdit,
    TransmissionClientEdit,
    WatchFolderClientEdit,
)
from nfoforge.frontend.custom_widgets.pre_upload_widgets.client_options import (
    ClientOptionsSection,
)
from nfoforge.frontend.windows.main_window import MainWindow
from nfoforge.frontend.wizards.pre_upload import PreUploadPage
from nfoforge.frontend.wizards.wizard import MainWindowWizard
from nfoforge.payloads.clients import (
    DelugeConfig,
    QBittorrentConfig,
    RTorrentConfig,
    TransmissionConfig,
)
from nfoforge.payloads.media_inputs import MediaInputPayload
from nfoforge.payloads.watch_folder import WatchFolder
from tests.repo_paths import build_app_paths


def _paths(tmp_path: Path) -> ConfigPaths:
    return build_app_paths(tmp_path)


def test_client_options_section_tracks_and_resets_run_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    qbit = config.settings.torrent_clients.qbittorrent
    qbit.enabled = True
    qbit.save_path_mode = QBittorrentSavePathMode.SOURCE

    media_directory = tmp_path / "Cleaner (2025)"
    context = ProcessingContext(
        media_input=MediaInputPayload(
            input_path=media_directory / "Cleaner.2025.mkv",
            working_dir=tmp_path,
        )
    )
    parent = QWidget()
    section = ClientOptionsSection(
        config,
        context,
        parent,
    )

    section.load()
    assert section.destination_entry.text() == str(media_directory)

    override = r"\\plex_server\movies\Cleaner (2025)"
    section.destination_entry.setText(override)
    assert (
        context.torrent_client_options.save_path_overrides[
            TorrentClientSelection.QBITTORRENT
        ]
        == override
    )

    section.reset_button.click()
    assert (
        TorrentClientSelection.QBITTORRENT
        not in context.torrent_client_options.save_path_overrides
    )
    assert section.destination_entry.text() == str(media_directory)


def test_client_options_warns_for_remote_windows_save_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    qbit = config.settings.torrent_clients.qbittorrent
    qbit.enabled = True
    qbit.host = "https://seedbox.example"
    qbit.save_path_mode = QBittorrentSavePathMode.SOURCE

    context = ProcessingContext(
        media_input=MediaInputPayload(
            input_path=Path(r"C:\Media\Movie.mkv"),
            working_dir=tmp_path,
        )
    )
    section = ClientOptionsSection(config, context)
    section.load()

    assert "remote" in section.status_label.text()


def test_qbittorrent_settings_mode_controls_template_field() -> None:
    config = QBittorrentConfig(
        category="Movies",
        save_path_mode=QBittorrentSavePathMode.CLIENT_DEFAULT,
    )
    editor = QBittorrentClientEdit(config)
    assert editor.save_path_template.isEnabled() is False

    editor.save_path_mode.setCurrentIndex(
        editor.save_path_mode.findData(QBittorrentSavePathMode.TEMPLATE.value)
    )

    assert editor.save_path_template.isEnabled() is True


def test_concrete_client_editors_save_typed_settings() -> None:
    qbit = QBittorrentConfig()
    qbit_editor = QBittorrentClientEdit(qbit)
    qbit_editor.category.setText("Movies")
    qbit_editor.super_seeding.setChecked(True)
    qbit_editor.save()

    deluge = DelugeConfig()
    deluge_editor = DelugeClientEdit(deluge)
    deluge_editor.label.setText("TV")
    deluge_editor.path.setText("/downloads/tv")
    deluge_editor.save()

    rtorrent = RTorrentConfig()
    rtorrent_editor = RTorrentClientEdit(rtorrent)
    rtorrent_editor.host.setText("https://rtorrent.example")
    rtorrent_editor.label.setText("Movies")
    rtorrent_editor.verify_tls.setChecked(False)
    rtorrent_editor.ca_bundle.setText("/etc/ssl/private/rtorrent-ca.pem")
    rtorrent_editor.save()

    transmission = TransmissionConfig()
    transmission_editor = TransmissionClientEdit(transmission)
    transmission_editor.path.setText("/downloads/movies")
    transmission_editor.save()

    watch_folder = WatchFolder()
    watch_editor = WatchFolderClientEdit(watch_folder)
    watch_editor.path.setText("C:/watch")
    watch_editor.save()

    assert qbit.category == "Movies"
    assert qbit.super_seeding is True
    assert deluge.label == "TV"
    assert deluge.path == "/downloads/tv"
    assert rtorrent.host == "https://rtorrent.example"
    assert rtorrent.label == "Movies"
    assert rtorrent.verify_tls is False
    assert rtorrent.ca_bundle == "/etc/ssl/private/rtorrent-ca.pem"
    assert transmission.path == "/downloads/movies"
    assert watch_folder.path == Path("C:/watch")


def _routing_wizard(
    media_type: MediaType | None,
    *,
    rename: bool = True,
    screenshots: bool = True,
) -> MainWindowWizard:
    settings = SimpleNamespace(
        movie=SimpleNamespace(enabled=rename),
        series=SimpleNamespace(enabled=rename),
        screenshots=SimpleNamespace(enabled=screenshots),
    )
    return cast(
        MainWindowWizard,
        SimpleNamespace(
            config=SimpleNamespace(settings=settings),
            context=SimpleNamespace(
                media_search=SimpleNamespace(media_type=media_type)
            ),
        ),
    )


def test_wizard_routes_trackers_through_pre_upload() -> None:
    wizard = _routing_wizard(MediaType.MOVIE)

    assert (
        MainWindowWizard._flow_production(wizard, WizardPages.TRACKERS_PAGE)
        == WizardPages.PRE_UPLOAD_PAGE.value
    )
    assert (
        MainWindowWizard._flow_production(wizard, WizardPages.PRE_UPLOAD_PAGE)
        == WizardPages.PROCESS_PAGE.value
    )
    assert MainWindowWizard._flow_production(wizard, WizardPages.PROCESS_PAGE) == -1


@pytest.mark.parametrize(
    ("media_type", "expected"),
    [
        (MediaType.MOVIE, WizardPages.RENAME_ENCODE_MOVIES_PAGE),
        (MediaType.SERIES, WizardPages.RENAME_ENCODE_SERIES_PAGE),
    ],
)
def test_wizard_picks_the_rename_page_for_the_media_type(
    media_type: MediaType, expected: WizardPages
) -> None:
    wizard = _routing_wizard(media_type)
    before_rename = (
        WizardPages.SERIES_MATCHER_PAGE
        if media_type is MediaType.SERIES
        else WizardPages.MEDIA_SEARCH_PAGE
    )

    assert MainWindowWizard._flow_production(wizard, before_rename) == expected.value


@pytest.mark.parametrize(
    "start", [WizardPages.INPUT_PAGE, WizardPages.PLUGIN_INPUT_PAGE]
)
def test_wizard_leaves_either_input_page_for_search(start: WizardPages) -> None:
    wizard = _routing_wizard(None)

    assert (
        MainWindowWizard._flow_production(wizard, start)
        == WizardPages.MEDIA_SEARCH_PAGE.value
    )


def test_wizard_skips_disabled_optional_pages() -> None:
    wizard = _routing_wizard(MediaType.MOVIE, rename=False, screenshots=False)

    assert (
        MainWindowWizard._flow_production(wizard, WizardPages.MEDIA_SEARCH_PAGE)
        == WizardPages.TRACKERS_PAGE.value
    )


def test_pre_upload_page_applies_release_notes_and_hides_disabled_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    config.settings.torrent_clients.qbittorrent.enabled = False
    tracker = TrackerSelection.BEYOND_HD
    config.settings.trackers.beyond_hd.nfo_template = "movie"

    context = ProcessingContext(
        media_input=MediaInputPayload(working_dir=tmp_path),
    )
    context.shared_data.selected_trackers = [tracker]
    parent = QWidget()
    page = PreUploadPage(config, context, cast(MainWindow, parent))

    page.initializePage()
    page.release_notes.setChecked(True)
    page.release_notes.dict_widget.text_box.setPlainText("A release note")

    assert page.client_options.isVisible() is False
    assert page.validatePage() is True
    assert context.shared_data.release_notes == "A release note"


def test_pre_upload_page_loads_and_applies_plugin_encode_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    config.settings.torrent_clients.qbittorrent.enabled = False
    tracker = TrackerSelection.BEYOND_HD
    config.settings.trackers.beyond_hd.nfo_template = "movie"

    context = ProcessingContext(
        media_input=MediaInputPayload(working_dir=tmp_path),
    )
    context.shared_data.selected_trackers = [tracker]
    context.shared_data.encode_logs = "log supplied by a plugin"
    parent = QWidget()
    page = PreUploadPage(config, context, cast(MainWindow, parent))

    page.initializePage()

    assert page.encode_logs.text_box.toPlainText() == "log supplied by a plugin"

    page.encode_logs.text_box.setPlainText("reviewed encode log")

    assert page.validatePage() is True
    assert context.shared_data.encode_logs == "reviewed encode log"


def test_pre_upload_page_blocks_missing_template_assignment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nfoforge.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    config.settings.torrent_clients.qbittorrent.enabled = False
    tracker = TrackerSelection.BEYOND_HD
    config.settings.trackers.beyond_hd.nfo_template = ""

    context = ProcessingContext(
        media_input=MediaInputPayload(working_dir=tmp_path),
    )
    context.shared_data.selected_trackers = [tracker]
    parent = QWidget()
    page = PreUploadPage(config, context, cast(MainWindow, parent))

    page.initializePage()

    assert page.validatePage() is False
    assert "Missing" in page.error_label.text()
