"""Pure, Qt-free helpers for matching media files to provider episodes.

Kept free of any Qt import so the matching rules can be unit tested without a
``QApplication``, mirroring ``tvdb_episodes.py`` next door. The widget in
``src/frontend/custom_widgets/series_episode_mapper.py`` is the main caller.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from rapidfuzz import fuzz


def expand_mapping_episodes(mapping: Mapping[str, Any]) -> list[int]:
    """Every episode number a single mapping row covers, ascending.

    This is the one definition of "what does this row claim". Three readers
    used to answer it differently: the mapper's validation and
    ``build_series_release_info`` both expanded ``episode``..``episode_end``
    as a range, which over-claims a non-contiguous span -- a file recorded as
    ``episode_list=[1, 5]`` carries ``episode_end=5``, and a range reads that
    as five episodes rather than two. ``episode_list`` is authoritative
    wherever it is present precisely because the ends alone cannot describe
    such a span.

    A row whose ``episode_end`` sits *below* its ``episode`` claims just the
    one episode. That shape is reachable by editing the start of a span, and
    expanding it as a range yielded an empty list -- a row that claimed
    nothing at all yet still satisfied validation.

    Returns an empty list only when the row carries no usable episode number,
    which callers treat as "unresolved" rather than "claims nothing".
    """
    episode_list = mapping.get("episode_list")
    if episode_list:
        numbers = {
            int(number)
            for number in episode_list
            if isinstance(number, int) and not isinstance(number, bool)
        }
        if numbers:
            return sorted(numbers)

    episode = mapping.get("episode")
    if not isinstance(episode, int) or isinstance(episode, bool):
        return []

    episode_end = mapping.get("episode_end")
    if (
        isinstance(episode_end, int)
        and not isinstance(episode_end, bool)
        and episode_end > episode
    ):
        return list(range(episode, episode_end + 1))

    return [episode]


def claimed_season_episodes(
    mapping: Mapping[str, Any],
) -> list[tuple[Any, int]]:
    """``(season, episode)`` pairs a row claims, for overlap detection."""
    season = mapping.get("season")
    return [(season, episode) for episode in expand_mapping_episodes(mapping)]


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """What one input filename claims, as far as parsing could tell."""

    season: int | None
    episodes: tuple[int, ...]
    title: str | None = None


@dataclass(frozen=True, slots=True)
class OrderingScore:
    """How well one TVDB ordering fits the files being mapped."""

    type_id: Any
    type_name: str
    api_type: str
    episode_count: int
    claims_total: int
    claims_matched: int
    titles_compared: int
    title_agreement: float

    @property
    def coverage(self) -> float:
        """Fraction of claimed episodes this ordering actually lists."""
        if not self.claims_total:
            return 0.0
        return self.claims_matched / self.claims_total

    @property
    def has_title_evidence(self) -> bool:
        return self.titles_compared >= _MIN_TITLE_SAMPLES

    def summary(self) -> str:
        """One line of evidence, for the ordering combo."""
        parts = [f"{self.episode_count} eps"]
        if self.claims_total:
            parts.append(f"{self.claims_matched}/{self.claims_total} matched")
        if self.has_title_evidence:
            parts.append(f"titles {self.title_agreement:.0f}%")
        return " · ".join(parts)


#: Below this many comparable titles the agreement figure is noise, so it is
#: not allowed to decide between two orderings.
_MIN_TITLE_SAMPLES = 2

#: A parsed title shorter than this carries no signal worth comparing.
_MIN_TITLE_LENGTH = 3

_PLACEHOLDER_TITLE_RE = re.compile(r"^(?:tba|tbd|episode\s*\d+)$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_title(text: str | None) -> str:
    """Casefold a title down to letters, digits and single spaces.

    "&" becomes "and" rather than being dropped, because a provider writes
    "Lost & Found" where a release writes "Lost.and.Found" -- the same title
    spelled two ways, which scored as a near miss when the ampersand simply
    vanished. This is the same substitution the packaged title-clean rules
    make on the way out.
    """
    if not text:
        return ""
    expanded = str(text).lower().replace("&", " and ")
    return _NON_ALNUM_RE.sub(" ", expanded).strip()


def is_placeholder_title(text: str | None) -> bool:
    """Whether a provider title is a stand-in ("TBA", "Episode 12")."""
    if not text:
        return False
    return bool(_PLACEHOLDER_TITLE_RE.match(str(text).strip()))


def comparable_title(text: str | None) -> str | None:
    """A normalized title worth comparing, or ``None`` if there is no signal."""
    if is_placeholder_title(text):
        return None
    normalized = normalize_title(text)
    if len(normalized) < _MIN_TITLE_LENGTH:
        return None
    return normalized


def title_similarity(left: str | None, right: str | None) -> float:
    """Similarity of two episode titles, 0-100.

    One definition shared by the ordering scorer, the per-row corroborator
    and fuzzy matching, so the three cannot drift apart. Takes the best of
    three rapidfuzz scorers: a filename may hold the title verbatim, may hold
    it with extra release words around it, or may hold its words reordered.
    """
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return max(
        fuzz.ratio(left_normalized, right_normalized),
        fuzz.partial_ratio(left_normalized, right_normalized),
        fuzz.token_sort_ratio(left_normalized, right_normalized),
    )


def index_episodes(
    episodes: Sequence[Mapping[str, Any]],
) -> dict[int, dict[int, Mapping[str, Any]]]:
    """Index a provider episode list by season, then episode number."""
    indexed: dict[int, dict[int, Mapping[str, Any]]] = {}
    for episode_data in episodes:
        season = episode_data.get("seasonNumber")
        number = episode_data.get("number")
        if season is None or number is None:
            continue
        indexed.setdefault(season, {}).setdefault(number, episode_data)
    return indexed


def score_episode_ordering(
    parsed_files: Sequence[ParsedFile],
    episodes: Sequence[Mapping[str, Any]],
    type_id: Any = None,
    type_name: str = "",
    api_type: str = "",
) -> OrderingScore:
    """Measure how well one provider ordering explains these filenames.

    Two independent signals:

    *Coverage* counts every episode the files claim, not one per file, so an
    ordering that merges a two-part premiere into a single entry is penalised
    twice for it -- once for the part it does not list, and again at the end
    of the season, which is now one episode short of what the release names.

    *Title agreement* is the tiebreak, and it is the signal that actually
    discriminates: two orderings of the same season usually both contain an
    episode 3, so coverage cannot tell them apart, but only one of them calls
    it what the filename calls it.
    """
    indexed = index_episodes(episodes)

    claims_total = 0
    claims_matched = 0
    scores: list[float] = []

    for parsed in parsed_files:
        if parsed.season is None or not parsed.episodes:
            continue

        season_episodes = indexed.get(parsed.season, {})
        for number in parsed.episodes:
            claims_total += 1
            if number in season_episodes:
                claims_matched += 1

        file_title = comparable_title(parsed.title)
        if file_title is None:
            continue

        # Compare against the episode the file's own first number points at:
        # the question is whether this ordering agrees with the filename,
        # not whether the title appears anywhere in the season.
        episode_data = season_episodes.get(parsed.episodes[0])
        if episode_data is None:
            continue
        provider_title = comparable_title(episode_data.get("name"))
        if provider_title is None:
            continue
        scores.append(title_similarity(file_title, provider_title))

    return OrderingScore(
        type_id=type_id,
        type_name=type_name or str(type_id),
        api_type=api_type,
        episode_count=len(episodes),
        claims_total=claims_total,
        claims_matched=claims_matched,
        titles_compared=len(scores),
        title_agreement=(sum(scores) / len(scores)) if scores else 0.0,
    )


def rank_episode_orderings(
    parsed_files: Sequence[ParsedFile],
    episodes_by_type: Mapping[Any, Mapping[str, Any]],
    prefer_type_id: Any = None,
    allow_absolute: bool = False,
) -> list[OrderingScore]:
    """Rank the provider's orderings best-fit first.

    The ordering used to be whichever one the provider happened to serve
    first, which is not a choice at all: the same season/episode pair names a
    different episode in each ordering, so picking wrong renames every file
    after the first divergence, silently and at full confidence.

    ``prefer_type_id`` wins any tie -- it is the ordering a resumed job or an
    existing mapping already committed to, and switching away from it would
    quietly re-point work the user has already approved.

    Absolute order is excluded unless ``allow_absolute``: it flattens a whole
    series into one season, so on a mid-season pack it can out-cover the
    ordering the release was actually numbered in.
    """
    scores: list[OrderingScore] = []
    for type_id, type_data in episodes_by_type.items():
        api_type = str(type_data.get("type", "")).lower()
        type_name = str(type_data.get("type_name", f"Type {type_id}"))
        if not allow_absolute and (
            "absolute" in api_type or "absolute" in type_name.lower()
        ):
            continue

        scores.append(
            score_episode_ordering(
                parsed_files,
                type_data.get("episodes", []),
                type_id=type_id,
                type_name=type_name,
                api_type=api_type,
            )
        )

    positions = {type_id: index for index, type_id in enumerate(episodes_by_type)}

    def sort_key(score: OrderingScore) -> tuple[Any, ...]:
        return (
            -round(score.coverage, 4),
            # Title agreement only votes where enough titles were comparable.
            -round(score.title_agreement if score.has_title_evidence else 0.0, 2),
            # Deterministic from here: the committed ordering, then aired
            # order, then the provider's own order.
            0 if _same_type_id(score.type_id, prefer_type_id) else 1,
            0 if score.api_type == "official" else 1,
            positions.get(score.type_id, len(positions)),
        )

    return sorted(scores, key=sort_key)


def _same_type_id(left: Any, right: Any) -> bool:
    """Compare ordering ids across a JSON round-trip, which stringifies keys."""
    if left is None or right is None:
        return False
    return left == right or str(left) == str(right)


def episode_spec_text(mapping: Mapping[str, Any]) -> str:
    """Render the episodes a row covers the way a user would type them.

    ``1``, ``1-2`` for a contiguous span, ``1,5`` for a non-contiguous one.
    An empty string means the row carries no usable episode number.
    """
    episodes = expand_mapping_episodes(mapping)
    if not episodes:
        return ""
    if len(episodes) == 1:
        return str(episodes[0])
    if episodes == list(range(episodes[0], episodes[-1] + 1)):
        return f"{episodes[0]}-{episodes[-1]}"
    return ",".join(str(number) for number in episodes)


def episode_designator(mapping: Mapping[str, Any]) -> str:
    """``S01E03`` / ``S01E01-E02`` / ``S01E01,E05`` for display.

    A contiguous span is written as a range and a non-contiguous one is
    listed, so the two are never confused: writing ``[1, 5]`` as
    ``S01E01-E05`` would claim four episodes the file does not hold.
    """
    episodes = expand_mapping_episodes(mapping)
    season = mapping.get("season")
    if not episodes or not isinstance(season, int):
        return ""

    if len(episodes) == 1:
        body = f"E{episodes[0]:02d}"
    elif episodes == list(range(episodes[0], episodes[-1] + 1)):
        body = f"E{episodes[0]:02d}-E{episodes[-1]:02d}"
    else:
        body = ",".join(f"E{number:02d}" for number in episodes)

    return f"S{season:02d}{body}"


#: Below this, a filename's title and the episode it was bound to are saying
#: different things. Between here and a clean match sits ordinary filename
#: mangling -- abbreviations, dropped articles, transliteration -- which is
#: not evidence of anything.
TITLE_DISAGREEMENT_FLOOR = 50.0

#: A different episode has to match this well before it is worth naming. The
#: useful signal is not "this row scores badly" but "this row's title belongs
#: to that other episode", which is what an ordering mismatch looks like.
TITLE_SUGGESTION_FLOOR = 85.0


@dataclass(frozen=True, slots=True)
class TitleCheck:
    """Whether a filename's own episode title backs up the episode it hit."""

    score: float | None = None
    suggested_episode: int | None = None
    suggested_score: float = 0.0

    @property
    def has_opinion(self) -> bool:
        """False when there was nothing comparable on one side or the other."""
        return self.score is not None

    @property
    def disagrees(self) -> bool:
        return self.score is not None and self.score < TITLE_DISAGREEMENT_FLOOR

    @property
    def points_elsewhere(self) -> bool:
        return self.disagrees and self.suggested_episode is not None


