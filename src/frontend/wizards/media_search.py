from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import traceback
from typing import Any, Protocol
from urllib import parse as url_parse
import webbrowser

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCursor, QMouseEvent, QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.media_search import MediaSearchBackEnd
from src.backend.utils.title_inference import MediaTitleInferer
from src.backend.utils.working_dir import RUNTIME_DIR
from src.config.config import ConfigManager
from src.context.processing_context import ProcessingContext
from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies, TMDBGenreIDsSeries
from src.exceptions import (
    MediaFileNotFoundError,
    MediaSearchError,
    MediaSearchUnavailableError,
)
from src.frontend.global_signals import GSigs
from src.frontend.utils import QWidgetTempStyle
from src.frontend.utils.general_worker import GeneralWorker
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.logger.nfo_forge_logger import LOG
from src.plugins.api import (
    MetadataInputContext,
    MetadataTransformContext,
    MetadataTransformRequest,
)
from src.utils.super_sub import normalize_super_sub


class _MediaSearchBackend(Protocol):
    def _parse_tmdb_api(self, media_str: str) -> dict[str, dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class MediaSearchJobResult:
    """Combined title-inference and TMDB search result."""

    query: str | None
    results: OrderedDict[str, Any]
    title_error: str | None = None


def _run_media_search_job(
    backend: _MediaSearchBackend,
    query: str | None,
    input_path: Path | None,
    selected_files: tuple[Path, ...],
) -> MediaSearchJobResult:
    """Infer an automatic query and perform the network search in one worker."""

    if query is None:
        if input_path is None:
            return MediaSearchJobResult(
                query=None,
                results=OrderedDict(),
                title_error="Failed to load the selected media path.",
            )

        try:
            inference = MediaTitleInferer().infer(
                input_path,
                video_files=selected_files,
            )
        except Exception as error:
            return MediaSearchJobResult(
                query=None,
                results=OrderedDict(),
                title_error=str(error) or "Unable to determine a media title.",
            )

        query = inference.title
        LOG.info(
            LOG.LOG_SOURCE.BE,
            f"Inferred media search title {query!r} "
            f"(confidence: {inference.confidence:.1%})",
        )

    return MediaSearchJobResult(
        query=query,
        results=OrderedDict(backend._parse_tmdb_api(query)),
    )


class IDParseWorker(QThread):
    job_finished = Signal(object)
    job_failed = Signal(object)

    def __init__(
        self,
        backend: MediaSearchBackEnd,
        media_type: MediaType,
        imdb_id: str,
        tmdb_title: str,
        tmdb_year: int,
        original_language: str,
        tmdb_genres: Sequence[TMDBGenreIDsMovies | TMDBGenreIDsSeries],
        tmdb_id: str = "",
        tvdb_id: str = "",
        metadata_transformer_id: str | None = None,
        config: ConfigManager | None = None,
        context: ProcessingContext | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.backend = backend
        self.media_type = media_type
        self.imdb_id = imdb_id
        self.tmdb_title = tmdb_title
        self.tmdb_year = tmdb_year
        self.original_language = original_language
        self.tmdb_genres = tmdb_genres
        self.tmdb_id = tmdb_id
        self.tvdb_id = tvdb_id
        self.metadata_transformer_id = metadata_transformer_id
        self.config = config
        self.context = context

    def run(self) -> None:
        async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(async_loop)
        try:
            parse_other_ids = async_loop.run_until_complete(
                self.backend.parse_other_ids(
                    self.media_type,
                    self.imdb_id,
                    self.tmdb_title,
                    self.tmdb_year,
                    self.original_language,
                    self.tmdb_genres,
                    self.tmdb_id,
                    self.tvdb_id,
                )
            )
            if (
                self.metadata_transformer_id
                and self.config is not None
                and self.context is not None
            ):
                payload = deepcopy(self.context.media_search)
                payload.apply_lookup_results(parse_other_ids)
                payload.populate_from_tmdb()
                try:
                    transformed = self.config.plugin_manager.transform_metadata(
                        self.metadata_transformer_id,
                        MetadataTransformRequest(
                            config=self.config,
                            context=MetadataTransformContext(
                                media_input=MetadataInputContext(
                                    input_path=self.context.media_input.input_path,
                                    media_type=self.context.media_input.media_type,
                                    working_dir=self.context.media_input.working_dir,
                                    files=tuple(self.context.media_input.file_list),
                                ),
                                media_search=payload,
                            ),
                            payload=payload,
                            timeout=self.backend.timeout,
                        ),
                    )
                    parse_other_ids["metadata_transformation"] = {
                        "success": True,
                        "result": transformed,
                    }
                except Exception as error:
                    parse_other_ids["metadata_transformation"] = {
                        "success": False,
                        "error": str(error),
                    }
            self.job_finished.emit(parse_other_ids)
        except Exception as e:
            LOG.error(
                LOG.LOG_SOURCE.BE,
                f"Media metadata lookup failed: {traceback.format_exc()}",
            )
            self.job_failed.emit(e)
        finally:
            async_loop.close()


class LinkLabel(QLabel):
    def __init__(
        self,
        on_click: Callable[[QMouseEvent], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_click = on_click

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._on_click(event)
        super().mousePressEvent(event)


class MediaSearch(BaseWizardPage):
    def __init__(
        self,
        config: ConfigManager,
        context: ProcessingContext,
        parent: QWidget,
        on_finished_cb: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(config, context, parent)
        self.setTitle("Search")
        self.setObjectName("mediaSearch")
        self.setCommitPage(True)

        self.main_window = parent
        self._on_finished_cb = on_finished_cb

        self.config = config
        self.backend = MediaSearchBackEnd(
            language=self.config.settings.general.tmdb_language,
            timeout=self.config.settings.general.timeout,
            api_key=self.config.settings.api_keys.tmdb_api_key,
        )

        # listen for settings changes to update the language and TMDB API key
        GSigs().settings_close.connect(self._update_backend_settings)

        self.search_worker: GeneralWorker | None = None
        self._search_generation = 0
        self.loading_complete = False
        self.id_parse_worker: IDParseWorker | None = None
        self.other_ids_parsed = False

        self.listbox = QListWidget()
        self.listbox.setFrameShape(QFrame.Shape.Box)
        self.listbox.setFrameShadow(QFrame.Shadow.Sunken)
        self.listbox.itemSelectionChanged.connect(self._select_media)

        self.plot_text = QPlainTextEdit()
        self.plot_text.setReadOnly(True)
        self.plot_text.setFrameShape(QFrame.Shape.NoFrame)
        plot_box = QGroupBox("Plot")
        self.plot_layout = QHBoxLayout(plot_box)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_layout.addWidget(self.plot_text)

        imdb_image = QPixmap(str(Path(RUNTIME_DIR / "images" / "imdb.png").resolve()))
        imdb_image = imdb_image.scaled(
            28,
            28,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        imdb_label = LinkLabel(self._open_imdb_link)
        imdb_label.setPixmap(imdb_image)
        imdb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.imdb_id_entry = QLineEdit()
        self.imdb_id_entry.setPlaceholderText("Automatic")
        self.imdb_id_entry.textEdited.connect(self._mark_metadata_dirty)

        tmdb_image = QPixmap(str(Path(RUNTIME_DIR / "images" / "tmdb.png").resolve()))
        tmdb_image = tmdb_image.scaled(
            28,
            28,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        tmdb_label = LinkLabel(self._open_tmdb_link)
        tmdb_label.setPixmap(tmdb_image)
        tmdb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tmdb_id_entry = QLineEdit()
        self.tmdb_id_entry.textEdited.connect(self._mark_metadata_dirty)

        tvdb_image = QPixmap(str(Path(RUNTIME_DIR / "images" / "tvdb.png").resolve()))
        tvdb_image = tvdb_image.scaled(
            28,
            30,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        tvdb_label = LinkLabel(self._open_tvdb_link)
        tvdb_label.setPixmap(tvdb_image)
        tvdb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.tvdb_id_entry = QLineEdit()
        self.tvdb_id_entry.setPlaceholderText("Automatic")
        self.tvdb_id_entry.textEdited.connect(self._mark_metadata_dirty)

        mal_image = QPixmap(str(Path(RUNTIME_DIR / "images" / "mal.png").resolve()))
        mal_image = mal_image.scaled(
            28,
            30,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        mal_label = LinkLabel(self._open_mal_link)
        mal_label.setPixmap(mal_image)
        mal_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.mal_id_entry = QLineEdit()
        self.mal_id_entry.setPlaceholderText("Automatic")

        id_row_1_layout = QHBoxLayout()
        id_row_1_layout.addWidget(imdb_label)
        id_row_1_layout.addWidget(self.imdb_id_entry)
        id_row_1_layout.addWidget(tmdb_label)
        id_row_1_layout.addWidget(self.tmdb_id_entry)

        id_row_2_layout = QHBoxLayout()
        id_row_2_layout.addWidget(tvdb_label)
        id_row_2_layout.addWidget(self.tvdb_id_entry)
        id_row_2_layout.addWidget(mal_label)
        id_row_2_layout.addWidget(self.mal_id_entry)

        tmdb_imdb_v_layout = QVBoxLayout()
        tmdb_imdb_v_layout.addLayout(id_row_1_layout)
        tmdb_imdb_v_layout.addLayout(id_row_2_layout)

        release_date_icon = QSvgWidget(
            str(Path(RUNTIME_DIR / "svg" / "date.svg").resolve())
        )
        release_date_icon.setFixedSize(20, 20)
        release_date_icon.setToolTip("Release date")
        self.release_date_label = QLabel()
        self.release_date_label.setMinimumWidth(80)
        rating_icon = QSvgWidget(
            str(Path(RUNTIME_DIR / "svg" / "rating.svg").resolve())
        )
        rating_icon.setFixedSize(20, 20)
        rating_icon.setToolTip("Average rating")
        self.rating_label = QLabel()
        self.rating_label.setMinimumWidth(80)

        media_type_icon = QSvgWidget(
            str(Path(RUNTIME_DIR / "svg" / "movie.svg").resolve())
        )
        media_type_icon.setFixedSize(20, 20)
        media_type_icon.setToolTip("Media Type")
        self.media_type_label = QLabel()
        self.media_type_label.setMinimumWidth(80)

        additional_info_layout = QFormLayout()
        additional_info_layout.addRow(release_date_icon, self.release_date_label)
        additional_info_layout.addRow(rating_icon, self.rating_label)
        additional_info_layout.addRow(media_type_icon, self.media_type_label)

        info_box = QGroupBox("Info")
        info_layout = QHBoxLayout(info_box)
        info_layout.addLayout(tmdb_imdb_v_layout)
        info_layout.addLayout(additional_info_layout)

        self.search_label = QLabel()
        self.search_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.MinimumExpanding
        )
        self.search_label.setCursor(QCursor(Qt.CursorShape.WhatsThisCursor))
        self.search_entry = QLineEdit()
        self.search_entry.returnPressed.connect(self._search_tmdb_api)
        self.search_button = QToolButton(self)
        QTAThemeSwap().register(
            self.search_button, "ph.file-search-light", icon_size=QSize(24, 24)
        )
        self.search_button.setFixedSize(24, 24)
        self.search_button.clicked.connect(self._search_tmdb_api)

        search_box = QGroupBox("Search")
        search_layout = QGridLayout(search_box)
        search_layout.addWidget(self.search_label, 0, 0, 1, 5)
        search_layout.addWidget(self.search_entry, 1, 0, 1, 4)
        search_layout.addWidget(self.search_button, 1, 4, 1, 1)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.listbox)
        self.main_layout.addWidget(info_box)
        self.main_layout.addWidget(plot_box)
        self.main_layout.addWidget(search_box)

    def validatePage(self) -> bool:
        if not self.loading_complete or not self._get_current_item_data():
            return False

        invalid_entries = self._check_invalid_entries((self.tmdb_id_entry,))
        if invalid_entries or self._has_invalid_id_formats():
            return False

        if not self.other_ids_parsed:
            self.listbox.setDisabled(True)
            self._search_other_ids()
            return False

        GSigs().wizard_next_button_reset_txt.emit()
        super().validatePage()
        return True

    def _check_invalid_entries(self, entires: tuple[QLineEdit, ...]) -> bool:
        invalid_entries = False
        for entry in entires:
            if entry.text().strip() == "" or entry.text() == entry.placeholderText():
                invalid_entries = True
                entry.setPlaceholderText("Requires ID")
                QWidgetTempStyle().set_temp_style(widget=entry).start()
        return invalid_entries

    def _has_invalid_id_formats(self) -> bool:
        invalid_entries: list[QLineEdit] = []
        imdb_id = self.imdb_id_entry.text().strip()
        tmdb_id = self.tmdb_id_entry.text().strip()
        tvdb_id = self.tvdb_id_entry.text().strip()

        if imdb_id and re.fullmatch(r"tt\d+", imdb_id, re.IGNORECASE) is None:
            invalid_entries.append(self.imdb_id_entry)
        if tmdb_id and not tmdb_id.isdecimal():
            invalid_entries.append(self.tmdb_id_entry)
        if tvdb_id and not tvdb_id.isdecimal():
            invalid_entries.append(self.tvdb_id_entry)

        for entry in invalid_entries:
            QWidgetTempStyle().set_temp_style(widget=entry).start()
        return bool(invalid_entries)

    @Slot(str)
    def _mark_metadata_dirty(self, _text: str) -> None:
        self.other_ids_parsed = False
        self.context.media_search.tvdb_data = None

    def _get_metadata_transformer_id(self) -> str | None:
        if not self.config.settings.general.enable_plugins:
            return None
        plugin_id = self.config.settings.plugins.metadata_transformer
        if not plugin_id:
            return None
        record = self.config.plugin_manager.get(plugin_id)
        if record is None or record.definition.metadata_transformer is None:
            return None
        return plugin_id

    def _search_other_ids(self) -> None:
        GSigs().main_window_set_disabled.emit(True)
        current_item_widget = self.listbox.currentItem()
        if current_item_widget is None:
            GSigs().main_window_set_disabled.emit(False)
            return
        current_item = current_item_widget.text()
        item_data = self.backend.media_data.get(current_item)
        if item_data:
            # Establish the canonical base payload before the worker receives an
            # isolated copy for optional plugin transformation.
            self._update_payload_data()
            media_type = item_data.get("media_type")
            title = item_data.get("title")
            year = item_data.get("year")
            raw_data = item_data.get("raw_data")
            genre_ids = item_data.get("genre_ids")
            self.id_parse_worker = IDParseWorker(
                backend=self.backend,
                media_type=MediaType.search_type(str(media_type)) or MediaType.MOVIE,
                imdb_id=self.imdb_id_entry.text().strip(),
                tmdb_title=str(title or ""),
                tmdb_year=int(year) if isinstance(year, int | str) else 0,
                original_language=(
                    str(raw_data.get("original_language") or "")
                    if isinstance(raw_data, dict)
                    else ""
                ),
                tmdb_genres=(
                    [
                        genre
                        for genre in genre_ids
                        if isinstance(genre, TMDBGenreIDsMovies | TMDBGenreIDsSeries)
                    ]
                    if isinstance(genre_ids, list)
                    else []
                ),
                tmdb_id=self.tmdb_id_entry.text().strip(),
                tvdb_id=self.tvdb_id_entry.text().strip(),
                metadata_transformer_id=self._get_metadata_transformer_id(),
                config=self.config,
                context=self.context,
                parent=self,
            )
            self.id_parse_worker.job_finished.connect(self._detected_id_data)
            self.id_parse_worker.job_failed.connect(self._handle_id_parse_failed)
            GSigs().main_window_update_status_tip.emit(
                "Parsing metadata, please wait...", 0
            )
            self.id_parse_worker.start()
            return

        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()

    @Slot(object)
    def _detected_id_data(self, media_data: dict[str, Any] | None) -> None:
        try:
            self._update_payload_data(media_data)
            if not self._handle_metadata_failures(media_data):
                self.other_ids_parsed = False
                self.listbox.setDisabled(False)
                return
            self.other_ids_parsed = True
            # if finished has a cb, utilize that instead of emit (for sandbox)
            if self._on_finished_cb:
                self._on_finished_cb()
            else:
                GSigs().wizard_next.emit()
        except MediaSearchError as error:
            self._handle_id_lookup_failed(str(error))
        except Exception as error:
            self._failed_search(str(error))
        finally:
            GSigs().main_window_set_disabled.emit(False)
            GSigs().main_window_clear_status_tip.emit()

    @Slot(object)
    def _handle_id_parse_failed(self, error: object) -> None:
        error_message = str(error) or "Media metadata lookup failed."
        if isinstance(error, MediaSearchUnavailableError):
            self._failed_search(error_message)
        elif isinstance(error, MediaSearchError):
            self._handle_id_lookup_failed(error_message)
        else:
            self._failed_search(error_message)

    def _handle_id_lookup_failed(self, error_message: str) -> None:
        """Keep the selected search result when a manually supplied ID fails."""

        self.other_ids_parsed = False
        self.listbox.setDisabled(False)
        self.completeChanged.emit()
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()
        QMessageBox.warning(
            self,
            "Metadata Lookup Failed",
            f"{error_message}\n\nCheck the ID and try again. Your current search selection was kept.",
        )

    def _handle_metadata_failures(self, media_data: dict[str, Any] | None) -> bool:
        if not media_data:
            return True

        transformer_error = self._result_error(
            media_data.get("metadata_transformation")
        )
        tvdb_error = self._result_error(media_data.get("tvdb_data"))

        if transformer_error:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                "Metadata transformer failed; using TMDb fallback: "
                f"{transformer_error}",
            )

        if self.context.media_search.media_type is MediaType.SERIES and tvdb_error:
            details = (
                f"TVDB metadata could not be loaded:\n{tvdb_error}\n\n"
                "Retry after checking or editing the IDs, or continue to map "
                "episodes manually."
            )
            if transformer_error:
                details += (
                    "\n\nThe external metadata transformer also failed; TMDb "
                    f"fallback data will be used:\n{transformer_error}"
                )
            return self._ask_to_continue_without_tvdb(details)

        if transformer_error:
            QMessageBox.warning(
                self,
                "Metadata Transformer Unavailable",
                f"{transformer_error}\n\nTMDb metadata will be used instead.",
            )
        return True

    @staticmethod
    def _result_error(result: object) -> str | None:
        if not isinstance(result, dict) or result.get("success") is not False:
            return None
        error = result.get("error")
        return str(error) if error else "Unknown metadata error"

    def _ask_to_continue_without_tvdb(self, details: str) -> bool:
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setWindowTitle("TVDB Metadata Unavailable")
        message_box.setText(details)
        retry_button = message_box.addButton("Retry", QMessageBox.ButtonRole.RejectRole)
        continue_button = message_box.addButton(
            "Continue Manually", QMessageBox.ButtonRole.AcceptRole
        )
        message_box.setDefaultButton(retry_button)
        message_box.exec()
        return message_box.clickedButton() is continue_button

    def _update_payload_data(self, media_data: dict[str, Any] | None = None) -> None:
        current_item = self.listbox.currentItem().text()
        item_data = self.backend.media_data.get(current_item)
        if not item_data:
            raise MediaSearchError("Failed to parse TMDB")

        prompted_anilist_data: dict[str, Any] | None = None

        # update both payloads with the correct MediaType
        self.context.media_input.media_type = self.context.media_search.media_type = (
            MediaType.strict_search_type(str(item_data.get("media_type") or ""))
        )
        self.context.media_search.imdb_id = self.imdb_id_entry.text().strip() or None
        self.context.media_search.tmdb_id = self.tmdb_id_entry.text().strip() or None
        self.context.media_search.tvdb_id = self.tvdb_id_entry.text().strip() or None
        self.context.media_search.tmdb_data = item_data.get("raw_data")
        self.context.media_search.tvdb_data = None

        # title selection handled by backend with smart regional preferences
        self.context.media_search.title = item_data.get("title")
        year_value = item_data.get("year")
        self.context.media_search.year = (
            int(year_value)
            if isinstance(year_value, int | str)
            and not isinstance(year_value, bool)
            and str(year_value).isdecimal()
            else None
        )
        original_title = item_data.get("original_title")
        self.context.media_search.original_title = (
            normalize_super_sub(original_title) if original_title else None
        )

        if media_data:
            # handle complete TMDB data first
            tmdb_complete_data = media_data.get("tmdb_complete_data")
            if tmdb_complete_data and tmdb_complete_data.get("success") is True:
                complete_tmdb_result = tmdb_complete_data.get("result")
                # use complete TMDB data as the primary tmdb_data
                self.context.media_search.tmdb_data = complete_tmdb_result

            resolved_ids = media_data.get("resolved_ids")
            if resolved_ids and resolved_ids.get("success") is True:
                resolved_result = resolved_ids.get("result")
                if isinstance(resolved_result, dict):
                    resolved_imdb_id = resolved_result.get("imdb_id")
                    resolved_tvdb_id = resolved_result.get("tvdb_id")
                    if resolved_imdb_id:
                        self.context.media_search.imdb_id = str(resolved_imdb_id)
                        self.imdb_id_entry.setText(str(resolved_imdb_id))
                    if resolved_tvdb_id:
                        self.context.media_search.tvdb_id = str(resolved_tvdb_id)
                        self.tvdb_id_entry.setText(str(resolved_tvdb_id))

            tvdb_data = media_data.get("tvdb_data")
            ani_list_data = media_data.get("ani_list_data")

            # tvdb data
            if tvdb_data and tvdb_data.get("success") is True:
                tvdb_data_result = tvdb_data.get("result")
                if isinstance(tvdb_data_result, dict):
                    self.context.media_search.tvdb_data = tvdb_data_result
                    tvdb_result_id = tvdb_data_result.get("id")
                    if tvdb_result_id:
                        self.context.media_search.tvdb_id = str(tvdb_result_id)
                        self.tvdb_id_entry.setText(str(tvdb_result_id))

            # anilist data
            if ani_list_data and ani_list_data.get("success") is True:
                ani_list_data_result = ani_list_data.get("result")
                if not ani_list_data_result:
                    mal_value = self._ask_user_for_id("MAL")
                    if mal_value is not None:
                        ani_list_data_result = {
                            "id": str(mal_value),
                            "idMal": str(mal_value),
                        }
                        prompted_anilist_data = ani_list_data_result
                if isinstance(ani_list_data_result, dict):
                    self._apply_anilist_data(ani_list_data_result)
                    if self.context.media_search.mal_id:
                        self.mal_id_entry.setText(self.context.media_search.mal_id)
        else:
            # title selection handled by backend, no additional processing needed
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"Using TMDB title selected by backend: '{self.context.media_search.title}'",
            )

        # `genres` must agree with `genre_names`, which `populate_from_tmdb`
        # (below) rewrites from `tmdb_data`. Computing it here -- after any
        # complete TMDB record fetched for a manually entered ID has already
        # replaced `tmdb_data` above -- keeps the two in sync. Reading the
        # listbox row directly left them disagreeing after a manual ID
        # entry, and downstream genre-aware logic reads `genres`.
        self.context.media_search.genres = self._genre_enums_from_tmdb(
            self.context.media_search.tmdb_data, item_data
        )

        self.context.media_search.populate_from_tmdb()
        if media_data:
            transformed_result = media_data.get("metadata_transformation")
            if (
                isinstance(transformed_result, dict)
                and transformed_result.get("success") is True
            ):
                transformed_payload = transformed_result.get("result")
                if isinstance(transformed_payload, type(self.context.media_search)):
                    self.context.media_search.copy_from(transformed_payload)

                    # The transformer ran on a worker snapshot created before
                    # the GUI could prompt for a missing MAL ID. Explicit user
                    # input therefore takes precedence over that stale copy.
                    if prompted_anilist_data is not None:
                        self._apply_anilist_data(prompted_anilist_data)

                    transformed = self.context.media_search
                    if transformed.media_type is not None:
                        self.context.media_input.media_type = transformed.media_type
                    self.imdb_id_entry.setText(transformed.imdb_id or "")
                    self.tmdb_id_entry.setText(transformed.tmdb_id or "")
                    self.tvdb_id_entry.setText(transformed.tvdb_id or "")
                    self.mal_id_entry.setText(transformed.mal_id or "")

    def _genre_enums_from_tmdb(
        self,
        tmdb_data: dict[str, Any] | None,
        item_data: dict[str, Any] | None,
    ) -> list[TMDBGenreIDsMovies | TMDBGenreIDsSeries]:
        """Genre enums from the fetched record, falling back to the search row.

        A complete TMDB record carries `genres` as objects with an `id`; a
        search result carries `genre_ids` as already-resolved genre enums.
        Prefer the former since it reflects a manually entered TMDB ID, and
        only fall back to the row when the record has no usable `genres` key
        at all. TMDB legitimately returns `genres: []` for some titles, and
        that empty-but-present list must be accepted as-is rather than
        treated as "missing" and backfilled from an unrelated search row.
        """
        enum_class: type[TMDBGenreIDsMovies] | type[TMDBGenreIDsSeries] = (
            TMDBGenreIDsSeries
            if self.context.media_search.media_type is MediaType.SERIES
            else TMDBGenreIDsMovies
        )

        if tmdb_data:
            raw_genres = tmdb_data.get("genres")
            if isinstance(raw_genres, list):
                resolved: list[TMDBGenreIDsMovies | TMDBGenreIDsSeries] = []
                for entry in raw_genres:
                    if not isinstance(entry, dict) or "id" not in entry:
                        continue
                    try:
                        resolved.append(enum_class(entry["id"]))
                    except ValueError:
                        resolved.append(enum_class.UNDEFINED)
                return resolved

        if item_data:
            genre_ids = item_data.get("genre_ids")
            if isinstance(genre_ids, list):
                return [genre for genre in genre_ids if isinstance(genre, enum_class)]

        return []

    def _apply_anilist_data(self, anilist_data: dict[str, Any]) -> None:
        self.context.media_search.anilist_data = anilist_data
        anilist_id = anilist_data.get("id")
        mal_id = anilist_data.get("idMal")
        self.context.media_search.anilist_id = (
            str(anilist_id) if anilist_id is not None else None
        )
        self.context.media_search.mal_id = str(mal_id) if mal_id is not None else None

    def _ask_user_for_id(self, id_source: str) -> int | None:
        ask_user_id, ask_user_ok = QInputDialog.getInt(
            self,
            f"{id_source} ID",
            f"Could not detect {id_source} ID, please enter this now.\n(If no "
            "value is provided, the lookup will be skipped)",
        )
        if ask_user_ok and ask_user_id:
            return ask_user_id
        return None

    @Slot()
    def _update_backend_settings(self) -> None:
        """Update MediaSearchBackEnd when settings change"""
        new_language = self.config.settings.general.tmdb_language
        self.backend.update_language(new_language)
        self.backend.update_api_key(self.config.settings.api_keys.tmdb_api_key)

    def isComplete(self) -> bool:
        """Overrides isComplete method to control the next button"""
        return self.loading_complete

    def initializePage(self) -> None:
        input_path = self.context.media_input.input_path
        if not input_path:
            raise MediaFileNotFoundError("Failed to load input path")

        self.search_label.setText(f"Input: {input_path.name}")
        self.search_label.setToolTip(input_path.name)
        self._search_tmdb_api(infer_title=True)

        QTimer.singleShot(1, self._after_initialization)

    def _after_initialization(self) -> None:
        """Gives time for the UI to draw widgets"""
        GSigs().wizard_next_button_change_txt.emit("Select Title")

    def _get_current_item_data(self) -> dict[str, Any] | None:
        current_item_widget = self.listbox.currentItem()
        if current_item_widget is None:
            return None
        current_item = current_item_widget.text()
        item_data = self.backend.media_data.get(current_item)
        if isinstance(item_data, dict):
            return dict(item_data)
        return None

    def _open_external_link(
        self, id_entry: QLineEdit, id_url: str, search_url: str, fallback_url: str
    ) -> None:
        entry_id = id_entry.text().strip()
        if entry_id:
            webbrowser.open(id_url.format(entry_id))
        else:
            item_data = self._get_current_item_data()
            if item_data and item_data.get("title"):
                webbrowser.open(search_url.format(url_parse.quote(item_data["title"])))
            else:
                webbrowser.open(fallback_url)

    @Slot()
    def _search_tmdb_api(self, infer_title: bool = False) -> None:
        """Search TMDB, inferring the initial title in the worker when asked."""

        if self.search_worker is not None and self.search_worker.isRunning():
            return

        query = None if infer_title else self.search_entry.text().strip()
        input_path = self.context.media_input.input_path if infer_title else None
        selected_files = (
            tuple(self.context.media_input.file_list) if infer_title else tuple()
        )

        self.reset_page(all_widgets=False)

        if not infer_title and not query:
            self.listbox.addItem("Enter a title to search...")
            return

        request_id = self._search_generation
        status = (
            "Inferring title and searching TMDB, please wait..."
            if infer_title
            else "Searching TMDB, please wait..."
        )
        self.listbox.addItem("Loading please wait...")
        GSigs().main_window_set_disabled.emit(True)
        GSigs().main_window_update_status_tip.emit(status, 0)

        worker = GeneralWorker(
            _run_media_search_job,
            self,
            self.backend,
            query,
            input_path,
            selected_files,
        )
        self.search_worker = worker
        worker.finished.connect(
            lambda worker=worker: self._release_search_worker(worker)
        )
        worker.job_finished.connect(
            lambda result, generation=request_id: self._handle_search_worker_finished(
                generation, result
            )
        )
        worker.job_failed.connect(
            lambda error, generation=request_id: self._handle_search_worker_failed(
                generation, error
            )
        )
        worker.start()

    def _release_search_worker(self, worker: GeneralWorker) -> None:
        if self.search_worker is worker:
            self.search_worker = None

    def _handle_search_worker_finished(self, generation: int, result: object) -> None:
        """Apply a result only if it belongs to the current search request."""

        if generation != self._search_generation:
            return

        if not isinstance(result, MediaSearchJobResult):
            self._failed_search("Media search returned an invalid result.")
            return

        if result.title_error:
            self._handle_title_inference_failed(result.title_error)
            return

        self._handle_search_result(result)

    def _handle_search_worker_failed(self, generation: int, error_str: str) -> None:
        """Handle network/search exceptions from the current worker."""

        if generation != self._search_generation:
            return

        self._failed_search(error_str)

    @Slot(object)
    def _handle_search_result(
        self,
        result: MediaSearchJobResult | OrderedDict[str, Any],
    ) -> None:
        if isinstance(result, MediaSearchJobResult):
            if result.query is not None:
                self.search_entry.setText(result.query)
            result_data = result.results
        else:
            result_data = result

        self.listbox.clear()
        if result_data:
            self.listbox.addItems(list(result_data))
            self.listbox.setCurrentRow(0)
            self._select_media()
        else:
            self.listbox.addItem("No results, try again...")

        self.loading_complete = bool(result_data)
        self.completeChanged.emit()
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()

    def _handle_title_inference_failed(self, error_str: str) -> None:
        """Leave the page usable so the user can enter a title manually."""

        self.loading_complete = False
        self.other_ids_parsed = False
        self.backend.media_data.clear()
        self.context.media_search.reset()
        self.context.media_input.media_type = None
        self.listbox.clear()
        self.listbox.addItem(
            "Title detection failed. Enter a title above and search manually."
        )
        self.listbox.setDisabled(False)
        self.completeChanged.emit()
        GSigs().wizard_next_button_reset_txt.emit()
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()
        QMessageBox.warning(
            self,
            "Title Detection Failed",
            f"{error_str}\n\nEnter a title manually to continue.",
        )

    @Slot(str)
    def _failed_search(self, error_str: str) -> None:
        self.loading_complete = False
        self.other_ids_parsed = False
        self.backend.media_data.clear()
        self.context.media_search.reset()
        self.context.media_input.media_type = None
        self.listbox.clear()
        self.listbox.addItem(f"Search unavailable: {error_str}")
        self.listbox.setDisabled(False)
        self.completeChanged.emit()
        GSigs().wizard_next_button_reset_txt.emit()
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()
        QMessageBox.warning(
            self,
            "Media Search Unavailable",
            f"{error_str}\n\nCheck your internet connection and try searching again.",
        )

    @Slot()
    def _select_media(self) -> None:
        current_item = self.listbox.currentItem()
        if not current_item:
            return

        item_key = current_item.text()
        item_data = self.backend.media_data.get(item_key)

        if item_data:
            self.imdb_id_entry.setText(item_data.get("imdb_id", ""))
            self.tmdb_id_entry.setText(item_data.get("tmdb_id", ""))
            self.plot_text.setPlainText(item_data.get("plot", ""))
            self.rating_label.setText(item_data.get("vote_average", ""))
            self.release_date_label.setText(item_data.get("full_release_date", ""))
            self.media_type_label.setText(item_data.get("media_type", ""))

    @Slot()
    def _open_imdb_link(self, _event: QMouseEvent) -> None:
        self._open_external_link(
            self.imdb_id_entry,
            "https://imdb.com/title/{}/",
            "https://www.imdb.com/find/?q={}",
            "https://www.imdb.com/",
        )

    @Slot()
    def _open_tmdb_link(self, _event: QMouseEvent) -> None:
        self._open_external_link(
            self.tmdb_id_entry,
            "https://www.themoviedb.org/movie/{}/",
            "https://www.themoviedb.org/search?query={}",
            "https://www.themoviedb.org/",
        )

    @Slot()
    def _open_tvdb_link(self, _event: QMouseEvent) -> None:
        self._open_external_link(
            self.tvdb_id_entry,
            "https://thetvdb.com/search?query={}",
            "https://thetvdb.com/search?query={}",
            "https://thetvdb.com/",
        )

    @Slot()
    def _open_mal_link(self, _event: QMouseEvent) -> None:
        self._open_external_link(
            self.mal_id_entry,
            "https://myanimelist.net/anime/{}",
            "https://myanimelist.net/search/all?q={}",
            "https://myanimelist.net/",
        )

    @Slot()
    def reset_page(self, all_widgets: bool = True) -> None:
        worker_was_running = (
            self.search_worker is not None and self.search_worker.isRunning()
        )
        self._search_generation += 1
        self.listbox.clear()
        self.listbox.setDisabled(False)
        self.imdb_id_entry.clear()
        self.imdb_id_entry.setPlaceholderText("Automatic")
        self.tmdb_id_entry.clear()
        self.tmdb_id_entry.setPlaceholderText("Automatic")
        self.tvdb_id_entry.clear()
        self.tvdb_id_entry.setPlaceholderText("Automatic")
        self.mal_id_entry.clear()
        self.mal_id_entry.setPlaceholderText("Automatic")
        self.release_date_label.clear()
        self.rating_label.clear()
        self.plot_text.clear()

        if self.search_worker is not None and not self.search_worker.isRunning():
            self.search_worker = None
        self.loading_complete = False
        self.id_parse_worker = None
        self.other_ids_parsed = False
        self.backend.media_data.clear()
        self.context.media_search.reset()
        self.context.media_input.media_type = None

        if all_widgets:
            self.search_entry.clear()

        if worker_was_running:
            GSigs().main_window_set_disabled.emit(False)
            GSigs().main_window_clear_status_tip.emit()
