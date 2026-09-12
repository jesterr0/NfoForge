"""What the user is told once the migration has run.

The only account they get, and the last time any of it is mentioned: nothing here
recurs on a later launch. So anything needing a decision has to be in it, and it
has to say that nothing will be rechecked -- otherwise a leftover folder waits
forever for a prompt that is never coming.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from src.config.layout_apply import Diversion, MigrationOutcome
from src.config.layout_migration import (
    ActionKind,
    Finding,
    FindingKind,
    MigrationPlan,
    PlannedAction,
)
import src.frontend.windows.migration_summary_dialog as summary_module
from src.frontend.windows.migration_summary_dialog import MigrationSummaryDialog


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    return tmp_path / "user_data"


@pytest.fixture
def legacy_root(tmp_path: Path) -> Path:
    return tmp_path / "previous install"


@pytest.fixture
def plan(state_root: Path, legacy_root: Path) -> MigrationPlan:
    return MigrationPlan(
        actions=(
            PlannedAction(
                kind=ActionKind.MOVE,
                source=state_root / "jobs",
                destination=state_root / "workspace" / "jobs",
                size=2048,
            ),
            PlannedAction(
                kind=ActionKind.COPY,
                source=legacy_root / "bundle" / "runtime" / "templates",
                destination=state_root / "templates",
                size=4096,
            ),
        ),
        state_root=state_root,
        legacy_root=legacy_root,
        findings=(
            Finding(
                kind=FindingKind.UNRECOGNISED_ENTRY,
                path=state_root / "notes",
                size=512,
            ),
        ),
    )


def _dialog(
    plan: MigrationPlan, outcome: MigrationOutcome
) -> Iterator[MigrationSummaryDialog]:
    widget = MigrationSummaryDialog(plan, outcome, parent=None)
    yield widget
    widget.deleteLater()


@pytest.fixture
def dialog(plan: MigrationPlan) -> Iterator[MigrationSummaryDialog]:
    yield from _dialog(plan, MigrationOutcome())


def test_it_says_where_the_data_now_lives(
    dialog: MigrationSummaryDialog, state_root: Path
) -> None:
    """The first thing anyone wants, and the thing that changed."""
    assert str(state_root) in dialog.summary_text()


def test_it_says_the_previous_installation_is_untouched(
    dialog: MigrationSummaryDialog, legacy_root: Path
) -> None:
    """Nothing was taken out of it, and deleting it is the user's call.

    They are the only one who can judge whether it holds anything else, so the
    summary says it is intact and asks them to review it rather than offering to
    remove it.
    """
    body = dialog.summary_text()

    assert str(legacy_root) in body
    assert "review" in body.lower()


def test_it_says_nothing_will_be_checked_again(
    dialog: MigrationSummaryDialog,
) -> None:
    """Without this, a leftover folder waits forever for a prompt never coming.

    The migration is offered once. Anything reported here that the user chooses
    to deal with later is theirs to remember, so the summary has to be explicit
    that it will not be raised again.
    """
    assert (
        "none of these locations will be checked again" in dialog.summary_text().lower()
    )


def test_it_reports_what_moved_and_what_was_copied(
    dialog: MigrationSummaryDialog, state_root: Path
) -> None:
    assert str(state_root / "workspace" / "jobs") in dialog.summary_text()
    assert str(state_root / "templates") in dialog.summary_text()


def test_it_reports_leftovers_for_review(
    dialog: MigrationSummaryDialog, state_root: Path
) -> None:
    assert str(state_root / "notes") in dialog.summary_text()


def test_it_warns_when_a_setting_still_points_inside_the_old_folder(
    plan: MigrationPlan, legacy_root: Path
) -> None:
    """This is the one finding with a consequence the user cannot see coming.

    They are being told the old folder can be deleted. A setting still pointing
    inside it keeps working until they act on that, and then fails for reasons
    that look unrelated.
    """
    plan = MigrationPlan(
        actions=plan.actions,
        state_root=plan.state_root,
        legacy_root=legacy_root,
        findings=(
            Finding(
                kind=FindingKind.PATH_INSIDE_LEGACY_INSTALL,
                path=legacy_root / "extras" / "thing.exe",
                detail="main: dependency other",
            ),
        ),
    )
    widget = MigrationSummaryDialog(plan, MigrationOutcome(), parent=None)
    try:
        body = widget.summary_text()
    finally:
        widget.deleteLater()

    assert "emptying" in body.lower()
    assert "main: dependency other" in body


def test_it_reports_settings_it_repointed(plan: MigrationPlan) -> None:
    """Changing a user's settings silently is not acceptable, even when correct."""
    outcome = MigrationOutcome(rewritten=("main: working directory",))
    widget = MigrationSummaryDialog(plan, outcome, parent=None)
    try:
        body = widget.summary_text()
    finally:
        widget.deleteLater()

    assert "main: working directory" in body


def test_it_reports_anything_that_could_not_go_where_planned(
    plan: MigrationPlan, state_root: Path
) -> None:
    """A diverted copy is the one outcome that needs the user to do something."""
    conflicts = state_root / "migration-conflicts" / "templates"
    outcome = MigrationOutcome(
        diverted=(Diversion(planned=state_root / "templates", actual=conflicts),)
    )
    widget = MigrationSummaryDialog(plan, outcome, parent=None)
    try:
        body = widget.summary_text()
        assert str(conflicts) in body
        assert widget.conflicts_button.isEnabled()
    finally:
        widget.deleteLater()


def test_the_conflicts_button_is_absent_when_nothing_collided(
    dialog: MigrationSummaryDialog,
) -> None:
    """The usual case, and an enabled button leading nowhere invites worry."""
    assert not dialog.conflicts_button.isEnabled()


def test_opening_the_data_folder_opens_where_the_data_is(
    dialog: MigrationSummaryDialog, state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(summary_module, "open_explorer", opened.append)

    dialog.open_button.click()

    assert opened == [state_root]
