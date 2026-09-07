"""The per-episode half of a pack's claims.

A pack and its files are separate surfaces. The wizard's combo boxes speak
for the pack -- the folder, the torrent, the release title -- and this table
speaks for the episodes. Neither cascades into the other, so a pack
assembled from individually repacked episodes can carry no REPACK of its own
while the five episodes that are repacks keep their marker.

Editing is delegate-based rather than widget-based on purpose. A complete
series pack runs to several hundred episodes, and seven live controls per
row would mean thousands of widgets each with its own layout and paint path.
`QTableWidgetItem` is cheap; a delegate builds one editor, only while a cell
is being edited, and sidesteps the scroll-wheel hijacking that combo boxes
inside a scrolling view are prone to.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHeaderView,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.backend.utils.filename_claims import FilenameClaims, resolve_file_claims
from src.backend.utils.rename_normalizations import (
    EDITION_INFO,
    FRAME_SIZE_INFO,
    LOCALIZATION_INFO,
    RE_RELEASE_INFO,
)
from src.backend.utils.streaming_services import STREAMING_SERVICE_CHOICES
from src.frontend.custom_widgets.custom_token_editor import ComboBoxDelegate
from src.packages.custom_types import RenameNormalization

# Claim key, column heading. Order is the column order after the episode name.
VALUE_CLAIMS: tuple[tuple[str, str], ...] = (
    ("edition", "Edition"),
    ("frame_size", "Frame Size"),
    ("localization", "Localization"),
    ("re_release", "Rerelease"),
    ("streaming_service", "Service"),
)

# Rendered as a check state rather than a value, since each has exactly one
# spelling. The value written into the claim dict is that spelling or "".
BOOLEAN_CLAIMS: tuple[tuple[str, str], ...] = (
    ("remux", "REMUX"),
    ("hybrid", "HYBRID"),
)

CLAIM_COLUMNS: tuple[str, ...] = tuple(
    key for key, _ in (*VALUE_CLAIMS, *BOOLEAN_CLAIMS)
)

# Breathing room beyond the widest dropdown column's content.
_COLUMN_PADDING = 12

# Floor for the episode name column. It is the only stretching column, so
# without a floor it absorbs every pixel the claim columns need and collapses
# to an unreadable sliver before anything else gives.
_EPISODE_MIN_WIDTH = 260


class AlwaysVisibleComboDelegate(ComboBoxDelegate):
    """A value column that looks like the dropdown it is.

    The base delegate only builds a combo box while a cell is being edited,
    so an untouched column reads as flat text with no hint that it can be
    changed. Painting the control instead of instantiating it keeps that
    affordance on every row without putting a live widget on every row --
    which at several hundred episodes is the whole reason for a delegate.
    """

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QComboBox:
        """Open the editor with its list already down.

        Without this the first click only swaps the painted combo for a real
        one, which looks identical and does nothing, so the list needs a
        second click. Deferred by a tick because the popup has to position
        itself against an editor the view has actually placed.
        """
        combo = super().createEditor(parent, option, index)
        combo.activated.connect(lambda _: self._commit(combo))
        QTimer.singleShot(0, combo.showPopup)
        return combo

    def _commit(self, editor: QComboBox) -> None:
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        combo = QStyleOptionComboBox()
        combo.rect = option.rect
        combo.palette = option.palette
        combo.currentText = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        # A suppressed column has `ItemIsEnabled` stripped, so the view has
        # already left `State_Enabled` out of the option. Recomputing it
        # from the flags would only restate that.
        combo.state = option.state
        style = QApplication.style()
        style.drawComplexControl(
            QStyle.ComplexControl.CC_ComboBox, combo, painter, option.widget
        )
        style.drawControl(
            QStyle.ControlElement.CE_ComboBoxLabel, combo, painter, option.widget
        )


class CenteredCheckDelegate(QStyledItemDelegate):
    """A check indicator drawn like a real checkbox, centred in its column.

    An item's own check state is drawn at the left edge, in the item view's
    palette, which against this app's dark Fusion palette is close to
    invisible. This borrows a real `QCheckBox` for its palette and draws the
    primitive that checkbox would draw, so the table's boxes are the ones
    from the pack controls below rather than a lookalike.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Never shown, never laid out. It exists to be asked what a checkbox
        # on this platform, in this style, is coloured -- which is not
        # something the item view's palette can answer.
        self._reference = QCheckBox()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # The background goes through the same call the default delegate
        # makes, so these cells shade and highlight exactly like the Episode
        # column. Drawing `PE_PanelItemViewItem` off the raw option instead
        # skips `initStyleOption`, which is what fills in the background
        # brush and the alternating-row state, and the column came out a
        # different colour from every other one.
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        # Its own indicator would be drawn at the left edge, in the item
        # palette -- the thing this delegate exists to replace.
        background.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        widget = background.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, background, painter, widget
        )

        button = QStyleOptionButton()
        button.palette = self._reference.palette()
        size = style.pixelMetric(
            QStyle.PixelMetric.PM_IndicatorWidth, option, self._reference
        )
        button.rect = QRect(0, 0, size, size)
        button.rect.moveCenter(option.rect.center())
        button.state = (
            QStyle.StateFlag.State_On
            if _is_checked(index)
            else QStyle.StateFlag.State_Off
        )
        button.state |= QStyle.StateFlag.State_Active
        if index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            button.state |= QStyle.StateFlag.State_Enabled
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorCheckBox,
            button,
            painter,
            self._reference,
        )

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """Toggle on a click anywhere in the cell.

        The base implementation hit-tests the indicator where the style
        would have put it, which is not where this one is drawn. Accepting
        the whole cell is both correct here and a larger target.
        """
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        if not index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        model.setData(
            index,
            Qt.CheckState.Unchecked if _is_checked(index) else Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )
        return True


