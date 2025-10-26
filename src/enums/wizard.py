from enum import Enum, auto

from typing_extensions import override


class WizardPages(Enum):
    INPUT_PAGE = auto()
    PLUGIN_INPUT_PAGE = auto()
    MEDIA_SEARCH_PAGE = auto()
    SERIES_MATCHER_PAGE = auto()
    RENAME_ENCODE_PAGE = auto()
    # RENAME_ENCODE_SERIES_PAGE = auto()
    IMAGES_PAGE = auto()
    TRACKERS_PAGE = auto()
    RELEASE_NOTES_PAGE = auto()
    NFO_TEMPLATE_PAGE = auto()
    PROCESS_PAGE = auto()

    @override
    def __str__(self) -> str:
        return self.name.replace("_", " ").title()
