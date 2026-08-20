from collections.abc import Iterator

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QToolButton
import pytest

import src.frontend.utils.qtawesome_theme_swapper as theme_swapper_module
from src.frontend.utils.qtawesome_theme_swapper import QTAwesomeThemeSwapper


@pytest.fixture
def isolated_theme_swapper() -> Iterator[QTAwesomeThemeSwapper]:
    previous_instance = QTAwesomeThemeSwapper._instance
    QTAwesomeThemeSwapper._instance = None
    swapper = QTAwesomeThemeSwapper()
    yield swapper
    swapper._icon_widgets.clear()
    QTAwesomeThemeSwapper._instance = previous_instance


@pytest.mark.parametrize(
    ("color_scheme", "expected_color"),
    [
        (Qt.ColorScheme.Light, QTAwesomeThemeSwapper.LIGHT_COLOR),
        (Qt.ColorScheme.Dark, QTAwesomeThemeSwapper.DARK_COLOR),
    ],
)
def test_newly_registered_icons_use_the_active_theme(
    isolated_theme_swapper: QTAwesomeThemeSwapper,
    monkeypatch: pytest.MonkeyPatch,
    color_scheme: Qt.ColorScheme,
    expected_color: str,
) -> None:
    requested_colors: list[str] = []
    original_icon = theme_swapper_module.qta.icon

    def recording_icon(icon_name: str, **icon_kwargs: object):
        requested_colors.append(str(icon_kwargs["color"]))
        return original_icon(icon_name, **icon_kwargs)

    monkeypatch.setattr(theme_swapper_module.qta, "icon", recording_icon)
    isolated_theme_swapper.update_icon(color_scheme)

    button = QToolButton()
    isolated_theme_swapper.register(
        button, "ph.file-arrow-down-light", icon_size=QSize(24, 24)
    )

    assert requested_colors[-1] == expected_color
