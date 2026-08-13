from pathlib import Path
from typing import Any

import tomlkit

from src.config.migrations import (
    migrate_unversioned_to_v2,
    migrate_v2_to_v3,
    migrate_v3_to_v4,
    migrate_v4_to_v5,
    migrate_v5_to_v6,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_v4_to_v5_clears_the_seeded_torrentleech_title_rule() -> None:
    old = _load_fixture("schema4_config.toml")
    assert old["tracker"]["torrent_leech"]["mvr_title_replace_map"]  # pyright: ignore[reportIndexIssue]

    new, unmapped = migrate_v4_to_v5(old, None)

    assert not unmapped
    assert new["schema_version"] == 5
    torrent_leech = new["tracker"]["torrent_leech"]
    assert torrent_leech["mvr_title_replace_map"] == []
    assert torrent_leech["mvr_title_override_enabled"] is False
    # only TorrentLeech's title override is touched
    assert torrent_leech["source"] == "TorrentLeech.org"
    assert new["tracker"]["aither"]["mvr_title_token_override"]
    assert new["tracker"]["aither"]["mvr_title_replace_map"]


def test_v4_to_v5_leaves_a_hand_edited_torrentleech_rule_alone() -> None:
    """The seeded rule is matched exactly, so a profile someone customized is
    carried forward rather than assumed to be the default."""
    document = tomlkit.parse(
        "schema_version = 4\n"
        "[tracker.torrent_leech]\n"
        "mvr_title_override_enabled = true\n"
        'mvr_title_token_override = ""\n'
        'mvr_title_replace_map = [["(?i)hdr10plus", "HDR10+"]]\n'
    )

    new, unmapped = migrate_v4_to_v5(document, None)

    assert not unmapped
    assert new["tracker"]["torrent_leech"]["mvr_title_replace_map"] == [
        ["(?i)hdr10plus", "HDR10+"]
    ]
    assert new["tracker"]["torrent_leech"]["mvr_title_override_enabled"] is True


def test_v4_to_v5_does_not_mutate_the_document_it_is_given() -> None:
    old = _load_fixture("schema4_config.toml")

    migrate_v4_to_v5(old, None)

    assert old["tracker"]["torrent_leech"]["mvr_title_replace_map"] == [  # pyright: ignore[reportIndexIssue]
        ["\\.", "[space]"]
    ]


def test_v4_to_v5_survives_a_profile_with_no_tracker_section() -> None:
    document = tomlkit.parse("schema_version = 4\n[general]\nsuffix = 1\n")

    new, unmapped = migrate_v4_to_v5(document, None)

    assert not unmapped
    assert new["schema_version"] == 5
    assert new["general"]["suffix"] == 1


def test_v3_to_v4_resets_display_name_plugin_selections() -> None:
    old = _load_fixture("schema3_config.toml")
    old["api_keys"] = {"tmdb_api_key": "user-supplied"}

    new, unmapped = migrate_v3_to_v4(old, None)

    assert not unmapped
    assert new["schema_version"] == 4
    # a user-supplied TMDB key override is unrelated to the plugin-ID
    # rename this hop performs, and must be carried forward, not dropped
    assert new["api_keys"] == {"tmdb_api_key": "user-supplied"}
    assert new["general"]["enable_plugins"] is True
    assert new["plugins"] == {
        "wizard_page": "",
        "token_replacer": "",
        "pre_upload": "",
        "metadata_transformer": "",
    }


def test_migrating_v3_preserves_a_user_supplied_api_key() -> None:
    document = tomlkit.parse('schema_version = 3\n[api_keys]\ntmdb_api_key = "kept"\n')

    migrated, unmapped = migrate_v3_to_v4(document, None)

    assert not unmapped
    assert migrated["api_keys"]["tmdb_api_key"] == "kept"


def _load_fixture(name: str) -> tomlkit.TOMLDocument:
    return tomlkit.parse((FIXTURES / name).read_text(encoding="utf-8"))


def test_migration_moves_and_renames_movie_sections() -> None:
    old = _load_fixture("schema1_config.toml")
    new, unmapped = migrate_unversioned_to_v2(old)

    assert new["schema_version"] == 2
    assert "movie_management" in new and "movie_rename" not in new

    # token renames applied to persisted token strings
    assert "{title_clean}" in new["movie_management"]["mvr_token"]
    assert "{audio_codec}" in new["movie_management"]["mvr_token"]
    assert "{movie_clean_title}" not in new["movie_management"]["mvr_token"]

    # dynamic range + clean rules moved to global_management
    assert "title_clean_rules" in new["global_management"]
    assert "video_dynamic_range" in new["global_management"]

    # new section filled from defaults
    assert new["series_management"]["tvr_enabled"] is True

    assert not unmapped


def test_v2_to_v3_removes_retired_ptpimg_selections() -> None:
    old = _load_fixture("schema2_config.toml")
    old["tracker"]["settings"]["last_used_img_host"]["Aither"] = "ImageBox"  # pyright: ignore[reportIndexIssue]

    new, unmapped = migrate_v2_to_v3(old)

    assert not unmapped
    image_hosts = new["image_hosts"]
    assert "ptpimg" not in image_hosts
    tracker_settings = new["tracker"]["settings"]
    assert tracker_settings["last_used_img_host"] == {"Aither": "ImageBox"}


def test_migration_preserves_untouched_sections() -> None:
    old = _load_fixture("schema1_config.toml")
    # Snapshot the serialized form *before* migration -- comparing
    # `new[...] == old[...]` after the fact is trivially true whenever
    # migration copies the tomlkit object forward by reference (as it does
    # here), even if that shared object were later mutated in place. Only a
    # pre-migration snapshot can actually catch an accidental mutation.
    before_api_keys = tomlkit.dumps(old["api_keys"])  # type: ignore[reportArgumentType]
    before_tl = tomlkit.dumps(old["tracker"]["torrent_leech"])  # type: ignore[reportArgumentType]

    new, _ = migrate_unversioned_to_v2(old)

    assert tomlkit.dumps(new["api_keys"]) == before_api_keys
    assert tomlkit.dumps(new["tracker"]["torrent_leech"]) == before_tl


def test_migration_renames_tokens_in_tracker_title_overrides() -> None:
    old = _load_fixture("schema1_config.toml")
    new, unmapped = migrate_unversioned_to_v2(old)

    assert not unmapped

    aither_override = new["tracker"]["aither"]["mvr_title_token_override"]
    assert "{movie_clean_title}" not in aither_override
    assert "{mi_audio_codec}" not in aither_override
    assert "{mi_" not in aither_override
    assert "{title_clean}" in aither_override
    assert "{audio_codec}" in aither_override

    # every schema-1 default tracker that shipped a non-empty override
    # using old token names must be rewritten the same way
    for tracker_name in (
        "aither",
        "huno",
        "lst",
        "dark_peers",
        "shareisland",
        "uploadcx",
        "only_encodes",
    ):
        override = new["tracker"][tracker_name]["mvr_title_token_override"]
        assert "{movie_clean_title}" not in override, tracker_name
        assert "{mi_" not in override, tracker_name
        assert "{title_clean}" in override, tracker_name

    # trackers with an empty override are left alone
    assert new["tracker"]["torrent_leech"]["mvr_title_token_override"] == ""
    assert new["tracker"]["beyond_hd"]["mvr_title_token_override"] == ""

    # non-token keys in a rewritten tracker section are untouched
    assert (
        new["tracker"]["aither"]["mvr_title_replace_map"]
        == old["tracker"]["aither"]["mvr_title_replace_map"]  # type: ignore[reportArgumentType]
    )
    assert new["tracker"]["aither"]["source"] == "Aither"


def test_migration_reports_unmapped_when_movie_rename_missing() -> None:
    old = {"general": {}}  # corrupt/partial: no movie_rename
    new, unmapped = migrate_unversioned_to_v2(old)

    assert "movie_management" in unmapped or "movie_rename" in unmapped


def test_migration_preserves_custom_user_values() -> None:
    old = _load_fixture("schema1_config.toml")
    new, unmapped = migrate_unversioned_to_v2(old)

    assert not unmapped
    assert new["movie_management"]["mvr_release_group"] == "CustomReleaseGroup"
    assert "CUSTOM" in new["movie_management"]["mvr_token"]
    assert new["tracker"]["torrent_leech"]["username"] == "custom_tl_user"
    assert ["_custom_user_rule_", "[space]"] in [
        list(rule) for rule in new["global_management"]["title_clean_rules"]
    ]
    assert new["global_management"]["title_clean_rules_modified"] is True


def test_migration_renames_tokens_in_user_tokens_section() -> None:
    old = {
        "general": {},
        "movie_rename": {
            "mvr_enabled": True,
            "mvr_replace_illegal_chars": True,
            "mvr_colon_replace_filename": 3,
            "mvr_colon_replace_title": 3,
            "mvr_parse_filename_attributes": True,
            "mvr_token": "{movie_clean_title}",
            "mvr_title_token": "{movie_clean_title}",
            "mvr_clean_title_rules": [],
            "mvr_clean_title_rules_modified": False,
            "mvr_release_group": "",
            "mvr_mi_video_dynamic_range": {
                "resolutions": {},
                "hdr_types": {},
                "custom_strings": {},
            },
        },
        "user_tokens": {
            "tokens": {
                "my_token": ["{movie_title} {mi_audio_codec}", "Movie"],
            }
        },
    }
    new, unmapped = migrate_unversioned_to_v2(old)

    assert not unmapped
    assert new["user_tokens"]["tokens"]["my_token"][0] == "{title} {audio_codec}"
    assert new["user_tokens"]["tokens"]["my_token"][1] == "Movie"


def test_migration_normalizes_legacy_newline_sequence() -> None:
    old = {
        "general": {},
        "movie_rename": {
            "mvr_enabled": True,
            "mvr_replace_illegal_chars": True,
            "mvr_colon_replace_filename": 3,
            "mvr_colon_replace_title": 3,
            "mvr_parse_filename_attributes": True,
            "mvr_token": "",
            "mvr_title_token": "",
            "mvr_clean_title_rules": [],
            "mvr_clean_title_rules_modified": False,
            "mvr_release_group": "",
            "mvr_mi_video_dynamic_range": {
                "resolutions": {},
                "hdr_types": {},
                "custom_strings": {},
            },
        },
        "template_settings": {"newline_sequence": "\\n"},
    }
    new, unmapped = migrate_unversioned_to_v2(old)

    assert not unmapped
    assert new["template_settings"]["newline_sequence"] == "\n"


def test_migration_renames_tokens_in_template_settings() -> None:
    """[template_settings] holds no token-string fields today, but the
    rename sweep must cover it anyway (forward-safety) the same way it
    already covers user_tokens.tokens and tracker title overrides.
    """
    old = {
        "general": {},
        "movie_rename": {
            "mvr_enabled": True,
            "mvr_replace_illegal_chars": True,
            "mvr_colon_replace_filename": 3,
            "mvr_colon_replace_title": 3,
            "mvr_parse_filename_attributes": True,
            "mvr_token": "",
            "mvr_title_token": "",
            "mvr_clean_title_rules": [],
            "mvr_clean_title_rules_modified": False,
            "mvr_release_group": "",
            "mvr_mi_video_dynamic_range": {
                "resolutions": {},
                "hdr_types": {},
                "custom_strings": {},
            },
        },
        "template_settings": {
            "some_future_token_field": "{movie_title} {mi_audio_codec}",
            "block_syntax_color": "#89689d",
        },
    }
    new, unmapped = migrate_unversioned_to_v2(old)

    assert not unmapped
    assert (
        new["template_settings"]["some_future_token_field"] == "{title} {audio_codec}"  # noqa: S105 - NFO template token field name/value used as test fixture data, not a credential
    )
    # non-token config is left untouched
    assert new["template_settings"]["block_syntax_color"] == "#89689d"


# ---------------------------------------------------------------------------
# 5 -> 6: title overrides stopped being locked
# ---------------------------------------------------------------------------


def _v5_doc(stored_token: str, bhd_token: str = "") -> dict[str, Any]:
    return {
        "schema_version": 5,
        "tracker": {
            "aither": {
                "source": "Aither",
                "mvr_title_override_enabled": True,
                "mvr_title_token_override": stored_token,
                "mvr_title_colon_replace": 1,
                "mvr_title_replace_map": [["stale", "rule"]],
            },
            "beyond_hd": {
                "source": "BHD",
                "mvr_title_override_enabled": True,
                "mvr_title_token_override": bhd_token,
                "mvr_title_colon_replace": 3,
                "mvr_title_replace_map": [],
            },
        },
    }


_V6_DEFAULTS = {
    "tracker": {
        "aither": {
            "mvr_title_override_enabled": True,
            "mvr_title_token_override": "{title_exact} (packaged)",
            "mvr_title_colon_replace": 1,
            "mvr_title_replace_map": [["(?i)hdr10plus", "HDR10+"]],
            "tvr_title_overrides": {"Standard": {"token": "{title_exact} S01"}},
        },
        "beyond_hd": {
            "mvr_title_override_enabled": True,
            "mvr_title_token_override": "{title_exact} (packaged bhd)",
            "mvr_title_colon_replace": 1,
            "mvr_title_replace_map": [],
        },
    }
}


def test_v5_to_v6_refreshes_a_formerly_locked_tracker() -> None:
    """Aither's stored value was never editable, so it is the packaged default
    from whenever the profile was created -- and stale, because merge_defaults
    only backfills *missing* keys. Unlocking makes it govern, so it has to be
    brought up to date or every existing profile silently reverts."""
    new, unmapped = migrate_v5_to_v6(_v5_doc("{title_exact} (stale)"), _V6_DEFAULTS)

    assert not unmapped
    assert new["schema_version"] == 6
    aither = new["tracker"]["aither"]
    assert aither["mvr_title_token_override"] == "{title_exact} (packaged)"  # noqa: S105 - a title template, not a credential
    assert aither["mvr_title_replace_map"] == [["(?i)hdr10plus", "HDR10+"]]
    assert aither["tvr_title_overrides"] == {"Standard": {"token": "{title_exact} S01"}}
    # unrelated keys in the same section survive
    assert aither["source"] == "Aither"


def test_v5_to_v6_leaves_an_always_editable_tracker_alone() -> None:
    """BeyondHD was never locked, so whatever it stores is a choice the user
    made. Overwriting it would discard real customization."""
    new, _ = migrate_v5_to_v6(
        _v5_doc(
            "{title_exact} (stale)",
            bhd_token="{title_exact} (my own)",  # noqa: S106 - a title template
        ),
        _V6_DEFAULTS,
    )

    assert new["tracker"]["beyond_hd"]["mvr_title_token_override"] == (
        "{title_exact} (my own)"  # noqa: S105 - a title template, not a credential
    )
    assert new["tracker"]["beyond_hd"]["mvr_title_colon_replace"] == 3


def test_v5_to_v6_drops_a_stale_key_the_packaged_default_no_longer_ships() -> None:
    """A movie-only tracker that once shipped series overrides must not keep
    governing from the stale copy."""
    doc = _v5_doc("{title_exact} (stale)")
    doc["tracker"]["aither"]["tvr_title_overrides"] = {"Standard": {"token": "old"}}
    defaults = {"tracker": {"aither": {"mvr_title_token_override": "{title_exact}"}}}

    new, _ = migrate_v5_to_v6(doc, defaults)

    assert "tvr_title_overrides" not in new["tracker"]["aither"]


def test_v5_to_v6_survives_a_document_with_no_tracker_table() -> None:
    new, unmapped = migrate_v5_to_v6({"schema_version": 5}, _V6_DEFAULTS)

    assert not unmapped
    assert new == {"schema_version": 6}


def test_v5_to_v6_does_not_mutate_the_document_it_was_given() -> None:
    """The hop may not be the last one forever; a later hop must not find the
    caller's document altered underneath it."""
    doc = _v5_doc("{title_exact} (stale)")

    migrate_v5_to_v6(doc, _V6_DEFAULTS)

    assert doc["tracker"]["aither"]["mvr_title_token_override"] == (
        "{title_exact} (stale)"  # noqa: S105 - a title template, not a credential
    )
