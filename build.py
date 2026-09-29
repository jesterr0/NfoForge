import os
from pathlib import Path
import platform
import re
import shutil
from subprocess import run
import sys

from stdlib_list import stdlib_list

from nfoforge.backend.utils.get_os_executable_ext import get_executable_string_by_os
from nfoforge.launcher import CLI_EXECUTABLE

# Modules that exist for external plugins to import rather than for NfoForge's
# own use. Nothing here imports them, so PyInstaller's walk from the entry
# script never reaches them and they are left out of the frozen build -- which
# a plugin discovers only as `No module named ...` once a user runs a release,
# since running from source resolves them off the filesystem regardless.
#
# The build cannot infer this set for itself: plugins are copied in after the
# freeze, are not present on the build machine, and may be compiled, so their
# imports are beyond static analysis. Naming them here stands in for the import
# edge PyInstaller has no way to see.
PLUGIN_API_MODULES: list[str] = [
    # `WizardPluginBase`, which a wizard plugin subclasses
    "nfoforge.plugins.plugin_wizard_base",
]


def get_std_lib() -> list:
    """Return all standard library modules removing 'this' and 'antigravity'"""
    standard_lib = stdlib_list()
    standard_lib.remove("this")
    standard_lib.remove("antigravity")
    return standard_lib


def spec_hiddenimports(include_std_lib: bool) -> list[str]:
    """Modules to name in the spec that PyInstaller's own walk would not find.

    The plugin API is always included. The standard library is per-build, and
    the plugin API must not be gated on that choice: a build without the
    standard library is still a build external plugins load into.
    """
    hiddenimports: list[str] = list(PLUGIN_API_MODULES)
    if include_std_lib:
        hiddenimports += get_std_lib()
    return hiddenimports


def modify_spec_file(spec_file_path: Path, hiddenimports: list):
    # open the spec file and read the contents
    with open(spec_file_path) as spec_file:
        spec_content = spec_file.read()

    # find the hiddenimports list in the spec file
    hiddenimports_str = "hiddenimports=[]"
    hiddenimports_line = f"hiddenimports={hiddenimports}"

    # modify the spec file content by replacing the old hiddenimports list with the new one
    spec_content = spec_content.replace(hiddenimports_str, hiddenimports_line)

    # write the modified spec content back to the spec file
    with open(spec_file_path, "w") as spec_file:
        spec_file.write(spec_content)


CONSOLE_EXECUTABLES: dict[str, str] = {
    # the desktop app with a console attached, for reading its log live
    "exe_debug": "NfoForge-debug",
    # the command line; `nfoforge.launcher` runs it from this file name
    "exe_cli": CLI_EXECUTABLE,
}


def add_console_executables(spec_content: str) -> str:
    """Add the console executables to a generated spec.

    Each is a copy of the desktop app's EXE over the same analysis and bundle,
    renamed and given a console. Sharing the analysis is what lets the command
    line load any plugin the desktop app can, Qt included.
    """
    # regex pattern to match multi-line EXE definitions
    exe_pattern = re.compile(r"(exe\s*=\s*EXE\s*\(\s*\n(?:[^)]*\n)*?\))", re.MULTILINE)

    matches = list(exe_pattern.finditer(spec_content))
    if not matches:
        raise ValueError("Could not find EXE definition in the spec file.")
    original_exe = matches[0].group(1)

    copies = [
        original_exe.replace("exe = ", f"{variable} = ")
        .replace("console=False", "console=True")
        .replace("name='NfoForge'", f"name='{name}'")
        for variable, name in CONSOLE_EXECUTABLES.items()
    ]
    spec_content = spec_content.replace(
        original_exe, "\n".join([original_exe, *copies])
    )

    # list them in COLLECT beside the original, so they share its bundle
    collect_pattern = re.compile(r"(coll\s*=\s*COLLECT\s*\(\s*\n\s*exe,)", re.MULTILINE)
    added = "".join(f"\n    {variable}," for variable in CONSOLE_EXECUTABLES)
    spec_content, found = collect_pattern.subn(rf"\1{added}", spec_content)
    if not found:
        raise ValueError("Could not find COLLECT definition in the spec file.")
    return spec_content


