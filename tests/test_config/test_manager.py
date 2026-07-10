from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

import pytest
import tomlkit

from src.config.codec import TomlConfigCodec
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.config.persistence import atomic_write_text
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import ConfigError
from src.payloads.trackers import MoreThanTVInfo


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = Path("runtime/config/defaults")
    default_config = defaults / "default_config.toml"
    default_program = defaults / "default_program_conf.toml"
    default_config.write_text(
        (source_defaults / "default_config.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    default_program.write_text(
        (source_defaults / "default_program_conf.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ConfigPaths(
        default_config=default_config,
        default_program=default_program,
        program=tmp_path / "program/conf.toml",
        user_configs=tmp_path / "user",
        tracker_cookies=tmp_path / "cookies",
    )


def test_manager_loads_nested_typed_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )

    manager = ConfigManager("test", _paths(tmp_path))

    assert manager.settings.general.timeout == 60
    assert manager.settings.series.standard_episode_token
    assert manager.settings.trackers.more_than_tv.source == "MTV"
    assert manager.settings.templates.newline_sequence == "\n"


def test_save_preserves_unknown_keys_and_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)
    profile = paths.user_configs / "test.toml"
    document = tomlkit.parse(profile.read_text(encoding="utf-8"))
    document.add(tomlkit.comment("third-party setting"))
    document["third_party"] = {"enabled": True}
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager.load_profile("test")
    manager.settings.general.timeout = 90
    manager.save()
    saved = profile.read_text(encoding="utf-8")

    assert "# third-party setting" in saved
    assert "[third_party]" in saved
    assert "timeout = 90" in saved


def test_manager_preserves_qbittorrent_super_seeding_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    manager = ConfigManager("test", paths)

    assert (
        manager.settings.torrent_clients.qbittorrent.specific_params["super_seeding"]
        is False
    )

    manager.save()
    manager.load_profile("test")

    profile = paths.user_configs / "test.toml"
    saved = tomlkit.parse(profile.read_text(encoding="utf-8"))
    torrent_client = cast(MutableMapping[str, Any], saved["torrent_client"])
    qbittorrent = cast(MutableMapping[str, Any], torrent_client["qbittorrent"])
    specific_params = cast(MutableMapping[str, Any], qbittorrent["specific_params"])
    assert specific_params["super_seeding"] is False
    assert (
        manager.settings.torrent_clients.qbittorrent.specific_params["super_seeding"]
        is False
    )


def test_manager_repairs_generated_empty_qbittorrent_super_seeding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    torrent_client = cast(MutableMapping[str, Any], document["torrent_client"])
    qbittorrent = cast(MutableMapping[str, Any], torrent_client["qbittorrent"])
    specific_params = cast(MutableMapping[str, Any], qbittorrent["specific_params"])
    specific_params["super_seeding"] = ""
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    manager = ConfigManager("test", paths)

    assert (
        manager.settings.torrent_clients.qbittorrent.specific_params["super_seeding"]
        is False
    )
    repaired = tomlkit.parse(profile.read_text(encoding="utf-8"))
    repaired_torrent_client = cast(MutableMapping[str, Any], repaired["torrent_client"])
    repaired_qbittorrent = cast(
        MutableMapping[str, Any], repaired_torrent_client["qbittorrent"]
    )
    repaired_specific_params = cast(
        MutableMapping[str, Any], repaired_qbittorrent["specific_params"]
    )
    assert repaired_specific_params["super_seeding"] is False


def test_lookup_helpers_do_not_cache_replaced_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    replacement = MoreThanTVInfo(source="replacement")

    manager.settings.trackers.more_than_tv = replacement

    assert (
        manager.settings.trackers.by_selection()[TrackerSelection.MORE_THAN_TV]
        is replacement
    )


def test_unchanged_settings_do_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    manager = ConfigManager("test", _paths(tmp_path))
    writes = 0

    def record_write(path: Path, text: str) -> None:
        nonlocal writes
        writes += 1

    monkeypatch.setattr("src.config.operations.atomic_write_text", record_write)

    manager.save()

    assert writes == 0


def test_codec_reports_dotted_path_for_invalid_type() -> None:
    defaults = tomlkit.parse(
        Path("runtime/config/defaults/default_config.toml").read_text(encoding="utf-8")
    )
    invalid = tomlkit.parse(tomlkit.dumps(defaults))
    general = cast(MutableMapping[str, Any], invalid["general"])
    general["timeout"] = "sixty"

    with pytest.raises(ConfigError, match=r"general\.timeout"):
        TomlConfigCodec.validate_types(invalid, defaults)


def test_manager_rejects_blank_required_series_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    series_management = cast(MutableMapping[str, Any], document["series_management"])
    series_management["tvr_standard_episode_token"] = ""
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(
        ConfigError,
        match=r"series_management\.tvr_standard_episode_token",
    ):
        ConfigManager("test", paths)


def test_manager_rejects_unsupported_schema_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    document["schema_version"] = 99
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(
        ConfigError, match="Unsupported configuration schema_version: 99"
    ):
        ConfigManager("test", paths)


def test_manager_rejects_old_schema_before_value_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    document["schema_version"] = 1
    template_settings = cast(MutableMapping[str, Any], document["template_settings"])
    template_settings["newline_sequence"] = "\\n"
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(
        ConfigError, match="Unsupported configuration schema_version: 1"
    ):
        ConfigManager("test", paths)


def test_replace_profile_with_default_archives_old_config(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    old_config = "schema_version = 1\n[template_settings]\nnewline_sequence = '\\n'\n"
    profile.write_text(old_config, encoding="utf-8")

    backup_path = ConfigManager.replace_profile_with_default(profile, paths)

    assert backup_path.parent == profile.parent / "old_configs"
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == old_config
    assert profile.exists()
    assert "schema_version = 2" in profile.read_text(encoding="utf-8")


@pytest.mark.parametrize("newline_sequence", ("\\n", "\\r", "\\r\\n", "invalid"))
def test_manager_rejects_invalid_newline_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, newline_sequence: str
) -> None:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    paths = _paths(tmp_path)
    profile = paths.user_configs / "test.toml"
    profile.parent.mkdir(parents=True)
    document = tomlkit.parse(paths.default_config.read_text(encoding="utf-8"))
    template_settings = cast(MutableMapping[str, Any], document["template_settings"])
    template_settings["newline_sequence"] = newline_sequence
    profile.write_text(tomlkit.dumps(document), encoding="utf-8")

    with pytest.raises(ConfigError, match=r"template_settings\.newline_sequence"):
        ConfigManager("test", paths)


def test_atomic_write_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "config.toml"
    destination.write_text("original", encoding="utf-8")

    def fail_replace(self: Path, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(destination, "replacement")

    assert destination.read_text(encoding="utf-8") == "original"
