from enum import Enum

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config.config import ConfigManager
from src.enums.trackers.beyondhd import BHDLiveRelease, BHDPromo
from src.enums.trackers.morethantv import MTVSourceOrigin
from src.enums.url_type import URLType
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.masked_qline_edit import MaskedQLineEdit
from src.frontend.custom_widgets.url_organizer import URLOrganizer


class TrackerEditBase(QFrame):
    MAX_CONTROL_WIDTH = 650
    MAX_LABEL_WIDTH = 280

    load_data = Signal()
    save_data = Signal()

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.config = config
        self.load_data.connect(self.load_settings)
        self.save_data.connect(self.save_settings)

        self.upload_enabled_lbl = QLabel("Upload Enabled", self)
        self.upload_enabled_lbl.setToolTip(
            "If disabled, the tracker will be processed but upload and injection will be skipped"
        )
        self.upload_enabled = QCheckBox(self)

        self.announce_url_lbl = QLabel("Announce URL", self)
        self.announce_url = MaskedQLineEdit(masked=True, parent=self)

        self.comments_lbl = QLabel("Torrent Comments", self)
        self.comments = QLineEdit(self)

        self.source_lbl = QLabel("Torrent Source", self)
        self.source = QLineEdit(self)

        self.screen_shot_settings: URLOrganizer | None = None

        self.common_layout = self.build_form_layout()
        self._add_form_row(
            self.common_layout, self.upload_enabled_lbl, self.upload_enabled
        )
        self._add_form_row(self.common_layout, self.announce_url_lbl, self.announce_url)
        self._add_form_row(self.common_layout, self.comments_lbl, self.comments)
        self._add_form_row(self.common_layout, self.source_lbl, self.source)

        # Tracker-specific controls are added by each editor below. Keep the
        # groups open and visible; the editor is already inside a scroll area.
        self.settings_layout = self.build_form_layout()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(10)
        self.main_layout.addWidget(
            self.build_section_heading("General / Upload Settings")
        )
        self.main_layout.addLayout(self.common_layout)
        self.main_layout.addWidget(self.build_section_heading("Tracker Options"))
        self.main_layout.addLayout(self.settings_layout)
        self.setLayout(self.main_layout)

    def add_pair_to_layout(self, label: QLabel, widget: QWidget) -> QFormLayout:
        self._add_form_row(self.settings_layout, label, widget)
        return self.settings_layout

    def add_widget_to_layout(
        self, widget: QWidget, alignment: Qt.AlignmentFlag | None = None
    ) -> None:
        if isinstance(widget, QLabel):
            widget.setWordWrap(True)
            widget.setMaximumWidth(self.MAX_CONTROL_WIDTH)
            widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            if alignment is not None:
                widget.setAlignment(alignment)
        self.settings_layout.addRow(widget)

    def add_screen_shot_settings(self) -> None:
        """Add screenshot layout controls under an always-visible heading."""
        self.screen_shot_settings = URLOrganizer(self)
        self.screen_shot_settings.main_layout.setContentsMargins(0, 0, 0, 0)
        self.screen_shot_settings.setMaximumWidth(self.MAX_CONTROL_WIDTH)
        self.main_layout.addWidget(
            self.build_section_heading("Screenshot / URL Formatting")
        )
        self.main_layout.addWidget(self.screen_shot_settings)

    def load_settings(self) -> None:
        raise NotImplementedError("Must be implemented this per tracker")

    def save_settings(self) -> None:
        raise NotImplementedError("Must be implemented this per tracker")

    @classmethod
    def build_form_layout(cls) -> QFormLayout:
        layout = QFormLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(6)
        return layout

    @classmethod
    def _add_form_row(
        cls, layout: QFormLayout, lbl: QLabel | str, widget: QWidget
    ) -> None:
        label = lbl if isinstance(lbl, QLabel) else QLabel(lbl)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setMaximumWidth(cls.MAX_LABEL_WIDTH)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        widget.setMaximumWidth(cls.MAX_CONTROL_WIDTH)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addRow(label, widget)
        layout.setAlignment(widget, Qt.AlignmentFlag.AlignTop)

    @staticmethod
    def build_section_heading(title: str) -> QLabel:
        label = QLabel(title)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setWordWrap(True)
        label.setContentsMargins(0, 4, 0, 0)
        return label

    @staticmethod
    def load_combo_box(
        widget: CustomComboBox, enum: type[Enum], saved_data: Enum
    ) -> None:
        """Clears CustomComboBox and reloads it with fresh data, setting the default value if available"""
        widget.clear()
        for item in enum:
            widget.addItem(str(item), item)
        current_index = widget.findText(str(enum(saved_data)))
        if current_index >= 0:
            widget.setCurrentIndex(current_index)

    def _disable_scrollwheel_spinbox(self, spinbox: QSpinBox) -> None:
        spinbox.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QSpinBox) and event.type() is QEvent.Type.Wheel:
            event.ignore()
            return True
        return bool(super().eventFilter(watched, event))


class MTVTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        totp_lbl = QLabel("TOTP Secret", self)
        totp_lbl.setToolTip(
            "If 2FA is enabled on your account and no TOTP secret is provided, "
            "you will be prompted to enter your one-time password"
        )
        self.totp = MaskedQLineEdit(parent=self, masked=True)
        self.totp.setToolTip(totp_lbl.toolTip())

        group_description_lbl = QLabel("Group Description", self)
        self.group_description = MaskedQLineEdit(parent=self)

        additional_tags_lbl = QLabel("Additional Tags", self)
        self.additional_tags = MaskedQLineEdit(parent=self)

        source_origin_lbl = QLabel("Source Origin", self)
        self.source_origin = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(100, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(username_lbl, self.username)
        self.add_pair_to_layout(password_lbl, self.password)
        self.add_pair_to_layout(totp_lbl, self.totp)
        self.add_pair_to_layout(group_description_lbl, self.group_description)
        self.add_pair_to_layout(additional_tags_lbl, self.additional_tags)
        self.add_pair_to_layout(source_origin_lbl, self.source_origin)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.more_than_tv
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.username.setText(tracker_data.username if tracker_data.username else "")
        self.password.setText(tracker_data.password if tracker_data.password else "")
        self.totp.setText(tracker_data.totp if tracker_data.totp else "")
        self.group_description.setText(
            tracker_data.group_description if tracker_data.group_description else ""
        )
        self.additional_tags.setText(
            tracker_data.additional_tags if tracker_data.additional_tags else ""
        )
        self.load_combo_box(
            self.source_origin, MTVSourceOrigin, tracker_data.source_origin
        )
        self.image_width.setValue(tracker_data.image_width)
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.more_than_tv.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.more_than_tv.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.more_than_tv.comments = (
            self.comments.text().strip()
        )
        self.config.settings.trackers.more_than_tv.source = self.source.text().strip()
        self.config.settings.trackers.more_than_tv.anonymous = (
            self.anonymous.isChecked()
        )
        self.config.settings.trackers.more_than_tv.api_key = self.api_key.text().strip()
        self.config.settings.trackers.more_than_tv.username = (
            self.username.text().strip()
        )
        self.config.settings.trackers.more_than_tv.password = (
            self.password.text().strip()
        )
        self.config.settings.trackers.more_than_tv.totp = self.totp.text().strip()
        self.config.settings.trackers.more_than_tv.group_description = (
            self.group_description.text().strip()
        )
        self.config.settings.trackers.more_than_tv.additional_tags = (
            self.additional_tags.text().strip()
        )
        self.config.settings.trackers.more_than_tv.source_origin = MTVSourceOrigin(
            self.source_origin.currentData()
        )
        self.config.settings.trackers.more_than_tv.image_width = (
            self.image_width.value()
        )
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.more_than_tv.column_s = col_s
            self.config.settings.trackers.more_than_tv.column_space = col_space
            self.config.settings.trackers.more_than_tv.row_space = row_space


class TLTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        torrent_passkey_lbl = QLabel("Torrent Passkey", self)
        self.torrent_passkey = MaskedQLineEdit(parent=self, masked=True)

        alt_2_fa_token_lbl = QLabel("Alt2FaToken", self)
        self.alt_2_fa_token = MaskedQLineEdit(parent=self, masked=True)

        self.add_pair_to_layout(username_lbl, self.username)
        self.add_pair_to_layout(password_lbl, self.password)
        self.add_pair_to_layout(torrent_passkey_lbl, self.torrent_passkey)
        self.add_pair_to_layout(alt_2_fa_token_lbl, self.alt_2_fa_token)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.torrent_leech
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.username.setText(tracker_data.username if tracker_data.username else "")
        self.password.setText(tracker_data.password if tracker_data.password else "")
        self.torrent_passkey.setText(
            tracker_data.torrent_passkey if tracker_data.torrent_passkey else ""
        )
        self.alt_2_fa_token.setText(
            tracker_data.alt_2_fa_token if tracker_data.alt_2_fa_token else ""
        )
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.torrent_leech.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.torrent_leech.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.torrent_leech.comments = (
            self.comments.text().strip()
        )
        self.config.settings.trackers.torrent_leech.source = self.source.text().strip()
        self.config.settings.trackers.torrent_leech.username = (
            self.username.text().strip()
        )
        self.config.settings.trackers.torrent_leech.password = (
            self.password.text().strip()
        )
        self.config.settings.trackers.torrent_leech.torrent_passkey = (
            self.torrent_passkey.text().strip()
        )
        self.config.settings.trackers.torrent_leech.alt_2_fa_token = (
            self.alt_2_fa_token.text().strip()
        )
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.torrent_leech.column_s = col_s
            self.config.settings.trackers.torrent_leech.column_space = col_space
            self.config.settings.trackers.torrent_leech.row_space = row_space


class BHDTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        rss_key_lbl = QLabel("RSS Key", self)
        self.rss_key = MaskedQLineEdit(parent=self, masked=True)

        promo_lbl = QLabel("Promo", self)
        self.promo = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        live_release_lbl = QLabel("Live Release", self)
        self.live_release = CustomComboBox(
            completer=True, disable_mouse_wheel=True, parent=self
        )

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        localization_to_custom_edition_lbl = QLabel(
            "Add/append localization to Custom Edition field on upload", self
        )
        self.add_localization_to_custom_edition = QCheckBox(self)

        stream_optimized_lbl = QLabel("Upload releases as Streaming Optimized", self)
        self.stream_optimized = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(100, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(rss_key_lbl, self.rss_key)
        self.add_pair_to_layout(promo_lbl, self.promo)
        self.add_pair_to_layout(live_release_lbl, self.live_release)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(
            localization_to_custom_edition_lbl, self.add_localization_to_custom_edition
        )
        self.add_pair_to_layout(stream_optimized_lbl, self.stream_optimized)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.beyond_hd
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.rss_key.setText(tracker_data.rss_key if tracker_data.rss_key else "")
        self.load_combo_box(self.promo, BHDPromo, tracker_data.promo)
        self.load_combo_box(
            self.live_release, BHDLiveRelease, tracker_data.live_release
        )
        self.internal.setChecked(bool(tracker_data.internal))
        self.add_localization_to_custom_edition.setChecked(
            tracker_data.add_localization_to_custom_edition
        )
        self.stream_optimized.setChecked(bool(tracker_data.stream_optimized))
        self.image_width.setValue(tracker_data.image_width)
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.beyond_hd.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.beyond_hd.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.beyond_hd.comments = self.comments.text().strip()
        self.config.settings.trackers.beyond_hd.source = self.source.text().strip()
        self.config.settings.trackers.beyond_hd.anonymous = self.anonymous.isChecked()
        self.config.settings.trackers.beyond_hd.api_key = self.api_key.text().strip()
        self.config.settings.trackers.beyond_hd.rss_key = self.rss_key.text().strip()
        self.config.settings.trackers.beyond_hd.promo = BHDPromo(
            self.promo.currentData()
        )
        self.config.settings.trackers.beyond_hd.live_release = BHDLiveRelease(
            self.live_release.currentData()
        )
        self.config.settings.trackers.beyond_hd.internal = self.internal.isChecked()
        self.config.settings.trackers.beyond_hd.image_width = self.image_width.value()
        self.config.settings.trackers.beyond_hd.add_localization_to_custom_edition = (
            self.add_localization_to_custom_edition.isChecked()
        )
        self.config.settings.trackers.beyond_hd.stream_optimized = (
            self.stream_optimized.isChecked()
        )
        self.config.settings.trackers.beyond_hd.image_width = self.image_width.value()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.beyond_hd.column_s = col_s
            self.config.settings.trackers.beyond_hd.column_space = col_space
            self.config.settings.trackers.beyond_hd.row_space = row_space


class PTPTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_user_lbl = QLabel("API User", self)
        self.api_user = MaskedQLineEdit(parent=self, masked=True)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        username_lbl = QLabel("Username", self)
        self.username = MaskedQLineEdit(parent=self)

        password_lbl = QLabel("Password", self)
        self.password = MaskedQLineEdit(parent=self, masked=True)

        totp_lbl = QLabel(
            '<span>TOTP Secret <span style="font-style: italic; font-size: small;">'
            "(if 2FA is enabled you can add your TOTP secret to avoid prompts during processing)</span></span>",
            parent=self,
        )
        totp_lbl.setToolTip(
            "If 2FA is enabled on your account and no TOTP secret is provided, "
            "you will be prompted to enter your one-time password"
        )
        self.totp = MaskedQLineEdit(parent=self, masked=True)
        self.totp.setToolTip(totp_lbl.toolTip())

        self.add_pair_to_layout(api_user_lbl, self.api_user)
        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(username_lbl, self.username)
        self.add_pair_to_layout(password_lbl, self.password)
        self.add_pair_to_layout(totp_lbl, self.totp)
        self.add_screen_shot_settings()

        # disable columns and column space, PTP doesn't support these
        if self.screen_shot_settings:
            self.screen_shot_settings.column_count_spinbox.setDisabled(True)
            self.screen_shot_settings.column_space_spinbox.setDisabled(True)

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.pass_the_popcorn
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_user.setText(tracker_data.api_user if tracker_data.api_user else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.username.setText(tracker_data.username if tracker_data.username else "")
        self.password.setText(tracker_data.password if tracker_data.password else "")
        self.totp.setText(tracker_data.totp if tracker_data.totp else "")
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.pass_the_popcorn.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.pass_the_popcorn.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.pass_the_popcorn.comments = (
            self.comments.text().strip()
        )
        self.config.settings.trackers.pass_the_popcorn.source = (
            self.source.text().strip()
        )
        self.config.settings.trackers.pass_the_popcorn.api_user = (
            self.api_user.text().strip()
        )
        self.config.settings.trackers.pass_the_popcorn.api_key = (
            self.api_key.text().strip()
        )
        self.config.settings.trackers.pass_the_popcorn.username = (
            self.username.text().strip()
        )
        self.config.settings.trackers.pass_the_popcorn.password = (
            self.password.text().strip()
        )
        self.config.settings.trackers.pass_the_popcorn.totp = self.totp.text().strip()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.pass_the_popcorn.column_s = col_s
            self.config.settings.trackers.pass_the_popcorn.column_space = col_space
            self.config.settings.trackers.pass_the_popcorn.row_space = row_space


class RFTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        personal_release_lbl = QLabel("Personal Release", self)
        self.personal_release = QCheckBox(self)

        stream_optimized_lbl = QLabel("Stream Optimized", self)
        self.stream_optimized = QCheckBox(self)

        opt_in_mod_queue_lbl = QLabel("Opt-in Mod Queue", self)
        self.opt_in_mod_queue = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        staff_and_internal_lbl = QLabel(
            "All items below are available for staff and internal users", self
        )
        bold_font = staff_and_internal_lbl.font()
        bold_font.setWeight(bold_font.Weight.Bold)
        staff_and_internal_lbl.setFont(bold_font)

        featured_lbl = QLabel("Featured", self)
        self.featured = QCheckBox(self)

        free_lbl = QLabel("Free", self)
        self.free = QCheckBox(self)

        double_up_lbl = QLabel("Double Up", self)
        self.double_up = QCheckBox(self)

        sticky_lbl = QLabel("Sticky", self)
        self.sticky = QCheckBox(self)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(personal_release_lbl, self.personal_release)
        self.add_pair_to_layout(stream_optimized_lbl, self.stream_optimized)
        self.add_pair_to_layout(opt_in_mod_queue_lbl, self.opt_in_mod_queue)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_widget_to_layout(
            staff_and_internal_lbl,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.add_pair_to_layout(featured_lbl, self.featured)
        self.add_pair_to_layout(free_lbl, self.free)
        self.add_pair_to_layout(double_up_lbl, self.double_up)
        self.add_pair_to_layout(sticky_lbl, self.sticky)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.reelflix
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.personal_release.setChecked(bool(tracker_data.personal_release))
        self.stream_optimized.setChecked(bool(tracker_data.stream_optimized))
        self.opt_in_mod_queue.setChecked(bool(tracker_data.opt_in_to_mod_queue))
        self.image_width.setValue(tracker_data.image_width)
        self.featured.setChecked(bool(tracker_data.featured))
        self.free.setChecked(bool(tracker_data.free))
        self.double_up.setChecked(bool(tracker_data.double_up))
        self.sticky.setChecked(bool(tracker_data.sticky))
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.reelflix.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.reelflix.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.reelflix.comments = self.comments.text().strip()
        self.config.settings.trackers.reelflix.source = self.source.text().strip()
        self.config.settings.trackers.reelflix.api_key = self.api_key.text().strip()
        self.config.settings.trackers.reelflix.anonymous = self.anonymous.isChecked()
        self.config.settings.trackers.reelflix.internal = self.internal.isChecked()
        self.config.settings.trackers.reelflix.personal_release = (
            self.personal_release.isChecked()
        )
        self.config.settings.trackers.reelflix.stream_optimized = (
            self.stream_optimized.isChecked()
        )
        self.config.settings.trackers.reelflix.opt_in_to_mod_queue = (
            self.opt_in_mod_queue.isChecked()
        )
        self.config.settings.trackers.reelflix.image_width = self.image_width.value()
        self.config.settings.trackers.reelflix.featured = self.featured.isChecked()
        self.config.settings.trackers.reelflix.free = self.free.isChecked()
        self.config.settings.trackers.reelflix.double_up = self.double_up.isChecked()
        self.config.settings.trackers.reelflix.sticky = self.sticky.isChecked()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.reelflix.column_s = col_s
            self.config.settings.trackers.reelflix.column_space = col_space
            self.config.settings.trackers.reelflix.row_space = row_space


class AitherTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        personal_release_lbl = QLabel("Personal Release", self)
        self.personal_release = QCheckBox(self)

        stream_optimized_lbl = QLabel("Stream Optimized", self)
        self.stream_optimized = QCheckBox(self)

        opt_in_mod_queue_lbl = QLabel("Opt-in Mod Queue", self)
        self.opt_in_mod_queue = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        staff_and_internal_lbl = QLabel(
            "All items below are available for staff and internal users", self
        )
        bold_font = staff_and_internal_lbl.font()
        bold_font.setWeight(bold_font.Weight.Bold)
        staff_and_internal_lbl.setFont(bold_font)

        featured_lbl = QLabel("Featured", self)
        self.featured = QCheckBox(self)

        free_lbl = QLabel("Free", self)
        self.free = QCheckBox(self)

        double_up_lbl = QLabel("Double Up", self)
        self.double_up = QCheckBox(self)

        sticky_lbl = QLabel("Sticky", self)
        self.sticky = QCheckBox(self)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(personal_release_lbl, self.personal_release)
        self.add_pair_to_layout(stream_optimized_lbl, self.stream_optimized)
        self.add_pair_to_layout(opt_in_mod_queue_lbl, self.opt_in_mod_queue)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_widget_to_layout(
            staff_and_internal_lbl,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.add_pair_to_layout(featured_lbl, self.featured)
        self.add_pair_to_layout(free_lbl, self.free)
        self.add_pair_to_layout(double_up_lbl, self.double_up)
        self.add_pair_to_layout(sticky_lbl, self.sticky)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.aither
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.personal_release.setChecked(bool(tracker_data.personal_release))
        self.stream_optimized.setChecked(bool(tracker_data.stream_optimized))
        self.opt_in_mod_queue.setChecked(bool(tracker_data.opt_in_to_mod_queue))
        self.image_width.setValue(tracker_data.image_width)
        self.featured.setChecked(bool(tracker_data.featured))
        self.free.setChecked(bool(tracker_data.free))
        self.double_up.setChecked(bool(tracker_data.double_up))
        self.sticky.setChecked(bool(tracker_data.sticky))
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.aither.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.aither.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.aither.comments = self.comments.text().strip()
        self.config.settings.trackers.aither.source = self.source.text().strip()
        self.config.settings.trackers.aither.api_key = self.api_key.text().strip()
        self.config.settings.trackers.aither.anonymous = self.anonymous.isChecked()
        self.config.settings.trackers.aither.internal = self.internal.isChecked()
        self.config.settings.trackers.aither.personal_release = (
            self.personal_release.isChecked()
        )
        self.config.settings.trackers.aither.stream_optimized = (
            self.stream_optimized.isChecked()
        )
        self.config.settings.trackers.aither.opt_in_to_mod_queue = (
            self.opt_in_mod_queue.isChecked()
        )
        self.config.settings.trackers.aither.image_width = self.image_width.value()
        self.config.settings.trackers.aither.featured = self.featured.isChecked()
        self.config.settings.trackers.aither.free = self.free.isChecked()
        self.config.settings.trackers.aither.double_up = self.double_up.isChecked()
        self.config.settings.trackers.aither.sticky = self.sticky.isChecked()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.aither.column_s = col_s
            self.config.settings.trackers.aither.column_space = col_space
            self.config.settings.trackers.aither.row_space = row_space


class HunoTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        stream_optimized_lbl = QLabel("Stream Optimized", self)
        self.stream_optimized = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(stream_optimized_lbl, self.stream_optimized)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.huno
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.stream_optimized.setChecked(bool(tracker_data.stream_optimized))
        self.image_width.setValue(tracker_data.image_width)
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.huno.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.huno.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.huno.comments = self.comments.text().strip()
        self.config.settings.trackers.huno.source = self.source.text().strip()
        self.config.settings.trackers.huno.api_key = self.api_key.text().strip()
        self.config.settings.trackers.huno.anonymous = self.anonymous.isChecked()
        self.config.settings.trackers.huno.internal = self.internal.isChecked()
        self.config.settings.trackers.huno.stream_optimized = (
            self.stream_optimized.isChecked()
        )
        self.config.settings.trackers.huno.image_width = self.image_width.value()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.huno.column_s = col_s
            self.config.settings.trackers.huno.column_space = col_space
            self.config.settings.trackers.huno.row_space = row_space


class LSTTrackerEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        personal_release_lbl = QLabel("Personal Release", self)
        self.personal_release = QCheckBox(self)

        mod_queue_opt_in_lbl = QLabel("Send to ModQ", self)
        self.mod_queue_opt_in = QCheckBox(self)

        draft_queue_opt_in_lbl = QLabel("Send to Draft", self)
        self.draft_queue_opt_in = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        staff_and_internal_lbl = QLabel(
            "All items below are available for staff and internal users", self
        )
        bold_font = staff_and_internal_lbl.font()
        bold_font.setWeight(bold_font.Weight.Bold)
        staff_and_internal_lbl.setFont(bold_font)

        featured_lbl = QLabel("Featured", self)
        self.featured = QCheckBox(self)

        free_lbl = QLabel("Free", self)
        self.free = QCheckBox(self)

        double_up_lbl = QLabel("Double Up", self)
        self.double_up = QCheckBox(self)

        sticky_lbl = QLabel("Sticky", self)
        self.sticky = QCheckBox(self)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(personal_release_lbl, self.personal_release)
        self.add_pair_to_layout(mod_queue_opt_in_lbl, self.mod_queue_opt_in)
        self.add_pair_to_layout(draft_queue_opt_in_lbl, self.draft_queue_opt_in)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_widget_to_layout(
            staff_and_internal_lbl,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.add_pair_to_layout(featured_lbl, self.featured)
        self.add_pair_to_layout(free_lbl, self.free)
        self.add_pair_to_layout(double_up_lbl, self.double_up)
        self.add_pair_to_layout(sticky_lbl, self.sticky)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.lst
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.personal_release.setChecked(bool(tracker_data.personal_release))
        self.mod_queue_opt_in.setChecked(bool(tracker_data.mod_queue_opt_in))
        self.draft_queue_opt_in.setChecked(bool(tracker_data.draft_queue_opt_in))
        self.image_width.setValue(tracker_data.image_width)
        self.featured.setChecked(bool(tracker_data.featured))
        self.free.setChecked(bool(tracker_data.free))
        self.double_up.setChecked(bool(tracker_data.double_up))
        self.sticky.setChecked(bool(tracker_data.sticky))
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.lst.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.lst.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.lst.comments = self.comments.text().strip()
        self.config.settings.trackers.lst.source = self.source.text().strip()
        self.config.settings.trackers.lst.api_key = self.api_key.text().strip()
        self.config.settings.trackers.lst.anonymous = self.anonymous.isChecked()
        self.config.settings.trackers.lst.internal = self.internal.isChecked()
        self.config.settings.trackers.lst.personal_release = (
            self.personal_release.isChecked()
        )
        self.config.settings.trackers.lst.mod_queue_opt_in = (
            self.mod_queue_opt_in.isChecked()
        )
        self.config.settings.trackers.lst.draft_queue_opt_in = (
            self.draft_queue_opt_in.isChecked()
        )
        self.config.settings.trackers.lst.image_width = self.image_width.value()
        self.config.settings.trackers.lst.featured = self.featured.isChecked()
        self.config.settings.trackers.lst.free = self.free.isChecked()
        self.config.settings.trackers.lst.double_up = self.double_up.isChecked()
        self.config.settings.trackers.lst.sticky = self.sticky.isChecked()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.lst.column_s = col_s
            self.config.settings.trackers.lst.column_space = col_space
            self.config.settings.trackers.lst.row_space = row_space


class DarkPeersEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        personal_release_lbl = QLabel("Personal Release", self)
        self.personal_release = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        staff_and_internal_lbl = QLabel(
            "All items below are available for staff and internal users", self
        )
        bold_font = staff_and_internal_lbl.font()
        bold_font.setWeight(bold_font.Weight.Bold)
        staff_and_internal_lbl.setFont(bold_font)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(personal_release_lbl, self.personal_release)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_widget_to_layout(
            staff_and_internal_lbl,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.dark_peers
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.personal_release.setChecked(bool(tracker_data.personal_release))
        self.image_width.setValue(tracker_data.image_width)
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.dark_peers.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.dark_peers.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.dark_peers.comments = self.comments.text().strip()
        self.config.settings.trackers.dark_peers.source = self.source.text().strip()
        self.config.settings.trackers.dark_peers.api_key = self.api_key.text().strip()
        self.config.settings.trackers.dark_peers.anonymous = self.anonymous.isChecked()
        self.config.settings.trackers.dark_peers.internal = self.internal.isChecked()
        self.config.settings.trackers.dark_peers.personal_release = (
            self.personal_release.isChecked()
        )
        self.config.settings.trackers.dark_peers.image_width = self.image_width.value()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.dark_peers.column_s = col_s
            self.config.settings.trackers.dark_peers.column_space = col_space
            self.config.settings.trackers.dark_peers.row_space = row_space


class ShareIslandEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        personal_release_lbl = QLabel("Personal Release", self)
        self.personal_release = QCheckBox(self)

        opt_in_mod_queue_lbl = QLabel("Opt-in Mod Queue", self)
        self.opt_in_mod_queue = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(opt_in_mod_queue_lbl, self.opt_in_mod_queue)
        self.add_pair_to_layout(personal_release_lbl, self.personal_release)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.share_island
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.personal_release.setChecked(bool(tracker_data.personal_release))
        self.opt_in_mod_queue.setChecked(bool(tracker_data.opt_in_to_mod_queue))
        self.image_width.setValue(tracker_data.image_width)
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.share_island.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.share_island.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.share_island.comments = (
            self.comments.text().strip()
        )
        self.config.settings.trackers.share_island.source = self.source.text().strip()
        self.config.settings.trackers.share_island.api_key = self.api_key.text().strip()
        self.config.settings.trackers.share_island.anonymous = (
            self.anonymous.isChecked()
        )
        self.config.settings.trackers.share_island.internal = self.internal.isChecked()
        self.config.settings.trackers.share_island.personal_release = (
            self.personal_release.isChecked()
        )
        self.config.settings.trackers.share_island.opt_in_to_mod_queue = (
            self.opt_in_mod_queue.isChecked()
        )
        self.config.settings.trackers.share_island.image_width = (
            self.image_width.value()
        )
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.share_island.column_s = col_s
            self.config.settings.trackers.share_island.column_space = col_space
            self.config.settings.trackers.share_island.row_space = row_space


class UploadCXEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        personal_release_lbl = QLabel("Personal Release", self)
        self.personal_release = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(personal_release_lbl, self.personal_release)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.upload_cx
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.personal_release.setChecked(bool(tracker_data.personal_release))
        self.image_width.setValue(tracker_data.image_width)
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.upload_cx.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.upload_cx.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.upload_cx.comments = self.comments.text().strip()
        self.config.settings.trackers.upload_cx.source = self.source.text().strip()
        self.config.settings.trackers.upload_cx.api_key = self.api_key.text().strip()
        self.config.settings.trackers.upload_cx.anonymous = self.anonymous.isChecked()
        self.config.settings.trackers.upload_cx.internal = self.internal.isChecked()
        self.config.settings.trackers.upload_cx.personal_release = (
            self.personal_release.isChecked()
        )
        self.config.settings.trackers.upload_cx.image_width = self.image_width.value()
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.upload_cx.column_s = col_s
            self.config.settings.trackers.upload_cx.column_space = col_space
            self.config.settings.trackers.upload_cx.row_space = row_space


class OnlyEncodesEdit(TrackerEditBase):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(config, parent)

        api_key_lbl = QLabel("API Key", self)
        self.api_key = MaskedQLineEdit(parent=self, masked=True)

        anonymous_lbl = QLabel("Anonymous", self)
        self.anonymous = QCheckBox(self)

        internal_lbl = QLabel("Internal", self)
        self.internal = QCheckBox(self)

        personal_release_lbl = QLabel("Personal Release", self)
        self.personal_release = QCheckBox(self)

        image_width_lbl = QLabel("Image Width", self)
        self.image_width = QSpinBox(self)
        self.image_width.setRange(300, 2000)
        self._disable_scrollwheel_spinbox(self.image_width)

        self.add_pair_to_layout(api_key_lbl, self.api_key)
        self.add_pair_to_layout(anonymous_lbl, self.anonymous)
        self.add_pair_to_layout(internal_lbl, self.internal)
        self.add_pair_to_layout(personal_release_lbl, self.personal_release)
        self.add_pair_to_layout(image_width_lbl, self.image_width)
        self.add_screen_shot_settings()

    def load_settings(self) -> None:
        tracker_data = self.config.settings.trackers.only_encodes
        self.upload_enabled.setChecked(tracker_data.upload_enabled)
        self.announce_url.setText(
            tracker_data.announce_url if tracker_data.announce_url else ""
        )
        self.comments.setText(tracker_data.comments if tracker_data.comments else "")
        self.source.setText(tracker_data.source if tracker_data.source else "")
        self.api_key.setText(tracker_data.api_key if tracker_data.api_key else "")
        self.anonymous.setChecked(bool(tracker_data.anonymous))
        self.internal.setChecked(bool(tracker_data.internal))
        self.personal_release.setChecked(bool(tracker_data.personal_release))
        self.image_width.setValue(tracker_data.image_width)
        if self.screen_shot_settings:
            self.screen_shot_settings.load_settings(
                url_type=URLType(tracker_data.url_type),
                columns=tracker_data.column_s,
                col_space=tracker_data.column_space,
                row_space=tracker_data.row_space,
            )

    def save_settings(self) -> None:
        self.config.settings.trackers.only_encodes.upload_enabled = (
            self.upload_enabled.isChecked()
        )
        self.config.settings.trackers.only_encodes.announce_url = (
            self.announce_url.text().strip()
        )
        self.config.settings.trackers.only_encodes.comments = (
            self.comments.text().strip()
        )
        self.config.settings.trackers.only_encodes.source = self.source.text().strip()
        self.config.settings.trackers.only_encodes.api_key = self.api_key.text().strip()
        self.config.settings.trackers.only_encodes.anonymous = (
            self.anonymous.isChecked()
        )
        self.config.settings.trackers.only_encodes.internal = self.internal.isChecked()
        self.config.settings.trackers.only_encodes.personal_release = (
            self.personal_release.isChecked()
        )
        self.config.settings.trackers.only_encodes.image_width = (
            self.image_width.value()
        )
        if self.screen_shot_settings:
            col_s, col_space, row_space = self.screen_shot_settings.current_settings()
            self.config.settings.trackers.only_encodes.column_s = col_s
            self.config.settings.trackers.only_encodes.column_space = col_space
            self.config.settings.trackers.only_encodes.row_space = row_space
