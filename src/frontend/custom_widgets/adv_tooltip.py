from __future__ import annotations

from collections.abc import Callable
from enum import Enum, StrEnum, auto

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QCursor, QEnterEvent, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap


class PopupTrigger(Enum):
    """Controls how a HelpButton opens its popup."""

    CLICK = auto()
    HOVER = auto()


class QTAIconStr(StrEnum):
    PH_QUESTION = "ph.question"
    PH_QUESTION_LIGHT = "ph.question-light"
    PH_QUESTION_THIN = "ph.question-thin"
    PH_INFO = "ph.info"
    PH_INFO_LIGHT = "ph.info-light"
    PH_INFO_THIN = "ph.info-thin"


class AdvPopup(QFrame):
    """Popup container for rich text and arbitrary widget content."""

    accepted = Signal()
    rejected = Signal()
    closed = Signal()

    hover_entered = Signal()
    hover_left = Signal()

    CURSOR_MARGIN = 12
    SCREEN_MARGIN = 16
    CONTENT_MARGIN = 8
    SECTION_SPACING = 6

    def __init__(
        self,
        *,
        title: str = "",
        text: str = "",
        body_factory: BodyFactory | None = None,
        parent: QWidget | None = None,
        close_on_click_outside: bool = True,
        frameless: bool = False,
        modal: bool = False,
        show_close_button: bool | None = None,
        close_on_escape: bool = True,
        min_width: int = 300,
        preferred_width: int = 400,
        max_width: int = 600,
        max_height: int = 500,
    ) -> None:
        flags = Qt.WindowType.Popup if close_on_click_outside else Qt.WindowType.Tool
        if frameless:
            flags |= Qt.WindowType.FramelessWindowHint

        super().__init__(parent, flags)

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if modal:
            self.setWindowModality(Qt.WindowModality.WindowModal)

        self._close_on_escape = close_on_escape
        self._modal = modal
        self._result_emitted = False

        self._min_width = min_width
        self._preferred_width = preferred_width
        self._max_width = max_width
        self._max_height = max_height

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(
            self.CONTENT_MARGIN,
            self.CONTENT_MARGIN,
            self.CONTENT_MARGIN,
            self.CONTENT_MARGIN,
        )
        self._main_layout.setSpacing(self.SECTION_SPACING)

        self._title_label: QLabel | None = None
        if title:
            self._add_title(title)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)

        if text:
            self._add_text(text)

        if body_factory is not None:
            self._body_layout.addWidget(body_factory(self))

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setMinimumSize(0, 0)
        self._scroll_area.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Ignored,
        )
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setWidget(self._body)

        self._main_layout.addWidget(self._scroll_area)

        self._close_button = None
        self._close_button_box: QDialogButtonBox | None = None
        should_show_close_button = (
            modal if show_close_button is None else show_close_button
        )
        if should_show_close_button:
            self._add_close_button()

    def _add_title(self, title: str) -> None:
        """Add the popup title."""
        label = QLabel(title, self)

        font = QFont(label.font())
        font.setBold(True)
        label.setFont(font)

        self._title_label = label
        self._main_layout.addWidget(label)

    def _add_text(self, text: str) -> None:
        """Add rich text to the popup body."""
        label = QLabel(text, self._body)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        label.setOpenExternalLinks(True)

        self._body_layout.addWidget(label)

    def _add_close_button(self) -> None:
        """Add a standard close action for a modal popup."""
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            self,
        )
        button_box.rejected.connect(self.reject)
        self._close_button_box = button_box
        self._close_button = button_box.button(QDialogButtonBox.StandardButton.Close)
        self._main_layout.addWidget(button_box)

    def accept(self) -> None:
        """Accept and close the popup."""
        if self._result_emitted:
            return

        self._result_emitted = True
        self.accepted.emit()
        self.close()

    def reject(self) -> None:
        """Reject and close the popup."""
        if self._result_emitted:
            return

        self._result_emitted = True
        self.rejected.emit()
        self.close()

    def show_popup(self, position: QPoint | None = None) -> None:
        """Show near a global position, defaulting to the cursor."""
        anchor = position if position is not None else QCursor.pos()

        screen = QApplication.screenAt(anchor)

        if screen is None:
            screen = QApplication.primaryScreen()

        if screen is None:
            self.adjustSize()
            self.move(
                anchor
                + QPoint(
                    self.CURSOR_MARGIN,
                    self.CURSOR_MARGIN,
                )
            )
            self.show()
            return

        available = screen.availableGeometry()

        self._resize_to_content(available)
        self.move(self._popup_position(anchor, available))

        self.show()
        self.raise_()
        self._focus_default_control()

    def _focus_default_control(self) -> None:
        """Focus the first interactive body control in a modal popup."""
        if not self._modal:
            return

        for widget in self._body.findChildren(QWidget):
            if (
                widget.isEnabled()
                and widget.isVisible()
                and widget.focusPolicy() != Qt.FocusPolicy.NoFocus
            ):
                widget.setFocus(Qt.FocusReason.PopupFocusReason)
                return

        if self._close_button is not None:
            self._close_button.setFocus(Qt.FocusReason.PopupFocusReason)

    def _resize_to_content(self, available: QRect) -> None:
        """Grow naturally until scrolling is required."""
        available_width = max(
            1,
            available.width() - (self.SCREEN_MARGIN * 2),
        )
        available_height = max(
            1,
            available.height() - (self.SCREEN_MARGIN * 2),
        )

        max_width = min(
            self._max_width,
            available_width,
        )
        max_height = min(
            self._max_height,
            available_height,
        )

        min_width = min(
            self._min_width,
            max_width,
        )

        margins = self._main_layout.contentsMargins()
        body_hint = self._body.sizeHint()

        desired_width = max(
            min_width,
            self._preferred_width,
            body_hint.width() + margins.left() + margins.right(),
        )

        desired_width = min(
            desired_width,
            max_width,
        )

        self.setMinimumWidth(min_width)
        self.setMaximumSize(
            max_width,
            max_height,
        )

        desired_height = min(
            self._content_height(desired_width),
            max_height,
        )

        self.resize(
            desired_width,
            desired_height,
        )

    def _content_height(self, popup_width: int) -> int:
        """Return the height required by the visible popup content."""
        margins = self._main_layout.contentsMargins()
        frame_width = self.frameWidth() * 2
        body_width = max(
            1,
            popup_width - margins.left() - margins.right() - frame_width,
        )

        body_height = self._body_layout.heightForWidth(body_width)
        if body_height < 0:
            body_height = self._body_layout.sizeHint().height()

        section_heights = [body_height]
        if self._title_label is not None:
            section_heights.insert(0, self._title_label.sizeHint().height())

        if self._close_button_box is not None:
            section_heights.append(self._close_button_box.sizeHint().height())

        return (
            margins.top()
            + margins.bottom()
            + frame_width
            + sum(section_heights)
            + self._main_layout.spacing() * (len(section_heights) - 1)
        )

    def _popup_position(
        self,
        anchor: QPoint,
        available: QRect,
    ) -> QPoint:
        """Position near the anchor while remaining on-screen."""
        x = anchor.x() + self.CURSOR_MARGIN
        y = anchor.y() + self.CURSOR_MARGIN

        right = available.right() - self.SCREEN_MARGIN
        bottom = available.bottom() - self.SCREEN_MARGIN

        # prefer the right side of the anchor.
        if x + self.width() > right:
            x = anchor.x() - self.width() - self.CURSOR_MARGIN

        # prefer below the anchor.
        if y + self.height() > bottom:
            y = anchor.y() - self.height() - self.CURSOR_MARGIN

        min_x = available.left() + self.SCREEN_MARGIN
        min_y = available.top() + self.SCREEN_MARGIN

        max_x = max(
            min_x,
            right - self.width(),
        )
        max_y = max(
            min_y,
            bottom - self.height(),
        )

        return QPoint(
            max(min_x, min(x, max_x)),
            max(min_y, min(y, max_y)),
        )

    def contains_global_position(self, position: QPoint) -> bool:
        """Return whether a global position is inside the popup."""
        local_position = self.mapFromGlobal(position)
        return self.rect().contains(local_position)

    def enterEvent(self, event: QEnterEvent) -> None:
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.hover_left.emit()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._close_on_escape and event.key() == Qt.Key.Key_Escape:
            self.reject()
            return

        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        super().closeEvent(event)


