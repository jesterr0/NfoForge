"""`nfo_template` is still the only key that names a template file.

The export sweep finds templates by looking for one key name, which is what
lets it cover a tracker table it has never been told about. It is also what
lets it miss one: a feature added later that names a template under a different
key would quietly stop being bundled, and the way that surfaces is somebody
else's shared configuration rendering blank.

This is the same shape of lock as `test_credential_fields.py` -- a new key has
to be classified before it can pass. It catches the likely naming, not every
possible one: a key called `layout` or `skin` that happened to name a file in
`templates/` would go unnoticed, and nothing cheap can find that.
"""

import tomllib
from typing import Any

from src.config.transfer import TEMPLATE_KEY
from tests.repo_paths import DEFAULT_CONFIG_TOML

NOT_A_TEMPLATE_REFERENCE = frozenset(
    {
        # A token string expanded per release, not the name of a file in
        # `templates/`, so it travels inside the profile like any other setting.
        "save_path_template",
    }
)


def _keys_mentioning_templates(value: Any, found: set[str]) -> None:
    """Every leaf key whose name mentions a template, at any depth.

    Leaf keys only. `[template_settings]` is a table whose own keys are colours
    and whitespace flags, and counting the table name would mean listing all of
    them as exceptions for no benefit.
    """
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        if isinstance(child, dict):
            _keys_mentioning_templates(child, found)
        elif "template" in key.casefold():
            found.add(key)


def test_only_one_key_in_the_schema_names_a_template_file() -> None:
    document = tomllib.loads(DEFAULT_CONFIG_TOML.read_text(encoding="utf-8"))

    found: set[str] = set()
    _keys_mentioning_templates(document, found)
    unclassified = found - {TEMPLATE_KEY} - NOT_A_TEMPLATE_REFERENCE

    assert not unclassified, (
        "These keys mention a template but are neither the key the export "
        "sweep looks for nor declared as something other than a file "
        f"reference, so a bundle may be leaving files behind: {sorted(found)}"
    )
    assert TEMPLATE_KEY in found, (
        f"'{TEMPLATE_KEY}' is no longer in the packaged default configuration, "
        "so the export sweep is looking for a key that does not exist."
    )


def test_the_lock_notices_a_new_template_key() -> None:
    """The lock above is only worth having if it can fail."""
    found: set[str] = set()
    _keys_mentioning_templates({"movie": {"intro_template": "banner"}}, found)

    assert found - {TEMPLATE_KEY} - NOT_A_TEMPLATE_REFERENCE == {"intro_template"}
