from pathlib import Path


class NfoForgeError(Exception):
    """Base exception for NfoForge"""


class MediaFileNotFoundError(NfoForgeError):
    """Exception when we can't find the media file"""


class ConfigError(NfoForgeError):
    """Exception incorrect screenshot count"""


class ConfigSchemaError(ConfigError):
    """Exception for incompatible or missing config schema versions"""

    def __init__(self, message: str, config_path: Path | None = None) -> None:
        super().__init__(message)
        self.config_path = config_path


class MediaParsingError(NfoForgeError):
    """Exception for media parsing errors"""


class GuessitParsingError(NfoForgeError):
    """Exception for guessing parsing errors"""


class MissingVideoTrackError(NfoForgeError):
    """Error for missing video track"""


class ResolutionMappingError(NfoForgeError):
    """Error for missing video resolution map"""


class InvalidTokenError(NfoForgeError):
    """Error for invalid tokens"""


class DebugDumpError(NfoForgeError):
    """Error for debug dump errors"""


class MediaFrameCountError(NfoForgeError):
    """Error for failure to detect media frame count"""


class DependencyNotFoundError(NfoForgeError):
    """Custom exception class to call when a dependency is not found"""


class ImageUploadError(NfoForgeError):
    """Custom exception class to call when uploading images"""


class TrackerError(NfoForgeError):
    """Custom exception class for tracker errors"""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool | None = None,
        server_accepted: bool = False,
        phase: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.server_accepted = server_accepted
        self.phase = phase
        self.status_code = status_code


class ProcessError(NfoForgeError):
    """Custom exception class for process errors"""


class ProcessCancelled(ProcessError):
    """The user cancelled the remaining processing work."""


class TrackerClientError(NfoForgeError):
    """Custom exception class for tracker client errors"""


class PluginError(NfoForgeError):
    """Custom exception for plugin related errors"""


class PluginExecutionError(PluginError):
    """A validated plugin failed while executing one of its capabilities."""

    def __init__(self, plugin_id: str, capability: str, cause: Exception) -> None:
        super().__init__(f"Plugin '{plugin_id}' failed in {capability}: {cause}")
        self.plugin_id = plugin_id
        self.capability = capability
        self.cause = cause


class MediaSearchError(NfoForgeError):
    """Custom exception for media search related errors"""


class MediaSearchUnavailableError(MediaSearchError):
    """Raised when a required media metadata service cannot be reached."""


class ImageHostError(NfoForgeError):
    """Custom exception for image host related errors"""


class URLFormattingError(NfoForgeError):
    """Custom exception for URL formatting related errors"""


class MkbrrTorrentError(NfoForgeError):
    """Custom exception mkbrr torrent related errors"""
