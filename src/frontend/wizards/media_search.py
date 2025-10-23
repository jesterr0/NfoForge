import asyncio
import traceback
import webbrowser
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib import parse as url_parse

from guessit import guessit
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCursor, QPixmap
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
)

from src.backend.media_search import MediaSearchBackEnd
from src.backend.utils.filter_title import edition_and_title_extractor as extract_title
from src.backend.utils.super_sub import normalize_super_sub
from src.backend.utils.working_dir import RUNTIME_DIR
from src.config.config import Config
from src.enums.media_type import MediaType
from src.enums.tmdb_genres import TMDBGenreIDsMovies
from src.exceptions import MediaFileNotFoundError, MediaParsingError, MediaSearchError
from src.frontend.global_signals import GSigs
from src.frontend.utils import QWidgetTempStyle
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.logger.nfo_forge_logger import LOG

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class QueuedWorker(QThread):
    job_finished = Signal(OrderedDict)
    job_failed = Signal(str)

    def __init__(self, backend, query, parent=None) -> None:
        super().__init__(parent=parent)
        self.backend = backend
        self.query = query

    def run(self) -> None:
        try:
            result = self.backend._parse_tmdb_api(self.query)
            self.job_finished.emit(OrderedDict(result))
        except Exception as e:
            self.job_failed.emit(f"Failed to parse TMDB: {e}\n{traceback.format_exc()}")


class IDParseWorker(QThread):
    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(
        self,
        backend: MediaSearchBackEnd,
        media_type: MediaType,
        imdb_id: str,
        tmdb_title: str,
        tmdb_year: int,
        original_language: str,
        tmdb_genres: list[TMDBGenreIDsMovies],
        tmdb_id: str = "",
        parent=None,
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
                )
            )
            self.job_finished.emit(parse_other_ids)
        except Exception as e:
            self.job_failed.emit(
                f"Failed to parse ID data: ({e})\n{traceback.format_exc()}"
            )
        finally:
            async_loop.close()