def check_title_against_episode(
    parsed_title: str | None,
    season_episodes: Mapping[int, Mapping[str, Any]],
    bound_episode: int,
) -> TitleCheck:
    """Compare a filename's episode title with the episode its number hit.

    Returns "no opinion" rather than "disagrees" whenever either side has
    nothing comparable -- an unparseable filename or a provider placeholder
    such as "TBA" is silence, not evidence, and treating it as evidence would
    paint most anime and most unaired packs amber for no reason.
    """
    file_title = comparable_title(parsed_title)
    if file_title is None:
        return TitleCheck()

    bound = season_episodes.get(bound_episode)
    if bound is None:
        return TitleCheck()

    bound_title = comparable_title(bound.get("name"))
    if bound_title is None:
        return TitleCheck()

    score = title_similarity(file_title, bound_title)
    if score >= TITLE_DISAGREEMENT_FLOOR:
        return TitleCheck(score=score)

    best_episode: int | None = None
    best_score = TITLE_SUGGESTION_FLOOR
    for number, episode_data in season_episodes.items():
        if number == bound_episode:
            continue
        other_title = comparable_title(episode_data.get("name"))
        if other_title is None:
            continue
        other_score = title_similarity(file_title, other_title)
        if other_score >= best_score:
            best_episode, best_score = number, other_score

    if best_episode is None:
        return TitleCheck(score=score)
    return TitleCheck(
        score=score, suggested_episode=best_episode, suggested_score=best_score
    )


