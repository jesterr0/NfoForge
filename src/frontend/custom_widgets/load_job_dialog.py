"""Picker for saved jobs."""

from collections.abc import Generator
from contextlib import contextmanager, suppress
from datetime import datetime
from enum import Enum
from html import escape
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
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
    reselect_trackers,
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
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.setSizeGripEnabled(True)

        self.active_profile = active_profile or ""
        self.selected_listing: JobListing | None = None
        self.switch_profile_requested = False
        self.add_trackers_requested = False
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
        `_on_tree_selection_changed` and `_on_queue_row_changed`, below --
        which is also where `_suppress_source_tracking` is checked.
        """
        self._suppress_source_tracking: bool = False
        """Set by `_programmatic_selection`, below, around a selection
        change that is queue/tree bookkeeping rather than user interaction --
        `_apply_filter` deselecting a hidden row, a reload re-clearing and
        re-selecting the tree, the queue reordering or dropping a row.
        Checked directly here rather than through the context manager, since
        these two slots are the signal handlers it is guarding against, not
        callers of it.
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
        # Every column sizes to its own contents rather than sharing out the
        # panel's width: this tree sits in a splitter pane the user can pull
        # narrow, and stretching Name and Title to fit it truncated exactly
        # the two columns a job is recognized by. The row is free to end up
        # wider than the pane instead, which is what the horizontal scrollbar
        # below is for -- and why the last section must not stretch.
        header = self.job_tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)

        self.job_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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

        # we'll wrap the job tree in a widget to match spacing of the other panels
        job_panel = QWidget(self)
        job_layout = QVBoxLayout(job_panel)
        job_layout.setContentsMargins(0, 0, 8, 0)
        job_layout.addWidget(self.job_tree, stretch=1)

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
        self.splitter.addWidget(job_panel)
        self.splitter.addWidget(queue_panel)
        self.splitter.addWidget(details_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setStretchFactor(2, 2)
        # after UI loads we'll set the size of each panel relative to the UI
        QTimer.singleShot(0, self._set_initial_splitter_sizes)

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

        self.add_trackers_btn = QPushButton("Add Trackers", self)
        self.add_trackers_btn.setToolTip(
            "Choose new trackers for a reusable archived release"
        )
        self.add_trackers_btn.clicked.connect(self._accept_add_trackers)

        self.resolve_uncertain_btn = QPushButton("Resolve Uncertain", self)
        self.resolve_uncertain_btn.setToolTip(
            "Record whether an upload with an unknown result reached its tracker"
        )
        self.resolve_uncertain_btn.clicked.connect(self._resolve_uncertain)

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
        bottom_row.addWidget(self.resolve_uncertain_btn)
        bottom_row.addWidget(self.add_trackers_btn)
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

    def _set_initial_splitter_sizes(self) -> None:
        """Calculate the right size to set the sizes of each column"""
        width = self.splitter.width()
        self.splitter.setSizes(
            [
                width * 3 // 7,
                width * 2 // 7,
                width * 2 // 7,
            ]
        )

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

        # Deselecting whatever the tree held fires itemSelectionChanged if
        # something was selected -- a reload triggered by a rename or delete
        # must not use that to yank a queue-sourced pane back to the tree
        # before the reload has even produced anything to show. Confirmed
        # empirically: without this, the source flips here, synchronously,
        # before `_on_listings_loaded` ever runs.
        with self._programmatic_selection():
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
        # Repopulating the tree fires tree signals; see the same suppression
        # in `_load_listings`. This clear is a no-op selection-wise today --
        # `_load_listings` already emptied the tree before starting the
        # loader that ends up here -- but it costs nothing to keep guarded
        # rather than depend on that staying true.
        with self._programmatic_selection():
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
                    self._tracker_column_text(listing),
                    listing.config_profile or "—",
                    "Archive"
                    if listing.archived and not listing.summary.trackers
                    else "Prepared"
                    if listing.prepared
                    else "Needs input",
                    self._saved_text(listing.created_at),
                )
            )
            item.setData(0, _LISTING_ROLE, listing)
            item.setIcon(
                5,
                prepared_icon
                if listing.prepared or listing.archived
                else needs_input_icon,
            )
            # the Trackers column is Interactive and elides, so the full list
            # has to be reachable somewhere
            tracker_tooltip = self._tracker_tooltip(listing)
            if tracker_tooltip:
                item.setToolTip(3, tracker_tooltip)
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
                    (
                        "The original media is no longer present, but this "
                        "archive can still add trackers from its saved package."
                        if listing.source_less_ready
                        else "The media this job was built from is no longer at "
                        f"'{listing.summary.input_path}', so it cannot be processed "
                        "until the file is back."
                    ),
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
            # Selecting the tree's own first row on every reload must not
            # steal a queue-sourced pane back either -- same reasoning as
            # the clear() above.
            with self._programmatic_selection():
                self.job_tree.setCurrentItem(first_item)

        # Queue items keep the JobListing they were queued with, which is now
        # stale if the job was renamed since -- rebind each one to the fresh
        # listing at the same path so `_renumber_queue` renders the current
        # name. Only paths still present here are touched: a job missing from
        # one scan is not proof it is gone, and dropping its queue entry
        # would be an undisclosed side effect, the same reasoning
        # `_delete_selected` already applies to a failed delete.
        by_path = {listing.path: listing for listing in listings}
        for row in range(self.queue_list.count()):
            queue_item = self.queue_list.item(row)
            stored = queue_item.data(_LISTING_ROLE)
            if isinstance(stored, JobListing) and stored.path in by_path:
                queue_item.setData(_LISTING_ROLE, by_path[stored.path])
        self._renumber_queue()
        # The rebind above can change a queue-sourced listing's rendered
        # content without changing its path -- a rename keeps the same path.
        # `_load_listings` already cleared `_details_cache` and reset
        # `_last_described_path` once at the start of this reload, but the
        # button-state refresh that runs there (while the tree is still
        # empty and the queue not yet rebound) reads and caches the *old*
        # queue listing at that same path -- both `_describe`'s cache and
        # `_refresh_details`'s memo -- before this rebind has a chance to
        # matter. Clearing and resetting again here is what lets the
        # `_apply_filter` call below actually re-render it.
        self._details_cache.clear()
        self._last_described_path = None

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

        The deselect is a programmatic change, not the user picking a
        different row -- typing in the filter box must not steal the details
        pane away from a queue-sourced description, so it runs inside
        `_programmatic_selection`.
        """
        needle = self.filter_edit.text().strip().casefold()
        only_mine = self.only_this_config.isChecked()

        with self._programmatic_selection():
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
                        " ".join(listing.summary.uploaded_trackers),
                        " ".join(listing.summary.uncertain_trackers),
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
    def _tracker_column_text(listing: JobListing) -> str:
        summary = listing.summary
        if not summary.uploaded_trackers and not summary.uncertain_trackers:
            return ", ".join(summary.trackers)
        parts: list[str] = []
        if summary.trackers:
            parts.append(f"Pending: {', '.join(summary.trackers)}")
        if summary.uploaded_trackers:
            parts.append(f"Uploaded: {', '.join(summary.uploaded_trackers)}")
        if summary.uncertain_trackers:
            parts.append(f"Uncertain: {', '.join(summary.uncertain_trackers)}")
        return "; ".join(parts)

    @staticmethod
    def _tracker_tooltip(listing: JobListing) -> str:
        summary = listing.summary
        lines = [f"Pending: {tracker}" for tracker in summary.trackers]
        lines.extend(f"Uploaded: {tracker}" for tracker in summary.uploaded_trackers)
        lines.extend(f"Uncertain: {tracker}" for tracker in summary.uncertain_trackers)
        return "\n".join(lines)

    @staticmethod
    def _tracker_display_name(raw_name: object) -> str:
        """A tracker's saved-job key, in the same casing the rest of the UI uses.

        `tracker_image_hosts` is keyed by `TrackerSelection` member *name*
        (`"AITHER"`), matching the round-trip-by-name convention the job codec
        uses everywhere -- see `src/backend/jobs/codec.py`. That is not the
        member's display value (`"Aither"`), which is what the tree's Trackers
        column and `JobSummary.trackers` both show. A name a current build no
        longer recognizes -- a retired tracker -- falls back to the raw string
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
        the raw name and the pane shows "Aither -> CHEVERETO_V3": a humanized
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
            if item is not None:
                listing = item.data(_LISTING_ROLE)
                if isinstance(listing, JobListing):
                    return listing
            # The queue emptied, or lost the row being described, out from
            # under a queue-sourced pane -- a different widget's action, not
            # the user switching away. Falling through to the tree below
            # always leaves something sensible on screen, rather than a pane
            # that goes blank for no reason the user did anything about.

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

    def _can_load(self, listing: JobListing) -> bool:
        """Whether plain "Load" can open this job as it stands.

        An archive with no trackers left has nothing for the process page to
        run, so loading it lands the user on a page whose only button fails.
        Its way back into a wizard is 'Add Trackers', which starts at the
        tracker page instead.

        This is the rule, not a copy of it: `_update_button_state` gates the
        Load button on it and `_accept_selection` enforces it, because the
        button being disabled never stopped a double click.
        """
        if not listing.matches_profile(self.active_profile):
            return False
        return not listing.archived or bool(listing.summary.trackers)

    def _can_add_trackers(self, listing: JobListing) -> bool:
        """Whether this job can be reopened to pick trackers it has not used.

        Only an archive that still carries its own release package qualifies:
        choosing new trackers is worth offering precisely when the media it
        was built from may be long gone.
        """
        return (
            listing.matches_profile(self.active_profile)
            and listing.archived
            and listing.source_less_ready
        )

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
        # takeItem() and setCurrentRow() both fire currentRowChanged -- this
        # is the queue reordering itself, not the user picking the queue
        # pane, so it must not set the source. See `_programmatic_selection`.
        with self._programmatic_selection():
            self.queue_list.insertItem(target, self.queue_list.takeItem(row))
            self.queue_list.setCurrentRow(target)
        self._renumber_queue()
        self._update_button_state()

    @Slot()
    def _remove_queued(self) -> None:
        row = self.queue_list.currentRow()
        if row < 0:
            return
        # takeItem() on the current row fires currentRowChanged -- removing a
        # row is not the user picking the queue pane. See
        # `_programmatic_selection`.
        with self._programmatic_selection():
            self.queue_list.takeItem(row)
        self._renumber_queue()
        self._update_button_state()

    def _drop_from_queue(self, paths: set[Path]) -> None:
        """Take deleted jobs out of the queue, so it cannot point at nothing."""
        # Same reasoning as `_remove_queued`: a delete elsewhere is not the
        # user picking the queue pane.
        with self._programmatic_selection():
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
            if not self._can_load(listing):
                # Pointing at 'Add Trackers' is only useful while that button
                # is the one enabled; an archive missing its base torrent or
                # its MediaInfo cannot take that route either, and saying so
                # beats naming an action that does nothing.
                if self._can_add_trackers(listing):
                    return (
                        f"'{listing.name}' has already uploaded to every tracker "
                        "it was run for. Use 'Add Trackers' to send it somewhere "
                        "new."
                    )
                return (
                    f"'{listing.name}' has already uploaded to every tracker it "
                    "was run for, and its saved release package is incomplete, "
                    "so it cannot be reopened for new ones."
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

    @contextmanager
    def _programmatic_selection(self) -> Generator[None, None, None]:
        """Mark a block that changes tree or queue selection without the
        user having picked anything, so the source-setting slots below
        ignore whatever `itemSelectionChanged`/`currentRowChanged` it fires.

        Not reentrant -- nothing in this file nests one of these blocks
        inside another, and if that ever changes, the inner block's own
        `finally` would clear the flag while the outer block is still in
        progress. Centralizing the flag toggle here exists specifically so a
        future call site is a single self-documenting line instead of a
        try/finally to notice and copy correctly: the sites needing this
        have been missed by enumeration three times over this feature's
        review history.
        """
        self._suppress_source_tracking = True
        try:
            yield
        finally:
            self._suppress_source_tracking = False

    @Slot()
    def _on_tree_selection_changed(self) -> None:
        # Programmatic selection changes -- a filter hiding a row, a reload
        # re-populating the tree -- must not be mistaken for the user
        # switching panes. See `_programmatic_selection`.
        if self._suppress_source_tracking:
            return
        self._details_source = "tree"
        self._update_button_state()

    @Slot()
    def _on_queue_row_changed(self) -> None:
        if self._suppress_source_tracking:
            return
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
        self.add_trackers_btn.setEnabled(
            bool(listing is not None and self._can_add_trackers(listing))
        )
        self.resolve_uncertain_btn.setEnabled(
            bool(listing and matches and listing.summary.uncertain_trackers)
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
            open_button.setEnabled(
                bool(listing is not None and self._can_load(listing))
            )
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
            (
                "State",
                "Archive"
                if listing.archived and not listing.summary.trackers
                else "Prepared"
                if listing.prepared
                else "Needs input",
            ),
        ]
        title_text = self._title_text(listing)
        if title_text:
            rows.append(("Title", escape(title_text)))
        summary = listing.summary
        if summary.media_type:
            rows.append(("Type", escape(summary.media_type)))
        if summary.file_count:
            rows.append(("Files", str(summary.file_count)))
        if summary.uploaded_trackers:
            rows.append(
                ("Uploaded", "<br />".join(map(escape, summary.uploaded_trackers)))
            )
        if summary.uncertain_trackers:
            rows.append(
                (
                    "Uncertain",
                    "<br />".join(map(escape, summary.uncertain_trackers)),
                )
            )
        if summary.input_path:
            note = (
                ""
                if listing.media_available
                else "  (archived package available)"
                if listing.source_less_ready
                else "  (no longer there)"
            )
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
        """Open on double click, routing a job to whatever it can actually do.

        Doing nothing is what this used to do, and it reads as the dialog being
        broken rather than as the job needing a different config. Each branch
        picks the same action the row's own enabled button offers: a
        cross-profile job goes through the profile switch, and an archive with
        no trackers left goes to 'Add Trackers', since a plain load would drop
        it on a process page with nothing to process.
        """
        listing = item.data(0, _LISTING_ROLE)
        if not isinstance(listing, JobListing):
            return
        self.job_tree.setCurrentItem(item)
        if not listing.matches_profile(self.active_profile):
            self._accept_with_switch()
        elif self._can_load(listing):
            self._accept_selection()
        elif self._can_add_trackers(listing):
            self._accept_add_trackers()
        # else: nothing this dialog can do with it, which `_selection_hint`
        # says in words rather than leaving the click to look ignored

    @Slot()
    def _accept_selection(self) -> None:
        # The selected job, not the current one -- see `_rename_selected`.
        # This is what lands on the process page, where the next action is
        # Process: loading the wrong release here uploads it to a tracker.
        selected = self._selected_listings()
        if len(selected) != 1:
            return
        listing = selected[0]
        if not self._can_load(listing):
            return
        self.selected_listing = listing
        self.switch_profile_requested = False
        self.add_trackers_requested = False
        self.accept()

    @Slot()
    def _accept_add_trackers(self) -> None:
        selected = self._selected_listings()
        if len(selected) != 1:
            return
        listing = selected[0]
        if not self._can_add_trackers(listing):
            return
        self.selected_listing = listing
        self.switch_profile_requested = False
        self.add_trackers_requested = True
        self.accept()

    @Slot()
    def _resolve_uncertain(self) -> None:
        selected = self._selected_listings()
        if len(selected) != 1:
            return
        listing = selected[0]
        try:
            job = load_job(listing.path)
        except JobStoreError as error:
            QMessageBox.critical(self, "Update Failed", str(error))
            return
        uploaded = set(job.uploaded_trackers)
        unresolved = list(job.uncertain_trackers)
        # "it never landed" has to make the tracker runnable again, not just
        # move its name between two lists. Its title, NFO and image host were
        # kept in the context for exactly this moment (see
        # `codec.filter_context_document`), so putting it back in
        # `selected_trackers` restores the release the user already reviewed.
        runnable: list[TrackerSelection] = []
        for tracker_name in unresolved:
            try:
                display = str(TrackerSelection[tracker_name])
            except KeyError:
                display = tracker_name
            result = QMessageBox.question(
                self,
                "Resolve Upload",
                f"Did the upload to {display} reach the tracker?\n\n"
                "Choose Yes if it is present, No if it is safe to upload, or "
                "Cancel to leave it unresolved.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if result is QMessageBox.StandardButton.Cancel:
                continue
            job.uncertain_trackers.remove(tracker_name)
            if result is QMessageBox.StandardButton.Yes:
                uploaded.add(tracker_name)
            elif tracker_name in TrackerSelection.__members__:
                runnable.append(TrackerSelection[tracker_name])
        job.uploaded_trackers = sorted(uploaded)
        if runnable:
            job.context = reselect_trackers(job.context, runnable)
            # Only what `reselect_trackers` actually took. It refuses a tracker
            # whose title and NFO are gone, and a summary claiming the job
            # covers one the context cannot run is the mismatch that makes the
            # picker offer a job the wizard then builds no row for.
            #
            # `JobSummary.trackers` holds display values while the context
            # holds member names -- mixing the two fails silently.
            shared = job.context.get("shared_data")
            selected = (
                shared.get("selected_trackers") if isinstance(shared, dict) else []
            )
            accepted = {
                str(tracker)
                for tracker in runnable
                if isinstance(selected, list) and tracker.name in selected
            }
            job.summary.trackers = sorted(set(job.summary.trackers) | accepted)
        job.summary.uncertain_trackers = [
            str(TrackerSelection[name])
            for name in job.uncertain_trackers
            if name in TrackerSelection.__members__
        ]
        job.summary.uploaded_trackers = [
            str(TrackerSelection[name])
            for name in job.uploaded_trackers
            if name in TrackerSelection.__members__
        ]
        try:
            write_job_document(job, listing.path)
        except JobStoreError as error:
            QMessageBox.critical(self, "Update Failed", str(error))
            return
        self._load_listings()

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

        name, accepted = self._change_job_name(listing.name)
        if not accepted or not name:
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

    def _change_job_name(self, cur_name: str | None) -> tuple[str, bool]:
        """Dialog to gather change job name from user."""
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Rename Job")
        dlg.setLabelText("Job name:")

        if cur_name:
            dlg.setTextValue(cur_name)

        dlg.resize(400, dlg.sizeHint().height())

        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        if not accepted:
            return "", False

        return dlg.textValue().strip(), True
