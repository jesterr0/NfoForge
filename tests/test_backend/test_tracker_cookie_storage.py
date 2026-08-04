import json
from pathlib import Path

import niquests

from src.backend.trackers.cookie_storage import load_cookies, save_cookies


def test_cookie_storage_round_trips_json_and_restricts_permissions(
    tmp_path: Path, monkeypatch
) -> None:
    session = niquests.Session()
    session.cookies.set(
        "session_id",
        "secret-value",
        domain="tracker.example",
        path="/",
        secure=True,
    )
    path = tmp_path / "tracker.json"
    chmod_modes: list[int] = []
    original_chmod = Path.chmod

    def record_chmod(self: Path, mode: int) -> None:
        chmod_modes.append(mode)
        original_chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", record_chmod)
    save_cookies(session.cookies, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == [
        {
            "name": "session_id",
            "value": "secret-value",
            "domain": "tracker.example",
            "path": "/",
            "expires": None,
            "secure": True,
        }
    ]
    assert chmod_modes and set(chmod_modes) == {0o600}

    restored = niquests.Session()
    assert load_cookies(restored.cookies, path)
    cookie = next(iter(restored.cookies))
    assert cookie.name == "session_id"
    assert cookie.value == "secret-value"
    assert cookie.domain == "tracker.example"
    assert cookie.secure


def test_cookie_storage_ignores_invalid_or_legacy_data(tmp_path: Path) -> None:
    path = tmp_path / "tracker.json"
    path.write_bytes(b"cos\x80 pickle data")

    session = niquests.Session()
    assert not load_cookies(session.cookies, path)
    assert list(session.cookies) == []
