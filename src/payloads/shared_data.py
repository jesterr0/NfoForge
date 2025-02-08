from dataclasses import dataclass, field
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.packages.custom_types import ImageUploadData
from src.enums.tracker_selection import TrackerSelection


@dataclass(slots=True)
class SharedPayload:
    url_data: list[ImageUploadData] = field(default_factory=list)
    selected_trackers: Sequence[TrackerSelection] | None = None
    loaded_images: Sequence[Path] | None = None
    dynamic_data: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        self.url_data.clear()
        self.selected_trackers = None
        self.loaded_images = None
        self.dynamic_data.clear()
