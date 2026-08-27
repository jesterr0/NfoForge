from dataclasses import dataclass
from datetime import datetime, timezone
import platform
from typing import Any

import niquests
import semver

from src.backend.utils.http_client import new_http_session
from src.config.config import ConfigManager
from src.logger.nfo_forge_logger import LOG
from src.version import __version__, program_name

GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/jesterr0/NfoForge/releases/latest"
)
MIN_CHECK_INTERVAL_HOURS = 12
REQUEST_TIMEOUT_SECONDS = 10

_HEADERS = {
    "User-Agent": f"{program_name} v{__version__} ({platform.system()} {platform.release()})",
    "Accept": "application/vnd.github+json",
}


@dataclass(slots=True)
class UpdateCheckResult:
    update_available: bool
    latest_version: str
    release_url: str


def _strip_v_prefix(value: str) -> str:
    value = value.strip()
    return value[1:] if value[:1] in ("v", "V") else value


def _parse_version(value: str) -> semver.VersionInfo | None:
    try:
        return semver.VersionInfo.parse(_strip_v_prefix(value))
    except ValueError:
        return None


def fetch_latest_release() -> tuple[str, str] | None:
    """Fetch the latest published NfoForge release from GitHub.

    Never raises. Returns ``(version_str, html_url)`` on success, else
    ``None`` -- any network failure, non-ok response, or unparseable payload
    is logged and swallowed, since this is a best-effort background check
    that must never disrupt startup.
    """
    session = new_http_session()
    try:
        with session.get(
            GITHUB_LATEST_RELEASE_URL,
            headers=_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            if not response.ok:
                LOG.warning(
                    LOG.LOG_SOURCE.BE,
                    f"Update check failed: GitHub returned {response.status_code}",
                )
                return None
            payload: Any = response.json()
    except niquests.exceptions.RequestException as error:
        LOG.warning(LOG.LOG_SOURCE.BE, f"Update check request failed: {error}")
        return None
    finally:
        session.close()

    tag_name = payload.get("tag_name") if isinstance(payload, dict) else None
    html_url = payload.get("html_url") if isinstance(payload, dict) else None
    if not isinstance(tag_name, str) or not tag_name.strip():
        LOG.warning(LOG.LOG_SOURCE.BE, "Update check failed: missing tag_name")
        return None
    if not isinstance(html_url, str) or not html_url.strip():
        LOG.warning(LOG.LOG_SOURCE.BE, "Update check failed: missing html_url")
        return None
    return _strip_v_prefix(tag_name), html_url.strip()


def check_for_updates_job(config: ConfigManager) -> UpdateCheckResult | None:
    """Gated update check, meant to run inside a background `GeneralWorker`
    thread. Touches only `config.program.*` / `config.settings.general.*`
    attributes and `config.save_program()` (plain file I/O, safe off the GUI
    thread since only one such worker runs at a time from startup) -- never a
    Qt widget.
    """
    if not config.settings.general.check_for_updates:
        return None

    now = datetime.now(timezone.utc)
    due = True
    last_checked_raw = config.program.last_update_check
    if last_checked_raw:
        try:
            last_checked = datetime.fromisoformat(last_checked_raw)
            if last_checked.tzinfo is None:
                last_checked = last_checked.replace(tzinfo=timezone.utc)
            elapsed_hours = (now - last_checked).total_seconds() / 3600
            due = elapsed_hours >= MIN_CHECK_INTERVAL_HOURS
        except ValueError:
            due = True  # unparseable stamp: treat as due

    latest_version = config.program.latest_known_version
    release_url = config.program.latest_release_url

    if due:
        fetched = fetch_latest_release()
        # stamp regardless of outcome -- avoids hammering GitHub every
        # startup when it's briefly unreachable
        config.program.last_update_check = now.isoformat()
        if fetched is not None:
            latest_version, release_url = fetched
            config.program.latest_known_version = latest_version
            config.program.latest_release_url = release_url
        config.save_program()

    if not latest_version or not release_url:
        return None

    current = _parse_version(str(__version__))
    latest = _parse_version(latest_version)
    if current is None or latest is None or latest <= current:
        return None

    return UpdateCheckResult(
        update_available=True,
        latest_version=latest_version,
        release_url=release_url,
    )
