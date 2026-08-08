"""Shared pytest fixtures/config for the whole suite.

Sets the Qt platform plugin to "offscreen" before Qt is ever imported so the
suite is safe to run on a headless CI runner (no X server/display required).
Provides one shared ``QApplication`` for the whole test session. Qt permits
only one application instance per process, and all widget tests can reuse it.
"""

import os

# must be set before any PySide6/Qt import happens, anywhere in the test
# session, so use setdefault to respect an explicit override (e.g. a
# developer running with a real display) while still defaulting to
# offscreen for CI/headless runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QDialog
import pytest

from src.backend.utils.example_parsed_movie_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as MOVIE_EXAMPLE_PAYLOAD,
)
from src.backend.utils.example_parsed_series_data import (
    EXAMPLE_MEDIA_INPUT_PAYLOAD as SERIES_EXAMPLE_PAYLOAD,
)


@pytest.fixture(scope="session", autouse=True)
def qapp() -> QApplication | QCoreApplication:
    """Create one QApplication for all tests that construct QWidgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _no_blocking_modals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn an accidentally-opened modal into a failure instead of a hang.

    ``QDialog.exec()`` and ``QMenu.exec()`` start a nested event loop and do
    not return until something closes them. In a test there is nobody to
    close them, so reaching one is not a test that fails -- it is a run that
    stops dead, producing no output and naming no culprit. That is not
    hypothetical: when the job rename prompt moved off
    ``QInputDialog.getText()`` to a hand-built dialog, the tests stubbing the
    old call sailed straight into a modal that never closed, and the suite
    simply stopped part-way through with a pegged CPU.

    Patching ``QDialog`` covers ``QMessageBox``, ``QInputDialog``,
    ``QFileDialog``, ``QWizard`` and the rest: none of them define their own
    ``exec``, so this is the one they all resolve to.

    ``QMenu.exec`` is deliberately *not* patched, and cannot usefully be.
    PySide6 exposes it as a ``staticmethod`` (it has a static overload), and
    instance lookup on ``menu.exec`` returns the built-in straight off the C++
    type without ever consulting the class attribute -- so a patch here would
    look like it applied while a populated ``QMenu.exec()`` went on blocking
    exactly as before. That case is left to the ``timeout`` in
    ``pyproject.toml``, which does not care how the call blocks.

    A test that means to reach one of these stubs it deliberately, patching
    ``QDialog.exec`` -- the class the method actually lives on -- with the
    answer it wants. Doing that overrides this guard for that test, and
    restores it afterwards.
    """

    def refuse(self: object, *_args: object, **_kwargs: object) -> int:
        raise AssertionError(
            f"{type(self).__name__}.exec() opened a real modal dialog, which "
            "would block this test forever -- there is no user to dismiss it. "
            "Stub the prompt instead: patch `QDialog.exec` (and whatever "
            "supplies its result, e.g. `textValue`) with the answer this test "
            "needs."
        )

    monkeypatch.setattr(QDialog, "exec", refuse)


@pytest.fixture(autouse=True)
def _clear_example_payload_analysis_caches() -> None:
    """Reset the shared example payloads' derived-value caches.

    Both example payloads are module-level singletons in production code,
    imported by several test files. Their ``analysis_cache`` would otherwise
    carry values from one test into the next.
    """
    MOVIE_EXAMPLE_PAYLOAD.analysis_cache.clear()
    SERIES_EXAMPLE_PAYLOAD.analysis_cache.clear()
