from pathlib import Path

import tomlkit

from src.config.migrations import migrate_unversioned_to_v2

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_migration_preserves_untouched_sections() -> None:
    old = _load_fixture("schema1_config.toml")
    new, _ = migrate_unversioned_to_v2(old)

    assert new["api_keys"] == old["api_keys"]
    assert new["tracker"]["more_than_tv"] == old["tracker"]["more_than_tv"]


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
