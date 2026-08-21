from collections.abc import Sequence
from typing import TYPE_CHECKING, TypedDict, cast

from PySide6.QtCore import QSize, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import FileToken, Tokens, TokenSelection, TokenType
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_FILE_NAME_1,
    EXAMPLE_MEDIA_INPUT_PAYLOAD,
    EXAMPLE_MEDIAINFO_OUTPUT_STR,
    EXAMPLE_SEARCH_PAYLOAD,
)
from src.backend.utils.filename_claims import (
    FilenameClaims,
    detect_filename_claims,
)
from src.config.config import ConfigManager
from src.config.models import DynamicRangeSettings, DynamicRangeSettingsData
from src.config.tv_tokens import (
    SUPPORTED_TVR_FORMATS,
    get_tvr_episode_token,
    get_tvr_title_token,
    resolve_season_subfolder_token,
    set_tvr_episode_token,
    set_tvr_title_token,
)
from src.enums.multi_episode_style import MultiEpisodeStyle
from src.enums.series import EpisodeFormat
from src.enums.token_replacer import (
    FILENAME_COLON_OPTIONS,
    ColonReplace,
    UnfilledTokenRemoval,
)
from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import set_top_parent_geometry
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


class FormatWidgets(TypedDict):
    file_token: QLineEdit
    title_token: QLineEdit
    file_example: QLineEdit
    title_example: QLineEdit


