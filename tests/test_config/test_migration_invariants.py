"""Invariants that must hold for the migration chain itself.

These guard the failure mode where `TomlConfigCodec.SCHEMA_VERSION` is bumped
without a corresponding migration being written -- which silently turns every
existing user profile into an "unsupported schema" error at startup, with no
recovery path other than archive+regenerate.
"""

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

import pytest
import tomlkit

from src.config.codec import TomlConfigCodec
from src.config.migrations import (
    MIGRATIONS,
    SCHEMA_1_VERSION,
    check_migration_chain,
    document_version,
    migrate_document,
)
from tests.repo_paths import DEFAULT_CONFIG_TOML

FIXTURES = Path(__file__).parent / "fixtures"


def _noop(
    old_doc: Mapping[str, Any],
    default_document: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    return dict(old_doc), []


def _load_fixture(name: str) -> tomlkit.TOMLDocument:
    return tomlkit.parse((FIXTURES / name).read_text(encoding="utf-8"))


def test_registry_covers_every_version_below_current_schema() -> None:
    """The registry must hold exactly one hop per version gap: a migration
    keyed `n` takes a schema-`n` document to schema-`n+1`, so the keys must be
    `SCHEMA_1_VERSION .. SCHEMA_VERSION - 1` with no gaps and nothing past the
    current version."""
    assert set(MIGRATIONS) == set(
        range(SCHEMA_1_VERSION, TomlConfigCodec.SCHEMA_VERSION)
    )


def test_check_migration_chain_accepts_the_real_registry() -> None:
    check_migration_chain(MIGRATIONS, TomlConfigCodec.SCHEMA_VERSION)


def test_check_migration_chain_rejects_a_missing_terminal_hop() -> None:
    """The exact regression: SCHEMA_VERSION bumped to 3, but the registry
    still only knows how to reach 2."""
    with pytest.raises(RuntimeError, match=r"no migration is registered.*\[2\]"):
        check_migration_chain({1: _noop}, 3)


def test_check_migration_chain_rejects_a_gap() -> None:
    with pytest.raises(RuntimeError, match=r"no migration is registered.*\[2\]"):
        check_migration_chain({1: _noop, 3: _noop}, 4)


def test_check_migration_chain_rejects_a_hop_past_the_current_schema() -> None:
    """A migration keyed at or above SCHEMA_VERSION would produce a document
    newer than the app supports."""
    with pytest.raises(RuntimeError, match="beyond"):
        check_migration_chain({1: _noop, 2: _noop}, 2)


def test_document_version_treats_a_missing_field_as_schema_1() -> None:
    assert document_version({}) == SCHEMA_1_VERSION
    assert document_version({"schema_version": 2}) == 2


def test_migrate_document_chains_schema_1_to_the_current_version() -> None:
    """Version-agnostic on purpose: this must keep passing after every future
    bump, which is only possible if a migration was added alongside it."""
    old = _load_fixture("schema1_config.toml")

    new, unmapped = migrate_document(old)

    assert new["schema_version"] == TomlConfigCodec.SCHEMA_VERSION
    assert not unmapped


def test_migrate_document_is_a_no_op_for_a_current_version_document() -> None:
    current = {"schema_version": TomlConfigCodec.SCHEMA_VERSION, "general": {}}

    new, unmapped = migrate_document(current)

    assert new["schema_version"] == TomlConfigCodec.SCHEMA_VERSION
    assert not unmapped


def _version_fixtures() -> list[Path]:
    return sorted(FIXTURES.glob("schema*_config.toml"))


def _fixture_version(fixture: Path) -> int:
    match = re.fullmatch(r"schema(\d+)_config", fixture.stem)
    assert match, f"unexpected fixture name: {fixture.name}"
    return int(match.group(1))


def test_a_fixture_exists_for_every_migratable_schema_version() -> None:
    """Each bump must land a fixture for the version being migrated away
    from, otherwise the round-trip test below silently stops covering it and
    the chain is only verified by its version numbers."""
    present = {_fixture_version(fixture) for fixture in _version_fixtures()}
    required = set(range(SCHEMA_1_VERSION, TomlConfigCodec.SCHEMA_VERSION))

    assert required <= present, (
        f"missing config fixture(s) for schema version(s) {sorted(required - present)}"
    )


@pytest.mark.parametrize(
    "fixture", _version_fixtures(), ids=lambda fixture: fixture.stem
)
def test_every_version_fixture_migrates_to_the_current_schema(fixture: Path) -> None:
    """A real config at each historical version must survive the full chain.

    This is what keeps the chain honest: the registry can look complete by
    its keys alone while a hop still mangles a document it is handed.
    """
    old = tomlkit.parse(fixture.read_text(encoding="utf-8"))

    new, unmapped = migrate_document(old)

    assert not unmapped
    assert new["schema_version"] == TomlConfigCodec.SCHEMA_VERSION


def test_packaged_default_declares_the_current_schema_version() -> None:
    """`default_config.toml` and `codec.SCHEMA_VERSION` are edited by hand in
    two separate files; nothing else ties them together."""
    document = tomlkit.parse(DEFAULT_CONFIG_TOML.read_text(encoding="utf-8"))

    assert document["schema_version"] == TomlConfigCodec.SCHEMA_VERSION
