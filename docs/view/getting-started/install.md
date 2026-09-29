# Install

Run from [Release](#run-from-release) or [Run From Source](#run-from-source).

## Run From Release

1. Download the latest [release](https://github.com/jesterr0/NfoForge/releases) for your operating system.
2. Extract the contents of the release.
3. Execute **NfoForge**.

!!! info "Already using an older version?" From 1.2.0 onward your settings and data live outside the application folder, so replacing a release leaves them alone. The first launch offers to bring your existing settings across. See [Upgrading](upgrading.md).

## Run From Source

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).

<!--prettier-ignore-start -->

2. Install Python with uv if not already installed.  

    !!! question "What version of Python?"
        Refer to the **requires-python** value in [`pyproject.toml`](https://github.com/jesterr0/NfoForge/blob/main/pyproject.toml) to see the supported Python range.

    ```sh
    uv python install 3.12
    ```

3. Configure the HTTP dependencies, then create a virtual environment and install the locked runtime dependencies.

    NfoForge uses both Requests-based clients and Niquests. The project keeps their
    HTTP transports in separate namespaces, so `URLLIB3_NO_OVERRIDE` must be set
    before `uv sync` installs `urllib3-future`.

    On Windows PowerShell:

    ```powershell
    $env:URLLIB3_NO_OVERRIDE = "1"
    uv sync --locked
    ```

    On macOS or Linux:

    ```sh
    URLLIB3_NO_OVERRIDE=1 uv sync --locked
    ```

    Use `uv sync --locked --all-extras` instead when you also need every optional
    extra. `--all-extras` controls which optional dependencies are installed; it
    does not replace the environment variable above.

4. Start the application.

    ```sh
    uv run nfoforge-gui
    ```

### Updating the locked HTTP dependencies

The lockfile must keep `urllib3-future` at version `2.14.900` or newer. That
release fixed installation-order problems that could mix the `urllib3` and
`urllib3-future` package files in a fresh environment. When intentionally
refreshing this transitive dependency, run:

```sh
uv lock --upgrade-package urllib3-future
```

Commit the resulting `uv.lock`, and keep `URLLIB3_NO_OVERRIDE=1` set before the
next `uv sync`. See the [`urllib3.future` cohabitation guidance](https://github.com/jawah/urllib3.future)
for the upstream rationale.
    
<!--prettier-ignore-end -->

## Where Your Settings Are Kept

NfoForge keeps your profiles, templates, cookies, plugins, tools and saved jobs in a folder of your own, separate from the application:

| System  | Location                                 |
| ------- | ---------------------------------------- |
| Windows | `%LOCALAPPDATA%\nfoforge`                |
| macOS   | `~/Library/Application Support/nfoforge` |
| Linux   | `~/.local/share/nfoforge`                |

A source checkout uses `nfoforge-dev` in the same place, so running from source never shares data with an installed release.

The desktop app and the command line use the same folder, so a profile set up in one works in the other.

### Keeping Them Somewhere Else

There are two ways to use a different folder. Both work for the desktop app and the command line alike.

**Portable mode.** Create a folder named `data` beside the NfoForge executable (on macOS, beside `NfoForge.app`). That release then keeps everything in it instead. Nothing is written beside a release unless you create the folder, and removing it goes back to the usual location.

!!! warning "Keep the `data` folder when you upgrade" In portable mode your settings live inside the release folder. When you replace a release, move its `data` folder into the new one rather than deleting the old folder.

**For one launch.** Pass `--data-dir PATH`:

```sh
NfoForge --data-dir D:\nfoforge-data
nfoforge-cli --data-dir /config upload ...
```

This is the one to use in a container or a script. It takes priority over portable mode, and the folder is created if it does not exist.

Either way, the folder starts empty. To bring your existing settings across, copy the contents of your current data folder into it before the first launch.
