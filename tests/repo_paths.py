"""Absolute anchors for test data, so the suite does not depend on the cwd.

pytest's ``pythonpath = ["."]`` makes imports cwd-independent, but a bare
``Path("assets/...")`` literal still resolves against the working directory.
Everything here is anchored to this file instead.
"""

from pathlib import Path

from src.config.paths import AppPaths

REPO_ROOT = Path(__file__).resolve().parents[1]

ASSET_DIR = REPO_ROOT / "assets"
DEFAULT_CONFIG_DIR = ASSET_DIR / "config" / "defaults"
DEFAULT_CONFIG_TOML = DEFAULT_CONFIG_DIR / "default_config.toml"
CONFIG_FIXTURE_DIR = REPO_ROOT / "tests" / "test_config" / "fixtures"
METADATA_PLUGIN_EXAMPLE_DIR = REPO_ROOT / "plugins" / "metadata_plugin_example"


def build_app_paths(tmp_path: Path) -> AppPaths:
    """A throwaway tree seeded with the real packaged defaults.

    The state root and the asset root are separate directories under
    `tmp_path`, which is the arrangement a release has, so a test cannot pass by
    accidentally reading a shipped file through a state path or the reverse.

    Only the two default documents are copied. They are the one asset the
    config layer reads at runtime, and copying them rather than pointing at the
    repository's own keeps a test that writes from touching tracked files.
    """
    state_root = tmp_path / "state"
    asset_root = tmp_path / "assets"
    defaults = asset_root / "config" / "defaults"
    defaults.mkdir(parents=True)
    for name in ("default_config.toml", "default_program_conf.toml"):
        (defaults / name).write_text(
            (DEFAULT_CONFIG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return AppPaths(state_root=state_root, asset_root=asset_root)
