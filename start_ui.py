# relevant documentation
# https://doc.qt.io/qtforpython-6/index.html#

# we're going to load all .env variables for dev purposes before any other module is called
from pathlib import Path

from dotenv import load_dotenv

from src.backend.utils.working_dir import CURRENT_DIR, IS_FROZEN, RUNTIME_DIR

# The portable/frozen build must not trust an arbitrary `.env` placed beside
# the executable.  Development installs may still use the convenience file,
# but only startup code should opt into it.
if not IS_FROZEN:
    load_dotenv(CURRENT_DIR / ".env", override=False)

# remaining imports
from datetime import datetime
import faulthandler
from multiprocessing import freeze_support as mp_freeze_support
import sys
import traceback

from PySide6.QtCore import QTimer, QtMsgType, Slot, qInstallMessageHandler
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
import tomlkit

from src.backend.utils.template_token_migration import (
    migrate_templates,
    scan_template_dir,
)
from src.config.config import ConfigManager
from src.config.paths import ConfigPaths
from src.exceptions import ConfigError, ConfigSchemaError
from src.frontend.custom_widgets.scrollable_error_dialog import ScrollableErrorDialog
from src.frontend.windows.main_window import MainWindow
from src.frontend.windows.splash_screen import SplashScreen, SplashScreenLoader
from src.frontend.windows.template_migration_dialog import TemplateMigrationDialog
from src.logger.nfo_forge_logger import LOG


