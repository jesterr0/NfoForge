"""The shape of the progress and error reporters the backend calls.

The backend reports by calling `.emit(...)` on an object its caller hands in.
The desktop application hands in a Qt `SignalInstance`, which carries the
update across into the UI thread; anything else only needs a matching `emit`.
These protocols describe that shape without importing Qt, so a Qt signal and a
plain object both satisfy them.
"""

from typing import Protocol


class ErrorSignal(Protocol):
    """Reports an error the run survives."""

    def emit(self, message: str, /) -> None: ...


class ProgressSignal(Protocol):
    """Reports what a step is doing and how far through it is, in percent."""

    def emit(self, message: str, progress: float, /) -> None: ...


class FileProgressSignal(Protocol):
    """Reports progress over a known number of files."""

    def emit(self, percent: int, completed: int, total: int, /) -> None: ...
