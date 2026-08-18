from collections.abc import Mapping, Sequence, Set as AbstractSet

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPointF, Qt, Slot
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from src.config.config import ConfigManager
from src.config.models import TrackerSettings
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.custom_splitter import CustomSplitter
from src.frontend.custom_widgets.tracker_management import (
    AitherTrackerEdit,
    BHDTrackerEdit,
    BlutopiaEdit,
    DarkPeersEdit,
    FearNoPeerEdit,
    HDBTrackerEdit,
    HunoTrackerEdit,
    LSTTrackerEdit,
    OnlyEncodesEdit,
    PTPTrackerEdit,
    RFTrackerEdit,
    SeedPoolEdit,
    ShareIslandEdit,
    TLTrackerEdit,
    TrackerEditBase,
    UploadCXEdit,
    UTPEdit,
    YuSceneEdit,
)

TrackerEditorType = type[TrackerEditBase]

TRACKER_EDITOR_TYPES: Mapping[TrackerSelection, TrackerEditorType] = {
    TrackerSelection.TORRENT_LEECH: TLTrackerEdit,
    TrackerSelection.BEYOND_HD: BHDTrackerEdit,
    TrackerSelection.PASS_THE_POPCORN: PTPTrackerEdit,
    TrackerSelection.REELFLIX: RFTrackerEdit,
    TrackerSelection.AITHER: AitherTrackerEdit,
    TrackerSelection.HUNO: HunoTrackerEdit,
    TrackerSelection.LST: LSTTrackerEdit,
    TrackerSelection.DARK_PEERS: DarkPeersEdit,
    TrackerSelection.SHARE_ISLAND: ShareIslandEdit,
    TrackerSelection.UPLOAD_CX: UploadCXEdit,
    TrackerSelection.ONLY_ENCODES: OnlyEncodesEdit,
    TrackerSelection.HDB: HDBTrackerEdit,
    TrackerSelection.BLUTOPIA: BlutopiaEdit,
    TrackerSelection.SEEDPOOL: SeedPoolEdit,
    TrackerSelection.UTOPIA: UTPEdit,
    TrackerSelection.YU_SCENE: YuSceneEdit,
    TrackerSelection.FEAR_NO_PEER: FearNoPeerEdit,
}


class TrackerListDelegate(QStyledItemDelegate):
    """Paint a subtle drag grip on the right side of hovered tracker rows."""

    GRIP_MARGIN = 12
    DOT_SPACING = 4
    DOT_RADIUS = 1.25

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)

        state = option.state
        if not (
            state & QStyle.StateFlag.State_MouseOver
            or state & QStyle.StateFlag.State_Selected
        ):
            return

        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            selected = bool(state & QStyle.StateFlag.State_Selected)
            color = option.palette.color(
                QPalette.ColorRole.HighlightedText
                if selected
                else QPalette.ColorRole.Mid
            )
            color.setAlpha(190)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)

            center_x = option.rect.right() - self.GRIP_MARGIN
            center_y = option.rect.center().y()
            for row in (-1, 0, 1):
                for column in (0, 1):
                    painter.drawEllipse(
                        QPointF(
                            center_x + column * self.DOT_SPACING,
                            center_y + row * self.DOT_SPACING,
                        ),
                        self.DOT_RADIUS,
                        self.DOT_RADIUS,
                    )
        finally:
            painter.restore()


