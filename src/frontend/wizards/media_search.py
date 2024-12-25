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
from src.exceptions import MediaFileNotFoundError, MediaParsingError
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

    def __init__(self, backend, query) -> None:
        super().__init__()
        self.backend = backend
        self.query = query

    def run(self) -> None:
        try:
            result = self.backend._parse_tmdb_api(self.query)
            self.job_finished.emit(OrderedDict(result))
        except Exception as e:
            self.job_failed.emit(f"Failed to parse TMDB: {e}\n{traceback.format_exc()}")


class IMDBParseWorker(QThread):
    job_finished = Signal(tuple)
    job_failed = Signal(str)

    def __init__(self, backend: MediaSearchBackEnd, imdb_id: str) -> None:
        super().__init__()
        self.backend = backend
        self.imdb_id = imdb_id

    def run(self) -> None:
        try:
            media_title = None
            media_year = None
            media_original_title = None

            parse_imdb_data = self.backend.parse_imdb(self.imdb_id)
            if parse_imdb_data:
                media_title, media_year, media_original_title = parse_imdb_data

            self.job_finished.emit((media_title, media_year, media_original_title))
        except Exception as e:
            self.job_failed.emit(
                f"Failed to parse IMDB: ({e})\n{traceback.format_exc()}"
            )


class MediaSearch(BaseWizardPage):
    def __init__(self, config: Config, parent: "MainWindow | Any"):
        super().__init__(config, parent)
        self.setTitle("Search")
        self.setObjectName("mediaSearch")
        self.setCommitPage(True)

        self.main_window = parent

        self.config = config
        self.payload = self.config.media_search_payload
        self.backend = MediaSearchBackEnd(api_key=self.config.cfg_payload.tmdb_api_key)
        self.queued_worker: QueuedWorker | None = None
        self.current_source = None
        self.loading_complete = False
        self.imdb_worker: IMDBParseWorker | None = None
        self.imdb_parsed = False

        self.listbox = QListWidget()
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
        imdb_h_layout = QHBoxLayout()
        imdb_h_layout.addWidget(imdb_label)
        imdb_h_layout.addWidget(self.imdb_id_entry)

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
        tmdb_h_layout = QHBoxLayout()
        tmdb_h_layout.addWidget(tmdb_label)
        tmdb_h_layout.addWidget(self.tmdb_id_entry)

        tmdb_imdb_v_layout = QVBoxLayout()
        tmdb_imdb_v_layout.addLayout(imdb_h_layout)
        tmdb_imdb_v_layout.addLayout(tmdb_h_layout)

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
        required_entries = [self.tmdb_id_entry, self.imdb_id_entry]
        invalid_entries = False

        for entry in required_entries:
            if entry.text().strip() == "" or entry.text() == entry.placeholderText():
                invalid_entries = True
                # TODO: Flash red or something once we theme it
                # entry.setStyleSheet("QLineEdit {border: 1px solid red; border-radius: 3px;}")
                entry.setPlaceholderText("Requires ID")

        if invalid_entries:
            return False
        else:
            # TODO: should we thread this and display loading in the UI (for imdb parse)?
            # TMDB is the default information provided
            media_title = self.config.media_search_payload.title
            media_year = self.config.media_search_payload.year
            media_original_title = self.config.media_search_payload.original_title
            self._update_payload_data(media_title, media_year, media_original_title)

            # if the user wants to use IMDb
            if not self.imdb_parsed and self.config.cfg_payload.mvr_imdb_parse:
                self._search_imdb()
                return False

            return True

    def _search_imdb(self) -> None:
        self.main_window.set_disabled.emit(True)
        self.imdb_worker = IMDBParseWorker(
            self.backend, self.imdb_id_entry.text().strip()
        )
        self.imdb_worker.job_finished.connect(self._detected_imdb_data)
        self.imdb_worker.job_failed.connect(self._failed_search)
        self.imdb_worker.start()

    @Slot(tuple)
    def _detected_imdb_data(
        self, media_data: tuple[str | None, int | None, str | None]
    ) -> None:
        if media_data:
            media_title, media_year, media_original_title = media_data
            self._update_payload_data(media_title, media_year, media_original_title)
        self.imdb_parsed = True
        self.main_window.set_disabled.emit(False)
        if self.main_window.wizard:
            self.main_window.wizard.next()

    def _update_payload_data(
        self,
        media_title: str | None,
        media_year: int | None,
        media_original_title: str | None,
    ):
        self.payload.imdb_id = self.imdb_id_entry.text()
        self.payload.tmdb_id = self.tmdb_id_entry.text()
        self.payload.title = media_title
        self.payload.year = media_year
        self.payload.original_title = media_original_title

    def isComplete(self):
        """Overrides isComplete method to control the next button"""
        return self.loading_complete

    def initializePage(self):
        if not self._get_tmdb_api_key():
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

    def _get_tmdb_api_key(self) -> bool:
        if not self.config.cfg_payload.tmdb_api_key.strip():
            text, ok = QInputDialog.getText(
                self,
                "TMDB Api Key",
                "Requires TMDB Api Key (v3), please input this now",
            )
            if ok and text:
                self.config.cfg_payload.tmdb_api_key = text.strip()
                self.config.save_config()
                self.backend.update_api_key(self.config.cfg_payload.tmdb_api_key)
            else:
                QMessageBox.critical(
                    self,
                    "TMDB Api Key",
                    "You must input a TMDB Api Key (v3) to continue",
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

            self.queued_worker = QueuedWorker(self.backend, self.search_entry.text())
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
        self.main_window.set_disabled.emit(False)

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

            # set non ui related stuff on media selection click event
            self.config.media_search_payload.title = item_data.get("title")
            self.config.media_search_payload.original_title = item_data.get(
                "original_title"
            )
            self.config.media_search_payload.year = item_data.get("year")
            self.config.media_search_payload.genres = item_data.get("genre_ids")

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
    def reset_page(self, all_widgets: bool = True):
        self.listbox.clear()
        self.imdb_id_entry.clear()
        self.tmdb_id_entry.clear()
        self.release_date_label.clear()
        self.rating_label.clear()
        self.plot_text.clear()

        self.queued_worker = None
        self.current_source = None
        self.loading_complete = False
        self.imdb_worker = None
        self.imdb_parsed = False

        self.backend.update_api_key(self.config.cfg_payload.tmdb_api_key)

        if all_widgets:
            self.search_entry.clear()
