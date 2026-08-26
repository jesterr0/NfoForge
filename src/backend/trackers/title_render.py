"""Render a release title through a tracker's entry.

Two stages: compose from the entry (or the user's global template when it
has none), then normalise from the entry. This module is the normalisation
half.

Normalisation always applies, whether or not the entry composes, so the
seven trackers with no layout of their own still get their separator, colon
and vocabulary imposed on the user's house style.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from types import MappingProxyType

from src.backend.token_replacer import TokenReplacer
from src.backend.trackers.title_rules import (
    TITLE_RULES,
    Composition,
    ConditionalOrder,
    Designator,
    DynamicRangeRule,
    Normalisation,
    ReleaseProperties,
    Separator,
)
from src.backend.trackers.utils import dot_separate_title, strip_title_dots
from src.config.models import HdrType
from src.enums.token_replacer import ColonReplace
from src.enums.tracker_selection import TrackerSelection

_REPEATED_WHITESPACE = re.compile(r"\s{2,}")
# A key must not rewrite the release group, which is a name rather than a
# vocabulary term: a group called "DV" would otherwise ship as "DoVi" on any
# tracker mapping that value. Bounding on a preceding hyphen rules the tag
# out while still letting a key match where a tag abuts it on the right, as
# "H.265-GRP" does.
_TAG_SEPARATOR_LOOKBEHIND = r"(?<!-)"

# Whitespace left between the last rendered component and the group tag. The
# tag is the trailing "-<name>", and a group name may itself carry hyphens
# ("-D-Z0N3"), so this matches to the end rather than to the next hyphen. It
# anchors, so a legitimate interior " - " (ShareIsland joins its languages
# that way) is untouched.
_TRAILING_TAG_GAP = re.compile(r"\s+-(\S+)$")

# BeyondHD's DD exception: "DD5.1" closed up, where "DDP 5.1" stays spaced.
_DD_CHANNELS = re.compile(r"\bDD\s+(\d\.[01])")

# How NfoForge spells each identity, mirroring `{video_dynamic_range_type}`.
# Four of the eight are not written the way the identity is named -- HDR10 is
# "HDR", HDR10+ is "HDR10Plus", and the two Dolby Vision composites follow --
# so the identity name is not usable as a default. These spellings are what
# trackers expect: Aither's published "REMUX HDR HEVC" and LST's "REMUX DV
# HDR HEVC" both show it.
#
# They are also what an entry's vocabulary is written against: the three
# trackers publishing "HDR10+" map it from "HDR10Plus".
_DEFAULT_SPELLINGS: Mapping[HdrType, str] = MappingProxyType(
    {
        "SDR": "SDR",
        "PQ": "PQ",
        "HLG": "HLG",
        "HDR10": "HDR",
        "HDR10+": "HDR10Plus",
        "DV": "DV",
        "DV HDR10": "DV HDR",
        "DV HDR10+": "DV HDR10Plus",
    }
)


def normalise_title(
    title: str,
    normalisation: Normalisation,
    *,
    global_colon: ColonReplace,
) -> str:
    """Apply a tracker's always-on rules to a composed title.

    Four stages, in this order:

    1. **Colon**, from the entry where it names one and from the user's
       global title setting otherwise. That is field-level precedence, the
       same rule that governs layout. It runs before the separator because
       three of the five colon forms insert a space, and on a dotted entry
       a space is exactly what must not survive: replacing after dotting
       gave SeedPool "Movie.Name - .The.Subtitle".
    2. **Separator**, so every later stage sees the form the tracker will
       actually receive -- and, for a dotted entry, so the spaces stage 1
       introduced become periods like any other.
    3. **Vocabulary**, plain rewrites then conditional ones. Both spellings
       of a spaced key ("H 265") need the separator to have run.
    4. **Allowlist**, last, so a rewrite cannot reintroduce a character the
       tracker forbids.
    """
    colon = normalisation.colon if normalisation.colon is not None else global_colon
    # Reused rather than reimplemented: a second definition of what a colon
    # becomes is exactly the kind of drift this design removes, and the
    # filename side already owns one.
    result = TokenReplacer._colon_replace(colon, title)

    if normalisation.separator is Separator.DOTTED:
        result = dot_separate_title(result)
    else:
        result = strip_title_dots(result)

    for match, replacement in normalisation.vocabulary.items():
        result = _rewrite(result, match, replacement)

    for rule in normalisation.conditional_vocabulary:
        if rule.unless_present in result:
            continue
        result = _rewrite(result, rule.match, rule.replacement)

    if normalisation.glue_dd_to_channels:
        # `\bDD\s` is what keeps this off `DDP 5.1`, which the same rule
        # leaves spaced: the character after `DD` there is `P`, not a space.
        result = _DD_CHANNELS.sub(r"DD\1", result)

    if normalisation.allowlist is not None:
        result = re.sub(rf"[^{normalisation.allowlist}]+", "", result)
        # Removing a character that sat between a space and a period leaves
        # " ." behind. The allowlist permits the period, so nothing else
        # takes it out, and the separator stage has already run.
        result = result.replace(" .", ".").replace("..", ".")

    result = _REPEATED_WHITESPACE.sub(" ", result).strip()
    # A component that renders empty leaves a gap. Collapsing runs of spaces
    # closes it everywhere except against the tag, where one space plus the
    # tag's own hyphen is not a run -- so "DTS-HD MA 7.1 -GRP" survived it.
    # The last component of a remux order is `{atmos}`, which is empty on
    # every non-Atmos remux, so this was the common case rather than an edge.
    return _TRAILING_TAG_GAP.sub(r"-\1", result)


def compose_token_string(
    composition: Composition,
    release: ReleaseProperties,
    custom_strings: Mapping[HdrType, str] | None = None,
) -> str:
    """Build the token string a tracker's own layout asks for.

    Returns a token string rather than a rendered title, so composition
    stays pure: no MediaInfo, no TokenReplacer, no online metadata. The
    caller renders it once and normalises the result.

    Two things a reader might expect here and will not find. Unresolved
    components are not removed -- the renderer's `TOKEN_ONLY` mode already
    does that, and every component is conditional on its token resolving.
    Nor is the gap one leaves behind closed here; normalisation does that
    for every entry, including the gaps an omit rule and a suppressed
    vocabulary value leave.
    """
    omitted = {
        component
        for rule in composition.omit
        if rule.when(release)
        for component in rule.components
    }

    parts: list[str] = []
    for component in composition.components:
        for token in _expand(component, release, custom_strings):
            if token and token not in omitted:
                parts.append(token)

    token_string = " ".join(parts)
    if not token_string:
        return ""

    # The tag is written as an optional prefix so it disappears with the
    # group rather than leaving a trailing hyphen.
    if composition.tag_default is not None:
        return (
            f"{token_string}"
            f"{{:opt=-:release_group|default('{composition.tag_default}')}}"
        )
    return f"{token_string}{{:opt=-:release_group}}"


def render_tracker_title(
    tracker: TrackerSelection,
    release: ReleaseProperties,
    *,
    render: Callable[[str], str | None],
    global_template: str,
    global_colon: ColonReplace,
    custom_strings: Mapping[HdrType, str] | None = None,
) -> str | None:
    """One tracker's release title: compose, render, normalise.

    Field-level precedence in one place. The entry's composition governs
    where it has one and the user's global template applies otherwise;
    likewise the entry's colon, then the user's. That is the whole of what
    a tracker imposes and what a user keeps.

    Returns ``None`` where nothing rendered, which the caller turns into
    either a refusal or a fallback depending on whether the entry composes.
    A tracker with no release name field returns ``None`` immediately --
    there is nothing to shape.
    """
    entry = TITLE_RULES.get(tracker)
    if entry is None:
        # Not a tracker NfoForge ships. Render the user's template with no
        # rules imposed rather than guessing at any.
        return render(global_template) or None

    if not entry.has_release_name_field:
        return None

    if entry.composition is not None:
        token_string = compose_token_string(entry.composition, release, custom_strings)
    else:
        token_string = global_template

    rendered = render(token_string)
    if not rendered:
        return None

    normalised = normalise_title(
        rendered, entry.normalisation, global_colon=global_colon
    )
    return normalised or None


def resolve_dynamic_range(
    rule: DynamicRangeRule,
    release: ReleaseProperties,
    custom_strings: Mapping[HdrType, str] | None = None,
) -> str:
    """State a release's dynamic range the way one tracker wants it.

    Identity first, spelling last. The release already resolved to one of
    the eight identities; this decides whether the tracker states it, and
    only then how it is written.

    Takes no `DynamicRangeSettings`. Its `resolutions` and `hdr_types`
    switches blank the component by resolution or by type, which belongs to
    filenames: a tracker rule cannot be subject to a user toggle, and
    BeyondHD requires SDR on a 2160p WEB release from a user who may have
    SDR switched off. Only `custom_strings` reaches here, because a
    spelling preference is not a rule.
    """
    identity = release.hdr_identity
    above_1080 = release.resolution > 1080

    if identity == "SDR" and not (above_1080 and rule.emit_sdr_above_1080):
        return ""

    if (
        rule.assumes_hdr10_on_disc_or_remux
        and above_1080
        and (release.is_disc or release.is_remux)
    ):
        # The baseline is dropped, not rewritten: HDR10 was assumed, so
        # stating it says nothing. HDR10+ and DV HDR10+ are untouched
        # because neither is plain HDR10.
        if identity == "HDR10":
            return ""
        if identity == "DV HDR10":
            identity = "DV"

    if identity in rule.spellings:
        return rule.spellings[identity] or ""

    return (custom_strings or {}).get(identity, "") or _DEFAULT_SPELLINGS[identity]


def _expand(
    component: object,
    release: ReleaseProperties,
    custom_strings: Mapping[HdrType, str] | None,
) -> tuple[str, ...]:
    """One component as the token strings it stands for."""
    if isinstance(component, ConditionalOrder):
        # Recursive because a branch holds components rather than plain
        # tokens: what moves between a remux order and an encode order is
        # the dynamic range as much as the codec.
        branch = component.then if component.when(release) else component.otherwise
        return tuple(
            token for item in branch for token in _expand(item, release, custom_strings)
        )
    if isinstance(component, Designator):
        designator = _designator(component, release)
        return (designator,) if designator else ()
    if isinstance(component, DynamicRangeRule):
        dynamic_range = resolve_dynamic_range(component, release, custom_strings)
        return (dynamic_range,) if dynamic_range else ()
    return (str(component),)


def _designator(style: Designator, release: ReleaseProperties) -> str:
    """The season/episode designator, computed rather than rendered.

    `{episode_number}` renders per the user's `multi_episode_style`, which
    is theirs to choose for filenames. A tracker that mandates a form needs
    its own, so this is a literal rather than a token.
    """
    if release.season is None:
        return ""

    season = f"S{release.season:02d}"
    episodes = release.episodes
    if not episodes:
        return season

    first, last = episodes[0], episodes[-1]
    if first == last:
        return f"{season}E{first:02d}"
    if style is Designator.BANDED_BY_COUNT and len(episodes) == 2:
        return f"{season}E{first:02d}E{last:02d}"
    return f"{season}E{first:02d}-{last:02d}"


def _rewrite(title: str, match: str, replacement: str | None) -> str:
    """Replace one whole value, or remove it when `replacement` is None.

    Word-bounded rather than a substring replace, so a key of "DV" leaves
    "DVDRip" alone, and rather than whole space-delimited components, so a
    key still matches where the group tag abuts it.
    """
    pattern = rf"{_TAG_SEPARATOR_LOOKBEHIND}\b{re.escape(match)}\b"
    return re.sub(pattern, replacement if replacement is not None else "", title)
