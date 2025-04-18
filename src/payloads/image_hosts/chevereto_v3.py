from dataclasses import dataclass

from src.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class CheveretoV3Payload(ImagePayloadBase):
    user: str | None = None
    password: str | None = None
