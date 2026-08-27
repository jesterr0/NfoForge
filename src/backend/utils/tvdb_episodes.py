"""Reading episode lists out of a TVDB payload.

Two callers need the same list for different questions -- the token
replacer resolves one episode's data from it, and the tracker title asks
whether a release covers a whole season -- so the shape of the payload is
described once here rather than twice at the call sites.
"""

from __future__ import annotations

from typing import Any, cast


def tvdb_episode_list(
    tvdb_data: dict[str, Any] | None, episode_order_type_id: Any | None = None
) -> list[dict[str, Any]]:
    """Episode list for one TVDB ordering, or the flat list.

    ``episodes_by_type`` holds one list per ordering; the flat ``episodes``
    key is the official/aired order. An id that is absent, or names an
    ordering this payload does not carry, falls back to the flat list.

    The id is matched against both the int and str forms of each key: a
    saved job round-trips ``tvdb_data`` through JSON, which turns the int
    keys of ``episodes_by_type`` into strings, while the mapping row's id
    stays an int.
    """
    if not tvdb_data:
        return []

    if episode_order_type_id is not None:
        episodes_by_type = tvdb_data.get("episodes_by_type") or {}
        if isinstance(episodes_by_type, dict):
            type_data = episodes_by_type.get(episode_order_type_id)
            if type_data is None:
                type_data = episodes_by_type.get(str(episode_order_type_id))
            if isinstance(type_data, dict):
                episodes = type_data.get("episodes")
                if isinstance(episodes, list):
                    return cast(list[dict[str, Any]], episodes)

    return cast(list[dict[str, Any]], tvdb_data.get("episodes", []))


def season_episode_numbers(
    tvdb_data: dict[str, Any] | None,
    season: int,
    episode_order_type_id: Any | None = None,
) -> frozenset[int]:
    """Every episode number TVDB lists for one season.

    Empty means "unknown", not "no episodes": a payload with no TVDB data,
    a season the payload does not cover, and a genuinely empty season are
    indistinguishable here. A caller deciding whether a release is a
    complete season must treat empty as unproven rather than as trivially
    satisfied -- an empty set is a subset of everything.
    """
    numbers: set[int] = set()
    for episode in tvdb_episode_list(tvdb_data, episode_order_type_id):
        if not isinstance(episode, dict):
            continue
        if _as_int(episode.get("seasonNumber")) != season:
            continue
        number = _as_int(episode.get("number"))
        if number is not None:
            numbers.add(number)
    return frozenset(numbers)


def _as_int(value: Any) -> int | None:
    """A TVDB numeric field as an int, or ``None`` where it is not one.

    Saved jobs round-trip through JSON and hand-built payloads vary, so a
    season or episode number arrives as an int or as the string form of
    one.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
