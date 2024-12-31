class NfoForgeError(Exception):
    """Base exception for NfoForge"""


class MediaFileNotFoundError(NfoForgeError):
    """Exception when we can't find the media file"""


class ConfigError(NfoForgeError):
    """Exception incorrect screenshot count"""


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


class ProcessError(NfoForgeError):
    """Custom exception class for process errors"""


class TrackerClientError(NfoForgeError):
    """Custom exception class for tracker client errors"""


class PluginError(NfoForgeError):
    """Custom exception for plugin related errors"""


class MediaSearchError(NfoForgeError):
    """Custom exception for media search related errors"""
