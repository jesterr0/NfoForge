from src.backend.utils.working_dir import RUNTIME_DIR

EXPECTED_RUNTIME_FONTS = {
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


def test_runtime_font_inventory_contains_only_required_assets() -> None:
    font_root = RUNTIME_DIR / "fonts"
    actual = {
        path.relative_to(font_root).as_posix()
        for path in font_root.rglob("*")
        if path.is_file()
    }

    assert actual == EXPECTED_RUNTIME_FONTS
