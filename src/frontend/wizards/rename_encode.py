import re
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QGridLayout,
    QGroupBox,
    QSizePolicy,
)

from src.config.config import Config
from src.exceptions import MediaParsingError
from src.enums.rename import TypeHierarchy
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.frontend.utils import build_h_line
from src.backend.rename_encode import RenameEncodeBackEnd

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class RenameEncode(BaseWizardPage):
    EDITION_INFO = (
        (
            "Directors Cut",
            (r"(?:director's|directors)[\s|\.]*cut",),
            "Directors.Cut.",
            TypeHierarchy.CUT,
        ),
        (
            "Extended Cut",
            (r"extended(?:[\s|\.]*cut)?",),
            "Extended.Cut.",
            TypeHierarchy.CUT,
        ),
        (
            "Theatrical Cut",
            (r"theatrical(?:[\s|\.]*cut)?",),
            "Theatrical.Cut.",
            TypeHierarchy.CUT,
        ),
        ("Unrated", (r"unrated",), "Unrated.", TypeHierarchy.CUT),
        ("Uncut", (r"uncut",), "Uncut.", TypeHierarchy.CUT),
    )

    FRAME_SIZE_INFO = (
        ("IMAX", (r"imax",), "IMAX.", TypeHierarchy.EXTRAS),
        (
            "Open Matte",
            (r"open[\s|\.]*matte",),
            "Open.Matte.",
            TypeHierarchy.EXTRAS,
        ),
    )

    LOCALIZATION_INFO = (
        ("Dubbed", (r"dubbed",), "Dubbed.", TypeHierarchy.LOCALIZATION),
        ("Subbed", (r"subbed",), "Subbed.", TypeHierarchy.LOCALIZATION),
    )

    RE_RELEASE_INFO = (
        ("PROPER", (r"proper(?![2345])",), "PROPER.", TypeHierarchy.RE_RELEASE),
        ("PROPER2", (r"proper2",), "PROPER2.", TypeHierarchy.RE_RELEASE),
        ("PROPER3", (r"proper3",), "PROPER3.", TypeHierarchy.RE_RELEASE),
        ("PROPER4", (r"proper4",), "PROPER4.", TypeHierarchy.RE_RELEASE),
        ("PROPER5", (r"proper5",), "PROPER5.", TypeHierarchy.RE_RELEASE),
        ("REPACK", (r"repack(?![2345])",), "REPACK.", TypeHierarchy.RE_RELEASE),
        ("REPACK2", (r"repack2",), "REPACK2.", TypeHierarchy.RE_RELEASE),
        ("REPACK3", (r"repack3",), "REPACK3.", TypeHierarchy.RE_RELEASE),
        ("REPACK4", (r"repack4",), "REPACK4.", TypeHierarchy.RE_RELEASE),
        ("REPACK5", (r"repack5",), "REPACK5.", TypeHierarchy.RE_RELEASE),
    )

    REPACK_REASONS = (
        "",
        "Repacked to correct filename",
        "Repacked due to subtitle issue.",
        "Repacked to fix aspect ratio issue",
        "Repacked to fix AR issue",
        "Repacked due to audio issues",
    )

    PROPER_REASONS = (
        "",
        "Proper for superior audio quality",
        "Proper for superior video quality",
        "Proper for superior video and audio quality",
    )

    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)
        self.setTitle("Rename")
        self.setObjectName("renameEncode")
        self.setCommitPage(True)

        self.config = config
        self.backend = RenameEncodeBackEnd()
        self._input_ext: str | None = None

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

        check_box_layout_group_box = QGroupBox("Options")
        check_box_layout_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )
        check_box_layout = QGridLayout(check_box_layout_group_box)
        check_box_layout.setColumnStretch(0, 1)
        check_box_layout.setColumnStretch(1, 1)
        check_box_layout.setColumnStretch(2, 1)
        check_box_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        edition_lbl = QLabel("Edition", self)
        self.edition_combo = CustomComboBox(
            completer=True, completer_strict=False, parent=self
        )
        self._update_combo_box(self.edition_combo, self.EDITION_INFO)
        self.edition_combo.currentIndexChanged.connect(self.update_generated_name)
        self.edition_combo.lineEdit().editingFinished.connect(self.manual_edition_edit)
        self.edition_combo_line_edit_last_text: str | None = None

        frame_size_lbl = QLabel("Frame Size", self)
        self.frame_size_combo = CustomComboBox(parent=self)
        self._update_combo_box(self.frame_size_combo, self.FRAME_SIZE_INFO)
        self.frame_size_combo.currentIndexChanged.connect(self.update_generated_name)

        localization_lbl = QLabel("Localization", self)
        self.localization_combo = CustomComboBox(parent=self)
        self._update_combo_box(self.localization_combo, self.LOCALIZATION_INFO)
        self.localization_combo.currentIndexChanged.connect(self.update_generated_name)

        re_release_lbl = QLabel("Rerelease", self)
        self.re_release_combo = CustomComboBox(parent=self)
        self._update_combo_box(self.re_release_combo, self.RE_RELEASE_INFO)
        self.re_release_combo.currentIndexChanged.connect(self.update_generated_name)
        self.re_release_combo_last_index = 0

        self.repack_reason_lbl = QLabel("Repack Reason", self)
        self.repack_reason_combo = CustomComboBox(
            completer=True, completer_strict=False, parent=self
        )
        self.repack_reason_combo.setSizeAdjustPolicy(
            CustomComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.repack_reason_combo.addItems(self.REPACK_REASONS)
        self.repack_reason_combo.lineEdit().setPlaceholderText("Select Reason")
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
        self.proper_reason_combo.lineEdit().setPlaceholderText("Select Reason")
        self.proper_reason_lbl.hide()
        self.proper_reason_combo.hide()

        self.combo_info_pairs = (
            (self.edition_combo, self.EDITION_INFO),
            (self.frame_size_combo, self.FRAME_SIZE_INFO),
            (self.localization_combo, self.LOCALIZATION_INFO),
            (self.re_release_combo, self.RE_RELEASE_INFO),
        )

        release_group_lbl = QLabel("Release Group", self)
        self.release_group_entry = QLineEdit(self)
        self.release_group_entry.setToolTip("Release group name")
        self.release_group_entry.textChanged.connect(self.update_generated_name)

        check_box_layout.addWidget(edition_lbl, 0, 0)
        check_box_layout.addWidget(self.edition_combo, 1, 0)
        check_box_layout.addWidget(frame_size_lbl, 0, 1)
        check_box_layout.addWidget(self.frame_size_combo, 1, 1)
        check_box_layout.addWidget(localization_lbl, 0, 2)
        check_box_layout.addWidget(self.localization_combo, 1, 2)
        check_box_layout.addWidget(re_release_lbl, 2, 0)
        check_box_layout.addWidget(self.re_release_combo, 3, 0)
        check_box_layout.addWidget(self.repack_reason_lbl, 2, 1)
        check_box_layout.addWidget(self.repack_reason_combo, 3, 1, 1, 2)
        check_box_layout.addWidget(self.proper_reason_lbl, 2, 1)
        check_box_layout.addWidget(self.proper_reason_combo, 3, 1, 1, 2)
        check_box_layout.addWidget(build_h_line((6, 1, 6, 1)), 18, 0, 1, 3)
        check_box_layout.addWidget(release_group_lbl, 19, 0)
        check_box_layout.addWidget(self.release_group_entry, 20, 0, 1, 3)

        output_group_box = QGroupBox("Output")
        output_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )
        output_layout = QVBoxLayout(output_group_box)
        self.output_entry = QLineEdit()
        self.output_entry.setToolTip("Suggested name, updates automatically")

        # could re implement this if we want to auto update drop downs
        # self.output_entry.textChanged.connect(self._auto_select_combos)

        output_layout.addWidget(self.output_entry)

        layout = QVBoxLayout(self)
        layout.addWidget(input_group_box)
        layout.addWidget(check_box_layout_group_box)
        layout.addWidget(output_group_box)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def initializePage(self) -> None:
        data = self.config.media_input_payload
        media_file = data.encode_file
        source_file = data.source_file
        media_info_obj = data.encode_file_mi_obj
        release_group_name = self.config.cfg_payload.mvr_release_group

        if not media_file:
            raise FileNotFoundError("Failed to load 'media_file' data")
        else:
            media_file = Path(media_file)

        if not media_info_obj:
            raise MediaParsingError(f"Failed to parse {media_file}")

        self.media_label.setText(media_file.stem)
        self.media_label.setToolTip(media_file.stem)

        base_renamed_media = self.backend.media_renamer(
            media_file=media_file,
            source_file=source_file,
            mvr_token=self.config.cfg_payload.mvr_token,
            mvr_colon_replacement=self.config.cfg_payload.mvr_colon_replacement,
            media_search_payload=self.config.media_search_payload,
            media_info_obj=media_info_obj,
            source_file_mi_obj=self.config.media_input_payload.source_file_mi_obj,
            movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
        )
        if not base_renamed_media:
            raise FileNotFoundError("Failed to find input file for renamer")

        self.release_group_entry.setText(
            release_group_name if release_group_name else ""
        )

        self._input_ext = base_renamed_media.suffix
        self.output_entry.setText(base_renamed_media.stem.strip("."))
        self._auto_select_combos(base_renamed_media.stem.strip("."))

    def validatePage(self) -> bool:
        file_input = self.config.media_input_payload.encode_file
        if file_input:
            if not self._name_validations():
                return False
            if not self._release_group_validation():
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
                    self.edition_combo.currentText()
                )

            # update re release tokens
            self._re_release_reason_tokens_update()

            return True
        return False

    def _name_validations(self) -> bool:
        renamed_output_lowered = self.output_entry.text().lower()
        if "subbed" in renamed_output_lowered and "dubbed" in renamed_output_lowered:
            QMessageBox.warning(
                self, "Error", "Both 'Subbed' and 'Dubbed' should not be used together."
            )
            return False
        if "imax" in renamed_output_lowered and re.search(
            r"open[\s|\.]*matte", renamed_output_lowered, flags=re.IGNORECASE
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
                match = re.search(pattern, final_output_text, flags=re.IGNORECASE)
                if match:
                    self.config.jinja_engine.add_global(
                        global_name.replace("_reason", "_n"), match.group(1)
                    )
                # ensure only one combo box is processed
                break

    def injection_point(self) -> int:
        year_str = str(self.config.media_search_payload.year)
        try:
            return self.output_entry.text().rindex(year_str) + len(year_str) + 1
        except ValueError:
            return len(self.output_entry.text())

    @Slot(int)
    def update_generated_name(self, _e: int | None = None) -> None:
        """Update the generated name based on current selections."""
        current_name = self.output_entry.text()

        # gather formatting from all combo boxes
        selected_formatting = []
        for combo, info in self.combo_info_pairs:
            index = combo.currentIndex()

            if combo is self.edition_combo and combo.currentIndex() > 0:
                self.edition_combo_line_edit_last_text = None

            # reset re_release_combo if needed
            if (
                combo is self.re_release_combo
                and combo.currentIndex() != self.re_release_combo_last_index
            ):
                self._reset_re_release_reason_widgets()
                self.re_release_combo_last_index = combo.currentIndex()

            self._enable_re_release_widgets(combo)

            # remove formatting
            for entry in info:
                formatting = entry[2]
                current_name = re.sub(
                    re.escape(formatting), "", current_name, flags=re.IGNORECASE
                )

            # remove existing formatting for the currently selected index
            if index > 0:
                formatting = info[index - 1][2]
                current_name = re.sub(
                    re.escape(formatting), "", current_name, flags=re.IGNORECASE
                )
                selected_formatting.append(formatting)

        # determine the injection point
        inject_index = self.injection_point()

        # construct the new name with formatting injected at the correct position
        formatted_section = ".".join(selected_formatting)
        new_name = f"{current_name[:inject_index]}{formatted_section}{current_name[inject_index:]}"

        # remove extra dots if present
        new_name = re.sub(r"\.{2,}", ".", new_name).strip(".")

        # update the output entry
        self.output_entry.setText(new_name)

    @Slot()
    def manual_edition_edit(self) -> None:
        """Handle manual edition text changes, inserting it correctly in the name."""
        current_name = self.output_entry.text()
        if self.edition_combo_line_edit_last_text:
            current_name = current_name.replace(
                self.edition_combo_line_edit_last_text, "."
            )

        # get the current index of the combo box
        edition_idx = self.edition_combo.currentIndex()

        # remove any existing edition formatting if the combo box index is not 0 (i.e., it's not the default)
        if edition_idx > 0:
            formatting = self.EDITION_INFO[edition_idx - 1][2]
            current_name = re.sub(
                re.escape(formatting), "", current_name, flags=re.IGNORECASE
            )

        # find the correct injection point (this is where we insert the manual data)
        inject_index = self.injection_point()

        injection_string = re.sub(
            r"\s{1,}",
            ".",
            f"{self.edition_combo.currentText().strip().replace('.', '')}.",
        )
        self.edition_combo_line_edit_last_text = injection_string

        # if the combo box is at index 0, replace it with the manually entered data
        new_name = f"{current_name[:inject_index]}{injection_string}{current_name[inject_index:]}"

        # remove any extra periods that may arise
        new_name = re.sub(r"\.{2,}", ".", new_name).strip(".")

        # update the output entry with the newly generated name
        self.output_entry.setText(new_name)

    # @Slot(str)
    def _auto_select_combos(self, current_text: str) -> None:
        """
        Automatically checks and sets the combo boxes to the appropriate options
        based on substrings found in the provided current text.

        Args:
            current_text (str): The current name to analyze.
        """
        self._reset_re_release_reason_widgets()

        for combo, info in self.combo_info_pairs:
            if combo is self.edition_combo and self.edition_combo_line_edit_last_text:
                continue

            self._enable_re_release_widgets(combo)

            # default to 0 if no match is found
            matched_index = 0

            # start index at 1 (skip default)
            for idx, entry in enumerate(info, start=1):
                patterns = entry[1]
                for pattern in patterns:
                    if re.search(pattern, current_text, flags=re.IGNORECASE):
                        matched_index = idx
                        break
                if matched_index > 0:
                    break

            # set the combo box to the matched index
            combo.setCurrentIndex(matched_index)

            # update `re_release_combo_last_index`
            if combo is self.re_release_combo:
                self.re_release_combo_last_index = matched_index

    def _reset_re_release_reason_widgets(self) -> None:
        self.repack_reason_lbl.hide()
        self.proper_reason_lbl.hide()
        for widget in (self.repack_reason_combo, self.proper_reason_combo):
            widget.hide()
            widget.setCurrentIndex(0)
            widget.setPlaceholderText("Select Reason")

    def _enable_re_release_widgets(self, combo: CustomComboBox) -> None:
        if combo is self.re_release_combo:
            re_release_combo_text = combo.currentText().lower()
            if "repack" in re_release_combo_text:
                if (
                    self.repack_reason_lbl.isHidden()
                    and self.repack_reason_combo.isHidden()
                ):
                    self.repack_reason_lbl.show()
                    self.repack_reason_combo.show()
            elif "proper" in re_release_combo_text:
                if (
                    self.proper_reason_lbl.isHidden()
                    and self.proper_reason_combo.isHidden()
                ):
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
        self.edition_combo_line_edit_last_text = None
        self._reset_re_release_reason_widgets()
        self.release_group_entry.clear()
        self._input_ext = None
        self.output_entry.clear()

    @staticmethod
    def _update_combo_box(
        combobox: CustomComboBox,
        items: tuple,
    ) -> None:
        combobox.addItem("")
        for item in items:
            combobox.addItem(item[0])
