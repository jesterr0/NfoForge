from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings


# TODO: series and movie management (NOW JUST SERIES) tabs need to update their example tokens 
# on some of these changes, like clean title etc.


class GlobalManagementSettings(BaseSettings):
    """Movie and Series global settings"""

    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("globalManagementSettings")

        # hook up signals
        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        # token table
        self.token_table = TokenTable(show_tokens=False, allow_edits=True, parent=self)
        self.token_table.main_layout.setContentsMargins(0, 0, 0, 0)
        self.title_clean_rules_modified = False
        
        # Connect to debounced signals from TokenTable
        self.token_table.replacement_rules_changed.connect(
            self._title_clean_rules_user_change
        )
        self.token_table.video_dynamic_range_changed.connect(
            self._video_dynamic_range_update_live_cfg
        )
        # Still need the defaults applied signal for immediate response
        self.token_table.replacement_list_widget.defaults_applied.connect(
            self._title_clean_rules_defaults_applied
        )

        self.token_table_box = QGroupBox("Tokens")
        self.token_table_layout = QVBoxLayout(self.token_table_box)
        self.token_table_layout.addWidget(self.token_table)

        # final layout
        self.add_widget(self.token_table_box)
        self.add_layout(self.reset_layout, add_stretch=True)

        self._load_saved_settings()

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        # temporarily block signals until data is loaded
        self.token_table.replacement_list_widget.blockSignals(True)

        # load settings
        self.title_clean_rules_modified = (
            self.config.cfg_payload.title_clean_rules_modified
        )
        self.token_table.load_replacement_rules(
            self.config.cfg_payload.title_clean_rules
        )
        self.token_table.video_dynamic_range.from_dict(
            self.config.cfg_payload.video_dynamic_range
        )
        self._default_title_clean_update_check()

        # unblock signals
        self.token_table.replacement_list_widget.blockSignals(False)

    @Slot(list)
    def _title_clean_rules_user_change(self, data: list) -> None:
        self.title_clean_rules_modified = True
        # emit signal with live data for real-time updates
        GSigs().global_management_state_changed.emit({
            'title_clean_rules': data
        })

    @Slot()
    def _title_clean_rules_defaults_applied(self) -> None:
        self.title_clean_rules_modified = False
        # Emit signal with default rules for real-time updates
        defaults = self.token_table.replacement_list_widget.default_rules
        if defaults:
            GSigs().global_management_state_changed.emit({
                'title_clean_rules': defaults
            })

    @Slot(object)
    def _video_dynamic_range_update_live_cfg(self, data: dict) -> None:
        if data:
            self.config.cfg_payload.video_dynamic_range = data
            # Emit signal for real-time updates
            GSigs().global_management_state_changed.emit({
                'video_dynamic_range': data
            })

    @Slot()
    def _save_settings(self) -> None:
        self.config.cfg_payload.title_clean_rules_modified = (
            self.title_clean_rules_modified
        )
        self._clean_title_rules_save()
        self.config.cfg_payload.video_dynamic_range = (
            self.token_table.video_dynamic_range.to_dict()
        )
        self.updated_settings_applied.emit()

    def _default_title_clean_update_check(self) -> None:
        """
        Checks to see if defaults have been changed on the program level and updates users config if their
        config was not modified before.
        """
        if not self.config.cfg_payload.title_clean_rules_modified:
            replacements = self.token_table.replacement_list_widget.replacement_list_widget.get_replacements()
            defaults = self.token_table.replacement_list_widget.default_rules
            if not defaults:
                raise ValueError(
                    "Cannot detect 'replacement_list_widget' default rules"
                )
            if set(replacements) != set(defaults):
                self.config.cfg_payload.title_clean_rules = defaults
                self.token_table.reset()
                self.config.save_config()

    def _clean_title_rules_save(self) -> None:
        replacements = self.token_table.replacement_list_widget.replacement_list_widget.get_replacements()
        defaults = self.token_table.replacement_list_widget.default_rules
        if not defaults:
            raise ValueError("Cannot detect 'replacement_list_widget' default rules")
        if not self.config.cfg_payload.title_clean_rules_modified:
            self.config.cfg_payload.title_clean_rules = defaults
        else:
            self.config.cfg_payload.title_clean_rules = replacements

        if set(replacements) != set(defaults):
            self.config.cfg_payload.title_clean_rules_modified = True
        else:
            self.config.cfg_payload.title_clean_rules_modified = False

    def apply_defaults(self) -> None:
        self.token_table.reset()
        self.config.cfg_payload.title_clean_rules_modified = (
            self.config.cfg_payload_defaults.title_clean_rules_modified
        )
        self.token_table.video_dynamic_range.from_dict(
            self.config.cfg_payload_defaults.video_dynamic_range
        )
        self.title_clean_rules_modified = False

    @staticmethod
    def _build_nested_groupbox_layout(widget1: QWidget, box: QGroupBox) -> QVBoxLayout:
        """Builds a nested layout for the group box and another widget to be very close"""
        nested_layout = QVBoxLayout()
        nested_layout.setContentsMargins(0, 0, 0, 0)
        nested_layout.setSpacing(0)
        nested_layout.addWidget(widget1)
        nested_layout.addWidget(box)
        return nested_layout
