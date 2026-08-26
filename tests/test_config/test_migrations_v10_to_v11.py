"""Schema 11 gives the two Chevereto slots room for more than one site each.

One Chevereto build powers many sites -- ptscreens, and the OnlyImage and
Lensdump entries that only exist as their own hosts because this slot held
exactly one. A profile that had configured a Chevereto site keeps it as an
instance, so nothing a user selected per tracker is lost.
"""

from typing import Any

from src.config.migrations import migrate_v10_to_v11


def _doc(
    image_hosts: dict[str, Any], last_used: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 10,
        "image_hosts": image_hosts,
        "tracker": {
            "settings": {
                "tracker_order": ["Aither"],
                "last_used_img_host": last_used if last_used is not None else {},
            },
            "aither": {"enabled": True, "api_key": "key"},
        },
    }


_UNCONFIGURED = {
    "chevereto_v3": {"enabled": False, "base_url": "", "user": "", "password": ""},
    "chevereto_v4": {"enabled": False, "base_url": "", "api_key": ""},
}


def test_a_configured_v4_site_becomes_an_instance_keyed_one() -> None:
    document, unmapped = migrate_v10_to_v11(
        _doc(
            {
                **_UNCONFIGURED,
                "chevereto_v4": {
                    "enabled": True,
                    "base_url": "https://ptscreens.com/",
                    "api_key": "v4-key",
                },
            }
        ),
        None,
    )

    assert not unmapped
    assert document["schema_version"] == 11
    assert document["image_hosts"]["chevereto_v4"] == {
        "1": {
            "label": "Chevereto v4",
            "enabled": True,
            "base_url": "https://ptscreens.com/",
            "api_key": "v4-key",
        }
    }


def test_a_configured_v3_site_keeps_its_username_and_password() -> None:
    document, _ = migrate_v10_to_v11(
        _doc(
            {
                **_UNCONFIGURED,
                "chevereto_v3": {
                    "enabled": True,
                    "base_url": "https://v3.example.com/",
                    "user": "someone",
                    "password": "hunter2",
                },
            }
        ),
        None,
    )

    assert document["image_hosts"]["chevereto_v3"] == {
        "1": {
            "label": "Chevereto v3",
            "enabled": True,
            "base_url": "https://v3.example.com/",
            "user": "someone",
            "password": "hunter2",
        }
    }


def test_an_untouched_slot_becomes_no_instance_at_all() -> None:
    """An empty instance would show up in the settings list and the
    per-tracker picker as a host the user never configured."""
    document, _ = migrate_v10_to_v11(_doc(dict(_UNCONFIGURED)), None)

    assert document["image_hosts"]["chevereto_v3"] == {}
    assert document["image_hosts"]["chevereto_v4"] == {}


def test_a_slot_enabled_but_blank_still_migrates_so_the_toggle_is_not_lost() -> None:
    document, _ = migrate_v10_to_v11(
        _doc(
            {
                **_UNCONFIGURED,
                "chevereto_v4": {"enabled": True, "base_url": "", "api_key": ""},
            }
        ),
        None,
    )

    assert list(document["image_hosts"]["chevereto_v4"]) == ["1"]


def test_last_used_hosts_are_rewritten_to_the_new_stable_keys() -> None:
    document, _ = migrate_v10_to_v11(
        _doc(
            dict(_UNCONFIGURED),
            {
                "Aither": "Chevereto v4",
                "ReelFliX": "Chevereto v3",
                "HUNO": "Lensdump",
                "LST": "Disabled",
            },
        ),
        None,
    )

    assert document["tracker"]["settings"]["last_used_img_host"] == {
        "Aither": "CHEVERETO_V4:1",
        "ReelFliX": "CHEVERETO_V3:1",
        "HUNO": "LENSDUMP",
        "LST": "DISABLED",
    }


def test_an_unrecognised_last_used_value_is_carried_forward_untouched() -> None:
    """`ImageSource.URLS` is a legitimate destination this remap does not
    cover, and a value from a future build must not be silently dropped."""
    document, _ = migrate_v10_to_v11(
        _doc(dict(_UNCONFIGURED), {"Aither": "URLs", "HUNO": "SomethingElse"}),
        None,
    )

    assert document["tracker"]["settings"]["last_used_img_host"] == {
        "Aither": "URLs",
        "HUNO": "SomethingElse",
    }


def test_everything_outside_image_hosts_is_carried_forward() -> None:
    document, _ = migrate_v10_to_v11(_doc(dict(_UNCONFIGURED)), None)

    assert document["tracker"]["aither"] == {"enabled": True, "api_key": "key"}
    assert document["tracker"]["settings"]["tracker_order"] == ["Aither"]


def test_a_document_with_no_image_hosts_section_survives() -> None:
    document, unmapped = migrate_v10_to_v11({"schema_version": 10}, None)

    assert not unmapped
    assert document == {"schema_version": 11}
