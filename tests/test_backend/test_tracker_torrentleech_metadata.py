"""TorrentLeech's optional ID fields (imdb / tvmazeid+tvmazetype).

Without these TL matches an upload on the release name alone and picks the
wrong entry for titles with several versions. Every case here asserts either
that we send the ID TL expects for that category, or that we send nothing at
all -- a wrong ID is worse than none, since it overrides TL's own detection.
"""

from typing import Any

import pytest

from src.backend.trackers.torrentleech import TLUploader
from src.backend.utils.tvmaze_client import TVmazeClient, normalize_imdb_id
from src.enums.media_type import MediaType


class _FakeTVmazeClient:
    """Stands in for TVmazeClient so these tests never touch the network."""

    def __init__(self, show_id: int | None = 82, episode_id: int | None = 4952) -> None:
        self.show_id = show_id
        self.episode_id = episode_id
        self.lookup_calls: list[tuple[str | None, str | None]] = []
        self.episode_calls: list[tuple[int, int, int]] = []
        self.closed = False

    def lookup_show_id(
        self, imdb_id: str | None = None, tvdb_id: str | None = None
    ) -> int | None:
        self.lookup_calls.append((imdb_id, tvdb_id))
        return self.show_id

    def get_episode_id(self, show_id: int, season: int, episode: int) -> int | None:
        self.episode_calls.append((show_id, season, episode))
        return self.episode_id

    def close(self) -> None:
        self.closed = True


def _uploader(**kwargs: Any) -> TLUploader:
    return TLUploader(announce_key="announce-key", **kwargs)


# ---------------------------------------------------------------------------
# IMDb normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("tt1630029", "tt1630029"),
        ("TT1630029", "tt1630029"),
        ("  tt1630029  ", "tt1630029"),
        # a plugin-supplied payload can carry the bare digits
        ("1630029", "tt1630029"),
        ("", None),
        (None, None),
        ("not-an-id", None),
        ("tt12", None),
    ),
)
def test_normalize_imdb_id(value: str | None, expected: str | None) -> None:
    assert normalize_imdb_id(value) == expected


# ---------------------------------------------------------------------------
# movies -> imdb
# ---------------------------------------------------------------------------


def test_movie_sends_imdb_id() -> None:
    uploader = _uploader(imdb_id="tt1630029")

    assert uploader._metadata_fields(
        MediaType.MOVIE, is_pack=False, is_anime=False
    ) == {"imdb": "tt1630029"}


def test_movie_without_imdb_id_sends_nothing() -> None:
    """TL then auto-detects, which is the behaviour we had before this existed."""
    uploader = _uploader(imdb_id=None)

    assert (
        uploader._metadata_fields(MediaType.MOVIE, is_pack=False, is_anime=False) == {}
    )


def test_movie_never_sends_a_tvmaze_id() -> None:
    """A movie carrying a stray tvdb_id must not be pinned to a TVmaze show."""
    client = _FakeTVmazeClient()
    uploader = _uploader(imdb_id="tt1630029", tvdb_id="121361", tvmaze_client=client)

    fields = uploader._metadata_fields(MediaType.MOVIE, is_pack=False, is_anime=False)

    assert fields == {"imdb": "tt1630029"}
    assert client.lookup_calls == []


# ---------------------------------------------------------------------------
# series -> tvmazeid + tvmazetype
#
# tvmazetype tells TL what the ID refers to: 1 for the show, 2 for a single
# episode. TVmaze numbers shows and episodes in separate namespaces (Game of
# Thrones is show 82; its S01E01 is episode 4952), which is why TL needs the
# discriminator at all.
# ---------------------------------------------------------------------------


def test_series_pack_sends_show_id_with_type_1() -> None:
    client = _FakeTVmazeClient()
    uploader = _uploader(imdb_id="tt0944947", season=1, tvmaze_client=client)

    fields = uploader._metadata_fields(MediaType.SERIES, is_pack=True, is_anime=False)

    assert fields == {"tvmazeid": 82, "tvmazetype": 1}
    # a pack covers the whole season, so no episode lookup should happen
    assert client.episode_calls == []


def test_single_episode_sends_episode_id_with_type_2() -> None:
    client = _FakeTVmazeClient()
    uploader = _uploader(imdb_id="tt0944947", season=1, episode=1, tvmaze_client=client)

    fields = uploader._metadata_fields(MediaType.SERIES, is_pack=False, is_anime=False)

    assert fields == {"tvmazeid": 4952, "tvmazetype": 2}
    assert client.episode_calls == [(82, 1, 1)]