#: A span wider than this is a typo, not a file. Guards against "1-9999"
#: allocating a list nobody asked for.
MAX_SPAN_WIDTH = 50

_SPEC_TOKEN_RE = re.compile(
    r"^(?:s\d+)?e?(?P<start>\d{1,4})(?:\s*[-–—]\s*(?:s\d+)?e?(?P<end>\d{1,4}))?$",
    re.IGNORECASE,
)


def parse_episode_spec(text: str) -> list[int] | None:
    """Read the episodes a user typed into the Episode cell.

    Accepts ``1``, ``1-2``, ``1,2``, ``1-2,5`` and the ``E01-E02`` forms that
    fall out of copying from a filename, with a hyphen, en dash or em dash.

    Returns ``None`` for anything it cannot read, so the caller can leave the
    previous value standing rather than silently clearing a mapping because
    of a stray keystroke. An empty string is ``[]`` -- deliberately clearing
    the cell, which is how a row is unmapped.
    """
    stripped = text.strip()
    if not stripped:
        return []

    episodes: list[int] = []
    for part in stripped.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue

        match = _SPEC_TOKEN_RE.match(token)
        if not match:
            return None

        start = int(match.group("start"))
        end_text = match.group("end")
        if end_text is None:
            episodes.append(start)
            continue

        end = int(end_text)
        if end < start or end - start >= MAX_SPAN_WIDTH:
            return None
        episodes.extend(range(start, end + 1))

    if not episodes:
        return None
    return sorted(set(episodes))


