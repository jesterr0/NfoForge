from dataclasses import dataclass

from nfoforge.payloads.image_hosts import ImagePayloadBase


@dataclass(slots=True)
class PixhostPayload(ImagePayloadBase):
    pass
