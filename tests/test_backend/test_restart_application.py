import pytest

import src.backend.main_window as main_window_module
from src.backend.main_window import restart_application


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
    monkeypatch.setattr(main_window_module.sys, "argv", argv)
    monkeypatch.setattr(main_window_module.sys, "executable", "C:/fake/python.exe")


def test_restart_application_relaunches_and_quits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_argv(monkeypatch, ["start_ui.py", "-c", "myprofile"])
    monkeypatch.setattr(main_window_module, "IS_FROZEN", False)

    started: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        main_window_module.QProcess,
        "startDetached",
        staticmethod(lambda program, args: started.append((program, args)) or True),
    )
    fake_app = _FakeApp()
    monkeypatch.setattr(
        main_window_module.QApplication, "instance", staticmethod(lambda: fake_app)
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
    monkeypatch.setattr(main_window_module, "IS_FROZEN", True)
    monkeypatch.setattr(main_window_module.sys, "executable", "C:/fake/NfoForge.exe")

    started: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        main_window_module.QProcess,
        "startDetached",
        staticmethod(lambda program, args: started.append((program, args)) or True),
    )
    monkeypatch.setattr(
        main_window_module.QApplication, "instance", staticmethod(lambda: _FakeApp())
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
        main_window_module.QProcess,
        "startDetached",
        staticmethod(lambda *a, **k: started.append(1) or True),
    )
    quit_calls: list[object] = []
    monkeypatch.setattr(
        main_window_module.QApplication,
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
    monkeypatch.setattr(main_window_module, "IS_FROZEN", False)
    monkeypatch.setattr(
        main_window_module.QProcess,
        "startDetached",
        staticmethod(lambda program, args: False),
    )
    fake_app = _FakeApp()
    monkeypatch.setattr(
        main_window_module.QApplication, "instance", staticmethod(lambda: fake_app)
    )

    main_window = _FakeMainWindow(close_result=True)
    result = restart_application(main_window)  # type: ignore[arg-type]

    assert result is False
    assert main_window.close_calls == 1
    assert fake_app.quit_calls == 0
