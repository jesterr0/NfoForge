import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from guessit import guessit
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
from rapidfuzz import fuzz

from src.config.tv_tokens import SUPPORTED_TVR_FORMATS
from src.enums.series import EpisodeFormat
from src.frontend.custom_widgets.custom_splitter import CustomSplitter
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.logger.nfo_forge_logger import LOG
from src.payloads.media_inputs import MediaInputPayload
from src.payloads.media_search import MediaSearchPayload

NO_TVDB_EPISODE_DATA_MESSAGE = (
    "TVDB returned no episode data for this series; enter season/episode manually."
)


def match_by_absolute(
    files_parsed: dict[Any, int | None],
    absolute_episodes: list[dict[str, Any]],
) -> dict[Any, dict[str, Any]]:
    """Match files to TVDB absolute-order episodes by absolute episode number.

    This is a pure, Qt-free helper so it can be unit-tested without a widget.

    Args:
        files_parsed: maps an arbitrary, hashable file identifier (a
            ``Path``, a filename string, a row index, etc. -- the caller
            decides) to that file's parsed absolute episode number. This is
            typically guessit's ``episode`` value for an anime/absolute
            release that carries no season component, e.g.
            ``"[Group] Show - 025.mkv"`` parses to ``25``. A value of
            ``None`` means the file had no parseable number and is skipped.
        absolute_episodes: the list of TVDB episode dicts for the
            "Absolute Order" season type, i.e.
            ``episodes_by_type[type_id]["episodes"]`` for the entry whose
            ``type`` is ``"absolute"``. Each dict is expected to carry an
            ``absoluteNumber`` key (and typically ``seasonNumber``/``number``
            identifying where that absolute episode lives in aired order).

    Returns:
        A dict with the same keys as ``files_parsed``, but containing only
        the keys that produced a match, mapped to the matched episode dict
        from ``absolute_episodes``. Keys with no parseable number, or whose
        number doesn't appear in ``absolute_episodes``, are omitted.
    """
    episodes_by_absolute_number: dict[int, dict[str, Any]] = {}
    for episode_data in absolute_episodes:
        absolute_number = episode_data.get("absoluteNumber")
        if absolute_number is None:
            continue
        episodes_by_absolute_number.setdefault(absolute_number, episode_data)

    matches: dict[Any, dict[str, Any]] = {}
    for file_key, absolute_number in files_parsed.items():
        if absolute_number is None:
            continue
        episode_data = episodes_by_absolute_number.get(absolute_number)
        if episode_data is not None:
            matches[file_key] = episode_data
    return matches


