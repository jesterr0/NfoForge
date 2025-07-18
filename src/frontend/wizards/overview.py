from collections.abc import Iterable
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)
from pymediainfo import MediaInfo

from src.backend.template_selector import TemplateSelectorBackEnd
from src.backend.token_replacer import TokenReplacer
from src.config.config import Config
from src.frontend.custom_widgets.basic_code_editor import CodeEditor
from src.frontend.custom_widgets.file_tree import FileSystemTreeView
from src.frontend.custom_widgets.image_listbox import ThumbnailListWidget
from src.frontend.utils import recursively_clear_layout
from src.frontend.wizards.wizard_base_page import BaseWizardPage

if TYPE_CHECKING:
    from src.frontend.windows.main_window import MainWindow


class Overview(BaseWizardPage):
    def __init__(self, config: Config, parent: "MainWindow") -> None:
        super().__init__(config, parent)

        self.setObjectName("overviewPage")
        self.setTitle("Overview (Read Only)")
        self.setCommitPage(True)

        self.config = config

        media_input, self.media_input_box = self.build_form_layout("Input")
        renamed_output, self.renamed_output_box = self.build_form_layout("Output")
        self.renamed_media_box = self.build_group_box(
            "Media Rename", media_input, renamed_output
        )

        self.tracker_list_box = QListWidget()
        self.tracker_list_box.setFrameShape(QFrame.Shape.Box)
        self.tracker_list_box.setFrameShadow(QFrame.Shadow.Sunken)
        self.tracker_list_box.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.tracker_list_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        trackers_box = self.build_group_box("Tracker(s)", self.tracker_list_box)

        self.file_tree_view = FileSystemTreeView()
        self.file_tree_view.setSelectionMode(
            self.file_tree_view.SelectionMode.NoSelection
        )
        self.file_tree_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.file_tree_view.setMinimumHeight(180)
        file_box = self.build_group_box("File(s)", self.file_tree_view)

        self.nfo_box = QGroupBox("NFO(s)")
        self.nfo_box_layout = QVBoxLayout(self.nfo_box)

        self.thumbnail_listbox = ThumbnailListWidget()
        self.thumbnail_listbox.setFrameShape(QFrame.Shape.Box)
        self.thumbnail_listbox.setFrameShadow(QFrame.Shadow.Sunken)
        self.thumbnail_listbox.setMinimumHeight(300)
        self.image_box = self.build_group_box("Images", self.thumbnail_listbox)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.addWidget(self.renamed_media_box)
        content_layout.addWidget(trackers_box)
        content_layout.addWidget(file_box)
        content_layout.addWidget(self.nfo_box)
        content_layout.addWidget(self.image_box)
        content_layout.addSpacerItem(
            QSpacerItem(
                20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
            )
        )

        self.main_scroll_area = QScrollArea(self)
        self.main_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.main_scroll_area.setWidgetResizable(True)
        self.main_scroll_area.setWidget(content_widget)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.main_scroll_area)
        self.setLayout(main_layout)

    def initializePage(self) -> None:
        payload = self.config.media_input_payload
        media_in = payload.encode_file
        source_in = payload.source_file
        media_file_dir = None
        renamed_out = payload.renamed_file
        media_info_obj = payload.encode_file_mi_obj
        source_file_mi_obj = payload.source_file_mi_obj

        # sort the trackers in the users desired order before displaying them
        if self.config.shared_data.selected_trackers:
            self.tracker_list_box.addItems(
                [
                    str(x)
                    for x in sorted(
                        self.config.shared_data.selected_trackers,
                        key=lambda tracker: self.config.cfg_payload.tracker_order.index(
                            tracker
                        ),
                    )
                ]
            )

        self.media_input_box.setText(str(media_in))

        self._update_renamed_media_box(renamed_out)

        self._populate_file_view(media_file_dir if media_file_dir else media_in)

        self._update_nfo_text(
            media_input=media_in,
            source_file=source_in,
            media_info_obj=media_info_obj,
            source_file_mi_obj=source_file_mi_obj,
        )

        self._update_thumbnails()

    def _update_renamed_media_box(
        self, renamed_output: PathLike[str] | Path | None
    ) -> None:
        if renamed_output:
            self.renamed_media_box.show()
            self.renamed_output_box.setText(str(renamed_output))
        else:
            self.renamed_media_box.hide()

    def _populate_file_view(self, path: Path | None) -> None:
        if path:
            self.file_tree_view.build_tree(path)
            self.file_tree_view.show()
        else:
            self.file_tree_view.hide()

    def _update_nfo_text(
        self,
        media_input: PathLike[str] | Path,
        source_file: PathLike[str] | Path | None,
        media_info_obj: MediaInfo,
        source_file_mi_obj: MediaInfo | None,
    ) -> None:
        template_selector_backend = TemplateSelectorBackEnd()
        template_selector_backend.load_templates()

        if not self.config.shared_data.selected_trackers:
            self.nfo_box.hide()
        elif self.config.shared_data.selected_trackers and not self.nfo_box.isVisible():
            self.nfo_box.show()

        if self.config.shared_data.selected_trackers:
            for tracker in self.config.shared_data.selected_trackers:
                template = self.config.tracker_map[tracker].nfo_template
                nfo = ""
                nfo_template = template_selector_backend.read_template(template)
                if nfo_template:
                    # TODO: user_tokens should really be cached, we'll deal with this when we remove/rework overview page?
                    user_tokens = {
                        k: v
                        for k, (v, _) in self.config.cfg_payload.user_tokens.items()
                    }
                    token_replacer = TokenReplacer(
                        media_input=media_input,
                        jinja_engine=self.config.jinja_engine,
                        source_file=source_file,
                        token_string=nfo_template,
                        media_search_obj=self.config.media_search_payload,
                        media_info_obj=media_info_obj,
                        source_file_mi_obj=source_file_mi_obj,
                        releasers_name=self.config.cfg_payload.releasers_name,
                        dummy_screen_shots=True
                        if self.config.shared_data.url_data
                        or self.config.shared_data.loaded_images
                        else False,
                        release_notes=self.config.shared_data.release_notes,
                        edition_override=self.config.shared_data.dynamic_data.get(
                            "edition_override"
                        ),
                        frame_size_override=self.config.shared_data.dynamic_data.get(
                            "frame_size_override"
                        ),
                        override_tokens=self.config.shared_data.dynamic_data.get(
                            "override_tokens"
                        ),
                        user_tokens=user_tokens,
                        movie_clean_title_rules=self.config.cfg_payload.mvr_clean_title_rules,
                        mi_video_dynamic_range=self.config.cfg_payload.mvr_mi_video_dynamic_range,
                    ).get_output()
                    if token_replacer:
                        nfo = token_replacer
                        if not isinstance(nfo, str):
                            raise ValueError("NFO should be a string")

                    try:
                        token_replacer_plugin = self.config.cfg_payload.token_replacer
                        if token_replacer_plugin:
                            plugin = self.config.loaded_plugins[
                                token_replacer_plugin
                            ].token_replacer
                            if plugin and callable(plugin):
                                replace_tokens = plugin(
                                    config=self.config,
                                    input_str=nfo,
                                    tracker_s=(tracker,),
                                )
                                nfo = replace_tokens if replace_tokens else nfo
                    except Exception:
                        # we attempt to execute the plugin, but since some data is filled in process step
                        # it might not be available.
                        pass

                    nfo_widget = self._build_nfo_widget()
                    nfo_widget.setPlainText(nfo)
                    self.nfo_box_layout.addWidget(QLabel(str(tracker)))
                    self.nfo_box_layout.addWidget(nfo_widget)

    def _update_thumbnails(self) -> None:
        if self.config.shared_data.loaded_images:
            self.image_box.show()
            for img in self.config.shared_data.loaded_images:
                self.thumbnail_listbox.add_thumbnail(img)
        else:
            self.image_box.hide()

    @Slot()
    def reset_page(self) -> None:
        self.tracker_list_box.clear()
        self.file_tree_view.clear_tree()
        recursively_clear_layout(self.nfo_box_layout)
        self.thumbnail_listbox.clear()
        self.main_scroll_area.verticalScrollBar().setValue(
            self.main_scroll_area.verticalScrollBar().minimum()
        )

    @staticmethod
    def build_form_layout(txt1: str) -> tuple[QFormLayout, QLineEdit]:
        layout = QFormLayout()
        layout.addWidget(QLabel(txt1))
        text_box = QLineEdit()
        text_box.setReadOnly(True)
        layout.addWidget(text_box)
        return layout, text_box

    @staticmethod
    def build_group_box(text: str, *args: QWidget) -> QGroupBox:
        box = QGroupBox(text)
        box_layout = QVBoxLayout(box)

        def add_to_layout(item):
            if isinstance(item, QWidget):
                box_layout.addWidget(item)
            elif isinstance(item, QFormLayout):
                box_layout.addLayout(item)
            elif isinstance(item, Iterable):
                for sub_item in item:
                    add_to_layout(sub_item)

        for item in args:
            add_to_layout(item)

        return box

    @staticmethod
    def _build_nfo_widget() -> CodeEditor:
        nfo_widget = CodeEditor(line_numbers=False, wrap_text=False, mono_font=True)
        nfo_widget.setReadOnly(True)
        nfo_widget.setMinimumHeight(400)
        return nfo_widget
