"""Helpers for keeping credentials out of logs and user-facing errors."""

from collections.abc import Mapping
import re

_REDACTED = "[redacted]"

# These names cover credentials used by trackers, torrent clients, and the
# authentication forms whose payloads are occasionally logged while debugging.
_SECRET_FIELD_NAMES = frozenset(
    {
        "announcekey",
        "announce_key",
        "api_key",
        "apikey",
        "api_token",
        "authorization",
        "auth",
        "authkey",
        "cookie",
        "password",
        "passkey",
        "rss_key",
        "rsskey",
        "session",
        "token",
        "torrent_pass",
        "torrent_passkey",
    }
)
_SECRET_FIELD_PATTERN = "|".join(
    re.escape(name) for name in sorted(_SECRET_FIELD_NAMES, key=len, reverse=True)
)

_SECRET_QUERY_PARAM = re.compile(
    rf"(?i)(?P<name>\b(?:{_SECRET_FIELD_PATTERN})=)"
    r"(?P<value>[^&\s\"'<>]+)"
)

# BeyondHD puts its API key directly after these API endpoints. UNIT3D uses
# ``/api/torrents/upload`` for the upload endpoint, so exclude the known route
# name to avoid making an otherwise useful URL look like a secret.
_SECRET_API_PATH = re.compile(
    r"(?i)(?P<prefix>/api/(?:upload|torrents)/(?!"
    r"(?:download|filter|upload)(?=[/?\s:)>]|$))"
    r")(?:[^/?\s\"'<>:),\]}]+)"
)

# UNIT3D can put a user-specific key in the final component of the generated
# torrent download URL. Redact the whole artifact component: the numeric
# torrent id is not needed for diagnosing a failed download, and the shape is
# safe for both keyed and unkeyed tracker responses.
_TRACKER_DOWNLOAD_PATH = re.compile(
    r"(?i)(?P<prefix>/(?:api/)?torrents?/download/)"
    r"[^/?\s\"'<>:),\]}]+"
)

# Keep this intentionally narrow: only redact path segments that explicitly
# identify themselves as a credential. This covers tracker-generated download
# URLs that carry an RSS/announce key without hiding ordinary URL components.
_NAMED_SECRET_PATH = re.compile(
    rf"(?i)(?P<prefix>/(?:{_SECRET_FIELD_PATTERN})/)"
    r"[^/?\s\"'<>:),\]}]+"
)

# Tracker announce URLs carry the passkey as a bare path segment rather than a
# named field, so the patterns above cannot see it. Both orderings are in use:
# `/<passkey>/announce` and `/announce/<passkey>`. The lookbehind on the first
# keeps `https://host/announce` from having its hostname mistaken for a key --
# the `/` before a hostname is always the second of the scheme's `//`.
_ANNOUNCE_KEY_PREFIX = re.compile(
    r"(?i)(?<!/)/[^/?\s\"'<>:),\]}]+(?P<suffix>/announce(?:\.php)?\b)"
)
_ANNOUNCE_KEY_SUFFIX = re.compile(
    r"(?i)(?P<prefix>/announce(?:\.php)?/)[^/?\s\"'<>:),\]}]+"
)

# URL userinfo is used by rTorrent. The first pattern handles a normal URI;
# the second handles the schemeless form emitted by xmlrpc.client.ProtocolError
# after ServerProxy has normalized the configured URL.
_URI_USERINFO_PASSWORD = re.compile(
    r"(?i)(?P<prefix>://[^/\s:@]+:)[^@\s]+(?P<suffix>@)"
)
_SCHEMELESS_USERINFO_PASSWORD = re.compile(
    r"(?i)(?P<prefix>(?<![\w./-])[^/\s:@<>]+:(?!//))"
    r"[^@\s<>]+"
    r"(?P<suffix>@(?=[A-Za-z0-9.-]+(?:[:/>\s]|$)))"
)

# ``str(dict)`` and JSON-like payloads are common in debug logs. These values
# do not use URL query syntax, so redact them by field name as well.
_SECRET_MAPPING_VALUE = re.compile(
    rf"(?i)(?P<prefix>['\"]?(?:{_SECRET_FIELD_PATTERN})['\"]?\s*[:=]\s*)"
    r"(?P<quote>['\"])(?P<value>[^'\"]*)(?P=quote)"
)


def scrub_secrets(text: str) -> str:
    """Redact credentials from URLs, exception messages, and payload reprs."""

    text = _SECRET_QUERY_PARAM.sub(rf"\g<name>{_REDACTED}", text)
    text = _TRACKER_DOWNLOAD_PATH.sub(rf"\g<prefix>{_REDACTED}", text)
    text = _SECRET_API_PATH.sub(rf"\g<prefix>{_REDACTED}", text)
    text = _NAMED_SECRET_PATH.sub(rf"\g<prefix>{_REDACTED}", text)
    text = _ANNOUNCE_KEY_PREFIX.sub(rf"/{_REDACTED}\g<suffix>", text)
    text = _ANNOUNCE_KEY_SUFFIX.sub(rf"\g<prefix>{_REDACTED}", text)
    text = _URI_USERINFO_PASSWORD.sub(rf"\g<prefix>{_REDACTED}\g<suffix>", text)
    text = _SCHEMELESS_USERINFO_PASSWORD.sub(rf"\g<prefix>{_REDACTED}\g<suffix>", text)
    return _SECRET_MAPPING_VALUE.sub(_replace_mapping_value, text)


def _replace_mapping_value(match: re.Match[str]) -> str:
    quote = match.group("quote")
    return f"{match.group('prefix')}{quote}{_REDACTED}{quote}"


def scrub_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    """Return a shallow copy with known credential fields replaced.

    Tracker payloads are often interpolated into debug messages before they
    reach the logger. Redacting the mapping at construction time keeps those
    logs safe even when a value is not represented as a URL.
    """

    return {
        key: _REDACTED if key.casefold() in _SECRET_FIELD_NAMES else value
        for key, value in mapping.items()
    }
