from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
)

from src.config.config import ConfigManager
from src.config.models import PluginSettings as PluginSettingsPayload
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import build_h_line, create_form_layout
from src.plugins.api import PluginRecord

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


_CAPABILITY_LABELS = {
    "wizard_page": "Wizard input",
    "token_replacer": "Token replacement",
    "pre_upload": "Pre-upload",
    "metadata_transformer": "Metadata transformation",
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
            "Plugins are discovered at startup. Disabling plugins prevents their "
            "hooks and template contributions from running, but keeps selections "
            "and discovery information available.",
            self,
        )
        intro.setWordWrap(True)

        self.enable_plugins = QCheckBox("Enable External Plugins", self)
        self.enable_plugins.toggled.connect(self._set_selection_enabled)

        self.plugin_wizard_page_combo = self._create_combo()
        self.plugin_token_replacer_combo = self._create_combo()
        self.plugin_pre_upload_combo = self._create_combo()
        self.plugin_metadata_transformer_combo = self._create_combo()

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
                "Metadata Transformer",
                "Choose an optional plugin to transform completed TMDB metadata.",
                self.plugin_metadata_transformer_combo,
            ),
        )
        self._selection_widgets = tuple(combo for _, _, combo in selectors)

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
                "metadata_transformer",
                "TMDB Metadata",
                self.plugin_metadata_transformer_combo,
                selections.metadata_transformer,
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
            ("metadata_transformer", "Metadata transformation"),
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
        self.config.settings.plugins.metadata_transformer = (
            self.plugin_metadata_transformer_combo.currentData()
        )
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.enable_plugins.setChecked(self.config.defaults.general.enable_plugins)
        self._load_plugin_combos(self.config.defaults.plugins)
        self._set_selection_enabled(self.enable_plugins.isChecked())
