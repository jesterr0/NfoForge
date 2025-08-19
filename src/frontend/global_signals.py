from PySide6.QtCore import QObject, Signal


class GlobalSignals(QObject):
    """Singleton used to keep up with global signals"""

    _instance = None

    ########### SIGNALS ###########
    ask_prompt = Signal(str, str, object)  # prompt title, prompt, Queue
    ask_multi_prompt = Signal(str, object, object)  # prompt title, Sequence[str], Queue
    ask_custom_prompt = Signal(object, object)  # CustomPromptDialog | QDialog, Queue

    # main window
    main_window_set_disabled = Signal(bool)
    main_window_update_status_tip = Signal(str, int)  # message, timeout[milliseconds]
    main_window_clear_status_tip = Signal()
    main_window_hide = Signal(bool)
    main_window_update_status_bar_label = Signal(str)
    main_window_open_log_dir = Signal()
    main_window_open_log_file = Signal()

    # scaling
    scale_factor_changed_by_user = Signal(float)  # user hotkey changes (auto-save)
    scale_factor_changed = Signal(float)  # all changes (UI sync)
    scale_factor_set_from_settings = Signal(float)  # settings UI changes (no auto-save)

    # settings
    settings_clicked = Signal()
    settings_refresh = Signal()
    settings_close = Signal()  # called anytime we close settings
    settings_tab_changed = Signal(int)  # new index or -1 if not new
    settings_swap_tab = Signal(object)  # SettingsTabs (enum)
    token_state_changed = Signal()

    # wizard
    wizard_next = Signal()
    wizard_set_disabled = Signal(bool)
    wizard_end_early = Signal()
    wizard_next_button_reset_txt = Signal()
    wizard_next_button_change_txt = Signal(str)
    wizard_process_btn_clicked = Signal()
    wizard_process_btn_change_txt = Signal(str)
    wizard_process_btn_set_hidden = Signal()

    # process
    prompt_tokens_response = Signal(object)  # dict[str, str]
    # dict[TrackerSelection, dict[str | None, str]]
    overview_prompt_response = Signal(object)
    ########### SIGNALS ###########

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, parent=None) -> None:
        # ensure we've only initialized once
        if not hasattr(self, "_initialized"):
            super().__init__(parent)
            self._initialized = True


# alias to shorted class name
GSigs = GlobalSignals
