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
    uv run .\start_ui.py
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
