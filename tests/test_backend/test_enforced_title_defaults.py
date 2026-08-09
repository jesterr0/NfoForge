"""A REQUIRED tracker must actually enforce something.

REQUIRED locks the user out of the title override and makes the packaged
default govern (see generate_tracker_title in src/backend/process.py). If
that packaged default enforces nothing, the lock is config that does
nothing: the user loses control and gains no guarantee in exchange.

What gets enforced varies by tracker, and both forms count. Aither, LST and
ReelFliX enforce a token. MoreThanTV and TorrentLeech ship an empty token --
so the user's global movie template supplies the wording -- and enforce a
character rule instead: MTV rewrites spaces to dots, TorrentLeech does the
reverse.
"""

from pathlib import Path

import pytest

from src.backend.trackers.title_format_policy import (
    TRACKER_TITLE_FORMAT_POLICY,
    TitleFormatPolicy,
)
from src.config.config import ConfigManager
from tests.test_config.config_tree import build_config_paths


def _config_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    """Load the packaged default config through the real loader.

    Reading the TOML directly would mean duplicating the TrackerSelection ->
    section-name mapping that lives in src/config/operations.py. Going
    through ConfigManager tests the values as the app actually sees them.
    """
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", build_config_paths(tmp_path))


def test_required_trackers_enforce_something(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _config_manager(tmp_path, monkeypatch)
    packaged = manager.defaults.trackers.by_selection()

    for tracker, policy in TRACKER_TITLE_FORMAT_POLICY.items():
        if policy is not TitleFormatPolicy.REQUIRED:
            continue
        info = packaged[tracker]
        assert info.mvr_title_override_enabled, (
            f"{tracker} is REQUIRED but its packaged override is disabled, "
            "so the lock enforces nothing"
        )
        assert info.mvr_title_token_override.strip() or info.mvr_title_replace_map, (
            f"{tracker} is REQUIRED but ships neither a title token nor a "
            "replace rule, so the lock enforces nothing"
        )
