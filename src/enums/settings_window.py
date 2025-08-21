from enum import auto

from src.enums import CaseInsensitiveEnum


class SettingsTabs(CaseInsensitiveEnum):
    GENERAL_SETTINGS = auto()
    MOVIES_SETTINGS = auto()
    SERIES_SETTINGS = auto()
    GLOBAL_SETTINGS = auto()
    TEMPLATES_SETTINGS = auto()
    USER_TOKENS_SETTINGS = auto()
    SECURITY_SETTINGS = auto()
    CLIENTS_SETTINGS = auto()
    TRACKERS_SETTINGS = auto()
    SCREENSHOTS_SETTINGS = auto()
    DEPENDENCIES_SETTINGS = auto()
    ABOUT_TAB = auto()
