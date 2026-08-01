from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from src.frontend.windows import splash_screen
from src.frontend.windows.splash_screen import SplashScreen, SplashScreenLoader
from src.plugins.manager import PluginManager


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


def test_plugin_discovery_is_skipped_when_external_plugins_are_disabled(
    monkeypatch,
) -> None:
    class UnexpectedPluginLoader:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("disabled plugins must not be discovered")

    monkeypatch.setattr(splash_screen, "PluginLoader", UnexpectedPluginLoader)
    config = SimpleNamespace(
        plugin_manager=PluginManager(),
        settings=SimpleNamespace(
            general=SimpleNamespace(enable_plugins=False),
        ),
    )
    status_updates: list[str] = []
    status_signal = SimpleNamespace(emit=status_updates.append)
    loader = SplashScreenLoader(
        config,  # type: ignore[arg-type]
        status_signal,  # type: ignore[arg-type]
    )

    assert loader.init_plugins() is None
    assert status_updates == ["External plugins disabled"]
