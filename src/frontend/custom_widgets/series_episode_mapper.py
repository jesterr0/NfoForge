from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from guessit import guessit
from rapidfuzz import fuzz

from src.frontend.custom_widgets.custom_splitter import CustomSplitter
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload


class EnhancedFileTableItem(QTableWidgetItem):
    """Enhanced table item for files with episode data"""

    def __init__(self, text: str, file_path: Path) -> None:
        super().__init__(text)
        self.file_path = file_path
        self.parsed_data = {}
        self.assigned_season = None
        self.assigned_episode = None
        self.confidence = 0.0
        self.assignment_method = "unassigned"


class NumericTableItem(QTableWidgetItem):
    """Table item that only accepts numeric input"""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        # set flags to be editable
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsEditable)

    def setData(self, role, value):
        """Override setData to validate numeric input"""
        if role == Qt.ItemDataRole.EditRole:
            # only allow numeric values
            if isinstance(value, str):
                # remove any non-numeric characters
                numeric_value = "".join(filter(str.isdigit, value))
                if numeric_value:
                    super().setData(role, numeric_value)
                else:
                    super().setData(role, "")
            else:
                super().setData(role, str(value) if value is not None else "")
        else:
            super().setData(role, value)


@dataclass(slots=True)
class EpisodeListItem:
    """Episode list item for the episodes display"""

    season: int
    episode: int
    episode_data: dict
    name: str = ""
    is_assigned: bool = False

    def __post_init__(self):
        if not self.name:
            self.name = self.episode_data.get("name", "Unknown Episode")


