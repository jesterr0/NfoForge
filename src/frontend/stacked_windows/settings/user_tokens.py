from PySide6.QtCore import Slot
from PySide6.QtWidgets import QLabel

from src.backend.tokens import TokenSelection
from src.frontend.custom_widgets.custom_token_editor import CustomTokenEditor
from src.frontend.global_signals import GSigs
from src.frontend.stacked_windows.settings.base import BaseSettings


class UserTokenSettings(BaseSettings):
    def __init__(self, config, main_window, parent) -> None:
        super().__init__(config=config, main_window=main_window, parent=parent)
        self.setObjectName("userTokenSettings")

        self.load_saved_settings.connect(self._load_saved_settings)
        self.update_saved_settings.connect(self._save_settings)

        desc = QLabel(
            """\
            <span>
                <span style="font-weight: 500;">Token:</span>
                <ul style="margin: 0; padding-left: 20px;">
                    <li style="margin-top: 4px;">User tokens <span style ="font-weight: 500;">must</span> be prefixed with <span style ="font-weight: 500;">usr_</span> and <span style ="font-weight: 500;">lowercase</span>.</li>
                    <li>Only the <span style ="font-weight: 500;">last duplicate token</span> will be saved if there are multiple <span style ="font-weight: 500;">duplicate</span> tokens.</li>
                </ul>
                <span style="font-weight: 500;">Type:</span>
                <ul style="margin: 0; padding-left: 20px;">
                    <li style="margin-top: 4px;"><span style ="font-weight: 500;">FileToken:</span> accepts a <span style ="font-weight: 500;">single</span> line of input and is used in filenames.</li>
                    <li>
                        <span style ="font-weight: 500;">NfoToken:</span> accepts <span style ="font-weight: 500;">multi-line</span> input and is used in NFOs (<span style="font-style: italic; font-size: small;">FileTokens are also accepted in NFOs</span>).
                    </li>
                </ul>
            <span>""",
            wordWrap=True,
            parent=self,
        )

        self.token_editor = CustomTokenEditor(
            token_types=[x for x in TokenSelection], parent=self
        )
        self.token_editor.save_changes_now.connect(self._update_changes_now)

        self.add_widget(desc)
        self.add_widget(self.token_editor, stretch=10)
        self.add_layout(self.reset_layout, add_stretch=True)

        self._load_saved_settings()

    @Slot(object)
    def _update_changes_now(self, data: dict[str, tuple[str, str]]) -> None:
        self.config.cfg_payload.user_tokens = data
        self.config.save_config()
        GSigs().token_state_changed.emit()

    @Slot()
    def _load_saved_settings(self) -> None:
        if self.config.cfg_payload.user_tokens:
            self.token_editor.blockSignals(True)
            self.token_editor.load_tokens(self.config.cfg_payload.user_tokens)
            self.token_editor.blockSignals(False)

    @Slot()
    def _save_settings(self) -> None:
        saved_tokens = self.token_editor.save_all()
        if saved_tokens is not None:
            self.config.cfg_payload.user_tokens = saved_tokens
            self.updated_settings_applied.emit()

    def apply_defaults(self) -> None:
        self.token_editor.reset()
