from collections.abc import Sequence
from functools import partial
from pathlib import Path
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
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.rename_encode_series import RenameEncodeSeriesBackEnd
from src.backend.rename_files import RenamePlan, RenameResult
from src.backend.tokens import FileToken, Tokens, TokenSelection, TokenType
from src.backend.utils.filename_claims import (
    PER_FILE_CLAIM_KEYS,
    FilenameClaims,
    detect_file_claims,
    detect_filename_claims,
)
from src.backend.utils.media_files import find_sidecars_for
from src.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
)
from src.backend.utils.resolution import VideoResolutionAnalyzer
from src.backend.utils.streaming_services import (
    STREAMING_SERVICE_CHOICES,
)
from src.config.config import ConfigManager
from src.config.tv_tokens import (
    get_tvr_episode_token,
    resolve_season_subfolder_token,
)
from src.context.processing_context import ProcessingContext
from src.enums.rename import QualitySelection
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.episode_claims_table import EpisodeClaimsTable
from src.frontend.custom_widgets.rename_preview_dialog import RenamePreviewDialog
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.global_signals import GSigs
from src.frontend.utils import apply_plugin_override, build_h_line
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.utils.rename_operation import RenameOperationController
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.packages.custom_types import RenameNormalization
from src.payloads.series import build_series_release_info

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
        self, config: ConfigManager, context: ProcessingContext, parent: "MainWindow"
    ) -> None:
        super().__init__(config, context, parent)
        self.setTitle("Series Rename")
        self.setObjectName("renameEncodeSeries")
        self.setCommitPage(True)

        self.config = config
        self.context = context
        self.backend = RenameEncodeSeriesBackEnd(
            context.flat_filters,
            context.custom_edition_info,
            context.custom_cut_names,
        )
        self._token_window: QWidget | None = None
        self._overridden_tokens: set[str] = set()

        self._rename_operation = RenameOperationController(self)
        self._rename_operation.completed.connect(self._on_rename_completed)
        self._advance_after_rename = False

        # Create main scroll area for the entire page
        main_scroll = QScrollArea(self)
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.Shape.NoFrame)

        main_widget = QWidget()
        main_scroll.setWidget(main_widget)

        main_layout = QVBoxLayout(main_widget)

        # The episode half of the release. Built before the pack controls
        # below, because each of those carries a menu that acts on it.
        episode_list_group = QGroupBox("Episodes (filenames)")
        episode_list_layout = QVBoxLayout(episode_list_group)

        self.episode_claims = EpisodeClaimsTable(
            context.custom_edition_info, parent=self
        )
        self.episode_claims.claims_changed.connect(self.update_generated_name)
        episode_list_layout.addWidget(self.episode_claims)

        # The pack half. These drive the folder, the torrent and the release
        # title, and nothing here reaches an episode filename.
        options_group_box = QGroupBox("Pack (folder, torrent, release title)")
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
        checkboxes_layout.addWidget(self._bulk_button("remux"))
        checkboxes_layout.addWidget(self.hybrid_checkbox)
        checkboxes_layout.addWidget(self._bulk_button("hybrid"))
        checkboxes_layout.addStretch(1)

        # Release group
        release_group_lbl = QLabel("Release Group", self)
        release_group_lbl.setToolTip(
            "The group name on your output. Pre-filled from Settings > General, "
            "or from the input filenames when release group parsing is on. "
            "Clearing it publishes this release with no group."
        )
        self.release_group_entry = QLineEdit(self)
        self.release_group_entry.setToolTip(release_group_lbl.toolTip())
        self.release_group_entry.setPlaceholderText("No group tag")
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
        options_layout.addLayout(self._claim_row(self.edition_combo, "edition"), 1, 0)
        options_layout.addWidget(frame_size_lbl, 0, 1)
        options_layout.addLayout(
            self._claim_row(self.frame_size_combo, "frame_size"), 1, 1
        )
        options_layout.addWidget(localization_lbl, 0, 2)
        options_layout.addLayout(
            self._claim_row(self.localization_combo, "localization"), 1, 2
        )
        options_layout.addWidget(re_release_lbl, 2, 0)
        options_layout.addLayout(
            self._claim_row(self.re_release_combo, "re_release"), 3, 0
        )
        options_layout.addWidget(self.repack_reason_lbl, 2, 1)
        options_layout.addWidget(self.repack_reason_combo, 3, 1, 1, 2)
        options_layout.addWidget(self.proper_reason_lbl, 2, 1)
        options_layout.addWidget(self.proper_reason_combo, 3, 1, 1, 2)
        options_layout.addWidget(quality_combo_lbl, 4, 0)
        options_layout.addWidget(self.quality_combo, 5, 0)
        options_layout.addWidget(service_combo_lbl, 4, 1)
        options_layout.addLayout(
            self._claim_row(self.service_combo, "streaming_service"), 5, 1
        )
        options_layout.addLayout(checkboxes_layout, 6, 0, 1, 1)
        options_layout.addWidget(build_h_line((6, 4, 6, 4)), 18, 0, 1, 3)
        options_layout.addWidget(release_group_lbl, 19, 0)
        options_layout.addWidget(self.release_group_entry, 20, 0, 1, 3)
        options_layout.addWidget(build_h_line((6, 4, 6, 4)), 21, 0, 1, 3)
        options_layout.addWidget(self.override_group, 22, 0, 1, 3)

        self.options_scroll_area = QScrollArea(self, widgetResizable=True)
        self.options_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.options_scroll_area.setWidget(options_widget)

        # The pack's controls produce one string and nothing on this page
        # showed it. Cheap to render, unlike the episode names: one call
        # against the folder token rather than one per episode.
        pack_name_lbl = QLabel("Pack Name", self)
        pack_name_lbl.setToolTip(
            "The renamed folder, which the .torrent is also named after"
        )
        self.pack_name_preview = QLineEdit(self)
        self.pack_name_preview.setReadOnly(True)
        self.pack_name_preview.setPlaceholderText("No pack name generated")
        self.pack_name_preview.setToolTip(pack_name_lbl.toolTip())

        group_box_layout = QVBoxLayout(options_group_box)
        group_box_layout.setContentsMargins(0, 0, 0, 0)
        group_box_layout.addWidget(pack_name_lbl)
        group_box_layout.addWidget(self.pack_name_preview)
        group_box_layout.addWidget(self.options_scroll_area)

        # Add all sections to main layout
        main_layout.addWidget(episode_list_group)
        main_layout.addWidget(options_group_box)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Set main scroll as the page layout
        page_layout = QVBoxLayout(self)
        page_layout.addWidget(main_scroll)

    # -- pack controls acting on the episode table ---------------------
    def _claim_row(self, control: QWidget, key: str) -> QHBoxLayout:
        """A pack control paired with the menu that reaches the episodes.

        The menu sits here rather than on the table's column header because
        both its actions need a pack value to work from: "apply to all"
        copies this control, and the control is what the user has just set
        when they reach for it.
        """
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(control)
        layout.addWidget(self._bulk_button(key))
        return layout

    def _bulk_button(self, key: str) -> QToolButton:
        """The menu that lets a pack control reach every episode.

        The two surfaces are otherwise independent, which makes the common
        case -- the whole release is a REPACK -- one edit per episode. This
        is the shortcut, and the way back from it.
        """
        button = QToolButton(self)
        button.setText("...")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolTip("Apply this to every episode, or undo doing so")
        menu = QMenu(button)
        menu.addAction("Apply to all episodes", partial(self._apply_claim_to_all, key))
        menu.addAction(
            "Revert episodes to detected",
            partial(self.episode_claims.revert_to_detected, key),
        )
        button.setMenu(menu)
        return button

    def _apply_claim_to_all(self, key: str) -> None:
        """Copy the pack's answer for `key` onto every episode.

        Read from `override_tokens` rather than from the widgets. Every
        claim control already writes its value there through
        `_update_override_tokens`, so asking the widgets again would be a
        second answer to the same question, free to drift from the first.
        An absent key means the control is empty, which applies as a
        deliberate blank.
        """
        self.episode_claims.apply_to_all(key, self.backend.override_tokens.get(key, ""))

    def initializePage(self) -> None:
        """Initialize the page with series data and load episode batch."""
        media_files = self.context.media_input.file_list
        release_group_name = self.config.settings.general.release_group

        if not media_files:
            raise FileNotFoundError("No files found in media input payload")

        # The pack controls still read the pack: a claim every episode agrees
        # on is the release's claim. What they no longer do is speak for the
        # episodes, which now seed themselves from their own filenames.
        claims = self._pre_load_attribute_combos(
            [Path(path).stem for path in media_files]
        )
        self._load_episode_claims()

        apply_plugin_override(
            self.context.shared_data.dynamic_data,
            "localization_override",
            self.localization_combo,
        )

        # Use series token from config
        series_token = get_tvr_episode_token(
            self.config.settings.series,
            self.context.media_input.series_episode_format,
        )
        self.token_override.setText(series_token)

        # As with filename attributes, source quality is a pack-wide override only
        # when every episode has the same detected value.
        comp_pair = self.context.media_input.comparison_pair
        detected_qualities = {
            self.backend.get_quality(
                media_input=Path(media_file),
                source_input=comp_pair.source if comp_pair else None,
            )
            for media_file in media_files
        }
        common_quality = (
            next(iter(detected_qualities)) if len(detected_qualities) == 1 else None
        )
        if common_quality:
            quality_idx = self.quality_combo.findText(str(common_quality))
            if quality_idx > -1:
                self.quality_combo.setCurrentIndex(quality_idx)
        else:
            self.quality_combo.setCurrentIndex(0)

        # The settings value is the user's group tag; the detected one is the
        # source group, meaning whoever made the input files. Configured wins,
        # and with parsing off there is nothing to fall back to -- the
        # renderer has no filename parse of its own, so what this field shows
        # is what the output carries.
        self.release_group_entry.setText(release_group_name or claims.release_group)

        # Initial call to update_generated_name populates the override token
        # grid (using the first mapped episode as a representative preview)
        self.update_generated_name()

    def validatePage(self) -> bool:
        """Validate the page and perform batch episode renaming."""
        if self._advance_after_rename:
            self._advance_after_rename = False
            return self._complete_validation()
        if self._rename_operation.is_running:
            return False

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
            else get_tvr_episode_token(
                self.config.settings.series,
                self.context.media_input.series_episode_format,
            )
        )

        # Get user tokens
        user_tokens = {
            k: v
            for k, (v, t) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        }

        if not self.context.media_input.series_episode_map:
            QMessageBox.warning(
                self,
                "Incomplete Series Mapping",
                "No episode mappings were found. Please return to the Series Match page and map each file to an episode.",
            )
            return False

        rename_map: dict[Path, Path] = {}
        failed_files: list[Path] = []
        for (
            media_file,
            media_data,
        ) in self.context.media_input.series_episode_map.items():
            renamed_file = self.backend.series_renamer(
                media_input_obj=self.context.media_input,
                media_file=media_file,
                file_claims=self._file_claim_overrides(media_file),
                token=token,
                colon_replacement=self.config.settings.series.filename_colon_replace,
                media_search_payload=self.context.media_search,
                title_clean_rules=self.config.settings.global_management.title_clean_rules,
                video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
                user_tokens=user_tokens,
                season_num=media_data["season"],
                episode_num=media_data["episode"],
                episode_format=self.context.media_input.series_episode_format,
                multi_episode_style=self.config.settings.series.multi_episode_style,
                # each renamed file belongs to exactly one season, so season_end
                # matches season_num here (single-season, unchanged rendering);
                # the multi-season {season_number} range only applies to the
                # aggregate release title/NFO (see ProcessBackEnd).
                season_end=media_data["season"],
            )

            if not renamed_file:
                failed_files.append(media_file)
                continue
            # Get extension from original file
            ext = media_file.suffix
            renamed_output = media_file.parent / f"{renamed_file.stem}{ext}"
            rename_map[media_file] = renamed_output

        if failed_files:
            names = "\n".join(f"  {path.name}" for path in failed_files)
            if not rename_map:
                QMessageBox.warning(
                    self,
                    "Rename Failed",
                    "No filenames could be generated from the current token "
                    f"template. Nothing was renamed.\n\n{names}",
                )
                return False
            QMessageBox.warning(
                self,
                "Some Files Skipped",
                f"{len(failed_files)} file(s) could not have a name generated "
                f"and will be left unchanged:\n\n{names}",
            )

        # Subtitles and per-episode .nfo files are named after the episode they
        # belong to, so they have to follow it -- otherwise the rename silently
        # separates a pair the release depends on.
        for media_file, sidecars in find_sidecars_for(rename_map).items():
            renamed_output = rename_map[media_file]
            for sidecar, suffix in sidecars.items():
                rename_map[sidecar] = (
                    renamed_output.parent / f"{renamed_output.stem}{suffix}"
                )

        # Rename the opened folder to a pack name, and each season subfolder
        # within it to its own season's name. A pack spanning several seasons
        # renders the root's {season_number} as a range (S01-S05); each season
        # subfolder renders its own single season.
        release_info = build_series_release_info(self.context.media_input)
        root_folder_name = ""
        season_folder_names: dict[int, str] = {}
        file_seasons = {
            media_file: media_data["season"]
            for media_file, media_data in (
                self.context.media_input.series_episode_map or {}
            ).items()
            if media_data.get("season") is not None
        }
        if release_info.season is not None:
            folder_path = self.backend.series_folder_renamer(
                media_input_obj=self.context.media_input,
                token=self.config.settings.series.season_folder_token,
                colon_replacement=self.config.settings.series.filename_colon_replace,
                media_search_payload=self.context.media_search,
                title_clean_rules=self.config.settings.global_management.title_clean_rules,
                video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
                user_tokens=user_tokens,
                season_num=release_info.season,
                season_end=release_info.season_end,
            )
            if folder_path:
                root_folder_name = folder_path.name

            subfolder_token = resolve_season_subfolder_token(
                self.config.settings.series.season_subfolder_token,
                self.config.settings.series.season_folder_token,
            )
            for season in sorted(set(file_seasons.values())):
                season_path = self.backend.series_folder_renamer(
                    media_input_obj=self.context.media_input,
                    token=subfolder_token,
                    colon_replacement=self.config.settings.series.filename_colon_replace,
                    media_search_payload=self.context.media_search,
                    title_clean_rules=self.config.settings.global_management.title_clean_rules,
                    video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
                    user_tokens=user_tokens,
                    season_num=season,
                    season_end=season,
                )
                if season_path:
                    season_folder_names[season] = season_path.name

        rename_map, directory_targets = self.backend.build_pack_rename_targets(
            input_path=self.context.media_input.input_path,
            rename_map=rename_map,
            file_seasons=file_seasons,
            root_folder_name=root_folder_name,
            season_folder_names=season_folder_names,
        )

        # Check if there are any effective renames
        effective_renames = {
            src: trg
            for src, trg in rename_map.items()
            if str(src.absolute()) != str(trg.absolute())
        }
        effective_directories = {
            src: trg
            for src, trg in directory_targets.items()
            if str(src.absolute()) != str(trg.absolute())
        }

        if not effective_renames and not effective_directories:
            return self._complete_validation()

        try:
            plan = RenamePlan.build(
                effective_renames,
                self.context.media_input.input_path,
                directory_targets=effective_directories,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Rename", str(error))
            return False

        preview_dialog = RenamePreviewDialog(self)
        preview_dialog.set_renames(plan.file_targets, plan.directory_targets)
        if preview_dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        self._rename_operation.start(plan, "Renaming episodes...")
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

    # All the methods from RenameEncode, adapted for series
    def _pre_load_attribute_combos(self, filenames: Sequence[str]) -> FilenameClaims:
        """Pre-fill the claim controls from stage 1, and return what it found.

        The detection itself lives in `detect_filename_claims`, which the
        settings preview also calls, so what this page shows and what the
        preview shows cannot diverge. Everything here is presentation: put
        each detected value into the control that owns it.

        The claims come back so the caller can reuse them without detecting
        twice -- the release group seed needs the same result.
        """
        claims = detect_filename_claims(
            filenames,
            self.config.settings.series.claims,
            self.context.custom_edition_info,
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

        # REMUX used to have its own bespoke pack-wide check and HYBRID had
        # no pre-tick at all; both are ordinary claims now.
        self.remux_checkbox.setChecked(bool(claims.remux))
        self.hybrid_checkbox.setChecked(bool(claims.hybrid))
        return claims

    def _load_episode_claims(self) -> None:
        """Seed the episode table from each file's own name.

        Ordered by season then episode rather than by however the files came
        off disk: at several hundred rows across several seasons, filesystem
        order is not how anyone reads a pack. The mapping is the source
        because it is what `validatePage` iterates, so no row can exist
        without somewhere to rename to.
        """
        episode_map = self.context.media_input.series_episode_map or {}
        ordered = sorted(
            episode_map.items(),
            key=lambda item: (
                item[1].get("season") or 0,
                item[1].get("episode") or 0,
                item[0].name,
            ),
        )
        self.episode_claims.load(
            [
                (
                    media_file,
                    detect_file_claims(
                        media_file.stem,
                        self.config.settings.series.claims,
                        self.context.custom_edition_info,
                    ),
                )
                for media_file, _ in ordered
            ]
        )

    def _file_claim_overrides(self, media_file: Path) -> dict[str, str]:
        """This episode's claims, as the table currently holds them.

        The pack's claims are not consulted. A pack flagged REPACK says
        nothing about any one episode, and this is the episode's answer:
        what its filename claims, with whatever the user typed over the top.

        The table is the only source. It and every caller here are built
        from `series_episode_map`, so a file without a row cannot arise; a
        detect-on-the-spot fallback for that case would run guessit again
        for every claim-free episode, which is most of a pack.
        """
        return self.episode_claims.resolved_claims_for(media_file)

    def _detected_claims(self) -> FilenameClaims:
        return detect_filename_claims(
            [Path(path).stem for path in self.context.media_input.file_list],
            self.config.settings.series.claims,
            self.context.custom_edition_info,
        )

    def _auto_check_remux_checkbox(self) -> None:
        """Re-apply the detected REMUX claim.

        Called when the quality combo moves to a disc source, which
        re-enables the checkbox after a non-disc quality forced it off.
        Goes through the same detector as the initial pre-fill so the two
        cannot disagree, and so a switched-off REMUX category stays off.
        """
        self.remux_checkbox.setChecked(bool(self._detected_claims().remux))

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
                self.context.jinja_engine.add_global(global_name, combo_text, True)
                # Store the pattern info for batch processing
                self.context.jinja_engine.add_global(
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

        # If not using DVD or Bluray disable REMUX. The rule is about the
        # release rather than the control, so it reaches the episode column
        # too -- a per-file REMUX on a web pack is not a thing.
        if cur_text:
            if QualitySelection(cur_text) not in {
                QualitySelection.DVD,
                QualitySelection.BLURAY,
                QualitySelection.UHD_BLURAY,
            }:
                self.remux_checkbox.setChecked(False)
                self.remux_checkbox.setEnabled(False)
                self.episode_claims.set_claim_enabled("remux", False)
            else:
                self.remux_checkbox.setEnabled(True)
                self.episode_claims.set_claim_enabled("remux", True)
                self._auto_check_remux_checkbox()
        else:
            self.remux_checkbox.setEnabled(True)
            self.episode_claims.set_claim_enabled("remux", True)
            self._auto_check_remux_checkbox()

        self._sync_service_combo_to_quality(cur_text)

        # Update override
        self._update_override_tokens("source", cur_text, False if cur_text else True)

    def _sync_service_combo_to_quality(self, quality_text: str) -> None:
        """Only a web source can carry a streaming service.

        The same rule the token applies, surfaced in the UI: switching a
        pack to BluRay clears and disables Service rather than leaving a
        stale "AMZN" selected next to a disc source.
        """
        if not quality_text:
            self.service_combo.setEnabled(True)
            self.episode_claims.set_claim_enabled("streaming_service", True)
            return

        is_web = QualitySelection(quality_text) in {
            QualitySelection.WEB_DL,
            QualitySelection.WEB_RIP,
        }
        if not is_web:
            self.service_combo.setCurrentIndex(0)
        self.service_combo.setEnabled(is_web)
        self.episode_claims.set_claim_enabled("streaming_service", is_web)

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
        """Update override tokens."""
        if remove or not v:
            self.backend.override_tokens.pop(k, None)
        else:
            self.backend.override_tokens[k] = v
        self.update_generated_name()

    def _update_pack_name_preview(self, user_tokens: dict[str, str]) -> None:
        """Render the folder name the pack controls currently produce.

        The same call `validatePage` makes, so what is shown is what will be
        written. A pack with no resolvable season has no folder name to
        render, which is the one case the field goes empty.
        """
        release_info = build_series_release_info(self.context.media_input)
        if release_info.season is None:
            self.pack_name_preview.clear()
            return

        folder_path = self.backend.series_folder_renamer(
            media_input_obj=self.context.media_input,
            token=self.config.settings.series.season_folder_token,
            colon_replacement=self.config.settings.series.filename_colon_replace,
            media_search_payload=self.context.media_search,
            title_clean_rules=self.config.settings.global_management.title_clean_rules,
            video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
            user_tokens=user_tokens,
            season_num=release_info.season,
            season_end=release_info.season_end,
        )
        self.pack_name_preview.setText(folder_path.name if folder_path else "")

    @Slot(int)
    def update_generated_name(self, _: int | None = None) -> None:
        """Update the generated name based on current selections."""
        token = get_tvr_episode_token(
            self.config.settings.series,
            self.context.media_input.series_episode_format,
        )
        if self.override_group.isChecked():
            token = self.token_override.text()
        else:
            self.token_override.setText(token)

        # This page is stage 2, so the field is the whole answer: written
        # unconditionally, including blank. A blank here is the user deciding
        # this release carries no group, which has to beat the configured tag
        # rather than fall through to it.
        self.backend.override_tokens["release_group"] = (
            self.release_group_entry.text().strip()
        )

        # Run the renamer for a representative (first mapped) episode so the
        # override token grid mirrors the movie page's live preview. Without
        # a mapped episode there is nothing to preview yet.
        episode_map = self.context.media_input.series_episode_map
        if not episode_map:
            self.rename_token_control.reset()
            return

        representative_path, media_data = next(iter(episode_map.items()))

        user_tokens = {
            k: v
            for k, (v, t) in self.config.settings.user_tokens.tokens.items()
            if TokenSelection(t) is TokenSelection.FILE_TOKEN
        }

        # Before the episode render, not after: both renderers assign
        # `backend.token_replacer`, and the override grid below reads it
        # expecting the episode's tokens rather than the folder's.
        self._update_pack_name_preview(user_tokens)

        get_file_name = self.backend.series_renamer(
            media_input_obj=self.context.media_input,
            media_file=representative_path,
            file_claims=self._file_claim_overrides(representative_path),
            token=token,
            colon_replacement=self.config.settings.series.filename_colon_replace,
            media_search_payload=self.context.media_search,
            title_clean_rules=self.config.settings.global_management.title_clean_rules,
            video_dynamic_range=self.config.settings.global_management.video_dynamic_range,
            user_tokens=user_tokens,
            season_num=media_data["season"],
            episode_num=media_data["episode"],
            episode_format=self.context.media_input.series_episode_format,
            multi_episode_style=self.config.settings.series.multi_episode_style,
            season_end=media_data["season"],
        )

        if get_file_name and self.backend.token_replacer:
            # update rename token control. unlike the movie page's default
            # token, the series default tokens pipe {season_number} and
            # {episode_number} through filters (e.g. "{season_number|zfill(2)}"),
            # so the sort pattern must tolerate an optional "|filter" segment or
            # those two series-specific tokens would never appear in the grid.
            sort_token_order = re.findall(
                r"\{(?:[:][^:}]+:)*([a-z_]+)(?:\|[^:}]*)?(?:[:][^:}]+:)*\}", token
            )
            sort_token_data = self.backend.token_replacer.token_data.get_dict()  # pyright: ignore[reportAttributeAccessIssue]
            # Claims are excluded: the episode table owns them now. This grid
            # shows one representative episode's values but writes pack-wide,
            # so leaving a claim here would be a second control for the same
            # value, disagreeing with the first about which surface it means.
            sorted_token_data = {
                k: sort_token_data[k]
                for k in sort_token_order
                if k in sort_token_data
                and sort_token_data[k]
                and k not in PER_FILE_CLAIM_KEYS
            }
            self.rename_token_control.populate_table(sorted_token_data)

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
        """Update combo box with items."""
        combobox.addItem("")
        for item in items:
            combobox.addItem(item.normalized)


class SeriesRenameTokenControl(QWidget):
    """Token control widget specifically for series rename operations."""

    row_modified = Signal(tuple)

    def __init__(self, parent: QWidget | None = None) -> None:
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

    def get_token_values(self) -> dict[str, str]:
        """Return a dict of token: value."""
        values: dict[str, str] = {}
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
        try:
            self.table.setRowCount(0)
            self.table.clearContents()
            self.table.setAutoScroll(False)
        finally:
            self.table.blockSignals(False)