class NfoForge:
    def __init__(self, arg_parse: tuple[str | None, str | None]) -> None:
        self.app = QApplication(sys.argv)

        self.app.setWindowIcon(
            QIcon(str(Path(RUNTIME_DIR / "images" / "hammer_merged.png")))
        )
        self.app.setStyle("Fusion")

        self.config_file, self.arg_parse_msg = arg_parse

        # Exception/Qt hooks can run while any of the startup widgets are
        # being constructed, so initialize every optional dependency first.
        self.splash_screen_loader: SplashScreenLoader | None = None
        self.config: ConfigManager | None = None
        self.main_window: MainWindow | None = None
        self.splash_screen: SplashScreen | None = None
        # Set only by `_resolve_config_path` when `program/conf.toml` itself
        # fails to parse, so `_handle_config_error` can distinguish that
        # recoverable, single-file problem from "no config named" -- both of
        # which otherwise collapse to `_resolve_config_path` returning None.
        self.program_config_malformed = False

        # check if there is any messages from arg parser
        if not self._arg_parse_msg():
            return

        self._setup_exception_hooks()
        self._setup_font()

        # show splash screen
        self.splash_screen = SplashScreen()
        self.splash_screen.exit_app.connect(self.app.quit)
        self.splash_screen.show()
        self.splash_screen.updateMessageBox("Loading...")

        # initialize app
        self._startup_timer = QTimer(self.app, singleShot=True, interval=250)
        self._startup_timer.timeout.connect(self._init_app)
        self._startup_timer.start()

        sys.exit(self.app.exec())

    def _arg_parse_msg(self) -> bool:
        if self.arg_parse_msg:
            msg_box = QMessageBox(
                QMessageBox.Icon.Information,
                "Args",
                self.arg_parse_msg,
                QMessageBox.StandardButton.Ok,
            )
            msg_box.exec()
            self.app.quit()
            return False
        return True

    def _setup_exception_hooks(self) -> None:
        self._enable_crash_dump()
        sys.excepthook = self.exception_handler
        qInstallMessageHandler(self.qt_message_handler)

    def _enable_crash_dump(self) -> None:
        """Leave a Python stack behind if the process dies without warning.

        A segfault or access violation inside Qt or its bindings raises no
        Python exception and emits no Qt message, so neither `exception_handler`
        nor `qt_message_handler` ever runs: the application disappears and the
        log simply stops. faulthandler installs handlers for the fatal signals
        themselves and writes out every thread's Python stack when one arrives,
        which is the only record of where such a crash happened.

        The handle is kept on the instance on purpose. faulthandler writes to
        the descriptor while the process is already dying, so closing it or
        letting it be collected would leave the dump going nowhere. Appending
        keeps earlier crashes, and line buffering is what gets the bytes to disk
        before the process goes.
        """
        self._crash_log_handle = None
        crash_log = LOG.log_file.parent / "crash.log"
        try:
            handle = open(crash_log, "a", buffering=1, encoding="utf-8")
        except OSError as error:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Could not open the crash log ({crash_log}): {error}",
            )
            return
        # the log file is per run but this one is appended across runs, so a
        # dump is unattributable without naming the run it belongs to
        handle.write(f"\n=== {datetime.now().isoformat()} {LOG.log_file.name} ===\n")
        self._crash_log_handle = handle
        faulthandler.enable(file=handle)

    def _setup_font(self) -> None:
        font_folder = RUNTIME_DIR / "fonts"

        for font_file in font_folder.rglob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_file))

        desired_font = "Roboto"
        font = QFont(desired_font, 9)
        check_family = font.family()
        if check_family != desired_font:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Failed to load font {desired_font}, defaulting to {check_family}.",
            )

        self.app.setFont(font)

    def _init_app(self) -> None:
        if self.splash_screen is None:
            raise RuntimeError("Splash screen is not initialized")

        # check for multiple configs and show selector if needed
        available_configs = self._get_available_configs()
        if not self.config_file and available_configs and len(available_configs) > 1:
            self.splash_screen.show_config_selector(
                available_configs,
                selected_config=self._get_last_used_config(available_configs),
            )
            self.splash_screen.config_selected.connect(self._on_config_selected)
            return

        self._continue_init()

    def _continue_init(self) -> None:
        if self.splash_screen is None:
            raise RuntimeError("Splash screen is not initialized")

        # setup config
        self.splash_screen.updateMessageBox("Initializing config")
        try:
            self.config = ConfigManager(self.config_file)
        except ConfigSchemaError as error:
            # `ConfigSchemaError` is a subclass of `ConfigError`, so this
            # branch must stay ahead of the plain `ConfigError` one below --
            # it offers a migration-flavored recovery message, whereas the
            # generic branch is for a current-schema config that is
            # otherwise salvageable (e.g. a bad value/type for one field).
            self._handle_config_schema_error(error)
            return
        except ConfigError as error:
            self._handle_config_error(error)
            return
        if not self.config:
            raise AttributeError("Failed to load config")

        # setup loader
        self.splash_screen_loader = SplashScreenLoader(
            self.config, self.splash_screen.update_message_box, parent=self.app
        )
        self.splash_screen_loader.error_message.connect(self._error_on_splash)
        self.splash_screen_loader.success.connect(self._load_main_window)
        self.splash_screen_loader.start()

    @Slot(str)
    def _error_on_splash(self, error: str) -> None:
        if error:
            QMessageBox.critical(self.splash_screen, "Error", error)
            QApplication.quit()

    def _handle_config_schema_error(self, error: ConfigSchemaError) -> None:
        # note: by the time this fires, ConfigManager has already attempted
        # an automatic in-place migration (see `ConfigManager.load_profile`
        # / `migrate_document`) and either it wasn't applicable (the config
        # declares a version newer than this build supports, or a malformed
        # one) or it failed to fully account for the user's settings. Either
        # way, settings cannot be preserved from here, so this dialog makes
        # that explicit.
        config_path = error.config_path
        if not config_path:
            self._error_on_splash(str(error))
            return

        self._offer_archive_and_regenerate(
            config_path,
            str(error),
            "Your existing settings could not be fully migrated.",
            title="Incompatible Config",
        )

    def _handle_config_error(self, error: ConfigError) -> None:
        """Handle a non-schema `ConfigError` -- e.g. an invalid or
        unsupported value in an otherwise current-schema config, such as an
        int written where a float is expected -- by offering the same
        archive+regenerate recovery path used for an incompatible schema,
        instead of a fatal quit.

        Unlike `ConfigSchemaError`, a plain `ConfigError` carries no
        `config_path` (it can be raised before `ConfigManager` has fully
        constructed, so there is no object to attach one to), so the path is
        independently resolved from the config the app was asked to load.
        """
        config_path = self._resolve_config_path()
        # Checked ahead of (rather than alongside) `config_path`: a malformed
        # program config always resolves `config_path` to `None` in the same
        # call that sets this flag (see `_resolve_config_path`), so the flag
        # alone is the authoritative signal -- a known profile name must not
        # let this be missed.
        if self.program_config_malformed:
            self._offer_program_config_reset(str(error))
            return
        if not config_path:
            self._error_on_splash(str(error))
            return

        self._offer_archive_and_regenerate(
            config_path,
            str(error),
            "Your existing configuration has an invalid or unsupported value.",
            title="Invalid Config",
        )

    def _resolve_config_path(self) -> Path | None:
        """Best-effort resolution of the profile path the app was trying to
        load, for use when a plain `ConfigError` (no `config_path`
        attribute) is raised without a fully constructed `ConfigManager` to
        ask instead."""
        try:
            paths = ConfigPaths()
            config_file = self.config_file
            # `ConfigManager.load_program` parses `paths.program` on every
            # init regardless of whether a profile name was already
            # supplied (e.g. via `-c/--config`, or via the multi-profile
            # splash selector, which only globs `user_configs` and never
            # touches the program config) -- so detection here must not be
            # gated behind "no config file was given" either, or a
            # malformed program config with a known profile name silently
            # resolves to that profile's (fine) path instead, routing to
            # the profile archive+regenerate dialog and discarding a good
            # profile on every launch while never touching the file that
            # is actually broken.
            if paths.program.exists():
                try:
                    program_doc = tomlkit.parse(
                        paths.program.read_text(encoding="utf-8")
                    )
                except Exception:
                    # The program config itself is unparseable. That is its
                    # own recoverable problem -- one small file -- and must
                    # not be reported as an unrecoverable profile error.
                    self.program_config_malformed = True
                    return None
                if not config_file:
                    # mirrors `ConfigManager.decode_program`, which defaults
                    # a missing `current_config` key to "config" -- keep
                    # both resolutions of an absent key in agreement. Only
                    # fills in a profile name that wasn't already known;
                    # an explicitly supplied one always wins.
                    config_file = program_doc.get("current_config", "config")
            if not config_file:
                return None
            return paths.user_configs / f"{config_file}.toml"
        except Exception:
            return None

    def _offer_program_config_reset(self, error_text: str) -> None:
        """`program/conf.toml` is unparseable. Unlike a profile reset -- which
        loses every setting the user has entered -- this file stores only
        which profile is active and the window position, so regenerating it
        is safe and the recovery dialog says so instead of reusing the more
        alarming "settings will reset" wording used for a profile.
        """
        if self.splash_screen is None:
            raise RuntimeError("Splash screen is not initialized")

        # Reset up front rather than only on the success path: this handler
        # only ever runs because the flag was true, so its job of routing
        # here is already done, and the invariant ("true" means the next
        # `_resolve_config_path` call hasn't run yet) shouldn't depend on
        # `_error_on_splash`/`QApplication.quit()` on the decline/failure
        # branches below actually terminating startup rather than merely
        # requesting it.
        self.program_config_malformed = False

        paths = ConfigPaths()
        response = QMessageBox.question(
            self.splash_screen,
            "Invalid Program Config",
            (
                f"{error_text}\n\n"
                "NfoForge's program configuration file could not be read. It "
                "stores only which profile is active and the window "
                "position, so it can be safely recreated -- your profiles "
                "and settings are not affected.\n\n"
                f"File:\n{paths.program}\n\n"
                "Recreate it and continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response != QMessageBox.StandardButton.Yes:
            QApplication.quit()
            return

        try:
            if paths.program.exists():
                backup = paths.program.with_name(
                    f"{paths.program.name}.{datetime.now():%Y-%m-%d_%H-%M-%S}.bak"
                )
                paths.program.replace(backup)
        except OSError as reset_error:
            self._error_on_splash(
                f"Could not archive the program config: {reset_error}"
            )
            return

        # `_continue_init` -> `ConfigManager.__init__` -> `load_program`
        # recreates `program/conf.toml` from the bundled default the moment
        # `paths.program.exists()` is false, so this cannot loop back into
        # the same malformed-parse failure: the offending file is gone
        # before the retry ever reads it again.
        self._continue_init()

    def _offer_archive_and_regenerate(
        self, config_path: Path, error_text: str, issue_description: str, title: str
    ) -> None:
        if self.splash_screen is None:
            raise RuntimeError("Splash screen is not initialized")

        response = QMessageBox.question(
            self.splash_screen,
            title,
            (
                f"{error_text}\n\n"
                f"{issue_description}\n\n"
                "Would you like NfoForge to archive this config and generate a "
                "new default config? Settings will reset and must be "
                "re-entered.\n\n"
                f"Current config:\n{config_path}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if response != QMessageBox.StandardButton.Yes:
            QApplication.quit()
            return

        try:
            backup_path = ConfigManager.replace_profile_with_default(config_path)
        except ConfigError as reset_error:
            self._error_on_splash(str(reset_error))
            return
        except Exception as reset_error:
            self._error_message_box(
                "Config Reset Failed",
                str(reset_error),
                traceback.format_exc(),
            )
            self.app.exit()
            return

        QMessageBox.information(
            self.splash_screen,
            "Config Recreated",
            (
                f"{issue_description}\n\n"
                f"The old config has been backed up to:\n{backup_path}\n\n"
                "A new default config has been created; settings must be "
                "re-entered."
            ),
        )
        self._continue_init()

    @Slot(str)
    def _load_main_window(self, plugin_warning: str) -> None:
        if self.splash_screen is None:
            raise RuntimeError("Splash screen is not initialized")

        if plugin_warning:
            QMessageBox.warning(
                self.splash_screen, "Plugin Load Warning", plugin_warning
            )

        self._maybe_prompt_template_migration()

        self.splash_screen.update_message_box.emit("Loading main window")
        if not self.config:
            raise AttributeError("Failed to load config")

        try:
            self.main_window = MainWindow(self.config)
        except Exception as error:
            self._error_message_box(
                "Unhandled Exception", str(error), traceback.format_exc()
            )
            self.app.exit()
            return

        self.splash_screen.close()
        self.main_window.show()

    def _maybe_prompt_template_migration(self) -> None:
        """Offer to update templates that reference renamed tokens.

        Runs after the config migration has already completed and committed,
        so declining here -- or a write failure below -- can never leave the
        profile half-migrated. Any unexpected failure is swallowed: a
        convenience prompt must never block startup.
        """
        if not self.config or self.config.program.suppress_template_token_prompt:
            return

        try:
            reports = scan_template_dir(RUNTIME_DIR / "templates")
            if not reports:
                return

            dialog = TemplateMigrationDialog(reports, parent=self.splash_screen)
            dialog.exec()
            migrate_requested = dialog.migrate_requested
            suppress_future_prompts = dialog.suppress_future_prompts
            dialog.deleteLater()

            # The migration the user just asked for runs first, and its
            # success does not depend on the suppression write below: a
            # failure persisting "don't ask again" must never look like a
            # failure to update the templates themselves.
            if migrate_requested:
                migrated = migrate_templates(reports)
                skipped = len(reports) - len(migrated)
                message = f"Updated {len(migrated)} template(s)."
                if skipped:
                    message += (
                        f"\n\n{skipped} template(s) were left unchanged; they "
                        "either could not be written or only reference tokens "
                        "that have no replacement."
                    )
                QMessageBox.information(
                    self.splash_screen, "Templates Updated", message
                )

            if suppress_future_prompts:
                self.config.program.suppress_template_token_prompt = True
                try:
                    self.config.save_program()
                except ConfigError:
                    # Best-effort only: the migration above (if requested)
                    # has already happened, so losing this write just means
                    # the user is asked again next launch -- not silently
                    # left without the migration they consented to.
                    LOG.warning(
                        LOG.LOG_SOURCE.FE,
                        "Failed to persist template-token prompt suppression: "
                        f"{traceback.format_exc()}",
                    )
        except Exception:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Template token migration prompt failed: {traceback.format_exc()}",
            )

    def _get_available_configs(self) -> list[str] | None:
        """Get list of available config file names (without .toml extension)"""
        try:
            config_dir = ConfigPaths().user_configs
            if not config_dir.exists():
                return
            return sorted([x.stem for x in config_dir.glob("*.toml")])
        except Exception:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Failed to list available configs: {traceback.format_exc()}",
            )

    def _get_last_used_config(self, available_configs: list[str]) -> str | None:
        """Return the saved profile when it is still available.

        The program configuration is intentionally read directly here because
        profile selection happens before ``ConfigManager`` can be initialized.
        A missing, malformed, or stale value simply leaves the first profile
        selected by the combo box.
        """
        try:
            program_path = ConfigPaths().program
            if not program_path.exists():
                return None
            program_document = tomlkit.parse(program_path.read_text(encoding="utf-8"))
            current_config = program_document.get("current_config", "config")
            if isinstance(current_config, str) and current_config in available_configs:
                return current_config
        except Exception:
            LOG.warning(
                LOG.LOG_SOURCE.FE,
                f"Failed to read last used config: {traceback.format_exc()}",
            )
        return None

    @Slot(str)
    def _on_config_selected(self, selected_config: str) -> None:
        """Handle profile selection from splash screen"""
        self.config_file = selected_config
        self._continue_init()

    def exception_handler(self, exc_type, exc_value, exc_traceback) -> None:
        """Global exception handler for unhandled Python exceptions."""
        full_traceback = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )
        error_message = f"Unhandled exception:\n{exc_value}\n\n{full_traceback}"
        LOG.critical(LOG.LOG_SOURCE.FE, error_message)
        self._error_message_box("Unhandled Exception", error_message)
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def qt_message_handler(self, mode, _context, message) -> None:
        """Handler for Qt-specific warnings and errors."""
        if mode in (
            QtMsgType.QtWarningMsg,
            QtMsgType.QtCriticalMsg,
            QtMsgType.QtFatalMsg,
        ):
            LOG.critical(LOG.LOG_SOURCE.FE, f"Qt Error: {message}")
            if mode == QtMsgType.QtFatalMsg:
                # Qt aborts as soon as this returns, so there is no application
                # left to show a dialog against: _error_message_box runs exec(),
                # spinning a nested event loop mid-teardown, which can hang or
                # die before anyone reads it. The log line above is what
                # survives, and is what a crash report is built from.
                return
            self._error_message_box("QtError", message)
        else:
            LOG.debug(LOG.LOG_SOURCE.FE, f"Qt: {message}")

    def _error_message_box(
        self, title: str, message: str, traceback: str | None = None
    ) -> None:
        detect_parent = (
            self.splash_screen
            if self.splash_screen and self.splash_screen.isVisible()
            else self.main_window
        )
        if traceback:
            traceback = f"\n{traceback}"
        err_msg_box = ScrollableErrorDialog(
            f"{message}{traceback if traceback else ''}",
            title=title,
            parent=detect_parent,
        )
        err_msg_box.exec()
        if detect_parent is self.splash_screen and self.splash_screen is not None:
            if self.splash_screen.isVisible():
                self.app.quit()


def arg_parse() -> tuple[str | None, str | None]:
    config_arg = None
    message_arg = None
    args = sys.argv
    length = len(args)
    if length == 2 and args[1] in ("--help", "-h", "help", "h"):
        message_arg = (
            "-c/--config <config_file> (Loads the program with desired config)"
            "\n-h/--help (Displays this message)"
        )
    elif length == 3 and args[1] in ("--config", "-c", "config", "c"):
        config_arg = args[2]
        if config_arg.lower().endswith(".toml"):
            config_arg = config_arg[:-5]
    return config_arg, message_arg


if __name__ == "__main__":
    if IS_FROZEN:
        # required for multiprocessing support when the app is frozen (exe)
        mp_freeze_support()
    NfoForge(arg_parse())
