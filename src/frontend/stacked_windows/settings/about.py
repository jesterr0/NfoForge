from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
)

from src.backend.utils.working_dir import RUNTIME_DIR
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings
from src.frontend.utils import build_h_line
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.version import __version__


about_txt = f"""\
<h2 style="text-align: center;">NfoForge v{__version__}</h2>
<p style="text-align: center;">A powerful media upload assistant.</p>
<h3>Key Features</h3>
<ul>
    <li>Token system for advanced media file renaming.</li>
    <li>Integration with TMDB and IMDb for title parsing.</li>
    <li>Flexible Jinja-based template system for .NFO file generation.</li>
    <li>Screenshot generation and upload, including comparisons.</li>
    <li>Output file organization, saving .torrent and .NFO files to disk.</li>
    <li>Torrent cloning support for multi-tracker releases without re-generation.</li>
    <li>Duplicate release checker - checks trackers for duplicates pre-upload.</li>
    <li>Support for BeyondHD, MoreThanTV, and TorrentLeech, with more trackers coming soon.</li>
    <li>Integration with Deluge, qBittorrent, Transmission, rTorrent, and watch folders, as well as fast resume support.</li>
    <li>Plugin support for Python (.py) and compiled (.pyd) files (.pyd compiled files requires the same python version as NfoForge).</li>
    <li>Support for movie files in MKV and MP4 format</li>
    <li>Additional format support and features coming soon!</li>
</ul>
<h3>Thanks and Credits</h3>
<ul>
    <li>aiohttp</li>
    <li>beautifulsoup4</li>
    <li>cinemagoer</li>
    <li>deluge-web-client</li>
    <li>Guessit</li>
    <li>iso639-lang</li>
    <li>jinja2</li>
    <li>L4G's Upload Assistant, for inspiration</li>
    <li>pymediainfo</li>
    <li>pyimgbox</li>
    <li>PySide6</li>
    <li>qbittorrent-api</li>
    <li>niquests</li>
    <li>tomlkit</li>
    <li>torf</li>
    <li>transmission-rpc</li>
    <li>qtawesome</li>
</ul>
<h3>Support</h3>
<a href="https://github.com/jesterr0/NfoForge">Github</a>
<br />
<a href="https://jesterr0.github.io/NfoForge/">Documentation</a>
<OFFLINE_DOCS_PATH_REP>
<h3>Attributions</h3>
"""


