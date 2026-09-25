"""Piece size selection for the neutral base torrent.

One curve, applied to every torrent regardless of which trackers are in the run.

A run hashes the media once and stamps that base for every tracker, so a single
piece size has to serve all of them. mkbrr stores two different things per
tracker: ``PieceSizeRanges`` prescribes an *exact* exponent per content-size
band, and ``MaxPieceLength`` is a hard ceiling. The ranges conflict between
trackers -- at 10 GiB, LST wants 2^22 and TorrentLeech wants 2^23 -- so matching
mkbrr's preferred exponent per tracker is not achievable while sharing a hash.
Delegating the choice to mkbrr is not possible either: every lookup in its
``internal/trackers/trackers.go`` takes a single tracker URL and returns the
first substring match, so passing several ``-t`` flags applies one tracker's
rules and silently ignores the rest.

The ceiling is the part that actually gets an upload rejected, and it *is*
satisfiable by a fixed curve. The lowest ``MaxPieceLength`` across every tracker
NfoForge supports is 2^24, shared by BHD, PTP, HDB, LST and OnlyEncodes; Aither,
seedpool and TorrentLeech allow 2^27, HUNO and ULCX carry no limit, and the rest
are absent from mkbrr's table entirely. Nothing NfoForge uploads to is stricter
than 2^24, so a curve topping out there is legal everywhere. The limits that
would push in the opposite direction -- caps on the size of the ``.torrent``
file, which force pieces *larger* -- belong to ANT, NBL, GGN and AlphaRatio,
none of which NfoForge supports, so there is no opposing bound to balance.

The curve below uses mkbrr's TorrentLeech bands under 1 GiB so episode-sized
releases do not get coarse pieces, and its LST/Aither bands above, which top out
at exactly 2^24.

Fixed rather than computed per run, because a prepared job can be resumed with a
different tracker set (``keep_trackers`` already narrows one). An exponent
derived from the trackers present when the base was hashed could be wrong for
the set it is later stamped for, and adding a stricter tracker on resume would
leave the carried base violating its limit. A tracker-independent curve cannot
fail that way, and carrying a base across runs is the feature the neutral base
exists to protect.

Maintenance trigger: adding a tracker that caps the size of the ``.torrent``
file is the one case that requires revisiting this, since it is the only
constraint the curve does not already dominate. (At 2^24 a 100 GiB release
yields about a 128 KB ``.torrent``, and even ANT's 250 KiB limit -- the
strictest that exists -- would not bind until roughly 200 GiB of content.)
"""

_KIB = 1024
_MIB = 1024 * _KIB
_GIB = 1024 * _MIB

# The ceiling every tracker NfoForge supports allows, and torf's own
# `piece_size_max_default`. The whole policy rests on never exceeding it.
MAX_PIECE_EXPONENT = 24

# (inclusive upper bound on content size, exponent). Ordered smallest first;
# anything above the last bound gets MAX_PIECE_EXPONENT.
#
# Piece counts at the top of each band stay between 800 and 6400 across the
# entire range, and the exponents are monotonic:
#
#   50 MiB / 64 KiB    =  800      4 GiB / 2 MiB  = 2048
#   150 MiB / 128 KiB  = 1200     12 GiB / 4 MiB  = 3072
#   350 MiB / 256 KiB  = 1400     20 GiB / 8 MiB  = 2560
#   512 MiB / 512 KiB  = 1024    100 GiB / 16 MiB = 6400
#   1 GiB / 1 MiB      = 1024
_PIECE_SIZE_CURVE: tuple[tuple[int, int], ...] = (
    (50 * _MIB, 16),  # 64 KiB
    (150 * _MIB, 17),  # 128 KiB
    (350 * _MIB, 18),  # 256 KiB
    (512 * _MIB, 19),  # 512 KiB
    (1 * _GIB, 20),  # 1 MiB
    (4 * _GIB, 21),  # 2 MiB
    (12 * _GIB, 22),  # 4 MiB
    (20 * _GIB, 23),  # 8 MiB
)


def piece_exponent(content_size: int) -> int:
    """The piece size exponent for a release of `content_size` bytes.

    Returns ``n`` such that the piece length is ``2**n``. Both backends take
    this directly -- mkbrr as ``--piece-length n``, torf as
    ``piece_size=2**n`` -- so a torf fallback produces an identically shaped
    torrent rather than a differently shaped one.

    There is no tracker parameter: the curve is tracker-independent by
    construction (see the module docstring). The curve covers every content
    size, so neither backend ever falls back to its own default.
    """
    for upper_bound, exponent in _PIECE_SIZE_CURVE:
        if content_size <= upper_bound:
            return exponent
    return MAX_PIECE_EXPONENT
