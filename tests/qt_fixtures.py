"""The suite's Qt fixtures, used only when Qt is installed.

`tests/conftest.py` pulls these in when PySide6 is importable. Qt is the
optional `gui` extra, and the rest of the suite runs without it -- which is
the point of making it optional -- so nothing Qt may be imported from the
conftest itself.
"""

from collections.abc import Iterator

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QDialog
import pytest

from nfoforge.frontend.global_signals import GlobalSignals


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
def _fresh_global_signals() -> Iterator[None]:
    """Give every test its own `GlobalSignals`, so listeners cannot pile up.

    The singleton lives for the whole process, and every settings page
    connects itself to it in ``__init__`` without ever disconnecting. Widgets
    a test builds are seldom destroyed, so each one kept listening for the
    rest of the session.

    That turns into a timeout rather than a wrong answer.
    ``global_management_state_changed`` makes `SeriesManagement` and
    `MoviesManagement` re-render their examples, and each render runs
    ``guessit`` over a filename. By the end of the frontend suite the signal
    had 33 listeners and one emit took about three seconds. A test that only
    pumps the event queue then pays for all of them, which is what pushed
    ``test_wizard.py`` past the 60 second limit on CI while passing in
    isolation.

    Replacing the instance rather than disconnecting its signals one by one
    keeps this to the one line a new signal cannot forget to update. Widgets
    from an earlier test stay attached to the instance they were built with,
    which nothing emits on again.
    """
    yield
    GlobalSignals._instance = None  # pyright: ignore[reportPrivateUsage]
