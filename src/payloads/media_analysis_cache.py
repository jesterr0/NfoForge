from dataclasses import dataclass, field

from pymediainfo import MediaInfo


@dataclass(slots=True)
class MediaAnalysisCache:
    """Cache derived media facts for one :class:`MediaInputPayload`.

    The cache keeps the ``MediaInfo`` object alongside each value. That makes
    the object-identity key safe if a payload replaces a media object during a
    run and Python later reuses the old object's id.
    """

    _resolution: dict[tuple[int, bool], tuple[MediaInfo, str]] = field(
        default_factory=dict
    )

    def get_resolution(self, media_info: MediaInfo, remove_scan: bool) -> str | None:
        key = (id(media_info), remove_scan)
        cached = self._resolution.get(key)
        if cached is None:
            return None

        if cached[0] is not media_info:
            self._resolution.pop(key, None)
            return None

        return cached[1]

    def set_resolution(
        self, media_info: MediaInfo, remove_scan: bool, resolution: str
    ) -> None:
        self._resolution[(id(media_info), remove_scan)] = (media_info, resolution)

    def clear(self) -> None:
        """Discard all derived values before a payload is reused."""
        self._resolution.clear()
