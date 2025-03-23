import re


def ci_replace_filter(value: str, old: str, new: str) -> str:
    return re.sub(re.escape(old), new, value, flags=re.IGNORECASE)


def ci_replace_function(text: str, old: str, new: str) -> str:
    return re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
