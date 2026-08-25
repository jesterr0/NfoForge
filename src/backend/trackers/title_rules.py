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
optional -- nine entries have none. Seven of those render the user's global
title template, which is exactly what they do today; the remaining two
render no title at all, having no release name field to put one in.

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

    `glue_dd_to_channels` writes `DD 5.1` as `DD5.1`, BeyondHD's own
    exception. It is a flag rather than a `vocabulary` entry because the
    layout varies: a value map would need a row per layout, and each row
    would have to avoid matching `DDP 5.1`, which the same rule leaves
    spaced. Only BeyondHD publishes it.
    """

    separator: Separator = Separator.SPACED
    colon: ColonReplace | None = None
    vocabulary: Mapping[str, str | None] = field(default_factory=dict)
    conditional_vocabulary: tuple[ConditionalRewrite, ...] = ()
    allowlist: str | None = None
    glue_dd_to_channels: bool = False


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
    then: tuple[Component, ...]
    otherwise: tuple[Component, ...]


@dataclass(frozen=True, slots=True)
class DynamicRangeRule:
    """How one tracker states a release's dynamic range.

    Applied to the *identity* rather than to a rendered string. A rule such
    as "assume HDR10 on a disc or remux" is about what the release is --
    `DV HDR10` contains an assumed HDR10 and `DV HDR10+` does not -- and a
    rewrite over "DV HDR" would be inferring that from how it was spelled.

    `assumes_hdr10_on_disc_or_remux` drops the assumed baseline where the
    tracker takes HDR10 as read above 1080p: `HDR10` becomes nothing and
    `DV HDR10` becomes `DV`. The other identities pass through, including
    `PQ` and `HLG`, for which no rule was supplied and none is invented.

    `emit_sdr_above_1080` is the only place any entry states SDR. Below
    that it is never stated by anyone, which is convention rather than a
    published rule and so lives in the resolver.

    `spellings` is the tracker's published spelling for an identity, which
    outranks the user's. A value of ``None`` suppresses the component, as
    Aither does with `PQ`. An absent key means the tracker publishes no
    rule and the user's spelling stands.
    """

    assumes_hdr10_on_disc_or_remux: bool = False
    emit_sdr_above_1080: bool = False
    spellings: Mapping[HdrType, str | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OmitRule:
    """Components dropped when the release matches.

    LST and ReelFliX omit the resolution on a DVD source, and the video
    codec on a DVD remux while keeping it for a DVDRip encode.
    """

    when: Callable[[ReleaseProperties], bool]
    components: tuple[str, ...]


# A component is a token string, a run whose order depends on the release, or
# one of the two values computed rather than rendered.
Component = str | ConditionalOrder | Designator | DynamicRangeRule


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


# Questions about the release, shared freely between entries. A predicate is
# not a rule -- it asks what the release *is*, where a rule says what a
# tracker wants -- so sharing one couples nothing.
def _is_disc_or_remux(release: ReleaseProperties) -> bool:
    return release.is_disc or release.is_remux


def _is_dvd(release: ReleaseProperties) -> bool:
    return release.is_dvd


def _is_dvd_remux(release: ReleaseProperties) -> bool:
    return release.is_dvd and release.is_remux


def _is_series(release: ReleaseProperties) -> bool:
    return release.season is not None


# The Dub component, composable from tokens that already exist. Dual audio
# wins where present; a dubbed release says so; a subbed one is suppressed by
# the entry's vocabulary rather than by a token that refuses to render it.
_DUB = ("{audio_language_dual}", "{localization|unless(audio_language_dual)}")

# Components carry no `:opt= :` prefix. The shipped templates needed one to
# avoid a double space where a token did not resolve; normalisation closes
# that gap for every entry now, so the plain form is enough and reads as the
# published rules are written.

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
        # LST: "... Resolution ... SOURCE TYPE Hi10P HDR Vcodec Dub Acodec
        # Channels Object - Tag" on a disc or remux, and "... SOURCE TYPE Dub
        # Acodec Channels Object Hi10P HDR Vcodec - Tag" otherwise. Hi10P has
        # no token and is out of scope; its absence is a gap, not an
        # oversight.
        TrackerSelection.LST: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.KEEP,
                vocabulary={
                    "DDP": "DD+",
                    "HDR10Plus": "HDR10+",
                    "HYBRID": "Hybrid",
                    "Dual Audio": "Dual-Audio",
                    "Subbed": None,
                },
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.BANDED_BY_COUNT,
                    "{cut}",
                    "{frame_size}",
                    "{hybrid}",
                    "{re_release}",
                    "{resolution}",
                    "{streaming_service}",
                    "{source}",
                    "{remux}",
                    ConditionalOrder(
                        when=_is_disc_or_remux,
                        then=(
                            DynamicRangeRule(spellings={"PQ": "PQ10"}),
                            "{video_codec}",
                            *_DUB,
                            "{audio_codec_no_atmos}",
                            "{audio_channel_s}",
                            "{atmos}",
                        ),
                        otherwise=(
                            *_DUB,
                            "{audio_codec_no_atmos}",
                            "{audio_channel_s}",
                            "{atmos}",
                            DynamicRangeRule(spellings={"PQ": "PQ10"}),
                            "{video_codec}",
                        ),
                    ),
                ),
                tag_default="NOGROUP",
                omit=(
                    OmitRule(when=_is_series, components=("{release_year}",)),
                    OmitRule(when=_is_dvd, components=("{resolution}",)),
                    OmitRule(when=_is_dvd_remux, components=("{video_codec}",)),
                ),
            ),
        ),
        # Aither: "Title Year REPACK Resolution Source REMUX HDR VideoCodec
        # AudioCodec Channels Metadata-Crew" for a remux, with the audio
        # ahead of HDR and the codec otherwise. Its series shapes carry the
        # episode title, which LST's do not.
        TrackerSelection.AITHER: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.KEEP,
                vocabulary={
                    "DDP": "DD+",
                    "HDR10Plus": "HDR10+",
                    "HYBRID": "Hybrid",
                    "Dual Audio": "Dual-Audio",
                    "Subbed": None,
                },
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.SIMPLE,
                    "{episode_title_exact}",
                    "{cut}",
                    "{frame_size}",
                    "{hybrid}",
                    "{re_release}",
                    "{resolution}",
                    "{streaming_service}",
                    "{source}",
                    "{remux}",
                    ConditionalOrder(
                        when=_is_disc_or_remux,
                        then=(
                            DynamicRangeRule(spellings={"PQ": None}),
                            "{video_codec}",
                            *_DUB,
                            "{audio_codec_no_atmos}",
                            "{audio_channel_s}",
                            "{atmos}",
                        ),
                        otherwise=(
                            *_DUB,
                            "{audio_codec_no_atmos}",
                            "{audio_channel_s}",
                            "{atmos}",
                            DynamicRangeRule(spellings={"PQ": None}),
                            "{video_codec}",
                        ),
                    ),
                ),
                omit=(OmitRule(when=_is_series, components=("{release_year}",)),),
            ),
        ),
        # ReelFliX. Its shipped template was a near copy of BeyondHD's,
        # but its published rules match LST and Aither -- so every remux was
        # emitting audio before video where its rules require video first.
        # That defect is why entries do not share objects.
        TrackerSelection.REELFLIX: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.KEEP,
                vocabulary={
                    "DDP": "DD+",
                    "HDR10Plus": "HDR10+",
                    "HYBRID": "Hybrid",
                    "Dual Audio": "Dual-Audio",
                    "Subbed": None,
                },
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.SIMPLE,
                    "{cut}",
                    "{frame_size}",
                    "{hybrid}",
                    "{re_release}",
                    "{resolution}",
                    "{streaming_service}",
                    "{source}",
                    "{remux}",
                    ConditionalOrder(
                        when=_is_disc_or_remux,
                        then=(
                            DynamicRangeRule(spellings={"PQ": "PQ10"}),
                            "{video_codec}",
                            *_DUB,
                            "{audio_codec_no_atmos}",
                            "{audio_channel_s}",
                            "{atmos}",
                        ),
                        otherwise=(
                            *_DUB,
                            "{audio_codec_no_atmos}",
                            "{audio_channel_s}",
                            "{atmos}",
                            DynamicRangeRule(spellings={"PQ": "PQ10"}),
                            "{video_codec}",
                        ),
                    ),
                ),
                omit=(
                    OmitRule(when=_is_series, components=("{release_year}",)),
                    OmitRule(when=_is_dvd, components=("{resolution}",)),
                    OmitRule(when=_is_dvd_remux, components=("{video_codec}",)),
                ),
            ),
        ),
        # BeyondHD. Four differences from the shipped template, all from its
        # published rules:
        #
        # - audio is {audio_codec} plus channels, giving "DDP Atmos 5.1" as
        #   BeyondHD requires, not the "DDP 5.1 Atmos" the other three want.
        # - DDP is not rewritten to DD+; BHD uses DDP throughout.
        # - HYBRID sits against REMUX, since BeyondHD requires them adjacent.
        # - the DVD order is "MPEG-2 DD2.0", so the codec leads there
        #   where audio leads everywhere else.
        TrackerSelection.BEYOND_HD: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.KEEP,
                vocabulary={"HYBRID": "Hybrid"},
                glue_dd_to_channels=True,
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.SIMPLE,
                    "{cut}",
                    "{frame_size}",
                    "{re_release}",
                    "{resolution}",
                    "{streaming_service}",
                    "{source}",
                    "{hybrid}",
                    "{remux}",
                    ConditionalOrder(
                        when=_is_dvd,
                        then=(
                            "{video_codec}",
                            "{audio_codec}",
                            "{audio_channel_s}",
                        ),
                        otherwise=(
                            "{audio_codec}",
                            "{audio_channel_s}",
                            DynamicRangeRule(
                                emit_sdr_above_1080=True,
                                assumes_hdr10_on_disc_or_remux=True,
                            ),
                            "{video_codec}",
                        ),
                    ),
                ),
                tag_default="NOGROUP",
                omit=(OmitRule(when=_is_series, components=("{release_year}",)),),
            ),
        ),
        # The four below are transcribed from the shipped config rather than
        # from published rules, none having been gathered for them. What the
        # config says is copied rather than improved -- {edition} rather than
        # {cut}, undivided {audio_codec}, dash colon handling and the
        # over-1080 SDR form all stand.
        #
        # Two things do not come from the config, because the config had
        # nothing to say about either.
        #
        # Their shipped overrides cover films only, so a series on these
        # trackers used to render the user's global template. An entry has no
        # media-type split, so the composition now serves both, with the
        # designator supplying the season and episode and an episode title
        # beside it. Aither names the episode from its published examples;
        # only LST, ReelFliX and BeyondHD are known to leave it out.
        #
        # The title is {title_exact}, where the config said {title_clean}.
        # Clean answers to the user's `title_clean_rules`, which ship
        # aggressive: they unidecode, drop apostrophes and flatten every
        # non-alphanumeric to a space, so "Amelie's Cafe: Fire & Ice" reached
        # these four as "Amelies Cafe Fire and Ice" and reached the four with
        # gathered rules intact. Nothing published asks for that, a tracker
        # rule that varies with a user setting is not a rule, and the split
        # tracked which entries were transcribed rather than anything about
        # the trackers. The episode title matches at the same tier.
        TrackerSelection.DARK_PEERS: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.REPLACE_WITH_DASH,
                vocabulary={"DDP": "DD+", "HDR10Plus": "HDR10+"},
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.SIMPLE,
                    "{episode_title_exact}",
                    "{frame_size}",
                    "{edition}",
                    "{re_release}",
                    "{resolution}",
                    "{source}",
                    "{audio_codec}",
                    "{audio_channel_s}",
                    DynamicRangeRule(emit_sdr_above_1080=True),
                    "{video_codec}",
                ),
                omit=(OmitRule(when=_is_series, components=("{release_year}",)),),
            ),
        ),
        # ShareIsland alone carries a language component, immediately after
        # the year.
        TrackerSelection.SHARE_ISLAND: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.REPLACE_WITH_DASH,
                vocabulary={"DDP": "DD+", "HDR10Plus": "HDR10+"},
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.SIMPLE,
                    "{episode_title_exact}",
                    "{audio_language_all_full|upper|replace(' ',' - ')}",
                    "{frame_size}",
                    "{edition}",
                    "{re_release}",
                    "{resolution}",
                    "{source}",
                    "{audio_codec}",
                    "{audio_channel_s}",
                    DynamicRangeRule(emit_sdr_above_1080=True),
                    "{video_codec}",
                ),
                omit=(OmitRule(when=_is_series, components=("{release_year}",)),),
            ),
        ),
        TrackerSelection.UPLOAD_CX: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.REPLACE_WITH_DASH,
                vocabulary={"DDP": "DD+", "HDR10Plus": "HDR10+"},
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.SIMPLE,
                    "{episode_title_exact}",
                    "{frame_size}",
                    "{edition}",
                    "{re_release}",
                    "{resolution}",
                    "{source}",
                    "{audio_codec}",
                    "{audio_channel_s}",
                    DynamicRangeRule(emit_sdr_above_1080=True),
                    "{video_codec}",
                ),
                omit=(OmitRule(when=_is_series, components=("{release_year}",)),),
            ),
        ),
        TrackerSelection.ONLY_ENCODES: TrackerTitleEntry(
            normalisation=Normalisation(
                colon=ColonReplace.REPLACE_WITH_DASH,
                vocabulary={"DDP": "DD+", "HDR10Plus": "HDR10+"},
            ),
            composition=Composition(
                components=(
                    "{title_exact}",
                    "{release_year}",
                    Designator.SIMPLE,
                    "{episode_title_exact}",
                    "{frame_size}",
                    "{edition}",
                    "{re_release}",
                    "{resolution}",
                    "{source}",
                    "{audio_codec}",
                    "{audio_channel_s}",
                    DynamicRangeRule(emit_sdr_above_1080=True),
                    "{video_codec}",
                ),
                omit=(OmitRule(when=_is_series, components=("{release_year}",)),),
            ),
        ),
    }
)


def accepts_a_release_name(tracker: TrackerSelection) -> bool:
    """Whether an upload to `tracker` carries a release name at all.

    Was a frozenset beside the media-type support tables, which answers a
    different question. A tracker's title rules are one object now, and
    "there is no title" is one of them, so the answer comes from the entry
    rather than from a list that has to be kept in step with it.

    This is the accessor for a caller holding only a `TrackerSelection`.
    The renderer and `resolve_tracker_title` have the entry in hand already
    and read `has_release_name_field` off it directly.
    """
    entry = TITLE_RULES.get(tracker)
    return entry.has_release_name_field if entry is not None else True
