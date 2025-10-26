import importlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pymediainfo import MediaInfo
from PySide6.QtCore import SignalInstance

from src.backend.utils.working_dir import CURRENT_DIR
from src.config.config import Config
from src.context.processing_context import ProcessingContext
from src.enums.tracker_selection import TrackerSelection
from src.exceptions import PluginError
from src.logger.nfo_forge_logger import LOG
from src.plugins.plugin_payload import PluginPayload
from src.plugins.plugin_wizard_base import WizardPluginBase


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

        # load plugin_payload
        try:
            main_module = self._load_package_module(package_name)
            plugin_payload = main_module.plugin_payload
            self._check_plugin(plugin_payload)
            self.plugins[plugin_payload.name] = plugin_payload
            LOG.debug(LOG.LOG_SOURCE.FE, f"Plugin loaded: {plugin_payload.name}")
        except AttributeError:
            raise PluginError(f"Failed to load plugin package: {package_name}")

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

        if plugin_payload.flat_filters:
            if not isinstance(plugin_payload.flat_filters, dict):
                raise PluginError(
                    "'PluginPayload.flat_filters' should be a dictionary of {str: Callable}"
                )

        self._validate_plugin_functions(
            plugin_payload,
            {
                "token_replacer": {
                    "config": Config,
                    "context": ProcessingContext,
                    "input_str": str,
                    "tracker_s": Sequence[TrackerSelection],
                },
                "pre_upload": {
                    "config": Config,
                    "context": ProcessingContext,
                    "tracker": TrackerSelection,
                    "torrent_file": Path,
                    "upload_text_cb": Callable[[str], None],
                    "upload_text_replace_last_line_cb": Callable[[str], None],
                    "progress_cb": Callable[[float], None],
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
