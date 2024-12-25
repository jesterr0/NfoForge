import os
import shutil
import sys
from pathlib import Path
from subprocess import run
from stdlib_list import stdlib_list

# TODO: add support for linux


def get_std_lib() -> list:
    """Return all standard library modules removing 'this' and 'antigravity'"""
    standard_lib = stdlib_list()
    standard_lib.remove("this")
    standard_lib.remove("antigravity")
    return standard_lib


def modify_spec_file(spec_file_path: Path, hiddenimports: list):
    # open the spec file and read the contents
    with open(spec_file_path, "r") as spec_file:
        spec_content = spec_file.read()

    # find the hiddenimports list in the spec file
    hiddenimports_str = "hiddenimports=[]"
    hiddenimports_line = f"hiddenimports={hiddenimports}"

    # modify the spec file content by replacing the old hiddenimports list with the new one
    spec_content = spec_content.replace(hiddenimports_str, hiddenimports_line)

    # write the modified spec content back to the spec file
    with open(spec_file_path, "w") as spec_file:
        spec_file.write(spec_content)


def build_app(folder_name: str, include_std_lib: bool):
    # change directory to the project's root directory
    project_root = Path(__file__).parent
    os.chdir(project_root)

    # ensure we're in a virtual env, if we are, install dependencies using Poetry
    if sys.prefix == sys.base_prefix:
        raise Exception("You must activate your virtual environment first")
    else:
        run(["poetry", "install"])

    # pyinstaller build folder
    pyinstaller_folder = project_root / folder_name

    # delete the old build folder if it exists
    shutil.rmtree(pyinstaller_folder, ignore_errors=True)

    # create a folder for the PyInstaller output
    pyinstaller_folder.mkdir(exist_ok=True)

    # grab venv path
    venv_path = Path(
        run(
            ["poetry", "env", "info", "--path"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )

    # define paths before changing directory
    entry_script = project_root / "start_ui.py"
    icon_path = project_root / "runtime" / "images" / "hammer_merged.ico"
    babel_fish = venv_path / "Lib" / "site-packages" / "babelfish"
    guessit = venv_path / "Lib" / "site-packages" / "guessit"

    # dev runtime path to pull into final package
    dev_runtime = project_root / "runtime"

    # change directory so PyInstaller outputs all of its files in its own folder
    os.chdir(pyinstaller_folder)

    # run PyInstaller makespec to generate the spec file
    run(
        [
            "poetry",
            "run",
            "pyi-makespec",
            # "--onefile",
            f"--icon={icon_path}",
            "--add-data",
            f"{dev_runtime};runtime",
            "--add-data",
            f"{babel_fish};./babelfish",
            "--add-data",
            f"{guessit};./guessit",
            "--contents-directory",
            "bundle",
            "--name",
            "NfoForge",
            str(entry_script),
        ]
    )

    # modify the generated spec file
    spec_file_path = pyinstaller_folder / "NfoForge.spec"

    # add standard lib to bundle if needed
    if include_std_lib:
        hiddenimports = get_std_lib()
        modify_spec_file(spec_file_path, hiddenimports)

    # run PyInstaller using the modified spec file
    build_job = run(
        ["poetry", "run", "pyinstaller", "--noconfirm", str(spec_file_path)],
    )

    # ensure the output of the .exe
    success = "Did not complete successfully"
    exe_path = project_root / pyinstaller_folder / "dist" / "NfoForge" / "NfoForge.exe"
    if exe_path.is_file() and str(build_job.returncode) == "0":
        success = f"\nSuccess!\nPath to exe: {str(exe_path)}"

    # change directory back to the original directory
    os.chdir(project_root)

    # create plugin folder
    plugin_folder = Path(exe_path.parent / "plugins")
    plugin_folder.mkdir()

    # remove dev files
    bundled_runtime = Path(exe_path.parent / "bundle" / "runtime")

    # remove all config files from config directory
    for cfg_file in Path(bundled_runtime / "config").rglob("*.toml"):
        if not str(cfg_file.parent).endswith("defaults"):
            cfg_file.unlink()

    # remove templates
    for template_file in Path(bundled_runtime / "templates").glob("*.txt"):
        template_file.unlink()

    # remove user packages
    shutil.rmtree(bundled_runtime / "user_packages")

    # remove logs
    for log_file in Path(bundled_runtime / "logs").glob("*.log"):
        log_file.unlink()

    # Return a success message
    return success


if __name__ == "__main__":
    build_full = build_app("pyinstaller_build_full", True)
    print(build_full)
