"""Absolute anchors for test data, so the suite does not depend on the cwd.

pytest's ``pythonpath = ["."]`` makes imports cwd-independent, but a bare
``Path("runtime/...")`` literal still resolves against the working directory.
Everything here is anchored to this file instead.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG_DIR = REPO_ROOT / "runtime" / "config" / "defaults"
DEFAULT_CONFIG_TOML = DEFAULT_CONFIG_DIR / "default_config.toml"
CONFIG_FIXTURE_DIR = REPO_ROOT / "tests" / "test_config" / "fixtures"
METADATA_PLUGIN_EXAMPLE_DIR = REPO_ROOT / "plugins" / "metadata_plugin_example"