def test_single_episode_falls_back_to_show_when_episode_lookup_misses() -> None:
    """TVmaze files specials outside the regular numbering, among other gaps.

    The show is still a correct title, just less specific -- better than
    dropping the metadata entirely and letting TL guess.
    """
    client = _FakeTVmazeClient(episode_id=None)
    uploader = _uploader(imdb_id="tt0944947", season=0, episode=1, tvmaze_client=client)

    fields = uploader._metadata_fields(MediaType.SERIES, is_pack=False, is_anime=False)

    assert fields == {"tvmazeid": 82, "tvmazetype": 1}


def test_series_without_a_tvmaze_match_sends_nothing() -> None:
    client = _FakeTVmazeClient(show_id=None)
    uploader = _uploader(imdb_id="tt0944947", tvmaze_client=client)

    assert (
        uploader._metadata_fields(MediaType.SERIES, is_pack=True, is_anime=False) == {}
    )


def test_series_lookup_passes_both_imdb_and_tvdb_ids() -> None:
    """Either ID resolves the show, so both are offered to widen the hit rate."""
    client = _FakeTVmazeClient()
    uploader = _uploader(imdb_id="tt0944947", tvdb_id="121361", tvmaze_client=client)

    uploader._metadata_fields(MediaType.SERIES, is_pack=True, is_anime=False)

    assert client.lookup_calls == [("tt0944947", "121361")]


def test_single_episode_without_season_or_episode_uses_show_id() -> None:
    client = _FakeTVmazeClient()
    uploader = _uploader(
        imdb_id="tt0944947", season=None, episode=None, tvmaze_client=client
    )

    fields = uploader._metadata_fields(MediaType.SERIES, is_pack=False, is_anime=False)

    assert fields == {"tvmazeid": 82, "tvmazetype": 1}
    assert client.episode_calls == []


# ---------------------------------------------------------------------------
# anime -> animeid, which we cannot resolve
# ---------------------------------------------------------------------------


def test_anime_sends_no_ids_at_all() -> None:
    """TL's anime category takes `animeid`; we carry AniList/MAL and cannot
    tell which (if either) TL means, so guessing could pin the upload to an
    unrelated title. Auto-detection is the safe answer."""
    client = _FakeTVmazeClient()
    uploader = _uploader(
        imdb_id="tt0944947", tvdb_id="121361", season=1, episode=1, tvmaze_client=client
    )

    assert (
        uploader._metadata_fields(MediaType.SERIES, is_pack=False, is_anime=True) == {}
    )
    assert client.lookup_calls == []


def test_anime_movie_sends_no_imdb_id() -> None:
    """An anime film is categorised ANIME by _detect_category, so it takes
    animeid rather than imdb -- the anime check must win over the movie one."""
    uploader = _uploader(imdb_id="tt1630029")

    assert (
        uploader._metadata_fields(MediaType.MOVIE, is_pack=False, is_anime=True) == {}
    )


# ---------------------------------------------------------------------------
# the fields reach the actual upload payload
# ---------------------------------------------------------------------------


def test_get_data_merges_metadata_with_announce_key_and_category() -> None:
    uploader = _uploader(imdb_id="tt1630029")

    data = uploader._get_data(
        "Example.Movie.2026.1080p.BluRay.x264-GRP",
        "1080p",
        MediaType.MOVIE,
        is_pack=False,
        is_anime=False,
    )

    assert data["announcekey"] == "announce-key"
    assert data["imdb"] == "tt1630029"
    assert "category" in data


def test_owned_tvmaze_client_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The uploader builds its own client when none is injected; that one is
    ours to close, and an injected one is not."""
    client = _FakeTVmazeClient()
    monkeypatch.setattr(
        "src.backend.trackers.torrentleech.TVmazeClient", lambda timeout: client
    )
    uploader = _uploader(imdb_id="tt0944947")

    uploader._metadata_fields(MediaType.SERIES, is_pack=True, is_anime=False)

    assert client.closed is True


def test_injected_tvmaze_client_is_not_closed() -> None:
    client = _FakeTVmazeClient()
    uploader = _uploader(imdb_id="tt0944947", tvmaze_client=client)

    uploader._metadata_fields(MediaType.SERIES, is_pack=True, is_anime=False)

    assert client.closed is False


# ---------------------------------------------------------------------------
# the TVmaze client must never break an upload
# ---------------------------------------------------------------------------


def test_tvmaze_client_returns_none_on_transport_failure() -> None:
    """A TVmaze outage degrades to auto-detection rather than a failed upload."""
    import niquests

    class _ExplodingSession:
        def get(self, *args: Any, **kwargs: Any) -> Any:
            raise niquests.exceptions.ConnectionError("boom")

    client = TVmazeClient(timeout=1, session=_ExplodingSession())  # type: ignore[arg-type]
    client.RETRY_BACKOFF_SECONDS = 0

    assert client.lookup_show_id(imdb_id="tt0944947") is None