class TrackerSettingsWidget(QWidget):
    """Reusable tracker selector and stacked editor.

    The settings window and the processing wizard use the same editor. The
    caller controls which configuration object receives editor changes and
    can optionally disable trackers that do not support the current media.
    """

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._unsupported_trackers: frozenset[TrackerSelection] = frozenset()
        self._locked_trackers: frozenset[TrackerSelection] = frozenset()
        self._persist_enabled = True

        self.tracker_list = QListWidget(self)
        self.tracker_list.setObjectName("trackerSettingsList")
        self.tracker_list.setFrameShape(QFrame.Shape.Box)
        self.tracker_list.setFrameShadow(QFrame.Shadow.Sunken)
        self.tracker_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tracker_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tracker_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tracker_list.setDragEnabled(True)
        self.tracker_list.setAcceptDrops(True)
        self.tracker_list.setDropIndicatorShown(True)
        self.tracker_list.setMinimumWidth(190)
        self.tracker_list.setMouseTracking(True)
        self.tracker_list.setToolTip("Drag tracker rows to change upload priority.")
        self.tracker_list_delegate = TrackerListDelegate(self.tracker_list)
        self.tracker_list.setItemDelegate(self.tracker_list_delegate)
        self.tracker_list.currentRowChanged.connect(self._show_tracker_page)
        self.tracker_list.itemChanged.connect(self._tracker_enabled_changed)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.addWidget(self.tracker_list, stretch=1)
        left_panel = QWidget(self)
        left_panel.setLayout(left_layout)

        self.tracker_title = QLabel(self)
        self.tracker_title.setObjectName("trackerSettingsTitle")
        title_font = self.tracker_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        self.tracker_title.setFont(title_font)

        self.tracker_stack = QStackedWidget(self)
        self.tracker_stack.setObjectName("trackerSettingsStack")

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.addWidget(self.tracker_title)
        right_layout.addWidget(self.tracker_stack, stretch=1)
        right_panel = QWidget(self)
        right_panel.setLayout(right_layout)

        self.tracker_splitter = CustomSplitter(Qt.Orientation.Horizontal, self)
        self.tracker_splitter.setObjectName("trackerSettingsSplitter")
        self.tracker_splitter.setHandleWidth(16)
        self.tracker_splitter.setChildrenCollapsible(False)
        self.tracker_splitter.addWidget(left_panel)
        self.tracker_splitter.addWidget(right_panel)
        self.tracker_splitter.setStretchFactor(0, 0)
        self.tracker_splitter.setStretchFactor(1, 1)
        self.tracker_splitter.setMinimumHeight(500)

        self._editor_map: dict[TrackerSelection, TrackerEditBase] = {}
        self._page_map: dict[TrackerSelection, int] = {}
        self._build_editor_pages()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tracker_splitter)

    def _build_editor_pages(self) -> None:
        missing = set(TrackerSelection) - set(TRACKER_EDITOR_TYPES)
        if missing:
            missing_names = ", ".join(
                str(tracker) for tracker in sorted(missing, key=str)
            )
            raise RuntimeError(f"Missing tracker settings editors: {missing_names}")

        for tracker in TrackerSelection:
            editor_type = TRACKER_EDITOR_TYPES[tracker]
            editor = editor_type(self.config, self)
            editor.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )

            scroll_area = QScrollArea(self.tracker_stack)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            scroll_area.setWidgetResizable(True)
            scroll_area.setWidget(editor)

            self._editor_map[tracker] = editor
            self._page_map[tracker] = self.tracker_stack.addWidget(scroll_area)

    @staticmethod
    def _normalize_order(
        order: Sequence[TrackerSelection],
    ) -> list[TrackerSelection]:
        """Return every known tracker once, retaining the configured order."""
        known = set(TrackerSelection)
        result: list[TrackerSelection] = []
        seen: set[TrackerSelection] = set()
        for tracker in order:
            if tracker in known and tracker not in seen:
                result.append(tracker)
                seen.add(tracker)
        result.extend(tracker for tracker in TrackerSelection if tracker not in seen)
        return result

    def load_from_config(
        self,
        config: ConfigManager | None = None,
        *,
        unsupported_trackers: AbstractSet[TrackerSelection] | None = None,
        locked_trackers: AbstractSet[TrackerSelection] | None = None,
        preselected: Sequence[TrackerSelection] | None = None,
        persist_enabled: bool = True,
    ) -> None:
        """Load list state and editor values from ``config``.

        Editors retain ``self.config`` as their save target. A temporary source
        config is used only while loading, which lets the settings page preview
        defaults without changing where subsequent edits are written.

        `locked_trackers` are shown but cannot be picked -- a resumed job uses
        this for trackers it has already uploaded to, which must never be
        uploaded to twice.

        `preselected` replaces the configured `enabled` flags as the source of
        the initial check states. A resumed job's tracker choice belongs to that
        run, not to the profile, which is also why `persist_enabled=False` stops
        the checkboxes writing back into config at all.
        """
        source_config = config or self.config
        self._unsupported_trackers = frozenset(unsupported_trackers or ())
        self._locked_trackers = frozenset(locked_trackers or ())
        self._persist_enabled = persist_enabled
        self._load_tracker_items(
            source_config.settings.trackers,
            preselected=frozenset(preselected) if preselected is not None else None,
        )
        self._load_editor_values(source_config)

    def _load_tracker_items(
        self,
        tracker_settings: TrackerSettings,
        preselected: frozenset[TrackerSelection] | None = None,
    ) -> None:
        tracker_map = tracker_settings.by_selection()
        order = self._normalize_order(tracker_settings.order)

        self.tracker_list.blockSignals(True)
        self.tracker_list.clear()
        for tracker in order:
            item = QListWidgetItem(str(tracker), self.tracker_list)
            item.setData(Qt.ItemDataRole.UserRole, tracker)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
            )
            unsupported = tracker in self._unsupported_trackers
            locked = tracker in self._locked_trackers
            if unsupported:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(
                    f"{tracker} does not support series uploads in NfoForge yet."
                )
            elif locked:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(
                    f"{tracker} already has this release, or its upload result is "
                    "unresolved. Uploading again could duplicate it."
                )
            wanted = (
                tracker in preselected
                if preselected is not None
                else tracker_map[tracker].enabled
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if wanted and not unsupported and not locked
                else Qt.CheckState.Unchecked
            )
        self.tracker_list.blockSignals(False)

        if self.tracker_list.count():
            self.tracker_list.setCurrentRow(0)

    def _load_editor_values(self, source_config: ConfigManager) -> None:
        for editor in self._editor_map.values():
            editor_config = editor.config
            editor.config = source_config
            editor.load_data.emit()
            editor.config = editor_config

    @Slot(int)
    def _show_tracker_page(self, row: int) -> None:
        if row < 0 or row >= self.tracker_list.count():
            self.tracker_title.clear()
            return

        item = self.tracker_list.item(row)
        if item is None:
            self.tracker_title.clear()
            return
        tracker = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(tracker, TrackerSelection):
            self.tracker_title.clear()
            return

        self.tracker_title.setText(str(tracker))
        self.tracker_stack.setCurrentIndex(self._page_map[tracker])

    @Slot(QListWidgetItem)
    def _tracker_enabled_changed(self, item: QListWidgetItem) -> None:
        # A run-scoped selection must not touch the profile. Without this a
        # resumed job that unchecks a tracker would disable it everywhere --
        # this fires on every toggle, independently of `save_editor_settings`.
        if not self._persist_enabled:
            return
        tracker = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(tracker, TrackerSelection):
            return
        self.config.settings.trackers.by_selection()[tracker].enabled = (
            item.checkState() == Qt.CheckState.Checked
            and tracker not in self._unsupported_trackers
        )

    def sync_enabled_to_config(self) -> None:
        """Copy the current checkbox state into the configured tracker data."""
        tracker_map = self.config.settings.trackers.by_selection()
        for index in range(self.tracker_list.count()):
            item = self.tracker_list.item(index)
            if item is None:
                continue
            tracker = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(tracker, TrackerSelection):
                continue
            # A locked tracker is unchecked because it is off limits for this
            # run, not because the user turned it off -- copying that into the
            # profile would silently disable it everywhere.
            if tracker in self._locked_trackers:
                continue
            tracker_map[tracker].enabled = (
                item.checkState() == Qt.CheckState.Checked
                and tracker not in self._unsupported_trackers
            )

    def save_editor_settings(self) -> None:
        """Save all visible editor values into the configured object.

        The per-tracker editor fields always save; only the checkbox state is
        withheld when the selection is run-scoped (see `_persist_enabled`).
        """
        if self._persist_enabled:
            self.sync_enabled_to_config()
        for editor in self._editor_map.values():
            editor.save_data.emit()

    def current_order(self) -> list[TrackerSelection]:
        order: list[TrackerSelection] = []
        for index in range(self.tracker_list.count()):
            item = self.tracker_list.item(index)
            if item is None:
                continue
            tracker = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(tracker, TrackerSelection):
                order.append(tracker)
        return self._normalize_order(order)

    def get_selected_trackers(self) -> list[TrackerSelection] | None:
        selected: list[TrackerSelection] = []
        for index in range(self.tracker_list.count()):
            item = self.tracker_list.item(index)
            if item is None:
                continue
            tracker = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(tracker, TrackerSelection):
                continue
            if (
                item.checkState() == Qt.CheckState.Checked
                and tracker not in self._unsupported_trackers
                and tracker not in self._locked_trackers
            ):
                selected.append(tracker)
        return selected or None