class SeriesManagementSettings(BaseSettings):
    """Series specific settings"""

    _FORMAT_ORDER = SUPPORTED_TVR_FORMATS

    def __init__(
        self, config: ConfigManager, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("seriesManagementSettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)
        GSigs().token_state_changed.connect(self._token_state_changed)
        GSigs().global_management_state_changed.connect(
            self._global_management_state_changed
        )

        self._live_title_clean_rules: list[tuple[str, str]] | None = None
        self._live_video_dynamic_range: DynamicRangeSettings | None = None

        #### global controls ####
        self.rename_check_box = QCheckBox("Rename Series", self)
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

        # claims read out of the input filename
        self.claims_master = self._build_claims_master(self)
        self.claims_master.toggled.connect(self._on_claims_master_toggled)
        self.claims_master.clicked.connect(self._update_current_tab_file_example)
        self.claim_checks = self._build_claim_checks(self)
        for claim_check in self.claim_checks.values():
            claim_check.clicked.connect(self._update_current_tab_file_example)

        fn_colon_replace_lbl, self.fn_colon_replace = self._build_colon_replace_combo(
            """<span><span style="font-weight: bold;">Filename</span> Colon Replacement</span>""",
            self,
            FILENAME_COLON_OPTIONS,
        )
        self.fn_colon_replace.currentIndexChanged.connect(
            self._update_current_tab_file_example
        )
        fn_colon_replace_v_box = QVBoxLayout()
        fn_colon_replace_v_box.setContentsMargins(0, 0, 0, 0)
        fn_colon_replace_v_box.addWidget(fn_colon_replace_lbl)
        fn_colon_replace_v_box.addWidget(self.fn_colon_replace)

        title_colon_replace_lbl, self.title_colon_replace = (
            self._build_colon_replace_combo(
                """<span><span style="font-weight: bold;">Title</span> Colon Replacement</span>""",
                self,
            )
        )
        self.title_colon_replace.currentIndexChanged.connect(
            self._update_current_tab_title_example
        )
        title_colon_replace_v_box = QVBoxLayout()
        title_colon_replace_v_box.setContentsMargins(0, 0, 0, 0)
        title_colon_replace_v_box.addWidget(title_colon_replace_lbl)
        title_colon_replace_v_box.addWidget(self.title_colon_replace)

        multi_episode_style_lbl = QLabel(
            """<span style="font-weight: bold;">Multi-Episode Style</span>""",
            self,
        )
        multi_episode_style_lbl.setToolTip(
            "Select how NfoForge formats file names and titles for episodes "
            "that span multiple episode numbers"
        )
        self.multi_episode_style_combo = CustomComboBox(
            disable_mouse_wheel=True, parent=self
        )
        self.multi_episode_style_combo.currentIndexChanged.connect(
            self._update_all_examples
        )
        multi_episode_style_v_box = QVBoxLayout()
        multi_episode_style_v_box.setContentsMargins(0, 0, 0, 0)
        multi_episode_style_v_box.addWidget(multi_episode_style_lbl)
        multi_episode_style_v_box.addWidget(self.multi_episode_style_combo)

        season_folder_lbl = QLabel(
            """<span><span style="font-weight: bold;">Season Folder</span> Token</span>""",
            self,
        )
        season_folder_lbl.setToolTip(
            "Token used to rename the opened season pack folder. Only applies "
            "when a directory is opened; opening a single file leaves any folder "
            "untouched. A pack spanning several seasons renders {season_number} "
            "as a range, e.g. S01-S05."
        )
        self.season_folder_token = QLineEdit(self)
        self.season_folder_token.textChanged.connect(self._update_season_folder_example)
        self.season_folder_example = QLineEdit(self, readOnly=True, frame=False)
        season_folder_v_box = QVBoxLayout()
        season_folder_v_box.setContentsMargins(0, 0, 0, 0)
        season_folder_v_box.addWidget(season_folder_lbl)
        season_folder_v_box.addWidget(self.season_folder_token)
        season_folder_v_box.addWidget(self.season_folder_example)

        season_subfolder_lbl = QLabel(
            """<span><span style="font-weight: bold;">Season Subfolder</span> Token</span>""",
            self,
        )
        season_subfolder_lbl.setToolTip(
            "Token used to rename each 'Season NN' subfolder inside a pack that "
            "keeps its seasons in separate folders. Leave blank to use the "
            "Season Folder token, which names each subfolder after its own "
            "season while the pack folder above it carries the season range."
        )
        self.season_subfolder_token = QLineEdit(self)
        self.season_subfolder_token.setPlaceholderText(
            "Blank: use the Season Folder token"
        )
        self.season_subfolder_token.textChanged.connect(
            self._update_season_subfolder_example
        )
        self.season_subfolder_example = QLineEdit(self, readOnly=True, frame=False)
        season_subfolder_v_box = QVBoxLayout()
        season_subfolder_v_box.setContentsMargins(0, 0, 0, 0)
        season_subfolder_v_box.addWidget(season_subfolder_lbl)
        season_subfolder_v_box.addWidget(self.season_subfolder_token)
        season_subfolder_v_box.addWidget(self.season_subfolder_example)

        self.controls_box = QGroupBox("Controls")
        controls_layout = QVBoxLayout(self.controls_box)
        controls_layout.addLayout(control_top_layout)
        controls_layout.addWidget(self.claims_master)
        controls_layout.addLayout(self._build_claim_checks_layout(self.claim_checks))
        controls_layout.addLayout(fn_colon_replace_v_box)
        controls_layout.addLayout(title_colon_replace_v_box)
        controls_layout.addLayout(multi_episode_style_v_box)
        controls_layout.addLayout(season_folder_v_box)
        controls_layout.addLayout(season_subfolder_v_box)

        #### per format tabs ####
        self._format_widgets: dict[EpisodeFormat, FormatWidgets] = {}

        self.format_tab_widget = QTabWidget(self)
        for fmt in self._FORMAT_ORDER:
            tab_widget = self._build_format_tab(fmt)
            self.format_tab_widget.addTab(tab_widget, str(fmt))

        #### token table ####
        self.token_table = TokenTable(
            self._get_file_tokens(), allow_edits=False, parent=self
        )
        self.token_table.main_layout.setContentsMargins(0, 0, 0, 0)

        self.token_table_box = QGroupBox("Tokens")
        token_table_layout = QVBoxLayout(self.token_table_box)
        token_table_layout.addWidget(self.token_table)

        self.add_widget(self.controls_box)
        self.add_widget(self.format_tab_widget)
        self.add_widget(self.token_table_box)
        self.add_layout(self.reset_layout, add_stretch=True)

        self._load_saved_settings()

    def _build_format_tab(self, fmt: EpisodeFormat) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)

        # file token section
        file_token_input = QLineEdit(container)
        file_example = QLineEdit(container, readOnly=True, frame=False)
        file_token_input.textChanged.connect(lambda: self._update_tab_file_example(fmt))

        filename_box = QGroupBox()
        filename_box.setLayout(
            self._build_token_layout(
                QLabel("Token", container),
                file_token_input,
                self._build_indented_example_section(
                    QLabel("Example", container), file_example
                ),
            )
        )
        filename_box_lbl = QLabel(
            """<span>Format <span style="font-weight: bold;">Filename</span> Tokens</span>""",
            container,
        )

        # title token section
        title_token_input = QLineEdit(container)
        title_example = QLineEdit(container, readOnly=True, frame=False)
        title_token_input.textChanged.connect(
            lambda: self._update_tab_title_example(fmt)
        )

        title_box = QGroupBox()
        title_box.setLayout(
            self._build_token_layout(
                QLabel("Token", container),
                title_token_input,
                self._build_indented_example_section(
                    QLabel("Example", container), title_example
                ),
            )
        )
        title_box_lbl = QLabel(
            """<span>Format <span style="font-weight: bold;">Title</span> Tokens</span>""",
            container,
        )

        layout.addLayout(
            self._build_nested_groupbox_layout(filename_box_lbl, filename_box)
        )
        layout.addLayout(self._build_nested_groupbox_layout(title_box_lbl, title_box))

        self._format_widgets[fmt] = {
            "file_token": file_token_input,
            "title_token": title_token_input,
            "file_example": file_example,
            "title_example": title_example,
        }
        return container

    def _update_tab_file_example(self, fmt: EpisodeFormat) -> None:
        w = self._format_widgets[fmt]
        self._update_example(
            token_str=w["file_token"].text(),
            colon_replace=ColonReplace(self.fn_colon_replace.currentData()),
            file_name_mode=True,
            qline=w["file_example"],
        )

    def _update_tab_title_example(self, fmt: EpisodeFormat) -> None:
        w = self._format_widgets[fmt]
        self._update_example(
            token_str=w["title_token"].text(),
            colon_replace=ColonReplace(self.title_colon_replace.currentData()),
            file_name_mode=False,
            qline=w["title_example"],
        )

    @Slot()
    def _update_current_tab_file_example(self) -> None:
        fmt = self._FORMAT_ORDER[self.format_tab_widget.currentIndex()]
        self._update_tab_file_example(fmt)

    @Slot()
    def _update_current_tab_title_example(self) -> None:
        fmt = self._FORMAT_ORDER[self.format_tab_widget.currentIndex()]
        self._update_tab_title_example(fmt)

    def _update_all_examples(self) -> None:
        for fmt in self._FORMAT_ORDER:
            self._update_tab_file_example(fmt)
            self._update_tab_title_example(fmt)
        self._update_season_folder_example()
        self._update_season_subfolder_example()

    def _update_season_folder_example(self) -> None:
        self._update_example(
            token_str=self.season_folder_token.text(),
            colon_replace=ColonReplace(self.fn_colon_replace.currentData()),
            file_name_mode=True,
            qline=self.season_folder_example,
            episode_number=None,
            season_end=3,
        )

    def _update_season_subfolder_example(self) -> None:
        """Preview one season's subfolder, i.e. no season range.

        Falls back to the season folder token exactly as the rename does, so
        the blank default previews what the user will actually get rather than
        an empty line.
        """
        token_str = resolve_season_subfolder_token(
            self.season_subfolder_token.text(), self.season_folder_token.text()
        )
        self._update_example(
            token_str=token_str,
            colon_replace=ColonReplace(self.fn_colon_replace.currentData()),
            file_name_mode=True,
            qline=self.season_subfolder_example,
            episode_number=None,
            # equal to the example's season_number, so {season_number} renders
            # a single season rather than the range the pack folder shows
            season_end=1,
        )

    def _detected_claims(self) -> FilenameClaims:
        """Claims the example filename carries, per the current switches."""
        return detect_filename_claims(
            [EXAMPLE_FILE_NAME_1.stem],
            self._current_claim_switches(),
            self.config.plugin_manager.custom_edition_info(
                enabled=self.config.settings.general.enable_plugins
            ),
        )

    def _update_example(
        self,
        token_str: str,
        colon_replace: ColonReplace,
        file_name_mode: bool,
        qline: QLineEdit,
        override_title_rules: list[tuple[str, str]] | None = None,
        episode_number: int | None = 1,
        season_end: int = 1,
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
            # Stage 1 detection, the same function the rename pages call,
            # so the preview and the wizard cannot disagree about what the
            # example filename claims.
            override_tokens=self._detected_claims().as_override_tokens(),
            flat_filters=self.config.plugin_manager.flat_filters(
                enabled=self.config.settings.general.enable_plugins
            ),
            custom_edition_info=self.config.plugin_manager.custom_edition_info(
                enabled=self.config.settings.general.enable_plugins
            ),
            custom_cut_names=self.config.plugin_manager.custom_cut_names(
                enabled=self.config.settings.general.enable_plugins
            ),
            season_number=1,
            season_end=season_end,
            episode_number=episode_number,
            multi_episode_style=MultiEpisodeStyle(
                self.multi_episode_style_combo.currentData()
            ),
        )
        example_txt = qline.text()
        output = format_str.get_output()
        if output:
            example_txt = output
        self._update_qline_cursor_0(qline, example_txt)
        return example_txt

    @Slot()
    def _load_saved_settings(self) -> None:
        self._live_title_clean_rules = None
        self._live_video_dynamic_range = None

        self.fn_colon_replace.blockSignals(True)
        self.title_colon_replace.blockSignals(True)
        self.multi_episode_style_combo.blockSignals(True)
        self.season_folder_token.blockSignals(True)
        self.season_subfolder_token.blockSignals(True)
        for fmt in self._FORMAT_ORDER:
            w = self._format_widgets[fmt]
            w["file_token"].blockSignals(True)
            w["title_token"].blockSignals(True)

        self.rename_check_box.setChecked(self.config.settings.series.enabled)
        self._load_filename_colon_combo(
            self.fn_colon_replace,
            self.config.settings.series.filename_colon_replace,
        )
        self.load_combo_box(
            self.title_colon_replace,
            ColonReplace,
            self.config.settings.series.title_colon_replace,
        )
        self._load_claim_switches(self.config.settings.series.claims)
        self.load_combo_box(
            self.multi_episode_style_combo,
            MultiEpisodeStyle,
            self.config.settings.series.multi_episode_style,
        )
        self._update_qline_cursor_0(
            self.season_folder_token,
            self.config.settings.series.season_folder_token,
        )
        self._update_qline_cursor_0(
            self.season_subfolder_token,
            self.config.settings.series.season_subfolder_token,
        )

        for fmt in self._FORMAT_ORDER:
            w = self._format_widgets[fmt]
            episode_tok = get_tvr_episode_token(self.config.settings.series, fmt)
            if episode_tok.strip():
                self._update_qline_cursor_0(w["file_token"], episode_tok)
            title_tok = get_tvr_title_token(self.config.settings.series, fmt)
            if title_tok.strip():
                self._update_qline_cursor_0(w["title_token"], title_tok)

        self.fn_colon_replace.blockSignals(False)
        self.title_colon_replace.blockSignals(False)
        self.multi_episode_style_combo.blockSignals(False)
        self.season_folder_token.blockSignals(False)
        self.season_subfolder_token.blockSignals(False)
        for fmt in self._FORMAT_ORDER:
            w = self._format_widgets[fmt]
            w["file_token"].blockSignals(False)
            w["title_token"].blockSignals(False)

        self._update_all_examples()

    @Slot()
    def _save_settings(self) -> None:
        self.config.settings.series.enabled = self.rename_check_box.isChecked()
        self.config.settings.series.filename_colon_replace = ColonReplace(
            self.fn_colon_replace.currentData()
        )
        self.config.settings.series.title_colon_replace = ColonReplace(
            self.title_colon_replace.currentData()
        )
        self.config.settings.series.claims = self._current_claim_switches()
        self.config.settings.series.multi_episode_style = MultiEpisodeStyle(
            self.multi_episode_style_combo.currentData()
        )
        self.config.settings.series.season_folder_token = (
            self.season_folder_token.text()
        )
        self.config.settings.series.season_subfolder_token = (
            self.season_subfolder_token.text()
        )

        for fmt in self._FORMAT_ORDER:
            w = self._format_widgets[fmt]
            set_tvr_episode_token(
                self.config.settings.series, fmt, w["file_token"].text()
            )
            set_tvr_title_token(
                self.config.settings.series, fmt, w["title_token"].text()
            )

        self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.rename_check_box.setChecked(self.config.defaults.series.enabled)
        self._select_filename_colon(
            self.fn_colon_replace, self.config.defaults.series.filename_colon_replace
        )
        self._load_claim_switches(self.config.defaults.series.claims)
        self.title_colon_replace.setCurrentIndex(
            self.config.defaults.series.title_colon_replace.value - 1
        )
        self.multi_episode_style_combo.setCurrentIndex(
            self.config.defaults.series.multi_episode_style.value
        )
        self.season_folder_token.setText(
            self.config.defaults.series.season_folder_token
        )
        self.season_subfolder_token.setText(
            self.config.defaults.series.season_subfolder_token
        )
        for fmt in self._FORMAT_ORDER:
            w = self._format_widgets[fmt]
            w["file_token"].setText(
                get_tvr_episode_token(self.config.defaults.series, fmt)
            )
            w["title_token"].setText(
                get_tvr_title_token(self.config.defaults.series, fmt)
            )
        self.token_table.reset()

    @Slot()
    def _show_example_input_data(self) -> None:
        window = QDialog(self)
        set_top_parent_geometry(window)

        example_fn = QLineEdit(window, readOnly=True, text=str(EXAMPLE_FILE_NAME_1))
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

    @Slot()
    def _token_state_changed(self) -> None:
        self.token_table.populate_table(self._get_file_tokens(), False)
        self._update_current_tab_file_example()

    @Slot(object)
    def _global_management_state_changed(self, data: dict[str, object]) -> None:
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
        return (
            self._live_title_clean_rules
            if self._live_title_clean_rules is not None
            else self.config.settings.global_management.title_clean_rules
        )

    def _get_live_video_dynamic_range(self) -> DynamicRangeSettings:
        return (
            self._live_video_dynamic_range
            if self._live_video_dynamic_range is not None
            else self.config.settings.global_management.video_dynamic_range
        )

    @staticmethod
    def _build_colon_replace_combo(
        lbl_txt: str,
        parent: QWidget,
        options: Sequence[tuple[ColonReplace, str]] | None = None,
    ) -> tuple[QLabel, CustomComboBox]:
        """Build a colon-replacement combo.

        ``options`` defaults to every ColonReplace member, which is what the
        title side wants. The filename side passes FILENAME_COLON_OPTIONS:
        three members with their own labels, because "Keep" and "Delete"
        describe the enum rather than what a filename ends up looking like.
        """
        lbl = QLabel(lbl_txt, parent)
        lbl.setToolTip("Select how NfoForge handles colon replacement")
        combo = CustomComboBox(disable_mouse_wheel=True, parent=parent)
        for colon_enum, label in options or [
            (member, str(member)) for member in ColonReplace
        ]:
            combo.addItem(label, colon_enum)
        return lbl, combo

    @staticmethod
    def _build_token_layout(
        widget_1: QWidget,
        widget_2: QWidget,
        example_section: QWidget,
        header_widgets: Sequence[QWidget] | None = None,
        footer_widgets: Sequence[QWidget] | None = None,
        margins: tuple[int, int, int, int] | None = None,
    ) -> QVBoxLayout:
        layout = QVBoxLayout()
        if margins:
            layout.setContentsMargins(*margins)
        if header_widgets:
            for hw in header_widgets:
                layout.addWidget(hw)
        layout.addWidget(widget_1)
        layout.addWidget(widget_2)
        layout.addWidget(example_section)
        if footer_widgets:
            for fw in footer_widgets:
                layout.addWidget(fw)
        return layout

    @staticmethod
    def _build_indented_example_section(
        example_label: QWidget, example_input: QWidget
    ) -> QWidget:
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 0, 0, 0)
        container_layout.setSpacing(4)
        container_layout.addWidget(example_label)
        container_layout.addWidget(example_input)
        return container

    @staticmethod
    def _build_nested_groupbox_layout(widget1: QWidget, box: QGroupBox) -> QVBoxLayout:
        nested = QVBoxLayout()
        nested.setContentsMargins(0, 0, 0, 0)
        nested.setSpacing(0)
        nested.addWidget(widget1)
        nested.addWidget(box)
        return nested

    @staticmethod
    def _update_qline_cursor_0(widget: QLineEdit, txt: str) -> None:
        widget.setText(txt)
        widget.setCursorPosition(0)
        widget.setToolTip(txt)
