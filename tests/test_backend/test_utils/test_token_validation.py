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
    # `meta.find_undeclared_variables` never reports a top-level `{% set %}`
    # target in the first place, so this pins the baseline behaviour and
    # passes regardless of what `_bound_names` does.
    template = "{% set scan_type = 'Progressive' %}{{ scan_type }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_set_block_binding_is_not_flagged() -> None:
    # As above: a top-level `{% set %}` target (block form included) is never
    # reported by `find_undeclared_variables`, so this passes regardless of
    # `_bound_names`.
    template = "{% set body %}text{% endset %}{{ body }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_for_loop_target_is_not_flagged() -> None:
    template = "{% for item in [1, 2] %}{{ item }}{% endfor %}"
    assert find_unknown_tokens(template, _env()) == set()


def test_if_nested_set_is_not_flagged() -> None:
    # The leading top-level `{% set s = '' %}` means `s` is already bound at
    # an outer scope, so `find_undeclared_variables` never reports it in the
    # first place -- this also passes regardless of `_bound_names`.
    template = "{% set s = '' %}{% if 1 %}{% set s = 'v' %}{% endif %}{{ s }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_conditional_simple_set_is_not_flagged() -> None:
    # Guards the `isinstance(target, nodes.Name)` branch: a conditional
    # binding IS reported by find_undeclared_variables, so only _bound_names
    # keeps it from being flagged. Non-constant condition, no outer binding.
    template = "{% if video_height %}{% set s = 'v' %}{% endif %}{{ s }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_conditional_tuple_set_is_not_flagged() -> None:
    # Guards the `target.find_all(nodes.Name)` branch: tuple targets are
    # reached only by the walk, not the isinstance check.
    template = "{% if video_height %}{% set a, b = 1, 2 %}{% endif %}{{ a }}{{ b }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_set_block_nested_binding_is_not_flagged() -> None:
    # Guards the recursive descent: the inner binding is only reachable by
    # recursing into the AssignBlock child.
    template = "{% set body %}{% set inner = 1 %}{% endset %}{{ inner }}"
    assert find_unknown_tokens(template, _env()) == set()


def test_loop_scoped_set_used_outside_the_loop_is_flagged() -> None:
    # The binding does not outlive the loop, so this really does render
    # blank -- the exact silent-blank failure this module exists to catch.
    template = "{% for i in ['A'] %}{% set y = i %}{% endfor %}{{ y }}"
    assert find_unknown_tokens(template, _env()) == {"y"}


def test_macro_scoped_set_used_outside_the_macro_is_flagged() -> None:
    template = "{% macro m() %}{% set q = 1 %}{% endmacro %}{{ q }}"
    assert find_unknown_tokens(template, _env()) == {"q"}


def test_call_scoped_set_used_outside_the_call_is_flagged() -> None:
    # `{% call %}` is the third scope-opening construct in
    # `_SCOPE_OPENING_NODES`; without this it is the one named case with no
    # regression cover, so a change to the walk could silently reintroduce
    # the false negative for it alone.
    template = (
        "{% macro m() %}{{ caller() }}{% endmacro %}"
        "{% call m() %}{% set c = 1 %}{% endcall %}{{ c }}"
    )
    assert find_unknown_tokens(template, _env()) == {"c"}


def test_with_scoped_set_used_outside_is_flagged() -> None:
    template = "{% with %}{% set q = 1 %}{% endwith %}{{ q }}"
    assert find_unknown_tokens(template, _env()) == {"q"}


def test_filter_block_scoped_set_used_outside_is_flagged() -> None:
    template = "{% filter upper %}{% set q = 1 %}{% endfilter %}{{ q }}"
    assert find_unknown_tokens(template, _env()) == {"q"}


def test_block_scoped_set_used_outside_is_flagged() -> None:
    template = "{% block b %}{% set q = 1 %}{% endblock %}{{ q }}"
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
