"""Shared pytest fixtures/config for the whole suite.

Sets the Qt platform plugin to "offscreen" before Qt is ever imported so the
suite is safe to run on a headless CI runner (no X server/display required).
Individual test modules are free to keep constructing their own
``QApplication`` ad hoc (``QApplication.instance() or QApplication([])``);
this module only guarantees the offscreen default and offers a shared
session-scoped fixture for tests that want to adopt it.
"""

import os

# must be set before any PySide6/Qt import happens, anywhere in the test
# session, so use setdefault to respect an explicit override (e.g. a
# developer running with a real display) while still defaulting to
# offscreen for CI/headless runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Shared QApplication instance for tests that construct QWidgets.

    Reuses an existing instance if one is already alive (e.g. created by a
    test module before adopting this fixture) rather than constructing a
    second one, which Qt does not allow.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
