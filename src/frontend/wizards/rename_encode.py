from collections.abc import Sequence
from functools import partial
import re
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.rename_encode import RenameEncodeBackEnd
from src.backend.rename_files import RenamePlan, RenameResult
from src.backend.tokens import FileToken, Tokens, TokenSelection, TokenType
from src.backend.utils.filename_claims import FilenameClaims, detect_filename_claims
from src.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
    is_imax,
)
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.backend.utils.streaming_services import (
    STREAMING_SERVICE_CHOICES,
)
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.rename import QualitySelection
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.rename_preview_dialog import RenamePreviewDialog
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.global_signals import GSigs
from src.frontend.utils import build_h_line
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.utils.rename_operation import RenameOperationController
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

    def __init__(
        self, config: ConfigManager, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)
        self.setTitle("Rename")
        self.setObjectName("renameEncode")
        self.setCommitPage(True)

        self.config = config
        self.context = context
        self.backend = RenameEncodeBackEnd(
            context.flat_filters,
            context.custom_edition_info,
            context.custom_cut_names,
        )
        self._input_ext: str | None = None
        self._token_window: QWidget | None = None
        self._overridden_tokens: set[str] = set()

        self._rename_operation = RenameOperationController(self)
        self._rename_operation.completed.connect(self._on_rename_completed)
        self._advance_after_rename = False

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

        options_widget = QWidget(self)
        options_layout = QGridLayout(options_widget)
        options_layout.setColumnStretch(0, 1)
        options_layout.setColumnStretch(1, 1)
        options_layout.setColumnStretch(2, 1)
        options_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        edition_lbl = QLabel("Edition", self)
        self.edition_combo = CustomComboBox(
            completer=True,
            completer_strict=False,
            disable_mouse_wheel=True,
            parent=self,
        )
        self._update_combo_box(self.edition_combo, EDITION_INFO)
        self.edition_combo.currentIndexChanged.connect(self._update_edition_combo)
        edition_combo_line_edit = self.edition_combo.lineEdit()
        if not edition_combo_line_edit:
            raise AttributeError("Could not detect edition_combo.lineEdit()")
        edition_combo_line_edit.editingFinished.connect(self._update_edition_combo)

        frame_size_lbl = QLabel("Frame Size", self)
        self.frame_size_combo = CustomComboBox(disable_mouse_wheel=True, parent=self)
        self._update_combo_box(self.frame_size_combo, FRAME_SIZE_INFO)
        self.frame_size_combo.currentIndexChanged.connect(self._update_frame_size_combo)

        localization_lbl = QLabel("Localization", self)
        self.localization_combo = CustomComboBox(disable_mouse_wheel=True, parent=self)
        self._update_combo_box(self.localization_combo, LOCALIZATION_INFO)
        self.localization_combo.currentIndexChanged.connect(
            self._update_localization_combo
        )

        re_release_lbl = QLabel("Rerelease", self)
        self.re_release_combo = CustomComboBox(disable_mouse_wheel=True, parent=self)
        self._update_combo_box(self.re_release_combo, RE_RELEASE_INFO)
        self.re_release_combo.currentIndexChanged.connect(self._update_re_release_combo)

        self.repack_reason_lbl = QLabel("Repack Reason", self)
        self.repack_reason_combo = CustomComboBox(
            completer=True,
            completer_strict=False,
            disable_mouse_wheel=True,
            parent=self,
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
            completer=True,
            completer_strict=False,
            disable_mouse_wheel=True,
            parent=self,
        )
        self.proper_reason_combo.setSizeAdjustPolicy(
            CustomComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.proper_reason_combo.addItems(self.PROPER_REASONS)
        proper_reason_combo_line_edit = self.proper_reason_combo.lineEdit()
        if not proper_reason_combo_line_edit:
            raise AttributeError(
                "Could not detect proper_reason_combo_line_edit.lineEdit()"
            )
        proper_reason_combo_line_edit.setPlaceholderText(self.REASON_STR)
        self.proper_reason_lbl.hide()
        self.proper_reason_combo.hide()

        quality_combo_lbl = QLabel("Quality", self)
        self.quality_combo = CustomComboBox(
            completer=True,
            completer_strict=True,
            disable_mouse_wheel=True,
            parent=self,
        )
        self.quality_combo.addItem("")
        self.quality_combo.addItems([str(q) for q in QualitySelection])
        self.quality_combo.currentIndexChanged.connect(self._update_quality_combo)

        service_combo_lbl = QLabel("Service", self)
        self.service_combo = CustomComboBox(
            completer=True,
            completer_strict=True,
            disable_mouse_wheel=True,
            parent=self,
        )
        self.service_combo.setToolTip(
            "Streaming service abbreviation, for web sources "
            "(Aither and LST require it)"
        )
        self.service_combo.addItem("")
        self.service_combo.addItems(STREAMING_SERVICE_CHOICES)
        self.service_combo.currentIndexChanged.connect(self._update_service_combo)

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

        release_group_lbl = QLabel("Release Group", self)
        release_group_lbl.setToolTip(
            "Release group name (this requires the token {release_group} in the token string)"
        )
        self.release_group_entry = QLineEdit(self)
        self.release_group_entry.setToolTip(release_group_lbl.toolTip())
        self.release_group_entry.textEdited.connect(self.update_generated_name)

        token_override_lbl = QLabel("Override File Name Tokens", self)
        view_tokens_popup_btn = QToolButton(self)
        QTAThemeSwap().register(
            view_tokens_popup_btn, "ph.eye-light", icon_size=QSize(20, 20)
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

        self.rename_token_control = RenameTokenControl(self)
        self.rename_token_control.row_modified.connect(self._update_override)

        self.override_group = QGroupBox(
            title="Override", parent=self, checkable=True, checked=False
        )
        self.override_group.toggled.connect(self._on_override_group_toggled)
        self.override_group.toggled.connect(self.update_generated_name)
        override_group_layout = QVBoxLayout(self.override_group)
        override_group_layout.addLayout(token_override_layout)
        override_group_layout.addWidget(self.token_override)
        override_group_layout.addWidget(self.rename_token_control)

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
        options_layout.addWidget(quality_combo_lbl, 4, 0)
        options_layout.addWidget(self.quality_combo, 5, 0)
        options_layout.addWidget(service_combo_lbl, 4, 1)
        options_layout.addWidget(self.service_combo, 5, 1)
        options_layout.addLayout(checkboxes_layout, 6, 0, 1, 1)
        options_layout.addWidget(build_h_line((6, 4, 6, 4)), 18, 0, 1, 3)
        options_layout.addWidget(release_group_lbl, 19, 0)
        options_layout.addWidget(self.release_group_entry, 20, 0, 1, 3)
        options_layout.addWidget(build_h_line((6, 4, 6, 4)), 21, 0, 1, 3)
        options_layout.addWidget(self.override_group, 22, 0, 1, 3)

        self.options_scroll_area = QScrollArea(self, widgetResizable=True)
        self.options_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.options_scroll_area.setWidget(options_widget)

        group_box_layout = QVBoxLayout(options_group_box)
        group_box_layout.setContentsMargins(0, 0, 0, 0)
        group_box_layout.addWidget(self.options_scroll_area)

        output_group_box = QGroupBox("Output")
        output_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )
        output_layout = QVBoxLayout(output_group_box)
        self.output_entry = QLineEdit()
        self.output_entry.setToolTip("Suggested name, updates automatically")
        self.output_entry.setReadOnly(True)

        output_layout.addWidget(self.output_entry)

        layout = QVBoxLayout(self)
        layout.addWidget(input_group_box)
        layout.addWidget(options_group_box)
        layout.addWidget(output_group_box)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def initializePage(self) -> None:
        # this is a movie so there's only ever 1 to rename, grab it with index 0
        media_file = self.context.media_input.file_list[0]
        release_group_name = self.config.settings.movie.release_group

        self.media_label.setText(media_file.stem)
        self.media_label.setToolTip(media_file.stem)

        claims = self._pre_load_attribute_combos(media_file.stem)

        # apply localization override from plugin if present # TODO: handle all potential overrides later
        localization_override = self.context.shared_data.dynamic_data.get(
            "localization_override"
        )
        if localization_override:
            localization_idx = self.localization_combo.findText(localization_override)
            if localization_idx > -1:
                self.localization_combo.setCurrentIndex(localization_idx)

        self.token_override.setText(self.config.settings.movie.filename_token)

        comp_pair = self.context.media_input.comparison_pair
        get_quality = self.backend.get_quality(
            media_input=media_file, source_input=comp_pair.source if comp_pair else None
        )
        if get_quality:
            quality_idx = self.quality_combo.findText(get_quality)
            if quality_idx > -1:
                self.quality_combo.setCurrentIndex(quality_idx)

        # The settings value means "my group"; the detected one means
        # "whoever made the source file". Configured wins, but a blank
        # setting must not leave the field empty while the output silently
        # carries the detected group -- that is the invisible claim this
        # design removes everywhere else.
        self.release_group_entry.setText(release_group_name or claims.release_group)

        self.update_generated_name()

    def validatePage(self) -> bool:
        if self._advance_after_rename:
            self._advance_after_rename = False
            return self._complete_validation()
        if self._rename_operation.is_running:
            return False

        file_input = self.context.media_input.file_list[0]
        if file_input:
            if not self._name_validations() or not self._quality_validations():
                return False
            output_name = self.output_entry.text().strip()
            renamed_output = file_input.parent / f"{output_name}{file_input.suffix}"
            rename_map = {file_input: renamed_output}

            # if user opened a folder (not a single file), rename the folder to match the movie
            if (
                self.context.media_input.input_path
                and self.context.media_input.input_path.is_dir()
                and file_input.parent == self.context.media_input.input_path
            ):
                # rename folder to match the renamed file's stem
                old_folder = file_input.parent
                new_folder = old_folder.parent / self.output_entry.text().strip()

                # update the renamed_output to be in the new folder
                renamed_output = new_folder / f"{output_name}{file_input.suffix}"
                rename_map[file_input] = renamed_output

            # determine if there are any effective renames (source != target).
            effective_renames = {
                src: trg
                for src, trg in rename_map.items()
                if str(src.absolute()) != str(trg.absolute())
            }

            # If there are no actual renames, skip the preview and worker.
            if not effective_renames:
                return self._complete_validation()

            try:
                plan = RenamePlan.build(
                    effective_renames,
                    self.context.media_input.input_path,
                )
            except ValueError as error:
                QMessageBox.warning(self, "Invalid Rename", str(error))
                return False

            preview_dialog = RenamePreviewDialog(self)
            preview_dialog.set_renames(plan.file_targets)
            if preview_dialog.exec() != QDialog.DialogCode.Accepted:
                return False

            self._rename_operation.start(plan, "Renaming media...")
            return False
        return False

    @Slot(object)
    def _on_rename_completed(self, result: object) -> None:
        if not isinstance(result, RenameResult):
            QMessageBox.critical(
                self, "Rename Failed", "The rename operation returned invalid data."
            )
            return

        current_input = self.context.media_input.input_path
        if result.path_mapping or result.updated_input_path != current_input:
            self.context.media_input.apply_rename_mapping(
                result.path_mapping,
                result.updated_input_path,
            )

        if not result.success:
            message = result.message or "The rename operation failed."
            if result.rollback_complete:
                QMessageBox.warning(self, "Rename Failed", message)
            else:
                QMessageBox.critical(self, "Rename Requires Attention", message)
            return

        try:
            self.context.media_input.require_existing_media_paths(
                include_comparison=True
            )
        except (FileNotFoundError, RuntimeError) as error:
            QMessageBox.critical(
                self,
                "Rename Verification Failed",
                f"The files were renamed, but the updated media paths could not "
                f"be verified:\n\n{error}",
            )
            return

        self._advance_after_rename = True
        GSigs().wizard_next.emit()

    def _complete_validation(self) -> bool:
        try:
            self.context.media_input.require_existing_media_paths(
                include_comparison=True
            )
        except (FileNotFoundError, RuntimeError) as error:
            QMessageBox.warning(self, "Media Files Unavailable", str(error))
            return False

        edition_combo_text = self.edition_combo.currentText()
        if edition_combo_text:
            self.context.shared_data.dynamic_data["edition_override"] = (
                edition_combo_text
            )

        frame_size_text = self.frame_size_combo.currentText()
        if frame_size_text:
            self.context.shared_data.dynamic_data["frame_size_override"] = (
                frame_size_text
            )

        self.context.shared_data.dynamic_data["override_tokens"] = (
            self.backend.override_tokens
        )
        self._re_release_reason_tokens_update()
        self._close_token_window()
        super().validatePage()
        return True

    def _pre_load_attribute_combos(self, filename: str) -> FilenameClaims:
        """Pre-fill the claim controls from stage 1, and return what it found.

        The detection itself lives in `detect_filename_claims`, which the
        settings preview also calls, so what this page shows and what the
        preview shows cannot diverge. Everything here is presentation.

        Preselecting the streaming service changes no output -- the token
        detects it independently. It makes the detection visible, which is
        the only way a user can tell it read the release wrong and correct
        it before uploading to a tracker that requires the abbreviation.

        The claims come back so the caller can reuse them without detecting
        twice -- the release group seed needs the same result.
        """
        claims = detect_filename_claims(
            [filename], self.config.settings.movie.claims
        )

        for combo, value in (
            (self.edition_combo, claims.edition),
            (self.frame_size_combo, claims.frame_size),
            (self.localization_combo, claims.localization),
            (self.re_release_combo, claims.re_release),
            (self.service_combo, claims.streaming_service),
        ):
            idx = combo.findText(value)
            combo.setCurrentIndex(idx if idx > -1 else 0)

        self.remux_checkbox.setChecked(bool(claims.remux))
        self.hybrid_checkbox.setChecked(bool(claims.hybrid))
        return claims

    def _detected_claims(self) -> FilenameClaims:
        return detect_filename_claims(
            [path.stem for path in self.context.media_input.file_list],
            self.config.settings.movie.claims,
        )

    def _auto_check_remux_checkbox(self) -> None:
        """Re-apply the detected REMUX claim.

        Called when the quality combo moves to a disc source, which
        re-enables the checkbox after a non-disc quality forced it off.
        Goes through the same detector as the initial pre-fill, so a
        switched-off REMUX category stays off.
        """
        self.remux_checkbox.setChecked(bool(self._detected_claims().remux))

    @Slot(bool)
    def _on_override_group_toggled(self, checked: bool) -> None:
        if not checked:
            # remove only the overridden tokens
            for k in self._overridden_tokens:
                self.backend.override_tokens.pop(k, None)
                self.context.shared_data.dynamic_data.get("override_tokens", {}).pop(
                    k, None
                )
            self._overridden_tokens.clear()
            self.update_generated_name()

    @Slot(tuple)
    def _update_override(self, data: tuple[str, str]) -> None:
        self.backend.override_tokens[data[0]] = data[1]
        self._overridden_tokens.add(data[0])
        if data[0] == "release_group":
            self.release_group_entry.setText(data[1].lstrip("-"))
        self.update_generated_name()

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

        user_tokens = [
            TokenType(f"{{{k}}}", "User Token")
            for k, (_, t) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        ]

        token_widget = TokenTable(
            tokens=sorted(Tokens().get_token_objects(FileToken)) + user_tokens,
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
        output_name = self.output_entry.text().strip()
        if not output_name:
            QMessageBox.warning(
                self,
                "Invalid Rename",
                "The generated filename is empty. Choose a token template that "
                "produces a filename before continuing.",
            )
            return False
        if self._input_ext is None:
            QMessageBox.warning(
                self,
                "Invalid Rename",
                "A valid filename could not be generated from the selected media.",
            )
            return False
        if not self.context.media_input.file_list[0].suffix:
            QMessageBox.warning(
                self,
                "Invalid Rename",
                "The input media has no file extension to preserve.",
            )
            return False

        renamed_output_lowered = output_name.lower()
        if "subbed" in renamed_output_lowered and "dubbed" in renamed_output_lowered:
            QMessageBox.warning(
                self, "Error", "Both 'Subbed' and 'Dubbed' should not be used together."
            )
            return False
        if is_imax(renamed_output_lowered) and re.search(
            r"open[\s|\.]*matte", renamed_output_lowered, flags=re.I
        ):
            QMessageBox.warning(
                self,
                "Error",
                "Both 'IMAX' and 'Open Matte' should not be used together.",
            )
            return False
        return True

    def _quality_validations(self) -> bool:
        cur_quality = (
            QualitySelection(self.quality_combo.currentText())
            if self.quality_combo.currentText()
            else None
        )
        if not cur_quality:
            return True
        elif cur_quality in {QualitySelection.DVD, QualitySelection.SDTV}:
            first_file = self.context.media_input.require_first_file()
            mi_obj = (
                self.context.media_input.file_list_mediainfo.get(first_file)
                if self.context.media_input.file_list_mediainfo
                else None
            )
            if not mi_obj:
                raise FileNotFoundError("Failed to parse MediaInfo")
            detect_resolution = VideoResolutionAnalyzer(mi_obj).get_resolution(
                remove_scan=True
            )
            if detect_resolution:
                if int(detect_resolution) > 576:
                    QMessageBox.warning(
                        self,
                        "Error",
                        f"Cannot utilize quality {cur_quality} with a resolution above 576p.",
                    )
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
                self.context.jinja_engine.add_global(global_name, combo_text, True)
                match = re.search(pattern, final_output_text, flags=re.I)
                if match:
                    self.context.jinja_engine.add_global(
                        global_name.replace("_reason", "_n"), match.group(1), True
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
    def _update_quality_combo(self, _: int) -> None:
        cur_text = self.quality_combo.currentText()

        # if not using dvd or bluray disable REMUX
        if cur_text:
            if QualitySelection(cur_text) not in {
                QualitySelection.DVD,
                QualitySelection.BLURAY,
                QualitySelection.UHD_BLURAY,
            }:
                self.remux_checkbox.setChecked(False)
                self.remux_checkbox.setEnabled(False)
            else:
                self.remux_checkbox.setEnabled(True)
                self._auto_check_remux_checkbox()

        self._sync_service_combo_to_quality(cur_text)

        # update override
        self._update_override_tokens("source", cur_text, False if cur_text else True)

    def _sync_service_combo_to_quality(self, quality_text: str) -> None:
        """Only a web source can carry a streaming service.

        The same rule the token applies, surfaced in the UI: switching a
        release to BluRay clears and disables Service rather than leaving a
        stale "AMZN" selected next to a disc source.
        """
        if not quality_text:
            self.service_combo.setEnabled(True)
            return

        is_web = QualitySelection(quality_text) in {
            QualitySelection.WEB_DL,
            QualitySelection.WEB_RIP,
        }
        if not is_web:
            self.service_combo.setCurrentIndex(0)
        self.service_combo.setEnabled(is_web)

    @Slot(int)
    def _update_service_combo(self, _: int) -> None:
        self._update_override_tokens(
            "streaming_service", self.service_combo.currentText()
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

        token = self.config.settings.movie.filename_token
        if self.override_group.isChecked():
            token = self.token_override.text()
        else:
            self.token_override.setText(token)

        # treat release group as a pure override token
        release_group = self.release_group_entry.text().strip()
        if release_group:
            self.backend.override_tokens["release_group"] = release_group
        else:
            self.backend.override_tokens.pop("release_group", None)

        user_tokens = {
            k: v
            for k, (v, t) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        }

        get_file_name = self.backend.media_renamer(
            media_input_obj=self.context.media_input,
            mvr_token=token,
            mvr_colon_replacement=self.config.settings.movie.filename_colon_replace,
            media_search_payload=self.context.media_search,
            title_clean_rules=self.config.settings.global_management.title_clean_rules,
            video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
            user_tokens=user_tokens,
        )

        if get_file_name and self.backend.token_replacer:
            # update rename token control
            sort_token_order = re.findall(
                r"\{(?:[:][^:}]+:)*([a-z_]+)(?:[:][^:}]+:)*\}", token
            )
            sort_token_data = self.backend.token_replacer.token_data.get_dict()  # pyright: ignore[reportAttributeAccessIssue]
            sorted_token_data = {
                k: sort_token_data[k]
                for k in sort_token_order
                if k in sort_token_data and sort_token_data[k]
            }
            self.rename_token_control.populate_table(sorted_token_data)

            # update entries
            self._input_ext = get_file_name.suffix
            self.output_entry.setText(str(get_file_name.with_suffix("")))
        else:
            self._input_ext = None
            self.output_entry.clear()

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

    @staticmethod
    def _update_combo_box(
        combobox: CustomComboBox,
        items: Sequence[RenameNormalization],
    ) -> None:
        combobox.addItem("")
        for item in items:
            combobox.addItem(item.normalized)


class RenameTokenControl(QWidget):
    row_modified = Signal(tuple)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        desc = QLabel(
            """\
            <br>
            <span style="font-style: italic; font-size: smaller;"><strong>Note:</strong> Modifying the tokens 
            below will only update corresponding <strong>title</strong> tokens (global/per tracker) if they share 
            the same token.</span>""",
            self,
            wordWrap=True,
        )

        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.textChanged.connect(self.filter_table)

        self.table = QTableWidget(self)
        self.table.setColumnCount(2)
        self.table.setMinimumHeight(180)
        self.table.setHorizontalHeaderLabels(("Token", "Value (click to edit)"))
        self.table.setFrameShape(QFrame.Shape.Box)
        self.table.setFrameShadow(QFrame.Shadow.Sunken)
        self.table.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.table.itemChanged.connect(self._item_changed)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(desc)
        self.main_layout.addWidget(self.search_bar)
        self.main_layout.addWidget(self.table)

    def populate_table(self, tokens: dict[str, Any]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.clearContents()
        self.table.setRowCount(len(tokens))

        for idx, (token, value) in enumerate(tokens.items()):
            # build token item
            token_item = QTableWidgetItem(f"{{{token}}}")
            token_item.setFlags(
                token_item.flags()
                & ~Qt.ItemFlag.ItemIsEditable
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            self.table.setItem(idx, 0, token_item)

            # build editable item
            item = QTableWidgetItem(value)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
            )
            self.table.setItem(idx, 1, item)

        self.setup_table_properties()
        self.table.blockSignals(False)

    def setup_table_properties(self) -> None:
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setAutoScroll(False)

    @Slot(QTableWidgetItem)
    def _item_changed(self, item: QTableWidgetItem) -> None:
        token = self.table.item(item.row(), 0)
        if token and item:
            QTimer.singleShot(
                1,
                partial(
                    self.row_modified.emit, (token.text().strip("{}"), item.text())
                ),
            )

    def get_token_values(self) -> dict[str, str]:
        """Return a dict of token: value"""
        values: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            token = self.table.item(row, 0)
            value = self.table.item(row, 1)
            if token is not None and value is not None:
                values[token.text()] = value.text()
        return values

    @Slot(str)
    def filter_table(self, text: str) -> None:
        for row in range(self.table.rowCount()):
            match = False
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item and text.lower() in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(row, not match)