def _is_checked(index: QModelIndex | QPersistentModelIndex) -> bool:
    """Whether the item at `index` is checked.

    `index.data(CheckStateRole)` hands back a plain int, and PySide6's
    enums do not compare equal to ints -- `2 == Qt.CheckState.Checked` is
    False. Comparing the two directly therefore reads as "never checked"
    without erroring, which paints every box empty and makes every toggle
    a no-op. Convert first.
    """
    return (
        Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole) or 0)
        == Qt.CheckState.Checked
    )


def _choices(items: Sequence[RenameNormalization]) -> list[str]:
    """Combo entries for a normalisation table, blank first.

    Blank is not padding: it is how the user says "this episode carries no
    edition", which is a different statement from leaving detection alone.
    """
    return ["", *(item.normalized for item in items)]


class EpisodeClaimsTable(QWidget):
    """One row per episode, one column per claim the episode may carry."""

    claims_changed = Signal()

    def __init__(
        self,
        custom_edition_info: Sequence[RenameNormalization] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("episodeClaimsTable")

        self._paths: list[Path] = []
        self._detected: dict[Path, FilenameClaims] = {}
        self._edits: dict[Path, dict[str, str]] = {}
        self._disabled: set[str] = set()
        # Guards the difference between the table being filled in and the
        # user filling it in. Only the latter is an edit.
        self._loading = False
        # Re-entrancy guard for the column fit below.
        self._fitting = False

        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Search episodes...")
        self.search_bar.textChanged.connect(self.filter_rows)

        self.table = QTableWidget(self)
        self.table.setColumnCount(1 + len(CLAIM_COLUMNS))
        self.table.setHorizontalHeaderLabels(
            ["Episode", *(label for _, label in (*VALUE_CLAIMS, *BOOLEAN_CLAIMS))]
        )
        self.table.setMinimumHeight(220)
        self.table.setFrameShape(QFrame.Shape.Box)
        self.table.setFrameShadow(QFrame.Shadow.Sunken)
        self.table.verticalHeader().setVisible(False)
        # Single click opens the dropdown. `AllEditTriggers` fires on the
        # cell becoming current, which needs cells to be selectable at all:
        # under `NoSelection` nothing becomes current and the only way in
        # was a double click.
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)

        value_choices = {
            "edition": _choices((*EDITION_INFO, *custom_edition_info)),
            "frame_size": _choices(FRAME_SIZE_INFO),
            "localization": _choices(LOCALIZATION_INFO),
            "re_release": _choices(RE_RELEASE_INFO),
            "streaming_service": ["", *STREAMING_SERVICE_CHOICES],
        }
        for column, (key, _) in enumerate(VALUE_CLAIMS, start=1):
            self.table.setItemDelegateForColumn(
                column, AlwaysVisibleComboDelegate(value_choices[key], self)
            )
        for offset in range(len(BOOLEAN_CLAIMS)):
            self.table.setItemDelegateForColumn(
                1 + len(VALUE_CLAIMS) + offset, CenteredCheckDelegate(self)
            )

        self._fix_column_widths(value_choices)

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.search_bar)
        layout.addWidget(self.table)

    def _fix_column_widths(self, value_choices: dict[str, list[str]]) -> None:
        """Size every column once, from what it *could* hold.

        Measuring current contents instead makes the columns move: pick a
        long edition, clear it again, and the row reflows. The set of
        options is fixed at construction, so the widest one is knowable up
        front and the layout can then be left alone forever.

        One width across all five dropdowns, so they read as one row of
        choices rather than five unrelated controls.
        """
        cell_metrics = self.table.fontMetrics()
        header = self.table.horizontalHeader()
        header_metrics = header.fontMetrics()

        widest = max(
            *(
                cell_metrics.horizontalAdvance(choice)
                for choices in value_choices.values()
                for choice in choices
            ),
            *(header_metrics.horizontalAdvance(label) for _, label in VALUE_CLAIMS),
        )
        # Through the style rather than by hand: a combo box is its text
        # plus a drop-down arrow, and only the style knows how wide that is.
        value_width = (
            QApplication.style()
            .sizeFromContents(
                QStyle.ContentsType.CT_ComboBox,
                QStyleOptionComboBox(),
                QSize(widest, cell_metrics.height()),
            )
            .width()
            + _COLUMN_PADDING
        )

        # Interactive rather than Stretch. Stretch has no floor, so the
        # episode name is squeezed to a sliver before any claim column
        # gives; `_fit_episode_column` stretches it by hand instead, down
        # to a limit, and lets the table's own scroll bar take the rest.
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        for column in range(1, 1 + len(VALUE_CLAIMS)):
            self.table.setColumnWidth(column, value_width)
        for offset, (_, label) in enumerate(BOOLEAN_CLAIMS):
            self.table.setColumnWidth(
                1 + len(VALUE_CLAIMS) + offset,
                header_metrics.horizontalAdvance(label) + _COLUMN_PADDING * 2,
            )
        self._fit_episode_column()

    def _fit_episode_column(self) -> None:
        """Give the episode name whatever the claim columns are not using.

        Down to `_EPISODE_MIN_WIDTH`, past which the table overflows and
        scrolls. The scroll bar belongs to the table, under it, rather than
        to the page: a minimum width on the widget would push the overflow
        out to the wizard's own scroll bar at the bottom of the window,
        which is a long way from the thing that is actually too narrow.
        """
        if self._fitting:
            return
        claims = sum(
            self.table.columnWidth(column)
            for column in range(1, self.table.columnCount())
        )
        wanted = max(_EPISODE_MIN_WIDTH, self.table.viewport().width() - claims)
        if wanted == self.table.columnWidth(0):
            return
        # Widening the column can bring the scroll bar in, which resizes the
        # viewport, which lands back here. Settle it in one pass rather than
        # letting the two chase each other a pixel at a time.
        self._fitting = True
        try:
            self.table.setColumnWidth(0, wanted)
        finally:
            self._fitting = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Refit whenever the viewport itself changes size.

        Not the widget's own `resizeEvent`: that arrives before the table
        child has been laid out, so the viewport width read there is the
        previous one. Fitting from a stale width sets a column that is
        wrong by exactly the delta, which the next event corrects -- and
        during a window drag that is a scroll bar blinking on and off. It
        is also why the column started at its minimum, since at
        construction there is no layout yet to read.
        """
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_episode_column()
        return super().eventFilter(watched, event)

    # -- population ----------------------------------------------------
    def load(self, rows: Sequence[tuple[Path, FilenameClaims]]) -> None:
        """Fill the table, discarding any edits made against the old rows.

        `rows` arrive in display order; the caller sorts, because it is the
        caller that knows each file's season and episode.
        """
        self._paths = [path for path, _ in rows]
        self._detected = dict(rows)
        # Suppression belongs to the release's source quality, not to the
        # rows, so it outlives them: new rows arriving under a web source
        # must not come up carrying a REMUX their filenames happen to claim.
        self._edits = {path: dict.fromkeys(self._disabled, "") for path in self._paths}
        self._repopulate()

    def _repopulate(self) -> None:
        self._loading = True
        try:
            self.table.setRowCount(0)
            self.table.clearContents()
            self.table.setRowCount(len(self._paths))
            for row, path in enumerate(self._paths):
                name_item = QTableWidgetItem(path.stem)
                name_item.setToolTip(path.name)
                name_item.setFlags(
                    name_item.flags()
                    & ~Qt.ItemFlag.ItemIsEditable
                    & ~Qt.ItemFlag.ItemIsSelectable
                )
                self.table.setItem(row, 0, name_item)
                self._write_row(row, path)
        finally:
            self._loading = False

    def _write_row(self, row: int, path: Path) -> None:
        resolved = self.resolved_claims_for(path)
        for column, (key, _) in enumerate(VALUE_CLAIMS, start=1):
            item = QTableWidgetItem(resolved.get(key, ""))
            if key in self._disabled:
                # Both flags, not just the editable one: the delegate paints
                # the enabled state, so leaving it enabled would draw a live
                # looking dropdown that refuses to open.
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemFlag.ItemIsEditable
                    & ~Qt.ItemFlag.ItemIsEnabled
                )
            self.table.setItem(row, column, item)

        boolean_start = 1 + len(VALUE_CLAIMS)
        for offset, (key, spelling) in enumerate(BOOLEAN_CLAIMS):
            item = QTableWidgetItem("")
            # Not selectable, for the same reason the episode name is not:
            # a selected cell fills with `palette.highlight()`, and on this
            # platform that is the identical colour the checkbox itself is
            # drawn in, so selecting a cell erased the box inside it.
            # Clicking still toggles -- `editorEvent` is routed to enabled
            # items whether or not they can be selected.
            flags = (
                item.flags()
                & ~Qt.ItemFlag.ItemIsEditable
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            if key not in self._disabled:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags)
            item.setCheckState(
                Qt.CheckState.Checked
                if resolved.get(key) == spelling
                else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, boolean_start + offset, item)

    # -- reading -------------------------------------------------------
    def resolved_claims_for(self, path: Path) -> dict[str, str]:
        """This episode's claims: its filename's, with the user's on top.

        Detection ran once, at load. Re-running it per read would mean a
        guessit parse per episode on every keystroke in the pack controls.
        """
        detected = self._detected.get(path)
        if detected is None:
            return {}
        return resolve_file_claims(detected, self._edits.get(path, {}))

    # -- editing -------------------------------------------------------
    @Slot(QTableWidgetItem)
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        column = item.column()
        if column == 0 or column > len(CLAIM_COLUMNS):
            return
        path = self._paths[item.row()]
        key = CLAIM_COLUMNS[column - 1]

        if column <= len(VALUE_CLAIMS):
            self._edits[path][key] = item.text().strip()
        else:
            spelling = BOOLEAN_CLAIMS[column - 1 - len(VALUE_CLAIMS)][1]
            checked = item.checkState() == Qt.CheckState.Checked
            self._edits[path][key] = spelling if checked else ""

        self.claims_changed.emit()

    def apply_to_all(self, key: str, value: str) -> None:
        """Stamp one claim onto every episode.

        Recorded as an edit on every row, including an empty one: applying a
        blank is the user saying no episode carries this, which has to beat
        what the filenames say.
        """
        for path in self._paths:
            self._edits[path][key] = value
        self._repopulate()
        self.claims_changed.emit()

    def revert_to_detected(self, key: str) -> None:
        """Drop the user's edits for one claim, in every row.

        Reverts to what each filename says, which is not necessarily what
        the row held before the last bulk apply -- a manual edit made
        earlier is dropped too. Holding a snapshot to restore instead would
        mean deciding when it goes stale.
        """
        for edits in self._edits.values():
            edits.pop(key, None)
        self._repopulate()
        self.claims_changed.emit()

    def set_claim_enabled(self, key: str, enabled: bool) -> None:
        """Enable or suppress one claim across every episode.

        Disabling clears the column rather than parking its values out of
        reach, so nothing the release cannot have -- REMUX on a web pack --
        survives in hidden state. Re-enabling therefore has nothing stored
        to put back and returns the column to what the filenames say, which
        is what the pack's own checkbox does on the same signal. Edits made
        before the suppression are not restored; holding a snapshot to
        restore instead would mean deciding when it goes stale.
        """
        if enabled == (key not in self._disabled):
            return
        if enabled:
            # Re-enabling *is* reverting: suppression stored nothing, so
            # what comes back is whatever the filenames say.
            self._disabled.discard(key)
            self.revert_to_detected(key)
            return
        self._disabled.add(key)
        for edits in self._edits.values():
            edits[key] = ""
        self._repopulate()
        self.claims_changed.emit()

    # -- view ----------------------------------------------------------
    @Slot(str)
    def filter_rows(self, text: str) -> None:
        """Show only episodes whose name contains `text`.

        Hiding rather than rebuilding: a hidden row keeps its edits, so
        searching to reach one episode cannot cost the user the others.
        """
        needle = text.strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            name = item.text().lower() if item else ""
            self.table.setRowHidden(row, bool(needle) and needle not in name)
