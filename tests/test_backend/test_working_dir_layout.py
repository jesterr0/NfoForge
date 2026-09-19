"""Coverage for the working directory layout that keeps jobs safe from cleanup."""

import os
from pathlib import Path
import re

import pytest

from src.backend.utils import working_dir
from src.backend.utils.working_dir import (
    JOBS_DIR_NAME,
    PROCESSING_DIR_NAME,
    cleanable_items,
    cleanable_size,
    jobs_dir,
    normalise_path,
    processing_dir,
)
from src.config.paths import DATA_DIR_ENV_VAR
from tests.repo_paths import REPO_ROOT


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """A data directory cleanup cannot reach, which is the ordinary case.

    The one test that needs an overlapping data directory builds its own.
    """
    return tmp_path / "appdata"


def test_normalise_path_collapses_redundant_components(tmp_path: Path) -> None:
    """Configured paths are compared for identity, so spelling must not matter.

    A working directory saved with a trailing separator, or reached via a
    parent hop, is the same directory as the plainly spelled one. String
    equality says otherwise, which is why the comparison goes through here.
    """
    plain = tmp_path / "work"
    plain.mkdir()

    assert normalise_path(Path(f"{plain}{os.sep}")) == normalise_path(plain)
    assert normalise_path(plain / ".." / "work") == normalise_path(plain)


@pytest.mark.skipif(
    os.name != "nt", reason="only Windows treats paths as case-insensitive"
)
def test_normalise_path_ignores_case_on_windows(tmp_path: Path) -> None:
    """A directory saved in another case is the same directory.

    This is the case the rewrite rules turn on: a profile holding
    `c:\\users\\...` must be recognised as the default working directory that
    the application spells `C:\\Users\\...`, or it is treated as a custom path
    and left pointing at the old layout.

    The directory deliberately does not exist, which is the harder case and a
    common one here: an unplugged drive, or a profile written on another
    machine. For a directory that is there, `resolve()` recovers the real
    casing from disk and the question never arises.

    `Path` supplies this rather than `normalise_path` doing any folding of its
    own, so this is a characterisation test: it fails if someone rewrites a
    comparison to work on `str`, which is not case-insensitive.
    """
    missing = tmp_path / "work"

    assert normalise_path(Path(str(missing).upper())) == normalise_path(missing)


def test_normalise_path_keeps_different_directories_apart(tmp_path: Path) -> None:
    """Normalising must not be so eager that it merges unrelated paths."""
    first = tmp_path / "work"
    second = tmp_path / "work2"

    assert normalise_path(first) != normalise_path(second)


def test_jobs_and_processing_are_siblings(tmp_path: Path) -> None:
    assert jobs_dir(tmp_path) == tmp_path / JOBS_DIR_NAME
    assert processing_dir(tmp_path) == tmp_path / PROCESSING_DIR_NAME


def test_directories_are_only_created_when_asked(tmp_path: Path) -> None:
    jobs_dir(tmp_path)
    assert not (tmp_path / JOBS_DIR_NAME).exists()

    jobs_dir(tmp_path, ensure_exists=True)
    assert (tmp_path / JOBS_DIR_NAME).is_dir()


def test_cleanup_removes_the_contents_of_processing(
    tmp_path: Path, data_root: Path
) -> None:
    """Clean up reclaims generated data, and nothing else.

    The processing folder itself survives: what comes back is its contents, so
    the directory is still there for the next run.
    """
    saved_job = jobs_dir(tmp_path, ensure_exists=True) / "job.json"
    saved_job.write_text("{}", encoding="utf-8")
    run_folder = processing_dir(tmp_path, ensure_exists=True) / "Some.Release"
    run_folder.mkdir(parents=True)

    removable = cleanable_items(tmp_path, data_root)

    assert run_folder in removable
    assert processing_dir(tmp_path) not in removable
    assert jobs_dir(tmp_path) not in removable


def test_cleanup_leaves_everything_outside_processing_alone(
    tmp_path: Path, data_root: Path
) -> None:
    """Siblings of the processing folder are no longer swept.

    This reverses earlier behaviour deliberately. Cleanup used to be expressed
    as "everything except jobs", which caught the run folders older versions
    wrote at the working directory root without needing a migration step. It
    also meant that pointing the working directory at a folder holding anything
    else handed that content to the Clean Up button, and once the layout puts
    configuration and tooling under the same root it would hand those over too.

    The run folders that exclusion used to catch are relocated into
    `processing/` by the one-time layout migration instead, and any that are
    left behind are reported rather than deleted.
    """
    legacy_run = tmp_path / "Old.Release_01.01.2026_12.00.00"
    legacy_run.mkdir(parents=True)
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("x", encoding="utf-8")
    jobs_dir(tmp_path, ensure_exists=True)

    removable = cleanable_items(tmp_path, data_root)

    assert removable == []


def test_cleanup_refuses_when_it_would_reach_the_data_directory(
    tmp_path: Path,
) -> None:
    """Clean up must never be able to delete the application's own data.

    Narrowing to `processing/` already means no ordinary working directory can
    reach configuration, templates or tooling. This is the invariant behind
    that: whatever a configured working directory happens to be, if emptying
    its processing folder would take the data directory with it, nothing is
    returned at all. Stated as a rule rather than left to the arithmetic of
    whichever directory names the layout uses this release.
    """
    # the data directory is itself what cleanup would empty
    data_root = tmp_path / PROCESSING_DIR_NAME
    data_root.mkdir()
    (data_root / "program.toml").write_bytes(b"x" * 10)

    assert cleanable_items(tmp_path, data_root) == []
    assert cleanable_size(tmp_path, data_root) == 0

    # the data directory sits inside what cleanup would empty
    nested = data_root / "nfoforge"
    nested.mkdir()

    assert cleanable_items(tmp_path, nested) == []
    assert cleanable_size(tmp_path, nested) == 0