class SeriesEpisodeMapper(QWidget):
    mapping_changed = Signal()
    validation_changed = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # store payloads (can be set later)
        self.media_input_payload = None
        self.media_search_payload = None

        # episode data and mappings
        self.available_episodes = {}  # {season: {episode: episode_data}}
        self.episodes_by_type = {}  # enhanced episode data organized by season type
        self.file_episode_mappings = {}  # {file_path: {season, episode, confidence, etc}}
        self.episode_items = []  # list of EpisodeListItem objects

        # fuzzy matching controls
        matching_group = QGroupBox("Fuzzy Matching", self)

        self.enable_fuzzy_checkbox = QCheckBox("Enable", self)
        self.enable_fuzzy_checkbox.setChecked(True)
        self.enable_fuzzy_checkbox.setToolTip(
            "Use fuzzy matching for episode names when S/E numbers aren't available"
        )

        self.fuzzy_threshold_spin = QSpinBox(
            parent=self, suffix="%", minimum=50, maximum=95, value=75
        )
        self.fuzzy_threshold_spin.setToolTip(
            "Minimum similarity score for fuzzy matches"
        )

        matching_layout = QHBoxLayout(matching_group)
        matching_layout.addWidget(self.enable_fuzzy_checkbox)
        matching_layout.addWidget(QLabel("Threshold:", self))
        matching_layout.addWidget(self.fuzzy_threshold_spin)

        # actions
        actions_group = QGroupBox("Actions", self)

        self.auto_match_btn = QToolButton(self)
        self.auto_match_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.auto_match_btn.setText("Re-match All")
        QTAThemeSwap().register(
            self.auto_match_btn,
            "ph.arrow-counter-clockwise-light",
            icon_size=QSize(20, 20),
        )
        self.auto_match_btn.setToolTip(
            "Re-run automatic matching with current settings"
        )
        self.auto_match_btn.clicked.connect(self._auto_match_files)

        self.fuzzy_match_btn = QToolButton(self)
        self.fuzzy_match_btn.setText("Fuzzy Match")
        self.fuzzy_match_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        QTAThemeSwap().register(
            self.fuzzy_match_btn,
            "ph.target-light",
            icon_size=QSize(20, 20),
        )
        self.fuzzy_match_btn.setToolTip("Run fuzzy matching on unassigned files")
        self.fuzzy_match_btn.clicked.connect(self._fuzzy_match_unassigned)

        self.clear_btn = QToolButton(self)
        self.clear_btn.setText("Clear All")
        self.clear_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        QTAThemeSwap().register(
            self.clear_btn,
            "ph.trash-light",
            icon_size=QSize(20, 20),
        )
        self.clear_btn.setToolTip("Clear all assignments")
        self.clear_btn.clicked.connect(self._clear_all_assignments)

        actions_layout = QHBoxLayout(actions_group)
        actions_layout.addWidget(self.auto_match_btn)
        actions_layout.addWidget(self.fuzzy_match_btn)
        actions_layout.addWidget(self.clear_btn)

        header_layout = QHBoxLayout()
        header_layout.addWidget(matching_group)
        header_layout.addWidget(actions_group)
        header_layout.addStretch()

        splitter = CustomSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(True)

        # left side: files table
        files_group = QGroupBox("Files")

        self.files_table = QTableWidget(self)
        self.files_table.setFrameShape(QFrame.Shape.Box)
        self.files_table.setFrameShadow(QFrame.Shadow.Sunken)
        self.files_table.setColumnCount(5)
        self.files_table.setHorizontalHeaderLabels(
            ("Filename", "Season", "Episode", "Confidence", "Method")
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )

        self.files_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.files_table.setAlternatingRowColors(True)
        # self.files_table.itemSelectionChanged.connect(self._on_file_selection_changed)
        self.files_table.itemChanged.connect(self._on_table_item_changed)

        self.files_stats_label = QLabel("Files: 0 total, 0 assigned")

        files_layout = QVBoxLayout(files_group)
        files_layout.addWidget(self.files_table)
        files_layout.addWidget(self.files_stats_label)

        splitter.addWidget(files_group)

        # right side: episodes list
        episodes_group = QGroupBox("Episodes")

        # episode search box
        self.episode_search_box = QLineEdit()
        self.episode_search_box.setPlaceholderText("Search episode names...")
        self.episode_search_box.textChanged.connect(self._on_episode_search_changed)

        # clear search button
        self.clear_search_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.clear_search_btn,
            "ph.x-light",
            icon_size=QSize(20, 20),
        )
        self.clear_search_btn.setToolTip("Clear search")
        self.clear_search_btn.clicked.connect(self._clear_episode_search)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:", self))
        search_layout.addWidget(self.episode_search_box)
        search_layout.addWidget(self.clear_search_btn)

        # episode controls - right side
        self.episode_order_combo = QComboBox()
        # will be populated dynamically based on available episode types
        self.episode_order_combo.currentTextChanged.connect(
            self._on_episode_order_changed
        )

        self.episode_filter_combo = QComboBox()
        self.episode_filter_combo.addItem("All Seasons", "all")
        self.episode_filter_combo.currentTextChanged.connect(
            self._on_episode_filter_changed
        )

        episode_controls_layout = QHBoxLayout()
        episode_controls_layout.addWidget(QLabel("Order:"))
        episode_controls_layout.addWidget(self.episode_order_combo)
        episode_controls_layout.addWidget(QLabel("Filter:"))
        episode_controls_layout.addWidget(self.episode_filter_combo)
        episode_controls_layout.addStretch()

        self.episodes_tree = QTreeWidget(self)
        self.episodes_tree.setFrameShape(QFrame.Shape.Box)
        self.episodes_tree.setFrameShadow(QFrame.Shadow.Sunken)
        self.episodes_tree.setHeaderLabels(("Episode", "Ep#", "Abs#", "Aired"))
        self.episodes_tree.setAlternatingRowColors(True)
        self.episodes_tree.setRootIsDecorated(True)
        self.episodes_tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.episodes_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.episodes_tree.header().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.episodes_tree.header().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )

        self.episodes_stats_label = QLabel("Episodes: 0 available, 0 assigned")

        episodes_layout = QVBoxLayout(episodes_group)
        episodes_layout.addLayout(search_layout)
        episodes_layout.addLayout(episode_controls_layout)
        episodes_layout.addWidget(self.episodes_tree)
        episodes_layout.addWidget(self.episodes_stats_label)

        splitter.addWidget(episodes_group)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(header_layout)
        self.main_layout.addWidget(splitter, stretch=1)

    def load_data(
        self,
        media_input_payload: MediaInputPayload,
        media_search_payload: MediaSearchPayload,
    ) -> None:
        """Load media data and populate the widget"""
        self.media_input_payload = media_input_payload
        self.media_search_payload = media_search_payload

        # load and populate data
        self._load_episode_data()
        self._populate_files_table()
        self._auto_match_files()

    def clear_data(self) -> None:
        """Clear all data and reset the widget"""
        self.media_input_payload = None
        self.media_search_payload = None

        # clear all data structures
        self.available_episodes.clear()
        self.episodes_by_type.clear()
        self.file_episode_mappings.clear()
        self.episode_items.clear()

        # clear UI elements
        self.files_table.setRowCount(0)
        self.episodes_tree.clear()
        self.episode_order_combo.clear()
        self.episode_filter_combo.clear()
        self.episode_filter_combo.addItem("All Seasons", "all")
        self.episode_search_box.clear()

        # update stats
        self._update_all_stats()

    def _load_episode_data(self):
        """Load all available episode data from TVDB"""
        self.available_episodes.clear()
        # store episodes organized by season type
        self.episodes_by_type = {}

        if not (
            self.media_search_payload
            and self.media_search_payload.tvdb_data
            and "episodes_by_type" in self.media_search_payload.tvdb_data
        ):
            return

        tvdb_data = self.media_search_payload.tvdb_data

        # store all episode types for UI
        self.episodes_by_type = tvdb_data["episodes_by_type"]

        # setup dynamic episode order combo based on available types
        self._setup_episode_order_combo_from_data()

        # use the first available type for initial load
        if self.episodes_by_type:
            first_type_data = next(iter(self.episodes_by_type.values()))
            episodes_to_load = first_type_data.get("episodes", [])
        else:
            return

        # load episodes into available_episodes structure
        for episode in episodes_to_load:
            season_num = episode.get("seasonNumber")
            episode_num = episode.get("number")

            if season_num is not None and episode_num is not None:
                if season_num not in self.available_episodes:
                    self.available_episodes[season_num] = {}

                self.available_episodes[season_num][episode_num] = episode

        # update episode filter combo with available seasons
        self.episode_filter_combo.clear()
        self.episode_filter_combo.addItem("All Seasons", "all")
        for season in sorted(self.available_episodes.keys()):
            self.episode_filter_combo.addItem(f"Season {season}", season)

        if self.available_episodes:
            self._load_episodes_with_ordering()

        # Log available episode types if we have enhanced data
        # if self.episodes_by_type:
        #     print("🎬 Available episode orderings:")
        #     for type_id, type_data in self.episodes_by_type.items():
        #         episode_count = len(type_data["episodes"])
        #         print(f"   • {type_data['type_name']}: {episode_count} episodes")

    def _setup_episode_order_combo_from_data(self) -> None:
        """Setup episode order combo based on available enhanced episode types"""
        if not self.episodes_by_type:
            return

        self.episode_order_combo.clear()

        for type_id, type_data in self.episodes_by_type.items():
            type_name = type_data.get("type_name", f"Type {type_id}")
            episode_count = len(type_data.get("episodes", []))
            display_name = f"{type_name} ({episode_count} episodes)"

            # store the type ID in the combo item data for easy lookup
            self.episode_order_combo.addItem(display_name, type_id)

        # set the first item as default selection
        if self.episode_order_combo.count() > 0:
            self.episode_order_combo.setCurrentIndex(0)
            # explicitly trigger episodes loading since setCurrentIndex might not emit signal
            self._load_episodes_with_ordering()

    def _populate_files_table(self) -> None:
        """Populate the files table with file data"""
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return

        self.files_table.setRowCount(len(self.media_input_payload.file_list))

        for row, file_path in enumerate(self.media_input_payload.file_list):
            # parse file with guessit
            try:
                parsed_data = guessit(str(file_path))
            except Exception:
                parsed_data = {}

            # create filename item (read only)
            filename_item = EnhancedFileTableItem(file_path.name, file_path)
            filename_item.parsed_data = parsed_data
            filename_item.setFlags(filename_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.files_table.setItem(row, 0, filename_item)

            # season column (editable, numeric only)
            season_item = NumericTableItem("")
            self.files_table.setItem(row, 1, season_item)

            # episode column (editable, numeric only)
            episode_item = NumericTableItem("")
            self.files_table.setItem(row, 2, episode_item)

            # confidence column (read only)
            confidence_item = QTableWidgetItem("")
            confidence_item.setFlags(
                confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            self.files_table.setItem(row, 3, confidence_item)

            # method column (read only)
            method_item = QTableWidgetItem("")
            method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.files_table.setItem(row, 4, method_item)

        self._update_files_stats()

    def _normalize_text(self, text: str) -> str:
        """Normalize text for fuzzy matching"""
        # remove common video terms and normalize
        text = re.sub(
            r"\b(720p|1080p|hdtv|webrip|bluray|dvdrip|x264|h264|x265|hevc)\b",
            "",
            text.lower(),
        )
        # remove season/episode patterns for fuzzy matching
        text = re.sub(r"\bs\d+e\d+\b", "", text)  # remove S01E01 style
        text = re.sub(r"\bseason\s*\d+\b", "", text)  # remove "season 1" style
        text = re.sub(r"\bepisode\s*\d+\b", "", text)  # remove "episode 1" style
        text = re.sub(r"\b\d+x\d+\b", "", text)  # remove 1x01 style
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text.strip())
        return text

    def _fuzzy_match_episode_name(
        self, filename: str, season: int | None = None
    ) -> tuple[int, int, float] | None:
        """Fuzzy match filename against episode names"""
        if not self.enable_fuzzy_checkbox.isChecked():
            return None

        threshold = self.fuzzy_threshold_spin.value()
        filename_clean = self._normalize_text(filename)

        # extract potential episode title from filename
        # remove show name to isolate episode title
        show_name_variations = []
        if (
            self.media_search_payload
            and hasattr(self.media_search_payload, "title")
            and self.media_search_payload.title
        ):
            show_title = self.media_search_payload.title.lower()
            show_name_variations.append(show_title)
            # also try with punctuation removed
            show_title_clean = re.sub(r"[^a-z0-9\s]", " ", show_title)
            show_title_clean = re.sub(r"\s+", " ", show_title_clean.strip())
            if show_title_clean != show_title:
                show_name_variations.append(show_title_clean)

        episode_title = filename_clean
        for show_name in show_name_variations:
            episode_title = episode_title.replace(show_name, "").strip()

        # remove common technical terms that don't help with episode matching
        episode_title = re.sub(
            r"\b(web|dl|rip|bluray|dvd|hdtv|mkv|mp4|avi)\b", "", episode_title
        )
        episode_title = re.sub(r"\s+", " ", episode_title.strip())

        # if there's no meaningful episode title left (too short), skip fuzzy matching
        if len(episode_title) < 3:
            return None

        best_match = None
        best_score = 0

        # search in specified season or all seasons
        seasons_to_search = [season] if season else self.available_episodes.keys()

        for search_season in seasons_to_search:
            if search_season not in self.available_episodes:
                continue

            for episode_num, episode_data in self.available_episodes[
                search_season
            ].items():
                episode_name = episode_data.get("name", "")
                if not episode_name:
                    continue

                episode_name_clean = self._normalize_text(episode_name)

                # try different fuzzy matching approaches
                scores = [
                    fuzz.ratio(episode_title, episode_name_clean),
                    fuzz.partial_ratio(episode_title, episode_name_clean),
                    fuzz.token_sort_ratio(episode_title, episode_name_clean),
                ]

                score = max(scores)

                if score > best_score and score >= threshold:
                    best_score = score
                    best_match = (search_season, episode_num, score / 100.0)

        return best_match

    def _auto_match_files(self) -> None:
        """Enhanced auto-matching with fuzzy fallback"""
        if not self.available_episodes:
            return

        matched_count = 0
        fuzzy_matched_count = 0

        for row in range(self.files_table.rowCount()):
            filename_item = self.files_table.item(row, 0)
            if not isinstance(filename_item, EnhancedFileTableItem):
                continue

            file_path = filename_item.file_path
            parsed_data = filename_item.parsed_data

            # stage 1: try regex/guessit parsing (highest confidence)
            season = parsed_data.get("season")
            episode = parsed_data.get("episode")

            if isinstance(season, list):
                season = season[0] if season else None
            if isinstance(episode, list):
                episode = episode[0] if episode else None

            if (
                season
                and episode
                and season in self.available_episodes
                and episode in self.available_episodes[season]
            ):
                # high confidence regex match
                episode_data = self.available_episodes[season][episode]
                confidence = 0.95
                method = "regex"

                self._store_mapping(
                    file_path, season, episode, episode_data, confidence, method
                )
                self._update_file_row_assignment(
                    row, season, episode, confidence, method
                )
                matched_count += 1
                continue

            # stage 2: try fuzzy matching (medium confidence)
            fuzzy_result = self._fuzzy_match_episode_name(file_path.stem)
            if fuzzy_result:
                season, episode, confidence = fuzzy_result
                if (
                    season in self.available_episodes
                    and episode in self.available_episodes[season]
                ):
                    episode_data = self.available_episodes[season][episode]
                    method = "fuzzy"

                    self._store_mapping(
                        file_path, season, episode, episode_data, confidence, method
                    )
                    self._update_file_row_assignment(
                        row, season, episode, confidence, method
                    )
                    fuzzy_matched_count += 1
                    continue

        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _fuzzy_match_unassigned(self) -> None:
        """Run fuzzy matching specifically on unassigned files"""
        fuzzy_matched = 0

        for row in range(self.files_table.rowCount()):
            # check if file is already assigned
            season_item = self.files_table.item(row, 1)
            if season_item and season_item.text():
                continue

            filename_item = self.files_table.item(row, 0)
            if not isinstance(filename_item, EnhancedFileTableItem):
                continue

            file_path = filename_item.file_path

            # try fuzzy matching
            fuzzy_result = self._fuzzy_match_episode_name(file_path.stem)
            if fuzzy_result:
                season, episode, confidence = fuzzy_result
                if (
                    season in self.available_episodes
                    and episode in self.available_episodes[season]
                ):
                    episode_data = self.available_episodes[season][episode]
                    method = "fuzzy"

                    self._store_mapping(
                        file_path, season, episode, episode_data, confidence, method
                    )
                    self._update_file_row_assignment(
                        row, season, episode, confidence, method
                    )
                    fuzzy_matched += 1

        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _store_mapping(
        self,
        file_path: Path,
        season: int,
        episode: int,
        episode_data: dict,
        confidence: float,
        method: str,
    ) -> None:
        """Store file-to-episode mapping"""
        self.file_episode_mappings[file_path] = {
            "season": season,
            "episode": episode,
            "episode_data": episode_data,
            "episode_name": episode_data.get("name", "Unknown"),
            "confidence": confidence,
            "assignment_method": method,
        }

    def _update_file_row_assignment(
        self, row: int, season: int, episode: int, confidence: float, method: str
    ):
        """Update file table row with assignment data"""
        # season (editable, numeric)
        season_item = NumericTableItem(str(season))
        self.files_table.setItem(row, 1, season_item)

        # episode (editable, numeric)
        episode_item = NumericTableItem(str(episode))
        self.files_table.setItem(row, 2, episode_item)

        # confidence with color coding (read only)
        confidence_item = QTableWidgetItem(f"{confidence * 100:.0f}%")
        confidence_item.setFlags(confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if confidence >= 0.9:
            confidence_item.setBackground(Qt.GlobalColor.green)
        elif confidence >= 0.7:
            confidence_item.setBackground(Qt.GlobalColor.yellow)
        else:
            confidence_item.setBackground(Qt.GlobalColor.red)
        self.files_table.setItem(row, 3, confidence_item)

        # method (read only)
        method_item = QTableWidgetItem(method)
        method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.files_table.setItem(row, 4, method_item)

    def _clear_all_assignments(self) -> None:
        """Clear all file assignments"""
        self.file_episode_mappings.clear()

        # clear table cells while preserving edit flags
        for row in range(self.files_table.rowCount()):
            # clear Season (keep editable, numeric only)
            season_item = NumericTableItem("")
            self.files_table.setItem(row, 1, season_item)

            # clear Episode (keep editable, numeric only)
            episode_item = NumericTableItem("")
            self.files_table.setItem(row, 2, episode_item)

            # clear Confidence (read-only)
            confidence_item = QTableWidgetItem("")
            confidence_item.setFlags(
                confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            confidence_item.setBackground(Qt.GlobalColor.transparent)
            self.files_table.setItem(row, 3, confidence_item)

            # clear Method (read-only)
            method_item = QTableWidgetItem("")
            method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.files_table.setItem(row, 4, method_item)

        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _load_episodes_with_ordering(self) -> None:
        """Load episodes list with specified ordering from enhanced data"""
        type_id = self.episode_order_combo.currentData()

        self.episode_items.clear()

        # use enhanced episode data with specific type
        if (
            type_id is not None
            and self.episodes_by_type
            and type_id in self.episodes_by_type
        ):
            type_data = self.episodes_by_type[type_id]
            episodes_source = type_data.get("episodes", [])

            # create episode items directly from enhanced data
            for episode_data in episodes_source:
                season_num = episode_data.get("seasonNumber")
                episode_num = episode_data.get("number")
                if season_num is not None and episode_num is not None:
                    episode_item = EpisodeListItem(
                        season_num, episode_num, episode_data
                    )
                    self.episode_items.append(episode_item)

        self._refresh_episodes_display()
        self._update_season_filter_for_current_ordering()

    def _update_season_filter_for_current_ordering(self) -> None:
        """Update season filter dropdown to show episode counts for current ordering"""
        # store current selection
        current_filter = self.episode_filter_combo.currentData()

        # Block signals to prevent infinite loop
        self.episode_filter_combo.blockSignals(True)

        # clear and rebuild the filter
        self.episode_filter_combo.clear()
        self.episode_filter_combo.addItem("All Seasons", "all")

        # count episodes per season in current ordering
        season_counts = {}
        for episode_item in self.episode_items:
            season = episode_item.season
            if season not in season_counts:
                season_counts[season] = 0
            season_counts[season] += 1

        # add season items with current episode counts
        for season in sorted(season_counts.keys()):
            count = season_counts[season]
            self.episode_filter_combo.addItem(
                f"Season {season} ({count} episodes)", season
            )

        # restore previous selection if it still exists
        for i in range(self.episode_filter_combo.count()):
            if self.episode_filter_combo.itemData(i) == current_filter:
                self.episode_filter_combo.setCurrentIndex(i)
                break

        # Re-enable signals
        self.episode_filter_combo.blockSignals(False)

    def _refresh_episodes_display(self) -> None:
        """Refresh the episodes tree display with search filtering"""
        self.episodes_tree.clear()

        # get filter setting and search text
        filter_data = self.episode_filter_combo.currentData()
        search_text = self.episode_search_box.text().lower().strip()

        # handle None filter_data by defaulting to "all"
        if filter_data is None:
            filter_data = "all"

        # get all assigned episodes for marking purposes
        assigned_episodes = set()
        for mapping in self.file_episode_mappings.values():
            assigned_episodes.add((mapping["season"], mapping["episode"]))

        # update episode items to reflect assignment status
        for episode_item in self.episode_items:
            episode_item.is_assigned = (
                episode_item.season,
                episode_item.episode,
            ) in assigned_episodes

        # count total episodes per season from ALL episodes in current ordering
        total_episodes_per_season = {}
        for episode in self.episode_items:
            season = episode.season
            if season not in total_episodes_per_season:
                total_episodes_per_season[season] = 0
            total_episodes_per_season[season] += 1

        # group episodes by season (apply filters)
        seasons_data = {}
        for episode_item in self.episode_items:
            # apply season filter
            if filter_data != "all" and episode_item.season != filter_data:
                continue

            # apply search filter
            if search_text:
                episode_name = episode_item.name.lower()
                if search_text not in episode_name:
                    continue

            if episode_item.season not in seasons_data:
                seasons_data[episode_item.season] = []
            seasons_data[episode_item.season].append(episode_item)

        # create tree structure
        for season in sorted(seasons_data.keys()):
            # create season node
            season_item = QTreeWidgetItem([f"Season {season}"])
            season_item.setData(
                0, Qt.ItemDataRole.UserRole, {"type": "season", "season": season}
            )

            # count assigned episodes in this season (from filtered episodes)
            season_episodes = seasons_data[season]
            assigned_count = sum(
                1
                for ep in season_episodes
                if (ep.season, ep.episode) in assigned_episodes
            )

            # get total episode count for this season from ALL episodes in current ordering
            total_episodes_in_season = total_episodes_per_season.get(
                season, len(season_episodes)
            )

            # update season display with assignment count using total from current ordering
            season_item.setText(
                0,
                f"Season {season} ({assigned_count}/{total_episodes_in_season} assigned)",
            )

            # add episodes as children
            for episode_item in season_episodes:
                # check if assigned
                is_assigned = episode_item.is_assigned

                # create episode tree item with columns
                ep_name = episode_item.name
                if is_assigned:
                    ep_name = f"✅ {ep_name}"
                # unmatched
                else:
                    ep_name = f"⭕ {ep_name}"

                # format aired date
                aired_date = episode_item.episode_data.get("aired", "")
                if aired_date:
                    try:
                        # show full date in YYYY-MM-DD format
                        aired_display = aired_date
                    except Exception:
                        aired_display = aired_date
                else:
                    aired_display = ""

                tree_item = QTreeWidgetItem(
                    [
                        ep_name,
                        str(episode_item.episode),
                        str(episode_item.episode_data.get("absoluteNumber", "")),
                        aired_display,
                    ]
                )

                # store episode data in the item
                tree_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {
                        "type": "episode",
                        "season": episode_item.season,
                        "episode": episode_item.episode,
                        "episode_data": episode_item.episode_data,
                        "is_assigned": is_assigned,
                    },
                )

                # color code episodes based on assignment status
                if is_assigned:
                    # light green background
                    assigned_color = QColor(200, 255, 200)
                    for col in range(4):
                        tree_item.setBackground(col, assigned_color)
                else:
                    # light red background to make them stand out
                    unassigned_color = QColor(255, 220, 220)
                    for col in range(4):
                        tree_item.setBackground(col, unassigned_color)

                # highlight search terms (override assignment color if searching)
                if search_text and search_text in episode_item.name.lower():
                    tree_item.setBackground(0, Qt.GlobalColor.yellow)

                season_item.addChild(tree_item)

            self.episodes_tree.addTopLevelItem(season_item)

            # only expand seasons that have assigned episodes or when searching
            # this helps focus on what's been matched
            if assigned_count > 0 or search_text:
                season_item.setExpanded(True)

        self._update_episodes_stats()

    def _update_files_stats(self) -> None:
        """Update file statistics"""
        total_files = self.files_table.rowCount()
        assigned_files = len(self.file_episode_mappings)

        self.files_stats_label.setText(
            f"Files: {total_files} total, {assigned_files} assigned"
        )

    def _update_episodes_stats(self) -> None:
        """Update episode statistics"""
        total_episodes = len(self.episode_items)
        assigned_episodes = sum(1 for item in self.episode_items if item.is_assigned)

        self.episodes_stats_label.setText(
            f"Episodes: {total_episodes} available, {assigned_episodes} assigned"
        )

    def _update_all_stats(self):
        """Update all statistics"""
        self._update_files_stats()
        self._update_episodes_stats()

    @Slot(str)
    def _on_episode_order_changed(self, _order: str) -> None:
        self._load_episodes_with_ordering()

    @Slot(str)
    def _on_episode_filter_changed(self, filter_text: str) -> None:
        """Handle episode filter change"""
        self._refresh_episodes_display()

    @Slot(str)
    def _on_episode_search_changed(self, _search_text: str) -> None:
        """Handle episode search text change"""
        self._refresh_episodes_display()

    @Slot()
    def _clear_episode_search(self) -> None:
        """Clear the episode search box"""
        self.episode_search_box.clear()
        self._refresh_episodes_display()

    # def _on_file_selection_changed(self):
    #     """Handle file selection change"""
    #     # Could highlight corresponding episode in the list
    #     pass

    @Slot(QTableWidgetItem)
    def _on_table_item_changed(self, item) -> None:
        """Handle direct editing of season/episode in table"""
        if not item:
            return

        row = item.row()
        col = item.column()

        # only process season (col 1) and episode (col 2) changes
        if col not in [1, 2]:
            return

        # get the filename item to identify the file
        filename_item = self.files_table.item(row, 0)
        if not isinstance(filename_item, EnhancedFileTableItem):
            return

        file_path = filename_item.file_path

        try:
            # get current season and episode values
            season_item = self.files_table.item(row, 1)
            episode_item = self.files_table.item(row, 2)

            if not season_item or not episode_item:
                return

            season_text = season_item.text().strip()
            episode_text = episode_item.text().strip()

            # validate and convert to integers
            if not season_text or not episode_text:
                # remove mapping if either field is empty
                if file_path in self.file_episode_mappings:
                    del self.file_episode_mappings[file_path]
                    self._clear_row_assignment_data(row)
                return

            try:
                season = int(season_text)
                episode = int(episode_text)
            except ValueError:
                return

            # check if episode exists in TVDB data
            if (
                season in self.available_episodes
                and episode in self.available_episodes[season]
            ):
                episode_data = self.available_episodes[season][episode]
                confidence = 1.0  # 100%
                method = "manual"

                # store the mapping
                self._store_mapping(
                    file_path, season, episode, episode_data, confidence, method
                )

                # update confidence and method columns
                confidence_item = QTableWidgetItem(f"{confidence * 100:.0f}%")
                confidence_item.setFlags(
                    confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
                confidence_item.setBackground(Qt.GlobalColor.green)  # Manual = green
                self.files_table.setItem(row, 3, confidence_item)

                method_item = QTableWidgetItem(method)
                method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.files_table.setItem(row, 4, method_item)
            else:
                # clear confidence and method for invalid episodes
                self._clear_row_assignment_data(row)

        except Exception as _e:
            pass
            # TODO: log?

        # update stats and refresh display
        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _clear_row_assignment_data(self, row: int) -> None:
        """Clear confidence and method data for a row"""
        # clear confidence
        confidence_item = QTableWidgetItem("")
        confidence_item.setFlags(confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        confidence_item.setBackground(Qt.GlobalColor.transparent)
        self.files_table.setItem(row, 3, confidence_item)

        # clear method
        method_item = QTableWidgetItem("")
        method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.files_table.setItem(row, 4, method_item)

    # public API
    def load_media_search_data(self, media_search_payload: MediaSearchPayload) -> None:
        """Load new media search data and refresh the episode display"""
        self.media_search_payload = media_search_payload
        self._load_episode_data()
        if self.available_episodes:
            self._load_episodes_with_ordering()
        self._refresh_episodes_display()

    def load_media_input_data(self, media_input_payload: MediaInputPayload) -> None:
        """Load new media input data and refresh the files display"""
        self.media_input_payload = media_input_payload
        self._populate_files_table()
        self._auto_match_files()

    def get_file_episode_mappings(self) -> dict[Path, dict[str, Any]]:
        """Get the current file-to-episode mappings"""
        return self.file_episode_mappings.copy()

    def get_simple_mappings(self) -> dict[str, dict[str, Any]]:
        """Get simplified mappings: {filename: {season, episode, confidence_percent}}"""
        simple_mappings = {}

        for file_path, mapping_data in self.file_episode_mappings.items():
            simple_mappings[file_path.name] = {
                "season": mapping_data["season"],
                "episode": mapping_data["episode"],
                # convert to 0-100%
                "confidence": int(mapping_data["confidence"] * 100),
                "method": mapping_data["assignment_method"],
                "episode_name": mapping_data["episode_name"],
            }

        return simple_mappings

    def get_path_mappings(self) -> dict[str, dict[str, Any]]:
        """Get mappings with full file paths: {file_path: {season, episode, confidence_percent}}"""
        path_mappings = {}

        for file_path, mapping_data in self.file_episode_mappings.items():
            path_mappings[str(file_path)] = {
                "season": mapping_data["season"],
                "episode": mapping_data["episode"],
                # convert to 0-100%
                "confidence": int(mapping_data["confidence"] * 100),
                "method": mapping_data["assignment_method"],
                "episode_name": mapping_data["episode_name"],
            }

        return path_mappings

    def get_episode_map(self) -> dict | None:
        """Get episode mappings"""
        return self.file_episode_mappings

    def is_valid(self) -> bool:
        """Check if all files are properly assigned"""
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return False

        return len(self.file_episode_mappings) == len(
            self.media_input_payload.file_list
        )
