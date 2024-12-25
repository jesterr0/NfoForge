from dataclasses import dataclass

from src.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class CheveretoV3Payload(ImagePayloadBase):
    base_url: str | None = None
    user: str | None = None
    password: str | None = None
