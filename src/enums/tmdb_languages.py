from enum import Enum

from typing_extensions import override


class TMDBLanguage(Enum):
    """TMDB supported languages with ISO codes and human-readable names."""

    # Major world languages
    EN_US = ("en-US", "English (United States)")
    EN_GB = ("en-GB", "English (United Kingdom)")
    EN_CA = ("en-CA", "English (Canada)")
    EN_AU = ("en-AU", "English (Australia)")

    # Spanish variants
    ES_ES = ("es-ES", "Spanish (Spain)")
    ES_MX = ("es-MX", "Spanish (Mexico)")
    ES_AR = ("es-AR", "Spanish (Argentina)")

    # French variants
    FR_FR = ("fr-FR", "French (France)")
    FR_CA = ("fr-CA", "French (Canada)")

    # German variants
    DE_DE = ("de-DE", "German (Germany)")
    DE_AT = ("de-AT", "German (Austria)")
    DE_CH = ("de-CH", "German (Switzerland)")

    # Italian
    IT_IT = ("it-IT", "Italian (Italy)")

    # Portuguese variants
    PT_BR = ("pt-BR", "Portuguese (Brazil)")
    PT_PT = ("pt-PT", "Portuguese (Portugal)")

    # Russian and Slavic languages
    RU_RU = ("ru-RU", "Russian (Russia)")
    UK_UA = ("uk-UA", "Ukrainian (Ukraine)")
    PL_PL = ("pl-PL", "Polish (Poland)")
    CS_CZ = ("cs-CZ", "Czech (Czech Republic)")
    SK_SK = ("sk-SK", "Slovak (Slovakia)")
    BG_BG = ("bg-BG", "Bulgarian (Bulgaria)")
    HR_HR = ("hr-HR", "Croatian (Croatia)")
    SR_RS = ("sr-RS", "Serbian (Serbia)")
    SL_SI = ("sl-SI", "Slovenian (Slovenia)")

    # East Asian languages
    JA_JP = ("ja-JP", "Japanese (Japan)")
    KO_KR = ("ko-KR", "Korean (South Korea)")
    ZH_CN = ("zh-CN", "Chinese (Simplified)")
    ZH_TW = ("zh-TW", "Chinese (Traditional)")
    ZH_HK = ("zh-HK", "Chinese (Hong Kong)")

    # Arabic variants
    AR_SA = ("ar-SA", "Arabic (Saudi Arabia)")
    AR_AE = ("ar-AE", "Arabic (UAE)")
    AR_EG = ("ar-EG", "Arabic (Egypt)")

    # Indian subcontinent languages
    HI_IN = ("hi-IN", "Hindi (India)")
    BN_BD = ("bn-BD", "Bengali (Bangladesh)")
    TA_IN = ("ta-IN", "Tamil (India)")
    TE_IN = ("te-IN", "Telugu (India)")
    UR_PK = ("ur-PK", "Urdu (Pakistan)")

    # Southeast Asian languages
    TH_TH = ("th-TH", "Thai (Thailand)")
    VI_VN = ("vi-VN", "Vietnamese (Vietnam)")
    ID_ID = ("id-ID", "Indonesian (Indonesia)")
    MS_MY = ("ms-MY", "Malay (Malaysia)")
    TL_PH = ("tl-PH", "Filipino (Philippines)")

    # Nordic languages
    SV_SE = ("sv-SE", "Swedish (Sweden)")
    NO_NO = ("no-NO", "Norwegian (Norway)")
    DA_DK = ("da-DK", "Danish (Denmark)")
    FI_FI = ("fi-FI", "Finnish (Finland)")
    IS_IS = ("is-IS", "Icelandic (Iceland)")

    # Other European languages
    NL_NL = ("nl-NL", "Dutch (Netherlands)")
    NL_BE = ("nl-BE", "Dutch (Belgium)")
    HU_HU = ("hu-HU", "Hungarian (Hungary)")
    RO_RO = ("ro-RO", "Romanian (Romania)")
    EL_GR = ("el-GR", "Greek (Greece)")
    TR_TR = ("tr-TR", "Turkish (Turkey)")
    HE_IL = ("he-IL", "Hebrew (Israel)")

    # Baltic languages
    LT_LT = ("lt-LT", "Lithuanian (Lithuania)")
    LV_LV = ("lv-LV", "Latvian (Latvia)")
    ET_EE = ("et-EE", "Estonian (Estonia)")

    # African languages
    AF_ZA = ("af-ZA", "Afrikaans (South Africa)")
    SW_KE = ("sw-KE", "Swahili (Kenya)")

    # Latin American languages
    CA_ES = ("ca-ES", "Catalan (Spain)")
    EU_ES = ("eu-ES", "Basque (Spain)")
    GL_ES = ("gl-ES", "Galician (Spain)")

    # Additional European languages
    MT_MT = ("mt-MT", "Maltese (Malta)")
    CY_GB = ("cy-GB", "Welsh (United Kingdom)")
    GA_IE = ("ga-IE", "Irish (Ireland)")

    # Middle Eastern languages
    FA_IR = ("fa-IR", "Persian (Iran)")
    AZ_AZ = ("az-AZ", "Azerbaijani (Azerbaijan)")
    KA_GE = ("ka-GE", "Georgian (Georgia)")
    HY_AM = ("hy-AM", "Armenian (Armenia)")

    def __init__(self, code: str, display_name: str):
        self.code = code
        self.display_name = display_name

    @override
    def __str__(self) -> str:
        return self.display_name

    @classmethod
    def from_code(cls, code: str) -> "TMDBLanguage":
        """Get TMDBLanguage from language code."""
        for lang in cls:
            if lang.code == code:
                return lang

        # default fallback
        return cls.EN_US

    @classmethod
    def get_codes(cls) -> list[str]:
        """Get list of all language codes."""
        return [lang.code for lang in cls]

    @classmethod
    def get_display_names(cls) -> list[str]:
        """Get list of all display names."""
        return [lang.display_name for lang in cls]