_PART_SUFFIX_RE = re.compile(
    r"""
    \s*
    (?:
        \(\s*(?:part\s*)?(?:\d{1,2}|[ivx]{1,4}|one|two|three|four)\s*\)   # (1) (Part 2) (II)
      | [,:-]?\s*p(?:ar)?t\.?\s*(?:\d{1,2}|[ivx]{1,4}|one|two|three|four) # , Part 1 / Pt. 2
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def strip_part_suffix(title: str) -> str:
    """Drop a trailing part marker from an episode title.

    ``Lost & Found (1)`` and ``A Moral Star, Part 2`` name one story split in
    two. Only an anchored trailing marker is removed, so a title that simply
    ends in a number -- ``Supernova 2`` as a standalone episode, ``Apollo
    13`` -- keeps it unless it is bracketed or introduced by "part".
    """
    return _PART_SUFFIX_RE.sub("", title).strip()


def shared_span_title(titles: Sequence[str | None]) -> str | None:
    """The one title a multi-episode file can honestly carry, if there is one.

    A file covering several episodes has no single episode title, so naming
    it after the first would assert that one episode's title describes all of
    them. But the common case for a span is one story told in two parts,
    where every episode carries the *same* title and differs only by its part
    marker -- there the shared stem describes the file exactly.

    Returns ``None`` unless every episode resolved to a real title and all of
    them agree once their part markers are removed. One unresolved or
    placeholder episode is enough to withhold it: a title that covers only
    part of the file is worse than none.
    """
    if len(titles) < 2:
        return None

    stems: list[str] = []
    for title in titles:
        if not title or is_placeholder_title(title):
            return None
        stem = strip_part_suffix(str(title))
        if not stem:
            return None
        stems.append(stem)

    if len({normalize_title(stem) for stem in stems}) != 1:
        return None
    return stems[0]


def has_part_marker(title: str | None) -> bool:
    """Whether a title names which part of a multi-part story it is.

    "Lost & Found (1)" does; "Lost & Found" does not. This is what tells a
    file holding one part from a file holding the whole story, when neither
    carries episode numbers.
    """
    if not title:
        return False
    return strip_part_suffix(str(title)) != str(title).strip()


def multi_part_groups(
    season_episodes: Mapping[int, Mapping[str, Any]],
) -> list[tuple[str, tuple[int, ...]]]:
    """Runs of consecutive episodes that are parts of one story.

    Detected by title: consecutive episodes whose titles agree once their
    part markers are stripped, where at least one of them carries such a
    marker. Returns ``(shared title, episode numbers)`` per group.

    A provider splits a two-part premiere into two episodes while a release
    usually ships it as one file. Without the group, a file named after the
    story can only ever be matched to half of it.
    """
    groups: list[tuple[str, tuple[int, ...]]] = []
    numbers = sorted(season_episodes)

    index = 0
    while index < len(numbers):
        first = numbers[index]
        stem = strip_part_suffix(str(season_episodes[first].get("name") or ""))
        if not stem or is_placeholder_title(season_episodes[first].get("name")):
            index += 1
            continue

        run = [first]
        while index + len(run) < len(numbers):
            following = numbers[index + len(run)]
            # Consecutive in number as well as in title: two unrelated
            # episodes that happen to share a name are not one story.
            if following != run[-1] + 1:
                break
            name = season_episodes[following].get("name")
            if is_placeholder_title(name):
                break
            if normalize_title(strip_part_suffix(str(name or ""))) != normalize_title(
                stem
            ):
                break
            run.append(following)

        if len(run) > 1 and any(
            has_part_marker(season_episodes[number].get("name")) for number in run
        ):
            groups.append((stem, tuple(run)))

        index += len(run)

    return groups


@dataclass(frozen=True, slots=True)
class EpisodeCandidate:
    """One thing a file could be: an episode, or a whole multi-part story."""

    episodes: tuple[int, ...]
    title: str
    score: float

    @property
    def is_group(self) -> bool:
        return len(self.episodes) > 1


def rank_title_candidates(
    file_title: str | None,
    season_episodes: Mapping[int, Mapping[str, Any]],
    exclude: Collection[int] = (),
    threshold: float = 0.0,
    part_hint: int | None = None,
) -> list[EpisodeCandidate]:
    """Rank what a filename's episode title could be referring to.

    Candidates are the season's individual episodes plus each multi-part
    group, so a file named after a two-part story can match the story rather
    than only its first half.

    Where the filename names a part ("... Part 2"), single episodes are
    preferred, because the file says it holds one part. Where it does not,
    a group wins an otherwise equal score: a file named for the whole story
    and holding only half of it would leave the other half unmapped with no
    file to give it.

    ``exclude`` holds episodes another file already covers; a candidate
    touching any of them is dropped rather than ranked, so matching cannot
    put two files on one episode.

    ``part_hint`` is a number parsed from the filename that no season could
    be found for -- "A.Moral.Star.1" parses as episode 1 with no season, and
    that 1 is the part, not the episode. It is only consulted for a group
    whose stem the title already matches, and only when the title itself
    does not name a part.
    """
    comparable = comparable_title(file_title)
    if comparable is None:
        return []

    excluded = set(exclude)
    names_a_part = has_part_marker(file_title)

    candidates: list[EpisodeCandidate] = []
    # Episodes reached by resolving a part reference, which is direct
    # evidence and must outrank a plain title score that happens to tie.
    preferred: set[tuple[int, ...]] = set()

    for number, episode_data in season_episodes.items():
        if number in excluded:
            continue
        title = comparable_title(episode_data.get("name"))
        if title is None:
            continue
        candidates.append(
            EpisodeCandidate(
                episodes=(number,),
                title=str(episode_data.get("name")),
                score=title_similarity(comparable, title),
            )
        )

    for stem, episodes in multi_part_groups(season_episodes):
        stem_title = comparable_title(stem)
        if stem_title is None:
            continue

        # "A.Moral.Star.2" names one part of the group, not the group. The
        # single-episode candidate for that part already exists above; this
        # lifts its score to the group's, because the filename matched the
        # story's name exactly and only the part marker differs.
        part = resolve_part_reference(file_title, stem, episodes)
        if part is None and part_hint is not None and 1 <= part_hint <= len(episodes):
            part = episodes[part_hint - 1]
        if part is not None:
            if part in excluded:
                continue
            score = title_similarity(comparable, stem_title)
            candidates = [
                EpisodeCandidate(candidate.episodes, candidate.title, score)
                if candidate.episodes == (part,)
                else candidate
                for candidate in candidates
            ]
            preferred.add((part,))
            continue

        if excluded.intersection(episodes):
            continue
        candidates.append(
            EpisodeCandidate(
                episodes=episodes,
                title=stem,
                score=title_similarity(comparable, stem_title),
            )
        )

    ranked = [candidate for candidate in candidates if candidate.score >= threshold]
    ranked.sort(
        key=lambda candidate: (
            -candidate.score,
            candidate.episodes not in preferred,
            # A file naming a part wants one episode; a file naming the whole
            # story wants all of them.
            candidate.is_group is names_a_part,
            candidate.episodes[0],
        )
    )
    return ranked


_PART_FILLER_WORDS = frozenset({"part", "parts", "pt", "pts"})
_PART_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
}


def _as_part_number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _PART_WORD_NUMBERS.get(token)


def resolve_part_reference(
    file_title: str | None, stem: str, episodes: Sequence[int]
) -> int | None:
    """Which part of a multi-part story a filename is naming, if it names one.

    Returns the episode number for that part, or ``None`` when the filename
    names the whole story rather than a part of it.

    Resolved against the group rather than by pattern alone, which is what
    makes a bare trailing number safe to read as a part: releases write
    "A.Moral.Star.2" and "Supernova.2" with no "part" anywhere, but the
    number only counts as a part here when the rest of the title is the
    group's own and the number is within the group. A title that merely ends
    in a number -- "Apollo 13" -- has nowhere to resolve to and is left
    alone.
    """
    if not file_title:
        return None

    stem_tokens = set(normalize_title(stem).split())
    if not stem_tokens:
        return None

    remainder = [
        token
        for token in normalize_title(file_title).split()
        if token not in stem_tokens and token not in _PART_FILLER_WORDS
    ]
    if len(remainder) != 1:
        return None

    part = _as_part_number(remainder[0])
    if part is None or not 1 <= part <= len(episodes):
        return None
    return episodes[part - 1]
