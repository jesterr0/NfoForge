from collections.abc import Sequence
from functools import partial
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QSize, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, Tokens, TokenSelection, TokenType
from src.backend.trackers.media_support import (
    NO_RELEASE_NAME_FIELD,
    UNSUPPORTED_MOVIE_TRACKERS,
)
from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_FILE_NAME,
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_MEDIAINFO_OUTPUT_STR,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.config.config import ConfigManager
from src.config.models import DynamicRangeSettings, DynamicRangeSettingsData
from src.enums.token_replacer import ColonReplace, UnfilledTokenRemoval
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.resizable_stacked_widget import ResizableStackedWidget
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.custom_widgets.tracker_format_override import TrackerFormatOverride
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import build_h_line, set_top_parent_geometry
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


class MoviesManagementSettings(BaseSettings):
    """Movie specific settings"""

    def __init__(
        self, config: ConfigManager, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("movieManagementSettings")

        # hook up signals
        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)
        GSigs().token_state_changed.connect(self._token_state_changed)
        GSigs().global_management_state_changed.connect(
            self._global_management_state_changed
        )

        # live state cache for real-time updates
        self._live_title_clean_rules: list[tuple[str, str]] | None = None
        self._live_video_dynamic_range: DynamicRangeSettings | None = None

        # controls
        # rename
        self.rename_check_box = QCheckBox("Rename Movies", self)
        self.rename_check_box.setToolTip(
            "Will use the existing file name if renaming is disabled"
        )

        preview_example_data_btn = QToolButton(self)
        QTAThemeSwap().register(
            preview_example_data_btn, "ph.eye-light", icon_size=QSize(20, 20)
        )
        preview_example_data_btn.setToolTip("Preview example filename and MediaInfo")
        preview_example_data_btn.clicked.connect(self._show_example_input_data)

        control_top_layout = QHBoxLayout()
        control_top_layout.setContentsMargins(0, 0, 0, 0)
        control_top_layout.addWidget(self.rename_check_box)
        control_top_layout.addStretch()
        control_top_layout.addWidget(preview_example_data_btn)

        # layout
        self.controls_box = QGroupBox("Controls")
        self.controls_layout = QVBoxLayout(self.controls_box)
        self.controls_layout.addLayout(control_top_layout)

        # format file name
        # colon replace for file name
        fn_colon_replace_lbl, self.fn_colon_replace = self._build_colon_replace_combo(
            "Colon Replacement", self
        )
        self.fn_colon_replace.currentIndexChanged.connect(
            self._update_file_token_example
        )

        # parse from input filename
        self.parse_input_file_attributes = QCheckBox("Parse Filename Attributes", self)
        self.parse_input_file_attributes.setToolTip(
            "If enabled, attributes REMUX, HYBRID, PROPER, and REPACK will be detected from the filename"
        )
        self.parse_input_file_attributes.clicked.connect(
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
        self.format_file_name_token_example = QLineEdit(
            parent=parent, readOnly=True, frame=False
        )

        # layout
        filename_box_lbl = QLabel(
            """<span>Format <span style="font-weight: bold;">Filename</span> Tokens</span>""",
            self,
        )
        self.filename_box = QGroupBox()

        filename_example_section = self._build_indented_example_section(
            format_file_name_token_example_lbl, self.format_file_name_token_example
        )

        self.format_file_name_layout = self._build_token_layout(
            fn_colon_replace_lbl,
            self.fn_colon_replace,
            format_file_name_lbl,
            self.format_file_name_token_input,
            filename_example_section,
            header_widgets=(self.parse_input_file_attributes,),
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

        format_release_title_example_layout_lbl = QLabel("Example", self)
        self.format_release_title_example = QLineEdit(
            parent=parent, readOnly=True, frame=False
        )

        title_box_lbl = QLabel(
            """<span>Format <span style="font-weight: bold;">Title</span> Tokens</span>""",
            self,
        )
        self.title_box = QGroupBox()

        title_example_section = self._build_indented_example_section(
            format_release_title_example_layout_lbl, self.format_release_title_example
        )

        self.format_release_title_layout = self._build_token_layout(
            title_colon_replace_lbl,
            self.title_colon_replace,
            format_release_title_lbl,
            self.format_release_title_input,
            title_example_section,
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
        for tracker in self.config.settings.trackers.by_selection().keys():
            if (
                tracker in UNSUPPORTED_MOVIE_TRACKERS
                or tracker in NO_RELEASE_NAME_FIELD
            ):
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
            self._get_file_tokens(), allow_edits=False, parent=self
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
        self.add_layout(self.reset_layout, add_stretch=True)

        self._load_saved_settings()

    @Slot()
    def _update_file_token_example(self) -> None:
        self._update_example(
            token_str=self.format_file_name_token_input.text(),
            colon_replace=ColonReplace(self.fn_colon_replace.currentData()),
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
        override_widget = cast(
            TrackerFormatOverride,
            self.tracker_over_ride_stacked_widget.currentWidget(),
        )
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
        user_tokens = {
            k: v
            for k, (v, ts) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(ts) is TokenSelection.FILE_TOKEN
        }
        format_str = TokenReplacer(
            media_input_obj=EXAMPLE_MEDIA_INPUT_PAYLOAD,
            token_string=token_str,
            jinja_engine=None,
            colon_replace=colon_replace,
            media_search_obj=EXAMPLE_SEARCH_PAYLOAD,
            flatten=True,
            file_name_mode=file_name_mode,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            releasers_name=self.config.settings.general.releasers_name,
            title_clean_rules=self._get_live_title_clean_rules(),
            video_dynamic_range=self._get_live_video_dynamic_range(),
            override_title_rules=override_title_rules,
            user_tokens=user_tokens,
            parse_filename_attributes=self.parse_input_file_attributes.isChecked(),
            flat_filters=self.config.plugin_manager.flat_filters(
                enabled=self.config.settings.general.enable_plugins
            ),
            custom_edition_info=self.config.plugin_manager.custom_edition_info(
                enabled=self.config.settings.general.enable_plugins
            ),
            custom_cut_names=self.config.plugin_manager.custom_cut_names(
                enabled=self.config.settings.general.enable_plugins
            ),
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
        qline = tracker_format_override.over_ride_format_file_name_token_example
        enabled = tracker_format_override.enabled_checkbox.isChecked()
        token_str = (
            tracker_format_override.over_ride_format_title.text() if enabled else ""
        )
        colon_replace = (
            ColonReplace(tracker_format_override.title_colon_replace.currentData())
            if enabled
            else ColonReplace(self.title_colon_replace.currentData())
        )
        over_ride_rules = (
            tracker_format_override.over_ride_replacement_table.get_replacements()
            if enabled
            else None
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
        # initialize live cache with current config values
        self._live_title_clean_rules = None
        self._live_video_dynamic_range = None

        self.rename_check_box.setChecked(self.config.settings.movie.enabled)
        self.load_combo_box(
            self.fn_colon_replace,
            ColonReplace,
            self.config.settings.movie.filename_colon_replace,
        )
        self.load_combo_box(
            self.title_colon_replace,
            ColonReplace,
            self.config.settings.movie.title_colon_replace,
        )
        self.parse_input_file_attributes.setChecked(
            self.config.settings.movie.claims.enabled
        )
        if self.config.settings.movie.filename_token.strip():
            self._update_qline_cursor_0(
                self.format_file_name_token_input,
                self.config.settings.movie.filename_token,
            )
        if self.config.settings.movie.title_token.strip():
            self._update_qline_cursor_0(
                self.format_release_title_input,
                self.config.settings.movie.title_token,
            )
        # load saved tracker overrides
        for idx, tracker in enumerate(self.tracker_override_map.keys()):
            over_ride_widget = self.tracker_override_map[tracker]
            default_info = self.config.defaults.trackers.by_selection()[tracker]
            tracker_info = self.config.settings.trackers.by_selection()[tracker]
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
                default_info.mvr_title_replace_map
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

        # unblock signals
        self.format_file_name_token_input.blockSignals(False)
        self.fn_colon_replace.blockSignals(False)
        self.format_release_title_input.blockSignals(False)
        self.title_colon_replace.blockSignals(False)
        self._update_all_examples()
        QTimer.singleShot(1, self._delayed_unblock_override_widgets)

    def _delayed_unblock_override_widgets(self) -> None:
        """
        This prevents un-needed calls that are slightly 'expensive' that can happen when
        loading data into the override UI elements.
        """
        for over_ride_widget in self.tracker_override_map.values():
            over_ride_widget.blockSignals(False)

    @Slot()
    def _save_settings(self) -> None:
        self.config.settings.movie.enabled = self.rename_check_box.isChecked()
        self.config.settings.movie.filename_colon_replace = ColonReplace(
            self.fn_colon_replace.currentData()
        )
        self.config.settings.movie.claims.enabled = (
            self.parse_input_file_attributes.isChecked()
        )
        self.config.settings.movie.title_colon_replace = ColonReplace(
            self.title_colon_replace.currentData()
        )
        self.config.settings.movie.filename_token = (
            self.format_file_name_token_input.text()
        )
        self.config.settings.movie.title_token = self.format_release_title_input.text()
        # save tracker overrides
        for tracker in self.tracker_override_map.keys():
            over_ride_widget = self.tracker_override_map[tracker]
            self.config.settings.trackers.by_selection()[
                tracker
            ].mvr_title_override_enabled = over_ride_widget.enabled_checkbox.isChecked()
            self.config.settings.trackers.by_selection()[
                tracker
            ].mvr_title_colon_replace = (
                over_ride_widget.title_colon_replace.currentData()
            )
            self.config.settings.trackers.by_selection()[
                tracker
            ].mvr_title_token_override = over_ride_widget.over_ride_format_title.text()
            self.config.settings.trackers.by_selection()[
                tracker
            ].mvr_title_replace_map = (
                over_ride_widget.over_ride_replacement_table.get_replacements()
            )
        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.rename_check_box.setChecked(self.config.defaults.movie.enabled)
        self.fn_colon_replace.setCurrentIndex(
            self.config.defaults.movie.filename_colon_replace.value - 1
        )
        self.parse_input_file_attributes.setChecked(
            self.config.defaults.movie.claims.enabled
        )
        self.format_file_name_token_input.setText(
            self.config.defaults.movie.filename_token
        )
        self.title_colon_replace.setCurrentIndex(
            self.config.defaults.movie.title_colon_replace.value - 1
        )
        self.format_release_title_input.setText(self.config.defaults.movie.title_token)
        self._apply_override_defaults()
        self.token_table.reset()

    def _apply_override_defaults(self) -> None:
        for tracker in self.tracker_override_map.keys():
            over_ride_widget = self.tracker_override_map[tracker]
            tracker_info = self.config.defaults.trackers.by_selection()[tracker]
            over_ride_widget.enabled_checkbox.setChecked(
                tracker_info.mvr_title_override_enabled
            )
            over_ride_widget.title_colon_replace.setCurrentIndex(2)
            self._update_qline_cursor_0(
                over_ride_widget.over_ride_format_title,
                tracker_info.mvr_title_token_override,
            )
            over_ride_widget.over_ride_replacement_table.reset()
            if tracker_info.mvr_title_replace_map:
                over_ride_widget.over_ride_replacement_table.add_rows(
                    tracker_info.mvr_title_replace_map
                )

    @Slot()
    def _show_example_input_data(self) -> None:
        window = QDialog(self)
        set_top_parent_geometry(window)

        example_fn = QLineEdit(window, readOnly=True, text=str(EXAMPLE_FILE_NAME))

        example_mi = CodeEditor(
            line_numbers=False, wrap_text=False, mono_font=True, parent=window
        )
        example_mi.setReadOnly(True)
        example_mi.setPlainText(EXAMPLE_MEDIAINFO_OUTPUT_STR)

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel('<span style="font-weight: bold;">Example Filename:</span>', window)
        )
        layout.addWidget(example_fn)
        layout.addWidget(
            QLabel('<span style="font-weight: bold;">Example MediaInfo:</span>', window)
        )
        layout.addWidget(example_mi)

        window.setLayout(layout)
        window.exec()

    def _build_indented_example_section(
        self, example_layout: QWidget, example_input: QWidget
    ) -> QWidget:
        """Create an indented section for example layout and input"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 0, 0, 0)
        container_layout.setSpacing(4)
        container_layout.addWidget(example_layout)
        container_layout.addWidget(example_input)
        return container

    @Slot()
    def _token_state_changed(self) -> None:
        self.token_table.populate_table(self._get_file_tokens(), False)
        self._update_file_token_example()

    @Slot(object)
    def _global_management_state_changed(self, data: dict[str, object]) -> None:
        """Handle real-time updates from global management settings"""
        title_clean_rules = data.get("title_clean_rules")
        if isinstance(title_clean_rules, list):
            self._live_title_clean_rules = cast(
                list[tuple[str, str]], title_clean_rules
            )
        video_dynamic_range = data.get("video_dynamic_range")
        if isinstance(video_dynamic_range, dict):
            self._live_video_dynamic_range = DynamicRangeSettings(
                **cast(DynamicRangeSettingsData, video_dynamic_range)
            )
        self._update_all_examples()

    def _get_file_tokens(self) -> list[TokenType]:
        user_tokens = [
            TokenType(f"{{{k}}}", "User Token")
            for k, (_, t) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        ]
        return sorted(Tokens().get_token_objects(FileToken)) + user_tokens

    def _get_live_title_clean_rules(self) -> list[tuple[str, str]]:
        """Get live title clean rules (from cache if available, otherwise from config)"""
        return (
            self._live_title_clean_rules
            if self._live_title_clean_rules is not None
            else self.config.settings.global_management.title_clean_rules
        )

    def _get_live_video_dynamic_range(self) -> DynamicRangeSettings:
        """Get live video dynamic range (from cache if available, otherwise from config)"""
        return (
            self._live_video_dynamic_range
            if self._live_video_dynamic_range is not None
            else self.config.settings.global_management.video_dynamic_range
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
        for colon_enum in ColonReplace:
            colon_replacement_combo.addItem(str(colon_enum), colon_enum.value)
        return colon_replacement_lbl, colon_replacement_combo

    @staticmethod
    def _build_token_layout(
        colon_replace_lbl: QLabel,
        colon_replace: QComboBox,
        widget_1: QWidget,
        widget_2: QWidget,
        example_section: QWidget,
        header_widgets: Sequence[QWidget] | None = None,
        footer_widgets: Sequence[QWidget] | None = None,
        margins: tuple[int, int, int, int] | None = None,
    ) -> QVBoxLayout:
        """margins (tuple[int, int, int, int] | None, optional): Left, top, right, bottom"""
        layout = QVBoxLayout()
        if margins:
            layout.setContentsMargins(*margins)
        if header_widgets:
            for hw in header_widgets:
                layout.addWidget(hw)
        layout.addWidget(colon_replace_lbl)
        layout.addWidget(colon_replace, stretch=1)
        layout.addWidget(build_h_line((6, 1, 6, 1)))
        layout.addWidget(widget_1)
        layout.addWidget(widget_2)
        layout.addWidget(example_section)
        if footer_widgets:
            for fw in footer_widgets:
                layout.addWidget(fw)
        return layout

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
