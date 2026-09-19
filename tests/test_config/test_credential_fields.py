"""Every credential a profile can hold is one this build knows to strip.

`blank_credentials` works by name, which is what lets it cover a tracker table
it has never been told about -- and what lets it miss one. A tracker added later
with a field called `auth_secret` would export in full, and there is no way to
notice that after the fact: the bundle is already wherever the user sent it.

So this asserts that every field of every tracker, torrent-client and image-host
payload is *classified* -- either a credential, or deliberately listed below as
not one. A new field fails this test until somebody decides which it is.
"""

import dataclasses
import importlib
from pathlib import Path
from typing import Any

import pytest

import src.payloads.clients as clients
import src.payloads.image_hosts as image_hosts
import src.payloads.trackers as trackers
from src.utils.secret_redaction import CREDENTIAL_FIELD_NAMES

KNOWN_NON_CREDENTIAL_FIELDS = frozenset(
    {
        # What is uploaded, and how it is described
        "add_localization_to_custom_edition",
        "anonymous",
        "comments",
        "draft_queue_opt_in",
        "internal",
        "live_release",
        "mod_queue_opt_in",
        "nfo_template",
        "opt_in_to_mod_queue",
        "personal_release",
        "promo",
        "source",
        "stream_optimized",
        "upload_enabled",
        # Staff and internal flags
        "double_up",
        "featured",
        "free",
        "sticky",
        # Screenshot and URL layout
        "column_s",
        "column_space",
        "image_width",
        "row_space",
        "url_type",
        # Where a service lives, which is public
        "base_url",
        "host",
        "port",
        "verify_tls",
        "ca_bundle",
        # Torrent client bookkeeping
        "auth_mode",
        "category",
        "label",
        "path",
        "save_path_mode",
        "save_path_overrides",
        "save_path_template",
        "super_seeding",
        # Identity of a configured entry, not of a person
        "enabled",
        "instance_id",
    }
)
"""Payload fields that are settings rather than secrets.

Listed one by one rather than derived, because the whole value of this test is
that a field has to be looked at by a person before it can leave the machine.
"""


def _payload_classes() -> tuple[type[Any], ...]:
    modules = [trackers, clients]
    for module_path in Path(image_hosts.__file__).parent.glob("*.py"):
        if module_path.stem != "__init__":
            modules.append(
                importlib.import_module(f"src.payloads.image_hosts.{module_path.stem}")
            )

    found: list[type[Any]] = []
    for module in modules:
        for candidate in vars(module).values():
            if (
                isinstance(candidate, type)
                and dataclasses.is_dataclass(candidate)
                and candidate.__module__ == module.__name__
            ):
                found.append(candidate)
    return tuple(found)


def _unclassified(classes: tuple[type[Any], ...]) -> set[str]:
    names = {field.name for cls in classes for field in dataclasses.fields(cls)}
    return {
        name
        for name in names
        if name.casefold() not in CREDENTIAL_FIELD_NAMES
        and name not in KNOWN_NON_CREDENTIAL_FIELDS
    }


def test_every_payload_field_is_either_a_credential_or_declared_not_to_be() -> None:
    unclassified = _unclassified(_payload_classes())
    assert not unclassified, (
        "These payload fields are neither in CREDENTIAL_FIELD_NAMES nor in "
        "KNOWN_NON_CREDENTIAL_FIELDS, so exporting a configuration would carry "
        f"them off the machine without anyone having decided that is right: "
        f"{sorted(unclassified)}"
    )


def test_the_classification_is_found_to_be_missing_when_it_is() -> None:
    """The lock above is only worth having if it can fail."""

    @dataclasses.dataclass(slots=True)
    class _FutureTracker:
        auth_secret: str = ""

    assert _unclassified((_FutureTracker,)) == {"auth_secret"}


def test_the_names_the_logger_scrubs_are_all_stripped_from_an_export() -> None:
    """Exporting asks a wider question than logging, never a narrower one."""
    from src.utils.secret_redaction import _SECRET_FIELD_NAMES

    assert _SECRET_FIELD_NAMES <= CREDENTIAL_FIELD_NAMES


@pytest.mark.parametrize(
    "name", ("announce_url", "api_key", "password", "totp", "username")
)
def test_the_obvious_credentials_are_covered(name: str) -> None:
    assert name in CREDENTIAL_FIELD_NAMES
