"""Regression tests for the ``ProcessWorker.progress_signal`` emitting path.

``progress_signal`` used to be declared ``Signal(int)``, which silently
truncated the float values ``_progress_cb`` receives (e.g. 12.34 -> 12),
making the two-decimal formatting branch in ``_on_progress_update`` dead
code. ``_progress_cb`` also used to guard with ``if progress:``, which
swallows ``0`` and so never let the receiving slot enter its busy state.

These tests construct a real ``ProcessWorker`` (a ``QThread`` subclass) and
drive ``_progress_cb`` directly without starting the thread, so they exercise
the actual ``Signal`` declaration under test rather than a stand-in.
"""

from unittest.mock import MagicMock

from PySide6.QtCore import QCoreApplication
import pytest

from src.backend.process import ProcessBackEnd
from src.context.processing_context import ProcessingContext
from src.frontend.wizards.process import ProcessWorker


def _process_worker() -> ProcessWorker:
    return ProcessWorker(
        backend=MagicMock(spec=ProcessBackEnd),
        tracker_data={},
        context=ProcessingContext(),
    )


def test_fractional_progress_survives_the_signal(
    qapp: QCoreApplication,
) -> None:
    """`Signal(int)` silently truncated 12.34 to 12, making the two-decimal
    formatting branch in `_on_progress_update` unreachable."""
    worker = _process_worker()
    received: list[float] = []
    worker.progress_signal.connect(received.append)

    worker._progress_cb(12.34)

    assert received == [pytest.approx(12.34)]


def test_zero_progress_is_emitted_so_the_busy_state_can_trigger(
    qapp: QCoreApplication,
) -> None:
    """`if progress:` swallowed 0, so the bar never entered its busy range."""
    worker = _process_worker()
    received: list[float] = []
    worker.progress_signal.connect(received.append)

    worker._progress_cb(0)

    assert received == [0]


def test_none_progress_is_not_emitted(qapp: QCoreApplication) -> None:
    worker = _process_worker()
    received: list[float] = []
    worker.progress_signal.connect(received.append)

    worker._progress_cb(None)  # type: ignore[arg-type]

    assert received == []
