import pytest

from src.backend.utils.filename_claims import (
    PER_FILE_CLAIM_KEYS,
    FilenameClaims,
    detect_file_claims,
    detect_filename_claims,
    resolve_file_claims,
)
from src.config.models import ClaimSwitches


def _switches(**overrides: bool) -> ClaimSwitches:
    base = {
        "enabled": True,
        "edition": True,
        "frame_size": True,
        "localization": True,
        "re_release": True,
        "remux": True,
        "hybrid": True,
        "release_group": True,
    }
    base.update(overrides)
    return ClaimSwitches(**base)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("stem", "field", "expected"),
    [
        (
            "Movie.2024.Directors.Cut.1080p.BluRay.x264-GRP",
            "edition",
            "Directors Cut",
        ),
        ("Movie.2024.IMAX.1080p.BluRay.x264-GRP", "frame_size", "IMAX"),
        ("Movie.2024.Open.Matte.1080p.BluRay.x264-GRP", "frame_size", "Open Matte"),
        ("Movie.2024.DUBBED.1080p.BluRay.x264-GRP", "localization", "Dubbed"),
        ("Movie.2024.SUBBED.1080p.BluRay.x264-GRP", "localization", "Subbed"),
        ("Movie.2024.REPACK.1080p.BluRay.x264-GRP", "re_release", "REPACK"),
        ("Movie.2024.PROPER.1080p.BluRay.x264-GRP", "re_release", "PROPER"),
        ("Movie.2024.1080p.BluRay.REMUX.AVC-GRP", "remux", "REMUX"),
        ("Movie.2024.HYBRID.1080p.BluRay.x264-GRP", "hybrid", "HYBRID"),
        ("Movie.2024.1080p.AMZN.WEB-DL.x264-GRP", "streaming_service", "AMZN"),
        ("Movie.2024.1080p.BluRay.x264-GRP", "release_group", "GRP"),
    ],
)
def test_each_category_is_detected(stem: str, field: str, expected: str) -> None:
    claims = detect_filename_claims([stem], _switches())

    assert getattr(claims, field) == expected


def test_a_claim_needs_every_file_in_the_pack_to_agree() -> None:
    # The pack-wide rule the series page already applies: one dissenting
    # episode means the claim is not the pack's.
    claims = detect_filename_claims(
        [
            "Show.S01E01.REPACK.1080p.WEB-DL.x264-GRP",
            "Show.S01E02.1080p.WEB-DL.x264-GRP",
        ],
        _switches(),
    )

    assert claims.re_release == ""


def test_a_claim_every_file_agrees_on_survives() -> None:
    claims = detect_filename_claims(
        [
            "Show.S01E01.REPACK.1080p.WEB-DL.x264-GRP",
            "Show.S01E02.REPACK.1080p.WEB-DL.x264-GRP",
        ],
        _switches(),
    )

    assert claims.re_release == "REPACK"


def test_a_switched_off_category_is_absent() -> None:
    stem = "Movie.2024.IMAX.HYBRID.1080p.BluRay.x264-GRP"

    claims = detect_filename_claims([stem], _switches(frame_size=False))

    assert claims.frame_size == ""
    assert claims.hybrid == "HYBRID"


def test_master_off_suppresses_all_six() -> None:
    stem = "Movie.2024.Directors.Cut.IMAX.DUBBED.REPACK.HYBRID.REMUX.AVC-GRP"

    claims = detect_filename_claims([stem], _switches(enabled=False))

    assert claims.edition == ""
    assert claims.frame_size == ""
    assert claims.localization == ""
    assert claims.re_release == ""
    assert claims.remux == ""
    assert claims.hybrid == ""


def test_streaming_service_ignores_the_master_switch() -> None:
    # Quality/source and streaming service have no switch: nothing competes
    # with them, so "off" would mean nothing.
    stem = "Movie.2024.1080p.AMZN.WEB-DL.x264-GRP"

    claims = detect_filename_claims([stem], _switches(enabled=False))

    assert claims.streaming_service == "AMZN"


