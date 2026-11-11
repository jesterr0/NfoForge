"""Settle which playlist of a disc is the release."""

from __future__ import annotations

from nfoforge.core.disc.model import Disc, DiscError, DiscPlaylist, DiscType


def choose_playlist(disc: Disc, requested: str | None = None) -> DiscPlaylist:
    """Select `requested`, or the main feature when there is exactly one.

    A Blu-ray with several main candidates (two cuts, or decoy playlists on a
    protected disc) is never guessed at: the candidates are listed and the
    choice is left to whoever is running the release.
    """
    if requested:
        return disc.select(requested)
    candidates = disc.main_playlists()
    if len(candidates) == 1 or (candidates and disc.disc_type is DiscType.DVD):
        # Several like-sized title sets on a DVD are episodes, and the whole
        # disc is uploaded whichever one describes it: the first stands for
        # the rest. Like-sized Blu-ray playlists are different cuts, or decoys.
        return disc.select(candidates[0].playlist_id)
    raise DiscError(
        f"{disc.label} has {len(candidates)} possible main playlists; "
        f"choose one:\n{describe_playlists(disc)}"
    )


def needs_playlist_choice(disc: Disc) -> bool:
    """Whether `choose_playlist` would refuse to pick for this disc."""
    return disc.disc_type is not DiscType.DVD and len(disc.main_playlists()) > 1


def preferred_playlist(disc: Disc) -> DiscPlaylist | None:
    """The playlist a picker pre-selects: the largest main candidate.

    Only ever a suggestion to a person. Nothing takes it without being told.
    """
    return max(disc.main_playlists(), key=lambda playlist: playlist.size, default=None)


def describe_playlist(playlist: DiscPlaylist) -> str:
    """One playlist as a line of text, a main candidate flagged."""
    return (
        f"{playlist.playlist_id}  {format_duration(playlist.duration):>8}  "
        f"{playlist.size / 1024**3:6.2f} GiB"
        f"{'  (main)' if playlist.is_main else ''}"
    )


def describe_playlists(disc: Disc) -> str:
    """The disc's playlists as lines of text, main candidates flagged."""
    return "\n".join(f"  {describe_playlist(p)}" for p in disc.playlists)


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    whole = int(seconds)
    return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}"
