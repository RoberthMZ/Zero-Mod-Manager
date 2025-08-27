import sys
import os
import json
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QComboBox, QCheckBox, QPushButton, QGroupBox, QSpacerItem, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QObject

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

import sys
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QComboBox, 
                             QCheckBox, QGroupBox)
from PyQt6.QtCore import pyqtSignal

from translation import Translator 

class SettingsTab(QWidget):
    particle_animation_toggled = pyqtSignal(bool)
    language_changed = pyqtSignal(str) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        if self.main_window and hasattr(self.main_window, 'translator'):
            self.translator = self.main_window.translator
        else:
            self.translator = Translator()
            
        self.setObjectName("SettingsTab")
        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        self.language_group = QGroupBox()
        self.language_group.setObjectName("SettingsGroup")
        language_layout = QVBoxLayout(self.language_group)

        self.lang_label = QLabel() 
        self.lang_label.setObjectName("SettingsLabel")
        language_layout.addWidget(self.lang_label)

        self.language_combo_box = QComboBox()
        self.language_combo_box.currentIndexChanged.connect(self._on_language_changed)
        language_layout.addWidget(self.language_combo_box)
        main_layout.addWidget(self.language_group)

        self.animation_group = QGroupBox() 
        self.animation_group.setObjectName("SettingsGroup")
        animation_layout = QVBoxLayout(self.animation_group)

        self.animation_label = QLabel() 
        self.animation_label.setObjectName("SettingsLabel")
        self.animation_label.setWordWrap(True)
        animation_layout.addWidget(self.animation_label)

        self.particle_animation_checkbox = QCheckBox() 
        self.particle_animation_checkbox.setObjectName("SettingsCheckBox")
        self.particle_animation_checkbox.toggled.connect(self._on_particle_animation_toggled)
        animation_layout.addWidget(self.particle_animation_checkbox)
        main_layout.addWidget(self.animation_group)

        main_layout.addStretch(1)
        
        self.retranslate_ui()

    def retranslate_ui(self):
        t = self.translator.get
        
        self.language_group.setTitle(t("settings.language_section_title"))
        self.lang_label.setText(t("settings.language_label"))
        
        self.animation_group.setTitle(t("settings.animation_section_title"))
        self.animation_label.setText(t("settings.animation_label"))
        self.particle_animation_checkbox.setText(t("settings.animation_checkbox"))

        self.language_combo_box.blockSignals(True)
        current_code = self.language_combo_box.currentData()
        self.language_combo_box.clear()
        
        available_languages = self.translator.get_available_languages()
        for code, name in available_languages.items():
            self.language_combo_box.addItem(name, code)
        
        index_to_set = self.language_combo_box.findData(current_code)
        if index_to_set != -1:
            self.language_combo_box.setCurrentIndex(index_to_set)

        self.language_combo_box.blockSignals(False)


    def load_settings(self):
        if self.main_window and hasattr(self.main_window, 'config'):
            config = self.main_window.config

            current_lang_code = config.get("language", "en")
            index = self.language_combo_box.findData(current_lang_code)
            if index != -1:
                self.language_combo_box.setCurrentIndex(index)
            
            particle_enabled = config.get("particle_animation_enabled", False)
            self.particle_animation_checkbox.setChecked(particle_enabled)

    def _on_language_changed(self, index):
        if index == -1: return
        
        selected_lang_code = self.language_combo_box.itemData(index)
        if self.main_window and hasattr(self.main_window, 'config'):
            if self.main_window.config.get("language") != selected_lang_code:
                self.main_window.config["language"] = selected_lang_code
                self.main_window.save_config()
                self.language_changed.emit(selected_lang_code)

    def _on_particle_animation_toggled(self, checked):
        self.particle_animation_toggled.emit(checked)