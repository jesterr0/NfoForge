from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QRect, Signal, SignalInstance
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QLineEdit, QPushButton, QToolButton, QWidget

from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.custom_widgets.image_listbox import ThumbnailListWidget


class _HasDNDSignals(Protocol):
    accept_dir: bool
    accept_text: bool
    supported_extensions: Iterable[str] | None

    dropped: SignalInstance
    text_dropped: SignalInstance


class DNDMixin:
    accept_dir: bool = False
    accept_text: bool = False
    supported_extensions: Iterable[str] | None = None

    def dragEnterEvent(self: _HasDNDSignals, event: QDragEnterEvent) -> None:
        """Handles drag enter events. Ensures drag is accepted for valid files, directories, or text."""
        mime = event.mimeData()
        if mime.hasUrls():
            urls = mime.urls()
            if urls:
                drop = Path(urls[0].toLocalFile())
                if drop.is_file() and drop.exists():
                    if self.supported_extensions:
                        if (
                            "*" in self.supported_extensions
                            or drop.suffix in self.supported_extensions
                        ):
                            event.acceptProposedAction()
                elif drop.is_dir() and self.accept_dir:
                    event.acceptProposedAction()
        elif mime.hasText() and self.accept_text:
            event.acceptProposedAction()

    def dragMoveEvent(self: _HasDNDSignals, _event: QDragMoveEvent) -> None:
        """Handles drag move events (can be extended to accept moving elements)."""
        pass

    def dropEvent(self: _HasDNDSignals, event: QDropEvent) -> None:
        """Handles drop events, emitting the dropped signal with file paths."""
        mime = event.mimeData()
        if mime.hasUrls():
            file_urls = [Path(url.toLocalFile()) for url in mime.urls()]
            self.dropped.emit(file_urls)
        elif mime.hasText() and self.accept_text:
            self.text_dropped.emit(mime.text())

    def set_extensions(self, supported_extensions: Iterable[str]) -> None:
        """Sets the supported file extensions for drag-and-drop."""
        self.supported_extensions = supported_extensions

    def set_accept_dir(self, drop_accepted: bool) -> None:
        """Sets whether directories are accepted during the drag-and-drop."""
        self.accept_dir = drop_accepted

    def set_accept_text(self, accept: bool) -> None:
        """Enables or disables text dropping."""
        self.accept_text = accept


class DNDLineEdit(DNDMixin, QLineEdit):
    dropped = Signal(list)
    text_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None, **kwargs: Any) -> None:
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)


class DNDCodeEditor(DNDMixin, CodeEditor):
    dropped = Signal(list)
    text_dropped = Signal(str)

    def __init__(
        self,
        line_numbers: bool = True,
        wrap_text: bool = False,
        mono_font: bool = True,
        pop_out_expansion: bool = False,
        pop_out_name: str = "Editor",
        pop_out_geometry: QRect | None = None,
        parent: QWidget | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            line_numbers=line_numbers,
            wrap_text=wrap_text,
            mono_font=mono_font,
            pop_out_expansion=pop_out_expansion,
            pop_out_name=pop_out_name,
            pop_out_geometry=pop_out_geometry,
            parent=parent,
            **kwargs,
        )
        self.setAcceptDrops(True)


class DNDButton(DNDMixin, QPushButton):
    dropped = Signal(list)
    text_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None, **kwargs: Any) -> None:
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)


class DNDToolButton(DNDMixin, QToolButton):
    dropped = Signal(list)
    text_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None, **kwargs: Any) -> None:
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)


class DNDThumbnailListWidget(DNDMixin, ThumbnailListWidget):
    dropped = Signal(list)
    text_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None, **kwargs: Any) -> None:
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)
