from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QWidget
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.torrent_client import QBittorrentAuthMode, TorrentClientSelection
from src.frontend.custom_widgets.client_listbox import QBittorrentClientEdit
from src.frontend.custom_widgets.client_settings import ClientSettingsWidget
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.stacked_windows.settings.clients import ClientsSettings
from tests.repo_paths import build_app_paths


def _paths(tmp_path: Path) -> ConfigPaths:
    return build_app_paths(tmp_path)


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", _paths(tmp_path))


def test_client_settings_builds_fixed_dual_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    widget = ClientSettingsWidget(config)
    widget.load_from_config()

    assert widget.client_list.count() == len(TorrentClientSelection)
    assert widget.client_stack.count() == len(TorrentClientSelection)
    assert [
        widget.client_list.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(widget.client_list.count())
    ] == list(TorrentClientSelection)
    assert (
        widget.client_list.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
    )
    assert widget.client_list.dragEnabled() is False
    assert widget.client_list.acceptDrops() is False
    assert all(
        not bool(widget.client_list.item(index).flags() & Qt.ItemFlag.ItemIsDragEnabled)
        for index in range(widget.client_list.count())
    )


def test_client_settings_changes_are_transactional_until_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    parent = QWidget()
    settings = ClientsSettings(
        config,
        main_window=cast(Any, None),
        parent=cast(Any, parent),
    )
    editor = cast(
        QBittorrentClientEdit,
        settings.client_widget._editor_map[TorrentClientSelection.QBITTORRENT],
    )
    live_config = config.settings.torrent_clients.qbittorrent
    original_category = live_config.category

    editor.category.setText("Movies")
    assert live_config.category == original_category

    settings._save_settings()

    assert live_config.category == "Movies"


def _qbittorrent_editor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ClientsSettings, QBittorrentClientEdit]:
    config = _config(tmp_path, monkeypatch)
    parent = QWidget()
    settings = ClientsSettings(
        config,
        main_window=cast(Any, None),
        parent=cast(Any, parent),
    )
    editor = cast(
        QBittorrentClientEdit,
        settings.client_widget._editor_map[TorrentClientSelection.QBITTORRENT],
    )
    return settings, editor


def _select_auth_mode(editor: QBittorrentClientEdit, mode: QBittorrentAuthMode) -> None:
    editor.auth_mode.setCurrentIndex(editor.auth_mode.findData(mode.value))


def _set_qbittorrent_enabled(settings: ClientsSettings, enabled: bool) -> None:
    """Tick the client's row, which is what `enabled` is read from.

    `save_editor_settings` syncs the list checkboxes over the config, so
    setting the field directly would be undone before validation runs.
    """
    client_list = settings.client_widget.client_list
    for index in range(client_list.count()):
        item = client_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) is TorrentClientSelection.QBITTORRENT:
            item.setCheckState(
                Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
            )
            return
    raise AssertionError("no qBittorrent row in the client list")


def test_the_default_auth_mode_leaves_the_api_key_field_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, editor = _qbittorrent_editor(tmp_path, monkeypatch)

    assert editor.auth_mode.currentData() == QBittorrentAuthMode.USER_PASS.value
    assert editor.user.isEnabled()
    assert editor.password.isEnabled()
    assert not editor.api_key.isEnabled()


def test_choosing_the_api_key_mode_swaps_which_fields_are_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, editor = _qbittorrent_editor(tmp_path, monkeypatch)

    _select_auth_mode(editor, QBittorrentAuthMode.API_KEY)

    assert not editor.user.isEnabled()
    assert not editor.password.isEnabled()
    assert editor.api_key.isEnabled()


def test_saving_in_api_key_mode_clears_the_stored_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The two are alternatives, so only the selected one is kept. Holding
    # both would leave a password in the profile that nothing ever sends.
    settings, editor = _qbittorrent_editor(tmp_path, monkeypatch)
    editor.user.setText("admin")
    editor.password.setText("password")
    _select_auth_mode(editor, QBittorrentAuthMode.API_KEY)
    editor.api_key.setText("qbt_" + "x" * 28)

    settings._save_settings()
    stored = settings.config.settings.torrent_clients.qbittorrent

    assert stored.auth_mode is QBittorrentAuthMode.API_KEY
    assert stored.api_key == "qbt_" + "x" * 28
    assert stored.user == ""
    assert stored.password == ""


def test_saving_in_user_pass_mode_clears_the_stored_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, editor = _qbittorrent_editor(tmp_path, monkeypatch)
    _select_auth_mode(editor, QBittorrentAuthMode.API_KEY)
    editor.api_key.setText("qbt_" + "x" * 28)
    _select_auth_mode(editor, QBittorrentAuthMode.USER_PASS)
    editor.user.setText("admin")
    editor.password.setText("password")

    settings._save_settings()
    stored = settings.config.settings.torrent_clients.qbittorrent

    assert stored.auth_mode is QBittorrentAuthMode.USER_PASS
    assert stored.api_key == ""
    assert stored.user == "admin"


def test_an_enabled_client_in_api_key_mode_needs_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, editor = _qbittorrent_editor(tmp_path, monkeypatch)
    _set_qbittorrent_enabled(settings, True)
    _select_auth_mode(editor, QBittorrentAuthMode.API_KEY)
    editor.api_key.setText("   ")

    error = settings.validation_error()

    assert error is not None
    assert "API key" in error


def test_a_disabled_client_is_not_held_to_the_api_key_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A client nobody injects with cannot block saving the rest of Settings.
    settings, editor = _qbittorrent_editor(tmp_path, monkeypatch)
    _set_qbittorrent_enabled(settings, False)
    _select_auth_mode(editor, QBittorrentAuthMode.API_KEY)
    editor.api_key.setText("")

    assert settings.validation_error() is None


def _left_click(event_type: QEvent.Type) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        QPointF(0, 0),
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_masked_field_reveals_only_while_the_mouse_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Client passwords use `masked=True` (see `FullConnectionClientEditBase`
    # above). Revealing used to happen on hover, which exposed the password
    # to anyone whose screen was being shared whenever the pointer merely
    # crossed the field. It must now reveal only while the button is held.
    config = _config(tmp_path, monkeypatch)
    parent = QWidget()
    settings = ClientsSettings(
        config,
        main_window=cast(Any, None),
        parent=cast(Any, parent),
    )
    editor = cast(
        QBittorrentClientEdit,
        settings.client_widget._editor_map[TorrentClientSelection.QBITTORRENT],
    )
    field = editor.password
    assert field.echoMode() == QLineEdit.EchoMode.Password

    field.mousePressEvent(_left_click(QEvent.Type.MouseButtonPress))
    assert field.echoMode() == QLineEdit.EchoMode.Normal

    field.mouseReleaseEvent(_left_click(QEvent.Type.MouseButtonRelease))
    assert field.echoMode() == QLineEdit.EchoMode.Password


def test_unmasked_field_ignores_press_and_release() -> None:
    # `masked` is opt-in; an unmasked field must not change echo mode at all.
    field = MaskedQLineEdit(masked=False)
    assert field.echoMode() == QLineEdit.EchoMode.Normal

    field.mousePressEvent(_left_click(QEvent.Type.MouseButtonPress))
    assert field.echoMode() == QLineEdit.EchoMode.Normal

    field.mouseReleaseEvent(_left_click(QEvent.Type.MouseButtonRelease))
    assert field.echoMode() == QLineEdit.EchoMode.Normal
