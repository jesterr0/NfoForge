from enum import Enum


class DebugDataType(Enum):
    """Debug data types"""

    JSON = ".json"
    TEXT = ".txt"


class LogLevel(Enum):
    """Enum class for pythons built in logging class debug types"""

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    def __str__(self) -> str:
        level_map = {
            LogLevel.DEBUG: "Debug",
            LogLevel.INFO: "Info",
            LogLevel.WARNING: "Warning",
            LogLevel.ERROR: "Error",
            LogLevel.CRITICAL: "Critical",
        }
        return level_map[self]


class LogSource(Enum):
    """
    Enum to control tag for frontend vs backend
    FE: Frontend
    BE: Backend
    """

    FE = "[FE]"
    BE = "[BE]"
