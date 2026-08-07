"""Picker for saved jobs."""

from datetime import datetime

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from src.backend.jobs import JobListing, JobStoreError, delete_job, list_jobs
from src.config.profiles import unique_working_dirs
from src.logger.nfo_forge_logger import LOG

_LISTING_ROLE = Qt.ItemDataRole.UserRole


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

        self.info_lbl = QLabel(
            "<i><span>Pick a saved job to jump straight to processing. Duplicate "
            "checks still run when you process it.<br />Jobs saved under another "
            "config are shown greyed out; use <b>Switch profile and load</b> to "
            "open one.</span></i>",
            wordWrap=True,
            parent=self,
        )

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter by name, title or tracker...")
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
        self.job_tree.setSortingEnabled(True)
        # multi-select so several prepared jobs can be queued in one go
        self.job_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.job_tree.itemDoubleClicked.connect(self._on_double_click)
        self.job_tree.itemSelectionChanged.connect(self._update_button_state)

        self.empty_lbl = QLabel(
            "<span>No saved jobs yet. Use <b>Save Job</b> on the process page "
            "to create one.</span>",
            wordWrap=True,
            parent=self,
        )
        self.empty_lbl.hide()

        self.status_lbl = QLabel("", wordWrap=True, parent=self)
        self.status_lbl.setTextFormat(Qt.TextFormat.PlainText)

        self.delete_btn = QPushButton("Delete", self)
        self.delete_btn.setShortcut(Qt.Key.Key_Delete)
        self.delete_btn.clicked.connect(self._delete_selected)

        self.switch_btn = QPushButton("Switch profile and load", self)
        self.switch_btn.setToolTip(
            "Activate the config this job was saved under, then load it"
        )
        self.switch_btn.clicked.connect(self._accept_with_switch)

        self.queue_btn = QPushButton("Run Queue", self)
        self.queue_btn.setToolTip(
            "Upload the selected jobs one after another. Only prepared jobs on "
            "this config can be queued, since a queue has nobody to answer a "
            "prompt"
        )
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
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.queue_btn)
        bottom_row.addWidget(self.switch_btn)
        bottom_row.addWidget(self.button_box)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.info_lbl)
        main_layout.addLayout(filter_row)
        main_layout.addWidget(self.empty_lbl)
        main_layout.addWidget(self.job_tree, stretch=1)
        main_layout.addWidget(self.status_lbl)
        main_layout.addLayout(bottom_row)

        self._load_listings()

    def _load_listings(self) -> None:
        # sorting reshuffles the tree on every insert otherwise, which is
        # wasted work and would show rows swapping places as they load
        self.job_tree.setSortingEnabled(False)
        self.job_tree.clear()
        listings = list_jobs(unique_working_dirs())
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
        self.empty_lbl.setVisible(not has_jobs)
        first_item = self.job_tree.topLevelItem(0)
        if first_item is not None:
            self.job_tree.setCurrentItem(first_item)
        self._apply_filter()

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

    def _current_listing(self) -> JobListing | None:
        # an empty tree has no current item, so emptiness needs no separate
        # check here -- and must not be inferred from widget visibility, which
        # is still false before the dialog is shown
        item = self.job_tree.currentItem()
        if item is None:
            return None
        listing = item.data(0, _LISTING_ROLE)
        return listing if isinstance(listing, JobListing) else None

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
        """Selected jobs the queue is actually allowed to run.

        Both conditions are load-bearing: a job from another config would upload
        with the wrong credentials, and an unprepared one would stop at a prompt.
        """
        return [
            listing
            for listing in self._selected_listings()
            if listing.prepared and listing.matches_profile(self.active_profile)
        ]

    def _selection_hint(self) -> str:
        """One line saying what the current selection can and cannot do."""
        selected = self._selected_listings()
        if not selected:
            return "Select a job to load, or several prepared ones to queue."

        listing = self._current_listing()
        if len(selected) == 1 and listing is not None:
            if not listing.matches_profile(self.active_profile):
                return (
                    f"'{listing.name}' was saved under config "
                    f"'{listing.config_profile}'. Use 'Switch profile and load' "
                    "to open it."
                )
            if not listing.prepared:
                return (
                    f"'{listing.name}' still needs input, so it can be loaded "
                    "but not queued."
                )
            return f"'{listing.name}' is ready to load or queue."

        unprepared = sum(1 for entry in selected if not entry.prepared)
        other_config = sum(
            1 for entry in selected if not entry.matches_profile(self.active_profile)
        )
        reasons: list[str] = []
        if unprepared:
            reasons.append(f"{unprepared} not prepared")
        if other_config:
            reasons.append(f"{other_config} on another config")
        if reasons:
            return (
                f"{len(selected)} selected; cannot queue because "
                + " and ".join(reasons)
                + ". A queue has nobody to answer a prompt."
            )
        return f"{len(selected)} prepared job(s) selected; ready to queue."

    @Slot()
    def _update_button_state(self) -> None:
        listing = self._current_listing()
        matches = listing is not None and listing.matches_profile(self.active_profile)
        selected = self._selected_listings()
        queueable = self.queueable_listings()

        self.delete_btn.setEnabled(bool(selected))
        self.switch_btn.setEnabled(
            len(selected) == 1 and listing is not None and not matches
        )
        # every selected job has to be runnable, so a mixed selection cannot
        # silently drop the ones it would skip
        self.queue_btn.setEnabled(bool(queueable) and len(queueable) == len(selected))
        open_button = self.button_box.button(QDialogButtonBox.StandardButton.Open)
        if open_button:
            open_button.setEnabled(matches and len(selected) == 1)
        self.status_lbl.setText(self._selection_hint())

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
        listing = self._current_listing()
        if listing is None or not listing.matches_profile(self.active_profile):
            return
        self.selected_listing = listing
        self.switch_profile_requested = False
        self.accept()

    @Slot()
    def _accept_queue(self) -> None:
        queueable = self.queueable_listings()
        if not queueable or len(queueable) != len(self._selected_listings()):
            return
        self.queued_listings = queueable
        self.selected_listing = None
        self.accept()

    @Slot()
    def _accept_with_switch(self) -> None:
        listing = self._current_listing()
        if listing is None or listing.matches_profile(self.active_profile):
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
        # job directory actually holds -- images/, mediainfo/, nfo/ and the
        # base torrent. Omitting any of them understates the loss.
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

        failures: list[str] = []
        for listing in listings:
            try:
                delete_job(listing.path)
            except JobStoreError as error:
                LOG.error(LOG.LOG_SOURCE.FE, f"Failed to delete job: {error}")
                failures.append(f"{listing.name}: {error}")

        if failures:
            QMessageBox.critical(
                self,
                "Delete Failed",
                "Some jobs could not be deleted:\n\n" + "\n".join(failures),
            )
        self._load_listings()
