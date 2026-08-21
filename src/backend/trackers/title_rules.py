"""Hardcoded release title rules, one entry per tracker.

The filename is the user's; the release title is the tracker's. A tracker
whose rules are known gets them imposed here rather than offered as a
setting that enforcement would override anyway.

One entry per tracker, with no inheritance between them. Two entries that
are currently identical stay written out separately: a tracker changing its
rules must not require unpicking a shared abstraction, and must not be able
to alter another tracker by accident. That is not a hypothetical -- the
shipped config's worst defect was a template copied between two trackers
whose published rules differ, which propagated an error into a tracker that
never shared those rules. `test_no_two_entries_share_an_object` pins it.

An entry has two sections. Normalisation always applies. Composition is
optional -- seven trackers have none and render the user's global title
template, which is exactly what they do today.

A tracker rule never reaches a filename. Every rule lives in an entry, never
in a token handler: handlers are shared, and `file_name_mode` selects only
the final formatting stage, so a handler edited to satisfy a tracker would
change every user's filenames as a side effect.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection


class Separator(StrEnum):
    """How components are joined in the final string."""

    SPACED = "spaced"
    DOTTED = "dotted"


@dataclass(frozen=True, slots=True)
class Normalisation:
    """Rules that always apply, whether or not the entry composes.

    `colon` of ``None`` means "use the user's global title colon setting".
    An entry only names a value where the tracker has a rule, so the two
    states stay distinguishable: naming `KEEP` imposes it, naming nothing
    defers.

    `vocabulary` maps a rendered component to a replacement, or to ``None``
    to suppress it. An absent key is a deliberate state, not an oversight
    to be filled in later with a guess: it means NfoForge's own value is
    emitted unchanged.

    `allowlist` is a regex character class of what may survive. Only HDBits
    publishes one; ``None`` means no character filtering, and inventing one
    for another tracker would strip punctuation its own examples carry.
    """

    separator: Separator = Separator.SPACED
    colon: ColonReplace | None = None
    vocabulary: Mapping[str, str | None] = field(default_factory=dict)
    allowlist: str | None = None


@dataclass(frozen=True, slots=True)
class Composition:
    """A tracker's own component layout.

    Fields land in the composition task. Until then an entry carrying one
    would have nothing to say, so every entry below leaves it ``None`` and
    renders the user's global template -- which is what they all do today.
    """


@dataclass(frozen=True, slots=True)
class TrackerTitleEntry:
    """One tracker's title rules.

    `has_release_name_field` of ``False`` means the upload carries no
    release name in the mode NfoForge uses, so nothing is composed,
    normalised, or offered for review.
    """

    normalisation: Normalisation
    composition: Composition | None = None
    has_release_name_field: bool = True


# Every entry is constructed inline. Two that read alike are still two
# objects, so editing one cannot reach the other.
TITLE_RULES: Mapping[TrackerSelection, TrackerTitleEntry] = MappingProxyType(
    {
        # -- no release name field ------------------------------------------
        # PTP derives its release from structured fields plus the name inside
        # the torrent; HUNO auto mode builds its name from the torrent
        # filename, MediaInfo and TMDB. Neither has anything for a title to
        # shape.
        TrackerSelection.PASS_THE_POPCORN: TrackerTitleEntry(
            normalisation=Normalisation(),
            has_release_name_field=False,
        ),
        TrackerSelection.HUNO: TrackerTitleEntry(
            normalisation=Normalisation(),
            has_release_name_field=False,
        ),
        # -- normalisation only ---------------------------------------------
        # SeedPool names uploads after the release, so it wants the dotted
        # form the rest of the UNIT3D family strips.
        TrackerSelection.SEEDPOOL: TrackerTitleEntry(
            normalisation=Normalisation(separator=Separator.DOTTED),
        ),
        TrackerSelection.TORRENT_LEECH: TrackerTitleEntry(
            normalisation=Normalisation(),
        ),
        TrackerSelection.BLUTOPIA: TrackerTitleEntry(
            normalisation=Normalisation(),
        ),
        TrackerSelection.UTOPIA: TrackerTitleEntry(
            normalisation=Normalisation(),
        ),
        TrackerSelection.YU_SCENE: TrackerTitleEntry(
            normalisation=Normalisation(),
        ),
        TrackerSelection.FEAR_NO_PEER: TrackerTitleEntry(
            normalisation=Normalisation(),
        ),
        # HDBits is the most heavily normalised tracker in the codebase and
        # has no layout template at all, which is why composition had to be
        # optional rather than assumed.
        #
        # "H 265" is spelled with a space because a key is matched against
        # the title *after* dot stripping, where "H.265-GRP" has become
        # "H 265-GRP". That also settles how keys match: on word boundaries
        # rather than on whole space-delimited components, since the
        # components there are "H" and "265-GRP" and neither is the key.
        # Word boundaries still leave "DVDRip" alone, which is what a
        # component rule was reaching for.
        #
        # The HDR -> HDR10 rewrite is deliberately absent: it is conditional
        # on HDR10+ being missing, and a flat map cannot express a
        # condition. It lands with the normalisation stage, condition
        # intact.
        TrackerSelection.HDB: TrackerTitleEntry(
            normalisation=Normalisation(
                vocabulary={
                    "H 265": "HEVC",
                    "DV": "DoVi",
                    "REMUX": "Remux",
                },
                allowlist=r"0-9a-zA-ZÀ-ÿ. :&+'\-\[\]",
            ),
        ),
        # -- composing entries ----------------------------------------------
        # Their compositions land in a later task. Until then each carries
        # normalisation only, which is its current behaviour.
        TrackerSelection.LST: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.KEEP),
        ),
        TrackerSelection.AITHER: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.KEEP),
        ),
        TrackerSelection.REELFLIX: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.KEEP),
        ),
        TrackerSelection.BEYOND_HD: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.KEEP),
        ),
        TrackerSelection.DARK_PEERS: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.REPLACE_WITH_DASH),
        ),
        TrackerSelection.SHARE_ISLAND: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.REPLACE_WITH_DASH),
        ),
        TrackerSelection.UPLOAD_CX: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.REPLACE_WITH_DASH),
        ),
        TrackerSelection.ONLY_ENCODES: TrackerTitleEntry(
            normalisation=Normalisation(colon=ColonReplace.REPLACE_WITH_DASH),
        ),
    }
)
