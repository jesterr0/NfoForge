from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any, Protocol


class _Cookie(Protocol):
    name: str
    value: str
    domain: str
    path: str
    expires: int | None
    secure: bool


class _CookieJar(Protocol):
    def set(self, name: str, value: str, **kwargs: Any) -> Any: ...


def save_cookies(cookies: Iterable[_Cookie], path: Path) -> None:
    """Persist the fields needed to send a session cookie as JSON.

    Tracker cookies are credentials.  JSON avoids the arbitrary-code-execution
    risk of unpickling a file from the runtime directory, and the temporary
    file is restricted before it is moved into place.
    """

    payload = [
        {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "expires": cookie.expires,
            "secure": cookie.secure,
        }
        for cookie in cookies
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
        # Keep the mode explicit when replacing an existing file on platforms
        # whose rename semantics preserve the destination's metadata.
        path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_cookies(cookie_jar: _CookieJar, path: Path) -> bool:
    """Load a JSON cookie list into ``cookie_jar`` without executing data."""

    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, list):
        return False

    loaded = False
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        domain = item.get("domain", "")
        cookie_path = item.get("path", "/")
        expires = item.get("expires")
        secure = item.get("secure", False)
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or not isinstance(domain, str)
            or not isinstance(cookie_path, str)
            or (expires is not None and not isinstance(expires, int))
            or not isinstance(secure, bool)
        ):
            continue
        try:
            cookie_jar.set(
                name,
                value,
                domain=domain,
                path=cookie_path,
                expires=expires,
                secure=secure,
            )
        except (TypeError, ValueError):
            continue
        loaded = True
    return loaded
