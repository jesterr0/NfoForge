# Install

Run from [Release](#run-from-release) or [Run From Source](#run-from-source).

## Run From Release

1. Download the latest [release](https://github.com/jesterr0/NfoForge/releases) for your operating system.
2. Extract the contents of the release.
3. Execute **NfoForge**.

## Run From Source

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).

<!--prettier-ignore-start -->

2. Install Python with uv if not already installed.  
   <small>_Refer to the **requires-python** value in `pyproject.toml` to see the supported Python range._</small>

    ```sh
    uv python install 3.12
    ```

3. Create a virtual environment and install dependencies.

    ```sh
    uv pip install -r pyproject.toml
    ```

4. Start the application.

    ```sh
    uv run .\start_ui.py
    ```
    
<!--prettier-ignore-end -->
