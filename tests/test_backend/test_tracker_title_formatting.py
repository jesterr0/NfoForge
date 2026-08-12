"""Every tracker must be routed to the formatter its uploader actually uses.

`ProcessBackEnd.tracker_title_formatting` picks the formatting applied to a
generated (or user-edited) title before it is shown and stored, and each
uploader applies its own again at upload. The two have to agree: a tracker
routed to the wrong branch here shows the user one title and uploads another.

The mapping below is declared rather than derived, so adding a tracker forces
a decision about which formatter it gets instead of silently inheriting the
UNIT3D default.
"""

from typing import cast

import pytest

from src.backend.process import ProcessBackEnd
from src.backend.trackers.beyondhd import BHDUploader
from src.backend.trackers.hdb import HDBUploader
from src.backend.trackers.seedpool import SeedPoolUploader
from src.backend.trackers.torrentleech import TLUploader
from src.backend.trackers.unit3d_base import Unit3dBaseUploader
from src.config.config import ConfigManager
from src.enums.tracker_selection import TrackerSelection

# a dotted release name, which is what the filename fallback looks like
SOURCE_NAME = "Example.Movie.2026.1080p.WEB-DL.AAC.2.0.H.264-GRP"

_UNIT3D_SPACED = (
    TrackerSelection.REELFLIX,
    TrackerSelection.AITHER,
    TrackerSelection.HUNO,
    TrackerSelection.LST,
    TrackerSelection.DARK_PEERS,
    TrackerSelection.SHARE_ISLAND,
    TrackerSelection.UPLOAD_CX,
    TrackerSelection.ONLY_ENCODES,
    TrackerSelection.BLUTOPIA,
    TrackerSelection.UTOPIA,
    TrackerSelection.YU_SCENE,
    TrackerSelection.FEAR_NO_PEER,
)

EXPECTED_FORMATTER = {
    # SeedPool names uploads after the release, so it is the one UNIT3D
    # tracker that keeps the dotted form
    TrackerSelection.SEEDPOOL: SeedPoolUploader.generate_release_title,
    TrackerSelection.TORRENT_LEECH: TLUploader.generate_release_title,
    TrackerSelection.BEYOND_HD: BHDUploader.generate_release_title,
    TrackerSelection.HDB: HDBUploader.generate_release_title,
    # PTP dictates no title formatting of its own
    TrackerSelection.PASS_THE_POPCORN: lambda title: title,
    **{
        tracker: Unit3dBaseUploader.generate_release_title for tracker in _UNIT3D_SPACED
    },
}


def _backend() -> ProcessBackEnd:
    backend = object.__new__(ProcessBackEnd)
    backend.config = cast(ConfigManager, object())
    return backend


def test_every_tracker_has_an_expected_formatter() -> None:
    missing = set(TrackerSelection) - set(EXPECTED_FORMATTER)
    assert not missing, f"trackers missing a title-formatting expectation: {missing}"


@pytest.mark.parametrize("tracker", list(EXPECTED_FORMATTER))
def test_routing_matches_the_uploaders_own_formatter(tracker: TrackerSelection) -> None:
    expected = EXPECTED_FORMATTER[tracker](SOURCE_NAME)

    assert _backend().tracker_title_formatting(tracker, SOURCE_NAME) == expected


def test_seedpool_keeps_the_dotted_form_its_siblings_lose() -> None:
    """The regression this file was added for: SeedPool sat in the UNIT3D
    branch and had its release name flattened to prose."""
    backend = _backend()

    assert backend.tracker_title_formatting(TrackerSelection.SEEDPOOL, SOURCE_NAME) == (
        SOURCE_NAME
    )
    assert backend.tracker_title_formatting(TrackerSelection.AITHER, SOURCE_NAME) == (
        "Example Movie 2026 1080p WEB-DL AAC 2.0 H 264-GRP"
    )