def test_the_source_group_obeys_its_own_switch() -> None:
    # Turning the switch off has to reach output, not just the control: the
    # renderer parses no filename of its own, so an undetected source group
    # is one that cannot appear anywhere.
    stem = "Movie.2024.1080p.BluRay.x264-GRP"

    assert detect_filename_claims([stem], _switches()).release_group == "GRP"
    assert (
        detect_filename_claims([stem], _switches(release_group=False)).release_group
        == ""
    )
    assert detect_filename_claims([stem], _switches(enabled=False)).release_group == ""


def test_no_files_yields_no_claims() -> None:
    claims = detect_filename_claims([], _switches())

    assert claims == FilenameClaims()


def test_as_override_tokens_omits_empty_claims() -> None:
    claims = detect_filename_claims(
        ["Movie.2024.IMAX.1080p.BluRay.x264-GRP"], _switches()
    )

    tokens = claims.as_override_tokens()

    assert tokens["frame_size"] == "IMAX"
    assert "edition" not in tokens


def test_release_group_needs_pack_agreement_too() -> None:
    # A pack whose episodes came from different groups has no one group,
    # and pre-filling either would be a guess.
    claims = detect_filename_claims(
        [
            "Show.S01E01.1080p.WEB-DL.x264-ONE",
            "Show.S01E02.1080p.WEB-DL.x264-TWO",
        ],
        _switches(),
    )

    assert claims.release_group == ""


def test_per_file_claims_keep_a_lone_repack() -> None:
    # The pack-wide rule answers "what should the control show", where one
    # value covers every file. It is the wrong answer for "what should this
    # file render": a season pack with one repacked episode agrees on
    # nothing, and that episode still deserves its marker.
    stems = [
        "Show.S01E01.1080p.WEB-DL.H.264-GRP",
        "Show.S01E02.REPACK.1080p.WEB-DL.H.264-GRP",
        "Show.S01E03.1080p.WEB-DL.H.264-GRP",
    ]

    assert detect_filename_claims(stems, _switches()).re_release == ""
    assert detect_file_claims(stems[0], _switches()).re_release == ""
    assert detect_file_claims(stems[1], _switches()).re_release == "REPACK"


def test_per_file_claims_honour_the_switches() -> None:
    claims = detect_file_claims(
        "Show.S01E02.REPACK.1080p.WEB-DL.H.264-GRP", _switches(re_release=False)
    )

    assert claims.re_release == ""


def test_a_per_file_edit_wins_over_the_filenames_own_claim() -> None:
    # The user is looking at the episode and disagreeing with its name. That
    # is a decision, and detection does not get to overrule it.
    detected = detect_file_claims(
        "Show.S01E02.REPACK.1080p.WEB-DL.H.264-GRP", _switches()
    )

    resolved = resolve_file_claims(detected, {"re_release": "PROPER"})

    assert resolved["re_release"] == "PROPER"


def test_a_cleared_per_file_edit_suppresses_the_claim() -> None:
    # Clearing the cell is a decision -- "this episode is not a repack,
    # whatever its name says" -- so it has to reach output as an empty
    # override rather than falling back through to detection.
    detected = detect_file_claims(
        "Show.S01E02.REPACK.1080p.WEB-DL.H.264-GRP", _switches()
    )

    resolved = resolve_file_claims(detected, {"re_release": ""})

    assert resolved["re_release"] == ""


def test_an_unedited_claim_falls_through_to_the_filename() -> None:
    detected = detect_file_claims(
        "Show.S01E02.REPACK.1080p.WEB-DL.H.264-GRP", _switches()
    )

    resolved = resolve_file_claims(detected, {})

    assert resolved["re_release"] == "REPACK"


def test_an_undetected_unedited_claim_is_omitted_not_emptied() -> None:
    # Omission leaves a gap for whatever renders next; "" would assert the
    # file has no such claim, which nothing here is entitled to say.
    detected = detect_file_claims("Show.S01E02.1080p.WEB-DL.H.264-GRP", _switches())

    resolved = resolve_file_claims(detected, {})

    assert "re_release" not in resolved
    assert "edition" not in resolved


def test_the_group_is_never_resolved_per_file() -> None:
    # A release has at most one group tag, so the group is whole-release
    # even though it is detected per file like everything else.
    detected = detect_file_claims("Show.S01E02.1080p.WEB-DL.H.264-GRP", _switches())

    assert detected.release_group == "GRP"
    assert "release_group" not in resolve_file_claims(detected, {})
    assert "release_group" not in PER_FILE_CLAIM_KEYS
