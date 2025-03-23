import re


def normalize_super_sub(text):
    """Converts super strings to their normal counter parts with spaces"""
    superscript_map = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
    subscript_map = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

    # find occurrences of superscript/subscript numbers
    def replacer(match):
        before, script, after = match.groups()
        normalized = script.translate(superscript_map).translate(subscript_map)

        # ensure spaces are correctly placed
        before_space = "" if before.isspace() else " "
        after_space = "" if after.isspace() or after == "" else " "

        return f"{before}{before_space}{normalized}{after_space}{after}"

    pattern = re.compile(r"(\D|^)([⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]+)(\D|$)")
    return pattern.sub(replacer, text).strip()
