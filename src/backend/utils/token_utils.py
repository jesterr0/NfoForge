from collections.abc import Sequence
import re


def get_prompt_tokens(text: str) -> Sequence[str]:
    """Find all tokens formatted like {{ prompt_* }} and return them in a list"""
    return re.findall(r"\{\{\s*(prompt_[^}\s]+)\s*\}\}", text)
