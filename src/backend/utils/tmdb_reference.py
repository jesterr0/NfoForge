from dataclasses import dataclass
import re

from src.enums.media_type import MediaType

# Matches the unambiguous `themoviedb.org/(movie|tv)/<digits>` chunk anywhere
# in the input, so it tolerates a scheme, `www.`, a trailing `-slug`, extra
# path segments, or a query string without needing to model all of them.
TMDB_URL_RE = re.compile(r"themoviedb\.org/(movie|tv)/(\d+)", re.IGNORECASE)

# Forces a direct ID lookup for a bare number, e.g. `tmdb:603` / `tmdbid:603`.
# Anchored to the whole (stripped) input so it can't fire mid-sentence.
TMDB_ID_PREFIX_RE = re.compile(r"^tmdb(?:id)?\s*:\s*(\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TmdbReference:
    """A TMDB ID pulled directly out of search-box text, bypassing the fuzzy
    title search. `media_type` is known when a URL named `/movie/` or `/tv/`,
    and `None` when only a bare ID was given (e.g. via the `tmdb:` prefix).
    """

    tmdb_id: str
    media_type: MediaType | None


def parse_tmdb_reference(text: str) -> TmdbReference | None:
    """Recognize a pasted TMDB URL or a `tmdb:`/`tmdbid:` id reference.

    Returns `None` for anything else -- including a bare number on its own,
    which stays a normal text search since real movie titles are sometimes
    pure digits ("300", "42", "21", "9") and guessing wrong there would
    silently resolve to an unrelated title.
    """
    candidate = text.strip()
    if not candidate:
        return None

    url_match = TMDB_URL_RE.search(candidate)
    if url_match:
        media_type = MediaType.search_type(url_match.group(1))
        return TmdbReference(tmdb_id=url_match.group(2), media_type=media_type)

    prefix_match = TMDB_ID_PREFIX_RE.match(candidate)
    if prefix_match:
        return TmdbReference(tmdb_id=prefix_match.group(1), media_type=None)

    return None
