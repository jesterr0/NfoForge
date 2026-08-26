from pathlib import Path

from PySide6.QtWidgets import QApplication
import pytest

from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.enums.image_host import ImageHost
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.image_host_listbox import (
    CHEVERETO_V4_PRESETS,
    CheveretoV4Edit,
    ImageHostListBox,
    LensdumpEdit,
    OnlyImageEdit,
    PixhostEdit,
)
from src.packages.custom_types import ImageHostRef
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


def _row_texts(listbox: ImageHostListBox) -> list[str]:
    return [
        listbox.tree.topLevelItem(i).text(0)  # type: ignore[reportOptionalMemberAccess]
        for i in range(listbox.tree.topLevelItemCount())
    ]


def _editor_for(listbox: ImageHostListBox, row_text: str) -> object:
    parent = listbox.tree.topLevelItem(_row_texts(listbox).index(row_text))
    child = parent.child(0)  # type: ignore[reportOptionalMemberAccess]
    return listbox.tree.itemWidget(child, 0)


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
    listbox.add_items(manager.settings.image_hosts.by_selection())

    assert isinstance(_editor_for(listbox, str(image_host)), expected_cls)


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


# --------------------------------------------------------------------------
# Chevereto instances
# --------------------------------------------------------------------------
def test_a_fresh_profile_offers_no_chevereto_sites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chevereto is a list the user fills, not a slot shipped half-configured."""
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())

    assert manager.settings.image_hosts.chevereto_v4 == []
    assert not any("Chevereto" in text for text in _row_texts(listbox))


def test_adding_two_v4_sites_gives_each_its_own_row_and_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())

    first = listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="PTScreens")
    second = listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Somewhere")

    assert first.instance_id != second.instance_id
    assert len(manager.settings.image_hosts.chevereto_v4) == 2
    assert {"PTScreens", "Somewhere"} <= set(_row_texts(listbox))


def test_the_ptscreens_preset_fills_in_its_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason this feature exists: ptscreens is a Chevereto site, so
    it needs no host of its own -- only its URL prefilled."""
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())

    label, url = CHEVERETO_V4_PRESETS[0]
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label=label, base_url=url)

    instance = manager.settings.image_hosts.chevereto_v4[0]
    assert (instance.label, instance.base_url) == (
        "PTScreens",
        "https://ptscreens.com/",
    )


def test_an_unnamed_site_is_still_findable_in_the_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())

    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4)

    assert "Chevereto v4 (unnamed)" in _row_texts(listbox)


def test_a_v4_instance_edits_its_own_payload_not_a_shared_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="One")
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Two")

    editor = _editor_for(listbox, "One")
    assert isinstance(editor, CheveretoV4Edit)
    editor.api_key.setText("first-key")
    editor.base_url.setText("https://one.example.com/")
    editor.save_data.emit()

    by_label = {
        instance.label: instance
        for instance in manager.settings.image_hosts.chevereto_v4
    }
    assert by_label["One"].api_key == "first-key"
    assert by_label["Two"].api_key in (None, "")


