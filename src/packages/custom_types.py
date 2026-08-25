from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from typing_extensions import override

from src.enums.image_host import ImageHost, ImageSource


class SubNames(NamedTuple):
    source: str
    encode: str


class CropValues(NamedTuple):
    top: int
    bottom: int
    left: int
    right: int


class AdvancedResize(NamedTuple):
    src_left: float
    src_top: float
    src_width: float
    src_height: float


class ImageUploadData(NamedTuple):
    url: str | None
    medium_url: str | None


@dataclass(frozen=True, slots=True)
class ImageHostRef:
    """One selectable image-upload destination.

    `ImageHost` names the *kind* of host; it cannot name *which* one when a kind
    holds several user-configured sites (Chevereto v3/v4). `instance_id` is that
    missing half, and stays empty for the single-slot hosts.

    `label` is display only and deliberately excluded from equality, so renaming
    an instance does not orphan the saved jobs and per-tracker selections that
    point at it.
    """

    kind: ImageHost
    instance_id: str = ""
    label: str = field(default="", compare=False)

    def key(self) -> str:
        """The stable string identity, as persisted."""
        if self.instance_id:
            return f"{self.kind.name}:{self.instance_id}"
        return self.kind.name

    @classmethod
    def from_key(cls, value: str, label: str = "") -> "ImageHostRef | None":
        """Rebuild a ref from `key()`, or from a legacy bare display name.

        Returns None for a value naming a host this build no longer has, which
        a caller is expected to skip rather than treat as an error.
        """
        kind_name, _, instance_id = value.partition(":")
        try:
            kind = ImageHost(kind_name)
        except ValueError:
            return None
        return cls(kind=kind, instance_id=instance_id, label=label)

    @override
    def __str__(self) -> str:
        return self.label or str(self.kind)


# Not a real destination -- the "do not upload" choice, given a ref so every
# selection site can hold one type instead of a union with the bare enum.
DISABLED_HOST = ImageHostRef(ImageHost.DISABLED)


class ImageUploadFromTo(NamedTuple):
    img_from: ImageSource
    img_to: ImageSource | ImageHostRef


class RenameNormalization(NamedTuple):
    normalized: str
    re_gex: tuple[str, ...]


class ComparisonPair(NamedTuple):
    source: Path
    media: Path
    script: Path | None
