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

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qapp() -> QApplication | QCoreApplication:
    """Create one QApplication for all tests that construct QWidgets."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
