from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadData


@dataclass(slots=True)
class SharedPayload:
    url_data: list[ImageUploadData] = field(default_factory=list)
    selected_trackers: Sequence[TrackerSelection] | None = None
    loaded_images: Sequence[Path] | None = None
    generated_images: bool = False
    is_comparison_images: bool = False
    dynamic_data: dict[str, Any] = field(default_factory=dict)
    release_notes: str | None = None

    def reset(self) -> None:
        self.url_data.clear()
        self.selected_trackers = None
        self.loaded_images = None
        self.generated_images = False
        self.is_comparison_images = False
        self.dynamic_data.clear()
        self.release_notes = None
