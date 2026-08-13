"""A release must not carry the maintainer's own data out of their checkout.

The bundled runtime is seeded from `runtime/` as it exists on the build
machine, not from a clean template, so it arrives holding whatever that
machine accumulated: saved credentials and config under `config/`, a log
history, cookies. Stripping it by file extension is what let a plugin's JSON
credentials and a rotated `.log.1` reach a build, since the patterns were
written around NfoForge's own `.toml` and `.log` names.

CI is unaffected either way -- a fresh checkout has none of this, as
`.gitignore` keeps it all untracked -- which is exactly why a local build is
the one that leaks and the one nobody checks.
"""

from pathlib import Path

from build import strip_local_state

# Files a maintainer's checkout accumulates that must never reach a release.
# A plugin's saved credential and a rotated log are the two that really
# shipped: one survived because the config sweep only matched `*.toml`, the
# other because the log sweep only matched `*.log`.
LOCAL_STATE = (
    "config/plugins/example_plugin_auth.json",
    "config/plugins/example_plugin.toml",
    "config/user/user_config.toml",
    "config/program/program_conf.toml",
    "logs/nfoforge.log",
    "logs/nfoforge.log.1",
    "logs/crash.log",
    "cookies/session.pkl",
    "cookies/session.dat",
    "templates/my_template.txt",
    "templates/my_template.jinja",
    "user_packages/mypkg/module.py",
    "plugins/some_plugin/plugin.py",
)

# What a release genuinely needs, sitting in the same tree. `docs/` is
# gitignored like the local state above, but the build generates it, so
# "drop everything untracked" would silently ship a release with no docs.
SHIPPED = (
    "config/defaults/default_config.toml",
    "config/defaults/default_program_conf.toml",
    "config/audio_conventions/default.json",
    "docs/index.html",
    "fonts/Roboto/Roboto-Regular.ttf",
    "images/NfoForge_logo.png",
)


def build_runtime(root: Path) -> Path:
    """A bundled runtime holding both local state and what a release needs."""
    for relative in LOCAL_STATE + SHIPPED:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return root


def test_local_state_does_not_survive_into_a_release(tmp_path) -> None:
    runtime = build_runtime(tmp_path / "runtime")

    strip_local_state(runtime)

    survivors = sorted(
        relative for relative in LOCAL_STATE if (runtime / relative).exists()
    )
    assert not survivors, (
        f"these carry the build machine's own data into a release: {survivors}"
    )


def test_packaged_defaults_and_generated_docs_survive(tmp_path) -> None:
    # the same sweep that removes local state must leave a working release
    runtime = build_runtime(tmp_path / "runtime")

    strip_local_state(runtime)

    missing = sorted(
        relative for relative in SHIPPED if not (runtime / relative).exists()
    )
    assert not missing, f"a release needs these and the sweep removed them: {missing}"


def test_a_runtime_missing_the_optional_directories_is_not_an_error(tmp_path) -> None:
    # not every checkout has run the app, so these may never have been created
    runtime = tmp_path / "runtime"
    (runtime / "config" / "defaults").mkdir(parents=True)

    strip_local_state(runtime)

    assert (runtime / "config" / "defaults").is_dir()
