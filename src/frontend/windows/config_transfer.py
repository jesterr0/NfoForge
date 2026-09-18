"""Exporting a configuration, and importing one, from Settings.

A thin layer over `src.config.transfer`, which holds every rule about what may
leave the machine, what is refused on the way in and what is never overwritten.
Nothing is decided here; these windows choose what to ask and how to report it.

Not threaded, unlike `legacy_import`. That copies a hand-assembled toolchain and
can take minutes; a bundle is profiles and templates, measured in kilobytes, and
a progress dialog for it would flash and vanish.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
import tomllib

from src.backend.template_selector import TEMPLATE_SUFFIX
from src.backend.utils.file_utilities import open_explorer
from src.config.config import ConfigManager
from src.config.paths import AppPaths
from src.config.profiles import PROFILE_SUFFIX
from src.config.transfer import (
    BundleContents,
    Disposition,
    ImportPlan,
    NameConflict,
    TransferError,
    apply_import,
    available_profiles,
    export_bundle,
    plan_import,
    read_bundle,
    referenced_templates,
    render_export_summary,
    render_import_summary,
)
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.utils import build_h_line

IMPORT_FILTER = "NfoForge configuration (*.zip *.toml)"
EXPORT_FILTER = "NfoForge configuration bundle (*.zip)"


class ConfigExportDialog(QDialog):
    """Which profiles to export, and whether to include what is secret.

    The templates a selection pulls in are shown rather than merely carried,
    because they are the part a user does not think of: a profile names them,
    so they come too, and seeing which ones is how a user notices they picked
    the wrong profile.
    """

    def __init__(
        self,
        paths: AppPaths,
        active_profile: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._documents: dict[str, dict[str, Any]] = {}

        self.setWindowTitle("Export configuration")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Choose the profiles to export. The NFO templates they name "
                "are included automatically.",
                wordWrap=True,
                parent=self,
            )
        )

        self.profile_list = QListWidget(self)
        self.profile_list.setObjectName("exportProfileList")
        self.profile_list.itemChanged.connect(self._refresh)
        layout.addWidget(self.profile_list)

        layout.addWidget(QLabel("Templates included", parent=self))
        self.template_list = QListWidget(self)
        self.template_list.setObjectName("exportTemplateList")
        self.template_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.template_list.setMaximumHeight(110)
        layout.addWidget(self.template_list)

        layout.addWidget(build_h_line((6, 1, 6, 1)))

        self.include_credentials = QCheckBox("Include credentials", self)
        self.include_credentials.setToolTip(
            "Tracker API keys, passkeys, announce URLs, passwords, two-factor "
            "seeds and torrent client logins"
        )
        self.include_credentials.toggled.connect(self._refresh_warning)
        layout.addWidget(self.include_credentials)

        self.warning = QLabel(parent=self, wordWrap=True)
        layout.addWidget(self.warning)

        self.button_box = QDialogButtonBox(parent=self)
        self.export_button = QPushButton("Export...", parent=self)
        self.cancel_button = QPushButton("Cancel", parent=self)
        self.export_button.setDefault(True)
        self.cancel_button.setAutoDefault(False)
        self.button_box.addButton(
            self.export_button, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.button_box.addButton(
            self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole
        )
        self.export_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.button_box)

        self._load(available_profiles(paths), active_profile)
        self._refresh_warning()

    def _load(self, names: tuple[str, ...], active: str | None) -> None:
        for name in names:
            item = QListWidgetItem(name, self.profile_list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name == active else Qt.CheckState.Unchecked
            )
        self._refresh()

    def selected_profiles(self) -> tuple[str, ...]:
        return tuple(
            item.text()
            for item in self._items()
            if item.checkState() is Qt.CheckState.Checked
        )

    def _items(self) -> tuple[QListWidgetItem, ...]:
        return tuple(
            item
            for item in (
                self.profile_list.item(row) for row in range(self.profile_list.count())
            )
            if item is not None
        )

    @Slot()
    def _refresh(self) -> None:
        selected = self.selected_profiles()
        self.export_button.setEnabled(bool(selected))

        wanted: set[str] = set()
        for name in selected:
            wanted |= referenced_templates(self._document(name))

        self.template_list.clear()
        for stem in sorted(wanted):
            # A profile naming a template that is no longer on disk is an
            # ordinary state to be in, so it is shown as missing rather than
            # hidden -- the export goes ahead without it either way, and this
            # is the one moment the user is looking at the list.
            exists = (self._paths.templates / f"{stem}{TEMPLATE_SUFFIX}").is_file()
            QListWidgetItem(stem if exists else f"{stem} (missing)", self.template_list)

    def _document(self, name: str) -> dict[str, Any]:
        """One profile, parsed once and kept.

        Read with `tomllib` rather than through `ConfigManager`: this only
        needs the template names, and a profile the user has not opened in a
        while may legitimately fail validation without being unexportable.
        """
        if name not in self._documents:
            source = self._paths.user_configs / f"{name}{PROFILE_SUFFIX}"
            try:
                self._documents[name] = tomllib.loads(
                    source.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, tomllib.TOMLDecodeError):
                self._documents[name] = {}
        return self._documents[name]

    @Slot()
    def _refresh_warning(self) -> None:
        if self.include_credentials.isChecked():
            self.warning.setText(
                "The bundle will hold your tracker keys, passkeys and "
                "passwords in plain text. Suitable for moving to another "
                "machine of your own; treat the file as you would the "
                "credentials themselves."
            )
        else:
            self.warning.setText(
                "Credentials are removed. Your releaser name and group tag "
                "are not credentials and are kept."
            )

    def suggested_name(self) -> str:
        stamp = datetime.now().strftime("%Y-%m-%d")
        return f"nfoforge-config-{stamp}.zip"


class ConfigImportDialog(QDialog):
    """What a bundle holds, and what importing it would do.

    Shown before anything is written, because the interesting part of an import
    is the names: a bundle from someone else routinely carries a profile or a
    template named the same as one already here, and which of the two survives
    is the user's decision, not this window's.
    """

    def __init__(
        self,
        paths: AppPaths,
        contents: BundleContents,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._contents = contents

        self.setWindowTitle("Import configuration")
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self._describe(), wordWrap=True, parent=self))
        layout.addWidget(build_h_line((6, 1, 6, 1)))

        layout.addWidget(QLabel("If a name is already in use", parent=self))
        self.policy_combo = CustomComboBox(disable_mouse_wheel=True, parent=self)
        self.policy_combo.setObjectName("importPolicyCombo")
        for policy in NameConflict:
            self.policy_combo.addItem(policy.value, policy)
        self.policy_combo.setToolTip(
            "Keep both renames what is coming in. Skip leaves what is already "
            "here. Replace keeps a copy of what was there in old_configs."
        )
        self.policy_combo.activated.connect(self._replan)
        layout.addWidget(self.policy_combo)

        self.plan_tree = QTreeWidget(self)
        self.plan_tree.setObjectName("importPlanTree")
        self.plan_tree.setColumnCount(4)
        self.plan_tree.setHeaderLabels(
            ("Type", "In the bundle", "Lands as", "What happens")
        )
        self.plan_tree.setRootIsDecorated(False)
        self.plan_tree.setAlternatingRowColors(True)
        self.plan_tree.setMinimumHeight(180)
        header = self.plan_tree.header()
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.plan_tree)

        self.note = QLabel(parent=self, wordWrap=True)
        if not contents.manifest.credentials_included:
            self.note.setText(
                "This bundle was exported without credentials. Tracker keys, "
                "passkeys and passwords will be empty and have to be set "
                "before anything can be uploaded."
            )
        layout.addWidget(self.note)

        self.button_box = QDialogButtonBox(parent=self)
        self.import_button = QPushButton("Import", parent=self)
        self.cancel_button = QPushButton("Cancel", parent=self)
        self.import_button.setDefault(True)
        self.cancel_button.setAutoDefault(False)
        self.button_box.addButton(
            self.import_button, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.button_box.addButton(
            self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole
        )
        self.import_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.button_box)

        self._plan = plan_import(paths, contents, NameConflict.KEEP_BOTH)
        self._render()

    def _describe(self) -> str:
        manifest = self._contents.manifest
        parts = [f"{self._contents.source.name}"]
        if manifest.app_version:
            parts.append(f"written by NfoForge {manifest.app_version}")
        if manifest.created:
            parts.append(f"on {manifest.created}")
        return (
            ", ".join(parts)
            + f".\n{len(self._contents.profiles)} profile(s), "
            + f"{len(self._contents.templates)} template(s)."
        )

    def plan(self) -> ImportPlan:
        return self._plan

    @Slot()
    def _replan(self) -> None:
        policy = self.policy_combo.currentData()
        if not isinstance(policy, NameConflict):
            return
        self._plan = plan_import(self._paths, self._contents, policy)
        self._render()

    def _render(self) -> None:
        self.plan_tree.clear()
        for entry in self._plan.entries:
            QTreeWidgetItem(
                self.plan_tree,
                (
                    entry.kind.value,
                    entry.source_name,
                    "--"
                    if entry.disposition is Disposition.SKIPPED
                    else entry.destination_name,
                    entry.disposition.value,
                ),
            )


class TransferSummaryDialog(QDialog):
    """What an export or an import actually did.

    The text comes from `src.config.transfer` so that this window and anything
    else reporting the same run cannot describe it differently.
    """

    def __init__(
        self,
        title: str,
        intro: str,
        detail: str,
        reveal: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._reveal = reveal

        self.setWindowTitle(title)
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(intro, wordWrap=True, parent=self))

        self.detail_view = QTextEdit(parent=self)
        self.detail_view.setObjectName("transferSummaryDetail")
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlainText(detail)
        layout.addWidget(self.detail_view)

        button_box = QDialogButtonBox(parent=self)
        self.open_button = QPushButton("Open folder", parent=self)
        self.close_button = QPushButton("Close", parent=self)
        self.open_button.setAutoDefault(False)
        self.close_button.setDefault(True)
        button_box.addButton(self.open_button, QDialogButtonBox.ButtonRole.ActionRole)
        button_box.addButton(self.close_button, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(button_box)

        self.open_button.clicked.connect(lambda: open_explorer(self._reveal))
        self.close_button.clicked.connect(self.accept)


def export_configuration(parent: QWidget, config: ConfigManager) -> None:
    """Ask what to export, then write it, reporting either way.

    `TransferError` is caught here rather than allowed to propagate: both
    callers are Qt slots, where a raised exception reaches the global handler
    as a traceback naming a TOML key.
    """
    try:
        profiles = available_profiles(config.paths)
    except TransferError as error:
        QMessageBox.critical(parent, "Export", str(error))
        return
    if not profiles:
        QMessageBox.information(
            parent, "Export", "There are no profiles to export yet."
        )
        return

    dialog = ConfigExportDialog(
        config.paths, config.program.current_config, parent=parent
    )
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_profiles()
        include_credentials = dialog.include_credentials.isChecked()
        suggested = dialog.suggested_name()
    finally:
        dialog.deleteLater()

    chosen, _ = QFileDialog.getSaveFileName(
        parent,
        "Save configuration bundle",
        str(Path.home() / suggested),
        EXPORT_FILTER,
    )
    if not chosen:
        return

    try:
        outcome = export_bundle(
            config.paths, selected, Path(chosen), include_credentials
        )
    except TransferError as error:
        QMessageBox.critical(parent, "Export", str(error))
        return

    summary = TransferSummaryDialog(
        "Export complete",
        f"{len(outcome.profiles)} profile(s) written to a bundle you can copy "
        "to another machine or hand to someone else.",
        render_export_summary(outcome),
        outcome.archive.parent,
        parent=parent,
    )
    summary.exec()
    summary.deleteLater()


def import_configuration(parent: QWidget, config: ConfigManager) -> bool:
    """Ask for a bundle, show what it would do, then do it.

    Returns whether anything was written, so the caller can reload the list of
    profiles rather than leaving one on screen that no longer matches disk.
    """
    chosen, _ = QFileDialog.getOpenFileName(
        parent, "Select a configuration bundle", str(Path.home()), IMPORT_FILTER
    )
    if not chosen:
        return False

    try:
        contents = read_bundle(Path(chosen))
    except TransferError as error:
        QMessageBox.critical(parent, "Import", str(error))
        return False

    dialog = ConfigImportDialog(config.paths, contents, parent=parent)
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        plan = dialog.plan()
    finally:
        dialog.deleteLater()

    try:
        outcome = apply_import(config.paths, contents, plan, config)
    except TransferError as error:
        QMessageBox.critical(
            parent,
            "Import",
            f"{error}\n\nNothing was imported and your existing profiles are "
            "unchanged.",
        )
        return False

    summary = TransferSummaryDialog(
        "Import complete",
        f"{len(outcome.written)} file(s) imported. Nothing that was already "
        "here was overwritten.",
        render_import_summary(outcome),
        config.paths.state_root,
        parent=parent,
    )
    summary.exec()
    summary.deleteLater()
    return bool(outcome.written)
