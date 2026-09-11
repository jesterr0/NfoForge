"""A release must not carry the maintainer's own data out of their checkout.

This used to be enforced by copying the mutable tree into the bundle and then
deleting the user's own files back out of it, which meant a release shipped
whatever that pass happened to miss -- a plugin's JSON credentials and a
rotated `.log.1` both reached builds that way, because the sweep was written
around NfoForge's own `.toml` and `.log` names.

The guarantee is now structural: the build bundles the asset tree, which holds
only files put there deliberately, and does not bundle the mutable tree at all.
There is nothing to strip, so there is nothing for a stripping pass to miss.

CI was never the build that leaked -- a fresh checkout has no local state, since
`.gitignore` keeps it all untracked -- which is why the local build was the one
that leaked and the one nobody checked. That is also why this is asserted
against the build script rather than against a built tree: the leak only ever
existed on a machine that had accumulated something to leak.
"""

from tests.repo_paths import REPO_ROOT


def test_the_build_does_not_reference_the_mutable_tree() -> None:
    """Re-adding the mutable tree to the bundle must not be a quiet change.

    Naming it anywhere in the build is the tell, whether as bundled data or as
    a path to copy in afterwards. The asset tree is the only thing a release
    ships, and nothing the user owns lives there.
    """
    build_script = (REPO_ROOT / "build.py").read_text(encoding="utf-8")

    assert "runtime" not in build_script, (
        "build.py names the mutable tree again; a release must bundle assets/ "
        "only, or the user state that tree accumulates ships with it"
    )