def get_site_packages() -> Path:
    output = run(  # noqa: S603 - fixed argv, no shell, maintainer-run build script
        ["uv", "pip", "show", "babelfish"],  # noqa: S607 - "uv" resolved via PATH by design
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    get_location = re.search(r"Location: (.+)\n", output, flags=re.MULTILINE)
    if not get_location:
        raise FileNotFoundError("Can not detect site packages")
    return Path(get_location.group(1))


def run_doc_stuff(project_root: Path) -> Path:
    """Runs needed doc scripts and builds up to date docs to bundle."""
    # build doc snippets
    print("Generating document snippets")
    docs_scripts_dir = project_root / "docs_scripts"
    for py_file in docs_scripts_dir.glob("*.py"):
        build_doc_snippets = run(("uv", "run", str(py_file)))  # noqa: S603 - fixed argv, no shell, maintainer-run build script
        if build_doc_snippets.returncode != 0:
            raise AttributeError("Failed to build documentation for build")

    # build final docs
    print("Generating documentation")
    out = project_root / "assets" / "docs"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    build_doc = run(  # noqa: S603 - fixed argv, no shell, maintainer-run build script
        ("uv", "run", "mkdocs", "build", "--clean", "--site-dir", str(out))
    )
    if build_doc.returncode != 0:
        raise AttributeError("Failed to build documentation for build")
    return out


def build_app(folder_name: str, include_std_lib: bool, debug: bool = False):
    # change directory to the project's root directory
    project_root = Path(__file__).parent
    os.chdir(project_root)

    # ensure we're in a virtual env, if we are, install build and documentation extras
    if sys.prefix == sys.base_prefix:
        raise Exception("You must activate your virtual environment first")
    else:
        check_packages = run(  # noqa: S603 - fixed argv, no shell, maintainer-run build script
            ["uv", "sync", "--locked", "--extra", "build", "--extra", "docs"],  # noqa: S607 - "uv" resolved via PATH by design
            check=True,
            text=True,
        )
        if check_packages.returncode != 0:
            raise Exception("Failed to sync packages with UV")

    # build fresh docs after the documentation extra is available
    run_doc_stuff(project_root)

    # pyinstaller build folder
    pyinstaller_folder = project_root / folder_name

    # delete the old build folder if it exists
    shutil.rmtree(pyinstaller_folder, ignore_errors=True)

    # create a folder for the PyInstaller output
    pyinstaller_folder.mkdir(exist_ok=True)

    # define paths before changing directory
    entry_script = project_root / "nfoforge" / "launcher.py"
    icon_path = project_root / "assets" / "images" / "hammer_merged.ico"
    if platform.system() == "Darwin":
        icns_candidate = project_root / "assets" / "images" / "hammer_merged.icns"
        if icns_candidate.exists():
            icon_path = icns_candidate
    site_packages = get_site_packages()
    babel_fish = site_packages / "babelfish"
    guessit = site_packages / "guessit"

    # read-only files the release ships; nothing the user owns lives here, so
    # there is no stripping pass to run afterwards
    assets = project_root / "assets"

    # change directory so PyInstaller outputs all of its files in its own folder
    os.chdir(pyinstaller_folder)

    # run PyInstaller makespec to generate the spec file
    run(  # noqa: S603 - fixed argv, no shell, maintainer-run build script
        [  # noqa: S607 - "uv" resolved via PATH by design
            "uv",
            "run",
            "pyi-makespec",
            # "--onefile",
            "-w" if not debug else "-c",
            f"--icon={icon_path}",
            f"--add-data={assets}:assets",
            f"--add-data={babel_fish}:./babelfish",
            f"--add-data={guessit}:./guessit",
            # setuptools is in the build environment, so pkg_resources gets
            # collected and a PyInstaller startup hook imports it at every
            # launch, printing a deprecation warning to the command line's
            # console. Nothing NfoForge runs uses it.
            "--exclude-module",
            "pkg_resources",
            "--contents-directory",
            "bundle",
            "--name",
            "NfoForge",
            str(entry_script),
        ],
        check=True,
    )

    # modify the generated spec file
    spec_file_path = pyinstaller_folder / "NfoForge.spec"

    # name the modules PyInstaller's own import walk cannot reach
    modify_spec_file(spec_file_path, spec_hiddenimports(include_std_lib))

    # add the debug and command line executables beside the desktop app
    spec_file_path.write_text(
        add_console_executables(spec_file_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    # run pyinstaller
    build_job = run(  # noqa: S603 - fixed argv, no shell, maintainer-run build script
        ["uv", "run", "pyinstaller", "--noconfirm", str(spec_file_path)],  # noqa: S607 - "uv" resolved via PATH by design
    )

    # ensure the output of the executable
    success = "Did not complete successfully"
    if platform.system() == "Darwin":
        # PyInstaller's windowed (-w) onedir build on macOS wraps the output
        # into an .app bundle instead of the flat folder Windows/Linux produce
        exe_dir = pyinstaller_folder / "dist" / "NfoForge.app" / "Contents" / "MacOS"
    else:
        exe_dir = pyinstaller_folder / "dist" / "NfoForge"
    extension = get_executable_string_by_os()
    exe_path = exe_dir / f"NfoForge{extension}"
    cli_path = exe_dir / f"{CLI_EXECUTABLE}{extension}"
    if exe_path.is_file() and cli_path.is_file() and build_job.returncode == 0:
        success = (
            f"\nSuccess!\nPath to executable: {exe_path}\nCommand line: {cli_path}"
        )

    # change directory back to the original directory
    os.chdir(project_root)

    # bail out loudly rather than reporting success for a folder with no
    # executable in it - a failed PyInstaller run must fail the build (and CI)
    if build_job.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {build_job.returncode}.")
    for path in (exe_path, cli_path):
        if not path.is_file():
            raise FileNotFoundError(
                f"PyInstaller reported success but the expected executable is "
                f"missing: {path}"
            )

    # Return a success message
    return success


if __name__ == "__main__":
    print("Building release...")
    build_full = build_app("pyinstaller_build_full", True)
    print(build_full)
