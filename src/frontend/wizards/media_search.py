import asyncio
import traceback
import webbrowser
from collections import OrderedDict
from guessit import guessit
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal, Slot, QThread, QTimer
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QFrame,
    QListWidget,
    QGroupBox,
    QToolButton,
    QFormLayout,
    QSizePolicy,
    QInputDialog,
    QMessageBox,
)
from PySide6.QtGui import QCursor, QPixmap

from src.config.config import Config
from src.enums.tmdb_genres import TMDBGenreIDsMovies
from src.exceptions import MediaFileNotFoundError, MediaParsingError, MediaSearchError
from src.frontend.global_signals import GSigs
from src.frontend.utils import build_auto_theme_icon_buttons
from src.frontend.wizards.wizard_base_page import BaseWizardPage
from src.backend.media_search import MediaSearchBackEnd
from src.backend.utils.filter_title import edition_and_title_extractor as extract_title
from src.backend.utils.working_dir import RUNTIME_DIR

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
        except MediaParsingError as mpe:
            self.job_failed.emit(str(mpe))
        except Exception as e:
            self.job_failed.emit(f"Failed to parse TMDB: {e}\n{traceback.format_exc()}")


class IDParseWorker(QThread):
    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(
        self,
        backend: MediaSearchBackEnd,
        imdb_id: str,
        tmdb_title: str,
        tmdb_year: int,
        original_language: str,
        tmdb_genres: list[TMDBGenreIDsMovies],
        tvdb_api_key: str,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.backend = backend
        self.imdb_id = imdb_id
        self.tmdb_title = tmdb_title
        self.tmdb_year = tmdb_year
        self.original_language = original_language
        self.tmdb_genres = tmdb_genres
        self.tvdb_api_key = tvdb_api_key

    def run(self) -> None:
        async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(async_loop)
        try:
            parse_other_ids = async_loop.run_until_complete(
                self.backend.parse_other_ids(
                    self.imdb_id,
                    self.tmdb_title,
                    self.tmdb_year,
                    self.original_language,
                    self.tmdb_genres,
                    self.tvdb_api_key,
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
    def __init__(self, config: Config, parent: "MainWindow | Any"):
        super().__init__(config, parent)
        self.setTitle("Search")
        self.setObjectName("mediaSearch")
        self.setCommitPage(True)

        self.main_window = parent

        self.config = config
        self.backend = MediaSearchBackEnd(api_key=self.config.cfg_payload.tmdb_api_key)
        self.queued_worker: QueuedWorker | None = None
        self.current_source = None
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
        tvdb_label.mousePressEvent = self._open_mal_link
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
        self.search_button: QToolButton = build_auto_theme_icon_buttons(
            QToolButton, "search.svg", "searchButton", 24, 24
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
        invalid_entries = self._check_invalid_entries(
            (self.tmdb_id_entry, self.imdb_id_entry)
        )
        if invalid_entries:
            return False
        else:
            if not self.other_ids_parsed:
                self.listbox.setDisabled(True)
                self._search_other_ids()
                return False
            elif self.other_ids_parsed:
                if self._check_invalid_entries((self.tvdb_id_entry,)):
                    GSigs().wizard_next_button_reset_txt.emit()
                    return False

            GSigs().wizard_next_button_reset_txt.emit()
            return True

    def _check_invalid_entries(self, entires: tuple[QLineEdit, ...]) -> bool:
        invalid_entries = False
        for entry in entires:
            if entry.text().strip() == "" or entry.text() == entry.placeholderText():
                invalid_entries = True
                # TODO: Flash red or something once we theme it
                # entry.setStyleSheet("QLineEdit {border: 1px solid red; border-radius: 3px;}")
                entry.setPlaceholderText("Requires ID")
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
                imdb_id=self.imdb_id_entry.text().strip(),
                tmdb_title=item_data.get("title"),
                tmdb_year=int(item_data.get("year")),
                original_language=item_data.get("raw_data", {}).get(
                    "original_language"
                ),
                tmdb_genres=item_data.get("genre_ids", []),
                tvdb_api_key=self.config.cfg_payload.tvdb_api_key,
                parent=self,
            )
            self.id_parse_worker.job_finished.connect(self._detected_id_data)
            self.id_parse_worker.job_failed.connect(self._failed_search)
            GSigs().main_window_update_status_tip.emit(
                "Parsing IMDb/TVDb/Anilist data, please wait...", 0
            )
            self.id_parse_worker.start()

    @Slot(object)
    def _detected_id_data(self, media_data: dict | None) -> None:
        try:
            self._update_payload_data(media_data)
            self.other_ids_parsed = True
            GSigs().wizard_next.emit()
        except Exception:
            raise
        finally:
            GSigs().main_window_set_disabled.emit(False)
            GSigs().main_window_clear_status_tip.emit()

    def _update_payload_data(self, media_data: dict | None = None):
        current_item = self.listbox.currentItem().text()
        item_data = self.backend.media_data.get(current_item)
        if not item_data:
            raise MediaSearchError("Failed to parse TMDB")

        self.config.media_search_payload.imdb_id = self.imdb_id_entry.text()
        self.config.media_search_payload.tmdb_id = self.tmdb_id_entry.text()
        self.config.media_search_payload.tmdb_data = item_data.get("raw_data")

        if media_data:
            imdb_data = media_data.get("imdb_data")
            tvdb_data = media_data.get("tvdb_data")
            ani_list_data = media_data.get("ani_list_data")

            # imdb data
            if imdb_data and imdb_data.get("success") is True:
                imdb_data_result = imdb_data.get("result")
                self.config.media_search_payload.imdb_data = imdb_data_result
                self.config.media_search_payload.title = (
                    str(imdb_data_result.get("title"))
                    if imdb_data_result.get("title")
                    else None
                )
                try:
                    self.config.media_search_payload.year = int(
                        imdb_data_result.get("year")
                    )
                except ValueError:
                    pass
                self.config.media_search_payload.original_title = (
                    str(media_data.get("original title"))
                    if media_data.get("original title")
                    else None
                )
                genres = None
                if isinstance(item_data.get("genre_ids"), list):
                    genres = item_data.get("genre_ids")
                self.config.media_search_payload.genres = genres if genres else []

            # tvdb data
            if tvdb_data and tvdb_data.get("success") is True:
                tvdb_data_result = tvdb_data.get("result")
                tvdb_data_result_movie = tvdb_data_result.get("movie")
                if not tvdb_data_result_movie:
                    tvdb_value = self._ask_user_for_id("TVDB")
                    tvdb_data_result_movie = {"id": tvdb_value}
                self.config.media_search_payload.tvdb_data = tvdb_data_result
                self.config.media_search_payload.tvdb_id = str(
                    tvdb_data_result_movie.get("id")
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

    def isComplete(self):
        """Overrides isComplete method to control the next button"""
        return self.loading_complete

    def initializePage(self):
        if not self._check_media_api_keys():
            if self.main_window.wizard:
                QTimer.singleShot(1, self.main_window.wizard.reset_wizard)
            return

        path_obj = self.config.media_input_payload.source_file
        if not path_obj:
            path_obj = self.config.media_input_payload.encode_file
        if not path_obj:
            raise MediaFileNotFoundError("Failed to load input path")
        path_obj = Path(path_obj)

        source_name = path_obj.name
        self.search_label.setText(f"Input: {source_name}")
        self.search_label.setToolTip(source_name)
        self.search_entry.setText(self._get_title_only(path_obj))

        if not self.current_source:
            self._search_tmdb_api()
        else:
            if self.current_source != source_name:
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
            "TVDb": "tvdb_api_key",
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

    @Slot()
    def _search_tmdb_api(self):
        # disable the next button
        self.loading_complete = False
        self.completeChanged.emit()

        if self.search_entry.text().strip != "":
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
    def _handle_search_result(self, result):
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
    def _failed_search(self, error_str: str):
        self.listbox.clear()
        self.listbox.addItem(f"No results, {error_str}")
        self.search_entry.clear()
        self.search_entry.setPlaceholderText("Manually input title")
        GSigs().main_window_set_disabled.emit(False)
        GSigs().main_window_clear_status_tip.emit()

    @Slot()
    def _select_media(self):
        current_item = self.listbox.currentItem().text()
        item_data = self.backend.media_data.get(current_item)
        if item_data:
            self.imdb_id_entry.setText(item_data.get("imdb_id"))
            self.tmdb_id_entry.setText(item_data.get("tvdb_id"))
            self.plot_text.setPlainText(item_data.get("plot"))
            self.rating_label.setText(item_data.get("vote_average"))
            self.release_date_label.setText(item_data.get("full_release_date"))
            self.media_type_label.setText(item_data.get("media_type"))

    @Slot()
    def _open_imdb_link(self, _):
        imdb = self.imdb_id_entry.text().strip()
        if imdb != "":
            webbrowser.open(f"https://imdb.com/title/{imdb}/")
        else:
            webbrowser.open("https://www.imdb.com/")

    @Slot()
    def _open_tmdb_link(self, _):
        tmdb_id = self.tmdb_id_entry.text().strip()
        if tmdb_id != "":
            webbrowser.open(f"https://www.themoviedb.org/movie/{tmdb_id}/")
        else:
            webbrowser.open("https://www.themoviedb.org/movie/")

    @Slot()
    def _open_tvdb_link(self, _):
        tvdb_id = self.tvdb_id_entry.text().strip()
        if tvdb_id != "":
            webbrowser.open(f"https://thetvdb.com/search?query={tvdb_id}")
        else:
            webbrowser.open("https://thetvdb.com/search?query=")

    @Slot()
    def _open_mal_link(self, _):
        mal_id = self.mal_id_entry.text().strip()
        if mal_id != "":
            webbrowser.open(f"https://myanimelist.net/anime/{mal_id}")
        else:
            webbrowser.open("https://myanimelist.net/")

    @Slot()
    def reset_page(self, all_widgets: bool = True):
        self.listbox.clear()
        self.listbox.setDisabled(False)
        self.imdb_id_entry.clear()
        self.tmdb_id_entry.clear()
        self.tvdb_id_entry.clear()
        self.tvdb_id_entry.setPlaceholderText("Automatic")
        self.mal_id_entry.clear()
        self.mal_id_entry.setPlaceholderText("Automatic")
        self.release_date_label.clear()
        self.rating_label.clear()
        self.plot_text.clear()

        self.queued_worker = None
        self.current_source = None
        self.loading_complete = False
        self.id_parse_worker = None
        self.other_ids_parsed = False

        self.backend.update_api_key(self.config.cfg_payload.tmdb_api_key)

        if all_widgets:
            self.search_entry.clear()
