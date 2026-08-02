from pathlib import Path

from src.backend.utils.template_token_migration import (
    REMOVED_TEMPLATE_TOKENS,
    TEMPLATE_TOKEN_RENAMES,
    rewrite_template_text,
    scan_template_dir,
    scan_template_text,
)


def test_scan_detects_renamed_jinja_tokens() -> None:
    renamed, removed = scan_template_text("Title: {{ movie_title }}")
    assert renamed == {"movie_title": "title"}
    assert removed == set()


def test_scan_detects_mi_prefixed_tokens() -> None:
    renamed, _ = scan_template_text("Audio: {{ mi_audio_codec }}")
    assert renamed == {"mi_audio_codec": "audio_codec"}


def test_scan_detects_removed_token_with_no_target() -> None:
    renamed, removed = scan_template_text("{{ movie_full_title }}")
    assert renamed == {}
    assert removed == {"movie_full_title"}


def test_scan_ignores_prose_that_merely_contains_a_token_name() -> None:
    # The word appears outside Jinja delimiters and must not be rewritten.
    renamed, removed = scan_template_text("This template has no movie_title in it.")
    assert renamed == {}
    assert removed == set()


def test_scan_handles_tokens_inside_statement_blocks() -> None:
    renamed, _ = scan_template_text("{% if movie_title %}x{% endif %}")
    assert renamed == {"movie_title": "title"}


def test_scan_handles_tokens_with_filters_applied() -> None:
    renamed, _ = scan_template_text("{{ movie_clean_title | upper }}")
    assert renamed == {"movie_clean_title": "title_clean"}


def test_rewrite_replaces_only_inside_delimiters() -> None:
    text = "movie_title {{ movie_title }} {% if mi_audio_codec %}{% endif %}"
    assert rewrite_template_text(text) == (
        "movie_title {{ title }} {% if audio_codec %}{% endif %}"
    )


def test_rewrite_preserves_whitespace_and_filters() -> None:
    assert rewrite_template_text("{{movie_exact_title|title}}") == (
        "{{title_exact|title}}"
    )


def test_rewrite_leaves_removed_tokens_untouched() -> None:
    # There is no rename target, so the text is preserved and the user is told.
    assert rewrite_template_text("{{ movie_full_title }}") == "{{ movie_full_title }}"


def test_rewrite_is_idempotent() -> None:
    once = rewrite_template_text("{{ movie_title }}")
    assert rewrite_template_text(once) == once


def test_rewrite_does_not_touch_a_similarly_named_token() -> None:
    # `title` is already correct; `movie_titles` is not a known token and must
    # not be partially rewritten into `titles`.
    assert rewrite_template_text("{{ title }} {{ movie_titles }}") == (
        "{{ title }} {{ movie_titles }}"
    )


def test_scan_template_dir_reports_only_affected_files(tmp_path: Path) -> None:
    (tmp_path / "stale.txt").write_text("{{ movie_title }}", encoding="utf-8")
    (tmp_path / "clean.txt").write_text("{{ title }}", encoding="utf-8")
    (tmp_path / "ignored.md").write_text("{{ movie_title }}", encoding="utf-8")

    reports = scan_template_dir(tmp_path)

    assert [report.path.name for report in reports] == ["stale.txt"]
    assert reports[0].renamed == {"movie_title": "title"}


def test_scan_template_dir_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert scan_template_dir(tmp_path / "does-not-exist") == []


def test_rename_map_and_removed_set_are_disjoint() -> None:
    assert not set(TEMPLATE_TOKEN_RENAMES) & REMOVED_TEMPLATE_TOKENS


def test_scan_and_rewrite_ignore_comments_entirely() -> None:
    # `{# ... #}` never renders; a token name inside one must be neither
    # reported nor rewritten.
    text = "{# TODO: remove movie_title usage #}"
    assert scan_template_text(text) == ({}, set())
    assert rewrite_template_text(text) == text


def test_scan_and_rewrite_ignore_raw_blocks_entirely() -> None:
    # `{% raw %}...{% endraw %}` suppresses Jinja interpretation, so its
    # contents must be neither reported nor rewritten.
    text = "{% raw %}{{ movie_title }}{% endraw %}"
    assert scan_template_text(text) == ({}, set())
    assert rewrite_template_text(text) == text


def test_unclosed_raw_block_is_treated_as_running_to_the_end() -> None:
    text = "before {% raw %}{{ movie_title }}"
    assert scan_template_text(text) == ({}, set())
    assert rewrite_template_text(text) == text


def test_stray_endraw_with_no_matching_open_does_not_suppress_scanning() -> None:
    # No preceding `{% raw %}` means this is not a raw region at all; the
    # scanner must not crash and must keep scanning normally.
    text = "{{ movie_title }} {% endraw %}"
    renamed, _ = scan_template_text(text)
    assert renamed == {"movie_title": "title"}
    assert rewrite_template_text(text) == "{{ title }} {% endraw %}"


def test_rewrite_leaves_quoted_string_literal_arguments_untouched() -> None:
    # The string literal passed to `default(...)` is a value, not a token
    # reference; only the bare identifier form of the same word is renamed.
    text = "{{ movie_title | default('movie_title') }}"
    assert rewrite_template_text(text) == "{{ title | default('movie_title') }}"


def test_scan_does_not_report_a_token_name_that_only_appears_quoted() -> None:
    text = "{{ foo | default('mi_casa') }}"
    assert scan_template_text(text) == ({}, set())
    assert rewrite_template_text(text) == text


def test_rewrite_still_finds_a_stale_token_outside_a_raw_block_in_the_same_file() -> (
    None
):
    text = "{{ movie_title }} {% raw %}{{ movie_title }}{% endraw %}"
    renamed, _ = scan_template_text(text)
    assert renamed == {"movie_title": "title"}
    assert rewrite_template_text(text) == (
        "{{ title }} {% raw %}{{ movie_title }}{% endraw %}"
    )


def test_scan_template_dir_ignores_a_stale_token_referenced_only_in_a_comment(
    tmp_path: Path,
) -> None:
    (tmp_path / "commented.txt").write_text(
        "{# movie_title is no longer used #}", encoding="utf-8"
    )
    assert scan_template_dir(tmp_path) == []


def test_scan_template_dir_ignores_a_stale_token_referenced_only_inside_raw(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw-only.txt").write_text(
        "{% raw %}{{ movie_title }}{% endraw %}", encoding="utf-8"
    )
    assert scan_template_dir(tmp_path) == []
