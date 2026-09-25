from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from nfoforge.backend.utils.file_utilities import open_explorer
from nfoforge.config.config import ConfigManager
from nfoforge.config.models import PluginSettings as PluginSettingsPayload
from nfoforge.config.paths import DEV_PLUGINS_ENV_VAR, dev_plugin_dirs
from nfoforge.frontend.custom_widgets.combo_box import CustomComboBox
from nfoforge.frontend.stacked_windows.settings.base import BaseSettings
from nfoforge.frontend.utils import build_h_line, create_form_layout
from nfoforge.frontend.utils.app_lifecycle import restart_application
from nfoforge.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from nfoforge.frontend.windows.plugin_install import (
    install_from_archive,
    install_from_folder,
)
from nfoforge.plugins.api import PluginRecord

if TYPE_CHECKING:
    from nfoforge.frontend.stacked_windows.settings.settings import Settings
    from nfoforge.frontend.windows.main_window import MainWindow


_CAPABILITY_LABELS = {
    "wizard_page": "Wizard input",
    "token_replacer": "Token replacement",
    "pre_upload": "Pre-upload",
    "post_upload": "Post-upload",
    "metadata_transformer": "Metadata transformation",
    "image_host_uploader": "Image host uploader",
    "duplicate_checker": "Duplicate checker",
    "jinja2_filters": "Jinja filters",
    "jinja2_functions": "Jinja functions",
    "flat_filters": "Flat filters",
}