def _normalize_air_date(value: Any) -> str | None:
    """Normalize a date-like value to an ISO "YYYY-MM-DD" string.

    Accepts ``datetime.date``/``datetime.datetime`` (what guessit returns
    for a parsed filename date) as well as a string (what TVDB's ``aired``
    field carries, e.g. ``"2024-05-01"``). Returns ``None`` if ``value`` is
    ``None``, empty, or not a recognizable date.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    return None


def match_by_air_date(
    files_parsed: dict[Any, Any],
    episodes: list[dict[str, Any]],
) -> dict[Any, dict[str, Any]]:
    """Match files to TVDB episodes by air date.

    This is a pure, Qt-free helper so it can be unit-tested without a widget.
    It mirrors ``match_by_absolute`` but keys on air date instead of
    absolute episode number, for daily/date releases (e.g.
    "Show.2024.05.01.mkv") that carry no season/episode component at all.

    Args:
        files_parsed: maps an arbitrary, hashable file identifier (a
            ``Path``, a filename string, a row index, etc. -- the caller
            decides) to that file's parsed date. This is typically
            guessit's ``date`` value, a ``datetime.date`` (or
            ``datetime.datetime``). A value of ``None`` means the file had
            no parseable date and is skipped.
        episodes: the list of TVDB episode dicts to search, each expected
            to carry ``seasonNumber``/``number`` (identifying the episode)
            and an ``aired`` date string (e.g. ``"2024-05-01"``).

    Returns:
        A dict with the same keys as ``files_parsed``, but containing only
        the keys that produced a match, mapped to the matched episode dict
        from ``episodes``. Keys with no parseable date, or whose date
        doesn't match any episode's ``aired`` date, are omitted. Dates are
        normalized (see ``_normalize_air_date``) before comparison so a
        ``datetime.date``/``datetime.datetime`` parsed value compares equal
        to TVDB's ISO date string.
    """
    episodes_by_date: dict[str, dict[str, Any]] = {}
    for episode_data in episodes:
        normalized_aired = _normalize_air_date(episode_data.get("aired"))
        if normalized_aired is None:
            continue
        episodes_by_date.setdefault(normalized_aired, episode_data)

    matches: dict[Any, dict[str, Any]] = {}
    for file_key, parsed_date in files_parsed.items():
        normalized_parsed = _normalize_air_date(parsed_date)
        if normalized_parsed is None:
            continue
        episode_data = episodes_by_date.get(normalized_parsed)
        if episode_data is not None:
            matches[file_key] = episode_data
    return matches


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
        self._release_format_manually_selected = False
        self._loading_release_format_combo = False

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

        # release format controls
        release_format_group = QGroupBox("Release Format", self)

        self.release_format_combo = QComboBox()
        self.release_format_combo.setToolTip(
            "Controls title and filename token format. This does not change the TVDB episode order."
        )
        for episode_format in SUPPORTED_TVR_FORMATS:
            display_name = str(episode_format)
            if episode_format is EpisodeFormat.ANIME_ABSOLUTE:
                display_name = "Anime / Absolute Numbering"
            self.release_format_combo.addItem(display_name, episode_format)
        self.release_format_combo.currentIndexChanged.connect(
            self._on_release_format_changed
        )

        release_format_layout = QVBoxLayout(release_format_group)
        release_format_layout.addWidget(self.release_format_combo)

        header_layout = QHBoxLayout()
        header_layout.addWidget(matching_group)
        header_layout.addWidget(actions_group)
        header_layout.addWidget(release_format_group)
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
        episode_controls_layout.addWidget(QLabel("TVDB Order:"))
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
        self._release_format_manually_selected = False
        if media_input_payload.series_episode_format is not EpisodeFormat.STANDARD:
            self._set_release_format(
                media_input_payload.series_episode_format, manually_selected=True
            )

        # load and populate data
        self._load_episode_data()
        self._populate_files_table()
        self._auto_match_files()

    def _load_episode_data(self):
        """Load all available episode data from TVDB"""
        self.available_episodes.clear()
        # store episodes organized by season type
        self.episodes_by_type = {}

        tvdb_data = (
            self.media_search_payload.tvdb_data if self.media_search_payload else None
        )
        episodes_by_type = tvdb_data.get("episodes_by_type") if tvdb_data else None

        if not episodes_by_type:
            # TVDB returned no episode data at all for this series (or the
            # lookup never populated tvdb_data in the first place). Surface
            # this clearly rather than leaving the episodes tree empty with
            # no explanation -- the user can still map files manually.
            self.episodes_stats_label.setText(NO_TVDB_EPISODE_DATA_MESSAGE)
            return

        # store all episode types for UI
        self.episodes_by_type = episodes_by_type

        # setup dynamic episode order combo based on available types
        self._setup_episode_order_combo_from_data()

        self._load_episodes_with_ordering()

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
            self._sync_release_format_to_order()
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

        # search in specified season or all seasons. identity check, not
        # truthiness -- season 0 is a valid TVDB season (specials), and
        # `season == 0` is falsy in Python.
        seasons_to_search = (
            [season] if season is not None else self.available_episodes.keys()
        )

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

    def _get_absolute_order_episodes(self) -> list[dict[str, Any]]:
        """Return TVDB's "Absolute Order" episode list, if one was fetched.

        This scans all season types the mapper knows about rather than only
        the currently selected TVDB order, so absolute-number matching keeps
        working even when the user is viewing episodes in Aired/DVD order
        while the Anime/Absolute release format is selected -- the release
        format only controls title/filename tokens and doesn't change which
        TVDB order is displayed.
        """
        for type_data in self.episodes_by_type.values():
            order_type = str(type_data.get("type", "")).lower()
            order_name = str(type_data.get("type_name", "")).lower()
            if "absolute" in order_type or "absolute" in order_name:
                return type_data.get("episodes", [])
        return []

    def _get_available_episodes_flat(self) -> list[dict[str, Any]]:
        """Flatten ``self.available_episodes`` (season -> episode -> data)
        into a single list of episode dicts, for matchers that key on a
        field (like ``aired``) rather than the season/episode structure --
        e.g. air-date matching for daily/date releases.
        """
        return [
            episode_data
            for season_episodes in self.available_episodes.values()
            for episode_data in season_episodes.values()
        ]

    def _auto_match_files(self) -> None:
        """Enhanced auto-matching with fuzzy fallback"""
        if not self.available_episodes:
            return

        matched_count = 0
        fuzzy_matched_count = 0

        absolute_format_active = (
            self.get_series_format() == EpisodeFormat.ANIME_ABSOLUTE
        )
        absolute_episodes = (
            self._get_absolute_order_episodes() if absolute_format_active else []
        )
        daily_format_active = self.get_series_format() == EpisodeFormat.DAILY_DATE

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

            # guessit returns a list of episode numbers for files that span
            # multiple episodes (e.g. "S01E01E02"). keep the lowest as the
            # primary episode and carry the highest as the range end so a
            # single file's multi-episode span isn't collapsed to episode 1.
            episode_end = None
            if isinstance(episode, list):
                if episode:
                    episode = sorted(episode)
                    episode, episode_end = episode[0], episode[-1]
                    if episode_end == episode:
                        episode_end = None
                else:
                    episode = None

            # this must use identity checks, not truthiness -- TVDB uses
            # season 0 for specials, and `season == 0` is falsy in Python,
            # so a truthiness check would skip a genuinely parsed "S00E05"
            # even though `available_episodes` has that exact entry (it's
            # populated with an `is not None` check, so season 0 is valid).
            if (
                season is not None
                and episode is not None
                and season in self.available_episodes
                and episode in self.available_episodes[season]
            ):
                # high confidence regex match
                episode_data = self.available_episodes[season][episode]
                confidence = 0.95
                method = "regex"

                self._store_mapping(
                    file_path,
                    season,
                    episode,
                    episode_data,
                    confidence,
                    method,
                    episode_end=episode_end,
                )
                self._update_file_row_assignment(
                    row, season, episode, confidence, method
                )
                matched_count += 1
                continue

            # stage 1b: anime/absolute-numbered releases (e.g.
            # "[Group] Show - 025.mkv") carry no season, just an absolute
            # episode number, so stage 1 above never matches them. When the
            # Anime/Absolute release format is active, match that number
            # against TVDB's absolute-order episode list instead. The
            # `season is None` guard is required: a file that DID parse a
            # real season (e.g. "Show.S05E03.mkv" for a season TVDB has no
            # data for) must fall through to fuzzy/unmatched instead of
            # having its episode digit reinterpreted as an unrelated
            # absolute number.
            if (
                absolute_format_active
                and absolute_episodes
                and episode is not None
                and season is None
            ):
                absolute_match = match_by_absolute(
                    {file_path: episode}, absolute_episodes
                )
                absolute_episode_data = absolute_match.get(file_path)
                if absolute_episode_data is not None:
                    matched_season = absolute_episode_data.get("seasonNumber")
                    matched_episode = absolute_episode_data.get("number")
                    if matched_season is not None and matched_episode is not None:
                        confidence = 0.9
                        method = "absolute"

                        # translate the range end through the same absolute
                        # index used for the primary episode, e.g. for
                        # "[Group] Show - 025-026.mkv" (episode_end=26) so it
                        # renders as the in-season end (S02E04) rather than
                        # the raw absolute number. If the end number doesn't
                        # resolve, or resolves into a different season than
                        # the start, drop it rather than store a bogus value.
                        matched_episode_end = None
                        if episode_end is not None:
                            end_match = match_by_absolute(
                                {file_path: episode_end}, absolute_episodes
                            )
                            end_episode_data = end_match.get(file_path)
                            if end_episode_data is not None:
                                end_season = end_episode_data.get("seasonNumber")
                                end_number = end_episode_data.get("number")
                                if (
                                    end_season == matched_season
                                    and end_number is not None
                                ):
                                    matched_episode_end = end_number

                        self._store_mapping(
                            file_path,
                            matched_season,
                            matched_episode,
                            absolute_episode_data,
                            confidence,
                            method,
                            episode_end=matched_episode_end,
                        )
                        self._update_file_row_assignment(
                            row, matched_season, matched_episode, confidence, method
                        )
                        matched_count += 1
                        continue

            # stage 1c: daily/date releases (e.g. "Show.2024.05.01.mkv")
            # carry no season/episode, just an air date (guessit's `date`
            # key), so stage 1 above never matches them. When the
            # Daily/Date release format is active, match that date against
            # the currently loaded episode list's `aired` field instead.
            # The `season is None and episode is None` guard mirrors stage
            # 1b: a file that DID parse a real season/episode must fall
            # through to fuzzy/unmatched instead of being reinterpreted by
            # date. This must use identity checks, not truthiness -- TVDB
            # uses season 0 for specials, and `season == 0` is falsy in
            # Python, so a truthiness check would wrongly treat a genuinely
            # parsed "S00E01" as season-and-episode-less and let it be
            # hijacked by date.
            parsed_date = parsed_data.get("date")
            if (
                daily_format_active
                and parsed_date is not None
                and season is None
                and episode is None
            ):
                daily_episodes = self._get_available_episodes_flat()
                daily_match = match_by_air_date(
                    {file_path: parsed_date}, daily_episodes
                )
                daily_episode_data = daily_match.get(file_path)
                if daily_episode_data is not None:
                    matched_season = daily_episode_data.get("seasonNumber")
                    matched_episode = daily_episode_data.get("number")
                    if matched_season is not None and matched_episode is not None:
                        confidence = 0.9
                        method = "daily"

                        self._store_mapping(
                            file_path,
                            matched_season,
                            matched_episode,
                            daily_episode_data,
                            confidence,
                            method,
                        )
                        self._update_file_row_assignment(
                            row, matched_season, matched_episode, confidence, method
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
        episode_end: int | None = None,
    ) -> None:
        """Store file-to-episode mapping.

        ``episode_end`` carries the last episode number for a file that spans
        multiple episodes (e.g. a single "S01E01E02" file). It is ``None``
        for a normal single-episode mapping.
        """
        self.file_episode_mappings[file_path] = {
            "season": season,
            "episode": episode,
            "episode_end": episode_end,
            "episode_data": episode_data,
            "episode_name": episode_data.get("name", "Unknown"),
            "confidence": confidence,
            "assignment_method": method,
        }

    def _update_file_row_assignment(
        self, row: int, season: int, episode: int, confidence: float, method: str
    ):
        """Update file table row with assignment data"""
        # block signals while populating cells programmatically: setItem()
        # fires itemChanged, which would otherwise re-enter
        # _on_table_item_changed and re-store this mapping through the
        # "manual" path, clobbering the method/confidence (and episode_end)
        # that were just computed here.
        self.files_table.blockSignals(True)
        try:
            # season (editable, numeric)
            season_item = NumericTableItem(str(season))
            self.files_table.setItem(row, 1, season_item)

            # episode (editable, numeric)
            episode_item = NumericTableItem(str(episode))
            self.files_table.setItem(row, 2, episode_item)

            # confidence with color coding (read only)
            confidence_item = QTableWidgetItem(f"{confidence * 100:.0f}%")
            confidence_item.setFlags(
                confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
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
        finally:
            self.files_table.blockSignals(False)

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

        self.available_episodes.clear()
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
                    if season_num not in self.available_episodes:
                        self.available_episodes[season_num] = {}
                    self.available_episodes[season_num][episode_num] = episode_data
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
        self._sync_release_format_to_order()
        self._load_episodes_with_ordering()
        self._clear_all_assignments()
        self._auto_match_files()

    @Slot(int)
    def _on_release_format_changed(self, _idx: int) -> None:
        if not self._loading_release_format_combo:
            self._release_format_manually_selected = True

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
            has_tvdb_match = (
                season in self.available_episodes
                and episode in self.available_episodes[season]
            )
            if has_tvdb_match:
                episode_data = self.available_episodes[season][episode]
            else:
                # TVDB has no data for this season/episode (or no episode
                # data at all for the series): still store what the user
                # typed using a minimal synthesized payload instead of
                # clearing the row. Otherwise the user has no way to map
                # this file at all, and the wizard has no Back button to
                # escape the resulting dead end.
                episode_data = {
                    "season": season,
                    "episode": episode,
                    "name": None,
                    "aired": None,
                }

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
            method_item = QTableWidgetItem(method)
            method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if has_tvdb_match:
                confidence_item.setBackground(Qt.GlobalColor.green)  # Manual = green
                # season/episode items are already attached to the table;
                # a previous edit may have painted them amber (unverified
                # manual mapping) before this correction matched TVDB
                # data, so reset them back to the table default. block
                # signals while touching them so setBackground() (which
                # emits itemChanged) doesn't re-enter this slot
                self.files_table.blockSignals(True)
                try:
                    season_item.setBackground(Qt.GlobalColor.transparent)
                    episode_item.setBackground(Qt.GlobalColor.transparent)
                finally:
                    self.files_table.blockSignals(False)
            else:
                # amber: manual entry not confirmed against TVDB data
                unverified_color = QColor(255, 205, 120)
                confidence_item.setBackground(unverified_color)
                method_item.setBackground(unverified_color)
                # season/episode items are already attached to the table;
                # block signals while touching them so setBackground()
                # (which emits itemChanged) doesn't re-enter this slot
                self.files_table.blockSignals(True)
                try:
                    season_item.setBackground(unverified_color)
                    episode_item.setBackground(unverified_color)
                finally:
                    self.files_table.blockSignals(False)

            self.files_table.setItem(row, 3, confidence_item)
            self.files_table.setItem(row, 4, method_item)

        except Exception as e:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Failed to process manual season/episode edit for "
                f"'{file_path.name}': {e}",
            )

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

        # reset season/episode background: a previous edit may have
        # painted them amber (unverified manual mapping), but the mapping
        # no longer exists so the cells should show no special color.
        # block signals while touching them so setBackground() (which
        # emits itemChanged) doesn't re-enter _on_table_item_changed
        season_item = self.files_table.item(row, 1)
        episode_item = self.files_table.item(row, 2)
        if season_item is not None and episode_item is not None:
            self.files_table.blockSignals(True)
            try:
                season_item.setBackground(Qt.GlobalColor.transparent)
                episode_item.setBackground(Qt.GlobalColor.transparent)
            finally:
                self.files_table.blockSignals(False)

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
        """Get the current file-to-episode mappings.

        Each mapping value may include an ``episode_end`` key (``int | None``)
        when a single file spans multiple episodes (e.g. "S01E01E02").
        """
        return self.file_episode_mappings.copy()

    def get_simple_mappings(self) -> dict[str, dict[str, Any]]:
        """Get simplified mappings: {filename: {season, episode, episode_end, confidence_percent}}"""
        simple_mappings = {}

        for file_path, mapping_data in self.file_episode_mappings.items():
            simple_mappings[file_path.name] = {
                "season": mapping_data["season"],
                "episode": mapping_data["episode"],
                "episode_end": mapping_data.get("episode_end"),
                # convert to 0-100%
                "confidence": int(mapping_data["confidence"] * 100),
                "method": mapping_data["assignment_method"],
                "episode_name": mapping_data["episode_name"],
            }

        return simple_mappings

    def get_path_mappings(self) -> dict[str, dict[str, Any]]:
        """Get mappings with full file paths: {file_path: {season, episode, episode_end, confidence_percent}}"""
        path_mappings = {}

        for file_path, mapping_data in self.file_episode_mappings.items():
            path_mappings[str(file_path)] = {
                "season": mapping_data["season"],
                "episode": mapping_data["episode"],
                "episode_end": mapping_data.get("episode_end"),
                # convert to 0-100%
                "confidence": int(mapping_data["confidence"] * 100),
                "method": mapping_data["assignment_method"],
                "episode_name": mapping_data["episode_name"],
            }

        return path_mappings

    def get_episode_map(self) -> dict | None:
        """Get episode mappings.

        Values may include an ``episode_end`` key (``int | None``) marking the
        last episode number for a file that spans multiple episodes.
        """
        return self.file_episode_mappings

    def is_valid(self) -> bool:
        """Check that every file is mapped and no two files target overlapping episodes.

        A mapping is expanded to every ``(season, episode)`` pair it covers --
        a normal single-episode mapping covers just its own ``episode``, while
        a multi-episode mapping (``episode_end`` set, e.g. a single
        "S01E01E02" file) covers every episode from ``episode`` through
        ``episode_end`` inclusive. If any ``(season, episode)`` pair is
        claimed by more than one file, the mappings overlap and this returns
        ``False`` -- this generalizes the old exact-duplicate-start check,
        which missed overlaps like file A "S01E01-E02" and file B "S01E02":
        their start tuples ``(1, 1)`` and ``(1, 2)`` differ even though both
        claim S01E02.
        """
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return False

        if len(self.file_episode_mappings) != len(self.media_input_payload.file_list):
            return False

        claimed_targets: set[tuple[Any, Any]] = set()
        for mapping in self.file_episode_mappings.values():
            season = mapping.get("season")
            episode = mapping.get("episode")
            episode_end = mapping.get("episode_end")
            range_end = episode_end if episode_end is not None else episode

            if episode is None or range_end is None:
                target = (season, episode)
                if target in claimed_targets:
                    return False
                claimed_targets.add(target)
                continue

            for target_episode in range(episode, range_end + 1):
                target = (season, target_episode)
                if target in claimed_targets:
                    return False
                claimed_targets.add(target)

        return True

    def has_tvdb_episode_data(self) -> bool:
        """Whether TVDB returned any episode data for the current series."""
        return bool(self.episodes_by_type)

    def has_unmapped_files(self) -> bool:
        """Whether at least one input file still lacks a season/episode mapping."""
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return False
        return len(self.file_episode_mappings) < len(
            self.media_input_payload.file_list
        )

    def get_series_format(self) -> EpisodeFormat:
        """Get the output format for renaming/title tokens."""
        return EpisodeFormat(self.release_format_combo.currentData())

    def _sync_release_format_to_order(self) -> None:
        """Default release format from TVDB order until the user picks one."""
        if self._release_format_manually_selected:
            return

        release_format = self._default_release_format_for_current_order()
        self._loading_release_format_combo = True
        try:
            self._set_release_format(release_format, manually_selected=False)
        finally:
            self._loading_release_format_combo = False

    def _default_release_format_for_current_order(self) -> EpisodeFormat:
        type_id = self.episode_order_combo.currentData()
        type_data = self.episodes_by_type.get(type_id, {}) if type_id else {}
        order_type = str(type_data.get("type", "")).lower()
        order_name = str(type_data.get("type_name", "")).lower()

        if "absolute" in order_type or "absolute" in order_name:
            return EpisodeFormat.ANIME_ABSOLUTE
        return EpisodeFormat.STANDARD

    def _set_release_format(
        self, release_format: EpisodeFormat, manually_selected: bool
    ) -> None:
        release_format = EpisodeFormat(release_format)
        was_loading = self._loading_release_format_combo
        self._loading_release_format_combo = True
        try:
            for idx in range(self.release_format_combo.count()):
                if self.release_format_combo.itemData(idx) == release_format:
                    self.release_format_combo.setCurrentIndex(idx)
                    break
        finally:
            self._loading_release_format_combo = was_loading
        self._release_format_manually_selected = manually_selected