def test_cleanable_items_is_empty_for_a_missing_directory(
    tmp_path: Path, data_root: Path
) -> None:
    assert cleanable_items(tmp_path / "never-created", data_root) == []


def test_cleanable_items_survives_the_directory_vanishing_before_iterdir(
    tmp_path: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The directory can be removed between the is_dir() check and iterdir().

    Same race cleanable_size guards one level down; unguarded here it would
    surface straight out of cleanable_items and out of cleanable_size too,
    since cleanable_size iterates this function's result.
    """
    working_dir = tmp_path / "nfoforge"
    processing = processing_dir(working_dir, ensure_exists=True)

    real_iterdir = Path.iterdir

    def vanishing(self: Path) -> object:
        if self == processing:
            raise OSError("directory vanished mid-scan")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", vanishing)

    assert cleanable_items(working_dir, data_root) == []


def test_cleanable_size_adds_up_what_clean_up_would_remove(
    tmp_path: Path, data_root: Path
) -> None:
    processing = tmp_path / "processing" / "run"
    processing.mkdir(parents=True)
    (processing / "shot.png").write_bytes(b"x" * 100)
    jobs = tmp_path / "jobs" / "abc"
    jobs.mkdir(parents=True)
    (jobs / "job.json").write_bytes(b"y" * 500)
    (tmp_path / "stray.log").write_bytes(b"z" * 10)

    # jobs/ is never reclaimable and the stray file is outside processing/,
    # so only the screenshot counts
    assert cleanable_size(tmp_path, data_root) == 100


def test_cleanable_size_survives_a_file_disappearing(
    tmp_path: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "processing" / "run"
    run.mkdir(parents=True)
    (run / "gone.png").write_bytes(b"x" * 100)

    real_stat = Path.stat

    def vanishing(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "gone.png":
            raise OSError("file vanished mid-scan")
        return real_stat(self, *args, **kwargs)  # pyright: ignore[reportCallIssue]

    monkeypatch.setattr(Path, "stat", vanishing)

    assert cleanable_size(tmp_path, data_root) == 0


def test_cleanable_size_survives_a_directory_disappearing_mid_walk(
    tmp_path: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whole subdirectory can vanish while rglob() is still descending into it.

    That surfaces as an exception from the `for` statement driving the walk,
    not from a stat() call inside the loop body, so it needs its own guard
    one level up from the per-file one.
    """
    keep = tmp_path / "processing" / "keep"
    keep.mkdir(parents=True)
    (keep / "shot.png").write_bytes(b"x" * 50)

    gone = tmp_path / "processing" / "gone"
    gone.mkdir()
    (gone / "trace.log").write_bytes(b"x" * 30)

    real_rglob = Path.rglob

    def vanishing(self: Path, pattern: str) -> object:
        if self.name != "gone":
            return real_rglob(self, pattern)

        def disappearing_walk() -> object:
            # Yield the folder once, then fail as the walk attempts to descend.
            # Python 3.13's pathlib now suppresses scandir() failures internally,
            # so the iterator boundary is the stable point to model this race.
            yield self
            raise FileNotFoundError("directory vanished mid-scan")

        return disappearing_walk()

    monkeypatch.setattr(Path, "rglob", vanishing)

    # "gone" disappears out from under the walk; only "keep" can still be measured
    assert cleanable_size(tmp_path, data_root) == 50


def test_cleanable_size_is_zero_for_a_missing_directory(
    tmp_path: Path, data_root: Path
) -> None:
    assert cleanable_size(tmp_path / "never-created", data_root) == 0


def test_cleanable_size_is_zero_for_an_empty_directory(
    tmp_path: Path, data_root: Path
) -> None:
    assert cleanable_size(tmp_path, data_root) == 0


def test_nothing_in_the_application_reads_the_old_mutable_tree() -> None:
    """Four separate places were still reading it, each silently wrong.

    Templates, logs, plugins and the template token scan all derived a path from
    the installation, so each would have read an empty directory inside the
    release while the user's migrated files sat in the data directory. Nothing
    fails when that happens -- the directory is simply empty -- which is why this
    is asserted rather than left to review.

    The name itself survives for plugins, so absence cannot be the guarantee.
    What can be is that no module here uses it.
    """
    offenders = []
    sources = [REPO_ROOT / "start_ui.py", *(REPO_ROOT / "src").rglob("*.py")]
    for source in sources:
        if source.name == "working_dir.py":
            continue  # where the compatibility shim necessarily names it
        if re.search(r"\bRUNTIME_DIR\b", source.read_text(encoding="utf-8")):
            offenders.append(str(source.relative_to(REPO_ROOT)))

    assert not offenders, (
        f"{offenders} read RUNTIME_DIR. User state lives in the data directory; a "
        "path derived from the installation points inside a folder a release "
        "replaces, and reads as empty rather than failing."
    )


def test_the_old_name_still_resolves_for_plugins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plugins are user-installed and sometimes compiled, so they cannot be patched.

    Removing a name they have always imported would stop them loading outright.
    It resolves to the directory that now holds what it used to, so a plugin
    asking for `RUNTIME_DIR / "templates"` still gets the templates.
    """
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path / "data"))

    with pytest.warns(DeprecationWarning):
        resolved = working_dir.RUNTIME_DIR

    assert resolved == tmp_path / "data"


def test_an_unknown_name_is_still_an_attribute_error() -> None:
    """The shim answers for one name, not for anything asked of the module."""
    with pytest.raises(AttributeError):
        getattr(working_dir, "NO_SUCH_THING")  # noqa: B009 - the lookup is the subject
