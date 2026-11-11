"""The one place a disc's size class is decided.

Every tracker has a field for it (BHD's type, PTP's codec, the release name on
others), and deciding it separately per tracker is how they drift apart.
"""

from __future__ import annotations

from enum import StrEnum

from nfoforge.core.disc.model import DiscType


class DiscSize(StrEnum):
    BD25 = "BD25"
    BD50 = "BD50"
    BD66 = "BD66"
    BD100 = "BD100"
    DVD5 = "DVD5"
    DVD9 = "DVD9"


# Upper bound of each class, in bytes. A release is sized by what is on disk,
# which never exceeds what the medium holds.
_BLURAY_LIMITS = (
    (25_025_314_816, DiscSize.BD25),
    (50_050_629_632, DiscSize.BD50),
    (66_000_000_000, DiscSize.BD66),
)
_DVD5_LIMIT = 4_700_372_992


def disc_size_class(disc_type: DiscType, size: int) -> DiscSize:
    if disc_type is DiscType.DVD:
        return DiscSize.DVD5 if size <= _DVD5_LIMIT else DiscSize.DVD9
    for limit, size_class in _BLURAY_LIMITS:
        if size <= limit:
            return size_class
    return DiscSize.BD100
