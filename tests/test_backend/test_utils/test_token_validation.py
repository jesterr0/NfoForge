from jinja2 import Environment

from src.backend.utils.token_validation import (
    build_unknown_token_pattern,
    find_unknown_tokens,
)


def _env() -> Environment:
    return Environment()


def test_known_token_is_not_flagged() -> None:
    assert find_unknown_tokens("{{ video_bit_rate }}", _env()) == set()


def test_stale_mi_token_is_flagged() -> None:
    assert find_unknown_tokens("{{ mi_video_bit_rate }}", _env()) == {
        "mi_video_bit_rate"
    }


def test_only_the_unknown_name_on_a_mixed_line_is_flagged() -> None:
    template = (
        "Video: {{ mi_video_codec }} / {{ video_frame_rate }} / {{ format_profile }}"
    )
    assert find_unknown_tokens(template, _env()) == {"mi_video_codec"}


def test_environment_global_is_not_flagged() -> None:
    env = _env()
    env.globals["plugin_helper"] = object()
    assert find_unknown_tokens("{{ plugin_helper }}", env) == set()


def test_simple_set_binding_is_not_flagged() -> None:
    # Regression guard: `Node.find_all` does not yield the node it is called
    # on, and a simple `{% set %}` target *is* a `nodes.Name`. A walk-only
    # implementation misses this and reports `scan_type` as unknown.
    template = "{% set scan_type = 'Progressive' %}{{ scan_type }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_set_block_binding_is_not_flagged() -> None:
    template = "{% set body %}text{% endset %}{{ body }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_for_loop_target_is_not_flagged() -> None:
    template = "{% for item in [1, 2] %}{{ item }}{% endfor %}"
    assert find_unknown_tokens(template, _env()) == set()


def test_if_nested_set_is_not_flagged() -> None:
    # Jinja lets a binding made inside `{% if %}` leak out of the block, so
    # the later reference resolves. `find_undeclared_variables` reports it
    # anyway, and flagging it would mark a working template. This is the
    # shape used by a real user template.
    template = "{% set s = '' %}{% if 1 %}{% set s = 'v' %}{% endif %}{{ s }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_loop_scoped_set_used_outside_the_loop_is_flagged() -> None:
    # The binding does not outlive the loop, so this really does render
    # blank -- the exact silent-blank failure this module exists to catch.
    template = "{% for i in ['A'] %}{% set y = i %}{% endfor %}{{ y }}"
    assert find_unknown_tokens(template, _env()) == {"y"}


def test_macro_scoped_set_used_outside_the_macro_is_flagged() -> None:
    template = "{% macro m() %}{% set q = 1 %}{% endmacro %}{{ q }}"
    assert find_unknown_tokens(template, _env()) == {"q"}


def test_user_and_prompt_prefixed_names_are_not_flagged() -> None:
    assert find_unknown_tokens("{{ usr_custom }}{{ prompt_note }}", _env()) == set()


def test_explicitly_supplied_user_token_is_not_flagged() -> None:
    result = find_unknown_tokens(
        "{{ my_plugin_value }}", _env(), user_tokens=["my_plugin_value"]
    )
    assert result == set()


def test_unparseable_template_returns_empty_set() -> None:
    # The editor's existing TemplateSyntaxError dialog owns this case.
    assert find_unknown_tokens("{% if %}", _env()) == set()


def test_pattern_is_none_when_nothing_is_unknown() -> None:
    assert build_unknown_token_pattern([]) is None


def test_pattern_matches_each_unknown_name() -> None:
    pattern = build_unknown_token_pattern(["mi_video_codec", "mi_video_bit_rate"])
    assert pattern is not None
    text = "{{ mi_video_codec }} / {{ mi_video_bit_rate }} / {{ video_frame_rate }}"
    assert pattern.findall(text) == ["mi_video_codec", "mi_video_bit_rate"]


def test_pattern_does_not_match_a_longer_name_by_prefix() -> None:
    pattern = build_unknown_token_pattern(["mi_video_bit_rate"])
    assert pattern is not None
    assert pattern.search("{{ mi_video_bit_rate_num_only }}") is None
