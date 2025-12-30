import re
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEventLoop, QSize, Qt, QTimer, Signal, Slot
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
from src.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from src.backend.tokens import FileToken, Tokens, TokenSelection, TokenType
from src.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
)
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.config.config import Config
from src.context.processing_context import ProcessingContext
from src.enums.rename import QualitySelection
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.rename_preview_dialog import RenamePreviewDialog
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.global_signals import GSigs
from src.frontend.utils import block_all_signals, build_h_line
from src.frontend.utils.general_worker import GeneralWorker
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.packages.custom_types import RenameNormalization
from src.payloads.episode_selection import EpisodeSelection

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class RenameEncodeSeries(BaseWizardPage):
    """Series rename wizard page with episode selection capabilities."""

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
        self, config: Config, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)
        self.setTitle("Series Rename")
        self.setObjectName("renameEncodeSeries")
        self.setCommitPage(True)

        self.config = config
        self.context = context
        self.backend = RenameEncodeSeriesBackEnd()
        self._input_ext: str | None = None
        self._token_window: QWidget | None = None
        self._overridden_tokens = set()
        self._current_episode_selection: EpisodeSelection | None = None
        self._current_episode_batch = None

        # rename loop vars
        self._rename_loop: QEventLoop | None = None
        self._rename_mapping: dict[Path, Path] | None = None
        self._updated_input_path: Path | None = None

        # Create main scroll area for the entire page
        main_scroll = QScrollArea(self)
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.Shape.NoFrame)

        main_widget = QWidget()
        main_scroll.setWidget(main_widget)

        main_layout = QVBoxLayout(main_widget)

        # Episode list section (shows count only)
        episode_list_group = QGroupBox("Episodes to Rename")
        episode_list_layout = QVBoxLayout(episode_list_group)

        self.episode_count_label = QLabel("No episodes loaded")
        episode_list_layout.addWidget(self.episode_count_label)

        # Options section (similar to movies but adapted for series)
        options_group_box = QGroupBox("Rename Options")
        options_group_box.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum
        )

        options_widget = QWidget(self)
        options_layout = QGridLayout(options_widget)
        options_layout.setColumnStretch(0, 1)
        options_layout.setColumnStretch(1, 1)
        options_layout.setColumnStretch(2, 1)
        options_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Edition, Frame Size, Localization combos (similar to movies)
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

        # Repack/Proper reason combos
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

        # Quality combo
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

        # REMUX/HYBRID checkboxes
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

        # Release group
        release_group_lbl = QLabel("Release Group", self)
        release_group_lbl.setToolTip(
            "Release group name (this requires the token {release_group} in the token string)"
        )
        self.release_group_entry = QLineEdit(self)
        self.release_group_entry.setToolTip(release_group_lbl.toolTip())
        self.release_group_entry.textEdited.connect(self.update_generated_name)

        # Token override section
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

        self.rename_token_control = SeriesRenameTokenControl(self)
        self.rename_token_control.row_modified.connect(self._update_override)

        # Override group
        self.override_group = QGroupBox(
            title="Override", parent=self, checkable=True, checked=False
        )
        self.override_group.toggled.connect(self._on_override_group_toggled)
        self.override_group.toggled.connect(self.update_generated_name)
        override_group_layout = QVBoxLayout(self.override_group)
        override_group_layout.addLayout(token_override_layout)
        override_group_layout.addWidget(self.token_override)
        override_group_layout.addWidget(self.rename_token_control)

        # Layout options widgets
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

        # Add all sections to main layout
        main_layout.addWidget(episode_list_group)
        main_layout.addWidget(options_group_box)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Set main scroll as the page layout
        page_layout = QVBoxLayout(self)
        page_layout.addWidget(main_scroll)

    def initializePage(self) -> None:
        """Initialize the page with series data and load episode batch."""
        self.context.media_input.has_basic_data()
        media_files = self.context.media_input.file_list
        release_group_name = self.config.cfg_payload.tvr_release_group

        if not media_files:
            raise FileNotFoundError("No files found in media input payload")

        # Display episode count only
        episode_count = len(media_files)
        self.episode_count_label.setText(
            f"Found {episode_count} episode{'s' if episode_count != 1 else ''} to rename"
        )

        # Pre-load attribute combos based on first file
        if media_files:
            first_file = Path(media_files[0])
            self._pre_load_attribute_combos(first_file.stem)

        # Use series token from config
        series_token = (
            self.config.cfg_payload.tvr_standard_episode_token
            or "{title_clean} - S{season_number:02d}E{episode_number:02d} - {episode_title_clean} [{resolution} {source} {video_codec} {audio_codec}]-{release_group}"
        )
        self.token_override.setText(series_token)

        # Detect quality from first file if available
        first_file_path = Path(media_files[0])
        comp_pair = self.context.media_input.comparison_pair
        get_quality = self.backend.get_quality(
            media_input=first_file_path,
            source_input=comp_pair.source if comp_pair else None,
        )
        if get_quality:
            quality_idx = self.quality_combo.findText(str(get_quality))
            if quality_idx > -1:
                self.quality_combo.setCurrentIndex(quality_idx)

        self.release_group_entry.setText(
            release_group_name if release_group_name else ""
        )

        # Initial call to update_generated_name will trigger preview generation
        self.update_generated_name()

    def validatePage(self) -> bool:
        """Validate the page and perform batch episode renaming."""
        media_files = self.context.media_input.file_list

        if not media_files:
            QMessageBox.warning(self, "Error", "No episodes found to rename.")
            return False

        if not self._name_validations() or not self._quality_validations():
            return False

        # Generate rename map for all episodes
        token = (
            self.token_override.text()
            if self.override_group.isChecked()
            else (
                self.config.cfg_payload.tvr_standard_episode_token
                or "{series_title_clean} - S{season_number:02d}E{episode_number:02d} - {episode_title_clean} [{resolution} {source} {video_codec} {audio_codec}]-{release_group}"
            )
        )

        # Get user tokens
        user_tokens = {
            k: v
            for k, (v, t) in self.config.cfg_payload.user_tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        }

        # Generate renames for each episode file

        if not self.context.media_input.series_episode_map:
            raise ValueError  # TODO: do a proper error here

        # TODO: iterate the map instead of the media files since it's already loaded at this point
        for (
            media_file,
            media_data,
        ) in self.context.media_input.series_episode_map.items():
            # for media_file_path in media_files:
            #     media_file = Path(media_file_path)

            # Get episode info from series_episode_map if available
            # episode_data = None
            # if self.context.media_input.series_episode_map:
            # TODO: check and toss error instead
            # episode_data = self.context.media_input.series_episode_map.get(
            #     media_file
            # )

            # Create EpisodeSelection from episode data or use defaults
            # if episode_data:
            #     episode_selection = EpisodeSelection(
            #         series_title=self.context.media_search.title or "Unknown",
            #         season_number=episode_data.get("season", 1),
            #         episode_number=episode_data.get("episode", 1),
            #         episode_title=episode_data.get("episode_name"),
            #         episode_air_date=episode_data.get("episode_data", {}).get("aired")
            #         if isinstance(episode_data.get("episode_data"), dict)
            #         else None,
            #     )
            # else:
            #     # Fallback: try to detect from filename
            #     match = re.search(r"s(\d+)e(\d+)", media_file.stem, re.I)
            #     if match:
            #         season = int(match.group(1))
            #         episode = int(match.group(2))
            #     else:
            #         season = 1
            #         episode = media_files.index(media_file_path) + 1

            #     episode_selection = EpisodeSelection(
            #         series_title=self.context.media_search.title or "Unknown",
            #         season_number=season,
            #         episode_number=episode,
            #     )

            # Generate rename for this episode
            renamed_file = self.backend.series_renamer(
                media_input_obj=self.context.media_input,
                # media_file=media_file,
                token=token,
                colon_replacement=self.config.cfg_payload.tvr_colon_replace_filename,
                media_search_payload=self.context.media_search,
                title_clean_rules=self.config.cfg_payload.title_clean_rules,
                video_dynamic_range=self.config.cfg_payload.video_dynamic_range,
                user_tokens=user_tokens,
                season_num=media_data["season"],
                episode_num=media_data["episode"],
                # episode_selection=episode_selection,
            )
            print(f"Renamed file: {renamed_file}")

            if renamed_file:
                # Get extension from original file
                ext = media_file.suffix
                renamed_output = media_file.parent / f"{renamed_file.stem}{ext}"
                self.context.media_input.file_list_rename_map[media_file] = (
                    renamed_output
                )

        # Check if there are any effective renames
        effective_renames = {
            src: trg
            for src, trg in self.context.media_input.file_list_rename_map.items()
            if src != trg
        }

        if not effective_renames:
            # No renames needed
            self.context.media_input.file_list_rename_map.clear()
        else:
            preview_dialog = RenamePreviewDialog(self)
            preview_dialog.set_renames(self.context.media_input.file_list_rename_map)

            if preview_dialog.exec() != QDialog.DialogCode.Accepted:
                return False

            # Execute the renames
            try:
                GSigs().main_window_set_disabled.emit(True)
                GSigs().main_window_update_status_tip.emit("Renaming episodes...", 0)

                # Start an event loop to wait for rename completion
                self._rename_loop = QEventLoop(self)

                worker = GeneralWorker(
                    func=RenameEncodeBackEnd.execute_renames,
                    parent=self,
                    file_list_rename_map=self.context.media_input.file_list_rename_map,
                    input_path=self.context.media_input.input_path,
                )
                worker.job_finished.connect(self._on_rename_response)
                worker.job_failed.connect(self._on_rename_failed)
                worker.start()

                # Wait for response
                self._rename_loop.exec()

                # Apply renames to payload
                if not self._rename_mapping:
                    return False

                # Update file_list with renamed paths
                for i, old_path in enumerate(self.context.media_input.file_list):
                    if old_path in self._rename_mapping:
                        self.context.media_input.file_list[i] = self._rename_mapping[
                            old_path
                        ]

                # Update file_list_mediainfo keys
                if self.context.media_input.file_list_mediainfo:
                    new_mediainfo = {}
                    for (
                        old_path,
                        mi_obj,
                    ) in self.context.media_input.file_list_mediainfo.items():
                        new_path = self._rename_mapping.get(old_path, old_path)
                        new_mediainfo[new_path] = mi_obj
                    self.context.media_input.file_list_mediainfo = new_mediainfo

                # Update series_episode_map keys if it exists
                if self.context.media_input.series_episode_map:
                    new_episode_map = {}
                    for (
                        old_path,
                        ep_data,
                    ) in self.context.media_input.series_episode_map.items():
                        new_path = self._rename_mapping.get(old_path, old_path)
                        new_episode_map[new_path] = ep_data
                    self.context.media_input.series_episode_map = new_episode_map

                # Update input_path if it changed
                if self._updated_input_path:
                    self.context.media_input.input_path = self._updated_input_path

                # Clear the rename map
                self.context.media_input.file_list_rename_map.clear()

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Rename Failed",
                    f"Failed to rename files:\n\n{str(e)}",
                )
                return False

            finally:
                GSigs().main_window_set_disabled.emit(False)
                GSigs().main_window_clear_status_tip.emit()
                self._rename_loop = None

        # Update config shared data with detected edition
        edition_combo_text = self.edition_combo.currentText()
        if edition_combo_text:
            self.context.shared_data.dynamic_data["edition_override"] = (
                edition_combo_text
            )

        # Update config shared data with frame size
        frame_size_text = self.frame_size_combo.currentText()
        if frame_size_text:
            self.context.shared_data.dynamic_data["frame_size_override"] = (
                frame_size_text
            )

        # Update config shared data with override tokens
        self.context.shared_data.dynamic_data["override_tokens"] = (
            self.backend.override_tokens
        )

        # Update re-release reason tokens
        self._re_release_reason_tokens_update()

        # Close token window
        self._close_token_window()

        super().validatePage()
        return True

    @Slot(tuple)
    def _on_rename_response(
        self, response: tuple[dict[Path, Path], Path | None]
    ) -> None:
        self._rename_mapping, self._updated_input_path = response
        if not self._rename_loop:
            raise RuntimeError("There was a critical error, runtime loop is missing")
        self._rename_loop.quit()

    @Slot(str)
    def _on_rename_failed(self, failure: str) -> None:
        QMessageBox.warning(self, "Error", failure)

    # All the methods from RenameEncode, adapted for series
    def _pre_load_attribute_combos(self, filename: str) -> None:
        """Pre-load combo boxes based on filename analysis."""

        def select_combo_by_regex(norm_list, combo):
            for item in norm_list:
                for pat in item.re_gex:
                    if re.search(pat, filename, flags=re.I):
                        idx = combo.findText(item.normalized)
                        if idx > -1:
                            combo.setCurrentIndex(idx)
                            return

        select_combo_by_regex(EDITION_INFO, self.edition_combo)
        select_combo_by_regex(FRAME_SIZE_INFO, self.frame_size_combo)
        select_combo_by_regex(LOCALIZATION_INFO, self.localization_combo)
        select_combo_by_regex(RE_RELEASE_INFO, self.re_release_combo)

    def _auto_check_remux_checkbox(self) -> None:
        """Auto-check REMUX checkbox if detected in filename."""
        if self.context.media_input.file_list:
            first_file = Path(self.context.media_input.file_list[0])
            if "remux" in first_file.stem.lower():
                self.remux_checkbox.setChecked(True)

    @Slot(bool)
    def _on_override_group_toggled(self, checked: bool) -> None:
        """Handle override group toggle."""
        if not checked:
            # Remove only the overridden tokens
            for k in self._overridden_tokens:
                self.backend.override_tokens.pop(k, None)
                self.context.shared_data.dynamic_data.get("override_tokens", {}).pop(
                    k, None
                )
            self._overridden_tokens.clear()
            self.update_generated_name()

    @Slot(tuple)
    def _update_override(self, data: tuple[str, str]) -> None:
        """Update override tokens."""
        self.backend.override_tokens[data[0]] = data[1]
        self._overridden_tokens.add(data[0])
        if data[0] == "release_group":
            self.release_group_entry.setText(data[1].lstrip("-"))
        self.update_generated_name()

    @Slot()
    def _see_tokens(self) -> None:
        """Show token preview dialog."""
        if self._token_window:
            return

        self._token_window = QDialog(
            parent=self, f=Qt.WindowType.Window, sizeGripEnabled=True, modal=False
        )
        self._token_window.setWindowTitle("Series Tokens")
        self._token_window.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        self._token_window.resize(self.geometry().size())
        self._token_window.finished.connect(self._close_token_window)

        user_tokens = [
            TokenType(f"{{{k}}}", "User Token")
            for k, (_, t) in self.config.cfg_payload.user_tokens.items()
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
        """Close token preview window."""
        if self._token_window:
            self._token_window.deleteLater()
        self._token_window = None

    def _name_validations(self) -> bool:
        """Validate the generated name using batch preview data."""
        # Since we no longer have a single output entry, we'll validate
        # based on general naming rules for the batch
        # For now, always return True - detailed validation happens in batch processing
        return True

    def _quality_validations(self) -> bool:
        """Validate quality selection."""
        cur_quality = (
            QualitySelection(self.quality_combo.currentText())
            if self.quality_combo.currentText()
            else None
        )
        if not cur_quality:
            return True
        elif cur_quality in {QualitySelection.DVD, QualitySelection.SDTV}:
            # Check first file's mediainfo
            first_file = self.context.media_input.require_first_file()
            mi_obj = self.context.media_input.file_list_mediainfo.get(first_file)
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
        """Update Jinja global variables for repack or proper reasons."""
        combo_to_global_map = {
            "repack_reason": (self.repack_reason_combo.currentText(), r"(repack\d*)"),
            "proper_reason": (self.proper_reason_combo.currentText(), r"(proper\d*)"),
        }

        # For batch processing, we'll update the global variables
        # The specific validation will happen during batch rename
        for global_name, (combo_text, pattern) in combo_to_global_map.items():
            if combo_text:
                self.config.jinja_engine.add_global(global_name, combo_text, True)
                # Store the pattern info for batch processing
                self.config.jinja_engine.add_global(
                    global_name.replace("_reason", "_pattern"), pattern, True
                )
                # Ensure only one combo box is processed
                break

    # Signal handlers for combo boxes
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

        # If not using DVD or Bluray disable REMUX
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

        # Update override
        self._update_override_tokens("source", cur_text, False if cur_text else True)

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
        """Update override tokens."""
        if remove or not v:
            self.backend.override_tokens.pop(k, None)
        else:
            self.backend.override_tokens[k] = v
        self.update_generated_name()

    @Slot(int)
    def update_generated_name(self, _: int | None = None) -> None:
        """Update the generated name based on current selections."""
        token = (
            self.config.cfg_payload.tvr_standard_episode_token
            or "{title_clean} - S{season_number}E{episode_number} - {episode_title_clean} [{resolution} {source} {video_codec} {audio_codec}]-{release_group}"
        )
        if self.override_group.isChecked():
            token = self.token_override.text()
        else:
            self.token_override.setText(token)

        # Treat release group as a pure override token
        release_group = self.release_group_entry.text().strip()
        if release_group:
            self.backend.override_tokens["release_group"] = release_group
        else:
            self.backend.override_tokens.pop("release_group", None)

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
        """Reset the page to default state."""
        block_all_signals(self, True)
        for combo_box in (
            self.edition_combo,
            self.frame_size_combo,
            self.localization_combo,
            self.re_release_combo,
        ):
            combo_box.setCurrentIndex(0)
        self._reset_re_release_reason_widgets()
        self.release_group_entry.clear()
        self.options_scroll_area.verticalScrollBar().setValue(0)
        self.override_group.setChecked(False)
        self.episode_count_label.setText("No episodes loaded")

        self._input_ext = None
        self._current_episode_selection = None
        self._current_episode_batch = None
        self._close_token_window()
        self._overridden_tokens.clear()

        self.backend.reset()
        block_all_signals(self, False)

    @staticmethod
    def _update_combo_box(
        combobox: CustomComboBox,
        items: Sequence[RenameNormalization],
    ) -> None:
        """Update combo box with items."""
        combobox.addItem("")
        for item in items:
            combobox.addItem(item.normalized)


class SeriesRenameTokenControl(QWidget):
    """Token control widget specifically for series rename operations."""

    row_modified = Signal(tuple)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        desc = QLabel(
            """\
            <br>
            <span style="font-style: italic; font-size: smaller;"><strong>Note:</strong> Modifying the tokens 
            below will only update corresponding <strong>title</strong> tokens (global/per tracker) if they share 
            the same token. Series-specific tokens like season_number and episode_number are highlighted.</span>""",
            self,
            wordWrap=True,
        )

        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Search tokens...")
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
        """Populate the table with token data."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.clearContents()
        self.table.setRowCount(len(tokens))

        series_tokens = {
            "season_number",
            "episode_number",
            "episode_title",
            "episode_number_absolute",
            "air_date",
            "end_episode_number",
        }

        for idx, (token, value) in enumerate(tokens.items()):
            # Build token item
            token_item = QTableWidgetItem(f"{{{token}}}")
            token_item.setFlags(
                token_item.flags()
                & ~Qt.ItemFlag.ItemIsEditable
                & ~Qt.ItemFlag.ItemIsSelectable
            )

            # Highlight series-specific tokens
            if token in series_tokens:
                token_item.setBackground(Qt.GlobalColor.cyan)

            self.table.setItem(idx, 0, token_item)

            # Build editable item
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
        """Setup table display properties."""
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setAutoScroll(False)

    @Slot(QTableWidgetItem)
    def _item_changed(self, item: QTableWidgetItem) -> None:
        """Handle item changes."""
        token = self.table.item(item.row(), 0)
        if token and item:
            QTimer.singleShot(
                1,
                partial(
                    self.row_modified.emit, (token.text().strip("{}"), item.text())
                ),
            )

    def get_token_values(self) -> dict:
        """Return a dict of token: value."""
        values = {}
        for row in range(self.table.rowCount()):
            token = self.table.item(row, 0)
            value = self.table.item(row, 1)
            if token is not None and value is not None:
                values[token.text()] = value.text()
        return values

    @Slot(str)
    def filter_table(self, text: str) -> None:
        """Filter table rows based on search text."""
        for row in range(self.table.rowCount()):
            match = False
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                if item and text.lower() in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(row, not match)

    def reset(self) -> None:
        """Reset the table."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.clearContents()
        self.table.setAutoScroll(False)
