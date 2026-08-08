"""Picker for saved jobs."""

from contextlib import suppress
from datetime import datetime
from enum import Enum
from html import escape
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from src.backend.jobs import (
    JobListing,
    JobStoreError,
    delete_job,
    list_jobs,
    load_job,
    write_job_document,
)
from src.backend.utils.file_utilities import (
    file_bytes_to_str,
    get_dir_size,
    open_explorer,
)
from src.config.profiles import unique_working_dirs
from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.custom_splitter import CustomSplitter
from src.logger.nfo_forge_logger import LOG

_LISTING_ROLE = Qt.ItemDataRole.UserRole

# `img_to` is stored as an enum member name, and the same name can belong to
# either ImageHost or ImageSource -- see `_image_host_display_name`, and
# `_image_upload_from_to_to_dict` in `src/backend/jobs/codec.py`, which is why
# `img_to_type` is carried alongside it in the first place.
_IMAGE_DESTINATION_ENUMS: dict[str, type[Enum]] = {
    "ImageHost": ImageHost,
    "ImageSource": ImageSource,
}


class _ListingLoader(QThread):
    """Reads the saved-job list off the GUI thread.

    Listing walks every config profile's working directory and parses every
    `job.json` in it. That is fine locally and a visible stall on a network
    share, and the dialog has nothing to show until it finishes either way.
    """

    loaded = Signal(object)  # list[JobListing]

    def run(self) -> None:
        try:
            self.loaded.emit(list_jobs(unique_working_dirs()))
        except Exception as error:
            LOG.error(LOG.LOG_SOURCE.FE, f"Could not list saved jobs: {error}")
            self.loaded.emit([])


