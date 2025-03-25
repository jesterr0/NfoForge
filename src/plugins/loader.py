import importlib
import platform
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from pymediainfo import MediaInfo
from typing import Any

from PySide6.QtCore import SignalInstance

from src.backend.utils.working_dir import CURRENT_DIR
from src.exceptions import PluginError

from src.config.config import Config
from src.enums.tracker_selection import TrackerSelection
from src.logger.nfo_forge_logger import LOG
from src.plugins.plugin_wizard_base import WizardPluginBase
from src.plugins.plugin_payload import PluginPayload
from src.backend.utils.working_dir import RUNTIME_DIR


class PluginLoader:
    def __init__(self, update_splash_msg: SignalInstance) -> None:
        self.update_splash_msg = update_splash_msg
        self.plugins: dict[str, PluginPayload] = {}
        self.plugin_dir = CURRENT_DIR / "plugins"
        self.plugin_dir.mkdir(exist_ok=True, parents=True)

    def load_plugins(self) -> dict[str, PluginPayload]:
        """Load all plugin packages."""
        # get plugins in current directory or ONE level down
        directories = tuple(p for p in self.plugin_dir.glob("*") if p.is_dir()) + tuple(
            p for p in self.plugin_dir.glob("*/*") if p.is_dir()
        )
        for item in directories:
            if (
                item.is_dir()
                and item.name.startswith("plugin_")
                or item.name.startswith("plugin-")
            ):
                sys.path.append(str(item.parent))
                self._handle_dir(item)
        if self.plugins:
            LOG.debug(LOG.LOG_SOURCE.FE, f"Detected plugins: {self.plugins}")
        return self.plugins

    def _handle_dir(self, item_dir: Path) -> None:
        """Handle the plugin directory and load as a package."""
        package_name = item_dir.stem

        # ensure plugin folder has an __init__.py to treat it as a package
        init_file = item_dir / "__init__.py"
        init_file_pyd = item_dir / "__init__.pyd"
        if not init_file.exists() and not init_file_pyd.exists():
            raise PluginError("You must have a properly structured __init__ file")

        # check for requirements file and pip dependencies if needed
        self._pip_packages(item_dir / "requirements.txt")

        # load plugin_payload
        try:
            main_module = self._load_package_module(package_name)
            plugin_payload = main_module.plugin_payload
            self._check_plugin(plugin_payload)
            self.plugins[plugin_payload.name] = plugin_payload
            LOG.debug(LOG.LOG_SOURCE.FE, f"Plugin loaded: {plugin_payload.name}")
        except AttributeError:
            raise PluginError(f"Failed to load plugin package: {package_name}")

    def _pip_packages(self, requirements_txt: Path) -> None:
        if requirements_txt.exists() and requirements_txt.is_file():
            pip_dir = RUNTIME_DIR / "user_packages"
            pip_dir.mkdir(exist_ok=True)
            if str(pip_dir) not in sys.path:
                sys.path.append(str(pip_dir))

            # run `pip list` to get installed packages and parse the output into a dictionary
            get_installed_packages = subprocess.run(
                ["pip", "list", "--path", str(pip_dir), "--format=freeze"],
                check=True,
                text=True,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
                if platform.system() == "Windows"
                else 0,
            )
            LOG.debug(LOG.LOG_SOURCE.FE, f"PIP task output: {get_installed_packages}")

            # parse the output into a dictionary of installed packages
            installed_packages = {}
            for line in get_installed_packages.stdout.splitlines():
                pkg, version = line.split("==")
                installed_packages[pkg] = version

            # read the requirements.txt
            with open(requirements_txt, "r") as f:
                requirements = f.readlines()

            # filter out already installed or outdated packages
            packages_to_install = []
            for req in requirements:
                req = req.strip()
                if req:
                    # parse the required package name and version
                    if "==" in req:
                        package, required_version = req.split("==")
                    else:
                        package = req
                        required_version = None

                    installed_version = installed_packages.get(package)

                    # if package is not installed, we'll install it
                    if not installed_version:
                        packages_to_install.append(req)
                    elif required_version and installed_version != required_version:
                        packages_to_install.append(req)

            # install missing or outdated packages
            if packages_to_install:
                LOG.debug(
                    LOG.LOG_SOURCE.FE, f"PIP task output: {get_installed_packages}"
                )
                pip_cmd = [
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--target",
                    str(pip_dir),
                ] + packages_to_install
                self.update_splash_msg.emit("Installing needed user packages")
                LOG.debug(
                    LOG.LOG_SOURCE.FE, f"Installing missing user packages: {pip_cmd}"
                )
                pip_job = subprocess.run(
                    pip_cmd,
                    check=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if platform.system() == "Windows"
                    else 0,
                )
                LOG.debug(LOG.LOG_SOURCE.FE, f"Package install status: {pip_job}")

    def _load_package_module(self, package_name: str):
        """Dynamically import the main module within a plugin package."""
        # import the module as a package submodule
        module = importlib.import_module(package_name)
        sys.modules[package_name] = module
        return module

    def _check_plugin(self, plugin_payload: Any) -> None:
        if not isinstance(plugin_payload, PluginPayload):
            raise PluginError("Plugin isn't an instance of PluginPayload")

        if not plugin_payload.name:
            raise PluginError("PluginPayload requires the 'name' field to be filled")

        if plugin_payload.wizard and not issubclass(
            plugin_payload.wizard, WizardPluginBase
        ):
            raise PluginError(
                "'PluginPayload.wizard' should be a subclass of 'WizardPluginBase'"
            )

        if plugin_payload.jinja2_filters:
            if not isinstance(plugin_payload.jinja2_filters, dict):
                raise PluginError(
                    "'PluginPayload.jinja2_filters' should be a dictionary of {str: Callable}"
                )

        if plugin_payload.jinja2_functions:
            if not isinstance(plugin_payload.jinja2_functions, dict):
                raise PluginError(
                    "'PluginPayload.jinja2_functions' should be a dictionary of {str: Callable}"
                )

        self._validate_plugin_functions(
            plugin_payload,
            {
                "token_replacer": {
                    "config": Config,
                    "input_str": str,
                    "tracker_s": Sequence[TrackerSelection],
                },
                "pre_upload": {
                    "config": Config,
                    "tracker": TrackerSelection,
                    "torrent_file": Path,
                    "media_file": Path,
                    "mi_obj": MediaInfo,
                    "upload_text_cb": Callable[[str], None],
                    "upload_text_replace_last_line_cb": Callable[[str], None],
                },
            },
        )

    def _validate_plugin_functions(
        self, plugin_payload: PluginPayload, functions: dict
    ) -> None:
        for func_name, expected_kwargs in functions.items():
            func = getattr(plugin_payload, func_name, None)
            if func:
                self._check_callable_kwargs(
                    plugin_payload_var=func,
                    plugin_name=func_name,
                    expected_kwargs=expected_kwargs,
                )

    @staticmethod
    def _check_callable_kwargs(
        plugin_payload_var: Any,
        plugin_name: str,
        expected_kwargs: dict[str, Any],
    ) -> None:
        if not callable(plugin_payload_var):
            raise PluginError(
                f"'PluginPayload.{plugin_name}' should be a callable function"
            )

        # check that the function accepts **kwargs
        func_code = getattr(plugin_payload_var, "__code__", None)
        if not func_code or "kwargs" not in func_code.co_varnames:
            raise PluginError(
                f"'{plugin_name}' must accept '**kwargs' to be compatible with the loader."
            )

        # validate expected kwargs
        annotations = getattr(plugin_payload_var, "__annotations__", {})
        for key, expected_type in expected_kwargs.items():
            actual_type = annotations.get(key)
            if actual_type and actual_type != expected_type:
                raise PluginError(
                    f"Type for kwarg '{key}' in '{plugin_name}' is incorrect. "
                    f"Expected: {expected_type}, Found: {actual_type}"
                )
