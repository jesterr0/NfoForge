from collections.abc import Iterable, Mapping
from pathlib import Path
import traceback
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
    QPushButton,
    QWizard,
)

from src.backend.jobs import (
    JobCodecError,
    JobStoreError,
    MediaFingerprint,
    SavedJob,
    archived_base_is_valid,
    base_torrent_path,
    context_from_dict,
    fingerprints_match,
    load_job,
    read_job_asset,
    template_fingerprint,
)
from src.backend.template_selector import TemplateSelectorBackEnd
from src.backend.utils.media_info_utils import clear_restored_mediainfo
from src.config.config import ConfigManager
from src.context.factory import create_processing_context
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.tracker_selection import TrackerSelection
from src.enums.wizard import WizardPages
from src.exceptions import ConfigSchemaError
from src.frontend.custom_widgets.job_queue_dialog import JobQueueDialog
from src.frontend.custom_widgets.load_job_dialog import LoadJobDialog
from src.frontend.global_signals import GSigs
from src.frontend.wizards.images import ImagesPage
from src.frontend.wizards.media_input import MediaInput
from src.frontend.wizards.media_search import MediaSearch
from src.frontend.wizards.pre_upload import PreUploadPage
from src.frontend.wizards.process import ProcessPage
from src.frontend.wizards.rename_encode import RenameEncode
from src.frontend.wizards.rename_encode_series import RenameEncodeSeries
from src.frontend.wizards.series_match import SeriesMatch
from src.frontend.wizards.trackers import TrackersPage
from src.frontend.wizards.wizard_base_page import BaseWizardPage, DummyWizardPage
from src.logger.nfo_forge_logger import LOG

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


def tracker_profile_problems(
    trackers: Iterable[TrackerSelection],
    tracker_map: Mapping[TrackerSelection, Any],
    template_selector: TemplateSelectorBackEnd,
) -> list[str]:
    """Ways the *active* profile cannot fully serve `trackers`.

    A job stores no settings of its own -- credentials, templates and
    per-tracker toggles are all read live -- so this asks the live config, not
    the job.

    Deliberately silent about a tracker with no template assigned at all: a
    prepared job uploads a frozen NFO and does not care, and an unprepared one
    is stopped by the pre-upload page, which names the trackers precisely.
    """
    available_templates = set(template_selector.load_templates())
    problems: list[str] = []
    for tracker in trackers:
        tracker_info = tracker_map.get(tracker)
        if tracker_info is None:
            problems.append(f"{tracker}: not configured in this config")
            continue
        if not tracker_info.upload_enabled:
            problems.append(f"{tracker}: uploads are disabled in this config")
        template = tracker_info.nfo_template
        if template and template not in available_templates:
            problems.append(f"{tracker}: NFO template '{template}' no longer exists")
    return problems


