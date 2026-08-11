import pytest

from src.backend.torrents.piece_size import (
    _PIECE_SIZE_CURVE,
    MAX_PIECE_EXPONENT,
    piece_exponent,
)

_KIB = 1024
_MIB = 1024 * _KIB
_GIB = 1024 * _MIB


@pytest.mark.parametrize(
    ("content_size", "expected"),
    [
        # empty and tiny content still get a real exponent -- the curve covers
        # every size, so neither backend ever falls back to its own default
        (0, 16),
        (1, 16),
        # each band's upper bound, then one byte past it
        (50 * _MIB, 16),
        (50 * _MIB + 1, 17),
        (150 * _MIB, 17),
        (150 * _MIB + 1, 18),
        (350 * _MIB, 18),
        (350 * _MIB + 1, 19),
        (512 * _MIB, 19),
        (512 * _MIB + 1, 20),
        (1 * _GIB, 20),
        (1 * _GIB + 1, 21),
        (4 * _GIB, 21),
        (4 * _GIB + 1, 22),
        (12 * _GIB, 22),
        (12 * _GIB + 1, 23),
        (20 * _GIB, 23),
        (20 * _GIB + 1, 24),
        # a realistic remux and an absurd one both land on the ceiling
        (70 * _GIB, 24),
        (1024 * _GIB, 24),
    ],
)
def test_the_curve_returns_the_documented_exponent_at_every_band_boundary(
    content_size: int, expected: int
) -> None:
    assert piece_exponent(content_size) == expected


def test_the_curve_never_exceeds_the_lowest_tracker_ceiling() -> None:
    """2^24 is the guarantee the whole policy rests on.

    It is the lowest MaxPieceLength across every tracker NfoForge supports
    (BHD, PTP, HDB, LST, OnlyEncodes). One hash is shared by every tracker in a
    run, so a curve that exceeded it would produce a torrent one of them
    rejects -- and it is also torf's own piece_size_max_default, so exceeding
    it would break the fallback backend outright.
    """
    sizes = [0, 1]
    for upper_bound, _exponent in _PIECE_SIZE_CURVE:
        sizes.extend((upper_bound - 1, upper_bound, upper_bound + 1))
    sizes.extend((100 * _GIB, 10_000 * _GIB))

    assert all(piece_exponent(size) <= MAX_PIECE_EXPONENT for size in sizes)


def test_the_curve_is_monotonic() -> None:
    """More content never means smaller pieces."""
    sizes = [0]
    for upper_bound, _exponent in _PIECE_SIZE_CURVE:
        sizes.extend((upper_bound - 1, upper_bound, upper_bound + 1))
    sizes.append(100 * _GIB)

    exponents = [piece_exponent(size) for size in sorted(sizes)]
    assert exponents == sorted(exponents)


def test_every_exponent_is_within_the_range_both_backends_accept() -> None:
    """mkbrr's --piece-length accepts 16-27; torf's floor is 2^14."""
    exponents = [exponent for _bound, exponent in _PIECE_SIZE_CURVE]
    exponents.append(MAX_PIECE_EXPONENT)

    assert all(16 <= exponent <= 27 for exponent in exponents)
