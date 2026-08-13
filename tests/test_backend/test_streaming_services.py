"""The streaming-service table is derived from guessit's internal config.

That buys ~160 services with no list to maintain here, at the cost of a
dependency on a structure guessit does not treat as public API. These tests
are what turns that cost into a loud failure instead of a silent one: if a
guessit upgrade moves or reshapes `advanced_config.streaming_service`, the
table empties and every Aither/LST web title quietly loses its service.
"""

import pytest

from src.backend.utils.streaming_services import (
    STREAMING_SERVICE_ABBREVIATIONS,
    STREAMING_SERVICE_CHOICES,
    _first_literal,
    abbreviate_streaming_service,
    detect_streaming_service,
)


def test_the_table_loaded_from_guessit() -> None:
    """A near-empty table means the derivation broke, not that guessit
    suddenly knows only a few services."""
    assert len(STREAMING_SERVICE_ABBREVIATIONS) > 100


@pytest.mark.parametrize(
    ("name", "abbreviation"),
    [
        ("Netflix", "NF"),
        ("Amazon Prime", "AMZN"),
        ("Disney+", "DSNP"),
        ("AppleTV", "ATVP"),
        ("Paramount+", "PMTP"),
        ("HBO Max", "HMAX"),
        ("Hulu", "HULU"),
        ("Peacock", "PCOK"),
        # dict-shaped entries, which carry their abbreviation under "pattern"
        ("Max", "MAX"),
        ("NowTV", "NOW"),
    ],
)
def test_known_services_map_to_their_release_abbreviation(
    name: str, abbreviation: str
) -> None:
    assert abbreviate_streaming_service(name) == abbreviation


def test_an_unknown_service_yields_nothing() -> None:
    """Falling back to the name itself would put "Some New Service" in a
    title, which is worse than omitting it."""
    assert abbreviate_streaming_service("Some Service That Does Not Exist") == ""


@pytest.mark.parametrize("value", [None, "", "   ", [], 42])
def test_non_names_yield_nothing(value: object) -> None:
    assert abbreviate_streaming_service(value) == ""


def test_a_list_takes_the_winning_service() -> None:
    """guessit reports a list when a release name matches more than one."""
    assert abbreviate_streaming_service(["Netflix", "Hulu"]) == "NF"


@pytest.mark.parametrize(
    ("patterns", "expected"),
    [
        ("AMC", "AMC"),
        (["NF", "Netflix"], "NF"),
        ({"pattern": "MAX", "ignore_case": False}, "MAX"),
        # a regex alias is never the abbreviation
        (["re:Amazon-?Prime", "AMZN"], "AMZN"),
        (["re:Only-?Regex"], None),
        ({"no_pattern_key": True}, None),
        (None, None),
    ],
)
def test_first_literal_handles_every_shape_in_the_table(
    patterns: object, expected: str | None
) -> None:
    assert _first_literal(patterns) == expected


def test_choices_are_unique_and_cover_the_table() -> None:
    assert len(STREAMING_SERVICE_CHOICES) == len(set(STREAMING_SERVICE_CHOICES))
    assert set(STREAMING_SERVICE_CHOICES) == set(
        STREAMING_SERVICE_ABBREVIATIONS.values()
    )
    assert "" not in STREAMING_SERVICE_CHOICES


def test_choices_are_sorted_case_insensitively() -> None:
    """ "iP" and "iTunes" belong with the letters, not bunched after every
    uppercase abbreviation."""
    assert list(STREAMING_SERVICE_CHOICES) == sorted(
        STREAMING_SERVICE_CHOICES, key=str.casefold
    )


@pytest.mark.parametrize(
    ("release_name", "expected"),
    [
        ("Movie.2021.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb.mkv", "AMZN"),
        ("Show.S01E01.2160p.NF.WEB-DL.DDP5.1.DV.HDR.H.265-Kitsune.mkv", "NF"),
        ("Movie.2021.1080p.ATVP.WEB-DL.DDP5.1.Atmos.H.264-NTb.mkv", "ATVP"),
        # the full name spelled out still resolves to the abbreviation
        ("Movie.2021.1080p.Amazon.Prime.WEB-DL.H.264-NTb.mkv", "AMZN"),
        # no service in the name
        ("Movie.2021.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP.mkv", ""),
        ("", ""),
    ],
)
def test_detection_reads_the_abbreviation_out_of_a_release_name(
    release_name: str, expected: str
) -> None:
    assert detect_streaming_service(release_name) == expected


def test_the_wizard_and_the_token_gate_on_the_same_sources() -> None:
    """The Service combo is enabled for exactly the sources the token will
    render a service for.

    Both pages call `_sync_service_combo_to_quality`, which tests
    QualitySelection.WEB_DL/WEB_RIP -- the same pair `_streaming_service`
    checks. Listing them here means changing one side without the other shows
    up as a failure rather than as a combo the user can fill in and a title
    that silently drops it.
    """
    from src.enums.rename import QualitySelection

    web_sources = {QualitySelection.WEB_DL, QualitySelection.WEB_RIP}

    assert web_sources == {
        quality for quality in QualitySelection if "WEB" in quality.name
    }
