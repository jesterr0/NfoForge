import pytest

from src.utils.secret_redaction import scrub_secrets


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://tracker.example/deadbeefdeadbeefdeadbeefdeadbeef/announce",
            "https://tracker.example/[redacted]/announce",
        ),
        (
            "https://tracker.example/announce/deadbeefdeadbeefdeadbeefdeadbeef",
            "https://tracker.example/announce/[redacted]",
        ),
    ],
)
def test_scrub_secrets_redacts_a_passkey_carried_as_an_announce_path_segment(
    url: str,
    expected: str,
) -> None:
    """Announce URLs carry the passkey as a bare segment, not a named field.

    A passkey is the highest-value secret the app holds, and announce URLs
    reach the log through the mkbrr command line.
    """
    assert scrub_secrets(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://tracker.example/announce",
        "https://tracker.example/announce.php",
    ],
)
def test_scrub_secrets_keeps_a_keyless_announce_endpoint_readable(url: str) -> None:
    """Without a key segment there is nothing to hide; keep the URL useful."""
    assert scrub_secrets(url) == url


def test_scrub_secrets_redacts_a_passkey_in_a_full_mkbrr_command_line() -> None:
    """The real sink: `mkbrr command: ...` interpolates the announce URL."""
    scrubbed = scrub_secrets(
        "mkbrr command: mkbrr create --tracker "
        "https://tracker.example/deadbeefdeadbeefdeadbeefdeadbeef/announce "
        "--source EXAMPLE"
    )

    assert "deadbeefdeadbeefdeadbeefdeadbeef" not in scrubbed
    assert "--source EXAMPLE" in scrubbed