class PluginsSettings(BaseSettings):
    """Configure external plugin execution and inspect discovery status."""

    def __init__(
        self, config: ConfigManager, main_window: MainWindow, parent: Settings
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("pluginsSettings")

        intro = QLabel(
            "External plugins are imported only when enabled at startup. Disabling "
            "plugins keeps saved selections but prevents plugin code, hooks, and "
            "template contributions from loading. Applying a change to this "
            "setting will prompt you to restart NfoForge so it can take effect.",
            self,
        )
        intro.setWordWrap(True)

        self.enable_plugins = QCheckBox("Enable External Plugins", self)
        self.enable_plugins.toggled.connect(self._set_selection_enabled)

        self.plugin_wizard_page_combo = self._create_combo()
        self.plugin_token_replacer_combo = self._create_combo()
        self.plugin_pre_upload_combo = self._create_combo()
        self.plugin_post_upload_combo = self._create_combo()
        self.plugin_metadata_transformer_combo = self._create_combo()
        self.plugin_image_host_uploader_combo = self._create_combo()
        self.plugin_duplicate_checker_combo = self._create_combo()

        selectors = (
            (
                "Wizard Input Page",
                "Choose an optional plugin-provided wizard input page.",
                self.plugin_wizard_page_combo,
            ),
            (
                "Token Replacer",
                "Choose an optional plugin to replace tokens during processing.",
                self.plugin_token_replacer_combo,
            ),
            (
                "Pre-upload Processor",
                "Choose an optional plugin to run before tracker uploads.",
                self.plugin_pre_upload_combo,
            ),
            (
                "Post-upload Processor",
                "Choose an optional plugin to run after tracker uploads finish.",
                self.plugin_post_upload_combo,
            ),
            (
                "Metadata Transformer",
                "Choose an optional plugin to transform completed TMDB metadata.",
                self.plugin_metadata_transformer_combo,
            ),
            (
                "Image Host Uploader",
                "Choose an optional plugin to upload screenshots to a custom image "
                'host, selectable per tracker as "Plugin".',
                self.plugin_image_host_uploader_combo,
            ),
            (
                "Duplicate Checker",
                "Choose an optional plugin to supplement built-in dupe checking "
                "with an additional source, per tracker.",
                self.plugin_duplicate_checker_combo,
            ),
        )
        self._selection_widgets = tuple(combo for _, _, combo in selectors)

        self.plugin_dir_entry = QLineEdit(self)
        self.plugin_dir_entry.setReadOnly(True)
        self.plugin_dir_entry.setText(str(self.config.paths.plugins))
        self.plugin_dir_entry.setToolTip(str(self.config.paths.plugins))

        self.plugin_dir_open_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.plugin_dir_open_btn, "ph.folder-open-light", icon_size=QSize(20, 20)
        )
        self.plugin_dir_open_btn.setToolTip("Open plugins folder")
        self.plugin_dir_open_btn.clicked.connect(self._handle_open_plugin_dir_click)

        # A popup rather than two buttons: both entries do the same thing and
        # differ only in what is pointed at, so they belong under one verb.
        self.install_plugin_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.install_plugin_btn, "ph.package-light", icon_size=QSize(20, 20)
        )
        self.install_plugin_btn.setToolTip("Install a plugin")
        self.install_plugin_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.install_menu = QMenu(self.install_plugin_btn)
        self.install_folder_action = self.install_menu.addAction("From folder...")
        self.install_archive_action = self.install_menu.addAction("From archive...")
        self.install_folder_action.triggered.connect(
            self._handle_install_from_folder_click
        )
        self.install_archive_action.triggered.connect(
            self._handle_install_from_archive_click
        )
        self.install_plugin_btn.setMenu(self.install_menu)

        plugin_dir_widget = QWidget()
        plugin_dir_layout = QHBoxLayout(plugin_dir_widget)
        plugin_dir_layout.setContentsMargins(0, 0, 0, 0)
        plugin_dir_layout.addWidget(self.plugin_dir_entry, stretch=1)
        plugin_dir_layout.addWidget(self.plugin_dir_open_btn)
        plugin_dir_layout.addWidget(self.install_plugin_btn)

        # Shown only while the override is set, so a user who is not developing
        # a plugin never sees it. Saying nothing would be the worse default: the
        # field above still names the folder plugins are installed into and is
        # still right about that, but nothing is being loaded from it, and a
        # developer who left the variable set in a shell profile would have
        # nothing on screen to explain why what they installed is not there.
        # Both facts are stated, because the Install button beside it still
        # writes to the folder above.
        dev_dirs = dev_plugin_dirs()
        self.dev_plugin_dirs_label = QLabel(self)
        self.dev_plugin_dirs_label.setWordWrap(True)
        self.dev_plugin_dirs_label.setVisible(bool(dev_dirs))
        if dev_dirs:
            listed = "\n".join(str(directory) for directory in dev_dirs)
            self.dev_plugin_dirs_label.setText(
                f"{DEV_PLUGINS_ENV_VAR} is set, so plugins are loaded from here "
                "instead. The folder above is not read while it is set, though "
                f"Install still writes to it:\n{listed}"
            )
            self.dev_plugin_dirs_label.setToolTip(listed)

        self.plugin_status = QTreeWidget(self)
        self.plugin_status.setObjectName("pluginStatus")
        self.plugin_status.setColumnCount(4)
        self.plugin_status.setHeaderLabels(
            ("Plugin", "Version", "Capabilities", "Status")
        )
        self.plugin_status.setRootIsDecorated(False)
        self.plugin_status.setAlternatingRowColors(True)
        self.plugin_status.setMinimumHeight(180)
        header = self.plugin_status.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.add_widget(intro)
        self.add_layout(create_form_layout(self.enable_plugins))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        for title, tooltip, combo in selectors:
            label = QLabel(title, self)
            label.setToolTip(tooltip)
            combo.setToolTip(tooltip)
            self.add_layout(create_form_layout(label, combo))
        self.add_widget(build_h_line((10, 1, 10, 1)))
        plugin_dir_label = QLabel("Plugins Folder", self)
        plugin_dir_label.setToolTip(
            "Each plugin is one folder here, holding an nfoforge-plugin.toml. "
            "Copying a folder in by hand works and is still the documented way; "
            "Install does the same thing with the manifest checked first."
        )
        self.add_layout(create_form_layout(plugin_dir_label, plugin_dir_widget))
        self.add_widget(self.dev_plugin_dirs_label)
        status_label = QLabel("Discovered Plugins", self)
        status_label.setToolTip(
            "Plugins loaded at startup, load failures, and configured plugins that "
            "are currently unavailable."
        )
        self.add_widget(status_label)
        self.add_widget(self.plugin_status)
        self.add_layout(self.reset_layout)

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)
        self._load_saved_settings()

    @Slot()
    def _handle_open_plugin_dir_click(self) -> None:
        # Created on the way out rather than assumed: nothing creates it until
        # a load runs, so on a fresh installation with plugins disabled there
        # is no folder to open and the click would do nothing at all.
        self.config.paths.plugins.mkdir(parents=True, exist_ok=True)
        open_explorer(self.config.paths.plugins)

    @Slot()
    def _handle_install_from_folder_click(self) -> None:
        self._after_install(install_from_folder(self, self.config.paths))

    @Slot()
    def _handle_install_from_archive_click(self) -> None:
        self._after_install(install_from_archive(self, self.config.paths))

    def _after_install(self, destination: Path | None) -> None:
        """Offer the restart a newly installed plugin needs to be loaded.

        Plugins are imported once, at startup, so one that arrives afterwards
        is on disk and inert. Left unsaid, that reads as an install that did
        not work, and the discovered-plugins table below agrees -- it is built
        from what was loaded, which does not include this.
        """
        if destination is None:
            return
        self._load_plugin_status()
        if (
            QMessageBox.question(
                self,
                "Restart Required",
                "The plugin was installed. NfoForge loads plugins at startup, "
                "so it has to be restarted before this one is available. "
                "Restart now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            is QMessageBox.StandardButton.Yes
        ):
            restart_application(self.main_window)

    def _create_combo(self) -> CustomComboBox:
        return CustomComboBox(
            completer=True,
            disable_mouse_wheel=True,
            parent=self,
        )

    @Slot()
    def _load_saved_settings(self) -> None:
        self.enable_plugins.setChecked(self.config.settings.general.enable_plugins)
        self._load_plugin_combos(self.config.settings.plugins)
        self._load_plugin_status()
        self._set_selection_enabled(self.enable_plugins.isChecked())

    def _load_plugin_combos(self, selections: PluginSettingsPayload) -> None:
        capability_combos = (
            (
                "wizard_page",
                "Default Input",
                self.plugin_wizard_page_combo,
                selections.wizard_page,
            ),
            (
                "token_replacer",
                "Default Token Replacer",
                self.plugin_token_replacer_combo,
                selections.token_replacer,
            ),
            (
                "pre_upload",
                "Default Pre-upload Processing",
                self.plugin_pre_upload_combo,
                selections.pre_upload,
            ),
            (
                "post_upload",
                "Default Post-upload Processing",
                self.plugin_post_upload_combo,
                selections.post_upload,
            ),
            (
                "metadata_transformer",
                "TMDB Metadata",
                self.plugin_metadata_transformer_combo,
                selections.metadata_transformer,
            ),
            (
                "image_host_uploader",
                "Default Image Host Uploader",
                self.plugin_image_host_uploader_combo,
                selections.image_host_uploader,
            ),
            (
                "duplicate_checker",
                "Default Duplicate Checker",
                self.plugin_duplicate_checker_combo,
                selections.duplicate_checker,
            ),
        )
        for capability, default_text, combo, plugin_id in capability_combos:
            combo.clear()
            combo.addItem(default_text, None)
            for record in self.config.plugin_manager.definitions_with(capability):
                definition = record.definition
                combo.addItem(
                    f"{definition.display_name} ({definition.version})",
                    record.plugin_id,
                )
            index = combo.findData(plugin_id) if plugin_id else 0
            if plugin_id and index < 0:
                combo.addItem(f"Missing: {plugin_id}", plugin_id)
                index = combo.count() - 1
            combo.setCurrentIndex(max(index, 0))

    @Slot(bool)
    def _set_selection_enabled(self, enabled: bool) -> None:
        for widget in self._selection_widgets:
            widget.setEnabled(enabled)

    def _load_plugin_status(self) -> None:
        self.plugin_status.clear()
        if not self.enable_plugins.isChecked():
            item = QTreeWidgetItem(("External plugins disabled", "", "", "Not loaded"))
            details = (
                "Plugin modules were not imported. Saved capability selections "
                "will be available again after plugins are enabled and NfoForge "
                "is restarted (you'll be prompted to restart automatically after "
                "applying this setting)."
            )
            for column in range(self.plugin_status.columnCount()):
                item.setToolTip(column, details)
            self.plugin_status.addTopLevelItem(item)
            return

        configured = self._configured_capabilities(self.config.settings.plugins)

        for record in self.config.plugin_manager.records:
            capabilities = self._record_capabilities(record)
            item = QTreeWidgetItem(
                (
                    record.definition.display_name,
                    record.definition.version,
                    ", ".join(capabilities),
                    "Loaded",
                )
            )
            details = f"ID: {record.plugin_id}\nSource: {record.source}"
            if record.definition.description:
                details += f"\n\n{record.definition.description}"
            for column in range(self.plugin_status.columnCount()):
                item.setToolTip(column, details)
            self.plugin_status.addTopLevelItem(item)

        for issue in self.config.plugin_manager.load_issues:
            item = QTreeWidgetItem((issue.source, "", "", f"Failed: {issue.reason}"))
            item.setForeground(3, QColor(Qt.GlobalColor.red))
            for column in range(self.plugin_status.columnCount()):
                item.setToolTip(column, issue.reason)
            self.plugin_status.addTopLevelItem(item)

        available = self.config.plugin_manager.plugin_ids
        for plugin_id, capabilities in configured.items():
            if plugin_id in available:
                continue
            item = QTreeWidgetItem(
                (
                    plugin_id,
                    "",
                    ", ".join(capabilities),
                    "Configured but unavailable",
                )
            )
            item.setForeground(3, QColor(Qt.GlobalColor.darkYellow))
            self.plugin_status.addTopLevelItem(item)

        if self.plugin_status.topLevelItemCount() == 0:
            self.plugin_status.addTopLevelItem(
                QTreeWidgetItem(("No external plugins detected", "", "", ""))
            )

    @staticmethod
    def _configured_capabilities(
        settings: PluginSettingsPayload,
    ) -> dict[str, list[str]]:
        configured: dict[str, list[str]] = {}
        for attribute, label in (
            ("wizard_page", "Wizard input"),
            ("token_replacer", "Token replacement"),
            ("pre_upload", "Pre-upload"),
            ("post_upload", "Post-upload"),
            ("metadata_transformer", "Metadata transformation"),
            ("image_host_uploader", "Image host uploader"),
            ("duplicate_checker", "Duplicate checker"),
        ):
            plugin_id = getattr(settings, attribute)
            if plugin_id:
                configured.setdefault(plugin_id, []).append(label)
        return configured

    @staticmethod
    def _record_capabilities(record: PluginRecord) -> tuple[str, ...]:
        definition = record.definition
        capabilities: list[str] = []
        for attribute, label in _CAPABILITY_LABELS.items():
            value = getattr(definition, attribute)
            if value:
                capabilities.append(label)
        return tuple(capabilities)

    @Slot()
    def _save_settings(self) -> None:
        self.config.settings.general.enable_plugins = self.enable_plugins.isChecked()
        self.config.settings.plugins.wizard_page = (
            self.plugin_wizard_page_combo.currentData()
        )
        self.config.settings.plugins.token_replacer = (
            self.plugin_token_replacer_combo.currentData()
        )
        self.config.settings.plugins.pre_upload = (
            self.plugin_pre_upload_combo.currentData()
        )
        self.config.settings.plugins.post_upload = (
            self.plugin_post_upload_combo.currentData()
        )
        self.config.settings.plugins.metadata_transformer = (
            self.plugin_metadata_transformer_combo.currentData()
        )
        self.config.settings.plugins.image_host_uploader = (
            self.plugin_image_host_uploader_combo.currentData()
        )
        self.config.settings.plugins.duplicate_checker = (
            self.plugin_duplicate_checker_combo.currentData()
        )
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.enable_plugins.setChecked(self.config.defaults.general.enable_plugins)
        self._load_plugin_combos(self.config.defaults.plugins)
        self._set_selection_enabled(self.enable_plugins.isChecked())
