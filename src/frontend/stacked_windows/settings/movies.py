from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QCheckBox,
    QFormLayout,
    QLineEdit,
)

from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import create_form_layout
from src.backend.tokens import Tokens, FileToken
from src.backend.token_replacer import TokenReplacer, ColonReplace, UnfilledTokenRemoval


class MoviesSettings(BaseSettings):
    """Movie specific settings"""

    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("movieSettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        self.rename_check_box = QCheckBox("Rename Movies")
        self.rename_check_box.setToolTip(
            "Will use the existing file name if renaming is disabled"
        )

        self.replace_illegal_chars = QCheckBox("Replace Illegal Characters")
        self.replace_illegal_chars.setToolTip(
            "Replace illegal characters. If unchecked, NfoForge will remove them instead"
        )

        check_button_layout = QFormLayout()
        check_button_layout.addWidget(self.rename_check_box)
        check_button_layout.addWidget(self.replace_illegal_chars)

        self.check_media_info = QCheckBox("Parse With MediaInfo")
        self.check_media_info.setToolTip(
            "If checked, title information will be confirmed with MediaInfo"
        )
        check_mi_layout = QFormLayout()
        check_mi_layout.addWidget(self.check_media_info)

        colon_replacement_lbl = QLabel("Colon Replacement")
        colon_replacement_lbl.setToolTip(
            "Select how NfoForge handles colon replacement"
        )
        self.colon_replacement_combo = CustomComboBox()
        self.colon_replacement_combo.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        for colon_enum in ColonReplace:
            self.colon_replacement_combo.addItem(str(colon_enum), colon_enum.value)
        colon_replacement = create_form_layout(
            colon_replacement_lbl, self.colon_replacement_combo
        )
        self.colon_replacement_combo.currentIndexChanged.connect(
            self._update_movie_token_example_lbl
        )

        movie_format_lbl = QLabel("Movie Format")
        movie_format_lbl.setToolTip(
            "Select which tokens are used to generate the renamed file name"
        )
        self.default_user_token = (
            "{movie_title} {release_year} {re_release} "
            "{source} {resolution} {mi_audio_codec} "
            "{mi_audio_channel_s} {mi_video_codec}{:opt=-:release_group}"
        )
        self.movie_format_entry = QLineEdit(self.default_user_token)
        self.movie_format_entry.setCursorPosition(0)
        self.movie_format_entry.textChanged.connect(
            self._update_movie_token_example_lbl
        )

        title_example_label = QLabel("Title Example")
        title_example_label.setToolTip("An example of the title output")
        self.title_example_entry = QLineEdit()
        self.title_example_entry.setDisabled(True)
        title_example_form = create_form_layout(
            title_example_label, self.title_example_entry
        )
        title_example_form.setContentsMargins(5, 0, 0, 0)

        file_example_label = QLabel("File Example")
        file_example_label.setToolTip("An example of the file output")
        self.file_example_entry = QLineEdit()
        self.file_example_entry.setDisabled(True)
        file_example_form = create_form_layout(
            file_example_label, self.file_example_entry
        )
        file_example_form.setContentsMargins(5, 0, 0, 0)

        movie_format_widget = QWidget()
        movie_format_layout = QVBoxLayout(movie_format_widget)
        movie_format_layout.setContentsMargins(0, 0, 0, 0)
        movie_format_layout.addWidget(self.movie_format_entry)
        movie_format_layout.addLayout(title_example_form)
        movie_format_layout.addLayout(file_example_form)
        movie_format = create_form_layout(movie_format_lbl, movie_format_widget)

        movie_token_lbl = QLabel("Movie Tokens")
        movie_token_lbl.setToolTip(
            "Table of available movie tokens with short descriptions"
        )
        self.token_table = TokenTable(
            sorted(Tokens().get_token_objects(FileToken)),
            allow_edits=True,
        )
        token_table_layout = create_form_layout(movie_token_lbl, self.token_table)

        self.add_layout(check_button_layout)
        self.add_layout(check_mi_layout)
        self.add_layout(colon_replacement)
        self.add_layout(movie_format)
        self.add_layout(token_table_layout)
        self.add_layout(self.reset_layout)

        self._load_saved_settings()

    def _update_movie_token_example_lbl(self) -> None:
        # TODO get an actual dump of a file to actually parse the data in real time as well
        example_str = (
            "The Matrix 1999 UHD BluRay 2160p DTS-X.7.1 DV HEVC REMUX-ExampleGroup.mkv"
        )
        # TODO make sure to update this when we update media renamer
        format_str = TokenReplacer(
            media_input=Path(example_str),
            jinja_engine=None,
            source_file=None,
            token_string=self.movie_format_entry.text(),
            colon_replace=ColonReplace(self.colon_replacement_combo.currentData()),
            flatten=True,
            token_type=FileToken,
            unfilled_token_mode=UnfilledTokenRemoval.TOKEN_ONLY,
            movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
        )
        example_title_text = self.title_example_entry.text()
        example_file_text = self.file_example_entry.text()
        output = format_str.get_output()
        if output:
            example_title_text, example_file_text = output
        self.title_example_entry.setText(example_title_text)
        self.title_example_entry.setCursorPosition(0)
        self.file_example_entry.setText(example_file_text)
        self.file_example_entry.setCursorPosition(0)

    @Slot()
    def _load_saved_settings(self) -> None:
        """Applies user saved settings from the config"""
        # temporarily block signals until data is loaded
        self.movie_format_entry.blockSignals(True)
        self.colon_replacement_combo.blockSignals(True)

        self.rename_check_box.setChecked(self.config.cfg_payload.mvr_enabled)
        self.replace_illegal_chars.setChecked(
            self.config.cfg_payload.mvr_replace_illegal_chars
        )
        self.check_media_info.setChecked(
            self.config.cfg_payload.mvr_parse_with_media_info
        )
        self.load_combo_box(
            self.colon_replacement_combo,
            ColonReplace,
            self.config.cfg_payload.mvr_colon_replacement,
        )

        if self.config.cfg_payload.mvr_token.strip():
            self.movie_format_entry.setText(self.config.cfg_payload.mvr_token)
            self.movie_format_entry.setCursorPosition(0)

        self.token_table.load_replacement_rules(
            self.config.cfg_payload.mvr_clean_title_rules
        )

        # unblock signals
        self.movie_format_entry.blockSignals(False)
        self.colon_replacement_combo.blockSignals(False)
        self._update_movie_token_example_lbl()

    @Slot()
    def _save_settings(self) -> None:
        self.config.cfg_payload.mvr_enabled = self.rename_check_box.isChecked()
        self.config.cfg_payload.mvr_replace_illegal_chars = (
            self.replace_illegal_chars.isChecked()
        )
        self.config.cfg_payload.mvr_parse_with_media_info = (
            self.check_media_info.isChecked()
        )
        self.config.cfg_payload.mvr_colon_replacement = ColonReplace(
            self.colon_replacement_combo.currentData()
        )
        self.config.cfg_payload.mvr_token = self.movie_format_entry.text()
        self._mvr_clean_title_rules_change()
        self.updated_settings_applied.emit()

    def _mvr_clean_title_rules_change(self) -> None:
        replacements = self.token_table.replacement_list_widget.replacement_list_widget.get_replacements()
        defaults = self.token_table.replacement_list_widget.DEFAULT_RULES
        if not self.config.cfg_payload.mvr_clean_title_rules_modified:
            self.config.cfg_payload.mvr_clean_title_rules = defaults
        else:
            self.config.cfg_payload.mvr_clean_title_rules = replacements

        if set(replacements) != set(defaults):
            self.config.cfg_payload.mvr_clean_title_rules_modified = True
        else:
            self.config.cfg_payload.mvr_clean_title_rules_modified = False

    def apply_defaults(self) -> None:
        self.rename_check_box.setChecked(False)
        self.replace_illegal_chars.setChecked(True)
        self.check_media_info.setChecked(True)
        self.colon_replacement_combo.setCurrentIndex(0)
        self.movie_format_entry.setText(self.default_user_token)
        self.token_table.reset()
        self.config.cfg_payload.mvr_clean_title_rules_modified = False
