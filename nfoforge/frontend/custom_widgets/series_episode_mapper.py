from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor
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
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nfoforge.backend.utils.episode_matching import (
    TITLE_DISAGREEMENT_FLOOR,
    ParsedFile,
    TitleCheck,
    claimed_season_episodes,
    episode_designator,
    episode_spec_text,
    expand_mapping_episodes,
    parse_episode_spec,
    rank_episode_orderings,
)
from nfoforge.config.tv_tokens import SUPPORTED_TVR_FORMATS
from nfoforge.core.series.match import (
    UNVERIFIED_PARSE_CONFIDENCE,
    UNVERIFIED_PARSE_METHOD,
    EpisodeData,
    EpisodeMapping,
    EpisodeMatcher,
    method_label,
    parsed_file_summary,
)
from nfoforge.enums.series import EpisodeFormat
from nfoforge.frontend.custom_widgets.custom_splitter import CustomSplitter
from nfoforge.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from nfoforge.logger.nfo_forge_logger import LOG
from nfoforge.payloads.media_inputs import MediaInputPayload
from nfoforge.payloads.media_search import MediaSearchPayload

NO_TVDB_EPISODE_DATA_MESSAGE = (
    "TVDB returned no episode data for this series; enter season/episode manually."
)
NO_TVDB_EPISODE_DATA_STYLE = "color: #b3261e; font-weight: bold;"
TITLE_MISMATCH_STYLE = "color: #8a5300; font-weight: bold;"


class EpisodeSpecTableItem(QTableWidgetItem):
    """Editable cell holding the episodes one file covers.

    Accepts a span -- ``1-2``, ``1,5`` -- rather than a single number, which
    is the only way to say "this file covers both parts of the premiere".
    The digits-only cell it replaces could not express that at all: a span
    survived only where GuessIt had parsed one out of the filename, and
    retyping the episode silently dropped it.

    Input is not filtered as it is typed, because a half-typed ``1-`` is not
    yet wrong; ``parse_episode_spec`` decides what a completed edit means.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsEditable)
        self.setToolTip(
            "Episodes this file covers: 1, or 1-2 for a two-part episode, "
            "or 1,5 for separate episodes."
        )


class TitleOverrideTableItem(QTableWidgetItem):
    """Editable cell holding a title to use instead of the provider's."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsEditable)
        self.setToolTip(
            "Leave blank to use the episode title from TVDB. Anything typed "
            "here is what the renamed file and the release title will carry."
        )


class EnhancedFileTableItem(QTableWidgetItem):
    """Enhanced table item for files with episode data"""

    def __init__(self, text: str, file_path: Path) -> None:
        super().__init__(text)
        self.file_path = file_path
        self.parsed_data: EpisodeData = {}
        self.assigned_season: int | None = None
        self.assigned_episode: int | None = None
        self.confidence = 0.0
        self.assignment_method = "unassigned"


class NumericTableItem(QTableWidgetItem):
    """Table item that only accepts numeric input"""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        # set flags to be editable
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsEditable)

    def setData(self, role: int, value: Any) -> None:
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
    episode_data: EpisodeData
    name: str = ""
    is_assigned: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            self.name = str(self.episode_data.get("name", "Unknown Episode"))


