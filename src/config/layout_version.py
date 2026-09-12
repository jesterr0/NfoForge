"""Which directory layout a data directory is in, and the record saying so.

The counterpart to `src/config/layout_migration.py`, which works out what a
migration would do without doing any of it. This module owns `layout.json`: the
one file that decides whether a user is asked to migrate, and the only thing
written before a migration runs.

It is a file of its own rather than a key in the program configuration because
layout migration runs before configuration loading. Storing the version inside
the configuration would mean parsing configuration to find out where
configuration lives.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

LAYOUT_RECORD_NAME = "layout.json"

LEGACY_LAYOUT_VERSION = 0
"""What a data directory with no record is.

Absent means legacy rather than broken or migrated: every installation
predating this work has no record, so its absence is the ordinary starting
state.
"""

CURRENT_LAYOUT_VERSION = 1
"""The layout this build produces and understands.

Raised by one for each new hop, and never renumbered: a hop is keyed by the
version it accepts, so renumbering silently changes which trees it runs
against. The same discipline `migrations.py` documents for its own schema
chain.
"""


class LayoutRecordError(Exception):
    """The record exists but cannot be understood, so nothing may be assumed."""


def read_layout_version(state_root: Path) -> int:
    """The layout version of `state_root`, or legacy if it has no record.

    Raises `LayoutRecordError` if a record exists but cannot be understood.
    That is deliberately not the same answer as "absent": absent means legacy,
    which permits the first hop to run, while an unreadable record says nothing
    about whether the tree has already been migrated. Reading one as legacy
    would invite running the chain a second time over a tree that has had it.

    A version newer than this build understands is returned rather than
    refused. It is a valid record written by a newer release, and refusing to
    migrate backwards is the caller's decision to make and report.
    """
    record = state_root / LAYOUT_RECORD_NAME
    if not record.is_file():
        return LEGACY_LAYOUT_VERSION
    try:
        document = json.loads(record.read_text(encoding="utf-8"))
        version = document["layout_version"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise LayoutRecordError(f"{record} cannot be read: {error}") from error
    if isinstance(version, bool) or not isinstance(version, int):
        raise LayoutRecordError(
            f"{record} holds a layout version that is not a whole number"
        )
    return version


def write_layout_version(
    state_root: Path, version: int, record: Mapping[str, Any] | None = None
) -> None:
    """Record that `state_root` is now at `version`.

    Failure is not swallowed. Leaving the version behind quietly is what turns a
    migration nobody notices into a prompt on every launch, and worse, invites a
    second run of hops against a tree that has already had them.
    """
    path = state_root / LAYOUT_RECORD_NAME
    document = _existing_document(path)
    document.update(record or {})
    document["layout_version"] = version
    try:
        state_root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        raise LayoutRecordError(f"{path} could not be written: {error}") from error


def _existing_document(path: Path) -> dict[str, Any]:
    """Whatever is already recorded, so a write adds to it rather than replaces.

    One file holds the whole trail and more than one step writes to it: a hop
    records what it moved, a refused import is recorded separately, and a later
    hop writes again. A damaged document is refused rather than replaced,
    because it is the only account of what already happened -- replacing it with
    a fresh empty one loses that outright.
    """
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LayoutRecordError(f"{path} cannot be read: {error}") from error
    if not isinstance(document, dict):
        raise LayoutRecordError(f"{path} does not hold a record")
    return document


def pending_hops(version: int) -> tuple[int, ...]:
    """The hops that carry `version` up to what this build understands.

    Empty for a tree already current, and empty for one newer than this build:
    downgrading someone's data directory to suit an older release is worse than
    refusing to run, because the newer release is the one that knows what its
    own layout means.
    """
    return tuple(range(version + 1, CURRENT_LAYOUT_VERSION + 1))
