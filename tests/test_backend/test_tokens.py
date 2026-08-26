from src.backend.tokens import FileToken, NfoToken, Tokens


def test_video_dimensions_are_registered_as_file_and_nfo_tokens() -> None:
    file_tokens = Tokens.get_token_objects(FileToken)
    nfo_tokens = Tokens.get_token_objects(NfoToken)

    assert any(token is Tokens.FILE_VIDEO_WIDTH for token in file_tokens)
    assert any(token is Tokens.FILE_VIDEO_HEIGHT for token in file_tokens)
    assert any(token is Tokens.VIDEO_WIDTH for token in nfo_tokens)
    assert any(token is Tokens.VIDEO_HEIGHT for token in nfo_tokens)
    assert not any(token is Tokens.FILE_VIDEO_WIDTH for token in nfo_tokens)
    assert not any(token is Tokens.VIDEO_WIDTH for token in file_tokens)


def test_file_token_dataclass_includes_video_dimensions() -> None:
    token_data = Tokens.generate_token_dataclass(FileToken)

    assert "video_width" in token_data.get_dict()
    assert "video_height" in token_data.get_dict()


def test_plot_and_url_tokens_are_registered_as_nfo_only() -> None:
    # Plot text and URLs contain characters (newlines, "/", ":") that are
    # invalid in filenames, so these must stay NfoToken-only.
    file_tokens = Tokens.get_token_objects(FileToken)
    nfo_tokens = Tokens.get_token_objects(NfoToken)

    assert any(token is Tokens.PLOT for token in nfo_tokens)
    assert any(token is Tokens.IMDB_URL for token in nfo_tokens)
    assert any(token is Tokens.TMDB_URL for token in nfo_tokens)
    assert not any(token is Tokens.PLOT for token in file_tokens)
    assert not any(token is Tokens.IMDB_URL for token in file_tokens)
    assert not any(token is Tokens.TMDB_URL for token in file_tokens)
