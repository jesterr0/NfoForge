import pytest

from src.backend.utils.rename_normalizations import is_imax


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("IMAX", True),
        ("Movie.IMAX.2024", True),
        ("Movie_IMAX_2024", True),
        ("Climax", False),
        ("IMAX2", False),
    ],
)
def test_is_imax_requires_a_release_token_boundary(value: str, expected: bool) -> None:
    assert is_imax(value) is expected
