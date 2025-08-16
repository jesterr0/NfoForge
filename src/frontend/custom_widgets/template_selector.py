from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from guessit import guessit
from jinja2.exceptions import TemplateSyntaxError

from src.backend.template_selector import TemplateSelectorBackEnd
from src.backend.token_replacer import TokenReplacer
from src.backend.tokens import TokenType, Tokens
from src.backend.utils.token_utils import get_prompt_tokens
from src.config.config import Config
from src.enums.tracker_selection import TrackerSelection
from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.custom_widgets.combo_box import CustomComboBox
from src.frontend.custom_widgets.menu_button import CustomButtonMenu
from src.frontend.custom_widgets.prompt_token_editor_dialog import (
    PromptTokenEditorDialog,
)
from src.frontend.custom_widgets.token_table import TokenTable
from src.frontend.global_signals import GSigs
from src.frontend.utils import set_top_parent_geometry
from src.frontend.utils.qtawesome_theme_swapper import QTAThemeSwap
from src.frontend.wizards.media_input_basic import MediaInputBasic
from src.frontend.wizards.media_search import MediaSearch

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class TemplateSelector(QWidget):
    destroy_token_window = Signal()
    hide_parent = Signal(bool)

    def __init__(
        self,
        config: Config,
        sandbox: bool,
        main_window: "MainWindow",
        parent=None,
        toggle_prompt_tokens: QCheckBox | None = None,
    ) -> None:
        """
        Initialize the TemplateSelector.

        Args:
            config: Configuration object
            sandbox: Whether this is running in sandbox mode
            main_window: Reference to main window
            parent: Parent widget
            toggle_prompt_tokens: Checkbox that controls prompt token behavior in sandbox mode.
                                Only used when sandbox=True.
        """
        super().__init__(parent)

        self.config = config
        self.sandbox = sandbox
        self.toggle_prompt_tokens = toggle_prompt_tokens
        self.main_window = main_window
        self.sorted_tokens = self._get_file_tokens()
        GSigs().token_state_changed.connect(self._token_state_changed)

        self.backend = TemplateSelectorBackEnd()
        self.templates = self.backend.templates
        self.template_index_map = self.create_template_index_map()
        self.old_text: str | None = None
        self.cached_sandbox_prompt_tokens: dict[str, str] | None = None

        self.token_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.token_btn, "ph.squares-four-light", icon_size=QSize(24, 24)
        )
        self.token_btn.setCheckable(True)
        self.token_btn.clicked.connect(self.show_tokens)
        self.token_window = None

        self.template_combo: QComboBox = CustomComboBox(True)
        self.template_combo.currentIndexChanged.connect(self.selection_changed)
        self.new_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.new_btn, "ph.plus-circle-light", icon_size=QSize(24, 24)
        )

        self.popup_button = CustomButtonMenu(parent=self)
        QTAThemeSwap().register(
            self.popup_button, "ph.check-square-light", icon_size=QSize(24, 24)
        )
        self.popup_button.setText("Trackers")
        self.popup_button.item_changed.connect(self._tracker_toggled)

        self.new_btn.setToolTip("Create a new template")
        self.new_btn.clicked.connect(self.new_template)

        self.save_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.save_btn, "ph.floppy-disk-light", icon_size=QSize(24, 24)
        )
        self.save_btn.setToolTip("Save current template changes")
        self.save_btn.clicked.connect(self.save_template)

        self.del_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.del_btn, "ph.trash-simple-light", icon_size=QSize(24, 24)
        )
        self.del_btn.setToolTip("Delete current template")
        self.del_btn.clicked.connect(self.delete_template)

        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setFrameShadow(QFrame.Shadow.Raised)

        self.preview_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.preview_btn, "ph.eye-light", icon_size=QSize(24, 24)
        )
        if not self.sandbox:
            self.preview_btn.setToolTip("Preview template with applied changes")
        else:
            self.preview_btn.setToolTip(
                "Preview template with applied changes in sandbox mode"
            )
        self.preview_btn.setCheckable(True)
        self.preview_btn.clicked.connect(self.preview_template)

        self.max_btn = QToolButton(self)
        QTAThemeSwap().register(
            self.max_btn, "ph.corners-out-light", icon_size=QSize(24, 24)
        )
        self.max_btn.setToolTip("Pop out window of template")
        self.max_btn.clicked.connect(self.maximize_template)
        self.max_btn.setCheckable(True)

        self.template_control_layout = QHBoxLayout()
        self.template_control_layout.addWidget(self.token_btn)
        self.template_control_layout.addWidget(self.template_combo)
        self.template_control_layout.addWidget(self.popup_button)
        self.template_control_layout.addWidget(self.new_btn)
        self.template_control_layout.addWidget(self.save_btn)
        self.template_control_layout.addWidget(self.del_btn)
        self.template_control_layout.addWidget(v_line)
        self.template_control_layout.addWidget(self.preview_btn)
        self.template_control_layout.addWidget(self.max_btn)

        self.text_edit = CodeEditor(
            line_numbers=True, wrap_text=False, mono_font=True, parent=self
        )
        self.text_edit.save_contents.connect(self.save_template)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addLayout(self.template_control_layout)
        self.main_layout.addWidget(self.text_edit)

        self.modal: QWidget | None = None
        self.modal_h_layout: QHBoxLayout | None = None
        self.modal_layout: QVBoxLayout | None = None
        self.token_table: QWidget | None = None
        self.token_table_window: QWidget | None = None
        self.destroy_token_window.connect(self._destroy_token_window)

    def get_selected_template_name(self) -> str:
        return self.template_combo.currentText()

    def create_template_index_map(self) -> dict[str, int]:
        return {name: i for i, name in enumerate(self.backend.templates.keys())}

    def load_templates(self) -> None:
        self.template_combo.clear()
        templates = self.backend.load_templates()
        if templates:
            self.template_combo.addItems(tuple(templates.keys()))
            self.template_index_map = self.create_template_index_map()
        self._update_tracker_toggles()
        # INFO: if we wanted to load last used template or a default template we could do it here
        # self.template_combo.setCurrentIndex(
        #     self.template_index_map[self.config.cfg_payload.nfo_template]
        # )

    def _update_tracker_toggles(self) -> None:
        selected_template = self.template_combo.currentText()
        trackers = [
            (
                str(tracker),
                tracker_settings.nfo_template == selected_template
                if selected_template
                else False,
            )
            for tracker, tracker_settings in self.config.tracker_map.items()
        ]
        self.popup_button.update_items(trackers)
        if not selected_template:
            self.popup_button.setDisabled(True)
        else:
            self.popup_button.setDisabled(False)

    def read_template(self) -> None:
        self.text_edit.clear()
        get_template = self.backend.read_template(
            idx=self.template_combo.currentIndex()
        )
        if get_template is not None:
            self.text_edit.setPlainText(get_template)

    @Slot(tuple)
    def _tracker_toggled(self, data: tuple[str, bool]) -> None:
        tracker, toggled = data
        if toggled:
            self.config.tracker_map[
                TrackerSelection(tracker)
            ].nfo_template = self.template_combo.currentText()
        else:
            self.config.tracker_map[TrackerSelection(tracker)].nfo_template = ""
        self.config.save_config()

    @Slot()
    def show_tokens(self) -> None:
        if self.token_btn.isChecked():
            self.token_table_window = QWidget(self, Qt.WindowType.Window)
            self.token_table_window.setWindowTitle("Tokens")
            self.token_table_window.setMinimumSize(600, 400)
            self.token_table_window.setWindowFlag(
                Qt.WindowType.WindowMinimizeButtonHint, False
            )
            layout = QVBoxLayout()
            layout.addWidget(
                TokenTable(
                    tokens=self.sorted_tokens,
                    remove_brackets=True,
                )
            )
            self.token_table_window.setLayout(layout)
            self.token_table_window.closeEvent = self.close_token_table_window
            self.token_table_window.show()
        elif not self.token_btn.isChecked() and self.token_table_window:
            self.token_table_window.close()
            self.token_table_window = None

    def close_token_table_window(self, event) -> None:
        if self.token_table_window:
            self.token_btn.setChecked(False)
            event.accept()
            self.token_table_window = None

    def _destroy_token_window(self) -> None:
        if self.token_table_window:
            self.token_table_window.close()

    @Slot(int)
    def selection_changed(self, _: int) -> None:
        self.preview_btn.setChecked(False)
        self.old_text = None
        self.read_template()
        self._update_tracker_toggles()

    @Slot()
    def new_template(self) -> None:
        template, _ = QFileDialog.getSaveFileName(
            parent=self,
            caption="Choose template name",
            filter="*.txt",
            dir=str(self.backend.template_dir),
        )
        if template:
            if not template.endswith(".txt"):
                template += ".txt"
            new = self.backend.create_template(template)
            self.load_templates()
            index = self.template_index_map.get(new.stem, -1)
            self.template_combo.setCurrentIndex(index)

    @Slot(str)
    def save_template(self, _data: str | None = None) -> None:
        # uncheck the preview button before safe if checked to prevent overwriting the template with
        # the preview data
        if self.preview_btn.isChecked():
            self.preview_btn.setChecked(False)
            self.preview_template()

        if self.template_combo.currentIndex() != -1:
            selected_template = self.backend.templates[
                self.template_combo.currentText()
            ]
            self.backend.save_template(selected_template, self.text_edit.toPlainText())
            GSigs().main_window_update_status_tip.emit("Saved template", 3000)

    @Slot()
    def delete_template(self) -> None:
        if self.template_combo.currentIndex() == -1:
            return

        selected_template = self.backend.templates[self.template_combo.currentText()]
        if not self._template_in_use(selected_template):
            return
        self.backend.delete_template(selected_template)
        self.load_templates()
        self.template_combo.setCurrentIndex(0)

    def template_edited(self) -> bool:
        get_template = self.backend.read_template(
            idx=self.template_combo.currentIndex()
        )
        if get_template is not None:
            if self.text_edit.toPlainText() != get_template:
                return True
        return False

    def _template_in_use(self, selected_template: PathLike[str]) -> bool:
        toggled_trackers = [
            str(tracker)
            for tracker, tracker_settings in self.config.tracker_map.items()
            if tracker_settings.nfo_template == Path(selected_template).stem
        ]

        if not toggled_trackers:
            return True

        if (
            QMessageBox.question(
                self,
                "Confirm Deletion",
                f"Tracker(s) {', '.join(toggled_trackers)} currently utilizes this template. "
                "Are you sure you want to delete it?",
            )
            == QMessageBox.StandardButton.No
        ):
            return False

        for detected_tracker in toggled_trackers:
            self.config.tracker_map[
                TrackerSelection(detected_tracker)
            ].nfo_template = ""
        self.config.save_config()

        return True

    @Slot()
    def preview_template(self) -> None:
        if self.template_combo.currentIndex() == -1:
            self.preview_btn.setChecked(False)
            return

        if self.preview_btn.isChecked():
            if self.sandbox:
                if (
                    not self.config.media_input_payload.encode_file
                    or not self.config.media_search_payload.title
                ):
                    self.sandbox_input = SandBoxInput(self.config, self)
                    if self.sandbox_input.exec() == QDialog.DialogCode.Rejected:
                        self.preview_btn.setChecked(False)
                        self.text_edit.setReadOnly(False)
                        return

            if not self.config.media_input_payload.encode_file:
                raise FileNotFoundError("No input file to check template")

            user_tokens = {
                k: v for k, (v, _) in self.config.cfg_payload.user_tokens.items()
            }

            self.text_edit.setReadOnly(True)
            self.old_text = self.text_edit.toPlainText()

            # gather prompt tokens
            prompt_tokens = None
            if self.old_text:
                should_process_prompt_tokens = True

                # in sandbox mode, check if prompt tokens are disabled
                if self.sandbox and self.toggle_prompt_tokens:
                    should_process_prompt_tokens = self.toggle_prompt_tokens.isChecked()

                if should_process_prompt_tokens:
                    prompt_tokens = get_prompt_tokens(self.old_text)

            if prompt_tokens:
                # build dict (use cached value if present, else "")
                tokens_dict = {
                    token: (
                        self.cached_sandbox_prompt_tokens.get(token, "")
                        if self.cached_sandbox_prompt_tokens
                        else ""
                    )
                    for token in prompt_tokens
                }
                # remove any cached tokens not in the template
                if self.cached_sandbox_prompt_tokens:
                    self.cached_sandbox_prompt_tokens = {
                        k: v
                        for k, v in self.cached_sandbox_prompt_tokens.items()
                        if k in prompt_tokens
                    }
                prompt = PromptTokenEditorDialog(tokens_dict, self)
                if prompt.exec() == QDialog.DialogCode.Accepted:
                    prompt_results = prompt.get_results()
                    self.cached_sandbox_prompt_tokens = prompt_results
                    if prompt_results:
                        user_tokens.update(prompt_results)
                else:
                    self.text_edit.setPlainText(self.old_text if self.old_text else "")
                    self.preview_btn.setChecked(False)
                    self.text_edit.setReadOnly(False)
                    return

            nfo = ""
            try:
                token_replacer = TokenReplacer(
                    media_input=self.config.media_input_payload.encode_file,
                    jinja_engine=self.config.jinja_engine,
                    source_file=self.config.media_input_payload.source_file,
                    token_string=self.old_text,
                    media_search_obj=self.config.media_search_payload,
                    media_info_obj=self.config.media_input_payload.encode_file_mi_obj,
                    source_file_mi_obj=self.config.media_input_payload.source_file_mi_obj,
                    releasers_name=self.config.cfg_payload.releasers_name,
                    dummy_screen_shots=False
                    if self.config.shared_data.url_data
                    or self.config.shared_data.loaded_images
                    else True,
                    release_notes=self.config.shared_data.release_notes,
                    edition_override=self.config.shared_data.dynamic_data.get(
                        "edition_override"
                    ),
                    frame_size_override=self.config.shared_data.dynamic_data.get(
                        "frame_size_override"
                    ),
                    movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
                    mi_video_dynamic_range=self.config.cfg_payload.mvr_mi_video_dynamic_range,
                    user_tokens=user_tokens,
                )
                output = token_replacer.get_output()
                if output:
                    nfo = output
                    if not isinstance(nfo, str):
                        raise ValueError("NFO should be an instance of string")
            except TemplateSyntaxError as syntax_error:
                QMessageBox.warning(
                    self,
                    "Template Error",
                    f"Syntax Error in template: {syntax_error.message} at line {syntax_error.lineno}",
                )
                self.preview_btn.setChecked(False)
                self.text_edit.setReadOnly(False)
                return
            except Exception:
                self.preview_btn.setChecked(False)
                self.text_edit.setReadOnly(False)
                raise

            try:
                token_replacer_plugin = self.config.cfg_payload.token_replacer
                if token_replacer_plugin:
                    plugin = self.config.loaded_plugins[
                        token_replacer_plugin
                    ].token_replacer
                    if plugin and callable(plugin):
                        selected_template = self.template_combo.currentText()
                        tracker_s = [
                            tracker
                            for tracker, tracker_settings in self.config.tracker_map.items()
                            if tracker_settings.nfo_template == selected_template
                        ]
                        replace_tokens = plugin(
                            config=self.config, input_str=nfo, tracker_s=tracker_s
                        )
                        nfo = replace_tokens if replace_tokens else nfo
            except Exception:
                # we attempt to execute the plugin, but since some data is filled in process step
                # it might not be available.
                pass

            self.text_edit.setPlainText(nfo)
        else:
            self.text_edit.setReadOnly(False)
            self.text_edit.setPlainText(self.old_text if self.old_text else "")

    @Slot()
    def maximize_template(self) -> None:
        if self.max_btn.isChecked():
            if self.token_table_window:
                self.token_table_window.close()
            self.token_btn.setChecked(False)
            self.token_btn.setDisabled(True)

            self.main_layout.removeItem(self.template_control_layout)
            self.main_layout.removeWidget(self.text_edit)

            self.modal = QWidget()
            self.modal_layout = QVBoxLayout(self.modal)
            self.modal_h_layout = QHBoxLayout()
            self.token_table = TokenTable(
                tokens=self.sorted_tokens,
                remove_brackets=True,
            )
            self.modal_h_layout.addWidget(self.token_table, stretch=4)
            self.modal_h_layout.addWidget(self.text_edit, stretch=10)
            self.modal_layout.addLayout(self.template_control_layout)
            self.modal_layout.addLayout(self.modal_h_layout)
            self.modal.setLayout(self.modal_layout)
            self.modal.setWindowFlag(Qt.WindowType.Window)
            self.modal.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            self.modal.setWindowModality(Qt.WindowModality.ApplicationModal)
            self.modal.showMaximized()
            self.hide_parent.emit(True)
        else:
            self.token_btn.setDisabled(False)

            if self.modal_layout:
                self.modal_layout.removeItem(self.template_control_layout)
            if self.modal_h_layout:
                self.modal_h_layout.removeWidget(self.text_edit)
            self.main_layout.addLayout(self.template_control_layout)
            self.main_layout.addWidget(self.text_edit)
            if self.modal:
                self.modal.close()
                self.modal = None
            self.modal_layout = None
            self.modal_h_layout = None
            self.hide_parent.emit(False)

    @Slot()
    def _token_state_changed(self) -> None:
        self.sorted_tokens = self._get_file_tokens()

    def _get_file_tokens(self) -> list[TokenType]:
        user_tokens = [
            TokenType(f"{{{k}}}", "User Token")
            for k in self.config.cfg_payload.user_tokens.keys()
        ]
        return sorted(Tokens().get_token_objects()) + user_tokens


