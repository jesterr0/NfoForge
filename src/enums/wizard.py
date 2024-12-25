from enum import Enum, auto as auto_enum


class WizardPages(Enum):
    BASIC_INPUT_PAGE = auto_enum()
    ADVANCED_INPUT_PAGE = auto_enum()
    PLUGIN_INPUT_PAGE = auto_enum()
    MEDIA_SEARCH_PAGE = auto_enum()
    RENAME_ENCODE_PAGE = auto_enum()
    IMAGES_PAGE = auto_enum()
    TRACKERS_PAGE = auto_enum()
    NFO_TEMPLATE_PAGE = auto_enum()
    OVERVIEW_PAGE = auto_enum()
    PROCESS_PAGE = auto_enum()
