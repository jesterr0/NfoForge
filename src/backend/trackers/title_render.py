"""Render a release title through a tracker's entry.

Two stages, replacing the four rewriting layers that grew up separately:
compose from the entry (or the user's global template when it has none),
then normalise from the entry. This module is the normalisation half.

Normalisation always applies, whether or not the entry composes, so the
seven trackers with no layout of their own still get their separator,
colon and vocabulary imposed on the user's house style -- which is exactly
what they do today through their own `generate_release_title`.
"""

from __future__ import annotations

from collections.abc import Mapping
import re

from src.backend.token_replacer import TokenReplacer
from src.backend.trackers.title_rules import (
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

_REPEATED_WHITESPACE = re.compile(r"\s{2,}")
# A key must not rewrite the release group, which is a name rather than a
# vocabulary term: a group called "DV" would otherwise ship as "DoVi" on any
# tracker mapping that value. Bounding on a preceding hyphen rules the tag
# out while still letting a key match where a tag abuts it on the right, as
# "H.265-GRP" does.
_TAG_SEPARATOR_LOOKBEHIND = r"(?<!-)"


def normalise_title(
    title: str,
    normalisation: Normalisation,
    *,
    global_colon: ColonReplace,
) -> str:
    """Apply a tracker's always-on rules to a composed title.

    Four stages, in this order:

    1. **Separator**, first, so every later stage sees the form the tracker
       will actually receive. HDBits' "H.265" only looks like that once the
       dot-separated release form has been converted.
    2. **Colon**, from the entry where it names one and from the user's
       global title setting otherwise. That is field-level precedence, the
       same rule that governs layout.
    3. **Vocabulary**, plain rewrites then conditional ones.
    4. **Allowlist**, last, so a rewrite cannot reintroduce a character the
       tracker forbids.
    """
    if normalisation.separator is Separator.DOTTED:
        result = dot_separate_title(title)
    else:
        result = strip_title_dots(title)

    colon = normalisation.colon if normalisation.colon is not None else global_colon
    # Reused rather than reimplemented: a second definition of what a colon
    # becomes is exactly the kind of drift this design removes, and the
    # filename side already owns one.
    result = TokenReplacer._colon_replace(colon, result)

    for match, replacement in normalisation.vocabulary.items():
        result = _rewrite(result, match, replacement)

    for rule in normalisation.conditional_vocabulary:
        if rule.unless_present in result:
            continue
        result = _rewrite(result, rule.match, rule.replacement)

    if normalisation.allowlist is not None:
        result = re.sub(rf"[^{normalisation.allowlist}]+", "", result)
        # Removing a character that sat between a space and a period leaves
        # " ." behind. The allowlist permits the period, so nothing else
        # takes it out, and the separator stage has already run.
        result = result.replace(" .", ".").replace("..", ".")

    return _REPEATED_WHITESPACE.sub(" ", result).strip()


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

    # An identity's own value is its default spelling, so a tracker with no
    # rule and a user with no preference both land on the same string.
    return (custom_strings or {}).get(identity, "") or identity


def _expand(
    component: object,
    release: ReleaseProperties,
    custom_strings: Mapping[HdrType, str] | None,
) -> tuple[str, ...]:
    """One component as the token strings it stands for."""
    if isinstance(component, ConditionalOrder):
        return component.then if component.when(release) else component.otherwise
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
