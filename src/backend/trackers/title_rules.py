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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from src.config.models import HdrType
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection


class Separator(StrEnum):
    """How components are joined in the final string."""

    SPACED = "spaced"
    DOTTED = "dotted"


@dataclass(frozen=True, slots=True)
class ConditionalRewrite:
    """A rewrite that only fires when some other value is absent.

    `vocabulary` cannot express this: it maps a value to a replacement with
    no reference to the rest of the title. HDBits needs one -- a bare `HDR`
    means `HDR10`, but not in a title that already names `HDR10+` -- and a
    conditional rule kept as data stays in the entry, where a reader looking
    for that tracker's rules will find it, rather than becoming a branch in
    the shared renderer.
    """

    match: str
    replacement: str
    unless_present: str


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
    conditional_vocabulary: tuple[ConditionalRewrite, ...] = ()
    allowlist: str | None = None


class Designator(StrEnum):
    """How a season/episode designator states more than one episode.

    `SIMPLE` always states a range. `BANDED_BY_COUNT` is LST's rule:
    `S##E##E##` at exactly two episodes and `S##E##-##` above, which no
    single user `multi_episode_style` can satisfy -- which is why the
    designator is a composition field rather than that setting.
    """

    SIMPLE = "simple"
    BANDED_BY_COUNT = "banded_by_count"


@dataclass(frozen=True, slots=True)
class ReleaseProperties:
    """What a composition's conditions may ask about.

    A small closed set rather than the whole payload: a condition that can
    ask anything is a condition nobody can test exhaustively. Each field
    earns its place from a checked tracker -- `is_remux` and `is_disc` from
    the remux order swap and BeyondHD's dynamic range baseline, `is_dvd`
    from BeyondHD's DVD order and the LST and ReelFliX omit rules,
    `resolution` and `hdr_identity` from every dynamic range rule, and
    `season`/`episodes` from the designator.
    """

    is_remux: bool = False
    is_disc: bool = False
    is_dvd: bool = False
    resolution: int = 1080
    hdr_identity: HdrType = "SDR"
    season: int | None = None
    episodes: tuple[int, ...] = ()

    @property
    def episode_count(self) -> int:
        return len(self.episodes)


@dataclass(frozen=True, slots=True)
class ConditionalOrder:
    """A run of components whose order or membership depends on the release.

    LST, Aither and ReelFliX put the video components before the audio ones
    on a remux and after them otherwise. BeyondHD swaps on DVD instead, so
    the condition is a predicate over the release rather than a remux flag.
    """

    when: Callable[[ReleaseProperties], bool]
    then: tuple[str, ...]
    otherwise: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OmitRule:
    """Components dropped when the release matches.

    LST and ReelFliX omit the resolution on a DVD source, and the video
    codec on a DVD remux while keeping it for a DVDRip encode.
    """

    when: Callable[[ReleaseProperties], bool]
    components: tuple[str, ...]


# A component is a token string, a run whose order depends on the release,
# or a designator that is computed rather than rendered.
Component = str | ConditionalOrder | Designator


@dataclass(frozen=True, slots=True)
class Composition:
    """A tracker's own component layout.

    `components` is one ordered sequence rather than a base list plus
    separate conditional, episode-title and designator fields. The published
    rules *are* an ordered component list, so the data mirrors the source
    material -- and a separate "include the episode title" flag would be
    strictly less expressive, since it could not say where in the order the
    title goes. Aither carries one and LST does not; that difference is
    membership in this tuple.

    `tag_default` of ``None`` omits the release group entirely where a
    release has none, which is what Aither and ReelFliX prefer. LST and
    BeyondHD want the `NOGROUP` placeholder instead.
    """

    components: tuple[Component, ...] = ()
    tag_default: str | None = None
    omit: tuple[OmitRule, ...] = ()


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
        # HDBits is alone in wanting HEVC where NfoForge emits H.265; it
        # takes H.264 as written, which is why only one of the pair is
        # mapped. Keys are matched after dot stripping, which preserves a
        # codec's internal period, so "H.265" is the spelling that arrives
        # from NfoForge's own token. The other two are reachable because
        # HDBits has no composition and renders the user's global template,
        # where the codec can be typed by hand.
        TrackerSelection.HDB: TrackerTitleEntry(
            normalisation=Normalisation(
                vocabulary={
                    "H.265": "HEVC",
                    "H 265": "HEVC",
                    "H265": "HEVC",
                    "DV": "DoVi",
                    "REMUX": "Remux",
                },
                conditional_vocabulary=(
                    ConditionalRewrite(
                        match="HDR", replacement="HDR10", unless_present="HDR10+"
                    ),
                ),
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
