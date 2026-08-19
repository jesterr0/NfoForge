from types import SimpleNamespace
from typing import Any

from PySide6.QtWidgets import QDialog, QWizard, QWizardPage
import pytest

from src.enums.wizard import WizardPages
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


def test_the_jobs_button_tooltip_explains_what_it_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The "Jobs" button repurposes the wizard's unused HelpButton slot (see
    the comment above it in production), so nothing about its label says
    what it does -- the tooltip is the only explanation the user gets. Pinned
    so a rename silently reverting the wording, as already happened once on
    this branch, is caught here.

    Page construction and processing-context setup are heavy and unrelated
    to the button itself, so they are stubbed to let a real
    `MainWindowWizard` come up far enough to build its buttons.
    """
    monkeypatch.setattr(
        wizard_module,
        "create_processing_context",
        lambda *_a, **_k: SimpleNamespace(),
    )
    monkeypatch.setattr(MainWindowWizard, "_generate_new_pages", lambda self: [])
    monkeypatch.setattr(MainWindowWizard, "_insert_plugin_page", lambda self: None)
    monkeypatch.setattr(MainWindowWizard, "_build_wizard_pages", lambda self: None)
    monkeypatch.setattr(MainWindowWizard, "_set_start_page", lambda self: None)
    config = SimpleNamespace(
        settings=SimpleNamespace(), plugin_manager=SimpleNamespace()
    )

    wizard = MainWindowWizard(config, None)  # pyright: ignore[reportArgumentType]

    assert wizard.load_job_button.toolTip() == (
        "Browse saved jobs: load one to process it, or queue several"
    )


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


def _wizard_for_start_page(
    *, enable_plugins: bool, wizard_page: str | None, plugin_found: object | None
) -> QWizard:
    wizard = QWizard()
    for page_id in range(1, WizardPages.PROCESS_PAGE.value + 1):
        wizard.setPage(page_id, QWizardPage())
    wizard.config = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        settings=SimpleNamespace(
            general=SimpleNamespace(enable_plugins=enable_plugins),
            plugins=SimpleNamespace(wizard_page=wizard_page),
        ),
        plugin_manager=SimpleNamespace(get=lambda _name: plugin_found),
    )
    return wizard


@pytest.mark.parametrize(
    ("enable_plugins", "wizard_page", "plugin_found"),
    [
        (False, None, None),
        (True, None, None),
        (True, "a-plugin", None),
    ],
)
def test_start_over_never_inherits_a_resumed_job_start_page(
    enable_plugins: bool, wizard_page: str | None, plugin_found: object | None
) -> None:
    """`setStartId` is sticky, so not setting it is not the same as a default.

    `_resume_job` moves the start page to wherever the job picks up. Leaving
    it alone here -- which plugins being enabled with no usable wizard page
    used to do -- meant the next Start Over opened a brand new run on the
    *resumed* job's page, with a context that has nothing in it. The wizard
    only recovered when the app was restarted.
    """
    wizard = _wizard_for_start_page(
        enable_plugins=enable_plugins,
        wizard_page=wizard_page,
        plugin_found=plugin_found,
    )
    wizard.setStartId(WizardPages.TRACKERS_PAGE.value)  # a resumed job's page

    MainWindowWizard._set_start_page(wizard)  # pyright: ignore[reportArgumentType]

    assert wizard.startId() == WizardPages.INPUT_PAGE.value


def test_a_configured_plugin_page_is_still_where_a_fresh_run_starts() -> None:
    wizard = _wizard_for_start_page(
        enable_plugins=True, wizard_page="a-plugin", plugin_found=object()
    )
    wizard.setStartId(WizardPages.TRACKERS_PAGE.value)

    MainWindowWizard._set_start_page(wizard)  # pyright: ignore[reportArgumentType]

    assert wizard.startId() == WizardPages.PLUGIN_INPUT_PAGE.value


class _TeardownPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.torn_down = False

    def teardown(self) -> None:
        self.torn_down = True


def test_removing_pages_lets_each_one_hand_back_what_outlives_it() -> None:
    """`deleteLater()` schedules a delete; it does not perform one.

    A page subscribed to the global signal bus keeps answering it until it is
    really destroyed, and nothing in the rebuild waits for that. Pages get a
    say before they are dropped so anything order-sensitive can be released
    now rather than whenever the event loop gets to it.
    """
    wizard = QWizard()
    pages = [_TeardownPage(), _TeardownPage()]
    for page_id, page in enumerate(pages, start=1):
        wizard.setPage(page_id, page)

    MainWindowWizard._remove_all_pages(wizard)  # pyright: ignore[reportArgumentType]

    assert all(page.torn_down for page in pages)


def test_a_page_without_a_teardown_is_still_removed() -> None:
    """`_remove_all_pages` also runs against plugin-supplied pages."""
    wizard = QWizard()
    wizard.setPage(1, QWizardPage())

    MainWindowWizard._remove_all_pages(wizard)  # pyright: ignore[reportArgumentType]

    assert wizard.pageIds() == []
