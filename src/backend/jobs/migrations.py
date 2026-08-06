"""Job schema migrations, applied as a chain of single-version hops.

This mirrors `src/config/migrations.py`: each entry in `MIGRATIONS` is keyed
by the schema version it accepts and produces the next version up, so a job
saved several releases ago is walked through every intermediate step rather
than being rejected.

When does a bump warrant a migration?
-------------------------------------
Every `JOB_SCHEMA_VERSION` bump needs a matching `MIGRATIONS` entry --
`check_migration_chain` runs at import and refuses to let the module load
otherwise. The prior question is whether the bump is warranted at all:

- Renamed, moved, or retyped keys **do** need a bump. Nothing else can map
  the old layout onto the new one.
- Added keys **do not**. The decoder reads keys by name and falls back to
  each payload field's own default when a key is absent, so an older job
  simply keeps the default for anything it predates.
- Removed keys **do not**. The decoder only reads keys it knows about; a
  stale key sits unread in the job file.

Bumping for an added or removed key costs users their saved jobs for no
benefit, so prefer leaving the version alone and letting the decoder's
defaults absorb the change.

This module is deliberately kept free of any Qt/UI imports so it can be unit
tested without launching the application.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

JOB_SCHEMA_VERSION = 1

# a migration accepts a document and returns the next version's document.
MigrationFn = Callable[[Mapping[str, Any]], "dict[str, Any]"]

MIGRATIONS: dict[int, MigrationFn] = {}


class JobMigrationError(Exception):
    """A saved job cannot be brought up to the current schema version."""


def check_migration_chain() -> None:
    """Fail at import when a schema bump has no migration to go with it."""
    missing = [
        version for version in range(1, JOB_SCHEMA_VERSION) if version not in MIGRATIONS
    ]
    if missing:
        raise RuntimeError(
            "Job schema migrations are incomplete; no migration registered for "
            f"version(s): {', '.join(str(version) for version in missing)}"
        )


def document_version(document: Mapping[str, Any]) -> int:
    """Report the schema version a job document declares."""
    raw_version = document.get("schema_version")
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise JobMigrationError(
            "Job file is missing a usable 'schema_version' and cannot be read"
        )
    return raw_version


def migrate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Walk a job document up to `JOB_SCHEMA_VERSION`."""
    version = document_version(document)
    if version > JOB_SCHEMA_VERSION:
        raise JobMigrationError(
            f"Job was saved by a newer version of NfoForge (job schema "
            f"{version}, this build reads {JOB_SCHEMA_VERSION}). Update "
            "NfoForge to open it."
        )

    migrated = dict(document)
    while version < JOB_SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise JobMigrationError(
                f"No migration registered to upgrade a job from schema {version}"
            )
        migrated = migration(migrated)
        version += 1
        migrated["schema_version"] = version
    return migrated


check_migration_chain()
