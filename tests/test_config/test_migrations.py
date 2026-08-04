from pathlib import Path

import tomlkit

from src.config.migrations import (
    migrate_unversioned_to_v2,
    migrate_v2_to_v3,
    migrate_v3_to_v4,
)

FIXTURES = Path(__file__).parent / "fixtures"


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
    old["tracker"]["settings"]["last_used_img_host"]["Aither"] = "ImageBox"

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
    before_mtv = tomlkit.dumps(old["tracker"]["more_than_tv"])  # type: ignore[reportArgumentType]

    new, _ = migrate_unversioned_to_v2(old)

    assert tomlkit.dumps(new["api_keys"]) == before_api_keys
    assert tomlkit.dumps(new["tracker"]["more_than_tv"]) == before_mtv


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
    assert new["tracker"]["more_than_tv"]["mvr_title_token_override"] == ""
    assert new["tracker"]["torrent_leech"]["mvr_title_token_override"] == ""

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
    assert new["tracker"]["more_than_tv"]["username"] == "custom_mtv_user"
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
