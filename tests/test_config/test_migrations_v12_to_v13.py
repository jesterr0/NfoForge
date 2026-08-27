"""Schema 13 folds the two release group keys into one and switches parsing.

The group tag printed on output is the user's publishing identity rather than
a property of the media type, so the movie and series copies become a single
``[general]`` entry. The source group -- what an input filename claims --
becomes a switchable claim like the other six.
"""

from typing import Any

from src.config.migrations import migrate_v12_to_v13


def _doc(
    movie: dict[str, Any] | None = None,
    series: dict[str, Any] | None = None,
    general: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {"schema_version": 12}
    if general is not None:
        doc["general"] = general
    if movie is not None:
        doc["movie_management"] = movie
    if series is not None:
        doc["series_management"] = series
    return doc


def test_the_movie_group_tag_folds_into_general() -> None:
    document, unmapped = migrate_v12_to_v13(
        _doc(
            general={"releasers_name": "tester"},
            movie={
                "mvr_release_group": "MYGROUP",
                "mvr_token": "{title}",
            },
            series={"tvr_release_group": ""},
        ),
        None,
    )

    assert not unmapped
    assert document["schema_version"] == 13
    assert document["general"]["release_group"] == "MYGROUP"
    assert document["general"]["releasers_name"] == "tester"
    assert "mvr_release_group" not in document["movie_management"]
    assert "tvr_release_group" not in document["series_management"]
    assert document["movie_management"]["mvr_token"] == "{title}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential


def test_the_series_group_tag_is_used_when_the_movie_side_is_blank() -> None:
    document, _ = migrate_v12_to_v13(
        _doc(
            movie={"mvr_release_group": ""},
            series={"tvr_release_group": "TVGROUP"},
        ),
        None,
    )

    assert document["general"]["release_group"] == "TVGROUP"


def test_the_movie_side_wins_when_both_are_set() -> None:
    """Neither key ever had a UI, so both being set is a hand-edited profile.
    One of them has to win and the choice only has to be stated, not clever."""
    document, _ = migrate_v12_to_v13(
        _doc(
            movie={"mvr_release_group": "MOVIEGROUP"},
            series={"tvr_release_group": "TVGROUP"},
        ),
        None,
    )

    assert document["general"]["release_group"] == "MOVIEGROUP"


def test_both_sections_gain_the_release_group_claim_switch() -> None:
    """Written explicitly rather than left to the loader's default, so an
    upgraded profile looks like a fresh one. True keeps parsing working as it
    did before the switch existed."""
    document, _ = migrate_v12_to_v13(
        _doc(movie={"mvr_release_group": ""}, series={"tvr_release_group": ""}),
        None,
    )

    assert document["movie_management"]["mvr_parse_claim_release_group"] is True
    assert document["series_management"]["tvr_parse_claim_release_group"] is True


def test_a_profile_with_no_group_tag_set_gets_a_blank_one() -> None:
    document, unmapped = migrate_v12_to_v13(
        _doc(movie={"mvr_release_group": ""}, series={"tvr_release_group": ""}),
        None,
    )

    assert not unmapped
    assert document["general"]["release_group"] == ""


def test_surrounding_whitespace_is_dropped() -> None:
    document, _ = migrate_v12_to_v13(
        _doc(movie={"mvr_release_group": "  MYGROUP  "}),
        None,
    )

    assert document["general"]["release_group"] == "MYGROUP"


def test_a_document_with_no_management_tables_survives() -> None:
    """Should not happen at schema 12, but a partial document must not crash
    the hop -- and must still land the key the loader now reads."""
    document, unmapped = migrate_v12_to_v13({"schema_version": 12}, None)

    assert not unmapped
    assert document == {"schema_version": 13, "general": {"release_group": ""}}
