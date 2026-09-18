import pytest

from src.utils.secret_redaction import blank_credentials, scrub_secrets


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


def test_blank_credentials_empties_a_credential_at_any_depth() -> None:
    document = {
        "general": {"releasers_name": "someone"},
        "tracker": {
            "aither": {
                "api_key": "SECRET",
                "announce_url": "https://aither.cc/announce/PASSKEY",
                "source": "Aither",
            }
        },
        "image_hosts": {
            "chevereto_v3": {
                "abc123": {"user": "me", "password": "hunter2", "label": "mine"}
            }
        },
    }

    touched = blank_credentials(document)

    assert document["tracker"]["aither"]["api_key"] == ""
    assert document["tracker"]["aither"]["announce_url"] == ""
    assert document["image_hosts"]["chevereto_v3"]["abc123"]["password"] == ""
    # Settings and identity are left alone.
    assert document["tracker"]["aither"]["source"] == "Aither"
    assert document["general"]["releasers_name"] == "someone"
    assert set(touched) == {
        "tracker.aither.api_key",
        "tracker.aither.announce_url",
        "image_hosts.chevereto_v3.abc123.user",
        "image_hosts.chevereto_v3.abc123.password",
    }


def test_blank_credentials_reaches_inside_an_array_of_tables() -> None:
    """Nothing in the schema uses one today, and a missed one is unrecoverable."""
    document = {"hosts": [{"api_key": "SECRET", "base_url": "https://example"}]}

    touched = blank_credentials(document)

    assert document["hosts"][0]["api_key"] == ""
    assert document["hosts"][0]["base_url"] == "https://example"
    assert touched == ("hosts[0].api_key",)


def test_blank_credentials_leaves_an_already_empty_value_alone() -> None:
    document = {"tracker": {"aither": {"api_key": ""}}}
    assert blank_credentials(document) == ()


def test_blank_credentials_does_not_replace_a_table_named_like_a_credential() -> None:
    """A Chevereto instance keyed `password` is a table, not a secret."""
    document = {"image_hosts": {"password": {"api_key": "SECRET", "label": "odd"}}}

    blank_credentials(document)

    assert document["image_hosts"]["password"]["label"] == "odd"
    assert document["image_hosts"]["password"]["api_key"] == ""


@pytest.mark.parametrize(
    ("uri", "expected"),
    (
        (
            "https://alice:swordfish@example.test/plugins/httprpc/action.php",
            "https://example.test/plugins/httprpc/action.php",
        ),
        (
            "http://bob:hunter2@127.0.0.1/transmission/rpc",
            "http://127.0.0.1/transmission/rpc",
        ),
    ),
)
def test_blank_credentials_removes_uri_userinfo_from_client_hosts(
    uri: str, expected: str
) -> None:
    document = {"torrent_client": {"client": {"host": uri}}}

    touched = blank_credentials(document)

    assert document["torrent_client"]["client"]["host"] == expected
    assert touched == ("torrent_client.client.host",)


def test_blank_credentials_keeps_a_public_client_host() -> None:
    document = {"torrent_client": {"client": {"host": "http://127.0.0.1"}}}

    assert blank_credentials(document) == ()
    assert document["torrent_client"]["client"]["host"] == "http://127.0.0.1"