def test_toggling_a_row_enables_the_instance_it_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's text is a user-chosen label, so the checkbox has to resolve
    the instance through the ref the row carries rather than through its text."""
    from PySide6.QtCore import Qt

    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="One")
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Two")

    row = listbox.tree.topLevelItem(_row_texts(listbox).index("Two"))
    row.setCheckState(0, Qt.CheckState.Checked)  # type: ignore[reportOptionalMemberAccess]

    by_label = {
        instance.label: instance
        for instance in manager.settings.image_hosts.chevereto_v4
    }
    assert by_label["Two"].enabled is True
    assert by_label["One"].enabled is False


def test_removing_a_site_also_drops_the_trackers_pointed_at_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())
    doomed = listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Gone Soon")
    kept = listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Staying")

    manager.settings.trackers.last_used_image_host[TrackerSelection.AITHER] = doomed
    manager.settings.trackers.last_used_image_host[TrackerSelection.HUNO] = kept

    listbox.remove_chevereto_instance(doomed)

    assert [i.label for i in manager.settings.image_hosts.chevereto_v4] == ["Staying"]
    assert manager.settings.trackers.last_used_image_host == {
        TrackerSelection.HUNO: kept
    }
    assert "Gone Soon" not in _row_texts(listbox)


def test_renaming_a_site_leaves_a_tracker_still_pointed_at_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ImageHostRef` excludes the label from equality precisely so a rename
    does not orphan the per-tracker selections and saved jobs naming it."""
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())
    original = listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Old Name")
    manager.settings.trackers.last_used_image_host[TrackerSelection.AITHER] = original

    editor = _editor_for(listbox, "Old Name")
    assert isinstance(editor, CheveretoV4Edit)
    editor.label.setText("New Name")
    editor.label_changed.emit()

    renamed = ImageHostRef(
        kind=ImageHost.CHEVERETO_V4,
        instance_id=original.instance_id,
        label="New Name",
    )
    assert "New Name" in _row_texts(listbox)
    assert manager.settings.image_hosts.by_selection()[renamed] is not None
    assert (
        manager.settings.trackers.last_used_image_host[TrackerSelection.AITHER]
        == renamed
    )


def test_an_unconfigured_site_is_not_offered_as_a_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`is_configured` is what the process page's picker filters on, and a
    site with no URL or key would upload nothing."""
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Half Done")

    instance = manager.settings.image_hosts.chevereto_v4[0]
    assert instance.is_configured() is False

    instance.base_url = "https://ptscreens.com/"
    instance.api_key = "key"
    assert instance.is_configured() is True


# --------------------------------------------------------------------------
# the controls that make any of the above reachable
# --------------------------------------------------------------------------
def test_the_add_button_is_present_even_with_no_sites_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this guards: add/remove used to live only in the tree's
    context menu, and a profile with no Chevereto site has no row to
    right-click -- so the feature had no way in at all."""
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())

    assert listbox.add_site_btn.isVisibleTo(listbox)
    assert listbox.add_site_btn.menu() is not None


def test_the_add_menu_offers_both_kinds_and_every_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)

    menu = listbox.add_site_btn.menu()
    assert menu is not None
    texts = [action.text() for action in menu.actions() if not action.isSeparator()]

    assert "Blank Chevereto v3 Site" in texts
    assert "Blank Chevereto v4 Site" in texts
    for preset_label, _url in CHEVERETO_V4_PRESETS:
        assert f"{preset_label} (Chevereto v4)" in texts


def test_the_add_menu_actions_actually_add_a_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())

    menu = listbox.add_site_btn.menu()
    assert menu is not None
    preset_label = CHEVERETO_V4_PRESETS[0][0]
    action = next(
        a for a in menu.actions() if a.text() == f"{preset_label} (Chevereto v4)"
    )
    action.trigger()

    instance = manager.settings.image_hosts.chevereto_v4[0]
    assert (instance.label, instance.base_url) == (
        "PTScreens",
        "https://ptscreens.com/",
    )


def test_each_site_carries_its_own_remove_button(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Doomed")
    listbox.add_chevereto_instance(ImageHost.CHEVERETO_V4, label="Keeper")

    editor = _editor_for(listbox, "Doomed")
    assert isinstance(editor, CheveretoV4Edit)
    editor.remove_btn.click()
    # removal is deferred through the event loop, since it deletes the very
    # widget whose button is emitting
    QApplication.processEvents()

    assert [i.label for i in manager.settings.image_hosts.chevereto_v4] == ["Keeper"]
    assert "Doomed" not in _row_texts(listbox)


def test_a_single_slot_host_has_no_remove_button(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only Chevereto is a list; removing Pixhost is not a thing to offer."""
    manager = _manager(tmp_path, monkeypatch)
    listbox = ImageHostListBox(manager)
    listbox.add_items(manager.settings.image_hosts.by_selection())

    assert not hasattr(_editor_for(listbox, str(ImageHost.PIXHOST)), "remove_btn")