class MainWindowWizard(QWizard):
    def __init__(
        self,
        config: ConfigManager,
        parent: "MainWindow",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MainWizard")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoCancelButton)

        self.config = config
        self.main_window = parent
        self.context = create_processing_context(
            self.config.settings,
            self.config.plugin_manager,
        )

        self._PAGES = self._generate_new_pages()
        self._START_PAGES = (
            WizardPages.INPUT_PAGE,
            WizardPages.PLUGIN_INPUT_PAGE,
        )

        self._insert_plugin_page()
        self._build_wizard_pages()
        self._set_start_page()

        self.next_button = QPushButton("Next", self)
        self.next_button.setToolTip("Save & Continue")
        self.next_button.setToolTipDuration(1500)
        self.setButton(QWizard.WizardButton.CommitButton, self.next_button)

        self.settings_button = QPushButton("Settings", self)
        self.settings_button.clicked.connect(GSigs().settings_clicked.emit)
        self.setButton(QWizard.WizardButton.CustomButton1, self.settings_button)

        self.reset_button = QPushButton("Start Over", self)
        self.reset_button.clicked.connect(self.reset_wizard)
        self.setButton(QWizard.WizardButton.CustomButton2, self.reset_button)
        self.setOption(QWizard.WizardOption.HaveCustomButton2)

        self.process_button = QPushButton("Process (Dupe Check)", self)
        self.process_button.clicked.connect(GSigs().wizard_process_btn_clicked.emit)
        GSigs().wizard_process_btn_change_txt.connect(self._change_process_button_text)
        GSigs().wizard_process_btn_set_hidden.connect(self.process_button.hide)
        self.setButton(QWizard.WizardButton.CustomButton3, self.process_button)
        self.setOption(QWizard.WizardOption.HaveCustomButton3)

        # all three CustomButton slots are already spoken for, so the unused
        # HelpButton slot carries "Jobs" -- the same re-purposing this
        # wizard already does by putting "Next" on the CommitButton
        self.load_job_button = QPushButton("Jobs", self)
        self.load_job_button.setToolTip(
            "Browse saved jobs: load one to process it, or queue several"
        )
        self.load_job_button.clicked.connect(self.open_load_job_dialog)
        self.setButton(QWizard.WizardButton.HelpButton, self.load_job_button)
        self.setOption(QWizard.WizardOption.HaveHelpButton)

        self.starting_buttons = (
            QWizard.WizardButton.CustomButton1,
            QWizard.WizardButton.HelpButton,
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.CommitButton,
        )

        self.mid_flow_buttons = (
            QWizard.WizardButton.CustomButton2,
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.CommitButton,
        )

        self.ending_buttons = (
            QWizard.WizardButton.CustomButton2,
            QWizard.WizardButton.Stretch,
            QWizard.WizardButton.CustomButton3,
        )

        self.early_ending_buttons = (
            QWizard.WizardButton.CustomButton2,
            QWizard.WizardButton.Stretch,
        )

        self.setButtonLayout(self.starting_buttons)

        self._connect_current_id_changed()
        GSigs().wizard_set_disabled.connect(self._set_disabled)
        GSigs().wizard_next.connect(self.next)
        GSigs().wizard_next_button_change_txt.connect(self._change_next_button_text)
        GSigs().wizard_next_button_reset_txt.connect(self._reset_next_button_text)
        GSigs().wizard_end_early.connect(self.end_early)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # prevent enter/return key from pressing "Next" on the wizard
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape):
            pass
        else:
            # call the base class implementation for other key events
            super().keyPressEvent(event)

    def nextId(self) -> int:
        """Control the flow between pages based on conditions"""
        current_page = WizardPages(self.currentId())
        return self._flow_production(current_page)

    @Slot(str)
    def _change_next_button_text(self, text: str) -> None:
        self.next_button.setText(text)

    @Slot()
    def _reset_next_button_text(self) -> None:
        self.next_button.setText("Next")

    @Slot(str)
    def _change_process_button_text(self, text: str) -> None:
        self.process_button.setText(text)

    @Slot()
    def reset_wizard(self) -> None:
        # A job load caches each file's MediaInfo text dump globally so the
        # media never has to be re-read. Starting over means a genuinely new
        # run, which must measure the file itself rather than inherit a dump
        # that may now describe a different encode.
        clear_restored_mediainfo()

        self.context = create_processing_context(
            self.config.settings,
            self.config.plugin_manager,
        )
        self.currentIdChanged.disconnect()
        self._remove_all_pages()
        self._PAGES = self._generate_new_pages()
        self._insert_plugin_page()
        self._build_wizard_pages()
        self._set_start_page()
        self._connect_current_id_changed()
        self._set_disabled(False)
        self.next_button.setText("Next")
        self.process_button.setText("Process (Dupe Check)")
        self.setButtonLayout(self.starting_buttons)
        self.restart()

    @Slot()
    def open_load_job_dialog(self) -> None:
        """Pick saved jobs and either resume one or run several as a queue."""
        dialog = LoadJobDialog(self.config.program.current_config, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        # Same leak `queue_dialog` is guarded against below, and parenting
        # gives this one longer to matter: it holds a listing tree, a details
        # pane and one retired-but-parented `_ListingLoader` per
        # `_load_listings()` call. `done()` already blocks `exec()` from
        # returning until any in-flight loader has stopped, so there is
        # nothing left running for `deleteLater()` to tear down. Scheduled
        # once here, right after `exec()`, so it covers every return below
        # regardless of which one is taken.
        dialog.deleteLater()
        if not accepted:
            return

        if dialog.queued_listings:
            # A bare temporary here would still leak: parenting to `self`
            # transfers ownership to C++, so a dialog built and immediately
            # `.exec()`'d without ever being assigned would survive the call
            # as a hidden child of the wizard for the rest of its life --
            # log widget, finished thread, `ProcessBackEnd` and all, one per
            # queue run. `reject()` already guarantees the thread has
            # finished by the time `exec()` returns, so `deleteLater()` here
            # is never asked to tear down anything still running.
            queue_dialog = JobQueueDialog(
                job_paths=[listing.path for listing in dialog.queued_listings],
                config=self.config,
                parent=self,
            )
            queue_dialog.start()
            queue_dialog.exec()
            queue_dialog.deleteLater()
            return

        listing = dialog.selected_listing
        if listing is None:
            return

        try:
            job = load_job(listing.path)
        except JobStoreError as e:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to load job: {e}")
            QMessageBox.critical(self, "Load Failed", f"Could not load job:\n\n{e}")
            return

        # The profile has to be switched *before* the context is built: the
        # Jinja engine, flat filters and plugin contributions are all derived
        # from the active settings at construction time, so building first
        # would wire the job up to the outgoing profile.
        if dialog.switch_profile_requested and not self._switch_config_profile(
            job.config_profile
        ):
            return

        # build and validate the restored context before touching any live
        # wizard state, so a job that cannot be resumed leaves the current
        # session exactly as it was
        context = create_processing_context(
            self.config.settings,
            self.config.plugin_manager,
        )
        try:
            # a new run must not inherit MediaInfo cached for a previous job
            clear_restored_mediainfo()
            context_from_dict(
                job.context,
                context,
                lambda name: read_job_asset(listing.path, name),
            )
        except JobCodecError as e:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to restore job '{job.name}': {e}")
            QMessageBox.critical(
                self, "Load Failed", f"Job '{job.name}' could not be restored:\n\n{e}"
            )
            return

        if not self._restored_job_is_usable(
            job.name, context, allow_source_less=job.archived
        ):
            return

        self._attach_base_torrent(job, listing.path, context)
        if job.archived and context.shared_data.base_torrent is None:
            QMessageBox.critical(
                self,
                "Archive Unavailable",
                f"Job '{job.name}' cannot be extended because its saved base "
                "torrent is missing, corrupt, or no longer matches the archive.",
            )
            return
        context.loaded_job_path = listing.path
        context.loaded_job_id = job.job_id
        context.loaded_job_name = job.name
        context.loaded_job_archived = job.archived
        context.loaded_uploaded_trackers = self._tracker_names_to_members(
            job.uploaded_trackers
        )
        context.loaded_uncertain_trackers = self._tracker_names_to_members(
            job.uncertain_trackers
        )
        start_page = self._resume_start_page(
            context, adding_trackers=dialog.add_trackers_requested
        )
        self._resume_job(context, start_page)
        LOG.info(LOG.LOG_SOURCE.FE, f"Resumed job '{job.name}' at the {start_page}")

    @staticmethod
    def _resume_start_page(
        context: ProcessingContext, *, adding_trackers: bool
    ) -> WizardPages:
        """Where in the flow a restored job picks up.

        A job whose titles and NFOs are already frozen has nothing left to
        decide, so it goes straight to processing. Anything else -- an archive
        being extended, or a job saved before it was prepared -- still has to
        pick trackers and assign their NFO templates, and neither is stored in
        the job: both are read live from the profile, on wizard pages.

        `adding_trackers` is asked separately because an archive can carry
        prepared work for trackers left pending by an earlier run. That reads as
        prepared, but the whole point of the request is to choose trackers it
        does not have yet.
        """
        if adding_trackers or not context.shared_data.is_prepared():
            return WizardPages.TRACKERS_PAGE
        return WizardPages.PROCESS_PAGE

    @staticmethod
    def _tracker_names_to_members(names: list[str]) -> set[TrackerSelection]:
        restored: set[TrackerSelection] = set()
        for name in names:
            try:
                restored.add(TrackerSelection[name])
            except KeyError:
                continue
        return restored

    def _switch_config_profile(self, profile: str) -> bool:
        """Activate `profile`, reporting failure without changing anything.

        Mirrors the error handling in Settings -> General's own config swap: an
        incompatible profile must leave the previously active one in place
        rather than half-applying.
        """
        if not profile:
            return True
        previous = self.config.program.current_config
        try:
            self.config.load_profile(profile)
        except ConfigSchemaError as e:
            LOG.error(LOG.LOG_SOURCE.FE, f"Failed to switch to config '{profile}': {e}")
            QMessageBox.critical(
                self,
                "Incompatible Config",
                f"{e}\n\nStayed on the current config: {previous}",
            )
            return False
        LOG.info(LOG.LOG_SOURCE.FE, f"Switched config profile to '{profile}'")
        # an already-built Settings view would otherwise keep showing the
        # profile we just navigated away from
        GSigs().settings_refresh.emit()
        return True

    def _restored_job_is_usable(
        self,
        job_name: str,
        context: ProcessingContext,
        *,
        allow_source_less: bool = False,
    ) -> bool:
        """Check a restored job against the filesystem it has to run against.

        MediaInfo comes back from the job file itself, but the media and the
        screenshots still have to be on disk to upload. The working directory
        is user-wipeable from Settings, so missing screenshots are a real
        outcome rather than an edge case.
        """
        try:
            context.media_input.require_existing_media_paths(include_comparison=False)
        except (FileNotFoundError, RuntimeError) as e:
            if not allow_source_less:
                QMessageBox.critical(
                    self,
                    "Media Files Unavailable",
                    f"Job '{job_name}' cannot be loaded because its media is no "
                    f"longer where it was saved:\n\n{e}",
                )
                return False
        missing_images = [
            str(image)
            for image in (context.shared_data.loaded_images or ())
            if not image.is_file()
        ]
        if missing_images:
            preview = "\n".join(missing_images[:10])
            if len(missing_images) > 10:
                preview += f"\n...and {len(missing_images) - 10} more"
            if (
                QMessageBox.question(
                    self,
                    "Screenshots Missing",
                    f"{len(missing_images)} screenshot(s) saved with job "
                    f"'{job_name}' no longer exist:\n\n{preview}\n\n"
                    "Load it anyway? Trackers set to upload images will have "
                    "none to send.",
                )
                is not QMessageBox.StandardButton.Yes
            ):
                return False

        return self._confirm_profile_can_serve_job(job_name, context)

    def _attach_base_torrent(
        self, job: SavedJob, directory: Path, context: ProcessingContext
    ) -> None:
        """Offer the job's stored torrent for reuse, if the media is unchanged.

        Hashing is the most expensive part of a run, so a job that carries a
        finished torrent can skip it -- but only while the media's size and
        modified time still match what `MediaFingerprint` recorded. Cloning a
        torrent whose piece hashes no longer match would upload a torrent that
        simply does not work, so a changed (or missing) file silently falls
        back to hashing.
        """
        stored = base_torrent_path(directory)
        if stored is None:
            return

        details = job.context.get("base_torrent")
        input_path = context.media_input.input_path
        if not isinstance(details, dict) or input_path is None:
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"Not reusing the torrent saved with job '{job.name}': its "
                "saved fingerprint details or current input path are missing",
            )
            return

        if getattr(job, "archived", False):
            snapshot = details.get("snapshot")
            if not archived_base_is_valid(stored, snapshot):
                LOG.warning(
                    LOG.LOG_SOURCE.FE,
                    f"Not reusing archived torrent for '{job.name}': validation failed",
                )
                return
            if isinstance(snapshot, dict):
                content_size = snapshot.get("content_size")
                if isinstance(content_size, int):
                    context.media_input.content_size = content_size
                mode = snapshot.get("mode")
                if mode in {"singlefile", "multifile"}:
                    context.media_input.input_kind = (
                        "directory" if mode == "multifile" else "file"
                    )
            context.shared_data.base_torrent = stored
            return

        recorded = details.get("fingerprints")
        if isinstance(recorded, dict) and recorded:
            unchanged = fingerprints_match(recorded, input_path)
        else:
            # Jobs saved before the whole-release fingerprint recorded only the
            # first file. Honour that for a single-file release, where it is the
            # same thing; for a directory it proves nothing, so re-hash.
            legacy = MediaFingerprint.from_dict(details.get("fingerprint"))
            media = context.media_input.get_first_file()
            unchanged = (
                not input_path.is_dir()
                and legacy is not None
                and media is not None
                and legacy.matches(media)
            )

        if not unchanged:
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"Not reusing the torrent saved with job '{job.name}': its media "
                "has changed since the job was saved",
            )
            return

        context.shared_data.base_torrent = stored

    @staticmethod
    def _stale_template_warnings(
        context: ProcessingContext, template_selector: TemplateSelectorBackEnd
    ) -> list[str]:
        """Name any template that has changed since this job froze its NFOs.

        A prepared job deliberately uploads the NFO it prepared, so an edited
        template does not change what goes out. That is the intended behavior --
        this exists only so the difference is visible rather than silent.
        """
        warnings: list[str] = []
        for name, digest in context.shared_data.template_fingerprints.items():
            current = template_selector.read_template(name=name)
            if current is None:
                continue
            if template_fingerprint(current) != digest:
                warnings.append(
                    f"template '{name}' changed since this job was prepared; "
                    "its saved NFO will be uploaded, not the new template"
                )
        return warnings

    def _confirm_profile_can_serve_job(
        self, job_name: str, context: ProcessingContext
    ) -> bool:
        """Warn about trackers the *active* profile can no longer upload to.

        A job stores no settings of its own -- credentials, templates and
        per-tracker toggles are all read live at resume time -- so anything the
        active profile has since turned off or renamed would otherwise only
        surface as a failure partway through the upload.
        """
        template_selector = TemplateSelectorBackEnd()
        problems = tracker_profile_problems(
            context.shared_data.tracker_image_hosts,
            self.config.settings.trackers.by_selection(),
            template_selector,
        )
        problems.extend(self._stale_template_warnings(context, template_selector))

        if not problems:
            return True

        return (
            QMessageBox.question(
                self,
                "Config Mismatch",
                f"Job '{job_name}' has trackers this config cannot fully "
                "serve:\n\n"
                + "\n".join(problems)
                + "\n\nNote that NFO templates are shared across all configs, so "
                "an edited template changes what this job uploads.\n\nLoad it "
                "anyway?",
            )
            is QMessageBox.StandardButton.Yes
        )

    def _resume_job(
        self,
        context: ProcessingContext,
        start_page: WizardPages = WizardPages.PROCESS_PAGE,
    ) -> None:
        """Rebuild the wizard around a restored context, at `start_page`.

        Mirrors `reset_wizard`, except that it starts partway through: the pages
        before `start_page` were already answered when the job was saved, and
        `setStartId` + `restart()` (QWizard has no `setCurrentId`) also leaves a
        clean history so Back cannot walk into pages this run never visited.

        The process page is the usual entry, but a run that still has to
        generate NFOs starts at the trackers page instead -- tracker choice and
        NFO template assignment are read live from the profile rather than
        stored in the job, so they cannot be inherited the way the rest of the
        context is.
        """
        self.context = context
        self.currentIdChanged.disconnect()
        self._remove_all_pages()
        self._PAGES = self._generate_new_pages()
        self._insert_plugin_page()
        self._build_wizard_pages()
        self._connect_current_id_changed()
        self._set_disabled(False)
        self.next_button.setText("Next")
        self.process_button.setText("Process (Dupe Check)")
        self.process_button.show()
        self.setStartId(start_page.value)
        # `restart()` fires `currentIdChanged`, so `_handle_page_change` sets
        # this too; doing it here as well keeps the button bar correct even
        # for a start page that is somehow already current.
        self.setButtonLayout(
            self.ending_buttons
            if start_page is WizardPages.PROCESS_PAGE
            else self.mid_flow_buttons
        )
        self.restart()
        GSigs().main_window_update_status_bar_label.emit(
            str(start_page).removesuffix(" Page")
        )

    def _build_wizard_pages(self) -> None:
        for idx, page in enumerate(self._PAGES):
            self.setPage(idx + 1, page)

    def _set_start_page(self) -> None:
        """Point a fresh run at the page it begins on.

        Always sets one, which is the whole point. `setStartId` is sticky and
        `_resume_job` moves it to wherever a resumed job picks up, so leaving
        it alone here does not mean "the default" -- it means "wherever the
        last resumed job started". Plugins being enabled with no usable wizard
        page took that path, and Start Over then opened a brand new run
        partway through the wizard, on a context with nothing in it.
        """
        if (
            self.config.settings.general.enable_plugins
            and self.config.settings.plugins.wizard_page
            and self.config.plugin_manager.get(self.config.settings.plugins.wizard_page)
        ):
            self.setStartId(WizardPages.PLUGIN_INPUT_PAGE.value)
            GSigs().main_window_update_status_bar_label.emit(
                self.config.settings.plugins.wizard_page
            )
            return

        self.setStartId(WizardPages.INPUT_PAGE.value)
        GSigs().main_window_update_status_bar_label.emit("Input")

    @Slot(int)
    def _handle_page_change(self, idx: int) -> None:
        if idx > -1 and WizardPages(idx) in self._START_PAGES:
            self.setButtonLayout(self.starting_buttons)
        else:
            if idx != WizardPages.PROCESS_PAGE.value:
                self.setButtonLayout(self.mid_flow_buttons)
            else:
                self.setButtonLayout(self.ending_buttons)

    @Slot(bool)
    def _set_disabled(self, value: bool) -> None:
        self.settings_button.setDisabled(value)
        self.next_button.setDisabled(value)
        self.reset_button.setDisabled(value)
        self.process_button.setDisabled(value)
        self.load_job_button.setDisabled(value)

    def end_early(self) -> None:
        self.setButtonLayout(self.early_ending_buttons)

    def _insert_plugin_page(self) -> None:
        if (
            self.config.settings.general.enable_plugins
            and self.config.settings.plugins.wizard_page
            and self.config.plugin_manager.get(self.config.settings.plugins.wizard_page)
        ):
            try:
                record = self.config.plugin_manager.get(
                    self.config.settings.plugins.wizard_page
                )
                if record and record.definition.wizard_page:
                    # insert the plugin wizard page into the correct spot
                    plugin_wizard = record.definition.wizard_page(
                        self.config, self.context, self.main_window
                    )
                    self._PAGES.pop(WizardPages.PLUGIN_INPUT_PAGE.value - 1)
                    self._PAGES.insert(
                        WizardPages.PLUGIN_INPUT_PAGE.value - 1, plugin_wizard
                    )
            except Exception as e:
                LOG.critical(LOG.LOG_SOURCE.FE, traceback.format_exc())
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to load plugin page:\n{e}\n\nPlugins are disabled until plugin issues are resolved.",
                )
                # revert to default media input page on failure
                self._PAGES.pop(WizardPages.PLUGIN_INPUT_PAGE.value - 1)
                self._PAGES.insert(
                    WizardPages.PLUGIN_INPUT_PAGE.value - 1,
                    MediaInput(self.config, self.context, self.main_window),
                )
                # disable plugins for the rest of the wizard flow
                self.config.settings.general.enable_plugins = False
                self.config.save()

    def _remove_all_pages(self) -> None:
        for page_id in reversed(self.pageIds()):
            page = self.page(page_id)
            self.removePage(page_id)
            # removePage() only detaches the page from the wizard -- it does
            # not delete the widget, so its GSigs connections (e.g. MediaSearch's
            # settings_close) stay alive. Schedule the old instance for
            # deletion so "Start Over" doesn't keep accumulating live, still
            # connected page objects each time fresh pages are built.
            #
            # `deleteLater()` alone is not enough for a connection whose
            # correctness depends on *when* it goes: it schedules the delete
            # and nothing here waits for it. A page with something it must
            # hand back now says so in `teardown()`.
            if page is not None:
                teardown = getattr(page, "teardown", None)
                if callable(teardown):
                    teardown()
                page.deleteLater()

    def _connect_current_id_changed(self) -> None:
        self.currentIdChanged.connect(self._handle_page_change)

    def _flow_production(self, current_page: WizardPages) -> int:
        if current_page in self._START_PAGES:
            return WizardPages.MEDIA_SEARCH_PAGE.value

        elif current_page == WizardPages.MEDIA_SEARCH_PAGE:
            # if series navigate to the series matcher page
            if self.context.media_search.media_type is MediaType.SERIES:
                return WizardPages.SERIES_MATCHER_PAGE.value
            # movie
            else:
                if self.config.settings.movie.enabled:
                    return WizardPages.RENAME_ENCODE_MOVIES_PAGE.value
                elif (
                    not self.config.settings.movie.enabled
                    and self.config.settings.screenshots.enabled
                ):
                    return WizardPages.IMAGES_PAGE.value
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.SERIES_MATCHER_PAGE:
            if self.config.settings.series.enabled:
                return WizardPages.RENAME_ENCODE_SERIES_PAGE.value
            elif self.config.settings.screenshots.enabled:
                return WizardPages.IMAGES_PAGE.value
            return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.RENAME_ENCODE_MOVIES_PAGE:
            if self.config.settings.screenshots.enabled:
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.RENAME_ENCODE_SERIES_PAGE:
            if self.config.settings.screenshots.enabled:
                return WizardPages.IMAGES_PAGE.value
            else:
                return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.IMAGES_PAGE:
            return WizardPages.TRACKERS_PAGE.value

        elif current_page == WizardPages.TRACKERS_PAGE:
            return WizardPages.PRE_UPLOAD_PAGE.value

        elif current_page == WizardPages.PRE_UPLOAD_PAGE:
            return WizardPages.PROCESS_PAGE.value

        elif current_page == WizardPages.PROCESS_PAGE:
            return -1

        return -1

    def _generate_new_pages(self) -> list[BaseWizardPage]:
        """Helper method to generate wizard page instances and return them."""
        pages = (
            MediaInput,
            DummyWizardPage,
            MediaSearch,
            SeriesMatch,
            RenameEncode,
            RenameEncodeSeries,
            ImagesPage,
            TrackersPage,
            PreUploadPage,
            ProcessPage,
        )
        return [p(self.config, self.context, self.main_window) for p in pages]
