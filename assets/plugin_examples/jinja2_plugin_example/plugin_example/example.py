import re


def ci_replace_filter(value: str, old: str, new: str) -> str:
    """Usage: {{ SOME_VALUE_OR_VARIABLE|ci_replace_filter("b", "x") }}"""
    return re.sub(re.escape(old), new, value, flags=re.IGNORECASE)


def ci_replace_function(text: str, old: str, new: str) -> str:
    """Usage: {{ ci_replace_function("BillyBob", "b", "z") }}"""
    return re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
