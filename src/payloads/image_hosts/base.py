from dataclasses import dataclass


@dataclass(slots=True)
class ImagePayloadBase:
    base_url: str | None = None
    enabled: bool = False
