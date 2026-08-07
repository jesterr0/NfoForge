from types import SimpleNamespace
from typing import Any

from PySide6.QtWidgets import QDialog, QWizard, QWizardPage
import pytest

import src.frontend.wizards.wizard as wizard_module
from src.frontend.wizards.wizard import MainWindowWizard


class _SpyPage(QWizardPage):
    """QWizardPage subclass that records whether deleteLater() was called,
    without needing to pump the event loop to observe real deletion."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_later_called = False

    def deleteLater(self) -> None:
        self.delete_later_called = True
        super().deleteLater()


def test_remove_all_pages_schedules_deletion_and_detaches_pages() -> None:
    """Regression guard: _remove_all_pages only called removePage(), which
    detaches a page from the wizard but never deletes the widget. Old page
    instances (and their live GSigs connections, e.g. MediaSearch's
    settings_close) stayed parented and connected forever, so every "Start
    Over" accumulated another set of connected pages. _remove_all_pages must
    now call deleteLater() on each removed page.

    _remove_all_pages only touches methods any QWizard provides (pageIds,
    page, removePage), so it can be exercised directly against a bare QWizard
    instead of constructing the full MainWindowWizard (which requires a real
    MainWindow parent and heavier page dependencies).
    """
    wizard = QWizard()
    pages = [_SpyPage(), _SpyPage(), _SpyPage()]
    for idx, page in enumerate(pages, start=1):
        wizard.setPage(idx, page)

    assert wizard.pageIds() == [1, 2, 3]

    MainWindowWizard._remove_all_pages(wizard)

    # pages must be detached from the wizard ...
    assert wizard.pageIds() == []
    # ... and each removed page scheduled for deletion rather than left
    # dangling with live connections.
    assert all(page.delete_later_called for page in pages)


class _FakeLoadJobDialog:
    """Stands in for `LoadJobDialog`, whose own `.exec()` would block on a
    real modal loop. Records `deleteLater()` so a leak -- a parented dialog
    surviving as a hidden child of the wizard -- is observable without
    needing to construct the real dialog's tree, details pane and loader.
    """

    instances: list["_FakeLoadJobDialog"] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.delete_later_called = False
        self.queued_listings: list[Any] = []
        self.selected_listing: Any = None
        self._result = QDialog.DialogCode.Rejected
        _FakeLoadJobDialog.instances.append(self)

    def exec(self) -> int:
        return int(self._result)

    def deleteLater(self) -> None:
        self.delete_later_called = True


@pytest.fixture(autouse=True)
def _reset_fake_dialog_instances() -> None:
    _FakeLoadJobDialog.instances = []


def test_open_load_job_dialog_frees_the_dialog_when_the_user_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parenting `dialog` to the wizard (`LoadJobDialog(..., self)`) makes it
    survive as a hidden child for the wizard's life without `deleteLater()` --
    the same leak `queue_dialog` a few lines below is already guarded against,
    worse here since this dialog carries a listing tree, a details pane and
    one retired `_ListingLoader` per reload.
    """
    wizard = QWizard()
    wizard.config = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        program=SimpleNamespace(current_config="default")
    )
    monkeypatch.setattr(wizard_module, "LoadJobDialog", _FakeLoadJobDialog)

    MainWindowWizard.open_load_job_dialog(wizard)

    assert len(_FakeLoadJobDialog.instances) == 1
    assert _FakeLoadJobDialog.instances[0].delete_later_called is True


def test_open_load_job_dialog_frees_the_dialog_after_accepting_a_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leak is not limited to the cancel path -- every accepted run
    (queue or single job) has to schedule the same cleanup."""
    wizard = QWizard()
    wizard.config = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        program=SimpleNamespace(current_config="default")
    )

    class _AcceptedQueueDialog(_FakeLoadJobDialog):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._result = QDialog.DialogCode.Accepted
            self.queued_listings = [SimpleNamespace(path="does-not-matter")]

    class _FakeQueueDialog:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.delete_later_called = False

        def start(self) -> None: ...
        def exec(self) -> None: ...

        def deleteLater(self) -> None:
            self.delete_later_called = True

    monkeypatch.setattr(wizard_module, "LoadJobDialog", _AcceptedQueueDialog)
    monkeypatch.setattr(wizard_module, "JobQueueDialog", _FakeQueueDialog)

    MainWindowWizard.open_load_job_dialog(wizard)

    assert len(_FakeLoadJobDialog.instances) == 1
    assert _FakeLoadJobDialog.instances[0].delete_later_called is True
