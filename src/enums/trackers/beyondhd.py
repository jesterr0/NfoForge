from enum import Enum


class BHDCategoryID(Enum):
    MOVIE = 1
    TV = 2


class BHDType(Enum):
    BD_25 = "BD 25"
    BD_50 = "BD 50"
    BD_REMUX = "BD Remux"
    DVD_5 = "DVD 5"
    DVD_9 = "DVD 9"
    DVD_REMUX = "DVD Remux"
    P_1080I = "1080i"
    P_1080P = "1080p"
    P_2160P = "2160p"
    P_480P = "480p"
    P_540P = "540p"
    P_576P = "576p"
    P_720P = "720p"
    UHD_100 = "UHD 100"
    UHD_50 = "UHD 50"
    UHD_66 = "UHD 66"
    UHD_REMUX = "UHD Remux"
    OTHER = "Other"


class BHDSource(Enum):
    BLURAY = "Blu-ray"
    DVD = "DVD"
    HD_DVD = "HD-DVD"
    HDTV = "HDTV"
    WEB = "WEB"


class BHDPromo(Enum):
    NO_PROMO = 0
    PROMO_25 = 1
    PROMO_50 = 2
    PROMO_75 = 3
    FREELEECH = 4
    FREELEECH_LIMITED_UL = 5

    def __str__(self) -> str:
        str_map = {
            BHDPromo.NO_PROMO: "No Promo",
            BHDPromo.PROMO_25: "25% Promo",
            BHDPromo.PROMO_50: "50% Promo",
            BHDPromo.PROMO_75: "75% Promo",
            BHDPromo.FREELEECH: "Freeleech",
            BHDPromo.FREELEECH_LIMITED_UL: "Freeleech (Limited UL)",
        }
        return str_map[self]


class BHDLiveRelease(Enum):
    DRAFT = 0
    LIVE = 1

    def __str__(self) -> str:
        str_map = {
            BHDLiveRelease.DRAFT: "Draft",
            BHDLiveRelease.LIVE: "Live",
        }
        return str_map[self]
