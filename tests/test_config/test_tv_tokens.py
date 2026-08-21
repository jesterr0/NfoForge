from src.config.tv_tokens import resolve_season_subfolder_token


def test_blank_subfolder_token_falls_back_to_the_season_folder_token() -> None:
    # In a single-season pack the opened folder IS the season folder, so one
    # token covers both. The two diverge only for a nested pack.
    folder_token = "{title_clean} S{season_number|zfill(2)}"  # noqa: S105 - NFO template token string used as test fixture data, not a credential

    assert resolve_season_subfolder_token("", folder_token) == folder_token


def test_a_whitespace_only_subfolder_token_falls_back_too() -> None:
    # A field holding spaces is a field the user left alone.
    assert resolve_season_subfolder_token("   ", "{title_clean}") == "{title_clean}"


def test_a_configured_subfolder_token_wins() -> None:
    assert (
        resolve_season_subfolder_token("Season {season_number}", "{title_clean}")
        == "Season {season_number}"
    )


def test_a_configured_subfolder_token_is_stripped() -> None:
    # Space around the token is not part of it. Both call sites already
    # tested emptiness against the stripped value and then used it.
    assert (
        resolve_season_subfolder_token("  Season {season_number}  ", "{title_clean}")
        == "Season {season_number}"
    )