BodyFactory = Callable[[AdvPopup], QWidget]


class AdvPopupBtn(QToolButton):
    """Tool button that displays contextual content in an AdvPopup."""

    popup_opened = Signal(AdvPopup)

    def __init__(
        self,
        title: str = "",
        text: str = "",
        *,
        body_factory: BodyFactory | None = None,
        parent: QWidget | None = None,
        trigger: PopupTrigger = PopupTrigger.CLICK,
        close_on_click_outside: bool = True,
        modal: bool = False,
        show_close_button: bool | None = None,
        hover_open_delay: int = 250,
        hover_close_delay: int = 300,
        preferred_width: int = 400,
        max_width: int = 600,
        max_height: int = 500,
        qta_icon_str: QTAIconStr | str = QTAIconStr.PH_INFO_LIGHT,
        qta_icon_size: tuple[int, int] = (24, 24),
    ) -> None:
        """For more `qta_icon_str`s see https://github.com/spyder-ide/qtawesome."""
        super().__init__(parent)

        self._title = title
        self._text = text
        self._body_factory = body_factory
        self._trigger = trigger
        self._close_on_click_outside = close_on_click_outside
        self._modal = modal
        self._show_close_button = show_close_button

        self._preferred_width = preferred_width
        self._max_width = max_width
        self._max_height = max_height

        self._popup: AdvPopup | None = None

        self._open_timer: QTimer | None = None
        self._close_timer: QTimer | None = None

        self.setAutoRaise(True)
        self.setAccessibleName(f"Help: {title}")
        self.setAccessibleDescription(title)
        if self._trigger is PopupTrigger.CLICK:
            self.setToolTip(f"Show help: {title}")
        else:
            self.setStyleSheet("""
                QToolButton {
                    border: none;
                    background: transparent;
                    padding: 0;
                }
            """)

        QTAThemeSwap().register(
            self,
            str(qta_icon_str),
            icon_size=QSize(24, 24),
        )

        if self._trigger is PopupTrigger.CLICK:
            self.clicked.connect(self.show_popup)
        else:
            self._setup_hover(
                hover_open_delay,
                hover_close_delay,
            )

    def _setup_hover(
        self,
        open_delay: int,
        close_delay: int,
    ) -> None:
        """Configure timers used by hover-triggered popups."""
        self._open_timer = QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.setInterval(open_delay)
        self._open_timer.timeout.connect(self._open_from_hover)

        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(close_delay)
        self._close_timer.timeout.connect(self._close_from_hover)

    def show_popup(self) -> None:
        """Open the popup if it is not already visible."""
        self._stop_timers()

        if self._popup is not None and self._popup.isVisible():
            return

        if self._popup is not None:
            self._popup.deleteLater()
            self._popup = None

        # Qt.Popup works well for click-triggered content because Qt
        # automatically closes it when clicking elsewhere.
        #
        # Hover-triggered content intentionally uses Qt.Tool instead.
        # Qt.Popup grabs popup/mouse state and can cause artificial
        # enter/leave events on the trigger, creating an open/close loop.
        close_on_click_outside = (
            self._close_on_click_outside
            if self._trigger is PopupTrigger.CLICK
            else False
        )

        popup = AdvPopup(
            title=self._title,
            text=self._text,
            body_factory=self._body_factory,
            parent=self.window(),
            close_on_click_outside=close_on_click_outside,
            frameless=self._trigger is PopupTrigger.HOVER,
            modal=self._modal,
            show_close_button=self._show_close_button,
            preferred_width=self._preferred_width,
            max_width=self._max_width,
            max_height=self._max_height,
        )

        self._popup = popup

        popup.destroyed.connect(lambda *_: self._popup_destroyed(popup))

        if self._trigger is PopupTrigger.HOVER:
            popup.hover_entered.connect(self._popup_entered)
            popup.hover_left.connect(self._popup_left)

        popup.show_popup(self._popup_anchor())

        self.popup_opened.emit(popup)

    def close_popup(self) -> None:
        """Close the current popup."""
        if self._popup is not None:
            self._popup.close()

    def enterEvent(self, event: QEnterEvent) -> None:
        if self._trigger is PopupTrigger.HOVER:
            if self._close_timer is not None:
                self._close_timer.stop()

            if self._open_timer is not None:
                self._open_timer.start()

        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self._trigger is PopupTrigger.HOVER:
            if self._open_timer is not None:
                self._open_timer.stop()

            if self._close_timer is not None:
                self._close_timer.start()

        super().leaveEvent(event)

    def _open_from_hover(self) -> None:
        """Open if the cursor is still genuinely over the button."""
        if self._cursor_over_button() and (
            self._popup is None or not self._popup.isVisible()
        ):
            self.show_popup()

    def _close_from_hover(self) -> None:
        """Close once the cursor has left both trigger and popup."""
        cursor_position = QCursor.pos()

        if self._contains_global_position(cursor_position):
            return

        if self._popup is not None and self._popup.contains_global_position(
            cursor_position
        ):
            return

        self.close_popup()

    def _popup_entered(self) -> None:
        if self._close_timer is not None:
            self._close_timer.stop()

    def _popup_left(self) -> None:
        if self._close_timer is not None:
            self._close_timer.start()

    def _popup_destroyed(self, popup: AdvPopup) -> None:
        """Clear the reference when the currently displayed popup dies."""
        if self._popup is popup:
            self._popup = None

    def _cursor_over_button(self) -> bool:
        """Return whether the cursor is currently over the button."""
        return self._contains_global_position(QCursor.pos())

    def _popup_anchor(self) -> QPoint:
        """Anchor the popup to the button instead of the cursor."""
        return self.mapToGlobal(self.rect().bottomLeft())

    def _contains_global_position(
        self,
        position: QPoint,
    ) -> bool:
        """Return whether a global position is inside the button."""
        local_position = self.mapFromGlobal(position)
        return self.rect().contains(local_position)

    def _stop_timers(self) -> None:
        if self._open_timer is not None:
            self._open_timer.stop()

        if self._close_timer is not None:
            self._close_timer.stop()


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = QWidget()
    window.setWindowTitle("AdvPopup Test")
    window.resize(600, 400)

    layout = QVBoxLayout(window)

    # Simple click help
    click_help = AdvPopupBtn(
        "Click Help",
        (
            "This is a <b>click-triggered</b> popup.<br><br>"
            "Click outside the popup or press Escape to close it."
        ),
    )
    layout.addWidget(QLabel("Click popup:"))
    layout.addWidget(click_help)

    # Hover help
    hover_help = AdvPopupBtn(
        "Hover Help",
        (
            "This popup opens when you <b>hover</b> over the info icon.<br><br>"
            "You can move the mouse into this popup without it "
            "immediately disappearing."
        ),
        trigger=PopupTrigger.HOVER,
    )
    layout.addWidget(QLabel("Hover popup:"))
    layout.addWidget(hover_help)

    # large body to test scrolling
    def create_large_body(popup: AdvPopup) -> QWidget:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        for i in range(30):
            body_layout.addWidget(QLabel(f"Additional information #{i + 1}"))

        return body

    scroll_help = AdvPopupBtn(
        "Scrollable Content",
        "This popup contains enough content to require scrolling.",
        body_factory=create_large_body,
        max_height=350,
    )
    layout.addWidget(QLabel("Scrollable popup:"))
    layout.addWidget(scroll_help)

    # interactive body to test accept/reject
    def create_form(popup: AdvPopup) -> QWidget:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        body_layout.addWidget(QLabel("Pretend there are some form controls here."))

        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")

        save_button.clicked.connect(popup.accept)
        cancel_button.clicked.connect(popup.reject)

        body_layout.addWidget(save_button)
        body_layout.addWidget(cancel_button)

        return body

    form_help = AdvPopupBtn(
        "Interactive Popup",
        "This popup demonstrates an interactive body.",
        body_factory=create_form,
        close_on_click_outside=False,
        modal=True,
        show_close_button=False,
    )

    def form_opened(popup: AdvPopup) -> None:
        popup.accepted.connect(lambda: print("Popup accepted"))
        popup.rejected.connect(lambda: print("Popup rejected"))
        popup.closed.connect(lambda: print("Popup closed"))

    form_help.popup_opened.connect(form_opened)

    layout.addWidget(QLabel("Interactive popup:"))
    layout.addWidget(form_help)

    layout.addStretch()

    window.show()

    sys.exit(app.exec())
