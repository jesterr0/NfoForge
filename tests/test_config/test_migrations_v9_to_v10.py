"""Schema 10 discards every per-tracker title override.

Unlike the hop before it, this one changes output deliberately. Tracker
titles are enforced from hardcoded rules now, so a stored override is a
customisation the design removes rather than a value to carry forward --
which is the feature, not a cost of it.
"""

from typing import Any

from src.config.migrations import migrate_v9_to_v10


def _doc(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 9,
        "movie_management": {
            "mvr_enabled": True,
            "mvr_token": "{title_clean}",
            "mvr_title_token": "{title_clean} {release_year}",
            "mvr_title_colon_replace": 3,
        },
        "series_management": {
            "tvr_standard_title_token": "{title_exact} S{season_number}",
            "tvr_daily_title_token": "{title_exact} {episode_air_date}",
            "tvr_anime_title_token": "{title_exact} {episode_number_absolute}",
            "tvr_title_colon_replace": 1,
        },
        "tracker": {
            "aither": {
                "enabled": True,
                "api_key": "key",
                "mvr_title_override_enabled": True,
                "mvr_title_colon_replace": 1,
                "mvr_title_token_override": "{title_exact} custom",
                "mvr_title_replace_map": [["DDP", "DD+"]],
                "tvr_title_overrides": {
                    "standard": {
                        "enabled": True,
                        "colon_replace": 1,
                        "token": "{title_exact} S{season_number}",
                        "replace_map": [],
                    }
                },
            },
            "beyond_hd": {
                "enabled": False,
                "mvr_title_override_enabled": False,
                "mvr_title_token_override": "",
            },
        },
    }
    base.update(overrides)
    return base


def test_bumps_the_schema_version() -> None:
    migrated, unhandled = migrate_v9_to_v10(_doc(), None)

    assert migrated["schema_version"] == 10
    assert unhandled == []


def test_discards_every_per_tracker_title_override() -> None:
    # Users who customised a tracker title lose that customisation. That is
    # the feature: the shipped config was not derived from tracker rules,
    # and every tracker checked during design had defects.
    migrated, _ = migrate_v9_to_v10(_doc(), None)

    for tracker in migrated["tracker"].values():
        for key in (
            "mvr_title_override_enabled",
            "mvr_title_colon_replace",
            "mvr_title_token_override",
            "mvr_title_replace_map",
            "tvr_title_overrides",
        ):
            assert key not in tracker, key


def test_leaves_a_trackers_other_settings_alone() -> None:
    # Only the title fields go; a tracker's credentials and enablement are
    # not this migration's business.
    migrated, _ = migrate_v9_to_v10(_doc(), None)

    assert migrated["tracker"]["aither"]["enabled"] is True
    assert migrated["tracker"]["aither"]["api_key"] == "key"
    assert migrated["tracker"]["beyond_hd"]["enabled"] is False


def test_preserves_the_global_movie_and_series_title_tokens() -> None:
    """Decision 5: the global template stays the user's.

    Seven trackers have no composition and render exactly this, so
    discarding it would leave them with no title at all.
    """
    migrated, _ = migrate_v9_to_v10(_doc(), None)

    assert migrated["movie_management"]["mvr_title_token"] == (
        "{title_clean} {release_year}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential
    )
    series = migrated["series_management"]
    assert series["tvr_standard_title_token"] == "{title_exact} S{season_number}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential
    assert series["tvr_daily_title_token"] == "{title_exact} {episode_air_date}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential
    assert series["tvr_anime_title_token"] == "{title_exact} {episode_number_absolute}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential


def test_preserves_the_global_title_colon_settings() -> None:
    # The entry's colon wins where it names one; otherwise this applies.
    migrated, _ = migrate_v9_to_v10(_doc(), None)

    assert migrated["movie_management"]["mvr_title_colon_replace"] == 3
    assert migrated["series_management"]["tvr_title_colon_replace"] == 1


def test_leaves_the_filename_side_untouched() -> None:
    # This hop is about titles. Filenames stay the user's entirely.
    migrated, _ = migrate_v9_to_v10(_doc(), None)

    assert migrated["movie_management"]["mvr_enabled"] is True
    assert migrated["movie_management"]["mvr_token"] == "{title_clean}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential


def test_tolerates_a_document_with_no_trackers() -> None:
    migrated, unhandled = migrate_v9_to_v10({"schema_version": 9}, None)

    assert migrated["schema_version"] == 10
    assert unhandled == []


def test_tolerates_a_tracker_that_never_had_an_override() -> None:
    document = _doc()
    document["tracker"]["blutopia"] = {"enabled": True}

    migrated, unhandled = migrate_v9_to_v10(document, None)

    assert migrated["tracker"]["blutopia"] == {"enabled": True}
    assert unhandled == []
