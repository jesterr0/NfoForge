"""The record that decides whether a user is asked to migrate at all.

Getting this wrong is what turns a one-time prompt into one that appears on
every release, or worse, re-runs a migration against a tree that has already
had it.
"""

import json
from pathlib import Path

import pytest

from src.config.layout_version import (
    CURRENT_LAYOUT_VERSION,
    LEGACY_LAYOUT_VERSION,
    LayoutRecordError,
    pending_hops,
    read_layout_version,
    write_layout_version,
)


def test_a_data_directory_with_no_record_is_the_legacy_layout(tmp_path: Path) -> None:
    """Absent means legacy, not broken and not migrated.

    Every installation predating this work has no record, so its absence is the
    normal starting state rather than an error. It is also the only condition
    under which the first hop is allowed to run.
    """
    assert read_layout_version(tmp_path / "user_data") == LEGACY_LAYOUT_VERSION


def test_a_written_record_reads_back(tmp_path: Path) -> None:
    """The version is written after each hop, so it has to survive the trip.

    Written per hop rather than once at the end, so a run interrupted part way
    resumes from where it stopped instead of starting the chain again against a
    tree that is already half moved.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()

    write_layout_version(state_root, 1)

    assert read_layout_version(state_root) == 1


def test_the_record_is_created_with_its_directory_if_needed(tmp_path: Path) -> None:
    """A fresh installation writes its version before anything else exists."""
    state_root = tmp_path / "user_data"

    write_layout_version(state_root, 1)

    assert read_layout_version(state_root) == 1


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not json at all", "malformed"),
        ('{"something_else": 1}', "missing the version"),
        ('{"layout_version": "one"}', "a version that is not a number"),
        ('{"layout_version": null}', "a null version"),
    ],
)
def test_an_unusable_record_is_refused_rather_than_read_as_legacy(
    tmp_path: Path, content: str, reason: str
) -> None:
    """Present but unusable is not the same as absent, and must not be treated so.

    Absent means legacy, which permits the first hop to run. A record that
    exists but cannot be read says nothing about whether the tree has already
    been migrated, so reading it as legacy would invite running the chain a
    second time against a tree that has had it. Refusing lets the caller stop
    and say so, which is the only safe response to not knowing.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    (state_root / "layout.json").write_text(content, encoding="utf-8")

    with pytest.raises(LayoutRecordError):
        read_layout_version(state_root)


def test_a_version_from_a_newer_build_is_returned_not_refused(tmp_path: Path) -> None:
    """Reading it is how the caller finds out it must not migrate.

    A newer layout than this build understands is a valid record written by a
    newer release, so it is read and returned. Deciding to abort on it belongs
    to the caller, which is also the thing that can report it; migrating
    backwards is what must never happen.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    write_layout_version(state_root, CURRENT_LAYOUT_VERSION + 5)

    assert read_layout_version(state_root) == CURRENT_LAYOUT_VERSION + 5


def test_a_record_that_cannot_be_written_fails_loudly(tmp_path: Path) -> None:
    """Silence here is what turns one prompt into a prompt on every launch.

    If the version cannot be stored, the migration that just ran leaves no
    trace of having run, and the next launch offers to do it again.
    """
    blocked = tmp_path / "user_data"
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(LayoutRecordError):
        write_layout_version(blocked, 1)


def test_a_legacy_tree_runs_every_hop_in_order(tmp_path: Path) -> None:
    """Someone who skipped releases is carried up the chain, not across it.

    Hops are keyed by the version they accept, so arriving from legacy means
    running each in turn rather than jumping to the newest.
    """
    assert pending_hops(LEGACY_LAYOUT_VERSION) == tuple(
        range(1, CURRENT_LAYOUT_VERSION + 1)
    )


def test_a_current_tree_has_nothing_to_do(tmp_path: Path) -> None:
    """The silent case, and the one almost every launch takes."""
    assert pending_hops(CURRENT_LAYOUT_VERSION) == ()


def test_a_newer_tree_is_never_migrated_backwards(tmp_path: Path) -> None:
    """A newer layout is left entirely alone.

    Downgrading someone's data directory to suit an older build is worse than
    refusing to run: the newer release is the one that knows what its own
    layout means.
    """
    assert pending_hops(CURRENT_LAYOUT_VERSION + 5) == ()


def test_a_record_keeps_what_earlier_writes_put_there(tmp_path: Path) -> None:
    """One file holds the whole audit trail, written by more than one step.

    A hop records what it moved, the user's refusal of an import is recorded
    separately, and a later hop writes again. Each write has to leave the
    others alone, or the trail only ever shows the last thing that happened.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()

    write_layout_version(state_root, 1, record={"import_declined": True})
    write_layout_version(state_root, 1, record={"migrated_at": "2026-01-01T00:00:00"})

    document = json.loads((state_root / "layout.json").read_text(encoding="utf-8"))
    assert document["import_declined"] is True
    assert document["migrated_at"] == "2026-01-01T00:00:00"
    assert document["layout_version"] == 1


def test_an_unreadable_record_is_not_overwritten(tmp_path: Path) -> None:
    """Clobbering it would destroy the only account of what already happened.

    The trail is what tells a user, or whoever is helping them, which entries
    were moved and which collided. Replacing a damaged one with a fresh empty
    one loses that outright, so the write refuses too.
    """
    state_root = tmp_path / "user_data"
    state_root.mkdir()
    damaged = state_root / "layout.json"
    damaged.write_text('{"layout_version": 1, "moved": [ ...', encoding="utf-8")

    with pytest.raises(LayoutRecordError):
        write_layout_version(state_root, 1, record={"migrated_at": "now"})

    assert damaged.read_text(encoding="utf-8").startswith('{"layout_version": 1')