class LoadJobDialog(QDialog):
    """Lists saved jobs and reports which one the user chose to load.

    Jobs from every config profile are listed, because hiding the ones that
    don't match would leave a user who saved under another profile with no way
    to find their work. Those rows are shown muted and cannot be opened with
    plain "Load" -- resuming a job under settings it was not built for would
    silently upload with the wrong credentials and templates -- so crossing
    profiles takes the explicit "Switch profile and load" action instead.
    """

    def __init__(
        self, active_profile: str | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("loadJobDialog")
        self.setWindowTitle("Saved Jobs")
        self.resize(860, 400)
        self.setSizeGripEnabled(True)

        self.active_profile = active_profile or ""
        self.selected_listing: JobListing | None = None
        self.switch_profile_requested = False
        self.queued_listings: list[JobListing] = []
        """Jobs to run back to back, when the user chose Run Queue."""
        self._loader: _ListingLoader | None = None
        self._details_cache: dict[Path, str] = {}
        """`_describe(listing)` output, keyed by job path.

        `_describe` parses the job document and walks its folder -- the same
        read this branch already moved off-thread for `list_jobs`. Cleared in
        `_load_listings`, so a rename or delete cannot leave a stale render
        behind.
        """
        self._last_described_path: Path | None = None
        """The path `_refresh_details` last rendered, so an unrelated widget
        update -- moving the queue selection, typing in the filter -- that
        leaves the tree's current listing unchanged can skip the whole
        refresh rather than re-describing the same job from scratch.
        """
        self._details_source: Literal["tree", "queue"] = "tree"
        """Which pane the details view and Open Folder currently describe.
        Tracked explicitly rather than via focus -- `hasFocus()` is
        unreliable before the dialog is shown, and the tests for this file
        construct the dialog without showing it. Set by
        `_on_tree_selection_changed` and `_on_queue_row_changed`, below.
        """

        self.info_lbl = QLabel(
            "<i><span>Pick a saved job to jump straight to processing. Duplicate "
            "checks still run when you process it.<br />Jobs saved under another "
            "config are shown greyed out; use <b>Switch profile and load</b> to "
            "open one.</span></i>",
            wordWrap=True,
            parent=self,
        )

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter by name, title, file or tracker...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.only_this_config = QCheckBox("Only this config", self)
        self.only_this_config.setChecked(True)
        self.only_this_config.setToolTip(
            "Jobs saved under another config can still be opened, but only via "
            "'Switch profile and load'"
        )
        self.only_this_config.toggled.connect(self._apply_filter)

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.filter_edit, stretch=1)
        filter_row.addWidget(self.only_this_config)

        self.job_tree = QTreeWidget(self)
        self.job_tree.setFrameShape(QFrame.Shape.Box)
        self.job_tree.setFrameShadow(QFrame.Shadow.Sunken)
        self.job_tree.setRootIsDecorated(False)
        self.job_tree.setColumnCount(7)
        self.job_tree.setHeaderLabels(
            ("Name", "Title", "Type", "Trackers", "Config", "State", "Saved")
        )
        # Column widths carry meaning here: Name and Title are what a job is
        # recognised by, Trackers is an open-ended list the user may want wider,
        # and the rest are short enough to size themselves.
        header = self.job_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(3, 180)
        self.job_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        # multi-select so several prepared jobs can be queued in one go
        self.job_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.job_tree.itemDoubleClicked.connect(self._on_double_click)
        self.job_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        # itemClicked fires on every press, including a re-click of a row
        # that is already current -- itemSelectionChanged does not, which is
        # exactly the case that leaves a re-clicked pane stuck. Keeping both
        # connected covers clicking and keyboard navigation, which emits no
        # click at all.
        self.job_tree.itemClicked.connect(self._on_tree_selection_changed)

        self.empty_lbl = QLabel(
            "<span>No saved jobs yet. Use <b>Save Job</b> on the process page "
            "to create one.</span>",
            wordWrap=True,
            parent=self,
        )
        self.empty_lbl.hide()

        self.details_lbl = QLabel("", wordWrap=True, parent=self)
        self.details_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.details_lbl.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.details_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.open_folder_btn = QPushButton("Open job folder", self)
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._open_job_folder)

        details_panel = QWidget(self)
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(8, 0, 0, 0)
        details_scroll = QScrollArea(details_panel)
        details_scroll.setWidgetResizable(True)
        details_scroll.setWidget(self.details_lbl)
        details_layout.addWidget(details_scroll, stretch=1)
        details_layout.addWidget(self.open_folder_btn)

        self.queue_list = QListWidget(self)
        self.queue_list.setToolTip(
            "Jobs run top to bottom. Only prepared jobs on this config can be "
            "queued, since a queue has nobody to answer a prompt"
        )
        self.queue_list.currentRowChanged.connect(self._on_queue_row_changed)
        # Same reasoning as job_tree.itemClicked, above.
        self.queue_list.itemClicked.connect(self._on_queue_row_changed)

        self.add_to_queue_btn = QPushButton("Add to queue", self)
        self.add_to_queue_btn.clicked.connect(self._add_to_queue)
        self.queue_up_btn = QPushButton("Up", self)
        self.queue_up_btn.clicked.connect(lambda: self._move_queued(-1))
        self.queue_down_btn = QPushButton("Down", self)
        self.queue_down_btn.clicked.connect(lambda: self._move_queued(1))
        self.queue_remove_btn = QPushButton("Remove", self)
        self.queue_remove_btn.setToolTip("Take it out of the queue; the job is kept")
        self.queue_remove_btn.clicked.connect(self._remove_queued)

        queue_buttons = QHBoxLayout()
        queue_buttons.addWidget(self.queue_up_btn)
        queue_buttons.addWidget(self.queue_down_btn)
        queue_buttons.addWidget(self.queue_remove_btn)

        queue_panel = QWidget(self)
        queue_layout = QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(8, 0, 8, 0)
        queue_layout.addWidget(QLabel("<b>Queue</b>", parent=queue_panel))
        queue_layout.addWidget(self.add_to_queue_btn)
        queue_layout.addWidget(self.queue_list, stretch=1)
        queue_layout.addLayout(queue_buttons)

        self.splitter = CustomSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.job_tree)
        self.splitter.addWidget(details_panel)
        self.splitter.insertWidget(1, queue_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setStretchFactor(2, 2)

        self.status_lbl = QLabel("", wordWrap=True, parent=self)
        self.status_lbl.setTextFormat(Qt.TextFormat.PlainText)

        self.delete_btn = QPushButton("Delete", self)
        self.delete_btn.setShortcut(Qt.Key.Key_Delete)
        self.delete_btn.clicked.connect(self._delete_selected)

        self.rename_btn = QPushButton("Rename", self)
        self.rename_btn.setShortcut(Qt.Key.Key_F2)
        self.rename_btn.clicked.connect(self._rename_selected)

        self.switch_btn = QPushButton("Switch profile and load", self)
        self.switch_btn.setToolTip(
            "Activate the config this job was saved under, then load it"
        )
        self.switch_btn.clicked.connect(self._accept_with_switch)

        self.queue_btn = QPushButton("Run Queue", self)
        self.queue_btn.setToolTip("Upload the queued jobs one after another, in order")
        self.queue_btn.clicked.connect(self._accept_queue)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        open_button = self.button_box.button(QDialogButtonBox.StandardButton.Open)
        if open_button:
            open_button.setText("Load")
        self.button_box.accepted.connect(self._accept_selection)
        self.button_box.rejected.connect(self.reject)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.delete_btn)
        bottom_row.addWidget(self.rename_btn)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.queue_btn)
        bottom_row.addWidget(self.switch_btn)
        bottom_row.addWidget(self.button_box)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.info_lbl)
        main_layout.addLayout(filter_row)
        main_layout.addWidget(self.empty_lbl)
        main_layout.addWidget(self.splitter, stretch=1)
        main_layout.addWidget(self.status_lbl)
        main_layout.addLayout(bottom_row)

        self._load_listings()

    def _load_listings(self) -> None:
        # Retire any loader still in flight before starting another. Without
        # this, a second call replaces `self._loader` and the previous thread
        # becomes unreachable -- still running, still parented, and no longer
        # something `done()` can wait on, which is exactly the destroy-a-live-
        # thread abort this change exists to avoid. Not reachable through the
        # UI today (delete and rename are disabled while the tree is empty),
        # but the invariant should not depend on that staying true.
        self._stop_loader()
        # A path can be reused by a new render after this reload -- a rename
        # writes a new name under the same path, and `_describe` reads the
        # document fresh once repopulated -- so a cached render or a "nothing
        # changed" skip from before the reload must not survive it.
        self._details_cache.clear()
        self._last_described_path = None

        self.job_tree.clear()
        self.job_tree.setVisible(False)
        self.empty_lbl.setText("<span>Loading saved jobs...</span>")
        self.empty_lbl.setVisible(True)
        self._update_button_state()

        self._loader = _ListingLoader(self)
        self._loader.loaded.connect(self._on_listings_loaded)
        self._loader.start()

    @Slot(object)
    def _on_listings_loaded(self, listings: list[JobListing]) -> None:
        # sorting reshuffles the tree on every insert otherwise, which is
        # wasted work and would show rows swapping places as they load
        self.job_tree.setSortingEnabled(False)
        self.job_tree.clear()
        muted = QBrush(
            self.palette().color(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText
            )
        )
        # Built here from the live palette rather than registered with
        # QTAThemeSwap: that helper only takes QToolButton / QPushButton /
        # qta.IconWidget, and a QTreeWidgetItem is none of those. The cost is
        # that a colour-scheme change mid-dialog leaves these until the next
        # populate -- which every load and delete triggers anyway.
        icon_color = self.palette().color(QPalette.ColorRole.WindowText).name()
        prepared_icon = qta.icon("mdi6.package-variant-closed", color=icon_color)
        needs_input_icon = qta.icon("mdi6.pencil-outline", color=icon_color)
        missing_icon = qta.icon("mdi6.alert-outline", color=icon_color)

        for listing in listings:
            item = QTreeWidgetItem(
                (
                    listing.name,
                    self._title_text(listing),
                    listing.summary.media_type or "",
                    ", ".join(listing.summary.trackers),
                    listing.config_profile or "—",
                    "Prepared" if listing.prepared else "Needs input",
                    self._saved_text(listing.created_at),
                )
            )
            item.setData(0, _LISTING_ROLE, listing)
            item.setIcon(5, prepared_icon if listing.prepared else needs_input_icon)
            # the Trackers column is Interactive and elides, so the full list
            # has to be reachable somewhere
            if listing.summary.trackers:
                item.setToolTip(3, "\n".join(listing.summary.trackers))
            if not listing.matches_profile(self.active_profile):
                # muted rather than disabled: a disabled item cannot be
                # selected at all, and selecting it is exactly how the user
                # reaches the switch-and-load action
                for column in range(self.job_tree.columnCount()):
                    item.setForeground(column, muted)
                item.setToolTip(
                    0,
                    f"Saved under config '{listing.config_profile}'. "
                    "Use 'Switch profile and load' to open it.",
                )
            if not listing.media_available:
                # after the cross-profile tooltip so this one wins -- a job
                # that cannot run at all is the more urgent fact
                item.setIcon(0, missing_icon)
                item.setToolTip(
                    0,
                    "The media this job was built from is no longer at "
                    f"'{listing.summary.input_path}', so it cannot be processed "
                    "until the file is back.",
                )
            self.job_tree.addTopLevelItem(item)

        self.job_tree.setSortingEnabled(True)
        self.job_tree.sortByColumn(6, Qt.SortOrder.DescendingOrder)

        has_jobs = bool(listings)
        self.job_tree.setVisible(has_jobs)
        self.empty_lbl.setText(
            "<span>No saved jobs yet. Use <b>Save Job</b> on the process page "
            "to create one.</span>"
        )
        self.empty_lbl.setVisible(not has_jobs)
        first_item = self.job_tree.topLevelItem(0)
        if first_item is not None:
            self.job_tree.setCurrentItem(first_item)
        self._apply_filter()

    def _stop_loader(self) -> None:
        """Detach and finish the current loader before moving on.

        Disconnect first, and unconditionally. A queued `loaded` is delivered
        only if the connection is still live when it is dispatched, so severing
        it cancels an emission already in flight. Gating the disconnect on
        `isRunning()` would miss a loader that finished in the window between
        the check and the call, letting its result land in a dialog that is
        already closing.

        Then wait with no cap. An earlier version waited two seconds, which is
        precisely the wrong bound: the case this has to survive is the slow
        network scan the whole change exists to get off the GUI thread, and
        that is exactly the case that exceeds two seconds. Returning early
        leaves a running thread to be destroyed, which aborts the process. A
        brief freeze while closing is much the lesser cost.

        The wait is itself guarded against `RuntimeError`: if the underlying
        C++ object is already destroyed, that is exactly the post-condition
        this method wants -- no live thread left to wait for -- so suppressing
        it there is correct rather than masking a real failure.
        """
        loader = self._loader
        self._loader = None
        if loader is None:
            return
        with suppress(RuntimeError, TypeError):
            loader.loaded.disconnect(self._on_listings_loaded)
        with suppress(RuntimeError):
            loader.wait()

    def done(self, result: int) -> None:
        self._stop_loader()
        super().done(result)

    @Slot()
    def _apply_filter(self) -> None:
        """Hide rows that do not match the filter, and deselect what it hides.

        A hidden row that stayed selected would still be picked up by Load,
        Delete and the queue, which is exactly the kind of action-at-a-distance
        a filter is supposed to remove.
        """
        needle = self.filter_edit.text().strip().casefold()
        only_mine = self.only_this_config.isChecked()

        for index in range(self.job_tree.topLevelItemCount()):
            item = self.job_tree.topLevelItem(index)
            if item is None:
                continue
            listing = item.data(0, _LISTING_ROLE)
            if not isinstance(listing, JobListing):
                continue
            haystack = " ".join(
                (
                    listing.name,
                    listing.summary.title or "",
                    listing.summary.input_name or "",
                    " ".join(listing.summary.trackers),
                )
            ).casefold()
            hidden = bool(needle) and needle not in haystack
            if only_mine and not listing.matches_profile(self.active_profile):
                hidden = True
            item.setHidden(hidden)
            if hidden:
                item.setSelected(False)

        self._update_button_state()

    @staticmethod
    def _title_text(listing: JobListing) -> str:
        title = listing.summary.title or listing.summary.input_name or ""
        year = listing.summary.year
        return f"{title} ({year})" if title and year else title

    @staticmethod
    def _tracker_display_name(raw_name: object) -> str:
        """A tracker's saved-job key, in the same casing the rest of the UI uses.

        `tracker_image_hosts` is keyed by `TrackerSelection` member *name*
        (`"AITHER"`), matching the round-trip-by-name convention the job codec
        uses everywhere -- see `src/backend/jobs/codec.py`. That is not the
        member's display value (`"Aither"`), which is what the tree's Trackers
        column and `JobSummary.trackers` both show. A name a current build no
        longer recognises -- a retired tracker -- falls back to the raw string
        rather than raising out of the details pane.
        """
        try:
            return str(TrackerSelection(str(raw_name)))
        except ValueError:
            return str(raw_name)

    @staticmethod
    def _image_host_display_name(entry: dict[str, Any]) -> str:
        """Resolve a stored image destination back to what the user picked.

        The same problem `_tracker_display_name` solves, one field over. The
        codec writes `img_to` as an enum *member name* (`CHEVERETO_V3`) and
        carries `img_to_type` alongside it precisely because that name alone
        cannot say whether it belongs to `ImageHost` or `ImageSource`. Render
        the raw name and the pane shows "Aither -> CHEVERETO_V3": a humanised
        tracker arrowing at an internal identifier, in a table whose whole job
        is to be readable.

        Falls back to the raw string, so a destination retired since the job
        was saved still shows something.
        """
        raw = str(entry.get("img_to", "?"))
        destination = _IMAGE_DESTINATION_ENUMS.get(str(entry.get("img_to_type")))
        if destination is None:
            return raw
        try:
            return str(destination[raw])
        except KeyError:
            return raw

    @staticmethod
    def _saved_text(created_at: str) -> str:
        """Render the stored UTC timestamp in the user's local time."""
        try:
            return (
                datetime.fromisoformat(created_at)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M")
            )
        except ValueError:
            return created_at

    def _details_listing(self) -> JobListing | None:
        """The listing the details pane and Open Folder currently describe.

        Follows `self._details_source` rather than the tree unconditionally,
        so clicking a queue row describes that queued job instead of
        whatever the tree's own selection happens to be.
        """
        if self._details_source == "queue":
            item = self.queue_list.currentItem()
            if item is None:
                return None
            listing = item.data(_LISTING_ROLE)
            return listing if isinstance(listing, JobListing) else None

        # an empty tree has no current item, so emptiness needs no separate
        # check here -- and must not be inferred from widget visibility, which
        # is still false before the dialog is shown
        item = self.job_tree.currentItem()
        if item is None:
            return None
        listing = item.data(0, _LISTING_ROLE)
        if (
            not isinstance(listing, JobListing)
            or listing not in self._selected_listings()
        ):
            return None
        return listing

    def _selected_listings(self) -> list[JobListing]:
        listings: list[JobListing] = []
        for item in self.job_tree.selectedItems():
            if item.isHidden():
                continue
            listing = item.data(0, _LISTING_ROLE)
            if isinstance(listing, JobListing):
                listings.append(listing)
        return listings

    def queueable_listings(self) -> list[JobListing]:
        """The queue, in the order the user put it in.

        Membership was already gated when each job was added: a job from another
        config would upload with the wrong credentials, and an unprepared one
        would stop at a prompt.
        """
        listings: list[JobListing] = []
        for row in range(self.queue_list.count()):
            listing = self.queue_list.item(row).data(_LISTING_ROLE)
            if isinstance(listing, JobListing):
                listings.append(listing)
        return listings

    def _can_queue(self, listing: JobListing) -> bool:
        return listing.prepared and listing.matches_profile(self.active_profile)

    def _queued_paths(self) -> set[Path]:
        """Paths already in the queue, for the duplicate check.

        Its own method rather than an inline comprehension in `_add_to_queue`,
        so the "what is already queued" question has one answer that
        `_drop_from_queue` and any later caller can share.
        """
        return {listing.path for listing in self.queueable_listings()}

    def _renumber_queue(self) -> None:
        for row in range(self.queue_list.count()):
            item = self.queue_list.item(row)
            listing = item.data(_LISTING_ROLE)
            if isinstance(listing, JobListing):
                item.setText(f"{row + 1}. {listing.name}")

    @Slot()
    def _add_to_queue(self) -> None:
        queued = self._queued_paths()
        for listing in self._selected_listings():
            if not self._can_queue(listing) or listing.path in queued:
                continue
            item = QListWidgetItem(listing.name)
            item.setData(_LISTING_ROLE, listing)
            self.queue_list.addItem(item)
            queued.add(listing.path)
        self._renumber_queue()
        self._update_button_state()

    def _move_queued(self, offset: int) -> None:
        row = self.queue_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.queue_list.count():
            return
        self.queue_list.insertItem(target, self.queue_list.takeItem(row))
        self.queue_list.setCurrentRow(target)
        self._renumber_queue()
        self._update_button_state()

    @Slot()
    def _remove_queued(self) -> None:
        row = self.queue_list.currentRow()
        if row < 0:
            return
        self.queue_list.takeItem(row)
        self._renumber_queue()
        self._update_button_state()

    def _drop_from_queue(self, paths: set[Path]) -> None:
        """Take deleted jobs out of the queue, so it cannot point at nothing."""
        for row in reversed(range(self.queue_list.count())):
            listing = self.queue_list.item(row).data(_LISTING_ROLE)
            if isinstance(listing, JobListing) and listing.path in paths:
                self.queue_list.takeItem(row)
        self._renumber_queue()

    def _selection_hint(self) -> str:
        """One line saying what the current selection can and cannot do."""
        selected = self._selected_listings()
        if not selected:
            return "Select a job to load, or several prepared ones to add to the queue."

        # The selected job, not the current one -- see `_rename_selected`.
        # The hint is display-only, but it still has to name the row that is
        # actually highlighted, not whatever `currentItem()` last landed on.
        if len(selected) == 1:
            listing = selected[0]
            if not listing.matches_profile(self.active_profile):
                return (
                    f"'{listing.name}' was saved under config "
                    f"'{listing.config_profile}'. Use 'Switch profile and load' "
                    "to open it."
                )
            if not listing.prepared:
                return (
                    f"'{listing.name}' still needs input, so it can be loaded "
                    "but not added to the queue."
                )
            return f"'{listing.name}' is ready to load or add to the queue."

        unprepared = sum(1 for entry in selected if not entry.prepared)
        other_config = sum(
            1 for entry in selected if not entry.matches_profile(self.active_profile)
        )
        reasons: list[str] = []
        if unprepared:
            reasons.append(f"{unprepared} not prepared")
        if other_config:
            reasons.append(f"{other_config} on another config")
        # Counted once here for the headline, even though a job that is both
        # unprepared and on another config is counted in both `reasons` --
        # otherwise one such job selected reads as two problem jobs.
        blocked = [
            entry
            for entry in selected
            if not entry.prepared or not entry.matches_profile(self.active_profile)
        ]
        if blocked:
            return (
                f"{len(selected)} selected; {len(blocked)} cannot be added to "
                "the queue (" + ", ".join(reasons) + "). A queue has nobody to "
                "answer a prompt."
            )
        return f"{len(selected)} prepared job(s) selected; ready to add to the queue."

    @Slot()
    def _on_tree_selection_changed(self) -> None:
        self._details_source = "tree"
        self._update_button_state()

    @Slot()
    def _on_queue_row_changed(self) -> None:
        self._details_source = "queue"
        self._update_button_state()

    @Slot()
    def _update_button_state(self) -> None:
        # The selected job, not the current one -- see `_rename_selected`.
        # Enablement and the actions it gates have to agree with the same
        # row, or a coherent-looking UI can act on one job while highlighting
        # another.
        selected = self._selected_listings()
        listing = selected[0] if len(selected) == 1 else None
        matches = listing is not None and listing.matches_profile(self.active_profile)

        self.delete_btn.setEnabled(bool(selected))
        self.rename_btn.setEnabled(len(selected) == 1)
        self.switch_btn.setEnabled(
            len(selected) == 1 and listing is not None and not matches
        )
        # every selected job has to be addable, so a mixed selection cannot
        # silently drop the ones it would skip
        addable = [listing for listing in selected if self._can_queue(listing)]
        self.add_to_queue_btn.setEnabled(
            bool(addable) and len(addable) == len(selected)
        )
        self.queue_btn.setEnabled(self.queue_list.count() > 0)
        row = self.queue_list.currentRow()
        self.queue_up_btn.setEnabled(row > 0)
        self.queue_down_btn.setEnabled(0 <= row < self.queue_list.count() - 1)
        self.queue_remove_btn.setEnabled(row >= 0)
        open_button = self.button_box.button(QDialogButtonBox.StandardButton.Open)
        if open_button:
            open_button.setEnabled(matches and len(selected) == 1)
        self.status_lbl.setText(self._selection_hint())
        self._refresh_details()

    def _describe(self, listing: JobListing) -> str:
        """Everything worth knowing about a job before committing to it.

        The per-tracker image hosts and the screenshot count only exist in the
        job's document, so it is read here rather than at list time -- one file
        read when a row is picked, instead of one per job on every open.

        Memoised by path in `self._details_cache`: this reads the job's
        document and walks its folder on disk, and a job's rendered
        description cannot change while it sits in the same tree between
        reloads, so a second call for a job already described this session
        would otherwise repeat both for no new information.
        """
        cached = self._details_cache.get(listing.path)
        if cached is not None:
            return cached

        rows: list[tuple[str, str]] = [
            ("Saved", self._saved_text(listing.created_at)),
            (
                "Config",
                escape(listing.config_profile)
                if listing.config_profile
                else "not recorded",
            ),
            ("State", "Prepared" if listing.prepared else "Needs input"),
        ]
        title_text = self._title_text(listing)
        if title_text:
            rows.append(("Title", escape(title_text)))
        summary = listing.summary
        if summary.media_type:
            rows.append(("Type", escape(summary.media_type)))
        if summary.file_count:
            rows.append(("Files", str(summary.file_count)))
        if summary.input_path:
            note = "" if listing.media_available else "  (no longer there)"
            rows.append(("Media", f"{escape(summary.input_path)}{note}"))

        try:
            job = load_job(listing.path)
        except JobStoreError as error:
            LOG.warning(LOG.LOG_SOURCE.FE, f"Could not describe job: {error}")
            job = None

        if job is not None:
            shared = job.context.get("shared_data")
            if isinstance(shared, dict):
                images = shared.get("loaded_images")
                if isinstance(images, list):
                    rows.append(("Screenshots", f"{len(images)} screenshot(s)"))
                hosts = shared.get("tracker_image_hosts")
                if isinstance(hosts, dict) and hosts:
                    rows.append(
                        (
                            "Trackers",
                            "<br />".join(
                                f"{escape(self._tracker_display_name(name))} &rarr; "
                                f"{escape(self._image_host_display_name(entry))}"
                                for name, entry in hosts.items()
                                if isinstance(entry, dict)
                            ),
                        )
                    )
        if not any(label == "Trackers" for label, _ in rows) and summary.trackers:
            rows.append(("Trackers", "<br />".join(map(escape, summary.trackers))))

        try:
            rows.append(("On disk", file_bytes_to_str(get_dir_size(listing.path))))
        except OSError:
            pass
        rows.append(("Folder", escape(str(listing.path))))

        body = "".join(
            f"<tr><td style='padding-right: 10px;'><b>{label}</b></td>"
            f"<td>{value}</td></tr>"
            for label, value in rows
        )
        rendered = (
            f"<p style='margin: 0 0 6px 0;'><b>{escape(listing.name)}</b></p>"
            f"<table>{body}</table>"
        )
        self._details_cache[listing.path] = rendered
        return rendered

    def _refresh_details(self) -> None:
        """Render the details pane for the active source's current listing.

        The active source -- tree or queue -- comes from `_details_listing`.
        `_update_button_state` runs this on every filter keystroke, which
        moves neither pane's current item. Bailing out here when the listing
        to show has not changed since the last call is what stops that from
        re-reading the job's document and re-walking its folder for no
        reason; `_describe`'s own memoisation only covers the read, not the
        `is_dir()` stat this method also does. Switching source to a
        different job changes the path and so still re-renders; if the same
        job sits in both panes the early return is correct, since the
        rendered content would be identical either way.
        """
        listing = self._details_listing()

        path = listing.path if listing is not None else None
        if path == self._last_described_path:
            return
        self._last_described_path = path

        if listing is None:
            self.details_lbl.setText("")
            self.open_folder_btn.setEnabled(False)
            return
        self.details_lbl.setText(self._describe(listing))
        self.open_folder_btn.setEnabled(listing.path.is_dir())

    @Slot()
    def _open_job_folder(self) -> None:
        # Follows the same source as the details pane it sits under -- see
        # `_details_listing` -- so the button never opens a different job's
        # folder than the one the pane is currently describing.
        listing = self._details_listing()
        if listing is not None:
            open_explorer(listing.path)

    @Slot(QTreeWidgetItem, int)
    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        """Open on double click, routing a cross-profile job to the switch.

        Doing nothing is what this used to do, and it reads as the dialog being
        broken rather than as the job needing a different config.
        """
        listing = item.data(0, _LISTING_ROLE)
        if not isinstance(listing, JobListing):
            return
        self.job_tree.setCurrentItem(item)
        if listing.matches_profile(self.active_profile):
            self._accept_selection()
        else:
            self._accept_with_switch()

    @Slot()
    def _accept_selection(self) -> None:
        # The selected job, not the current one -- see `_rename_selected`.
        # This is what lands on the process page, where the next action is
        # Process: loading the wrong release here uploads it to a tracker.
        selected = self._selected_listings()
        if len(selected) != 1:
            return
        listing = selected[0]
        if not listing.matches_profile(self.active_profile):
            return
        self.selected_listing = listing
        self.switch_profile_requested = False
        self.accept()

    @Slot()
    def _accept_queue(self) -> None:
        queued = self.queueable_listings()
        if not queued:
            return
        self.queued_listings = queued
        self.selected_listing = None
        self.accept()

    @Slot()
    def _accept_with_switch(self) -> None:
        # The selected job, not the current one -- see `_rename_selected`.
        # This drives `_switch_config_profile`, which loads a profile and
        # emits `settings_refresh`: a persistent, global config change made
        # on the strength of a row the user did not select.
        selected = self._selected_listings()
        if len(selected) != 1:
            return
        listing = selected[0]
        if listing.matches_profile(self.active_profile):
            return
        self.selected_listing = listing
        self.switch_profile_requested = True
        self.accept()

    @Slot()
    def _delete_selected(self) -> None:
        listings = self._selected_listings()
        if not listings:
            return

        # Spelled out rather than "job(s)": this is the one irreversible action
        # in the dialog, and the list of what goes with it has to match what a
        # job directory actually holds. On disk that's images/, mediainfo/,
        # nfo/ and the base torrent; the text below names the same four
        # things in the terms a user recognizes -- screenshots, MediaInfo,
        # NFOs and torrent(s). Omitting any of them understates the loss.
        count = len(listings)
        names = "\n".join(f"  {listing.name}" for listing in listings)
        if count == 1:
            title = "Delete Job"
            question = "Delete this saved job?"
            consequence = (
                "This also removes its screenshots, MediaInfo, NFOs and torrent."
            )
        else:
            title = "Delete Jobs"
            question = f"Delete these {count} saved jobs?"
            consequence = (
                "This also removes their screenshots, MediaInfo, NFOs and torrents."
            )

        if (
            QMessageBox.question(
                self,
                title,
                f"{question}\n\n{names}\n\n{consequence} It cannot be undone.",
            )
            is not QMessageBox.StandardButton.Yes
        ):
            return

        removed: set[Path] = set()
        failures: list[str] = []
        for listing in listings:
            try:
                delete_job(listing.path)
            except JobStoreError as error:
                LOG.error(LOG.LOG_SOURCE.FE, f"Failed to delete job: {error}")
                failures.append(f"{listing.name}: {error}")
                continue
            removed.add(listing.path)

        if failures:
            QMessageBox.critical(
                self,
                "Delete Failed",
                "Some jobs could not be deleted:\n\n" + "\n".join(failures),
            )

        # Only what actually went. A job whose delete failed is still on disk
        # and still runnable, so dropping it from the queue would be a second,
        # silent consequence of an operation that did not happen -- and the
        # user would lose its queue position with nothing saying so.
        self._drop_from_queue(removed)
        self._load_listings()

    @Slot()
    def _rename_selected(self) -> None:
        """Rewrite a job's display name, and nothing else.

        The job id and its directory are untouched, so nothing pointing at the
        job by path -- a queue mid-flight, a listing already on screen -- is
        invalidated by the rename.
        """
        # The selected job, not the current one. `currentItem()` can sit on a
        # row that is not selected -- ctrl+click a second row, ctrl+click it
        # again, and the current item stays there while the first row remains
        # the only selection. Renaming what is current would rewrite the wrong
        # job's name on disk while the right one is still highlighted. The
        # sibling load/switch actions have the same shape but only mis-open a
        # job; this one writes.
        selected = self._selected_listings()
        if len(selected) != 1:
            return
        listing = selected[0]

        name, accepted = QInputDialog.getText(
            self, "Rename Job", "Job name:", text=listing.name
        )
        if not accepted or not name.strip():
            return

        try:
            job = load_job(listing.path)
            job.name = name.strip()
            write_job_document(job, listing.path)
        except JobStoreError as error:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to rename job: {error}")
            QMessageBox.critical(
                self,
                "Rename Failed",
                f"Could not rename '{listing.name}':\n\n{error}",
            )
            return

        self._load_listings()
