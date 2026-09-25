import pytest

import nfoforge.frontend.utils.app_lifecycle as app_lifecycle
from nfoforge.frontend.utils.app_lifecycle import restart_application


class _FakeMainWindow:
    def __init__(self, close_result: bool = True) -> None:
        self.close_result = close_result
        self.close_calls = 0

    def close(self) -> bool:
        self.close_calls += 1
        return self.close_result


class _FakeApp:
    def __init__(self) -> None:
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


def _patch_argv(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(app_lifecycle.sys, "argv", argv)
    monkeypatch.setattr(app_lifecycle.sys, "executable", "C:/fake/python.exe")


def test_restart_application_relaunches_and_quits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_argv(monkeypatch, ["start_ui.py", "-c", "myprofile"])
    monkeypatch.setattr(app_lifecycle, "IS_FROZEN", False)

    started: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        app_lifecycle.QProcess,
        "startDetached",
        staticmethod(lambda program, args: started.append((program, args)) or True),
    )
    fake_app = _FakeApp()
    monkeypatch.setattr(
        app_lifecycle.QApplication, "instance", staticmethod(lambda: fake_app)
    )

    main_window = _FakeMainWindow(close_result=True)
    result = restart_application(main_window)  # type: ignore[arg-type]

    assert result is True
    assert main_window.close_calls == 1
    # source (non-frozen): full sys.argv (script path included) is forwarded.
    assert started == [("C:/fake/python.exe", ["start_ui.py", "-c", "myprofile"])]
    assert fake_app.quit_calls == 1


def test_restart_application_frozen_drops_argv0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_argv(monkeypatch, ["NfoForge.exe", "-c", "myprofile"])
    monkeypatch.setattr(app_lifecycle, "IS_FROZEN", True)
    monkeypatch.setattr(app_lifecycle.sys, "executable", "C:/fake/NfoForge.exe")

    started: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        app_lifecycle.QProcess,
        "startDetached",
        staticmethod(lambda program, args: started.append((program, args)) or True),
    )
    monkeypatch.setattr(
        app_lifecycle.QApplication, "instance", staticmethod(lambda: _FakeApp())
    )

    main_window = _FakeMainWindow(close_result=True)
    result = restart_application(main_window)  # type: ignore[arg-type]

    assert result is True
    # frozen: sys.executable IS the app, so argv[0] is dropped to avoid duplicating it.
    assert started == [("C:/fake/NfoForge.exe", ["-c", "myprofile"])]


def test_restart_application_aborts_if_close_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[object] = []
    monkeypatch.setattr(
        app_lifecycle.QProcess,
        "startDetached",
        staticmethod(lambda *a, **k: started.append(1) or True),
    )
    quit_calls: list[object] = []
    monkeypatch.setattr(
        app_lifecycle.QApplication,
        "instance",
        staticmethod(
            lambda: type("A", (), {"quit": lambda self: quit_calls.append(1)})()
        ),
    )

    main_window = _FakeMainWindow(close_result=False)
    result = restart_application(main_window)  # type: ignore[arg-type]

    assert result is False
    assert not started
    assert not quit_calls


def test_restart_application_does_not_quit_if_relaunch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_argv(monkeypatch, ["start_ui.py"])
    monkeypatch.setattr(app_lifecycle, "IS_FROZEN", False)
    monkeypatch.setattr(
        app_lifecycle.QProcess,
        "startDetached",
        staticmethod(lambda program, args: False),
    )
    fake_app = _FakeApp()
    monkeypatch.setattr(
        app_lifecycle.QApplication, "instance", staticmethod(lambda: fake_app)
    )

    main_window = _FakeMainWindow(close_result=True)
    result = restart_application(main_window)  # type: ignore[arg-type]

    assert result is False
    assert main_window.close_calls == 1
    assert fake_app.quit_calls == 0
