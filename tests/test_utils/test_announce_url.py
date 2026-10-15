import pytest

from nfoforge.utils.announce_url import ensure_torrentleech_announce_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", ""),
        ("https://tracker.invalid/key", "https://tracker.invalid/key/announce"),
        (
            "https://tracker.invalid/key/",
            "https://tracker.invalid/key/announce",
        ),
        (
            "https://tracker.invalid/key/announce",
            "https://tracker.invalid/key/announce",
        ),
        (
            "https://tracker.invalid/key/announce.php",
            "https://tracker.invalid/key/announce.php",
        ),
        (
            "https://tracker.invalid/key?passkey=secret",
            "https://tracker.invalid/key/announce?passkey=secret",
        ),
        ("not a URL", "not a URL"),
    ],
)
def test_ensure_torrentleech_announce_url(
    value: str | None, expected: str | None
) -> None:
    assert ensure_torrentleech_announce_url(value) == expected
