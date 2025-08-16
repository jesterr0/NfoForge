import re


def get_prompt_tokens(text: str) -> tuple[str]:
    """Find all tokens formatted like {{ prompt_* }} and return them in a tuple"""
    # Pattern to match prompt_* tokens in various Jinja2 contexts:
    # - {{ prompt_token }}
    # - {% if prompt_token %}
    # - {{ func(prompt_token) }}
    # - {{ prompt_token|filter }}
    # - {% for item in prompt_token %}
    pattern = r"(?:\{\{|\{%)\s*(?:[^}]*\b)?(prompt_[a-zA-Z_][a-zA-Z0-9_]*)\b"

    matches = re.findall(pattern, text)
    # remove duplicates while preserving order
    return tuple(dict.fromkeys(matches))
