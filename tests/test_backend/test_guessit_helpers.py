from src.backend.utils.guessit_helpers import get_guessit_title


def test_get_guessit_title_keeps_scalar_title() -> None:
    assert get_guessit_title({"title": "Show Title"}) == "Show Title"


def test_get_guessit_title_uses_first_non_empty_title() -> None:
    assert (
        get_guessit_title({"title": ["", "Primary Title", "Alternative"]})
        == "Primary Title"
    )


def test_get_guessit_title_uses_alternative_only_without_primary() -> None:
    assert (
        get_guessit_title({"alternative_title": ["Alternate", "Other"]}) == "Alternate"
    )


def test_get_guessit_title_uses_fallback_without_title_values() -> None:
    assert get_guessit_title({"title": []}, fallback="Filename Title") == (
        "Filename Title"
    )


def test_get_guessit_title_never_stringifies_a_list() -> None:
    assert get_guessit_title({"title": ["One", "Two"]}) != "['One', 'Two']"
