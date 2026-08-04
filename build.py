import os
from pathlib import Path
import platform
import re
import shutil
from subprocess import run
import sys

from stdlib_list import stdlib_list

from src.backend.utils.get_os_executable_ext import get_executable_string_by_os


def get_std_lib() -> list:
    """Return all standard library modules removing 'this' and 'antigravity'"""
    standard_lib = stdlib_list()
    standard_lib.remove("this")
    standard_lib.remove("antigravity")
    return standard_lib


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


def modify_spec_file_for_dual_exe(spec_file_path: Path):
    """Modify the PyInstaller spec file to create two executables from a single bundle."""
    with open(spec_file_path) as spec_file:
        spec_content = spec_file.read()

    # regex pattern to match multi-line EXE definitions
    exe_pattern = re.compile(r"(exe\s*=\s*EXE\s*\(\s*\n(?:[^)]*\n)*?\))", re.MULTILINE)

    matches = list(exe_pattern.finditer(spec_content))
    if not matches:
        raise ValueError("Could not find EXE definition in the spec file.")

    # extract original EXE block
    original_exe = matches[0].group(1)

    # modify the original EXE block to create a debug version
    debug_exe = (
        original_exe.replace("exe = ", "exe_debug = ")
        .replace("console=False", "console=True")
        .replace("name='NfoForge'", "name='NfoForge-debug'")
    )

    # insert the debug EXE definition after the original
    modified_spec_content = spec_content.replace(
        original_exe, f"{original_exe}\n{debug_exe}"
    )

    # regex pattern to find COLLECT and insert exe_debug
    collect_pattern = re.compile(r"(coll\s*=\s*COLLECT\s*\(\s*\n\s*exe,)", re.MULTILINE)

    # modify COLLECT to include exe_debug
    modified_spec_content = collect_pattern.sub(
        r"\1\n    exe_debug,", modified_spec_content
    )

    # write back the modified spec file
    with open(spec_file_path, "w") as spec_file:
        spec_file.write(modified_spec_content)


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
    out = project_root / "runtime" / "docs"
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
    entry_script = project_root / "start_ui.py"
    icon_path = project_root / "runtime" / "images" / "hammer_merged.ico"
    if platform.system() == "Darwin":
        icns_candidate = project_root / "runtime" / "images" / "hammer_merged.icns"
        if icns_candidate.exists():
            icon_path = icns_candidate
    site_packages = get_site_packages()
    babel_fish = site_packages / "babelfish"
    guessit = site_packages / "guessit"

    # dev runtime path to pull into final package
    dev_runtime = project_root / "runtime"

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
            f"--add-data={dev_runtime}:runtime",
            f"--add-data={babel_fish}:./babelfish",
            f"--add-data={guessit}:./guessit",
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

    # add standard lib to bundle if needed
    if include_std_lib:
        hiddenimports = get_std_lib()
        modify_spec_file(spec_file_path, hiddenimports)

    # modify the generated spec file to include two executables
    modify_spec_file_for_dual_exe(spec_file_path)

    # run pyinstaller
    build_job = run(  # noqa: S603 - fixed argv, no shell, maintainer-run build script
        ["uv", "run", "pyinstaller", "--noconfirm", str(spec_file_path)],  # noqa: S607 - "uv" resolved via PATH by design
    )

    # ensure the output of the executable
    success = "Did not complete successfully"
    if platform.system() == "Darwin":
        # PyInstaller's windowed (-w) onedir build on macOS wraps the output
        # into an .app bundle instead of the flat folder Windows/Linux produce
        exe_path = (
            project_root
            / pyinstaller_folder
            / "dist"
            / "NfoForge.app"
            / "Contents"
            / "MacOS"
            / "NfoForge"
        )
    else:
        exe_path = (
            project_root
            / pyinstaller_folder
            / "dist"
            / "NfoForge"
            / f"NfoForge{get_executable_string_by_os()}"
        )
    if exe_path.is_file() and build_job.returncode == 0:
        success = f"\nSuccess!\nPath to executable: {str(exe_path)}"

    # change directory back to the original directory
    os.chdir(project_root)

    # bail out loudly instead of silently shipping a folder that only
    # contains the plugins directory created below - a failed PyInstaller
    # run must fail the build (and CI), not produce a bogus "successful" one
    if build_job.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {build_job.returncode}.")
    if not exe_path.is_file():
        raise FileNotFoundError(
            f"PyInstaller reported success but the expected executable is "
            f"missing: {exe_path}"
        )

    # create plugin folder
    plugin_folder = Path(exe_path.parent / "plugins")
    plugin_folder.mkdir(parents=True)

    # copy example jinja2 plugin example to the release
    shutil.copytree(
        project_root / "plugins" / "jinja2_plugin_example",
        plugin_folder / "plugin_example",
        ignore=lambda dir, files: [f for f in files if f == "__pycache__"],
        copy_function=shutil.copy,
    )

    # copy example metadata plugin example to the release
    shutil.copytree(
        project_root / "plugins" / "metadata_plugin_example",
        plugin_folder / "plugin_example",
        ignore=lambda dir, files: [f for f in files if f == "__pycache__"],
        copy_function=shutil.copy,
    )

    # copy example metadata plugin example to the release
    shutil.copytree(
        project_root / "plugins" / "metadata_plugin_example",
        plugin_folder / "metadata_plugin_example",
        ignore=lambda dir, files: [f for f in files if f == "__pycache__"],
        copy_function=shutil.copy,
    )

    # remove dev files
    bundled_runtime = Path(exe_path.parent / "bundle" / "runtime")

    # remove all config files from config directory
    for cfg_file in Path(bundled_runtime / "config").rglob("*.toml"):
        if not str(cfg_file.parent).endswith("defaults"):
            cfg_file.unlink(missing_ok=True)

    # remove templates
    for template_file in Path(bundled_runtime / "templates").glob("*.txt"):
        template_file.unlink(missing_ok=True)

    # remove user packages
    user_packages = bundled_runtime / "user_packages"
    if user_packages.exists():
        shutil.rmtree(bundled_runtime / "user_packages", ignore_errors=True)

    # remove logs
    for log_file in Path(bundled_runtime / "logs").glob("*.log"):
        log_file.unlink(missing_ok=True)

    # remove cookies
    for cookie_file in Path(bundled_runtime / "cookies").glob("*.pkl"):
        cookie_file.unlink(missing_ok=True)

    # remove plugins folder
    shutil.rmtree(bundled_runtime / "plugins", ignore_errors=True)

    # Return a success message
    return success


if __name__ == "__main__":
    print("Building release...")
    build_full = build_app("pyinstaller_build_full", True)
    print(build_full)
