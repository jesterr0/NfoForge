from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.enums.image_host import ImageHost, ImageSource
from src.enums.tracker_selection import TrackerSelection
from src.packages.custom_types import ImageUploadData, ImageUploadFromTo


@dataclass(slots=True)
class SharedPayload:
    url_data: list[ImageUploadData] = field(default_factory=list)
    selected_trackers: Sequence[TrackerSelection] | None = None
    loaded_images: Sequence[Path] | None = None
    generated_images: bool = False
    is_comparison_images: bool = False
    dynamic_data: dict[str, Any] = field(default_factory=dict)
    release_notes: str | None = None
    # Where each tracker's images are coming from and going to for this run.
    # The process page's combo boxes are the UI for this, but the selection
    # lives here so it can be carried with the run (and saved to a job file)
    # instead of only existing inside the widgets.
    tracker_image_hosts: dict[TrackerSelection, ImageUploadFromTo] = field(
        default_factory=dict
    )

    # Screenshots already uploaded, and where they went. A resumed job reuses
    # these instead of uploading the same images again -- but only while the
    # destination still matches, since changing a tracker's image host makes
    # the recorded URLs the wrong host's.
    uploaded_images: dict[TrackerSelection, dict[int, ImageUploadData]] = field(
        default_factory=dict
    )
    uploaded_image_hosts: dict[TrackerSelection, ImageHost | ImageSource] = field(
        default_factory=dict
    )

    # The same URLs again, filed by the host that issued them. The two maps
    # above answer "has *this tracker* already uploaded?"; this answers "does
    # this bundle hold images for *this host*?", which is the question a
    # tracker added after the fact asks -- and the one a narrowed job could not
    # answer, because narrowing takes the per-tracker maps with it.
    #
    # Written as soon as a host's uploads come back, before anything can raise
    # over a different host's failure, so a batch that succeeded is never lost
    # to a batch that did not.
    uploaded_images_by_host: dict[
        ImageHost | ImageSource, dict[int, ImageUploadData]
    ] = field(default_factory=dict)

    base_torrent: Path | None = None
    """An already-hashed torrent a resumed job brought with it, if any."""

    # The finished title and NFO per tracker. Populating this is what makes a
    # job "prepared": a run that finds it already filled in skips generating
    # titles/NFOs *and* skips both user prompts, which is what lets a prepared
    # job be uploaded unattended. It also preserves any edits made in the
    # overview dialog, which would otherwise be regenerated away.
    tracker_release_data: dict[TrackerSelection, dict[str, str | None]] = field(
        default_factory=dict
    )

    prompt_token_answers: dict[str, str] = field(default_factory=dict)
    """Answers already given for a template's prompt tokens, so nothing re-asks."""

    template_fingerprints: dict[str, str] = field(default_factory=dict)
    """NFO template name -> content hash at the time the release data was frozen.

    Frozen NFOs deliberately win over a since-edited template, so this exists
    purely to make that staleness visible instead of silent.
    """

    def is_prepared(self, trackers: Sequence[TrackerSelection] | None = None) -> bool:
        """Whether titles and NFOs are already generated for this run.

        Derived rather than stored as its own flag, so there is no second piece
        of state that can disagree with the data itself.
        """
        required = tuple(
            trackers if trackers is not None else self.selected_trackers or ()
        )
        if not required:
            return bool(self.tracker_release_data)
        return all(tracker in self.tracker_release_data for tracker in required)

    def reset(self) -> None:
        self.url_data.clear()
        self.selected_trackers = None
        self.loaded_images = None
        self.generated_images = False
        self.is_comparison_images = False
        self.dynamic_data.clear()
        self.release_notes = None
        self.tracker_image_hosts.clear()
        self.uploaded_images.clear()
        self.uploaded_image_hosts.clear()
        self.uploaded_images_by_host.clear()
        self.base_torrent = None
        self.tracker_release_data.clear()
        self.prompt_token_answers.clear()
        self.template_fingerprints.clear()
