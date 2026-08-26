from dataclasses import dataclass


@dataclass(slots=True)
class ImagePayloadBase:
    base_url: str | None = None
    enabled: bool = False

    def is_configured(self) -> bool:
        """Whether this host has everything it needs to be offered as a destination.

        Overridden per host. This replaces a reflective "every field except
        `enabled` must be truthy" check at the call site, which quietly turned
        any new optional field into a required credential.
        """
        return bool(self.base_url)
