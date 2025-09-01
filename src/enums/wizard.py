from enum import Enum, auto as auto_enum

from typing_extensions import override


class WizardPages(Enum):
    INPUT_PAGE = auto_enum()
    PLUGIN_INPUT_PAGE = auto_enum()
    MEDIA_SEARCH_PAGE = auto_enum()
    SERIES_MATCHER_PAGE = auto_enum()
    RENAME_ENCODE_PAGE = auto_enum()
    RENAME_ENCODE_SERIES_PAGE = auto_enum()
    IMAGES_PAGE = auto_enum()
    TRACKERS_PAGE = auto_enum()
    RELEASE_NOTES_PAGE = auto_enum()
    NFO_TEMPLATE_PAGE = auto_enum()
    PROCESS_PAGE = auto_enum()

    @override
    def __str__(self) -> str:
        return self.name.replace("_", " ").title()
