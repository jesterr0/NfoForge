from enum import Enum
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLayout,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.backend.utils.filename_claims import FilenameClaims
from src.config.config import ConfigManager
from src.config.models import ClaimSwitches
from src.enums.token_replacer import FILENAME_COLON_OPTIONS, ColonReplace
from src.frontend.custom_widgets.combo_box import CustomComboBox

if TYPE_CHECKING:
    from src.frontend.stacked_windows.settings.settings import Settings
    from src.frontend.windows.main_window import MainWindow


class BaseSettings(QWidget):
    """
    Inherited in all other settings pages. We'll keep common
    methods etc. in this class.
    """

    load_saved_settings = Signal()
    update_saved_settings = Signal()
    updated_settings_applied = Signal()

    REQUIRED_CHILD_METHODS = ("apply_defaults",)

    # Built by the management pages that carry claim switches, via the
    # helpers below. Declared here so those helpers can be shared rather
    # than written out identically on both pages.
    claims_master: QCheckBox
    claim_checks: dict[str, QCheckBox]

    def __init__(
        self, config: ConfigManager, main_window: "MainWindow", parent: "Settings"
    ) -> None:
        super().__init__(parent)
        self._custom_abstract_method_check()

        self.config = config
        self.main_window = main_window
        self.settings_window = parent

        # this timer is to be used in the child classes, not to be included in
        # this base templates layout
        self._reset_settings_timer = QTimer()
        self._reset_settings_timer.timeout.connect(self._reset_settings_button)
        self._reset_settings_btn = QToolButton()
        self._reset_settings_btn.setText("Reset")
        self._reset_settings_btn.setToolTip("Reset settings to default")
        self._reset_settings_btn.clicked.connect(self._reset_settings_click)
        self.reset_layout = QHBoxLayout()
        self.reset_layout.setContentsMargins(6, 12, 6, 6)
        self.reset_layout.addWidget(
            self._reset_settings_btn, stretch=1, alignment=Qt.AlignmentFlag.AlignRight
        )
        self.reset_layout.addStretch()

        scroll_area = QScrollArea(self)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        inner_widget = QWidget(scroll_area)
        scroll_area.setWidget(inner_widget)
        self.inner_layout = QVBoxLayout(inner_widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.addWidget(scroll_area)

    def _custom_abstract_method_check(self) -> None:
        """This is a work around to avoid mixin with ABC"""
        for method in self.REQUIRED_CHILD_METHODS:
            if not callable(getattr(self, method, None)):
                raise NotImplementedError(
                    f"You must implement the {method} method for {self.__class__.__name__}"
                )

    def add_widget(
        self, widget: QWidget, add_stretch: bool = False, **kwargs: Any
    ) -> None:
        """Adds widget to parent layout, removing and adding the spacer item to the bottom

        add_stretch should be applied to the last item added to the layout"""
        self.inner_layout.addWidget(widget, **kwargs)
        if add_stretch:
            self.inner_layout.addStretch()

    def add_layout(
        self, layout: QLayout, add_stretch: bool = False, **kwargs: Any
    ) -> None:
        """Adds layout to parent layout

        add_stretch should be applied to the last item added to the layout"""
        self.inner_layout.addLayout(layout, **kwargs)
        if add_stretch:
            self.inner_layout.addStretch()

    def _reset_settings_button(self) -> None:
        """Stops the timer and sets the text back to it's default state"""
        self._reset_settings_timer.stop()
        self._reset_settings_btn.setText("Reset")

    def _reset_settings_click(self) -> None:
        """
        Calls `_reset_settings_button` if the timer is active,
        otherwise it starts the timer and calls the children
        method `apply_defaults`
        """
        if self._reset_settings_timer.isActive():
            self._reset_settings_button()
            self.apply_defaults()
        else:
            self._reset_settings_btn.setText("Confirm?")
            self._reset_settings_timer.start(3000)

    def apply_defaults(self) -> None:
        raise NotImplementedError(
            "You must implement method 'apply_defaults' in children classes"
        )

    @staticmethod
    def _build_claims_master(parent: QWidget) -> QCheckBox:
        master = QCheckBox("Parse claims from input filename", parent)
        master.setToolTip(
            "Read claims that MediaInfo cannot verify out of the input "
            "filename. Quality/source and streaming service are always parsed."
        )
        return master

    @staticmethod
    def _build_claim_checks(parent: QWidget) -> dict[str, QCheckBox]:
        return {
            key: QCheckBox(label, parent)
            for key, label in (
                ("edition", "Edition (incl. Cut)"),
                ("frame_size", "Frame size (IMAX / Open Matte)"),
                ("localization", "Localization (Subbed / Dubbed)"),
                ("re_release", "Re-release (PROPER / REPACK)"),
                ("remux", "REMUX"),
                ("hybrid", "HYBRID"),
                ("release_group", "Release group"),
            )
        }

    @staticmethod
    def _build_claim_checks_layout(checks: dict[str, QCheckBox]) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(18, 0, 0, 0)
        layout.setSpacing(0)
        for check in checks.values():
            layout.addWidget(check)
        return layout

    def _load_claim_switches(self, claims: ClaimSwitches) -> None:
        self.claims_master.setChecked(claims.enabled)
        for key, check in self.claim_checks.items():
            check.setChecked(getattr(claims, key))
        # `toggled` does not fire when the checked state is unchanged, so
        # the greyed state is applied explicitly rather than relied upon.
        self._on_claims_master_toggled(claims.enabled)

    def _preview_overrides(self, claims: FilenameClaims) -> dict[str, str]:
        """What the example filename claims, with the configured group tag
        winning over its own group as it does on the rename page."""
        overrides = claims.as_override_tokens()
        if group_tag := self.config.settings.general.release_group:
            overrides["release_group"] = group_tag
        return overrides

    def _current_claim_switches(self) -> ClaimSwitches:
        return ClaimSwitches(
            enabled=self.claims_master.isChecked(),
            **{key: check.isChecked() for key, check in self.claim_checks.items()},
        )

    @Slot(bool)
    def _on_claims_master_toggled(self, checked: bool) -> None:
        """Grey the six at their current values rather than clearing them.

        A user who turns parsing off and on again gets back the categories
        they had, not an empty state.
        """
        for check in self.claim_checks.values():
            check.setEnabled(checked)

    @staticmethod
    def _select_filename_colon(combo: CustomComboBox, saved: ColonReplace) -> None:
        """Select a value by data rather than by index arithmetic.

        `apply_defaults` used `value - 1`, which only lands correctly
        because the three surviving members happen to be 1, 2 and 3.
        """
        index = combo.findData(saved)
        combo.setCurrentIndex(index if index > -1 else 0)

    @classmethod
    def _load_filename_colon_combo(
        cls, combo: CustomComboBox, saved: ColonReplace
    ) -> None:
        """Repopulate the filename colon combo and select the saved value.

        Not `load_combo_box`: that one clears the combo and refills it from
        the *whole* enum, so a three-option filename combo silently grows
        back to five the first time settings are loaded.
        """
        combo.clear()
        for colon_enum, label in FILENAME_COLON_OPTIONS:
            combo.addItem(label, colon_enum)
        cls._select_filename_colon(combo, saved)

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
