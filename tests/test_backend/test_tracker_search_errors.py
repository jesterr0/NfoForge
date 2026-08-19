from unittest.mock import MagicMock, patch

import pytest

from src.backend.trackers.passthepopcorn import PTPSearch
from src.backend.trackers.unit3d_base import Unit3dBaseSearch
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import TrackerError


@pytest.mark.parametrize("status_code", [401, 403, 500])
@patch("niquests.Session.get")
def test_ptp_search_reports_http_failures(get: MagicMock, status_code: int) -> None:
    response = MagicMock(status_code=status_code, reason="failure")
    get.return_value = response
    search = PTPSearch("api-user", "api-key")

    with pytest.raises(TrackerError, match=f"HTTP {status_code}"):
        search.search("Example", 2026, "Example.2026.mkv")


@pytest.mark.parametrize("status_code", [401, 403, 500])
@patch("niquests.Session.get")
def test_unit3d_search_reports_http_failures(get: MagicMock, status_code: int) -> None:
    response = MagicMock(status_code=status_code, reason="failure")
    get.return_value.__enter__.return_value = response
    search = Unit3dBaseSearch(
        TrackerSelection.AITHER,
        TrackerSelection.AITHER.get_root_url(),
        "api-key",
    )

    with pytest.raises(TrackerError, match=f"HTTP {status_code}"):
        search.search("Example.2026.mkv")
