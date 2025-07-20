from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QLineEdit, QPushButton, QToolButton

from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.custom_widgets.image_listbox import ThumbnailListWidget

# T = TypeVar("T", bound=QWidget)


# # TODO: replace this factory with the mixin classes below
# def DNDFactory(base_class: Type[T]) -> Type[T]:
#     """Factory used to create drag and drop widgets as needed"""

#     class DNDWidget(base_class):
#         dropped = Signal(list)

#         def __init__(self, parent=None):
#             super().__init__(parent)
#             self.setAcceptDrops(True)
#             self.supported_extensions = None
#             self.accept_dir = False

#         def dragEnterEvent(self, event):
#             urls = event.mimeData().urls()
#             if urls:
#                 drop = Path(urls[0].toLocalFile())
#                 if drop.is_file() and drop.exists():
#                     if self.supported_extensions:
#                         if (
#                             "*" in self.supported_extensions
#                             or drop.suffix in self.supported_extensions
#                         ):
#                             event.acceptProposedAction()
#                 elif drop.is_dir() and self.accept_dir:
#                     event.acceptProposedAction()

#         def dragMoveEvent(self, event):
#             # We would need to re enable logic if we want to accept moving elements
#             # around widgets.

#             # if event.mimeData().hasUrls():
#             #     event.acceptProposedAction()
#             # else:
#             #     event.ignore()
#             pass

#         def dropEvent(self, event):
#             file_urls = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
#             self.dropped.emit(file_urls)

#         def set_extensions(self, supported_extensions: Iterable):
#             self.supported_extensions = supported_extensions

#         def set_accept_dir(self, drop_accepted: bool):
#             self.accept_dir = drop_accepted

#     return DNDWidget  # pyright: ignore [reportReturnType]


class DNDMixin:
    accept_dir = False
    accept_text = False
    supported_extensions = None
    dropped = Signal(list)
    text_dropped = Signal(str)

    def dragEnterEvent(self, event: QDragEnterEvent):
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

    def dragMoveEvent(self, event: QDragMoveEvent):
        """Handles drag move events (can be extended to accept moving elements)."""
        pass

    def dropEvent(self, event: QDropEvent):
        """Handles drop events, emitting the dropped signal with file paths."""
        mime = event.mimeData()
        if mime.hasUrls():
            file_urls = [Path(url.toLocalFile()) for url in mime.urls()]
            self.dropped.emit(file_urls)  # pyright: ignore [reportAttributeAccessIssue]
        elif mime.hasText() and self.accept_text:
            self.text_dropped.emit(mime.text())  # pyright: ignore [reportAttributeAccessIssue]

    def set_extensions(self, supported_extensions: Iterable):
        """Sets the supported file extensions for drag-and-drop."""
        self.supported_extensions = supported_extensions

    def set_accept_dir(self, drop_accepted: bool):
        """Sets whether directories are accepted during the drag-and-drop."""
        self.accept_dir = drop_accepted

    def set_accept_text(self, accept: bool):
        """Enables or disables text dropping."""
        self.accept_text = accept


class DNDLineEdit(DNDMixin, QLineEdit):  # pyright: ignore [reportIncompatibleMethodOverride]
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)


class DNDCustomLineEdit(DNDMixin, CodeEditor):  # pyright: ignore [reportIncompatibleMethodOverride]
    def __init__(
        self,
        line_numbers: bool = True,
        wrap_text: bool = False,
        mono_font: bool = True,
        parent=None,
        **kwargs,
    ):
        super().__init__(
            line_numbers=line_numbers,
            wrap_text=wrap_text,
            mono_font=mono_font,
            parent=parent,
            **kwargs,
        )
        self.setAcceptDrops(True)


class DNDButton(DNDMixin, QPushButton):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)


class DNDToolButton(DNDMixin, QToolButton):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)


class DNDThumbnailListWidget(DNDMixin, ThumbnailListWidget):  # pyright: ignore [reportIncompatibleMethodOverride]
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.setAcceptDrops(True)
