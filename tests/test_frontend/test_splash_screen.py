from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from src.frontend.windows.splash_screen import SplashScreen


def test_splash_selector_preselects_profile_and_enter_continues() -> None:
    splash = SplashScreen()
    splash.show()
    selected: list[str] = []
    splash.config_selected.connect(selected.append)

    splash.show_config_selector(["first", "second"], selected_config="second")

    assert splash.config_combo is not None
    assert splash.config_combo.currentText() == "second"

    QTest.keyClick(splash.config_combo, Qt.Key.Key_Return)

    assert selected == ["second"]
    splash.close()


def test_splash_selector_falls_back_when_saved_profile_is_missing() -> None:
    splash = SplashScreen()
    splash.show_config_selector(["first", "second"], selected_config="missing")

    assert splash.config_combo is not None
    assert splash.config_combo.currentText() == "first"
    splash.close()
