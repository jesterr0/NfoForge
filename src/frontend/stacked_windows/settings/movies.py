from functools import partial
from pathlib import Path

from PySide6.QtCore import Slot, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QWidget,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QCheckBox,
    QLineEdit,
)

from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.custom_widgets.tracker_format_override import TrackerFormatOverride
from src.frontend.custom_widgets.resizable_stacked_widget import ResizableStackedWidget
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import create_form_layout, build_h_line
from src.backend.tokens import Tokens, FileToken
from src.backend.token_replacer import TokenReplacer, ColonReplace, UnfilledTokenRemoval
from src.backend.utils.example_parsed_file_data import (
    EXAMPLE_MEDIAINFO_OBJ,
    EXAMPLE_FILE_NAME,
    EXAMPLE_SEARCH_PAYLOAD,
)


class MoviesSettings(BaseSettings):
    """Movie specific settings"""

    TRACKERS_OVERRIDE_NOT_SUPPORTED = (TrackerSelection.PASS_THE_POPCORN,)

    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("movieSettings")

        # hook up signals
        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        # controls
        # rename
        self.rename_check_box = QCheckBox("Rename Movies", self)
        self.rename_check_box.setToolTip(
            "Will use the existing file name if renaming is disabled"
        )

        # replace illegal chars
        self.replace_illegal_chars = QCheckBox("Replace Illegal Characters", self)
        self.replace_illegal_chars.setToolTip(
            "Replace illegal characters. If unchecked, NfoForge will remove them instead"
        )

        # layout
        self.controls_box = QGroupBox("Controls")
        self.controls_layout = QVBoxLayout(self.controls_box)
        self.controls_layout.addWidget(self.rename_check_box)
        self.controls_layout.addWidget(self.replace_illegal_chars)

        # format file name
        # colon replace for file name
        fn_colon_replace_lbl, self.fn_colon_replace = self._build_colon_replace_combo(
            "Colon Replacement", self
        )
        self.fn_colon_replace.currentIndexChanged.connect(
            self._update_file_token_example
        )

        # format file name
        format_file_name_lbl = QLabel("Token", self)
        format_file_name_lbl.setToolTip(
            "Select which tokens are used to generate the renamed file name"
        )
        self.format_file_name_token_input = QLineEdit(self)
        self.format_file_name_token_input.textChanged.connect(
            self._update_file_token_example
        )

        format_file_name_token_example_lbl = QLabel("Example", self)
        self.format_file_name_token_example = self._build_disabled_example_qline_edit(
            self
        )

        # layout
        filename_box_lbl = QLabel(
            """<span>Format <span style="font-weight: bold;">Filename</span> Token</span>""",
            self,
        )
        self.filename_box = QGroupBox()
        self.format_file_name_layout = self._build_token_layout(
            fn_colon_replace_lbl,
            self.fn_colon_replace,
            format_file_name_lbl,
            self.format_file_name_token_input,
            format_file_name_token_example_lbl,
            self.format_file_name_token_example,
        )
        self.filename_box.setLayout(self.format_file_name_layout)
        self.filename_nested_layout = self._build_nested_groupbox_layout(
            filename_box_lbl, self.filename_box
        )

        # format release title
        # colon replace for title
        title_colon_replace_lbl, self.title_colon_replace = (
            self._build_colon_replace_combo("Colon Replacement", self)
        )
        self.title_colon_replace.currentIndexChanged.connect(
            self._update_title_token_example
        )

        format_release_title_lbl = QLabel("Token", self)
        format_release_title_lbl.setToolTip(
            "Select which tokens are used to generate the renamed file name"
        )
        self.format_release_title_input = QLineEdit(self)
        self.format_release_title_input.textChanged.connect(
            self._update_title_token_example
        )

        format_release_title_example_lbl = QLabel("Example", self)
        self.format_release_title_example = self._build_disabled_example_qline_edit(
            self
        )

        title_box_lbl = QLabel(
            """<span>Format <span style="font-weight: bold;">Title</span> Token</span>""",
            self,
        )
        self.title_box = QGroupBox()
        self.format_release_title_layout = self._build_token_layout(
            title_colon_replace_lbl,
            self.title_colon_replace,
            format_release_title_lbl,
            self.format_release_title_input,
            format_release_title_example_lbl,
            self.format_release_title_example,
        )
        self.title_box.setLayout(self.format_release_title_layout)
        self.title_nested_layout = self._build_nested_groupbox_layout(
            title_box_lbl, self.title_box
        )

        # tracker overrides
        # tracker override selection
        tracker_lbl = QLabel("Tracker", self)
        self.tracker_selection = CustomComboBox(disable_mouse_wheel=True, parent=self)

        # tracker override map
        self.tracker_override_map: dict[TrackerSelection, TrackerFormatOverride] = {}
        self.tracker_over_ride_stacked_widget = ResizableStackedWidget(self)
        for tracker in self.config.tracker_map.keys():
            if tracker in self.TRACKERS_OVERRIDE_NOT_SUPPORTED:
                continue
            tracker_format_override = TrackerFormatOverride(self)
            tracker_format_override.setting_changed.connect(
                partial(self._update_tracker_override_example, tracker_format_override)
            )
            self.tracker_selection.addItem(str(tracker), tracker)
            self.tracker_over_ride_stacked_widget.addWidget(tracker_format_override)
            self.tracker_override_map[tracker] = tracker_format_override

        # connect to signal to swap stacked widget
        self.tracker_selection.currentIndexChanged.connect(
            self._change_over_ride_tracker
        )

        self.over_ride_box = QGroupBox("Format Title Tracker Overrides")
        self.over_ride_inner_layout = QVBoxLayout(self.over_ride_box)
        self.over_ride_inner_layout.addWidget(tracker_lbl)
        self.over_ride_inner_layout.addWidget(self.tracker_selection)
        self.over_ride_inner_layout.addWidget(build_h_line((6, 1, 6, 1)))
        self.over_ride_inner_layout.addWidget(self.tracker_over_ride_stacked_widget)

        # token table
        self.token_table = TokenTable(
            sorted(Tokens().get_token_objects(FileToken)), allow_edits=True, parent=self
        )
        self.token_table.main_layout.setContentsMargins(0, 0, 0, 0)

        self.token_table_box = QGroupBox("Tokens")
        self.token_table_layout = QVBoxLayout(self.token_table_box)
        self.token_table_layout.addWidget(self.token_table)

        # final layout
        self.add_widget(self.controls_box)
        self.add_layout(self.filename_nested_layout)
        self.add_layout(self.title_nested_layout)
        self.add_widget(self.over_ride_box)
        self.add_widget(self.token_table_box)
        self.add_layout(self.reset_layout)

        self._load_saved_settings()

    @Slot()
    def _update_file_token_example(self) -> None:
        self._update_example(
            token_str=self.format_file_name_token_input.text(),
            colon_replace=ColonReplace(self.title_colon_replace.currentData()),
            file_name_mode=True,
            qline=self.format_file_name_token_example,
        )

    @Slot()
    def _update_title_token_example(self) -> None:
        txt_data = self._update_example(
            token_str=self.format_release_title_input.text(),
            colon_replace=ColonReplace(self.title_colon_replace.currentData()),
            file_name_mode=False,
            qline=self.format_release_title_example,
        )

        # if override widget is enabled we'll update the title portion of it's widget if
        # there is no token for that widget
        override_widget: TrackerFormatOverride = (
            self.tracker_over_ride_stacked_widget.currentWidget()
        )  # pyright: ignore [reportAssignmentType]
        if (
            override_widget.enabled_checkbox.isChecked()
            and not override_widget.over_ride_format_title.text()
        ):
            override_widget.over_ride_format_file_name_token_example.setText(txt_data)

    def _update_example(
        self,
        token_str: str,
        colon_replace: ColonReplace,
        file_name_mode: bool,
        qline: QLineEdit,
        override_title_rules: list[tuple[str, str]] | None = None,
    ) -> str:
        format_str = TokenReplacer(
            media_input=Path(EXAMPLE_FILE_NAME),
            jinja_engine=None,
            source_file=None,
            token_string=token_str,
            colon_replace=colon_replace,
            media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
            media_info_obj=EXAMPLE_MEDIAINFO_OBJ,
            flatten=True,
            file_name_mode=file_name_mode,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            releasers_name=self.config.cfg_payload.releasers_name,
            movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
            override_title_rules=override_title_rules,
        )
        example_txt = qline.text()
        output = format_str.get_output()
        if output:
            example_txt = output
        self._update_qline_cursor_0(qline, example_txt)
        return example_txt

    def _update_all_examples(self) -> None:
        self._update_file_token_example()
        self._update_title_token_example()

    @Slot(int)
    def _change_over_ride_tracker(self, idx: int) -> None:
        curr_tracker = self.tracker_selection.itemData(idx)
        if curr_tracker:
            tracker_override_widget = self.tracker_override_map[curr_tracker]
            self.tracker_over_ride_stacked_widget.setCurrentWidget(
                tracker_override_widget
            )
            self._update_tracker_override_example(tracker_override_widget)

    @Slot(TrackerFormatOverride)
    def _update_tracker_override_example(
        self, tracker_format_override: TrackerFormatOverride
    ) -> None:
        token_str = tracker_format_override.over_ride_format_title.text()
        qline = tracker_format_override.over_ride_format_file_name_token_example
        colon_replace = ColonReplace(
            tracker_format_override.title_colon_replace.currentData()
        )
        over_ride_rules = (
            tracker_format_override.over_ride_replacement_table.get_replacements()
        )
        self._update_example(
            token_str=token_str
            if token_str
            else self.format_release_title_input.text(),
            colon_replace=colon_replace,
            file_name_mode=False,
            qline=qline,
            override_title_rules=over_ride_rules,
        )

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        # temporarily block signals until data is loaded
        self.format_file_name_token_input.blockSignals(True)
        self.fn_colon_replace.blockSignals(True)
        self.format_release_title_input.blockSignals(True)
        self.title_colon_replace.blockSignals(True)
        for over_ride_widget in self.tracker_override_map.values():
            over_ride_widget.blockSignals(True)

        # load settings
        self.rename_check_box.setChecked(self.config.cfg_payload.mvr_enabled)
        self.replace_illegal_chars.setChecked(
            self.config.cfg_payload.mvr_replace_illegal_chars
        )
        self.load_combo_box(
            self.fn_colon_replace,
            ColonReplace,
            self.config.cfg_payload.mvr_colon_replace_filename,
        )
        self.load_combo_box(
            self.title_colon_replace,
            ColonReplace,
            self.config.cfg_payload.mvr_colon_replace_title,
        )
        if self.config.cfg_payload.mvr_token.strip():
            self._update_qline_cursor_0(
                self.format_file_name_token_input,
                self.config.cfg_payload.mvr_default_token,
            )
        if self.config.cfg_payload.mvr_title_token.strip():
            self._update_qline_cursor_0(
                self.format_release_title_input,
                self.config.cfg_payload.mvr_title_token,
            )
        # load saved tracker overrides
        for idx, tracker in enumerate(self.tracker_override_map.keys()):
            tracker_info = self.config.tracker_map[tracker]
            over_ride_widget = self.tracker_override_map[tracker]
            over_ride_widget.enabled_checkbox.setChecked(
                tracker_info.mvr_title_override_enabled
            )
            over_ride_widget.set_colon_replace(
                str(tracker_info.mvr_title_colon_replace)
            )
            self._update_qline_cursor_0(
                over_ride_widget.over_ride_format_title,
                tracker_info.mvr_title_token_override,
            )
            over_ride_widget.over_ride_replacement_table.set_default_rules(
                getattr(tracker_info, "mvr_default_title_replace_map", [])
            )
            over_ride_widget.over_ride_replacement_table.reset()
            if tracker_info.mvr_title_replace_map:
                over_ride_widget.over_ride_replacement_table.add_rows(
                    tracker_info.mvr_title_replace_map
                )
            # we only want to pay the cost of running the token engine on the currently visible tracker
            # override the others will be updated as they are clicked through
            if idx == 0:
                self._update_tracker_override_example(over_ride_widget)
        self.token_table.load_replacement_rules(
            self.config.cfg_payload.mvr_clean_title_rules
        )
        self._mvr_default_update_check()

        # unblock signals
        self.format_file_name_token_input.blockSignals(False)
        self.fn_colon_replace.blockSignals(False)
        self.format_release_title_input.blockSignals(False)
        self.title_colon_replace.blockSignals(False)
        self._update_all_examples()
        QTimer.singleShot(1, self._delayed_unblock_override_widgets)

    def _delayed_unblock_override_widgets(self):
        """
        This prevents un-needed calls that are slightly 'expensive' that can happen when
        loading data into the override UI elements.
        """
        for over_ride_widget in self.tracker_override_map.values():
            over_ride_widget.blockSignals(False)

    @Slot()
    def _save_settings(self) -> None:
        self.config.cfg_payload.mvr_enabled = self.rename_check_box.isChecked()
        self.config.cfg_payload.mvr_replace_illegal_chars = (
            self.replace_illegal_chars.isChecked()
        )
        self.config.cfg_payload.mvr_colon_replace_filename = ColonReplace(
            self.fn_colon_replace.currentData()
        )
        self.config.cfg_payload.mvr_colon_replace_title = ColonReplace(
            self.title_colon_replace.currentData()
        )
        self.config.cfg_payload.mvr_token = self.format_file_name_token_input.text()
        self.config.cfg_payload.mvr_title_token = self.format_release_title_input.text()
        # save tracker overrides
        for tracker in self.tracker_override_map.keys():
            over_ride_widget = self.tracker_override_map[tracker]
            self.config.tracker_map[
                tracker
            ].mvr_title_override_enabled = over_ride_widget.enabled_checkbox.isChecked()
            self.config.tracker_map[
                tracker
            ].mvr_title_colon_replace = (
                over_ride_widget.title_colon_replace.currentData()
            )
            self.config.tracker_map[
                tracker
            ].mvr_title_token_override = over_ride_widget.over_ride_format_title.text()
            self.config.tracker_map[
                tracker
            ].mvr_title_replace_map = (
                over_ride_widget.over_ride_replacement_table.get_replacements()
            )
        self._mvr_clean_title_rules_change()
        self.updated_settings_applied.emit()

    def _mvr_default_update_check(self) -> None:
        """
        Checks to see if defaults have been changed on the program level and updates users config if their
        config was not modified before.
        """
        if not self.config.cfg_payload.mvr_clean_title_rules_modified:
            replacements = self.token_table.replacement_list_widget.replacement_list_widget.get_replacements()
            defaults = self.token_table.replacement_list_widget.default_rules
            if not defaults:
                raise ValueError(
                    "Cannot detect 'replacement_list_widget' default rules"
                )
            if set(replacements) != set(defaults):
                self.config.cfg_payload.mvr_clean_title_rules = defaults
                self.token_table.reset()
                self.config.save_config()

    def _mvr_clean_title_rules_change(self) -> None:
        replacements = self.token_table.replacement_list_widget.replacement_list_widget.get_replacements()
        defaults = self.token_table.replacement_list_widget.default_rules
        if not defaults:
            raise ValueError("Cannot detect 'replacement_list_widget' default rules")
        if not self.config.cfg_payload.mvr_clean_title_rules_modified:
            self.config.cfg_payload.mvr_clean_title_rules = defaults
        else:
            self.config.cfg_payload.mvr_clean_title_rules = replacements

        if set(replacements) != set(defaults):
            self.config.cfg_payload.mvr_clean_title_rules_modified = True
        else:
            self.config.cfg_payload.mvr_clean_title_rules_modified = False

    def apply_defaults(self) -> None:
        self.rename_check_box.setChecked(True)
        self.replace_illegal_chars.setChecked(True)
        self.fn_colon_replace.setCurrentIndex(2)
        self.format_file_name_token_input.setText(
            self.config.cfg_payload.mvr_default_token
        )
        self.title_colon_replace.setCurrentIndex(2)
        self.format_release_title_input.setText(
            self.config.cfg_payload.mvr_default_token
        )
        self._apply_override_defaults()
        self.token_table.reset()
        self.config.cfg_payload.mvr_clean_title_rules_modified = False

    def _apply_override_defaults(self) -> None:
        """
        Reset tracker over ride, using getattr due to the dynamic nature of some trackers having
        defaults and others not having defaults.
        """
        for tracker in self.tracker_override_map.keys():
            over_ride_widget = self.tracker_override_map[tracker]
            tracker_info = self.config.tracker_map[tracker]
            over_ride_widget.enabled_checkbox.setChecked(
                bool(getattr(tracker_info, "mvr_default_title_override_enabled", False))
            )
            over_ride_widget.title_colon_replace.setCurrentIndex(2)
            self._update_qline_cursor_0(
                over_ride_widget.over_ride_format_title,
                str(getattr(tracker_info, "mvr_default_title_token_override", "")),
            )
            over_ride_widget.over_ride_replacement_table.reset()
            over_ride_widget.over_ride_replacement_table.add_rows(
                getattr(tracker_info, "mvr_default_title_replace_map", [])
            )

    @staticmethod
    def _build_colon_replace_combo(
        lbl_txt: str,
        parent: QWidget,
    ) -> tuple[QLabel, CustomComboBox]:
        colon_replacement_lbl = QLabel(lbl_txt, parent)
        colon_replacement_lbl.setToolTip(
            "Select how NfoForge handles colon replacement"
        )
        colon_replacement_combo = CustomComboBox(
            disable_mouse_wheel=True, parent=parent
        )
        colon_replacement_combo.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        for colon_enum in ColonReplace:
            colon_replacement_combo.addItem(str(colon_enum), colon_enum.value)
        return colon_replacement_lbl, colon_replacement_combo

    @staticmethod
    def _build_token_layout(
        colon_replace_lbl: QLabel,
        colon_replace: QComboBox,
        widget_1: QWidget,
        widget_2: QWidget,
        widget_t1: QWidget,
        widget_t2: QWidget,
        margins: tuple[int, int, int, int] | None = None,
    ) -> QVBoxLayout:
        """margins (tuple[int, int, int, int] | None, optional): Left, top, right, bottom"""
        layout = QVBoxLayout()
        if margins:
            layout.setContentsMargins(*margins)
        layout.addWidget(colon_replace_lbl)
        layout.addWidget(colon_replace)
        layout.addWidget(widget_1)
        layout.addWidget(widget_2)
        layout.addLayout(create_form_layout(widget_t1, widget_t2))
        return layout

    @staticmethod
    def _build_disabled_example_qline_edit(parent=None) -> QLineEdit:
        """Builds a disabled qline edit and returns it"""
        line_edit = QLineEdit(parent)
        line_edit.setDisabled(True)
        return line_edit

    @staticmethod
    def _update_qline_cursor_0(widget: QLineEdit, txt: str) -> None:
        widget.setText(txt)
        widget.setCursorPosition(0)
        widget.setToolTip(txt)

    @staticmethod
    def _build_nested_groupbox_layout(widget1: QWidget, box: QGroupBox) -> QVBoxLayout:
        """Builds a nested layout for the group box and another widget to be very close"""
        nested_layout = QVBoxLayout()
        nested_layout.setContentsMargins(0, 0, 0, 0)
        nested_layout.setSpacing(0)
        nested_layout.addWidget(widget1)
        nested_layout.addWidget(box)
        return nested_layout