class SeriesEpisodeMapper(QWidget):
    mapping_changed = Signal()
    validation_changed = Signal(bool)

    # Files table columns. Named because the literals were spread over a
    # dozen call sites, so inserting one column meant finding every 3 and 4
    # that happened to mean "confidence" and "method".
    COL_FILENAME = 0
    COL_SEASON = 1
    COL_EPISODE = 2
    COL_MATCHED = 3
    COL_TITLE = 4
    COL_CONFIDENCE = 5
    COL_METHOD = 6
    _COLUMN_COUNT = 7
    #: Columns the user can type into, and so the only ones worth reacting to.
    _EDITABLE_COLUMNS = (1, 2, 4)

    # Semantic cell colours. The foreground is set alongside every background:
    # the app's default text colour follows the theme, and on the dark theme it
    # is near-white, which is unreadable on any of these.
    _CELL_FOREGROUND = QColor(20, 20, 20)
    _CONFIDENCE_HIGH_COLOR = QColor(200, 255, 200)  # confidence >= 90%
    _CONFIDENCE_MEDIUM_COLOR = QColor(255, 243, 150)  # confidence >= 70%
    _CONFIDENCE_LOW_COLOR = QColor(255, 179, 179)  # confidence below 70%
    _ASSIGNED_EPISODE_COLOR = QColor(200, 255, 200)  # assigned tree row
    _UNASSIGNED_EPISODE_COLOR = QColor(255, 220, 220)  # unassigned tree row
    _SEARCH_HIGHLIGHT_COLOR = QColor(255, 243, 150)  # search term match
    _MANUAL_MATCH_COLOR = QColor(200, 255, 200)  # manual edit matched TVDB
    _MANUAL_UNVERIFIED_COLOR = QColor(255, 205, 120)  # manual edit unverified

    @contextmanager
    def _suppress_table_signals(self) -> Iterator[None]:
        """Write to the files table without re-entering the edit handler.

        Every ``setItem`` and every ``setBackground`` emits ``itemChanged``,
        so any programmatic write re-enters ``_on_table_item_changed`` -- and
        that path re-stores the row as a manual edit, overwriting the method
        and confidence just computed, or deletes the mapping outright while
        blank cells are going in. Nests safely, so a caller need not know
        whether its own caller already blocked.
        """
        previously_blocked = self.files_table.signalsBlocked()
        self.files_table.blockSignals(True)
        try:
            yield
        finally:
            self.files_table.blockSignals(previously_blocked)

    @classmethod
    def _paint_cell(
        cls, item: QTableWidgetItem | QTreeWidgetItem, colour: QColor, column: int = 0
    ) -> None:
        """Set a background and a foreground legible against it."""
        if isinstance(item, QTreeWidgetItem):
            item.setBackground(column, colour)
            item.setForeground(column, cls._CELL_FOREGROUND)
        else:
            # a QTableWidgetItem represents a single cell, so `column` has no
            # meaning here; a non-default value would be silently dropped.
            if column != 0:
                raise ValueError(
                    "column is meaningless for a QTableWidgetItem, which represents a single cell"
                )
            item.setBackground(colour)
            item.setForeground(cls._CELL_FOREGROUND)

    @classmethod
    def _clear_cell_paint(
        cls, item: QTableWidgetItem | QTreeWidgetItem, column: int = 0
    ) -> None:
        """Reset both brushes so the theme's own colours apply again."""
        if isinstance(item, QTreeWidgetItem):
            item.setBackground(column, QBrush())
            item.setForeground(column, QBrush())
        else:
            if column != 0:
                raise ValueError(
                    "column is meaningless for a QTableWidgetItem, which represents a single cell"
                )
            item.setBackground(QBrush())
            item.setForeground(QBrush())

    @property
    def available_episodes(self) -> dict[int, dict[int, EpisodeData]]:
        return self.matcher.available_episodes

    @available_episodes.setter
    def available_episodes(self, value: dict[int, dict[int, EpisodeData]]) -> None:
        self.matcher.available_episodes = value

    @property
    def episodes_by_type(self) -> dict[Any, EpisodeData]:
        return self.matcher.episodes_by_type

    @episodes_by_type.setter
    def episodes_by_type(self, value: dict[Any, EpisodeData]) -> None:
        self.matcher.episodes_by_type = value

    @property
    def file_episode_mappings(self) -> dict[Path, EpisodeMapping]:
        return self.matcher.mappings

    @file_episode_mappings.setter
    def file_episode_mappings(self, value: dict[Path, EpisodeMapping]) -> None:
        self.matcher.mappings = value

    @property
    def _guessit_cache(self) -> dict[Path, EpisodeData]:
        return self.matcher.parsed

    def _sync_matcher(self) -> EpisodeMatcher:
        """Hand the matcher what this widget's controls currently say."""
        matcher = self.matcher
        matcher.order_type_id = self.episode_order_combo.currentData()
        matcher.series_format = self.get_series_format()
        matcher.show_title = (
            self.media_search_payload.title if self.media_search_payload else None
        )
        matcher.fuzzy_enabled = self.enable_fuzzy_checkbox.isChecked()
        matcher.fuzzy_threshold = float(self.fuzzy_threshold_spin.value())
        return matcher

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # store payloads (can be set later)
        self.media_input_payload = None
        self.media_search_payload = None

        # episode data and mappings: the matcher owns them, this widget shows
        # them and forwards its controls to it
        self.matcher = EpisodeMatcher()
        self.episode_items: list[EpisodeListItem] = []
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
        self.auto_match_btn.clicked.connect(self._on_re_match_all_clicked)

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
        self.files_table.setColumnCount(self._COLUMN_COUNT)
        self.files_table.setHorizontalHeaderLabels(
            (
                "Filename",
                "Season",
                "Episode(s)",
                "Matched Episode",
                "Title Override",
                "Confidence",
                "Method",
            )
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            self.COL_FILENAME, QHeaderView.ResizeMode.Stretch
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            self.COL_SEASON, QHeaderView.ResizeMode.ResizeToContents
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            self.COL_EPISODE, QHeaderView.ResizeMode.ResizeToContents
        )
        # The episode a row is bound to is the one thing the user has to be
        # able to check at a glance: a number that matches while the name it
        # points at is wrong is exactly how a whole pack went out misnamed.
        self.files_table.horizontalHeader().setSectionResizeMode(
            self.COL_MATCHED, QHeaderView.ResizeMode.Stretch
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            self.COL_TITLE, QHeaderView.ResizeMode.Stretch
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            self.COL_CONFIDENCE, QHeaderView.ResizeMode.ResizeToContents
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            self.COL_METHOD, QHeaderView.ResizeMode.ResizeToContents
        )

        self.files_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.files_table.setAlternatingRowColors(True)
        # self.files_table.itemSelectionChanged.connect(self._on_file_selection_changed)
        self.files_table.itemChanged.connect(self._on_table_item_changed)

        self.files_stats_label = QLabel("Files: 0 total, 0 assigned")

        # Raised when most of the pack's filenames name a different episode
        # than the one their numbers landed on. That is one ordering problem,
        # not twenty row problems, so it is said once here rather than by
        # painting every row amber -- if everything is flagged, nothing is.
        self.title_warning_label = QLabel("")
        self.title_warning_label.setStyleSheet(TITLE_MISMATCH_STYLE)
        self.title_warning_label.setWordWrap(True)
        self.title_warning_label.hide()

        files_layout = QVBoxLayout(files_group)
        files_layout.addWidget(self.title_warning_label)
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
        # Index, not text: the item labels carry the fit evidence and are
        # rewritten whenever the files change, and a text-keyed signal would
        # read every relabel as the user picking a different ordering and
        # clear every assignment.
        self.episode_order_combo.currentIndexChanged.connect(
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

        # Adopt whatever mapping has already been committed for these files
        # -- a resumed saved job, or simply this page being entered a second
        # time. Without this the widget's own dict was the only store, so
        # every visit started from scratch and any row the user had fixed by
        # hand (or any row auto-matching cannot re-derive) was silently lost
        # and the page failed validation again.
        self._seed_mappings_from_payload()

        # load and populate data
        self._load_episode_data()
        self._populate_files_table()
        self._restore_existing_assignments()
        self._auto_match_files(preserve_existing=True)

    def _seed_mappings_from_payload(self) -> None:
        """Adopt the committed ``series_episode_map`` for the current files.

        Rows are copied so later edits in the widget do not mutate the payload
        before the page commits, and only rows whose file is still in the
        input list are taken -- a stale row would otherwise keep a mapping
        alive for a file the user has since removed.
        """
        if not self.media_input_payload:
            return

        committed = self.media_input_payload.series_episode_map
        if not committed:
            return

        current_files = set(self.media_input_payload.file_list or ())
        for file_path, mapping in committed.items():
            if file_path in current_files and isinstance(mapping, dict):
                self.file_episode_mappings.setdefault(file_path, dict(mapping))

    def _restore_existing_assignments(self) -> None:
        """Render the rows already held in ``file_episode_mappings``.

        ``_populate_files_table`` writes every row blank, so anything adopted
        or carried over has to be painted back into the table before
        auto-matching runs, or it would be invisible and look unmapped.
        """
        for row in range(self.files_table.rowCount()):
            filename_item = self.files_table.item(row, self.COL_FILENAME)
            if not isinstance(filename_item, EnhancedFileTableItem):
                continue

            mapping = self.file_episode_mappings.get(filename_item.file_path)
            if not mapping:
                continue

            season = mapping.get("season")
            episode = mapping.get("episode")
            if season is None or episode is None:
                continue

            self._update_file_row_assignment(row, mapping)

    def _load_episode_data(self) -> None:
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
            # no explanation -- the user can still map files manually. Style
            # it distinctly so it isn't mistaken for the plain stats message
            # this label normally shows.
            self.episodes_stats_label.setStyleSheet(NO_TVDB_EPISODE_DATA_STYLE)
            self.episodes_stats_label.setText(NO_TVDB_EPISODE_DATA_MESSAGE)
            return

        # TVDB returned real episode data: clear any warning styling left
        # over from a previous "no episode data" state so it doesn't stick.
        self.episodes_stats_label.setStyleSheet("")

        # store all episode types for UI
        self.episodes_by_type = episodes_by_type

        # setup dynamic episode order combo based on available types
        self._setup_episode_order_combo_from_data()

        self._load_episodes_with_ordering()

    def _parsed_files(self) -> list[ParsedFile]:
        """What each input filename claims, parsing and caching as needed.

        Reads the input list rather than the files table, because the
        ordering is chosen while episode data loads -- before the table has
        been built.
        """
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return []
        return [
            parsed_file_summary(self.matcher.parse(file_path))
            for file_path in self.media_input_payload.file_list
        ]

    def _committed_order_type_id(self) -> Any | None:
        """The ordering the rows already adopted were built against."""
        for mapping in self.file_episode_mappings.values():
            type_id = mapping.get("episode_order_type_id")
            if type_id is not None:
                return type_id
        return None

    def _setup_episode_order_combo_from_data(self) -> None:
        """Fill the ordering combo, best fit for these files selected.

        The selection used to be item 0 -- whichever ordering TVDB happened
        to serve first. That is not a choice: the same season/episode pair
        names a different episode in each ordering, so landing on the wrong
        one re-points every file after the first divergence, at full
        confidence and with nothing on screen saying so. Each item now
        carries the evidence it was ranked on, so a user who disagrees can
        see what they are overriding.
        """
        if not self.episodes_by_type:
            return

        ranked = rank_episode_orderings(
            self._parsed_files(),
            self.episodes_by_type,
            prefer_type_id=self._committed_order_type_id(),
            allow_absolute=self.get_series_format() is EpisodeFormat.ANIME_ABSOLUTE,
        )
        summaries = {score.type_id: score.summary() for score in ranked}
        best_type_id = ranked[0].type_id if ranked else None

        self.episode_order_combo.blockSignals(True)
        try:
            self.episode_order_combo.clear()

            selected_index = 0
            for index, (type_id, type_data) in enumerate(self.episodes_by_type.items()):
                type_name = type_data.get("type_name", f"Type {type_id}")
                summary = summaries.get(type_id)
                if summary is None:
                    # Not ranked (absolute order on a non-absolute release);
                    # still selectable, just without a fit figure.
                    summary = f"{len(type_data.get('episodes', []))} eps"
                self.episode_order_combo.addItem(f"{type_name} — {summary}", type_id)
                if type_id == best_type_id:
                    selected_index = index

            if self.episode_order_combo.count() > 0:
                self.episode_order_combo.setCurrentIndex(selected_index)
                self._sync_release_format_to_order()
        finally:
            self.episode_order_combo.blockSignals(False)

    def _populate_files_table(self) -> None:
        """Populate the files table with file data"""
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return

        # Block signals for the whole build. Every setItem() below fires
        # itemChanged, and the blank Season/Episode cells this writes drive
        # _on_table_item_changed down its "either field is empty" path, which
        # deletes the row's mapping. Re-entering the page therefore discarded
        # every mapping it was about to display -- including a hand-typed one
        # that auto-matching cannot re-derive. It also rebuilt the whole
        # episodes tree once per row.
        self.files_table.blockSignals(True)
        try:
            self._populate_files_table_rows()
        finally:
            self.files_table.blockSignals(False)

        self._update_files_stats()

    def _populate_files_table_rows(self) -> None:
        """Write one row per input file. Caller blocks the table's signals."""
        if not self.media_input_payload:
            return

        self.files_table.setRowCount(len(self.media_input_payload.file_list))

        for row, file_path in enumerate(self.media_input_payload.file_list):
            # Parse each filename at most once for this mapper.  Loading the
            # same page again should not repeat the relatively expensive
            # GuessIt work on the GUI thread.
            parsed_data = self._guessit_cache.get(file_path)
            if parsed_data is None:
                parsed_data = self.matcher.parse(file_path)
            else:
                parsed_data = dict(parsed_data)

            # create filename item (read only)
            filename_item = EnhancedFileTableItem(file_path.name, file_path)
            filename_item.parsed_data = parsed_data
            filename_item.setFlags(filename_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.files_table.setItem(row, self.COL_FILENAME, filename_item)

            # season column (editable, numeric only)
            season_item = NumericTableItem("")
            self.files_table.setItem(row, self.COL_SEASON, season_item)

            # episode column (editable, accepts a span)
            episode_item = EpisodeSpecTableItem("")
            self.files_table.setItem(row, self.COL_EPISODE, episode_item)

            # title override column (editable, blank means "use TVDB's")
            title_item = TitleOverrideTableItem("")
            self.files_table.setItem(row, self.COL_TITLE, title_item)

            # matched episode column (read only)
            matched_item = QTableWidgetItem("")
            matched_item.setFlags(matched_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.files_table.setItem(row, self.COL_MATCHED, matched_item)

            # confidence column (read only)
            confidence_item = QTableWidgetItem("")
            confidence_item.setFlags(
                confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            self.files_table.setItem(row, self.COL_CONFIDENCE, confidence_item)

            # method column (read only)
            method_item = QTableWidgetItem("")
            method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.files_table.setItem(row, self.COL_METHOD, method_item)

    def _fuzzy_match_episode_name(
        self,
        filename: str,
        season: int | None = None,
        parsed_data: EpisodeData | None = None,
        claimed_by: Path | None = None,
        min_score: float | None = None,
    ) -> tuple[int, tuple[int, ...], float] | None:
        """See `EpisodeMatcher.fuzzy_match_episode_name`."""
        return self._sync_matcher().fuzzy_match_episode_name(
            filename, season, parsed_data, claimed_by, min_score
        )

    def _auto_match_files(self, preserve_existing: bool = False) -> None:
        """Match every file in the table, then show the result.

        ``preserve_existing`` leaves rows that already carry a mapping
        untouched and matches only the rest. Page load passes it so that
        re-entering the page cannot overwrite a correction the user made --
        auto-matching would otherwise recompute the same wrong answer that
        was corrected. The "Re-match All" button deliberately does not,
        because discarding the current answers is the whole point of it.
        """
        if not self.available_episodes:
            return

        rows = {
            item.file_path: row
            for row in range(self.files_table.rowCount())
            if isinstance(
                item := self.files_table.item(row, self.COL_FILENAME),
                EnhancedFileTableItem,
            )
        }
        before = {path: self.file_episode_mappings.get(path) for path in rows}
        self._sync_matcher().match_files(list(rows), preserve_existing)

        # Repaint only the rows matching changed. A row it could not place
        # keeps whatever is in its cells -- a season typed to narrow a later
        # fuzzy match, say.
        for file_path, row in rows.items():
            mapping = self.file_episode_mappings.get(file_path)
            if mapping is not None and mapping is not before[file_path]:
                self._update_file_row_assignment(row, mapping)

        self._update_title_warning()
        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _update_title_warning(self) -> None:
        """Say once when the pack as a whole disagrees with this ordering.

        Counted from the scores stored on the rows rather than tallied as
        matching runs, so it is equally right after an ordering change, which
        re-resolves rows in place instead of re-matching them.
        """
        checked, disagreements = self.matcher.title_disagreements()

        if checked < 2 or disagreements * 2 <= checked:
            self.title_warning_label.hide()
            self.title_warning_label.clear()
            return

        order_name = self.episode_order_combo.currentText().split(" — ")[0]
        self.title_warning_label.setText(
            f"{disagreements} of {checked} filenames name a different episode "
            f"than {order_name or 'this ordering'} does at the same number. "
            "Check the episode order above before continuing."
        )
        self.title_warning_label.show()

    @Slot()
    def _on_re_match_all_clicked(self) -> None:
        """Button handler for "Re-match All".

        The empty-episode-data message lives here rather than in
        ``_auto_match_files`` because that method also runs on page load
        (``load_data``), on release-order changes
        (``_on_episode_order_changed``), and on ``load_media_input_data`` --
        all paths where an empty episode list is already reported inline via
        ``NO_TVDB_EPISODE_DATA_MESSAGE`` on ``episodes_stats_label``. Showing
        a blocking modal there turned a silent no-op into a nag on every page
        visit.
        """
        if not self.available_episodes:
            QMessageBox.information(
                self,
                "No Episode Data",
                "There is no TVDB episode data loaded, so files cannot be "
                "re-matched. Set a TVDB ID on the previous page and try again.",
            )
            return
        self._auto_match_files()

    def _fuzzy_match_unassigned(self) -> None:
        """Run fuzzy matching specifically on unassigned files"""
        fuzzy_matched = 0

        for row in range(self.files_table.rowCount()):
            filename_item = self.files_table.item(row, self.COL_FILENAME)
            if not isinstance(filename_item, EnhancedFileTableItem):
                continue

            # A season-only row is intentionally eligible: users commonly
            # enter the season first to constrain fuzzy matching. Only skip a
            # row when both editable assignment fields are populated.
            season_item = self.files_table.item(row, self.COL_SEASON)
            episode_item = self.files_table.item(row, self.COL_EPISODE)
            season_text = season_item.text().strip() if season_item else ""
            episode_text = episode_item.text().strip() if episode_item else ""
            if season_text and episode_text:
                continue

            file_path = filename_item.file_path

            # Prefer a manually entered season, then GuessIt's parsed season,
            # so duplicate episode names in different seasons stay scoped to
            # the user's intended season.
            season = None
            if season_text:
                try:
                    season = int(season_text)
                except ValueError:
                    season = None

            if self._sync_matcher().fuzzy_match_file(file_path, season):
                self._update_file_row_assignment(
                    row, self.file_episode_mappings[file_path]
                )
                fuzzy_matched += 1

        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _store_mapping(self, *args: Any, **kwargs: Any) -> EpisodeMapping:
        """See `EpisodeMatcher.store_mapping`."""
        return self.matcher.store_mapping(*args, **kwargs)

    def _title_check_for(
        self, file_path: Path, season: int, episode: int
    ) -> TitleCheck:
        """See `EpisodeMatcher.title_check_for`."""
        return self.matcher.title_check_for(file_path, season, episode)

    def _update_file_row_assignment(
        self, row: int, mapping: EpisodeMapping, rewrite_inputs: bool = True
    ) -> None:
        """Render one stored mapping into its table row.

        Takes the row itself rather than a handful of scalars so the cells
        can show everything it holds -- in particular the episode it is bound
        to. A season and an episode number that look right while naming the
        wrong episode is exactly how a pack goes out misnamed, and nothing in
        this table used to say which episode a row had actually landed on.

        ``rewrite_inputs`` is False when the user is the one who just typed
        into this row: replacing the cells they are editing would throw away
        the edit in progress, so those are repainted rather than rebuilt.
        """
        season = mapping.get("season")
        confidence = float(mapping.get("confidence", 0.0))
        method = str(mapping.get("assignment_method", ""))
        verified = bool(mapping.get("verified", bool(mapping.get("episode_data"))))

        # A row whose own filename names a different episode is no more
        # trustworthy than one TVDB cannot confirm, so it is flagged the same
        # way rather than sitting at a reassuring 95%.
        score = mapping.get("title_match_score")
        if isinstance(score, (int, float)) and score < TITLE_DISAGREEMENT_FLOOR:
            verified = False
        override = mapping.get("episode_title_override")

        with self._suppress_table_signals():
            if rewrite_inputs:
                self.files_table.setItem(
                    row, self.COL_SEASON, NumericTableItem(str(season))
                )
                self.files_table.setItem(
                    row,
                    self.COL_EPISODE,
                    EpisodeSpecTableItem(episode_spec_text(mapping)),
                )
                self.files_table.setItem(
                    row, self.COL_TITLE, TitleOverrideTableItem(str(override or ""))
                )
            else:
                # Repaint the cells the user is typing into so a correction
                # that now matches TVDB loses its amber, and one that still
                # does not keeps it.
                for column in (self.COL_SEASON, self.COL_EPISODE):
                    cell = self.files_table.item(row, column)
                    if cell is None:
                        continue
                    if verified:
                        self._clear_cell_paint(cell)
                    else:
                        self._paint_cell(cell, self._MANUAL_UNVERIFIED_COLOR)

            # the episode this row actually resolved to (read only)
            matched_item = QTableWidgetItem(self._matched_episode_text(mapping))
            matched_item.setFlags(matched_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not verified:
                self._paint_cell(matched_item, self._MANUAL_UNVERIFIED_COLOR)
            self.files_table.setItem(row, self.COL_MATCHED, matched_item)

            # confidence with color coding (read only)
            confidence_item = QTableWidgetItem(f"{confidence * 100:.0f}%")
            confidence_item.setFlags(
                confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            if not verified:
                # amber, matching the manual-entry path: the numbers stand,
                # TVDB just cannot confirm them.
                self._paint_cell(confidence_item, self._MANUAL_UNVERIFIED_COLOR)
            elif confidence >= 0.9:
                self._paint_cell(confidence_item, self._CONFIDENCE_HIGH_COLOR)
            elif confidence >= 0.7:
                self._paint_cell(confidence_item, self._CONFIDENCE_MEDIUM_COLOR)
            else:
                self._paint_cell(confidence_item, self._CONFIDENCE_LOW_COLOR)
            self.files_table.setItem(row, self.COL_CONFIDENCE, confidence_item)

            # method (read only)
            method_item = QTableWidgetItem(method)
            method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not verified:
                self._paint_cell(method_item, self._MANUAL_UNVERIFIED_COLOR)
            self.files_table.setItem(row, self.COL_METHOD, method_item)

    @staticmethod
    def _matched_episode_text(mapping: EpisodeMapping) -> str:
        """``S01E01-E02 - Lost & Found``, or a note when nothing confirms it."""
        designator = episode_designator(mapping)
        if not designator:
            return ""

        override = mapping.get("episode_title_override")
        name = override if override else mapping.get("episode_name")
        if not name:
            return f"{designator}  (not listed in this order)"
        return f"{designator}  {name}"

    def _clear_all_assignments(self) -> None:
        """Clear all file assignments"""
        self.file_episode_mappings.clear()

        # Same signal hazard as _populate_files_table: the blank cells written
        # below would re-enter _on_table_item_changed and rebuild the episodes
        # tree once per row.
        self.files_table.blockSignals(True)
        try:
            self._clear_assignment_cells()
        finally:
            self.files_table.blockSignals(False)

        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _clear_assignment_cells(self) -> None:
        """Blank every row's editable and status cells. Caller blocks signals."""
        # clear table cells while preserving edit flags
        for row in range(self.files_table.rowCount()):
            # clear Season (keep editable, numeric only)
            season_item = NumericTableItem("")
            self.files_table.setItem(row, self.COL_SEASON, season_item)

            # clear Episode (keep editable, numeric only)
            episode_item = NumericTableItem("")
            self.files_table.setItem(row, self.COL_EPISODE, episode_item)

            # clear Title Override (keep editable)
            self.files_table.setItem(row, self.COL_TITLE, TitleOverrideTableItem(""))

            # clear Matched Episode (read-only)
            matched_item = QTableWidgetItem("")
            matched_item.setFlags(matched_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._clear_cell_paint(matched_item)
            self.files_table.setItem(row, self.COL_MATCHED, matched_item)

            # clear Confidence (read-only)
            confidence_item = QTableWidgetItem("")
            confidence_item.setFlags(
                confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            self._clear_cell_paint(confidence_item)
            self.files_table.setItem(row, self.COL_CONFIDENCE, confidence_item)

            # clear Method (read-only)
            method_item = QTableWidgetItem("")
            method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.files_table.setItem(row, self.COL_METHOD, method_item)

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
        season_counts: dict[int, int] = {}
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

        # Get all assigned episodes for marking purposes. A file covering
        # several episodes claims every one of them, not only the first: with
        # just the start counted, a single "S01E01-E02" file left the season
        # reading "19/20 assigned" with E02 painted unassigned -- a gap the
        # user has no file to fill and no way to act on, while validation
        # (which does expand the span) was already satisfied.
        assigned_episodes: set[tuple[Any, int]] = set()
        for mapping in self.file_episode_mappings.values():
            assigned_episodes.update(claimed_season_episodes(mapping))

        # update episode items to reflect assignment status
        for episode_item in self.episode_items:
            episode_item.is_assigned = (
                episode_item.season,
                episode_item.episode,
            ) in assigned_episodes

        # count total episodes per season from ALL episodes in current ordering
        total_episodes_per_season: dict[int, int] = {}
        for episode in self.episode_items:
            season = episode.season
            if season not in total_episodes_per_season:
                total_episodes_per_season[season] = 0
            total_episodes_per_season[season] += 1

        # group episodes by season (apply filters)
        seasons_data: dict[int, list[EpisodeListItem]] = {}
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
                    for col in range(4):
                        self._paint_cell(tree_item, self._ASSIGNED_EPISODE_COLOR, col)
                else:
                    # light red background to make them stand out
                    for col in range(4):
                        self._paint_cell(tree_item, self._UNASSIGNED_EPISODE_COLOR, col)

                # highlight search terms (override assignment color if searching)
                if search_text and search_text in episode_item.name.lower():
                    self._paint_cell(tree_item, self._SEARCH_HIGHLIGHT_COLOR, 0)

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

    def _update_all_stats(self) -> None:
        """Update all statistics"""
        self._update_files_stats()
        self._update_episodes_stats()

    @Slot(int)
    def _on_episode_order_changed(self, _index: int) -> None:
        """Re-read the same season/episode numbers against a new ordering.

        Clearing every assignment first threw away the user's own edits for
        no reason: the numbers a row holds are the user's answer, and only
        the episode each one names changes with the ordering. Rows are
        re-resolved in place, and auto-matching then fills in whatever still
        has no mapping.
        """
        self._sync_release_format_to_order()
        self._load_episodes_with_ordering()
        self._reresolve_mappings_for_ordering()
        self._auto_match_files(preserve_existing=True)

    def _reresolve_mappings_for_ordering(self) -> None:
        """Point every existing row at the current ordering's episodes."""
        order_type_id = self.episode_order_combo.currentData()

        for file_path, mapping in self.file_episode_mappings.items():
            season = mapping.get("season")
            episode = mapping.get("episode")
            if not isinstance(season, int) or not isinstance(episode, int):
                continue

            season_episodes = self.available_episodes.get(season, {})
            covered = expand_mapping_episodes(mapping)
            episode_data = season_episodes.get(episode)
            if episode_data is None:
                episode_data = {
                    "season": season,
                    "episode": episode,
                    "name": None,
                    "aired": None,
                }

            mapping["episode_data"] = episode_data
            mapping["episode_name"] = episode_data.get("name", "Unknown")
            mapping["episode_order_type_id"] = order_type_id
            mapping["verified"] = bool(season_episodes) and all(
                number in season_episodes for number in covered
            )

            # The previous check was made against the old ordering's names,
            # and whether the filenames agree is the main thing a user wants
            # to know right after switching ordering.
            title_check = self._title_check_for(file_path, season, episode)
            mapping["title_match_score"] = title_check.score
            base = str(mapping.get("assignment_method", "")).split(" (title")[0]
            if base.startswith("regex"):
                if not mapping["verified"]:
                    # The new ordering does not list this episode at all, so
                    # the row is what the filename says and nothing more.
                    mapping["assignment_method"] = UNVERIFIED_PARSE_METHOD
                    mapping["confidence"] = UNVERIFIED_PARSE_CONFIDENCE
                else:
                    mapping["assignment_method"] = method_label(base, title_check)

        self._render_all_rows()
        self._update_title_warning()

    def _render_all_rows(self) -> None:
        """Repaint every row that has a mapping, dropping the rest."""
        for row in range(self.files_table.rowCount()):
            filename_item = self.files_table.item(row, self.COL_FILENAME)
            if not isinstance(filename_item, EnhancedFileTableItem):
                continue

            mapping = self.file_episode_mappings.get(filename_item.file_path)
            if mapping:
                self._update_file_row_assignment(row, mapping)
            else:
                with self._suppress_table_signals():
                    self._clear_row_assignment_data(row)

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
    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        """Re-read a row the user edited.

        A thin dispatcher: every editable column funnels into ``_apply_row``,
        which reads the whole row at once. The previous version reacted to
        one cell at a time and painted as it went, with four separate
        ``blockSignals`` pairs guarding against re-entering itself -- a shape
        that could not survive gaining more editable columns.
        """
        if not item:
            return
        if item.column() not in self._EDITABLE_COLUMNS:
            return
        self._apply_row(item.row())

    def _apply_row(self, row: int) -> None:
        """Store what one row now says, and render the result."""
        filename_item = self.files_table.item(row, self.COL_FILENAME)
        if not isinstance(filename_item, EnhancedFileTableItem):
            return

        file_path = filename_item.file_path
        season_item = self.files_table.item(row, self.COL_SEASON)
        episode_item = self.files_table.item(row, self.COL_EPISODE)
        if season_item is None or episode_item is None:
            # Mid-build: the row is still being assembled cell by cell.
            return

        title_item = self.files_table.item(row, self.COL_TITLE)
        title_override = title_item.text().strip() if title_item else ""

        try:
            season_text = season_item.text().strip()
            episodes = parse_episode_spec(episode_item.text())

            if episodes is None:
                # Not readable as episode numbers -- a half-typed "1-", or a
                # typo. Leave the stored mapping exactly as it was rather
                # than dropping it over a keystroke.
                return

            if not season_text or not episodes:
                if file_path in self.file_episode_mappings:
                    del self.file_episode_mappings[file_path]
                    with self._suppress_table_signals():
                        self._clear_row_assignment_data(row)
                self._after_mapping_change()
                return

            try:
                season = int(season_text)
            except ValueError:
                return

            episode = episodes[0]
            episode_end = episodes[-1] if len(episodes) > 1 else None

            season_episodes = self.available_episodes.get(season, {})
            # A span is only confirmed when TVDB lists every episode in it.
            has_tvdb_match = bool(season_episodes) and all(
                number in season_episodes for number in episodes
            )
            episode_data = season_episodes.get(episode)
            if episode_data is None:
                # TVDB has no data for this season/episode (or no episode
                # data at all for the series): still store what the user
                # typed, using a minimal synthesized payload, instead of
                # clearing the row. Otherwise the user has no way to map this
                # file at all, and the wizard has no Back button to escape
                # the resulting dead end.
                episode_data = {
                    "season": season,
                    "episode": episode,
                    "name": None,
                    "aired": None,
                }

            stored = self._store_mapping(
                file_path,
                season,
                episode,
                episode_data,
                1.0,
                "manual",
                episode_end=episode_end,
                episode_list=episodes,
                episode_order_type_id=self.episode_order_combo.currentData(),
                verified=has_tvdb_match,
                episode_title_override=title_override,
            )
            self._update_file_row_assignment(row, stored, rewrite_inputs=False)

        except Exception as e:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Failed to process manual episode edit for '{file_path.name}': {e}",
            )

        self._after_mapping_change()

    def _after_mapping_change(self) -> None:
        """Refresh everything that reads the mappings, and announce it."""
        self._update_all_stats()
        self._refresh_episodes_display()
        self.mapping_changed.emit()

    def _clear_row_assignment_data(self, row: int) -> None:
        """Clear confidence and method data for a row"""
        # clear matched episode
        matched_item = QTableWidgetItem("")
        matched_item.setFlags(matched_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._clear_cell_paint(matched_item)
        self.files_table.setItem(row, self.COL_MATCHED, matched_item)

        # clear confidence
        confidence_item = QTableWidgetItem("")
        confidence_item.setFlags(confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._clear_cell_paint(confidence_item)
        self.files_table.setItem(row, self.COL_CONFIDENCE, confidence_item)

        # clear method
        method_item = QTableWidgetItem("")
        method_item.setFlags(method_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.files_table.setItem(row, self.COL_METHOD, method_item)

        # reset season/episode background: a previous edit may have
        # painted them amber (unverified manual mapping), but the mapping
        # no longer exists so the cells should show no special color.
        # block signals while touching them so setBackground() (which
        # emits itemChanged) doesn't re-enter _on_table_item_changed
        season_item = self.files_table.item(row, self.COL_SEASON)
        episode_item = self.files_table.item(row, self.COL_EPISODE)
        if season_item is not None and episode_item is not None:
            self.files_table.blockSignals(True)
            try:
                self._clear_cell_paint(season_item)
                self._clear_cell_paint(episode_item)
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
        simple_mappings: dict[str, dict[str, Any]] = {}

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
        path_mappings: dict[str, dict[str, Any]] = {}

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

    def get_episode_map(self) -> dict[Path, EpisodeMapping]:
        """Get episode mappings.

        Values may include an ``episode_end`` key (``int | None``) marking the
        last episode number for a file that spans multiple episodes.
        """
        return self.file_episode_mappings.copy()

    def is_valid(self) -> bool:
        """Check that every file is mapped and no two files target overlapping episodes.

        A mapping is expanded to every ``(season, episode)`` pair it covers
        by ``claimed_season_episodes``, which reads a stored ``episode_list``
        where there is one and falls back to the ``episode``..``episode_end``
        range otherwise. If any pair is claimed by more than one file, the
        mappings overlap and this returns ``False`` -- catching overlaps like
        file A "S01E01-E02" and file B "S01E02", whose start tuples ``(1, 1)``
        and ``(1, 2)`` differ even though both claim S01E02.
        """
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return False

        # Compare file by file rather than by count. A row left behind for a
        # path no longer in the input list made the totals agree while a
        # genuinely unmapped file sat there unreported.
        if self.unmapped_files():
            return False

        if self.overlapping_claims():
            return False

        return True

    def focus_first_problem(self) -> None:
        """Select and scroll to the first row the user has to fix.

        A refusal that names files still leaves them to be found in a list
        that may not fit on screen.
        """
        problem_files = list(self.unmapped_files())
        for _target, claimants in self.overlapping_claims():
            problem_files.extend(claimants)
        if not problem_files:
            return

        wanted = set(problem_files)
        for row in range(self.files_table.rowCount()):
            filename_item = self.files_table.item(row, self.COL_FILENAME)
            if (
                isinstance(filename_item, EnhancedFileTableItem)
                and filename_item.file_path in wanted
            ):
                self.files_table.selectRow(row)
                self.files_table.scrollToItem(filename_item)
                return

    def unmapped_files(self) -> list[Path]:
        """Input files with no season/episode mapping, in input order."""
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return []
        return [
            file_path
            for file_path in self.media_input_payload.file_list
            if file_path not in self.file_episode_mappings
        ]

    def overlapping_claims(self) -> list[tuple[tuple[Any, Any], list[Path]]]:
        """Episodes claimed by more than one file.

        Each entry pairs a ``(season, episode)`` with every file claiming it,
        so the caller can name them. A file spanning several episodes claims
        each one, which is how "S01E01-E02" and a separate "S01E02" are
        caught despite their start numbers differing.
        """
        claimants: dict[tuple[Any, Any], list[Path]] = {}
        for file_path, mapping in self.file_episode_mappings.items():
            claimed = claimed_season_episodes(mapping)
            if not claimed:
                claimed = [(mapping.get("season"), mapping.get("episode"))]
            for target in claimed:
                claimants.setdefault(target, []).append(file_path)

        return [
            (target, sorted(files))
            for target, files in claimants.items()
            if len(files) > 1
        ]

    def has_tvdb_episode_data(self) -> bool:
        """Whether TVDB returned any episode data for the current series."""
        return bool(self.episodes_by_type)

    def has_unmapped_files(self) -> bool:
        """Whether at least one input file still lacks a season/episode mapping."""
        if not self.media_input_payload or not self.media_input_payload.file_list:
            return False
        return len(self.file_episode_mappings) < len(self.media_input_payload.file_list)

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
        type_data = (
            self.episodes_by_type.get(type_id, {}) if type_id is not None else {}
        )
        order_type = str(type_data.get("type", "")).lower()
        order_name = str(type_data.get("type_name", "")).lower()

        if "absolute" in order_type or "absolute" in order_name:
            return EpisodeFormat.ANIME_ABSOLUTE
        if "dvd" in order_type or "dvd" in order_name:
            return EpisodeFormat.DVD
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
