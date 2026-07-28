from pathlib import Path
from types import SimpleNamespace
from typing import cast

from PySide6.QtWidgets import QComboBox, QLineEdit, QWidget
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.context.processing_context import ProcessingContext
from src.enums.torrent_client import (
    QBittorrentSavePathMode,
    TorrentClientSelection,
)
from src.enums.tracker_selection import TrackerSelection
from src.enums.wizard import WizardPages
from src.frontend.custom_widgets.client_listbox import ClientEdit
from src.frontend.windows.main_window import MainWindow
from src.frontend.wizards.client_options import ClientOptionsSection
from src.frontend.wizards.pre_upload import PreUploadPage
from src.frontend.wizards.wizard import MainWindowWizard
from src.payloads.media_inputs import MediaInputPayload


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = Path("runtime/config/defaults")
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (source_defaults / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (source_defaults / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def test_client_options_section_tracks_and_resets_run_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    qbit = config.settings.torrent_clients.qbittorrent
    qbit.enabled = True
    qbit.specific_params["save_path_mode"] = QBittorrentSavePathMode.SOURCE.value

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


def test_qbittorrent_settings_mode_controls_template_field() -> None:
    editor = ClientEdit()
    editor.build_widgets_from_dict(
        {
            "category": "Movies",
            "super_seeding": False,
            "save_path_mode": QBittorrentSavePathMode.CLIENT_DEFAULT.value,
            "save_path_template": "",
        }
    )
    mode = editor.specific_params_map["save_path_mode"]
    template = editor.specific_params_map["save_path_template"]
    assert isinstance(mode, QComboBox)
    assert isinstance(template, QLineEdit)
    assert template.isEnabled() is False

    mode.setCurrentIndex(mode.findData(QBittorrentSavePathMode.TEMPLATE.value))

    assert template.isEnabled() is True


def test_wizard_routes_trackers_through_pre_upload() -> None:
    wizard = cast(
        MainWindowWizard,
        SimpleNamespace(
            _START_PAGES=(),
        ),
    )

    assert (
        MainWindowWizard._flow_production(
            wizard,
            WizardPages.TRACKERS_PAGE,
        )
        == WizardPages.PRE_UPLOAD_PAGE.value
    )
    assert (
        MainWindowWizard._flow_production(
            wizard,
            WizardPages.PRE_UPLOAD_PAGE,
        )
        == WizardPages.PROCESS_PAGE.value
    )


def test_pre_upload_page_applies_release_notes_and_hides_disabled_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    config.settings.torrent_clients.qbittorrent.enabled = False
    tracker = TrackerSelection.MORE_THAN_TV
    config.settings.trackers.more_than_tv.nfo_template = "movie"

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


def test_pre_upload_page_blocks_missing_template_assignment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    config = ConfigManager("test", _paths(tmp_path))
    config.settings.torrent_clients.qbittorrent.enabled = False
    tracker = TrackerSelection.MORE_THAN_TV
    config.settings.trackers.more_than_tv.nfo_template = ""

    context = ProcessingContext(
        media_input=MediaInputPayload(working_dir=tmp_path),
    )
    context.shared_data.selected_trackers = [tracker]
    parent = QWidget()
    page = PreUploadPage(config, context, cast(MainWindow, parent))

    page.initializePage()

    assert page.validatePage() is False
    assert "Missing" in page.error_label.text()
