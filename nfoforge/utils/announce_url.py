"""Helpers for normalizing tracker announce URLs."""

from urllib.parse import urlsplit, urlunsplit


def ensure_torrentleech_announce_url(url: str | None) -> str | None:
    """Add TorrentLeech's ``/announce`` endpoint when it is missing.

    TorrentLeech sometimes exposes a passkey URL without the final announce
    path. Keep empty and malformed values unchanged so the normal validation
    can report them to the user, and preserve any query string or fragment.
    """
    if not url:
        return url

    try:
        parsed = urlsplit(url)
    except ValueError:
        return url

    if not parsed.scheme or not parsed.netloc:
        return url

    path = parsed.path.rstrip("/")
    if path.rsplit("/", 1)[-1].casefold() in {"announce", "announce.php"}:
        return url

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{path}/announce",
            parsed.query,
            parsed.fragment,
        )
    )
