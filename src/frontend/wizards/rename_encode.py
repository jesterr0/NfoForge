from collections.abc import Sequence
from pathlib import Path
import re
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.rename_encode import RenameEncodeBackEnd
from src.backend.tokens import FileToken, Tokens
from src.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
)
from src.config.config import Config
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.utils import build_auto_theme_icon_buttons, build_h_line
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.packages.custom_types import RenameNormalization

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class RenameEncode(BaseWizardPage):
    REPACK_REASONS = (
        "",
        "Repacked to correct filename",
        "Repacked due to subtitle issue",
        "Repacked to fix aspect ratio issue",
        "Repacked due to audio issues",
        "Repacked due to problem with file",
    )

    PROPER_REASONS = (
        "",
        "Proper for superior audio quality",
        "Proper for superior video quality",
        "Proper for superior video and audio quality",
    )

    REASON_STR = "Select or enter reason"

    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)
        self.setTitle("Rename")
        self.setObjectName("renameEncode")
        self.setCommitPage(True)

        self.config = config
        self.backend = RenameEncodeBackEnd()
        self._input_ext: str | None = None
        self._token_window: QWidget | None = None

        self.media_label = QLabel()
        self.media_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum
        )
        self.media_label.setCursor(Qt.CursorShape.WhatsThisCursor)

        input_group_box = QGroupBox("Input")
        input_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )
        input_group_box_layout = QVBoxLayout(input_group_box)
        input_group_box_layout.addWidget(self.media_label)

        options_group_box = QGroupBox("Options")
        options_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )
        options_layout = QGridLayout(options_group_box)
        options_layout.setColumnStretch(0, 1)
        options_layout.setColumnStretch(1, 1)
        options_layout.setColumnStretch(2, 1)
        options_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        edition_lbl = QLabel("Edition", self)
        self.edition_combo = CustomComboBox(
            completer=True, completer_strict=False, parent=self
        )
        self._update_combo_box(self.edition_combo, EDITION_INFO)
        self.edition_combo.currentIndexChanged.connect(self._update_edition_combo)
        edition_combo_line_edit = self.edition_combo.lineEdit()
        if not edition_combo_line_edit:
            raise AttributeError("Could not detect edition_combo.lineEdit()")
        edition_combo_line_edit.editingFinished.connect(self._update_edition_combo)

        frame_size_lbl = QLabel("Frame Size", self)
        self.frame_size_combo = CustomComboBox(parent=self)
        self._update_combo_box(self.frame_size_combo, FRAME_SIZE_INFO)
        self.frame_size_combo.currentIndexChanged.connect(self._update_frame_size_combo)

        localization_lbl = QLabel("Localization", self)
        self.localization_combo = CustomComboBox(parent=self)
        self._update_combo_box(self.localization_combo, LOCALIZATION_INFO)
        self.localization_combo.currentIndexChanged.connect(
            self._update_localization_combo
        )

        re_release_lbl = QLabel("Rerelease", self)
        self.re_release_combo = CustomComboBox(parent=self)
        self._update_combo_box(self.re_release_combo, RE_RELEASE_INFO)
        self.re_release_combo.currentIndexChanged.connect(self._update_re_release_combo)

        self.repack_reason_lbl = QLabel("Repack Reason", self)
        self.repack_reason_combo = CustomComboBox(
            completer=True, completer_strict=False, parent=self
        )
        self.repack_reason_combo.setSizeAdjustPolicy(
            CustomComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.repack_reason_combo.addItems(self.REPACK_REASONS)
        repack_reason_combo_line_edit = self.repack_reason_combo.lineEdit()
        if not repack_reason_combo_line_edit:
            raise AttributeError("Could not detect repack_reason_combo.lineEdit()")
        repack_reason_combo_line_edit.setPlaceholderText(self.REASON_STR)
        self.repack_reason_lbl.hide()
        self.repack_reason_combo.hide()

        self.proper_reason_lbl = QLabel("Proper Reason", self)
        self.proper_reason_combo = CustomComboBox(
            completer=True, completer_strict=False, parent=self
        )
        self.proper_reason_combo.setSizeAdjustPolicy(
            CustomComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.proper_reason_combo.addItems(self.PROPER_REASONS)
        proper_reason_combo_line_edit = self.repack_reason_combo.lineEdit()
        if not proper_reason_combo_line_edit:
            raise AttributeError(
                "Could not detect proper_reason_combo_line_edit.lineEdit()"
            )
        proper_reason_combo_line_edit.setPlaceholderText(self.REASON_STR)
        self.proper_reason_lbl.hide()
        self.proper_reason_combo.hide()

        self.combo_info_pairs = (
            (self.edition_combo, EDITION_INFO),
            (self.frame_size_combo, FRAME_SIZE_INFO),
            (self.localization_combo, LOCALIZATION_INFO),
            (self.re_release_combo, RE_RELEASE_INFO),
        )

        release_group_lbl = QLabel("Release Group", self)
        self.release_group_entry = QLineEdit(self)
        self.release_group_entry.setToolTip("Release group name")
        self.release_group_entry.textEdited.connect(self.update_generated_name)

        token_override_lbl = QLabel("Override Movie Name Token", self)
        view_tokens_popup_btn: QToolButton = build_auto_theme_icon_buttons(
            QToolButton,
            "token.svg",
            "previewTokenBtn",
            20,
            20,
            parent=self,
        )
        view_tokens_popup_btn.setToolTip("Preview available file tokens")
        view_tokens_popup_btn.clicked.connect(self._see_tokens)
        token_override_layout = QHBoxLayout()
        token_override_layout.setContentsMargins(0, 0, 0, 0)
        token_override_layout.addWidget(token_override_lbl)
        token_override_layout.addWidget(
            view_tokens_popup_btn, alignment=Qt.AlignmentFlag.AlignRight
        )
        self.token_override = QLineEdit(self)
        self.token_override.textEdited.connect(self.update_generated_name)

        self.override_group = QGroupBox(
            title="Override", parent=self, checkable=True, checked=False
        )
        self.override_group.toggled.connect(self.update_generated_name)
        override_group_layout = QVBoxLayout(self.override_group)
        override_group_layout.addLayout(token_override_layout)
        override_group_layout.addWidget(self.token_override)

        self.remux_checkbox = QCheckBox("REMUX", self)
        self.remux_checkbox.setToolTip("Toggle REMUX token")
        self.remux_checkbox.toggled.connect(self._remux_toggle)

        self.hybrid_checkbox = QCheckBox("HYBRID", self)
        self.hybrid_checkbox.setToolTip("Toggle HYBRID token")
        self.hybrid_checkbox.toggled.connect(self._hybrid_toggle)

        checkboxes_layout = QHBoxLayout()
        checkboxes_layout.setContentsMargins(0, 0, 0, 0)
        checkboxes_layout.addWidget(self.remux_checkbox)
        checkboxes_layout.addWidget(self.hybrid_checkbox)

        options_layout.addWidget(edition_lbl, 0, 0)
        options_layout.addWidget(self.edition_combo, 1, 0)
        options_layout.addWidget(frame_size_lbl, 0, 1)
        options_layout.addWidget(self.frame_size_combo, 1, 1)
        options_layout.addWidget(localization_lbl, 0, 2)
        options_layout.addWidget(self.localization_combo, 1, 2)
        options_layout.addWidget(re_release_lbl, 2, 0)
        options_layout.addWidget(self.re_release_combo, 3, 0)
        options_layout.addWidget(self.repack_reason_lbl, 2, 1)
        options_layout.addWidget(self.repack_reason_combo, 3, 1, 1, 2)
        options_layout.addWidget(self.proper_reason_lbl, 2, 1)
        options_layout.addWidget(self.proper_reason_combo, 3, 1, 1, 2)
        options_layout.addLayout(checkboxes_layout, 4, 0, 1, 1)
        options_layout.addWidget(build_h_line((6, 4, 6, 4)), 18, 0, 1, 3)
        options_layout.addWidget(release_group_lbl, 19, 0)
        options_layout.addWidget(self.release_group_entry, 20, 0, 1, 3)
        options_layout.addWidget(build_h_line((6, 4, 6, 4)), 21, 0, 1, 3)
        options_layout.addWidget(self.override_group, 22, 0, 1, 3)

        output_group_box = QGroupBox("Output")
        output_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )
        output_layout = QVBoxLayout(output_group_box)
        self.output_entry = QLineEdit()
        self.output_entry.setToolTip("Suggested name, updates automatically")

        output_layout.addWidget(self.output_entry)

        layout = QVBoxLayout(self)
        layout.addWidget(input_group_box)
        layout.addWidget(options_group_box)
        layout.addWidget(output_group_box)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def initializePage(self) -> None:
        data = self.config.media_input_payload
        media_file = data.encode_file
        release_group_name = self.config.cfg_payload.mvr_release_group

        if not media_file:
            raise FileNotFoundError("Failed to load 'media_file' data")
        else:
            media_file = Path(media_file)

        self.media_label.setText(media_file.stem)
        self.media_label.setToolTip(media_file.stem)

        self.token_override.setText(self.config.cfg_payload.mvr_token)

        self.release_group_entry.setText(
            release_group_name if release_group_name else ""
        )

        self.update_generated_name()

    def validatePage(self) -> bool:
        file_input = self.config.media_input_payload.encode_file
        if file_input:
            if not self._name_validations() or not self._release_group_validation():
                return False
            self.config.media_input_payload.renamed_file = Path(
                file_input
            ).parent / Path(f"{self.output_entry.text().strip()}{self._input_ext}")

            release_group = self.release_group_entry.text().strip()
            if release_group and (
                release_group != self.config.cfg_payload.mvr_release_group
            ):
                self.config.cfg_payload.mvr_release_group = release_group
                self.config.save_config()

            # update config shared data with detected edition
            edition_combo_text = self.edition_combo.currentText()
            if edition_combo_text:
                self.config.shared_data.dynamic_data["edition_override"] = (
                    edition_combo_text
                )

            # update config shared data with frame size
            frame_size_text = self.frame_size_combo.currentText()
            if frame_size_text:
                self.config.shared_data.dynamic_data["frame_size_override"] = (
                    frame_size_text
                )

            # update config shared data with over ride tokens
            self.config.shared_data.dynamic_data["override_tokens"] = (
                self.backend.override_tokens
            )

            # update re release tokens
            self._re_release_reason_tokens_update()

            # close token window
            self._close_token_window()

            return True
        return False

    @Slot()
    def _see_tokens(self) -> None:
        if self._token_window:
            return

        self._token_window = QDialog(
            parent=self, f=Qt.WindowType.Window, sizeGripEnabled=True, modal=False
        )
        self._token_window.setWindowTitle("Tokens")
        self._token_window.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        self._token_window.resize(self.geometry().size())
        self._token_window.finished.connect(self._close_token_window)

        token_widget = TokenTable(
            tokens=sorted(Tokens().get_token_objects(FileToken)),
            remove_brackets=False,
            parent=self._token_window,
        )

        layout = QVBoxLayout()
        layout.addWidget(token_widget)
        self._token_window.setLayout(layout)
        self._token_window.show()

    @Slot(int)
    def _close_token_window(self, _: int | None = None) -> None:
        if self._token_window:
            self._token_window.deleteLater()
        self._token_window = None

    def _name_validations(self) -> bool:
        renamed_output_lowered = self.output_entry.text().lower()
        if "subbed" in renamed_output_lowered and "dubbed" in renamed_output_lowered:
            QMessageBox.warning(
                self, "Error", "Both 'Subbed' and 'Dubbed' should not be used together."
            )
            return False
        if "imax" in renamed_output_lowered and re.search(
            r"open[\s|\.]*matte", renamed_output_lowered, flags=re.I
        ):
            QMessageBox.warning(
                self,
                "Error",
                "Both 'IMAX' and 'Open Matte' should not be used together.",
            )
            return False
        return True

    def _release_group_validation(self) -> bool:
        input_text = self.output_entry.text().strip()

        saved_release_group = self.release_group_entry.text().strip()
        if saved_release_group.startswith("-"):
            QMessageBox.information(
                self,
                "Release Group",
                "Remove '-' from the start of your release group, this will be handled automatically.",
            )
            return False

        detect_group = re.search(r"-(\w{2,}?)$", input_text)
        if detect_group and (detect_group.group(1) != saved_release_group):
            if (
                QMessageBox.question(
                    self,
                    "Release Group",
                    (
                        "Release group detected in output that isn't the same as saved group, "
                        "would you like for this to be changed now?\n\nNote: you will have a chance "
                        "to confirm after this change."
                    ),
                )
                is QMessageBox.StandardButton.Yes
            ):
                new_name = f"{input_text.replace(detect_group.group(1), '')}{saved_release_group}"
                if new_name.endswith("-"):
                    new_name = new_name[:-1]
                self.output_entry.setText(new_name)
                return False
        elif not detect_group and saved_release_group:
            if (
                QMessageBox.question(
                    self,
                    "Release Group",
                    "Release group is missing from output, would you like to apply this now?\n\nNote: you "
                    "will have a chance to confirm after this change.",
                )
                is QMessageBox.StandardButton.Yes
            ):
                self.output_entry.setText(f"{input_text}-{saved_release_group}")
                return False
        return True

    def _re_release_reason_tokens_update(self) -> None:
        """
        Updates Jinja global variables for repack or proper reasons based on the current combo box selections
        and the content of the output text.
        """
        combo_to_global_map = {
            "repack_reason": (self.repack_reason_combo.currentText(), r"(repack\d*)"),
            "proper_reason": (self.proper_reason_combo.currentText(), r"(proper\d*)"),
        }

        final_output_text = self.output_entry.text()

        for global_name, (combo_text, pattern) in combo_to_global_map.items():
            if combo_text:
                self.config.jinja_engine.add_global(global_name, combo_text)
                match = re.search(pattern, final_output_text, flags=re.I)
                if match:
                    self.config.jinja_engine.add_global(
                        global_name.replace("_reason", "_n"), match.group(1)
                    )
                # ensure only one combo box is processed
                break

    @Slot(int)
    def _update_edition_combo(self, _: int | None = None) -> None:
        self._update_override_tokens(
            "edition", self.edition_combo.currentText().strip()
        )

    @Slot(int)
    def _update_frame_size_combo(self, _: int) -> None:
        self._update_override_tokens("frame_size", self.frame_size_combo.currentText())

    @Slot(int)
    def _update_localization_combo(self, _: int) -> None:
        self._update_override_tokens(
            "localization", self.localization_combo.currentText()
        )

    @Slot(int)
    def _update_re_release_combo(self, _: int) -> None:
        self._update_override_tokens("re_release", self.re_release_combo.currentText())
        self._enable_re_release_widgets(self.re_release_combo)

    @Slot(bool)
    def _remux_toggle(self, e: bool) -> None:
        self._update_override_tokens("remux", "REMUX", remove=not e)

    @Slot(bool)
    def _hybrid_toggle(self, e: bool) -> None:
        self._update_override_tokens("hybrid", "HYBRID", remove=not e)

    def _update_override_tokens(self, k: str, v: str, remove: bool = False) -> None:
        if remove or not v:
            self.backend.override_tokens.pop(k, None)
        else:
            self.backend.override_tokens[k] = v
        self.update_generated_name()

    @Slot(int)
    def update_generated_name(self, _: int | None = None) -> None:
        """Update the generated name based on current selections."""

        token = self.config.cfg_payload.mvr_token
        if self.override_group.isChecked():
            token = self.token_override.text()
        else:
            self.token_override.setText(token)

        data = self.config.media_input_payload
        media_file = data.encode_file
        source_file = data.source_file
        media_info_obj = data.encode_file_mi_obj
        release_group = self.release_group_entry.text().strip()
        if release_group:
            self.backend.override_tokens["release_group"] = release_group

        if not media_file:
            raise FileNotFoundError("Failed to read media_file")
        if not media_info_obj:
            raise AttributeError("Failed to parse MediaInfo")

        get_file_name = self.backend.media_renamer(
            media_file=media_file,
            source_file=source_file,
            mvr_token=token,
            mvr_colon_replacement=self.config.cfg_payload.mvr_colon_replace_filename,
            media_search_payload=self.config.media_search_payload,
            media_info_obj=media_info_obj,
            source_file_mi_obj=self.config.media_input_payload.source_file_mi_obj,
            movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
        )

        # update the output entry
        if get_file_name:
            self._input_ext = get_file_name.suffix
            self.output_entry.setText(str(get_file_name))

    def _reset_re_release_reason_widgets(self) -> None:
        """Hide and reset both repack and proper reason widgets."""
        for lbl, combo in [
            (self.repack_reason_lbl, self.repack_reason_combo),
            (self.proper_reason_lbl, self.proper_reason_combo),
        ]:
            lbl.hide()
            combo.hide()
            combo.setCurrentIndex(0)
            line_edit = combo.lineEdit()
            if line_edit:
                line_edit.setPlaceholderText(self.REASON_STR)

    def _enable_re_release_widgets(self, combo: CustomComboBox) -> None:
        """Show the appropriate reason widgets based on rerelease combo selection."""
        self._reset_re_release_reason_widgets()

        if combo is self.re_release_combo:
            text = combo.currentText().lower()
            if "repack" in text:
                self.repack_reason_lbl.show()
                self.repack_reason_combo.show()
            elif "proper" in text:
                self.proper_reason_lbl.show()
                self.proper_reason_combo.show()

    def reset_page(self) -> None:
        self.media_label.clear()
        for combo_box in (
            self.edition_combo,
            self.frame_size_combo,
            self.localization_combo,
            self.re_release_combo,
        ):
            combo_box.setCurrentIndex(0)
        self._reset_re_release_reason_widgets()
        self.release_group_entry.clear()
        self._input_ext = None
        self.output_entry.clear()

        self._close_token_window()

        self.backend.reset()

    @staticmethod
    def _update_combo_box(
        combobox: CustomComboBox,
        items: Sequence[RenameNormalization],
    ) -> None:
        combobox.addItem("")
        for item in items:
            combobox.addItem(item[0])
