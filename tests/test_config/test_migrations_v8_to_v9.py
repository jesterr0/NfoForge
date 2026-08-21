"""The schema 8 -> 9 hop: dead filename settings out, claim switches in.

Three changes share this hop because they are all filename-settings work and
splitting them would cost users three migrations for one release:

- `replace_illegal_chars` is dropped. Nothing read it.
- the filename colon control reduces from five options to three.
- `parse_filename_attributes` expands into a master plus six categories.

Every existing profile must render byte-identical output afterwards.
"""

from typing import Any

from src.config.migrations import migrate_v8_to_v9


def _doc(**movie: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 8,
        "movie_management": {
            "mvr_enabled": True,
            "mvr_replace_illegal_chars": True,
            "mvr_colon_replace_filename": 1,
            "mvr_colon_replace_title": 3,
            "mvr_parse_filename_attributes": True,
        },
        "series_management": {
            "tvr_replace_illegal_chars": True,
            "tvr_colon_replace_filename": 1,
            "tvr_parse_filename_attributes": True,
        },
    }
    base["movie_management"].update(movie)
    return base


def test_bumps_the_schema_version() -> None:
    migrated, unhandled = migrate_v8_to_v9(_doc(), None)

    assert migrated["schema_version"] == 9
    assert unhandled == []


def test_drops_the_dead_illegal_chars_key() -> None:
    migrated, _ = migrate_v8_to_v9(_doc(), None)

    assert "mvr_replace_illegal_chars" not in migrated["movie_management"]
    assert "tvr_replace_illegal_chars" not in migrated["series_management"]


# 1 KEEP -> Dot, 2 DELETE -> Remove, 3/4/5 dash variants -> Dash.
# Keep and Delete must NOT collapse together: they differ for any title
# whose colon has no following space, e.g. "Re:Zero" -> "Re.Zero" under
# Keep and "ReZero" under Delete.
def test_maps_the_five_colon_values_onto_three() -> None:
    for old, expected in ((1, 1), (2, 2), (3, 3), (4, 3), (5, 3)):
        migrated, _ = migrate_v8_to_v9(_doc(mvr_colon_replace_filename=old), None)

        assert migrated["movie_management"]["mvr_colon_replace_filename"] == (
            expected
        ), f"colon value {old}"


def test_leaves_the_title_colon_value_alone() -> None:
    # The title side keeps all five options; only the filename side reduces.
    migrated, _ = migrate_v8_to_v9(_doc(mvr_colon_replace_title=5), None)

    assert migrated["movie_management"]["mvr_colon_replace_title"] == 5


def test_expands_parse_attributes_into_a_master_plus_six() -> None:
    migrated, _ = migrate_v8_to_v9(_doc(), None)
    movie = migrated["movie_management"]

    assert movie["mvr_parse_claims"] is True
    for claim in (
        "edition",
        "frame_size",
        "localization",
        "re_release",
        "remux",
        "hybrid",
    ):
        assert movie[f"mvr_parse_claim_{claim}"] is True, claim
    assert "mvr_parse_filename_attributes" not in movie


def test_hybrid_follows_the_old_flag_when_it_was_off() -> None:
    # HYBRID is the one claim the old flag genuinely controlled, so a
    # config with it off must keep emitting no HYBRID. The other five were
    # pre-filled into override_tokens before the gate was consulted, so
    # they stay on and become live only when master is re-enabled.
    migrated, _ = migrate_v8_to_v9(_doc(mvr_parse_filename_attributes=False), None)
    movie = migrated["movie_management"]

    assert movie["mvr_parse_claims"] is False
    assert movie["mvr_parse_claim_hybrid"] is False
    assert movie["mvr_parse_claim_edition"] is True


def test_migrates_the_series_section_the_same_way() -> None:
    migrated, _ = migrate_v8_to_v9(_doc(), None)
    series = migrated["series_management"]

    assert series["tvr_parse_claims"] is True
    assert series["tvr_parse_claim_hybrid"] is True
    assert series["tvr_colon_replace_filename"] == 1


def test_tolerates_a_document_with_neither_section() -> None:
    migrated, unhandled = migrate_v8_to_v9({"schema_version": 8}, None)

    assert migrated["schema_version"] == 9
    assert unhandled == []


def test_leaves_unrelated_sections_untouched() -> None:
    doc = _doc()
    doc["tracker"] = {"lst": {"source": "LST.GG"}}

    migrated, _ = migrate_v8_to_v9(doc, None)

    assert migrated["tracker"] == {"lst": {"source": "LST.GG"}}
