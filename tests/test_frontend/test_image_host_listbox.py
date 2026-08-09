from pathlib import Path
from typing import cast

import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.image_host import ImageHost
from src.frontend.custom_widgets.image_host_listbox import (
    ImageHostListBox,
    LensdumpEdit,
    OnlyImageEdit,
    PixhostEdit,
)
from tests.repo_paths import DEFAULT_CONFIG_DIR


def _paths(tmp_path: Path) -> ConfigPaths:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    source_defaults = DEFAULT_CONFIG_DIR
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


def _manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setattr(
        "src.config.config.FindDependencies.update_dependencies",
        lambda self, dependencies: None,
    )
    return ConfigManager("test", _paths(tmp_path))


@pytest.mark.parametrize(
    ("image_host", "expected_cls"),
    [
        (ImageHost.ONLY_IMAGE, OnlyImageEdit),
        (ImageHost.PIXHOST, PixhostEdit),
        (ImageHost.LENSDUMP, LensdumpEdit),
    ],
)
def test_add_child_widget_builds_the_correct_editor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_host: ImageHost,
    expected_cls: type,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    items = manager.settings.image_hosts.by_selection()
    listbox.add_items(cast(dict, items))

    parent_texts = [
        listbox.tree.topLevelItem(i).text(0)  # type: ignore[reportOptionalMemberAccess]
        for i in range(listbox.tree.topLevelItemCount())
    ]
    parent_index = parent_texts.index(str(image_host))
    parent = listbox.tree.topLevelItem(parent_index)
    child = parent.child(0)  # type: ignore[reportOptionalMemberAccess]
    editor = listbox.tree.itemWidget(child, 0)

    assert isinstance(editor, expected_cls)


def test_onlyimage_and_lensdump_api_key_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)

    for host_attr, edit_cls in (
        ("only_image", OnlyImageEdit),
        ("lensdump", LensdumpEdit),
    ):
        editor = edit_cls(manager)
        editor.api_key.setText("secret-key")
        editor.save_data.emit()

        assert getattr(manager.settings.image_hosts, host_attr).api_key == (
            "secret-key"
        )


def test_pixhost_has_no_credential_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    editor = PixhostEdit(manager)
    editor.load_data.emit()  # populates the fixed base_url from config

    assert not hasattr(editor, "api_key")
    editor.validate_data()  # fixed base_url is always present; must not raise
