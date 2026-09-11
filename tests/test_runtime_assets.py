"""Inventory of the files a release ships.

A bulk move is the moment an asset goes missing, and a missing font or icon is
invisible at runtime: Qt returns a null pixmap and renders nothing rather than
raising. Asserting the set exactly, rather than just that each expected file
exists, also catches an asset added to the tree without anyone deciding to ship
it.
"""

from tests.repo_paths import ASSET_DIR

EXPECTED_FONTS = {
    "Fira_Mono/FiraMono-Bold.ttf",
    "Fira_Mono/FiraMono-Regular.ttf",
    "Fira_Mono/OFL.txt",
    "Montserrat/OFL.txt",
    "Montserrat/static/Montserrat-Medium.ttf",
    "Roboto/LICENSE.txt",
    "Roboto/Roboto-Bold.ttf",
    "Roboto/Roboto-BoldItalic.ttf",
    "Roboto/Roboto-Italic.ttf",
    "Roboto/Roboto-Medium.ttf",
    "Roboto/Roboto-MediumItalic.ttf",
    "Roboto/Roboto-Regular.ttf",
}

EXPECTED_PACKAGED_DEFAULTS = {
    "audio_conventions/default.json",
    "defaults/default_config.toml",
    "defaults/default_program_conf.toml",
}


def _inventory(subdirectory: str) -> set[str]:
    root = ASSET_DIR / subdirectory
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def test_font_inventory_contains_only_required_assets() -> None:
    assert _inventory("fonts") == EXPECTED_FONTS


def test_packaged_configuration_documents_are_present() -> None:
    """The defaults and the audio conventions are read at runtime.

    They sit under the asset root rather than beside the user's own
    configuration, which is the split that lets a release folder be replaced
    without taking someone's profiles with it.
    """
    assert _inventory("config") == EXPECTED_PACKAGED_DEFAULTS


def test_no_user_state_is_shipped_with_the_assets() -> None:
    """Nothing under the asset root may be a file the user owns.

    The build used to copy the whole mutable tree and then delete the user's
    own data back out of it, which meant a release shipped whatever the build
    machine happened to hold if that pass ever missed something. The asset tree
    is now only ever populated deliberately, and this is the assertion that
    keeps it that way.
    """
    forbidden = {"user", "program", "plugins", "cookies", "logs", "templates", "apps"}
    present = {path.name for path in ASSET_DIR.rglob("*") if path.is_dir()}

    assert not (forbidden & present)
