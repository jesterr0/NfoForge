"""Detect template variables that will not resolve when the template renders.

Jinja renders an unknown name as an empty string for plain substitution, so a
template written against a renamed or removed token keeps rendering with the
field silently blank. This module finds those names so the editor can mark
them.

Deliberately free of Qt, config, and media imports so it unit tests without a
QApplication or a loaded profile.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from jinja2 import Environment, meta, nodes
from jinja2.exceptions import TemplateSyntaxError

from src.backend.tokens import Tokens

# Supplied per run rather than declared in `Tokens`: user tokens are always
# `usr_` prefixed (see `TokenReplacer._parse_user_input`) and sandbox prompt
# tokens are always `prompt_` prefixed, so a name carrying either prefix is
# never reported as unknown.
_RUNTIME_TOKEN_PREFIXES = ("usr_", "prompt_")


# `{% for %}`, `{% macro %}`, `{% call %}`, `{% with %}`, `{% filter %}`, and
# `{% block %}` each open a scope: a name bound inside one does not exist
# after the block ends. Bindings inside them are therefore NOT collected as
# known -- such a name really does render blank afterwards, which is exactly
# what this module exists to report.
_SCOPE_OPENING_NODES = (
    nodes.For,
    nodes.Macro,
    nodes.CallBlock,
    nodes.With,
    nodes.FilterBlock,
    nodes.Block,
)


def _bound_names(node: nodes.Node) -> set[str]:
    """Names the template binds at a scope that outlives the binding.

    `meta.find_undeclared_variables` is already scope-aware and omits most
    `{% set %}` bindings by itself. It can still report one bound inside an
    `{% if %}` -- Jinja lets that binding leak out of the block, and the
    analyzer only omits it when a same-named binding already exists at an
    outer scope -- so those are collected here to keep a working template
    from being flagged.

    Recurses rather than using `find_all` so the walk can stop at a scope
    boundary. `Node.find_all` yields descendants but not the node it is called
    on, and a simple `{% set x = ... %}` target *is* a `nodes.Name`, so each
    target is type-checked directly as well as walked (the walk covers tuple
    targets such as `{% set a, b = 1, 2 %}`).
    """
    bound: set[str] = set()
    for child in node.iter_child_nodes():
        if isinstance(child, _SCOPE_OPENING_NODES):
            continue
        if isinstance(child, nodes.Assign | nodes.AssignBlock):
            target = child.target
            if isinstance(target, nodes.Name):
                bound.add(target.name)
            bound.update(name.name for name in target.find_all(nodes.Name))
        bound |= _bound_names(child)
    return bound


def find_unknown_tokens(
    template_text: str,
    environment: Environment,
    user_tokens: Iterable[str] | None = None,
) -> set[str]:
    """Names referenced by `template_text` that will not resolve at render time.

    A name is known if it is a built-in token, a global registered on
    `environment` (plugin jinja2 functions and the `nf_*` payloads), a name the
    template binds itself, or a supplied/prefixed user token.

    Returns an empty set when the template does not parse. An unparseable
    template is already reported by the editor's syntax-error dialog, and this
    must not compete with it.
    """
    try:
        ast = environment.parse(template_text)
    except TemplateSyntaxError:
        return set()

    known = (
        Tokens.get_tokens()
        | set(environment.globals)
        | _bound_names(ast)
        | set(user_tokens or ())
    )
    return {
        name
        for name in meta.find_undeclared_variables(ast)
        if name not in known and not name.startswith(_RUNTIME_TOKEN_PREFIXES)
    }


def build_unknown_token_pattern(names: Iterable[str]) -> re.Pattern[str] | None:
    """A regex matching each name in `names`, or None when there is nothing to match.

    Matches the bare name rather than the surrounding delimiters, so a name is
    marked wherever it appears, including inside `{% ... %}` blocks as well as
    `{{ ... }}`. The word boundaries stop a short name matching inside a longer
    one. A name appearing in the template's literal prose would also be marked;
    that is rare, and marking it is harmless.
    """
    unique = sorted({name for name in names if name})
    if not unique:
        return None
    alternation = "|".join(re.escape(name) for name in unique)
    return re.compile(r"\b(?:" + alternation + r")\b")
