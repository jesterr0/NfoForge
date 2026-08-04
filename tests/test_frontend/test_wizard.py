from PySide6.QtWidgets import QWizard, QWizardPage

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