class AboutTab(BaseSettings):
    ATTRIBUTION_SIZE = (138, 88)

    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("aboutTab")

        self.update_saved_settings.connect(self._save_settings)

        docs_index_path = RUNTIME_DIR / "docs" / "index.html"
        self.about_lbl = QLabel(
            about_txt.replace(
                "<OFFLINE_DOCS_PATH_REP>",
                f'<br /><a href="file:///{docs_index_path}">Offline Documentation</a>',
            )
            if docs_index_path.exists()
            else about_txt.replace("<OFFLINE_DOCS_PATH_REP>", ""),
            self,
        )
        self.about_lbl.setWordWrap(True)
        self.about_lbl.setOpenExternalLinks(True)

        # tvdb
        self.tvdb_image_lbl = QLabel(self)

        tvdb_info_attr_info = QLabel(
            '<span>Metadata provided by <a href="https://www.thetvdb.com/">TVDB</a>. '
            "Please consider adding missing information"
            ' or <a href="https://thetvdb.com/subscribe">subscribing</a></span>.',
            wordWrap=True,
            openExternalLinks=True,
            parent=self,
        )

        tvdb_frame_layout = QHBoxLayout()
        tvdb_frame_layout.addWidget(self.tvdb_image_lbl)
        tvdb_frame_layout.addWidget(tvdb_info_attr_info, stretch=1)

        # tmdb
        tmdb_icon = QPixmap(str(RUNTIME_DIR / "images" / "tmdb_med.png")).scaled(
            *self.ATTRIBUTION_SIZE,
            aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
            mode=Qt.TransformationMode.SmoothTransformation,
        )
        self.tmdb_image_lbl = QLabel(self)
        self.tmdb_image_lbl.setPixmap(tmdb_icon)

        tmdb_info_attr_info = QLabel(
            '<span>Metadata provided by <a href="https://www.themoviedb.org/">TMDB</a></span>.',
            wordWrap=True,
            openExternalLinks=True,
            parent=self,
        )

        tmdb_frame_layout = QHBoxLayout()
        tmdb_frame_layout.addWidget(self.tmdb_image_lbl)
        tmdb_frame_layout.addWidget(tmdb_info_attr_info, stretch=1)

        donation_info_lbl = QLabel(
            "<h3>Donations</h3><p>NfoForge is a free application. "
            "Donations of any size are greatly appreciated, and will support "
            "NfoForge's active development. Thank you!</p>",
            wordWrap=True,
            parent=self,
        )

        self.bitcoin_lbl = QLabel("<h4>Bitcoin</h4>", self)
        self.bitcoin_qr_img = QLabel(self)
        self.bitcoin_qr_img.setPixmap(
            QPixmap(str(RUNTIME_DIR / "images" / "bitcoin_qr.png")).scaled(
                160,
                160,
                aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
                mode=Qt.TransformationMode.SmoothTransformation,
            )
        )

        self.bitcoin_hash = MaskedQLineEdit(parent=self)
        self.bitcoin_hash.setReadOnly(True)
        self.bitcoin_hash.setText("bc1qwkhxfea0zmnuatt9fe784q87w0mwl72wd24xxc")

        self.bitcoin_copy_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.bitcoin_copy_btn, "ph.copy-simple-light", icon_size=QSize(20, 20)
        )
        self.bitcoin_copy_btn.clicked.connect(self._copy_bitcoin_to_clipboard)

        self.bitcoin_layout = QVBoxLayout()
        self.bitcoin_layout.setContentsMargins(0, 0, 0, 0)
        self.bitcoin_layout.addWidget(
            self.bitcoin_lbl, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.bitcoin_layout.addWidget(
            self.bitcoin_qr_img, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.bitcoin_layout.addLayout(
            self._build_h_layout(self.bitcoin_hash, self.bitcoin_copy_btn)
        )

        self.ethereum_lbl = QLabel("<h4>Ethereum</h4>", self)
        self.ethereum_qr_img = QLabel(self)
        self.ethereum_qr_img.setPixmap(
            QPixmap(str(RUNTIME_DIR / "images" / "eth_qr.png")).scaled(
                160,
                160,
                aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
                mode=Qt.TransformationMode.SmoothTransformation,
            )
        )

        self.ethereum_hash = MaskedQLineEdit(parent=self)
        self.ethereum_hash.setReadOnly(True)
        self.ethereum_hash.setText("0x86a726C7158b852C8001Fb6762f3a263742529e6")

        self.ethereum_copy_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.ethereum_copy_btn, "ph.copy-simple-light", icon_size=QSize(20, 20)
        )
        self.ethereum_copy_btn.clicked.connect(self._copy_ethereum_to_clipboard)

        self.ethereum_layout = QVBoxLayout()
        self.ethereum_layout.setContentsMargins(0, 0, 0, 0)
        self.ethereum_layout.addWidget(
            self.ethereum_lbl, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.ethereum_layout.addWidget(
            self.ethereum_qr_img, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.ethereum_layout.addLayout(
            self._build_h_layout(self.ethereum_hash, self.ethereum_copy_btn)
        )

        # connect to color scheme change signal to change images based on dark/light mode
        app = QApplication.instance()
        QApplication.instance().styleHints().colorSchemeChanged.connect(  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]
            self._update_tvdb_image
        )
        # set the initial image
        self._update_tvdb_image(app.styleHints().colorScheme())  # pyright: ignore [reportAttributeAccessIssue, reportOptionalMemberAccess]

        self.add_widget(self.about_lbl)
        self.add_layout(tvdb_frame_layout)
        self.inner_layout.addSpacing(10)
        self.add_layout(tmdb_frame_layout)
        self.add_widget(build_h_line((20, 1, 20, 1)))
        self.add_widget(donation_info_lbl)
        self.add_layout(self.bitcoin_layout)
        self.add_widget(build_h_line((20, 1, 20, 1)))
        self.add_layout(self.ethereum_layout, add_stretch=True)

    def _copy_bitcoin_to_clipboard(self) -> None:
        self._copy_to_clipboard(self.bitcoin_hash.text())

    def _copy_ethereum_to_clipboard(self) -> None:
        self._copy_to_clipboard(self.ethereum_hash.text())

    def _copy_to_clipboard(self, txt: str) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(txt)
        GSigs().main_window_update_status_tip.emit("Copied to clipboard!", 2000)

    def _build_h_layout(self, entry: MaskedQLineEdit, btn: QToolButton) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(80, 0, 80, 0)
        layout.addWidget(entry, stretch=1)
        layout.addWidget(btn)
        return layout

    @Slot(Qt.ColorScheme)
    def _update_tvdb_image(self, color_scheme: Qt.ColorScheme):
        """Updates the image based on the color scheme."""
        if color_scheme == Qt.ColorScheme.Dark:
            tvdb_icon = QPixmap(str(RUNTIME_DIR / "images" / "tvdb_dark.png")).scaled(
                *self.ATTRIBUTION_SIZE,
                aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
                mode=Qt.TransformationMode.SmoothTransformation,
            )
        else:
            tvdb_icon = QPixmap(str(RUNTIME_DIR / "images" / "tvdb.png")).scaled(
                *self.ATTRIBUTION_SIZE,
                aspectMode=Qt.AspectRatioMode.KeepAspectRatio,
                mode=Qt.TransformationMode.SmoothTransformation,
            )
        self.tvdb_image_lbl.setPixmap(tvdb_icon)

    @Slot()
    def _save_settings(self) -> None:
        """Even though no settings are changed, this still needs to be called to "complete" the save."""
        self.updated_settings_applied.emit()