class MediaSearch(BaseWizardPage):
    def __init__(
        self,
        config: Config,
        parent: "MainWindow | Any",
        on_finished_cb: Callable | None = None,
    ) -> None:
        super().__init__(config, parent)
        self.setTitle("Search")
        self.setObjectName("mediaSearch")
        self.setCommitPage(True)

        self.main_window = parent
        self._on_finished_cb = on_finished_cb

        self.config = config
        self.backend = MediaSearchBackEnd(
            api_key=self.config.cfg_payload.tmdb_api_key,
            language=self.config.cfg_payload.tmdb_language,
        )

        # listen for settings changes to update language
        GSigs().settings_close.connect(self._update_backend_settings)

        self.queued_worker: QueuedWorker | None = None
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

        imdb_label = QLabel()
        imdb_label.setPixmap(imdb_image)
        imdb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        imdb_label.mousePressEvent = self._open_imdb_link
        self.imdb_id_entry = QLineEdit()
        self.imdb_id_entry.setPlaceholderText("Automatic")

        tmdb_image = QPixmap(str(Path(RUNTIME_DIR / "images" / "tmdb.png").resolve()))
        tmdb_image = tmdb_image.scaled(
            28,
            28,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        tmdb_label = QLabel()
        tmdb_label.setPixmap(tmdb_image)
        tmdb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        tmdb_label.mousePressEvent = self._open_tmdb_link
        self.tmdb_id_entry = QLineEdit()

        tvdb_image = QPixmap(str(Path(RUNTIME_DIR / "images" / "tvdb.png").resolve()))
        tvdb_image = tvdb_image.scaled(
            28,
            30,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        tvdb_label = QLabel()
        tvdb_label.setPixmap(tvdb_image)
        tvdb_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        tvdb_label.mousePressEvent = self._open_tvdb_link
        self.tvdb_id_entry = QLineEdit()
        self.tvdb_id_entry.setPlaceholderText("Automatic")

        mal_image = QPixmap(str(Path(RUNTIME_DIR / "images" / "mal.png").resolve()))
        mal_image = mal_image.scaled(
            28,
            30,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        mal_label = QLabel()
        mal_label.setPixmap(mal_image)
        mal_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        mal_label.mousePressEvent = self._open_mal_link
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
        invalid_entries = self._check_invalid_entries((self.tmdb_id_entry,))
        if invalid_entries:
            return False
        else:
            if not self.other_ids_parsed:
                self.listbox.setDisabled(True)
                self._search_other_ids()
                return False
            elif (
                self.config.media_search_payload.media_type is MediaType.SERIES
                and self.other_ids_parsed
            ):
                if self._check_invalid_entries((self.tvdb_id_entry,)):
                    GSigs().wizard_next_button_reset_txt.emit()
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
            else:
                # add id manually to payload if the user provides it
                if entry is self.tvdb_id_entry:
                    tvdb_id_entry_text = self.tvdb_id_entry.text().strip()
                    if (
                        tvdb_id_entry_text
                        and tvdb_id_entry_text != self.tvdb_id_entry.placeholderText()
                    ):
                        self.config.media_search_payload.tvdb_id = tvdb_id_entry_text
        return invalid_entries

    def _search_other_ids(self) -> None:
        GSigs().main_window_set_disabled.emit(True)
        current_item = self.listbox.currentItem().text()
        item_data = self.backend.media_data.get(current_item)
        if item_data:
            self.id_parse_worker = IDParseWorker(
                backend=self.backend,
                media_type=MediaType.search_type(item_data.get("media_type"))
                or MediaType.MOVIE,
                imdb_id=self.imdb_id_entry.text().strip(),
                tmdb_title=item_data.get("title"),
                tmdb_year=int(item_data.get("year")),
                original_language=item_data.get("raw_data", {}).get(
                    "original_language"
                ),
                tmdb_genres=item_data.get("genre_ids", []),
                tmdb_id=item_data.get("tmdb_id"),
                parent=self,
            )
            self.id_parse_worker.job_finished.connect(self._detected_id_data)
            self.id_parse_worker.job_failed.connect(self._failed_search)
            GSigs().main_window_update_status_tip.emit(
                "Parsing metadata, please wait...", 0
            )
            self.id_parse_worker.start()

    @Slot(object)
    def _detected_id_data(self, media_data: dict | None) -> None:
        try:
            self._update_payload_data(media_data)
            self.other_ids_parsed = True
            # if finished has a cb, utilize that instead of emit (for sandbox)
            if self._on_finished_cb:
                self._on_finished_cb()
            else:
                GSigs().wizard_next.emit()
        except Exception:
            raise
        finally:
            GSigs().main_window_set_disabled.emit(False)
            GSigs().main_window_clear_status_tip.emit()

    def _update_payload_data(self, media_data: dict | None = None) -> None:
        current_item = self.listbox.currentItem().text()
        item_data = self.backend.media_data.get(current_item)
        if not item_data:
            raise MediaSearchError("Failed to parse TMDB")

        # update both payloads with the correct MediaType
        self.config.media_input_payload.media_type = (
            self.config.media_search_payload.media_type
        ) = MediaType.strict_search_type(item_data.get("media_type"))
        self.config.media_search_payload.imdb_id = self.imdb_id_entry.text()
        self.config.media_search_payload.tmdb_id = self.tmdb_id_entry.text()
        self.config.media_search_payload.tmdb_data = item_data.get("raw_data")

        # title selection handled by backend with smart regional preferences
        self.config.media_search_payload.title = item_data.get("title")
        self.config.media_search_payload.year = item_data.get("year")
        original_title = item_data.get("original_title")
        self.config.media_search_payload.original_title = (
            normalize_super_sub(original_title) if original_title else None
        )

        # set genres from TMDB data
        genres = None
        if isinstance(item_data.get("genre_ids"), list):
            genres = item_data.get("genre_ids")
        self.config.media_search_payload.genres = genres if genres else []

        if media_data:
            # handle complete TMDB data first
            tmdb_complete_data = media_data.get("tmdb_complete_data")
            if tmdb_complete_data and tmdb_complete_data.get("success") is True:
                complete_tmdb_result = tmdb_complete_data.get("result")
                # use complete TMDB data as the primary tmdb_data
                self.config.media_search_payload.tmdb_data = complete_tmdb_result

                # extract and update IMDb ID from complete data if not already set
                if (
                    complete_tmdb_result
                    and not self.config.media_search_payload.imdb_id
                ):
                    external_ids = complete_tmdb_result.get("external_ids", {})
                    extracted_imdb_id = external_ids.get("imdb_id", "")
                    if extracted_imdb_id:
                        self.config.media_search_payload.imdb_id = extracted_imdb_id
                        self.imdb_id_entry.setText(extracted_imdb_id)

            imdb_data = media_data.get("imdb_data")
            tvdb_data = media_data.get("tvdb_data")
            ani_list_data = media_data.get("ani_list_data")

            # imdb data
            if imdb_data and imdb_data.get("success") is True:
                imdb_data_result = imdb_data.get("result")
                self.config.media_search_payload.imdb_data = imdb_data_result

            # tvdb data
            if tvdb_data and tvdb_data.get("success") is True:
                tvdb_data_result = tvdb_data.get("result")
                self.config.media_search_payload.tvdb_data = tvdb_data_result
                self.config.media_search_payload.tvdb_id = str(
                    tvdb_data_result.get("id")
                )
                if self.config.media_search_payload.tvdb_id:
                    self.tvdb_id_entry.setText(self.config.media_search_payload.tvdb_id)

            # anilist data
            if ani_list_data and ani_list_data.get("success") is True:
                ani_list_data_result = ani_list_data.get("result")
                if not ani_list_data_result:
                    mal_value = self._ask_user_for_id("MAL")
                    ani_list_data_result = {
                        "id": str(mal_value),
                        "idMal": str(mal_value),
                    }
                self.config.media_search_payload.anilist_data = ani_list_data_result
                self.config.media_search_payload.anilist_id = ani_list_data_result.get(
                    "id"
                )
                self.config.media_search_payload.mal_id = ani_list_data_result.get(
                    "idMal"
                )
                if self.config.media_search_payload.mal_id:
                    self.mal_id_entry.setText(
                        str(self.config.media_search_payload.mal_id)
                    )
        else:
            # title selection handled by backend, no additional processing needed
            LOG.info(
                LOG.LOG_SOURCE.FE,
                f"Using TMDB title selected by backend: '{self.config.media_search_payload.title}'",
            )

    def _ask_user_for_id(self, id_source: str) -> int:
        value = 0
        ask_user_id, ask_user_ok = QInputDialog.getInt(
            self,
            f"{id_source} ID",
            f"Could not detect {id_source} ID, please enter this now.\n(If no "
            "value is provided a default value of 0 will be added)",
        )
        if ask_user_ok and ask_user_id:
            value = ask_user_id
        return value

    @Slot()
    def _update_backend_settings(self) -> None:
        """Update MediaSearchBackEnd when settings change"""
        new_language = self.config.cfg_payload.tmdb_language
        self.backend.update_language(new_language)
        self.backend.update_api_key(self.config.cfg_payload.tmdb_api_key)

    def isComplete(self) -> bool:
        """Overrides isComplete method to control the next button"""
        return self.loading_complete

    def initializePage(self) -> None:
        if not self._check_media_api_keys():
            if self.main_window.wizard:
                QTimer.singleShot(1, self.main_window.wizard.reset_wizard)
            return

        input_path = self.config.media_input_payload.input_path
        if not input_path:
            raise MediaFileNotFoundError("Failed to load input path")
        
        self.search_label.setText(f"Input: {input_path.name}")
        self.search_label.setToolTip(input_path.name)
        self.search_entry.setText(self._get_title_only(input_path))

        self._search_tmdb_api()

        QTimer.singleShot(1, self._after_initialization)

    def _after_initialization(self) -> None:
        """Gives time for the UI to draw widgets"""
        GSigs().wizard_next_button_change_txt.emit("Select Title")

    def _get_title_only(self, file_path: Path) -> str:
        guess = guessit(file_path.stem)
        title = guess.get("title")
        year = guess.get("year")
        if title and year:
            return f"{title} {year}"
        else:
            extracted_title = extract_title(file_path.stem).title
            if not extracted_title:
                raise MediaParsingError(
                    f"Failed to determine title name for input {file_path.name}"
                )
            return extracted_title

    def _check_media_api_keys(self) -> bool:
        required_keys_map = {
            "TMDB (v3)": "tmdb_api_key",
        }

        for service, key_attr in required_keys_map.items():
            key = getattr(self.config.cfg_payload, key_attr, None)

            if not key or not key.strip():
                text, ok = QInputDialog.getText(
                    self,
                    f"{service} Api Key",
                    f"Requires {service} Api Key, please input this now",
                )
                if ok and text:
                    text = text.strip()
                    setattr(self.config.cfg_payload, key_attr, text)
                    self.config.save_config()
                    self.backend.update_api_key(text)
                else:
                    QMessageBox.critical(
                        self,
                        f"{service} Api Key",
                        f"You must input a {service} to continue",
                    )
                    return False
        return True

    def _get_current_item_data(self) -> dict[str, Any] | None:
        current_item = self.listbox.currentItem().text()
        item_data = self.backend.media_data.get(current_item)
        if item_data:
            return item_data

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
    def _search_tmdb_api(self) -> None:
        # disable the next button
        self.loading_complete = False
        self.completeChanged.emit()

        if self.search_entry.text().strip() != "":
            self.reset_page(all_widgets=False)
            self.listbox.addItem("Loading please wait...")
            if self.queued_worker is not None and self.queued_worker.isRunning():
                self.queued_worker.terminate()

            self.queued_worker = QueuedWorker(
                self.backend, self.search_entry.text(), parent=self
            )
            self.queued_worker.job_finished.connect(self._handle_search_result)
            self.queued_worker.job_failed.connect(self._failed_search)
            self.queued_worker.start()

    @Slot(OrderedDict)
    def _handle_search_result(self, result) -> None:
        self.listbox.clear()
        if result:
            self.listbox.addItems(result)
            self.listbox.setCurrentRow(0)
            self._select_media()
        else:
            self.listbox.addItem("No results, try again...")

        # enables the next button
        self.loading_complete = True
        self.completeChanged.emit()

    @Slot(str)
    def _failed_search(self, error_str: str) -> None:
        self.listbox.clear()
        self.listbox.addItem(f"No results, {error_str}")
        self.search_entry.clear()
        self.search_entry.setPlaceholderText("Manually input title")
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()

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
    def _open_imdb_link(self, _):
        self._open_external_link(
            self.imdb_id_entry,
            "https://imdb.com/title/{}/",
            "https://www.imdb.com/find/?q={}",
            "https://www.imdb.com/",
        )

    @Slot()
    def _open_tmdb_link(self, _):
        self._open_external_link(
            self.tmdb_id_entry,
            "https://www.themoviedb.org/movie/{}/",
            "https://www.themoviedb.org/search?query={}",
            "https://www.themoviedb.org/",
        )

    @Slot()
    def _open_tvdb_link(self, _):
        self._open_external_link(
            self.tvdb_id_entry,
            "https://thetvdb.com/search?query={}",
            "https://thetvdb.com/search?query={}",
            "https://thetvdb.com/",
        )

    @Slot()
    def _open_mal_link(self, _):
        self._open_external_link(
            self.mal_id_entry,
            "https://myanimelist.net/anime/{}",
            "https://myanimelist.net/search/all?q={}",
            "https://myanimelist.net/",
        )

    @Slot()
    def reset_page(self, all_widgets: bool = True) -> None:
        self.listbox.clear()
        self.listbox.setDisabled(False)
        self.imdb_id_entry.clear()
        self.imdb_id_entry.setPlaceholderText("Automatic")
        self.tmdb_id_entry.clear()
        self.tvdb_id_entry.clear()
        self.tvdb_id_entry.setPlaceholderText("Automatic")
        self.mal_id_entry.clear()
        self.mal_id_entry.setPlaceholderText("Automatic")
        self.release_date_label.clear()
        self.rating_label.clear()
        self.plot_text.clear()

        self.queued_worker = None
        self.loading_complete = False
        self.id_parse_worker = None
        self.other_ids_parsed = False

        self.backend.update_api_key(self.config.cfg_payload.tmdb_api_key)

        if all_widgets:
            self.search_entry.clear()