class SandBoxInput(QDialog):
    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sandbox Input")
        set_top_parent_geometry(self)

        self.config = config
        self._wizard_next_count = 0

        GSigs().main_window_set_disabled.connect(self._set_disabled)
        GSigs().main_window_update_status_tip.connect(self._update_fake_status_bar)
        GSigs().main_window_clear_status_tip.connect(self._clear_fake_status_bar)

        self.sandbox_lbl = QLabel("Input", self)

        self.media_input = MediaInputBasic(
            self.config, self, on_finished_cb=self._handle_next
        )
        self.media_input.main_layout.setContentsMargins(0, 0, 0, 0)
        self.media_input.file_loaded.connect(self._update_media_search)
        self.media_input.file_tree.setMaximumHeight(130)

        self.media_search_lbl = QLabel("Search", self)

        self.media_search = MediaSearch(
            self.config, self, on_finished_cb=self._handle_next
        )
        self.media_search.main_layout.setContentsMargins(0, 0, 0, 0)

        self.accept_btn = QToolButton(self)
        self.accept_btn.setText("Accept")
        self.accept_btn.clicked.connect(self._accept)

        self.fake_status_bar = QLabel(self)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(self.sandbox_lbl)
        self.main_layout.addWidget(self.media_input)
        self.main_layout.addWidget(self.media_search_lbl)
        self.main_layout.addWidget(self.media_search, stretch=5)
        self.main_layout.addWidget(
            self.accept_btn, alignment=Qt.AlignmentFlag.AlignRight
        )
        self.main_layout.addSpacerItem(
            QSpacerItem(
                1, 20, QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
            )
        )
        self.main_layout.addWidget(self.fake_status_bar)

    @Slot(str)
    def _update_media_search(self, file_path: str) -> None:
        guess = guessit(Path(file_path).name)
        guessed_title = guess.get("title", "")
        year = guess.get("year", "")
        if year:
            guessed_title = f"{guessed_title} {year}"

        self.media_search.search_entry.setText(guessed_title)
        self.media_search._search_tmdb_api()

    @Slot()
    def _accept(self) -> None:
        self.media_input.validatePage()

    @Slot()
    def _handle_next(self) -> None:
        if self._wizard_next_count == 0:
            self.media_search.validatePage()
            self._wizard_next_count += 1
        else:
            # closes the dialogue
            self.accept()

    @Slot(bool)
    def _set_disabled(self, disable: bool) -> None:
        self.setDisabled(disable)

    @Slot(str, int)
    def _update_fake_status_bar(self, msg: str, _timer: int) -> None:
        self.fake_status_bar.setText(msg)

    @Slot()
    def _clear_fake_status_bar(self) -> None:
        self.fake_status_bar.clear()
