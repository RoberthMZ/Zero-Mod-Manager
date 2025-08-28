import sys
import os
import json
import shutil
import re
import patoolib
import random
import time
import threading
import requests
import locale
import zipfile
import subprocess
import psutil

try:
    import winreg
except ImportError:
    winreg = None

from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget,
                             QLabel, QHBoxLayout, QListWidget, QListWidgetItem,
                             QMessageBox, QFileDialog, QFrame, QStatusBar, QTabWidget,
                             QSpacerItem, QSizePolicy, QComboBox, QInputDialog, QStackedWidget,
                             QDialog, QScrollArea, QCheckBox, QGridLayout, QLineEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QUrl, QThread, QEventLoop, QPointF, QSize, QEvent
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFontMetrics, QDesktopServices, QIcon, QPen

from translation import Translator
from download_tab import DownloadTab, format_timestamp, FileSelectionDialog
from settings_tab import SettingsTab
from info_tab import InfoTab

SPARKING_ZERO_STEAM_APPID = "1790600"
CONFIG_FILE = "config.json"
MODS_DIR = "mods" 
DOWNLOADS_DIR = "downloads"
ACTIVE_MODS_BACKUP_DIR = "active_mods_backup"
MODPACKS_DATA_DIR = "modpacks_data" 
MODPACKS_LIBRARY_DIR = "modpacks_library"
MOD_IMAGES_DIR = "mod_images"
NUM_STARS = 350
ANIMATION_INTERVAL = 12

POWER_BUTTON_INACTIVE_STYLE = """
#PowerButton {
    font-size: 16px; font-weight: bold; padding: 12px 24px; border-radius: 22px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a2a5a, stop:1 #2a1a4a);
    color: #e0d8f0; min-width: 250px; border: 2px solid #4a3a6a;
}
#PowerButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4a3a6a, stop:1 #3a2a5a);
    color: #fff; border-color: #6a5a8a;
}
"""
POWER_BUTTON_ACTIVE_STYLE = """
#PowerButton {
    font-size: 16px; font-weight: bold; padding: 12px 24px; border-radius: 22px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffc900, stop:1 #ff8c00);
    color: #000000; min-width: 250px; border: 2px solid #ffc900;
}
"""

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

check_image_path = resource_path("img/check.png").replace('\\', '/') 

_original_popen = subprocess.Popen

class _PopenWrapper(object):

    def __init__(self, *args, **kwargs):
        if sys.platform == "win32":
            startupinfo = kwargs.get('startupinfo')
            if startupinfo is None:
                startupinfo = subprocess.STARTUPINFO()
            
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs['startupinfo'] = startupinfo

            creationflags = kwargs.get('creationflags', 0)
            creationflags |= subprocess.CREATE_NO_WINDOW
            kwargs['creationflags'] = creationflags

        self._process = _original_popen(*args, **kwargs)

    def __enter__(self):
        return self._process.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._process.__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name):
        return getattr(self._process, name)
    
class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class ModStatusIndicator(QLabel):
    def __init__(self, is_active=False):
        super().__init__()
        self.setFixedSize(20, 20)
        self.set_status(is_active)

    def set_status(self, is_active):
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        color = QColor("#00d1c1") if is_active else QColor("#5a5a5a")
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 20, 20)
        painter.end()
        self.setPixmap(pixmap)

class ElidedLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.original_text = text

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        elided_text = metrics.elidedText(self.original_text, Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), self.alignment(), elided_text)

class UpdateWorkerSignals(QObject):
    update_status_bar = pyqtSignal(str, int)
    show_message_box = pyqtSignal(str, str, int)
    enable_main_update_button = pyqtSignal(bool)
    set_cursor = pyqtSignal(Qt.CursorShape)
    update_process_finished = pyqtSignal(str)

class ImageLoaderSignals(QObject):
    image_loaded = pyqtSignal(QLabel, QPixmap)
    image_error = pyqtSignal(QLabel)

class ModUpdateUISignals(QObject):
    update_mod_details_status = pyqtSignal(str)

class UpdateFileSelectionHandler(QObject):
    show_dialog_request = pyqtSignal(list, object)

    def show_dialog(self, files_data, result_list_holder):
        dialog = FileSelectionDialog(files_data, parent=None)
        if dialog.exec() == dialog.DialogCode.Accepted:
            result_list_holder.append(dialog.selected_file_info)
        else:
            result_list_holder.append(None)

class ModpackCreationDialog(QDialog):
    def __init__(self, available_mods_data, translator, parent=None, modpack_data=None):
        super().__init__(parent)
        self.translator = translator
        self.setWindowTitle(translator.get("modpack_dialog_create_title") if modpack_data is None else translator.get("modpack_dialog_edit_title"))
        self.setMinimumSize(550, 700)

        self.default_image_path = resource_path("img/icon_pack.png")

        self.layout = QVBoxLayout(self)

        self.name_label = QLabel(translator.get("modpack_dialog_name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(translator.get("modpack_dialog_name_placeholder"))
        
        self.author_label = QLabel(translator.get("modpack_dialog_author"))
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText(translator.get("modpack_dialog_author_placeholder"))

        self.image_preview_title_label = QLabel(translator.get("modpack_dialog_image_preview"))
        self.image_preview_label = QLabel()
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setFixedSize(250, 150)
        self.image_preview_label.setObjectName("ModpackImagePreview")
        self.image_path_label = QLabel(translator.get("modpack_dialog_no_image_selected"))
        self.image_path_label.setStyleSheet("font-style: italic; color: #999;")
        
        self.image_path = None 
        
        self.select_image_button = QPushButton(translator.get("modpack_dialog_select_image"))
        self.select_image_button.clicked.connect(self.select_image)

        self.mod_list_label = QLabel(translator.get("modpack_dialog_select_mods"))
        
        selection_buttons_layout = QHBoxLayout()
        self.select_all_button = QPushButton(translator.get("modpack_dialog_select_all"))
        self.select_all_button.clicked.connect(self.select_all_mods)
        self.deselect_all_button = QPushButton(translator.get("modpack_dialog_deselect_all"))
        self.deselect_all_button.clicked.connect(self.deselect_all_mods)
        selection_buttons_layout.addWidget(self.select_all_button)
        selection_buttons_layout.addWidget(self.deselect_all_button)
        selection_buttons_layout.addStretch()

        self.mod_list_widget = QListWidget()
        selected_mods_folders = [mod.get("folder_name") for mod in modpack_data.get("mods", [])] if modpack_data else []
        
        for folder_name, display_name in sorted(available_mods_data.items(), key=lambda item: item[1]):
            item = QListWidgetItem(display_name, self.mod_list_widget)
            item.setData(Qt.ItemDataRole.UserRole, folder_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            is_checked = folder_name in selected_mods_folders
            item.setCheckState(Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)

        self.save_button = QPushButton(translator.get("btn_save"))
        self.save_button.clicked.connect(self.accept)

        self.layout.addWidget(self.name_label)
        self.layout.addWidget(self.name_edit)
        self.layout.addWidget(self.author_label)
        self.layout.addWidget(self.author_edit)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.image_preview_title_label)
        self.layout.addWidget(self.image_preview_label, 0, Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.image_path_label)
        self.layout.addWidget(self.select_image_button)
        self.layout.addSpacing(10)
        self.layout.addWidget(self.mod_list_label)
        self.layout.addLayout(selection_buttons_layout)
        self.layout.addWidget(self.mod_list_widget)
        self.layout.addStretch()
        self.layout.addWidget(self.save_button)
        
        if modpack_data:
            self.name_edit.setText(modpack_data.get("name", ""))
            self.author_edit.setText(modpack_data.get("author", ""))
            
            image_from_data = modpack_data.get("image", None)
            if image_from_data and os.path.exists(image_from_data):
                self.image_path = image_from_data
                self.image_path_label.setText(os.path.basename(self.image_path))
            else:
                self.image_path = self.default_image_path
                self.image_path_label.setText(translator.get("modpack_dialog_no_image_selected"))
        else:
            self.image_path = self.default_image_path
            self.image_path_label.setText(translator.get("modpack_dialog_no_image_selected"))

        self.update_image_preview()

    def select_all_mods(self):
        for i in range(self.mod_list_widget.count()):
            self.mod_list_widget.item(i).setCheckState(Qt.CheckState.Checked)

    def deselect_all_mods(self):
        for i in range(self.mod_list_widget.count()):
            self.mod_list_widget.item(i).setCheckState(Qt.CheckState.Unchecked)
            
    def update_image_preview(self):
        if self.image_path and os.path.exists(self.image_path):
            pixmap = QPixmap(self.image_path)
            scaled_pixmap = pixmap.scaled(self.image_preview_label.size(), 
                                          Qt.AspectRatioMode.KeepAspectRatio, 
                                          Qt.TransformationMode.SmoothTransformation)
            self.image_preview_label.setPixmap(scaled_pixmap)
        else:
            self.image_preview_label.clear()

    def select_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.get("modpack_dialog_select_image_title"), "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            self.image_path = file_path
            self.image_path_label.setText(os.path.basename(file_path))
            self.update_image_preview()

    def get_data(self):
        selected_mods = []
        for i in range(self.mod_list_widget.count()):
            item = self.mod_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                folder_name = item.data(Qt.ItemDataRole.UserRole)
                selected_mods.append(folder_name)
        
        image_to_save = self.image_path if self.image_path != self.default_image_path else None
                
        return {
            "name": self.name_edit.text(),
            "author": self.author_edit.text(),
            "image": image_to_save,
            "mods": selected_mods
        }

class ZeroManager(QMainWindow):
    update_mod_details_ui_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.resize(1370, 900)
        self._is_first_show = True
        self.game_path_is_valid = False
        self.is_applying_profile = False
        self.translator = Translator()
        self.image_loader_signals = ImageLoaderSignals()
        self.image_loader_signals.image_loaded.connect(self._set_detail_image)
        self.image_loader_signals.image_error.connect(self._set_detail_image_error)
        self.mod_update_ui_signals = ModUpdateUISignals()
        self.mod_update_ui_signals.update_mod_details_status.connect(self._update_mod_details_ui_slot)
        self.update_mod_details_ui_signal.connect(self._update_mod_details_ui_slot)
        self.update_worker_signals = UpdateWorkerSignals()
        self.update_worker_signals.update_status_bar.connect(self.statusBar().showMessage)
        self.update_worker_signals.show_message_box.connect(self._show_message_box_slot)
        self.update_worker_signals.enable_main_update_button.connect(self._set_main_update_button_enabled_slot)
        self.update_worker_signals.set_cursor.connect(QApplication.setOverrideCursor)
        self.update_worker_signals.update_process_finished.connect(self._on_update_process_finished)
        self.update_file_selection_handler = UpdateFileSelectionHandler()
        self.update_file_selection_handler.show_dialog_request.connect(self.update_file_selection_handler.show_dialog)
        
        self.current_mod_for_update = None
        self.timer = None
        self.setup_ui()
        self.load_config_and_init()
        try:
            check_image_path = resource_path("img/check.png").replace('\\', '/')

            css_file_path = resource_path("style.css")
            with open(css_file_path, "r", encoding='utf-8') as f:
                stylesheet_template = f.read()

            processed_stylesheet = stylesheet_template.replace('%%CHECK_IMAGE_PATH%%', check_image_path)

            self.setStyleSheet(processed_stylesheet)

        except FileNotFoundError:
            print("ADVERTENCIA: No se encontró el archivo style.css en la ruta esperada.")
        except Exception as e:
            print(f"ERROR: Ocurrió un problema al cargar la hoja de estilos: {e}")
        self.update_power_button_style(self.modding_power_button.isChecked())
        self.display_mod_details(None, None)

    def _show_message_box_slot(self, title, message, icon_int):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Icon(icon_int))
        msg_box.exec()

    def center_and_adjust(self):
        screen_geo = QApplication.primaryScreen().availableGeometry()
        window_size = self.size()
        new_width = min(window_size.width(), screen_geo.width())
        new_height = min(window_size.height(), screen_geo.height())
        self.resize(new_width, new_height)
        window_frame = self.frameGeometry()
        screen_center = screen_geo.center()
        window_frame.moveCenter(screen_center)
        self.move(window_frame.topLeft())

    def showEvent(self, event):
        super().showEvent(event)
        if self._is_first_show:
            self.center_and_adjust()
            self._is_first_show = False

    def _set_main_update_button_enabled_slot(self, enabled):
        self.update_mods_button.setEnabled(enabled)
        if self.current_mod_for_update:
            self.update_mod_details_ui_signal.emit(self.current_mod_for_update)

    def _on_update_process_finished(self, mod_name_affected):
        self.update_worker_signals.set_cursor.emit(Qt.CursorShape.ArrowCursor)
        self.update_worker_signals.enable_main_update_button.emit(True)
        if mod_name_affected:
            self.update_mod_details_ui_signal.emit(mod_name_affected)
        self.update_ui_state()

    def setup_particle_background(self):
        if self.timer and self.timer.isActive(): self.timer.stop()
        if self.config.get("particle_animation_enabled", False):
            self.stars = []
            center_x, center_y = self.width() / 2, self.height() / 2
            for _ in range(NUM_STARS):
                self.stars.append({'x': center_x, 'y': center_y, 'vx': random.uniform(-1, 1), 'vy': random.uniform(-1, 1), 'speed': random.uniform(2.0, 8.0), 'radius': random.uniform(0.5, 2.5), 'alpha': random.randint(50, 200)})
                if self.stars[-1]['vx'] == 0 and self.stars[-1]['vy'] == 0: self.stars[-1]['vx'] = random.choice([-1, 1])
            if not self.timer:
                self.timer = QTimer(self)
                self.timer.timeout.connect(self.update_stars)
            self.timer.start(ANIMATION_INTERVAL)
        else: self.stars = []
        self.update()

    def update_stars(self):
        center_x, center_y = self.width() / 2, self.height() / 2
        for star in self.stars:
            star['x'] += star['vx'] * star['speed']
            star['y'] += star['vy'] * star['speed']
            if (star['x'] < 0 or star['x'] > self.width() or star['y'] < 0 or star['y'] > self.height()):
                star.update({'x': center_x, 'y': center_y, 'vx': random.uniform(-1, 1), 'vy': random.uniform(-1, 1), 'speed': random.uniform(2.0, 8.0), 'radius': random.uniform(0.5, 2.5), 'alpha': random.randint(50, 200)})
                if star['vx'] == 0 and star['vy'] == 0: star['vx'] = random.choice([-1, 1])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0a0515"))
        if self.config.get("particle_animation_enabled", False):
            base_color = QColor(255, 230, 80) if self.modding_power_button.isChecked() else QColor(140, 160, 190)
            for star in self.stars:
                color = QColor(base_color)
                color.setAlpha(star['alpha'])
                pen = QPen(color)
                pen.setWidthF(star['radius'])
                painter.setPen(pen)
                end_x = star['x'] + star['vx'] * star['speed']
                end_y = star['y'] + star['vy'] * star['speed']
                painter.drawLine(QPointF(star['x'], star['y']), QPointF(end_x, end_y))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setup_particle_background()

    def update_power_button_style(self, checked):
        self.modding_power_button.setStyleSheet(POWER_BUTTON_ACTIVE_STYLE if checked else POWER_BUTTON_INACTIVE_STYLE)

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_widget.setStyleSheet("background: transparent;")
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        header_frame = QFrame()
        header_frame.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header_frame)
        self.title_label = QLabel("ZERO Mod Manager")
        self.title_label.setObjectName("TitleLabel")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        self.modding_power_button = QPushButton("MODO TRANSFORMACIÓN")
        self.modding_power_button.installEventFilter(self)
        self.modding_power_button.setObjectName("PowerButton")
        self.modding_power_button.setCheckable(True)
        self.modding_power_button.toggled.connect(self.update_power_button_style)
        self.modding_power_button.toggled.connect(self.manage_bypass)
        header_layout.addWidget(self.modding_power_button)
        main_layout.addWidget(header_frame)
        path_frame = QFrame()
        path_frame.setObjectName("PathFrame")
        path_layout = QHBoxLayout(path_frame)
        self.game_path_label = QLabel("...")
        self.game_path_label.setObjectName("PathLabel")
        path_layout.addWidget(self.game_path_label, 1)
        self.change_path_button = QPushButton("...")
        self.change_path_button.setObjectName("ChangePathButton")
        self.change_path_button.clicked.connect(self.change_game_path)
        path_layout.addWidget(self.change_path_button)
        main_layout.addWidget(path_frame)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        main_layout.addWidget(self.tabs)
        self.home_tab_widget = QWidget()
        self.home_tab_widget.setStyleSheet("background: transparent;")
        home_tab_layout = QVBoxLayout(self.home_tab_widget)
        home_tab_layout.setContentsMargins(0,0,0,0)
        self.home_stack = QStackedWidget()
        home_tab_layout.addWidget(self.home_stack)
        self.profile_view_widget = self.setup_profile_view_ui()
        self.home_stack.addWidget(self.profile_view_widget)
        self.modpack_view_widget = self.setup_modpack_view_ui()
        self.home_stack.addWidget(self.modpack_view_widget)
        self.tabs.addTab(self.home_tab_widget, "...")
        self.download_tab = DownloadTab(translator=self.translator)
        self.download_tab.mod_downloaded.connect(self.install_mod_from_path)
        self.tabs.addTab(self.download_tab, "...")
        self.settings_tab = SettingsTab(self)
        self.settings_tab.particle_animation_toggled.connect(self._handle_particle_animation_toggle)
        self.settings_tab.language_changed.connect(self._on_language_changed)
        self.tabs.addTab(self.settings_tab, "...")
        self.info_tab = InfoTab(self)
        info_icon_path = resource_path("img/info_icon.png")
        if os.path.exists(info_icon_path):
            self.tabs.addTab(self.info_tab, QIcon(info_icon_path), "")
        else:
            self.tabs.addTab(self.info_tab, "Info")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.setStatusBar(QStatusBar(self))
        self.statusBar().setStyleSheet("font-style: italic; color: #a090c0;")

    def setup_profile_view_ui(self):
        view_widget = QWidget()
        view_widget.setStyleSheet("background: transparent;")
        main_layout = QHBoxLayout(view_widget)
        mod_list_column_layout = QVBoxLayout()
        top_panel_frame = QFrame()
        top_panel_layout = QHBoxLayout(top_panel_frame)
        top_panel_layout.setContentsMargins(0,0,0,0)
        profile_frame = QFrame()
        profile_frame.setObjectName("ProfileManagerFrame")
        profile_layout = QHBoxLayout(profile_frame)
        profile_layout.setContentsMargins(15, 10, 15, 10)
        profile_layout.setSpacing(10)
        self.profile_label = QLabel("...")
        self.profile_label.setObjectName("ProfileLabel")
        self.profile_combo_box = QComboBox()
        self.profile_combo_box.currentIndexChanged.connect(self.change_profile)
        self.add_profile_button = QPushButton("...")
        self.add_profile_button.clicked.connect(self.add_profile)
        self.delete_profile_button = QPushButton("...")
        self.delete_profile_button.clicked.connect(self.delete_profile)
        profile_layout.addWidget(self.profile_label)
        profile_layout.addWidget(self.profile_combo_box, 1)
        profile_layout.addWidget(self.add_profile_button)
        profile_layout.addWidget(self.delete_profile_button)
        top_panel_layout.addWidget(profile_frame, 1)
        self.switch_to_modpacks_button = QPushButton()
        self.switch_to_modpacks_button.setObjectName("ModeSwitchButton")
        self.switch_to_modpacks_button.clicked.connect(self.switch_view_mode)
        profile_layout.addWidget(self.switch_to_modpacks_button)
        mod_list_column_layout.addWidget(top_panel_frame)
        self.mod_list = QListWidget()
        self.mod_list.setObjectName("ModList")
        self.mod_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mod_list.currentItemChanged.connect(self.display_mod_details)
        mod_list_column_layout.addWidget(self.mod_list)
        home_controls_frame = QFrame()
        home_controls_frame.setStyleSheet("background: transparent;")
        home_controls_layout = QHBoxLayout(home_controls_frame)
        home_controls_layout.setContentsMargins(15, 10, 15, 10)
        self.toggle_all_button = QPushButton("...")
        self.toggle_all_button.clicked.connect(lambda: self.toggle_all_mods(True))
        home_controls_layout.addWidget(self.toggle_all_button)
        self.disable_all_button = QPushButton("...")
        self.disable_all_button.clicked.connect(lambda: self.toggle_all_mods(False))
        home_controls_layout.addWidget(self.disable_all_button)
        home_controls_layout.addStretch()
        self.manual_install_button = QPushButton("...")
        self.manual_install_button.setObjectName("InstallButton")
        self.manual_install_button.clicked.connect(self.install_mod_manually)
        home_controls_layout.addWidget(self.manual_install_button)
        self.update_mods_button = QPushButton("...")
        self.update_mods_button.setObjectName("UpdateButton")
        self.update_mods_button.clicked.connect(self.check_for_mod_updates)
        home_controls_layout.addWidget(self.update_mods_button)
        mod_list_column_layout.addWidget(home_controls_frame)
        main_layout.addLayout(mod_list_column_layout, 2)
        self.mod_details_frame = QFrame()
        self.mod_details_frame.setObjectName("ModDetailsFrame")
        mod_details_layout = QVBoxLayout(self.mod_details_frame)
        mod_details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        mod_details_layout.setSpacing(15)
        self.mod_details_name_label = QLabel("...")
        self.mod_details_name_label.setObjectName("ModDetailName")
        self.mod_details_name_label.setWordWrap(True)
        mod_details_layout.addWidget(self.mod_details_name_label)
        self.mod_details_author_label = QLabel("")
        self.mod_details_author_label.setObjectName("ModDetailAuthor")
        mod_details_layout.addWidget(self.mod_details_author_label)
        self.mod_details_image_container = QFrame()
        self.mod_details_image_container.setObjectName("ModDetailImageContainer")
        image_container_layout = QVBoxLayout(self.mod_details_image_container)
        self.mod_details_image_label = ClickableLabel("...")
        self.mod_details_image_label.clicked.connect(self.on_manual_image_area_clicked)
        self.mod_details_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mod_details_image_label.setMinimumSize(300, 250)
        image_container_layout.addWidget(self.mod_details_image_label)
        mod_details_layout.addWidget(self.mod_details_image_container)
        self.mod_details_date_label = QLabel("")
        self.mod_details_date_label.setObjectName("ModDetailInfoLabel")
        mod_details_layout.addWidget(self.mod_details_date_label)
        self.mod_details_url_label = QLabel("")
        self.mod_details_url_label.setObjectName("ModDetailInfoLabel")
        self.mod_details_url_label.setOpenExternalLinks(True)
        mod_details_layout.addWidget(self.mod_details_url_label)
        mod_details_layout.addStretch(1)
        self.mod_details_update_status_label = QLabel("")
        self.mod_details_update_status_label.setObjectName("ModDetailUpdateStatus")
        self.mod_details_update_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mod_details_update_status_label.setWordWrap(True)
        mod_details_layout.addWidget(self.mod_details_update_status_label)
        self.update_single_mod_button = QPushButton("...")
        self.update_single_mod_button.setObjectName("UpdateModButton")
        self.update_single_mod_button.hide()
        mod_details_layout.addWidget(self.update_single_mod_button)
        main_layout.addWidget(self.mod_details_frame, 1)
        return view_widget

    def setup_modpack_view_ui(self):
        view_widget = QWidget()
        view_widget.setObjectName("ModpackViewWidget")
        main_layout = QVBoxLayout(view_widget)

        top_panel_frame = QFrame()
        top_panel_frame.setObjectName("ProfileManagerFrame")
        
        toolbar_layout = QHBoxLayout(top_panel_frame)
        toolbar_layout.setContentsMargins(15, 10, 15, 10) 
        toolbar_layout.setSpacing(10) 

        self.create_modpack_button = QPushButton()
        self.create_modpack_button.clicked.connect(self.create_modpack)
        self.import_modpack_button = QPushButton()
        self.import_modpack_button.clicked.connect(self.import_modpack)
        self.switch_to_profiles_button = QPushButton()
        self.switch_to_profiles_button.setObjectName("ModeSwitchButton")
        self.switch_to_profiles_button.clicked.connect(self.switch_view_mode)
        
        toolbar_layout.addWidget(self.create_modpack_button)
        toolbar_layout.addWidget(self.import_modpack_button)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.switch_to_profiles_button)

        main_layout.addWidget(top_panel_frame)
        
        content_layout = QHBoxLayout()
        main_layout.addLayout(content_layout, 1)
        modpack_list_container = QFrame()
        modpack_list_layout = QVBoxLayout(modpack_list_container)
        modpack_list_layout.setContentsMargins(10, 0, 10, 0)
        self.modpack_list_label = QLabel()
        self.modpack_list_label.setObjectName("ModpackListLabel")
        
        self.modpack_list = QListWidget()
        self.modpack_list.setObjectName("ModpackList")
        self.modpack_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.modpack_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.modpack_list.setMovement(QListWidget.Movement.Static)
        self.modpack_list.setUniformItemSizes(True)
        self.modpack_list.setGridSize(QSize(270, 270)) 
        self.modpack_list.setSpacing(0)
        
        self.modpack_list.currentItemChanged.connect(self.on_modpack_selected)
        modpack_list_layout.addWidget(self.modpack_list_label)
        modpack_list_layout.addWidget(self.modpack_list, 1)
        content_layout.addWidget(modpack_list_container, 2)
        mod_list_container = QFrame()
        mod_list_layout = QVBoxLayout(mod_list_container)
        self.modpack_mods_label = QLabel()
        self.modpack_mods_label.setObjectName("ModpackListLabel")
        self.modpack_mod_list = QListWidget()
        self.modpack_mod_list.setObjectName("ModpackModList")
        mod_list_layout.addWidget(self.modpack_mods_label)
        mod_list_layout.addWidget(self.modpack_mod_list, 1)
        content_layout.addWidget(mod_list_container, 1)
        return view_widget

    def _on_language_changed(self, lang_code):
        self.translator.load_language(lang_code)
        self.retranslate_ui()

    def retranslate_ui(self):
        t = self.translator.get
        self.setWindowTitle(t("app_title"))
        self.title_label.setText(t("app_title_header"))
        self.modding_power_button.setText(t("transformation_mode"))
        self.game_path_label.setText(t("finding_game_path"))
        self.change_path_button.setText(t("change_path"))
        self.tabs.setTabText(self.tabs.indexOf(self.home_tab_widget), t("tab_my_mods"))
        self.tabs.setTabText(self.tabs.indexOf(self.download_tab), t("tab_download_mods"))
        self.tabs.setTabText(self.tabs.indexOf(self.settings_tab), t("tab_settings"))
        info_tab_index = self.tabs.indexOf(self.info_tab)
        if self.tabs.tabIcon(info_tab_index).isNull(): self.tabs.setTabText(info_tab_index, t("tab_info"))
        self.tabs.setTabToolTip(info_tab_index, t("tab_info_tooltip"))
        self.profile_label.setText(t("profile_label"))
        self.add_profile_button.setText(t("profile_add"))
        self.delete_profile_button.setText(t("profile_delete"))
        self.toggle_all_button.setText(t("home_activate_all"))
        self.disable_all_button.setText(t("home_deactivate_all"))
        self.manual_install_button.setText(t("home_install_manual"))
        self.update_mods_button.setText(t("home_update_mods"))
        self.switch_to_modpacks_button.setText(t("switch_to_modpacks"))
        self.create_modpack_button.setText(t("modpack_create"))
        self.import_modpack_button.setText(t("modpack_import"))
        self.switch_to_profiles_button.setText(t("switch_to_profiles"))
        self.modpack_list_label.setText(t("modpack_list_title"))
        self.modpack_mods_label.setText(t("modpack_content_title"))
        self.update_single_mod_button.setText(t("details_update_this_mod"))
        self._clear_mod_details_ui()
        self.update_mod_list()
        self.populate_modpack_list()
        self.download_tab.retranslate_ui()
        self.settings_tab.retranslate_ui()
        self.info_tab.retranslate_ui()
        game_path = self.config.get("game_path")
        if game_path and self.game_path_is_valid: self.game_path_label.setText(f"{t('game_path_label')}: {game_path}")
        else: self.game_path_label.setText(t('game_path_not_set'))

    def on_tab_changed(self, index):
        if self.tabs.widget(index) == self.download_tab: self.download_tab.load_mods_if_needed()
        elif self.tabs.widget(index) == self.home_tab_widget:
            self.sync_mods_folder()
            if self.home_stack.currentIndex() == 0 and self.mod_list.currentItem():
                self.display_mod_details(self.mod_list.currentItem(), None)
        elif self.tabs.widget(index) == self.settings_tab: self.settings_tab.load_settings()

    def load_config_and_init(self):
        os.makedirs(MODS_DIR, exist_ok=True)
        os.makedirs(ACTIVE_MODS_BACKUP_DIR, exist_ok=True)
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        os.makedirs(MODPACKS_DATA_DIR, exist_ok=True)
        os.makedirs(MODPACKS_LIBRARY_DIR, exist_ok=True)
        os.makedirs(MOD_IMAGES_DIR, exist_ok=True)
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): self.config = {}
        lang_name_to_code = {"Español": "es", "English": "en", "Português": "pt"}
        saved_lang = self.config.get("language")
        target_lang_code = None
        if saved_lang:
            if saved_lang in self.translator.get_available_languages(): target_lang_code = saved_lang
            elif saved_lang in lang_name_to_code: target_lang_code = lang_name_to_code[saved_lang]
        if not target_lang_code:
            try:
                system_locale_str = locale.getlocale()[0]
                if system_locale_str:
                    locale_lower = system_locale_str.lower()
                    if 'spanish' in locale_lower or 'es_' in locale_lower: target_lang_code = 'es'
                    elif 'portuguese' in locale_lower or 'pt_' in locale_lower: target_lang_code = 'pt'
                    else: target_lang_code = 'en'
                else: raise ValueError("System locale returned None.")
            except Exception as e:
                print(f"No se pudo detectar el idioma del sistema, usando 'en' por defecto. Error: {e}")
                target_lang_code = 'en'
        self.translator.load_language(target_lang_code)
        self.config["language"] = self.translator.get_current_language_code()
        self.config.setdefault("mods", {})
        self.config.setdefault("bypass_active", False)
        self.config.setdefault("game_path", "")
        self.config.setdefault("profiles", {"Default": []})
        self.config.setdefault("current_profile", "Default")
        self.config.setdefault("particle_animation_enabled", False)
        self.config.setdefault("modpacks", {})
        self.config.setdefault("active_modpack", None)
        self.config.setdefault("mod_management_mode", "profiles")
        if "Default" not in self.config["profiles"]:
            self.config["profiles"]["Default"] = []
            self.config["current_profile"] = "Default"
        self.retranslate_ui()
        self.initialize_game_path()
        self.sync_mods_folder()
        self.load_profiles()
        self.populate_modpack_list()
        self.modding_power_button.setChecked(self.config.get("bypass_active", False))
        self.setup_particle_background()
        view_index = 1 if self.config.get("mod_management_mode") == "modpacks" else 0
        self.home_stack.setCurrentIndex(view_index)

        active_modpack_name = self.config.get("active_modpack")
        if active_modpack_name and self.config.get("mod_management_mode") == "modpacks":
            for i in range(self.modpack_list.count()):
                item = self.modpack_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == active_modpack_name:
                    self.modpack_list.setCurrentItem(item)
                    break 
        self.update_ui_state()
        self.save_config()

    def _handle_particle_animation_toggle(self, enabled):
        self.config["particle_animation_enabled"] = enabled
        self.save_config()
        self.setup_particle_background()
        self.update()

    def install_mod_manually(self):
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.get("dialog_select_mod_title"), "", f"{self.translator.get('dialog_compressed_files')} (*.zip *.rar *.7z)")
        if not file_path:
            return

        t = self.translator.get
        image_path = None
        reply = QMessageBox.question(self, t("dialog_add_image_title"), t("dialog_add_image_text"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            image_path, _ = QFileDialog.getOpenFileName(self, t("dialog_select_image_title"), "", "Images (*.png *.jpg *.jpeg)")

        mod_name_initial = os.path.splitext(os.path.basename(file_path))[0]
        self.install_mod_from_path(file_path, mod_name_initial, is_download=False, mod_gamebanana_info=None, manual_image_path=image_path)

    def install_mod_from_path(self, file_path, mod_name_initial, is_download=False, mod_gamebanana_info=None, manual_image_path=None):
        t = self.translator.get
        clean_mod_name = re.sub(r'[/:*?"<>|]', '', mod_name_initial)
        temp_extract_path = os.path.join(MODS_DIR, f"temp_{clean_mod_name}_{int(time.time())}")
        
        subprocess.Popen = _PopenWrapper

        try:
            self.update_worker_signals.update_status_bar.emit(t("status_extracting").format(mod_name=clean_mod_name), 5000)
            
            patoolib.extract_archive(file_path, outdir=temp_extract_path, verbosity=-1)

            items_in_temp = os.listdir(temp_extract_path)
            final_mod_name = clean_mod_name
            source_to_move = temp_extract_path
            if len(items_in_temp) == 1 and os.path.isdir(os.path.join(temp_extract_path, items_in_temp[0])):
                final_mod_name = items_in_temp[0]
                source_to_move = os.path.join(temp_extract_path, final_mod_name)
            elif len(items_in_temp) > 1 and any(os.path.isdir(os.path.join(temp_extract_path, item)) for item in items_in_temp):
                potential_mod_dirs = [d for d in items_in_temp if os.path.isdir(os.path.join(temp_extract_path, d))]
                if len(potential_mod_dirs) == 1:
                    final_mod_name = potential_mod_dirs[0]
                    source_to_move = os.path.join(temp_extract_path, final_mod_name)
            final_dest_path = os.path.join(MODS_DIR, final_mod_name)
            if final_mod_name in self.config["mods"]:
                if QMessageBox.question(self, t("dialog_mod_exists_title"), t("dialog_mod_exists_text").format(mod_name=final_mod_name), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                    self.update_worker_signals.update_status_bar.emit(t("status_replacing_mod").format(mod_name=final_mod_name), 3000)
                    self._delete_mod_files_and_paths(final_mod_name, keep_config_entry=True)
                else:
                    self.update_worker_signals.update_status_bar.emit(t("status_replace_cancelled").format(mod_name=final_mod_name), 3000)
                    return
            if source_to_move == temp_extract_path: os.rename(temp_extract_path, final_dest_path)
            else:
                shutil.move(source_to_move, final_dest_path)
                if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)

            saved_image_path = None
            if manual_image_path and os.path.exists(manual_image_path):
                try:
                    image_filename = f"{final_mod_name}{os.path.splitext(manual_image_path)[1]}"
                    dest_image_path = os.path.join(MOD_IMAGES_DIR, image_filename)
                    shutil.copy(manual_image_path, dest_image_path)
                    saved_image_path = dest_image_path
                except Exception as e:
                    print(f"Error al copiar la imagen manual: {e}")

            mod_entry = self.config["mods"].setdefault(final_mod_name, {"active": False, "deployed_paths": [], "gamebanana_info": None})

            if saved_image_path:
                mod_entry["manual_image_path"] = saved_image_path

            if mod_gamebanana_info:
                mod_entry["gamebanana_info"] = mod_gamebanana_info
                mod_entry["gamebanana_info"]["update_available"] = False
            mod_entry["active"] = mod_entry.get("active", False)
            self.save_config()
            self.update_worker_signals.update_status_bar.emit(t("status_mod_installed_success").format(mod_name=final_mod_name), 5000)

        except Exception as e:
            self.update_worker_signals.show_message_box.emit(t("dialog_install_error_title"), t("dialog_generic_install_error_text").format(mod_name=clean_mod_name, error=e), QMessageBox.Icon.Critical.value)
        
        finally:
            subprocess.Popen = _original_popen
            
            if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path, ignore_errors=True)
            if is_download and os.path.exists(file_path): os.remove(file_path)
            self.sync_mods_folder()


    def eventFilter(self, obj, event):
        if obj is self.modding_power_button:
            if event.type() == QEvent.Type.MouseButtonPress:
                game_processes = ["SparkingZERO.exe", "SparkingZERO-Win64-Shipping.exe"]
                for proc in psutil.process_iter(['name']):
                    if proc.info['name'] in game_processes:
                        t = self.translator.get
                        QMessageBox.warning(self, t("dialog_action_not_allowed_title"), t("dialog_bypass_stop_sparking"))
                        return True
        
        return super().eventFilter(obj, event)

    def manage_bypass(self, checked):
        t = self.translator.get
        if not self.game_path_is_valid:
            self.modding_power_button.blockSignals(True)
            self.modding_power_button.setChecked(not checked)
            self.modding_power_button.blockSignals(False)
            QMessageBox.warning(self, t("dialog_action_not_allowed_title"), t("dialog_set_valid_game_path_first"))
            return

        source_dir = resource_path("resources")
        game_base_path = self.config["game_path"]
        win64_path = os.path.join(game_base_path, "SparkingZERO", "Binaries", "Win64")
        game_mods_path = os.path.join(game_base_path, "SparkingZERO", "Mods")
        game_paks_mods_path = os.path.join(game_base_path, "SparkingZERO", "Content", "Paks", "~mods")
        backup_mods_path = os.path.join(ACTIVE_MODS_BACKUP_DIR, "Mods")
        backup_paks_mods_path = os.path.join(ACTIVE_MODS_BACKUP_DIR, "~mods")
        plugins_in_game_path = os.path.join(win64_path, "plugins")
        backup_plugins_path = os.path.join(ACTIVE_MODS_BACKUP_DIR, "plugins")

        try:
            if checked:
                needs_copy = False
                if os.path.exists(source_dir):
                    for item_name in os.listdir(source_dir):
                        dest_path = os.path.join(win64_path, item_name)
                        if not os.path.exists(dest_path):
                            needs_copy = True
                            break
                if needs_copy:
                    shutil.copytree(source_dir, win64_path, dirs_exist_ok=True)
                if os.path.exists(backup_plugins_path):
                    if os.path.exists(plugins_in_game_path): shutil.rmtree(plugins_in_game_path)
                    shutil.move(backup_plugins_path, plugins_in_game_path)
                os.makedirs(os.path.dirname(game_mods_path), exist_ok=True)
                os.makedirs(os.path.dirname(game_paks_mods_path), exist_ok=True)
                if os.path.exists(backup_mods_path): shutil.move(backup_mods_path, game_mods_path)
                if os.path.exists(backup_paks_mods_path): shutil.move(backup_paks_mods_path, game_paks_mods_path)
            else:
                os.makedirs(ACTIVE_MODS_BACKUP_DIR, exist_ok=True)
                if os.path.exists(game_mods_path):
                    if os.path.exists(backup_mods_path): shutil.rmtree(backup_mods_path)
                    shutil.move(game_mods_path, backup_mods_path)
                if os.path.exists(game_paks_mods_path):
                    if os.path.exists(backup_paks_mods_path): shutil.rmtree(backup_paks_mods_path)
                    shutil.move(game_paks_mods_path, backup_paks_mods_path)
                if os.path.exists(plugins_in_game_path):
                    if os.path.exists(backup_plugins_path): shutil.rmtree(backup_plugins_path)
                    shutil.move(plugins_in_game_path, backup_plugins_path)
                if os.path.exists(source_dir):
                    for item_name in os.listdir(source_dir):
                        dest_path = os.path.join(win64_path, item_name)
                        if os.path.exists(dest_path):
                            if os.path.isdir(dest_path): shutil.rmtree(dest_path)
                            else: os.remove(dest_path)
        
        except Exception as e:
            self.modding_power_button.blockSignals(True)
            self.modding_power_button.setChecked(not checked)
            self.modding_power_button.blockSignals(False)
            QMessageBox.critical(self, t("dialog_bypass_error_title"), t("dialog_bypass_error_text").format(error=e))
            return
        
        self.config["bypass_active"] = checked
        self.save_config()

        if checked:
            self.statusBar().showMessage(t("status_modding_activated"), 5000)
        else:
            self.statusBar().showMessage(t("status_modding_deactivated"), 5000)
            
        self.update_ui_state()
        self.sync_mods_folder()
        
    def _determine_mod_type(self, mod_path):
        if not os.path.isdir(mod_path): return None
        files = [item.lower() for item in os.listdir(mod_path) if os.path.isfile(os.path.join(mod_path, item))]
        if not files: return None
        if any(f.endswith(('.pak', '.ucas', '.utoc')) for f in files): return "paks"
        if any(f.endswith('.json') for f in files): return "json"
        return "general"

    def _find_actual_mod_folders(self, search_path):
        found_mod_paths = []
        if self._determine_mod_type(search_path) in ["paks", "json", "general"]: return [search_path]
        for item in os.listdir(search_path):
            path = os.path.join(search_path, item)
            if os.path.isdir(path):
                mod_type = self._determine_mod_type(path)
                if mod_type in ["paks", "json", "general"]: found_mod_paths.append(path)
                else: found_mod_paths.extend(self._find_actual_mod_folders(path))
        return found_mod_paths

    def toggle_mod(self, mod_name, checked, button, indicator):
        if self.is_applying_profile or self.config.get("mod_management_mode") != "profiles":
            return
        if not self.game_path_is_valid or not self.modding_power_button.isChecked():
            QMessageBox.warning(self, self.translator.get("dialog_modding_deactivated_title"), self.translator.get("dialog_modding_deactivated_text"))
            button.setChecked(not checked)
            return
        current_profile = self.config["current_profile"]
        active_mods_in_profile = self.config["profiles"].get(current_profile, [])
        if checked and mod_name not in active_mods_in_profile: active_mods_in_profile.append(mod_name)
        elif not checked and mod_name in active_mods_in_profile: active_mods_in_profile.remove(mod_name)
        self.config["profiles"][current_profile] = active_mods_in_profile
        self.save_config()
        self._apply_mod_state(mod_name, checked, button, indicator)

    def _apply_mod_state(self, mod_name, checked, button, indicator, base_path=None):
        t = self.translator.get
        if base_path is None:
            base_path = MODS_DIR
        
        mod_data = self.config["mods"].get(mod_name)
        if not mod_data and base_path == MODS_DIR: return
        elif not mod_data:
            mod_data = {"deployed_paths": []}

        game_base_path = self.config["game_path"]
        json_files_path = os.path.join(game_base_path, "SparkingZERO", "Mods", "ZeroSpark", "Json", "JsonFiles.json")
        try:
            if checked:
                source_path = os.path.join(base_path, mod_name)
                if not os.path.exists(source_path):
                    raise FileNotFoundError(f"Mod source folder not found at {source_path}")

                actual_mod_folders = self._find_actual_mod_folders(source_path)
                if not actual_mod_folders: raise ValueError(t("error_no_valid_mod_content"))
                
                deployed_paths = []
                json_mod_names_to_add = [os.path.splitext(f)[0] for p in actual_mod_folders if self._determine_mod_type(p) == "json" for f in os.listdir(p) if f.lower().endswith('.json')]
                if json_mod_names_to_add:
                    os.makedirs(os.path.dirname(json_files_path), exist_ok=True)
                    data = {}
                    if os.path.exists(json_files_path):
                        with open(json_files_path, 'r', encoding='utf-8') as f:
                            try: data = json.load(f)
                            except json.JSONDecodeError: data = {}
                    data.setdefault("Default", [])
                    data.setdefault("ZMM", [])
                    for name in json_mod_names_to_add:
                        if name not in data["ZMM"]: data["ZMM"].append(name)
                    with open(json_files_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
                
                for folder_path in actual_mod_folders:
                    mod_type, folder_name = self._determine_mod_type(folder_path), os.path.basename(folder_path)
                    dest_path = None
                    if mod_type == "paks": dest_path = os.path.join(game_base_path, "SparkingZERO", "Content", "Paks", "~mods", folder_name)
                    elif mod_type == "json":
                        dest_path_base = os.path.join(game_base_path, "SparkingZERO", "Mods", "ZeroSpark", "Json")
                        os.makedirs(dest_path_base, exist_ok=True)
                        for file in os.listdir(folder_path):
                            if file.lower().endswith('.json'):
                                src_file, dst_file = os.path.join(folder_path, file), os.path.join(dest_path_base, file)
                                shutil.copy(src_file, dst_file)
                                deployed_paths.append(dst_file)
                        continue
                    else: dest_path = os.path.join(game_base_path, "SparkingZERO", "Mods", folder_name)
                    if dest_path:
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        if os.path.exists(dest_path): shutil.rmtree(dest_path)
                        shutil.copytree(folder_path, dest_path, dirs_exist_ok=True)
                        deployed_paths.append(dest_path)
                mod_data["deployed_paths"] = deployed_paths
                if not self.is_applying_profile: self.statusBar().showMessage(t("status_mod_activated").format(mod_name=mod_name), 3000)
            else:
                deployed_paths = mod_data.get("deployed_paths", [])
                json_mod_names_to_remove = [os.path.splitext(os.path.basename(p))[0] for p in deployed_paths if p.lower().endswith('.json') and os.path.isfile(p) and "zerospark" in p.lower()]
                if json_mod_names_to_remove and os.path.exists(json_files_path):
                    data = {}
                    with open(json_files_path, 'r', encoding='utf-8') as f:
                        try: data = json.load(f)
                        except json.JSONDecodeError: data = None
                    if data and "ZMM" in data and isinstance(data.get("ZMM"), list):
                        data["ZMM"] = [name for name in data["ZMM"] if name not in json_mod_names_to_remove]
                        if not data["ZMM"]: del data["ZMM"]
                    if data:
                        with open(json_files_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
                for path in deployed_paths:
                    if os.path.exists(path):
                        if os.path.isfile(path): os.remove(path)
                        elif os.path.isdir(path): shutil.rmtree(path)
                mod_data["deployed_paths"] = []
                if not self.is_applying_profile: self.statusBar().showMessage(t("status_mod_deactivated").format(mod_name=mod_name), 3000)
            
            if mod_name in self.config["mods"]:
                self.config["mods"][mod_name]["active"] = checked
                self.config["mods"][mod_name]["deployed_paths"] = mod_data["deployed_paths"]
                self.save_config()
                if button: button.setText(t("btn_deactivate") if checked else t("btn_activate"))
                if indicator: indicator.set_status(checked)
                self.update_mod_details_ui_signal.emit(mod_name)
        except Exception as e:
            QMessageBox.critical(self, t("dialog_manage_mod_error_title"), t("dialog_manage_mod_error_text").format(mod_name=mod_name, error=e))
            if mod_name in self.config["mods"]:
                self.config["mods"][mod_name]["active"] = not checked
                self.save_config()
                self.sync_mods_folder()

    def sync_mods_folder(self):
        if not os.path.exists(MODS_DIR): os.makedirs(MODS_DIR)
        mods_in_app_folder = {d for d in os.listdir(MODS_DIR) if os.path.isdir(os.path.join(MODS_DIR, d))}
        mods_in_config = set(self.config['mods'].keys())
        for mod_name in mods_in_app_folder - mods_in_config: self.config['mods'][mod_name] = {"active": False, "deployed_paths": [], "gamebanana_info": None}
        for mod_name in mods_in_config - mods_in_app_folder:
            for profile in self.config["profiles"]:
                if mod_name in self.config["profiles"][profile]: self.config["profiles"][profile].remove(mod_name)
            if mod_name in self.config['mods']: del self.config['mods'][mod_name]
        self.save_config()
        self.update_mod_list()
        if self.mod_list.currentItem() is None: self._clear_mod_details_ui()

    def update_ui_state(self):
        is_modding_enabled = self.game_path_is_valid and self.modding_power_button.isChecked()
        is_profile_mode = self.config.get("mod_management_mode") == "profiles"
        self.toggle_all_button.setEnabled(is_modding_enabled and is_profile_mode)
        self.disable_all_button.setEnabled(is_modding_enabled and is_profile_mode)
        self.manual_install_button.setEnabled(self.game_path_is_valid)
        self.update_mods_button.setEnabled(self.game_path_is_valid)
        self.add_profile_button.setEnabled(self.game_path_is_valid and is_profile_mode)
        self.delete_profile_button.setEnabled(self.game_path_is_valid and is_profile_mode and self.config.get("current_profile") != "Default")
        for i in range(self.mod_list.count()):
            widget = self.mod_list.itemWidget(self.mod_list.item(i))
            if isinstance(widget, QWidget) and hasattr(widget, 'findChild'):
                toggle_button = widget.findChild(QPushButton, "ToggleButton")
                if toggle_button: toggle_button.setEnabled(is_modding_enabled and is_profile_mode)

    def initialize_game_path(self):
        t = self.translator.get
        game_path = self.config.get("game_path")
        if game_path and self.validate_game_path(game_path):
            self.statusBar().showMessage(t("status_game_path_loaded"), 5000)
            self.game_path_label.setText(f"{t('game_path_label')}: {game_path}")
        else:
            self.statusBar().showMessage(t("status_searching_steam"), 3000)
            game_path = self.find_game_path_automatically()
            if game_path and self.validate_game_path(game_path):
                self.config["game_path"] = game_path
                self.game_path_label.setText(f"{t('game_path_label')}: {game_path}")
                self.save_config()
                self.statusBar().showMessage(t("status_game_found").format(path=game_path), 5000)
            else:
                self.statusBar().showMessage(t("status_search_failed"), 0)
                game_path = self.prompt_for_game_path()
                if self.game_path_is_valid:
                    self.config["game_path"] = game_path
                    self.game_path_label.setText(f"{t('game_path_label')}: {game_path}")
                    self.save_config()
                else: self.game_path_label.setText(t('game_path_not_set'))
        self.update_ui_state()

    def find_game_path_automatically(self):
        if winreg is None: return None
        try:
            hkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
            steam_path = winreg.QueryValueEx(hkey, "InstallPath")[0]
            winreg.CloseKey(hkey)
            library_folders = [os.path.join(steam_path, "steamapps")]
            library_folders_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
            if os.path.exists(library_folders_path):
                with open(library_folders_path, 'r', encoding='utf-8') as f:
                    for match in re.finditer(r'"path"\s+"((?:[^"\\]|\\.)+)"', f.read()):
                        library_folders.append(os.path.join(match.group(1).replace('\\\\', '\\'), "steamapps"))
            self.statusBar().showMessage(self.translator.get("status_searching_libraries").format(count=len(library_folders)), 3000)
            app_manifest_file = f"appmanifest_{SPARKING_ZERO_STEAM_APPID}.acf"
            for library in library_folders:
                manifest_path = os.path.join(library, app_manifest_file)
                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        match = re.search(r'"installdir"\s+"([^"]+)"', f.read())
                        if match: return os.path.join(library, "common", match.group(1))
        except Exception as e: print(f"Error detección: {e}")
        return None

    def prompt_for_game_path(self, force_prompt=False):
        t = self.translator.get
        
        if not self.game_path_is_valid or force_prompt:
            QMessageBox.information(self, t("dialog_select_game_folder_title"), t("dialog_select_game_folder_text"))
            path = QFileDialog.getExistingDirectory(self, t("dialog_select_game_folder_title_short"))

            if path:
                if self.validate_game_path(path):
                    self.statusBar().showMessage(t("status_game_path_set").format(path=path), 5000)
                    return path
                else:
                    self.game_path_is_valid = False
                    self.statusBar().showMessage(t("status_invalid_path_or_cancelled"), 5000)
                    return ""

        return self.config.get("game_path", "")

    def validate_game_path(self, path):
        target_dir = os.path.join(path, "SparkingZERO", "Binaries", "Win64")
        if os.path.isdir(target_dir):
            self.game_path_is_valid = True
            return True
        self.game_path_is_valid = False
        return False

    def update_mod_list(self):
        self.mod_list.clear()
        sorted_mods = sorted(self.config["mods"].items())
        if not sorted_mods:
            item = QListWidgetItem(self.mod_list)
            label = QLabel(self.translator.get("misc_no_mods_installed"))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("padding: 40px; color: #a090c0; font-style: italic; background: transparent;")
            item.setSizeHint(label.sizeHint())
            self.mod_list.addItem(item)
            self.mod_list.setItemWidget(item, label)
        else:
            for mod_name, mod_data in sorted_mods:
                is_active = mod_data.get("active", False)
                item = QListWidgetItem(self.mod_list)
                item.setData(Qt.ItemDataRole.UserRole, mod_name)
                widget = self.create_mod_widget(mod_name, is_active)
                item.setSizeHint(widget.sizeHint())
                self.mod_list.addItem(item)
                self.mod_list.setItemWidget(item, widget)
        self.update_ui_state()

    def create_mod_widget(self, mod_name, is_active):
        widget = QWidget()
        widget.setMinimumHeight(55)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)
        status_indicator = ModStatusIndicator(is_active)
        layout.addWidget(status_indicator)
        display_name = mod_name
        mod_data = self.config["mods"].get(mod_name)
        if mod_data and mod_data.get("gamebanana_info"):
            gb_name = mod_data["gamebanana_info"].get('_sName')
            if gb_name: display_name = gb_name
        label = ElidedLabel(display_name, self)
        label.setObjectName("ModLabel")
        layout.addWidget(label, 1)
        toggle_button = QPushButton(self.translator.get("btn_deactivate") if is_active else self.translator.get("btn_activate"))
        toggle_button.setObjectName("ToggleButton")
        toggle_button.setCheckable(True)
        toggle_button.setChecked(is_active)
        toggle_button.setMinimumWidth(90)
        toggle_button.toggled.connect(lambda chk, n=mod_name, b=toggle_button, i=status_indicator: self.toggle_mod(n, chk, b, i))
        layout.addWidget(toggle_button)
        delete_button = QPushButton(self.translator.get("btn_delete"))
        delete_button.setObjectName("DeleteButton")
        delete_button.setMinimumWidth(80)
        delete_button.clicked.connect(lambda _, n=mod_name: self.delete_mod(n))
        layout.addWidget(delete_button)
        return widget

    def delete_mod(self, mod_name):
        t = self.translator.get
        if QMessageBox.question(self, t("dialog_confirm_delete_title"), t("dialog_confirm_delete_text").format(mod_name=mod_name), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                self.statusBar().showMessage(t("status_deleting_mod").format(mod_name=mod_name), 3000)
                self._delete_mod_files_and_paths(mod_name, keep_config_entry=False)
                if mod_name in self.config["mods"]:
                    del self.config["mods"][mod_name]
                for profile_name in self.config["profiles"]:
                    if mod_name in self.config["profiles"][profile_name]:
                        self.config["profiles"][profile_name].remove(mod_name)
                
                self.save_config()
                self.sync_mods_folder()
                self.statusBar().showMessage(t("status_mod_deleted_success").format(mod_name=mod_name), 3000)
            except Exception as e:
                QMessageBox.critical(self, t("dialog_delete_mod_error_title"), t("dialog_delete_mod_error_text").format(mod_name=mod_name, error=e))
                self.statusBar().showMessage(t("status_delete_mod_error").format(mod_name=mod_name), 3000)

    def _delete_mod_files_and_paths(self, mod_name, keep_config_entry=False):
        mod_data = self.config["mods"].get(mod_name, {})
        if mod_data.get("active"):
            self._apply_mod_state(mod_name, False, None, None)

        manual_image_path = mod_data.get("manual_image_path")
        if manual_image_path and os.path.exists(manual_image_path):
            try:
                os.remove(manual_image_path)
            except Exception as e:
                print(f"ADVERTENCIA: No se pudo eliminar la imagen del mod '{manual_image_path}'. Error: {e}")
        
        mod_local_path = os.path.join(MODS_DIR, mod_name)
        if os.path.exists(mod_local_path):
            try:
                shutil.rmtree(mod_local_path)
            except OSError as e:
                print(f"ADVERTENCIA: No se pudo eliminar la carpeta local del mod '{mod_local_path}'. Error: {e}")
        
        if keep_config_entry and mod_name in self.config["mods"]:
             self.config["mods"][mod_name]["deployed_paths"] = []
             self.config["mods"][mod_name]["active"] = False

    def change_game_path(self):
        t = self.translator.get
        new_path = self.prompt_for_game_path(force_prompt=True)
        if new_path:
            self.modding_power_button.setChecked(False)
            self.game_path_label.setText(f"{t('game_path_label')}: {new_path}")
            self.config["game_path"] = new_path
            self.save_config()
            self.update_ui_state()
            QMessageBox.information(self, t("dialog_path_updated_title"), t("dialog_path_updated_text").format(path=new_path))
        else: self.statusBar().showMessage(t("status_path_change_cancelled"), 3000)

    def toggle_all_mods(self, activate):
        t = self.translator.get
        if self.config.get("mod_management_mode") != "profiles": return
        if not self.game_path_is_valid or not self.modding_power_button.isChecked():
            QMessageBox.warning(self, t("dialog_modding_deactivated_title"), t("dialog_modding_deactivated_action_text"))
            return
        current_profile = self.config["current_profile"]
        all_mod_names = list(self.config["mods"].keys())
        self.config["profiles"][current_profile] = all_mod_names if activate else []
        self.save_config()
        self.apply_current_profile_state()
        self.update_mod_list()

    def save_config(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(self.config, f, indent=4)

    def _clear_mod_details_ui(self):
        t = self.translator.get
        self.mod_details_name_label.setText(t("details_select_mod"))
        self.mod_details_author_label.setText("")
        self.mod_details_image_label.setPixmap(QPixmap())
        self.mod_details_image_label.setText(t("details_no_image"))
        self.mod_details_date_label.setText("")
        self.mod_details_url_label.setText("")
        self.mod_details_update_status_label.setText("")
        self.update_single_mod_button.hide()
        try: self.update_single_mod_button.clicked.disconnect()
        except TypeError: pass
        self.current_mod_for_update = None

    def change_manual_mod_image(self):
        t = self.translator.get
        mod_name = self.current_mod_for_update
        if not mod_name:
            return

        image_path, _ = QFileDialog.getOpenFileName(self, t("dialog_select_image_title"), "", "Images (*.png *.jpg *.jpeg)")
        if image_path:
            try:
                mod_data = self.config["mods"].get(mod_name, {})
                old_image_path = mod_data.get("manual_image_path")
                if old_image_path and os.path.exists(old_image_path):
                    try:
                        os.remove(old_image_path)
                    except Exception as e:
                        print(f"ADVERTENCIA: No se pudo eliminar la imagen anterior: {e}")

                image_filename = f"{mod_name}{os.path.splitext(image_path)[1]}"
                dest_image_path = os.path.join(MOD_IMAGES_DIR, image_filename)
                shutil.copy(image_path, dest_image_path)
                
                self.config["mods"][mod_name]["manual_image_path"] = dest_image_path
                self.save_config()
                
                self.display_mod_details(self.mod_list.currentItem(), None)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo guardar la imagen: {e}")
    
    def on_manual_image_area_clicked(self):
        if not self.current_mod_for_update:
            return
        
        mod_data = self.config["mods"].get(self.current_mod_for_update, {})
        if not mod_data.get("gamebanana_info"):
            self.change_manual_mod_image()

    def display_mod_details(self, current_item, previous_item):
        t = self.translator.get
        self._clear_mod_details_ui()
        
        self.mod_details_image_label.setCursor(Qt.CursorShape.ArrowCursor)

        if current_item is None or current_item.data(Qt.ItemDataRole.UserRole) is None:
            return
        mod_name = current_item.data(Qt.ItemDataRole.UserRole)
        mod_data = self.config["mods"].get(mod_name)
        if not mod_data:
            return

        self.current_mod_for_update = mod_name
        
        gamebanana_info = mod_data.get("gamebanana_info")
        
        display_name = mod_name
        if gamebanana_info and gamebanana_info.get('_sName'):
            display_name = gamebanana_info.get('_sName')
        self.mod_details_name_label.setText(display_name)

        if not gamebanana_info:
            self.mod_details_image_label.setCursor(Qt.CursorShape.PointingHandCursor)
            manual_image_path = mod_data.get("manual_image_path")
            if manual_image_path and os.path.exists(manual_image_path):
                pixmap = QPixmap(manual_image_path)
                self._set_detail_image(self.mod_details_image_label, pixmap)
            else:
                self.mod_details_image_label.setText(t("details_click_to_add_image"))
        else:
            if gamebanana_info.get('image_url'):
                image_url = gamebanana_info.get('image_url')
                self.mod_details_image_label.setText(t("details_loading_image"))
                threading.Thread(target=self._fetch_image_for_details, args=(self.mod_details_image_label, image_url), daemon=True).start()
            else:
                self.mod_details_image_label.setText(t("details_no_image"))
        
        if gamebanana_info and gamebanana_info.get('_idRow'):
            self.mod_details_author_label.setText(t("details_author_prefix").format(author=gamebanana_info.get('author_name', t("details_unknown_author"))))
            created_ts, last_updated_ts = gamebanana_info.get('_tsDateAdded', 0), gamebanana_info.get('_tsDateModified', 0)
            is_update = last_updated_ts != created_ts
            status_text = t("details_date_updated") if is_update else t("details_date_published")
            timestamp = last_updated_ts if is_update else created_ts
            self.mod_details_date_label.setText(f"<b>{status_text}:</b> {format_timestamp(timestamp, self.translator)}")
            profile_url = gamebanana_info.get('_sProfileUrl')
            if profile_url:
                self.mod_details_url_label.setText(f'<a href="{profile_url}" style="color: #00d1c1;">{t("details_view_on_gb")}</a>')
                self.mod_details_url_label.linkActivated.connect(lambda link: QDesktopServices.openUrl(QUrl(link)))
            else:
                self.mod_details_url_label.setText(t("details_gb_url_not_available"))
            
            if gamebanana_info.get("update_available", False):
                self.mod_details_update_status_label.setText(t("details_update_available"))
                self.update_single_mod_button.show()
                try: self.update_single_mod_button.clicked.disconnect()
                except TypeError: pass
                self.update_single_mod_button.clicked.connect(lambda: self.update_mod_action(mod_name))
                self.update_single_mod_button.setEnabled(self.update_mods_button.isEnabled())
            else:
                self.mod_details_update_status_label.setText(t("details_mod_is_up_to_date"))
                self.update_single_mod_button.hide()
        else:
            self.mod_details_author_label.setText(t("details_no_gb_data"))
            self.mod_details_date_label.setText("")
            self.mod_details_url_label.setText("")
            self.mod_details_update_status_label.setText(t("details_cannot_check_updates"))
            self.update_single_mod_button.hide()

    def _fetch_image_for_details(self, image_label, url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            self.image_loader_signals.image_loaded.emit(image_label, pixmap)
        except Exception: self.image_loader_signals.image_error.emit(image_label)

    def _set_detail_image(self, image_label, pixmap):
        scaled_pixmap = pixmap.scaled(image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        image_label.setPixmap(scaled_pixmap)

    def _set_detail_image_error(self, image_label):
        image_label.setPixmap(QPixmap())
        image_label.setText(self.translator.get("details_image_load_error"))

    def check_for_mod_updates(self):
        t = self.translator.get
        if not self.game_path_is_valid:
            self.update_worker_signals.show_message_box.emit(t("dialog_game_path_title"), t("dialog_set_valid_game_path_updates"), QMessageBox.Icon.Warning.value)
            return
        gb_mods_to_check = {name: data for name, data in self.config["mods"].items() if data.get("gamebanana_info") and data["gamebanana_info"].get('_idRow')}
        if not gb_mods_to_check:
            self.update_worker_signals.show_message_box.emit(t("dialog_updates_title"), t("dialog_no_gb_mods_to_update"), QMessageBox.Icon.Information.value)
            return
        self.update_worker_signals.update_status_bar.emit(t("status_checking_for_updates"), 0)
        self.update_worker_signals.set_cursor.emit(Qt.CursorShape.WaitCursor)
        self.update_worker_signals.enable_main_update_button.emit(False)
        threading.Thread(target=self._run_update_check_thread, args=(gb_mods_to_check,), daemon=True).start()

    def _run_update_check_thread(self, gb_mods_to_check):
        t = self.translator.get
        updated_mods_count = 0
        total_mods = len(gb_mods_to_check)
        try:
            for i, (mod_name, mod_data) in enumerate(gb_mods_to_check.items()):
                self.update_worker_signals.update_status_bar.emit(t("status_checking_mod_progress").format(mod_name=mod_name, current=i+1, total=total_mods), 0)
                try:
                    if self._check_single_mod_for_update(mod_name, mod_data): updated_mods_count += 1
                except Exception as e: print(f"Error al verificar actualización para {mod_name}: {e}")
                self.mod_update_ui_signals.update_mod_details_status.emit(mod_name)
            if updated_mods_count > 0:
                self.update_worker_signals.update_status_bar.emit(t("status_updates_found").format(count=updated_mods_count), 5000)
                self.update_worker_signals.show_message_box.emit(t("dialog_updates_title"), t("dialog_updates_found_text").format(count=updated_mods_count), QMessageBox.Icon.Information.value)
            else:
                self.update_worker_signals.update_status_bar.emit(t("status_all_mods_up_to_date"), 5000)
                self.update_worker_signals.show_message_box.emit(t("dialog_updates_title"), t("dialog_all_mods_up_to_date_text"), QMessageBox.Icon.Information.value)
        finally: self.update_worker_signals.update_process_finished.emit("")

    def _check_single_mod_for_update(self, mod_name, mod_data):
        gb_info = mod_data.get("gamebanana_info")
        if not gb_info or not gb_info.get('_idRow') or not gb_info.get('_sName'): return False
        mod_id, mod_s_name, current_ts_modified = gb_info['_idRow'], gb_info['_sName'], gb_info.get('_tsDateModified', 0)
        try:
            api_url = f"https://gamebanana.com/apiv11/Game/{SPARKING_ZERO_STEAM_APPID}/Subfeed"
            params = {'_nPage': 1, '_sSort': 'new', '_sName': mod_s_name}
            response = requests.get(api_url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            records = data.get('_aRecords', [])
            latest_mod_record = next((r for r in records if r.get('_idRow') == mod_id), None)
            if latest_mod_record:
                latest_ts_modified = latest_mod_record.get('_tsDateModified', 0)
                if latest_ts_modified > current_ts_modified:
                    gb_info['latest_full_info'] = latest_mod_record
                    gb_info['update_available'] = True
                    self.save_config()
                    return True
            gb_info['update_available'] = False
            self.save_config()
        except Exception as e:
            print(f"Error al verificar actualización para {mod_name}: {e}")
            gb_info['update_available'] = False
            self.save_config()
        return False

    def _update_mod_details_ui_slot(self, mod_name_to_update):
        current_selected_item = self.mod_list.currentItem()
        if current_selected_item and current_selected_item.data(Qt.ItemDataRole.UserRole) == mod_name_to_update:
            self.display_mod_details(current_selected_item, None)

    def update_mod_action(self, mod_name):
        t = self.translator.get
        if not self.game_path_is_valid:
            self.update_worker_signals.show_message_box.emit(t("dialog_game_path_title"), t("dialog_set_valid_game_path_updates"), QMessageBox.Icon.Warning.value)
            return
        mod_data = self.config["mods"].get(mod_name)
        if not mod_data or not mod_data.get("gamebanana_info", {}).get("update_available", False):
            self.update_worker_signals.show_message_box.emit(t("dialog_update_mod_title"), t("dialog_mod_already_updated").format(mod_name=mod_name), QMessageBox.Icon.Information.value)
            return
        gb_info = mod_data["gamebanana_info"]
        latest_full_info = gb_info.get("latest_full_info")
        if not latest_full_info or not latest_full_info.get('_idRow'):
            self.update_worker_signals.show_message_box.emit(t("dialog_update_error_title"), t("dialog_no_update_info"), QMessageBox.Icon.Critical.value)
            return
        mod_id_to_download, mod_name_to_download = latest_full_info['_idRow'], latest_full_info['_sName']
        self.update_worker_signals.update_status_bar.emit(t("status_preparing_update_download").format(mod_name=mod_name), 0)
        self.update_worker_signals.set_cursor.emit(Qt.CursorShape.WaitCursor)
        self.update_single_mod_button.setEnabled(False)
        threading.Thread(target=self._fetch_update_files_and_install_thread, args=(mod_id_to_download, mod_name_to_download, latest_full_info, mod_name), daemon=True).start()

    def _fetch_update_files_and_install_thread(self, mod_id, mod_name_download, latest_full_info, original_mod_name):
        t = self.translator.get
        try:
            api_url = f"https://gamebanana.com/apiv11/Mod/{mod_id}/Files"
            response = requests.get(api_url, timeout=15)
            response.raise_for_status()
            files_data = response.json()
            if not files_data: raise ValueError(t("error_no_files_found_for_update"))
            selected_file_info = files_data[0] if len(files_data) == 1 else self.select_file_for_download(files_data)
            if selected_file_info:
                from download_tab import Downloader
                downloader = Downloader(selected_file_info['_sDownloadUrl'], selected_file_info['_sFile'], mod_name_download, latest_full_info)
                downloader.finished.connect(self._on_update_download_finished)
                downloader.error.connect(lambda msg: self._on_update_download_error_with_mod_name(msg, original_mod_name))
                downloader.run()
            else: raise Exception(t("error_could_not_select_file"))
        except Exception as e:
            self.update_worker_signals.show_message_box.emit(t("dialog_update_error_title"), t("dialog_prepare_update_error").format(mod_name=original_mod_name, error=e), QMessageBox.Icon.Critical.value)
            self.update_worker_signals.update_process_finished.emit(original_mod_name)

    def select_file_for_download(self, files_data):
        result_holder_list = []
        loop = QEventLoop()
        def on_request_finished():
            self.update_file_selection_handler.show_dialog_request.disconnect(on_request_finished)
            loop.quit()
        self.update_file_selection_handler.show_dialog_request.connect(on_request_finished)
        QTimer.singleShot(0, lambda: self.update_file_selection_handler.show_dialog(files_data, result_holder_list))
        loop.exec()
        return result_holder_list[0] if result_holder_list else None

    def _on_update_download_finished(self, file_path, mod_name_downloaded, mod_gamebanana_info):
        t = self.translator.get
        self.update_worker_signals.update_status_bar.emit(t("status_update_download_finished").format(mod_name=mod_name_downloaded), 0)
        self.install_mod_from_path(file_path, mod_name_downloaded, is_download=True, mod_gamebanana_info=mod_gamebanana_info)
        mod_data = self.config["mods"].get(mod_name_downloaded)
        if mod_data and mod_data.get("gamebanana_info"):
            mod_data["gamebanana_info"].update({"update_available": False, "_tsDateModified": mod_gamebanana_info["_tsDateModified"]})
            mod_data["gamebanana_info"].pop("latest_full_info", None)
            self.save_config()
        self.update_worker_signals.update_status_bar.emit(t("status_mod_updated_successfully").format(mod_name=mod_name_downloaded), 5000)
        self.update_worker_signals.update_process_finished.emit(mod_name_downloaded)

    def _on_update_download_error_with_mod_name(self, error_msg, original_mod_name):
        t = self.translator.get
        self.update_worker_signals.update_status_bar.emit(t("status_update_download_error").format(mod_name=original_mod_name, error=error_msg), 5000)
        self.update_worker_signals.show_message_box.emit(t("dialog_update_download_error_title"), t("dialog_update_download_error_text").format(mod_name=original_mod_name, error=error_msg), QMessageBox.Icon.Critical.value)
        self.update_worker_signals.update_process_finished.emit(original_mod_name)

    def load_profiles(self):
        self.profile_combo_box.blockSignals(True)
        self.profile_combo_box.clear()
        profiles = list(self.config["profiles"].keys())
        current_profile = self.config.get("current_profile", "Default")
        self.profile_combo_box.addItems(profiles)
        if current_profile in profiles: self.profile_combo_box.setCurrentText(current_profile)
        self.profile_combo_box.blockSignals(False)
        self.update_ui_state()

    def add_profile(self):
        t = self.translator.get
        text, ok = QInputDialog.getText(self, t("dialog_add_profile_title"), t("dialog_add_profile_text"))
        if ok and text:
            if text in self.config["profiles"]:
                QMessageBox.warning(self, t("dialog_profile_exists_title"), t("dialog_profile_exists_text").format(profile_name=text))
                return
            self.config["profiles"][text] = []
            self.config["current_profile"] = text
            self.save_config()
            self.load_profiles()
            self.update_mod_list()

    def delete_profile(self):
        t = self.translator.get
        profile_to_delete = self.config.get("current_profile")
        if profile_to_delete == "Default":
            QMessageBox.warning(self, t("dialog_action_not_allowed_title"), t("dialog_cannot_delete_default_profile"))
            return
        if QMessageBox.question(self, t("dialog_confirm_delete_title"), t("dialog_confirm_delete_profile_text").format(profile_name=profile_to_delete), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            del self.config["profiles"][profile_to_delete]
            self.config["current_profile"] = "Default"
            self.save_config()
            self.load_profiles()
            self.apply_current_profile_state()

    def change_profile(self, index):
        if index == -1: return
        t = self.translator.get
        new_profile = self.profile_combo_box.itemText(index)
        self.config["current_profile"] = new_profile
        self.save_config()
        self.statusBar().showMessage(t("status_profile_changed").format(profile_name=new_profile), 3000)
        self.apply_current_profile_state()
        self.update_mod_list()

    def apply_current_profile_state(self):
        self.is_applying_profile = True
        current_profile = self.config["current_profile"]
        mods_to_be_active = self.config["profiles"].get(current_profile, [])
        for mod_name, mod_data in self.config["mods"].items():
            should_be_active = mod_name in mods_to_be_active
            is_currently_active = mod_data.get("active", False)
            if should_be_active != is_currently_active: self._apply_mod_state(mod_name, should_be_active, None, None)
        self.is_applying_profile = False
        self.update_mod_list()
        self.statusBar().showMessage(self.translator.get("status_profile_mods_applied").format(profile_name=current_profile), 3000)

    def _deactivate_all_active_mods(self):
        active_mods_found = False
        for mod_name, mod_data in self.config["mods"].items():
            if mod_data.get("active", False):
                self._apply_mod_state(mod_name, False, None, None)
                active_mods_found = True
        
        if self.config.get("active_modpack"):
            self.config["active_modpack"] = None
            active_mods_found = True
        
        if active_mods_found:
            self.save_config()
        return active_mods_found

    def switch_view_mode(self):
        t = self.translator.get
        new_index = 1 - self.home_stack.currentIndex()
        self.home_stack.setCurrentIndex(new_index)
        new_mode = "modpacks" if new_index == 1 else "profiles"
        self.config["mod_management_mode"] = new_mode

        if self.config.get("bypass_active", False):
            if self._deactivate_all_active_mods():
                self.update_mod_list()
            
            if new_mode == "profiles":
                self.apply_current_profile_state()
                self.statusBar().showMessage(t("status_switched_to_profiles"), 3000)
            else:
                self.statusBar().showMessage(t("status_switched_to_modpacks"), 3000)
        
        self.save_config()
        self.update_ui_state()
        self.populate_modpack_list()

    def populate_modpack_list(self):
        self.modpack_list.clear()
        t = self.translator.get
        modpacks = self.config.get("modpacks", {})
        if not modpacks:
            self.modpack_list.setViewMode(QListWidget.ViewMode.ListMode)
            item = QListWidgetItem(self.modpack_list)
            label = QLabel(t("modpack_no_modpacks_created"))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("padding: 40px; color: #a090c0; font-style: italic; background: transparent;")
            item.setSizeHint(label.sizeHint())
            self.modpack_list.addItem(item)
            self.modpack_list.setItemWidget(item, label)
        else:
            self.modpack_list.setViewMode(QListWidget.ViewMode.IconMode)
            for pack_name in sorted(modpacks.keys()):
                pack_data = modpacks[pack_name]
                item = QListWidgetItem(self.modpack_list)
                item.setData(Qt.ItemDataRole.UserRole, pack_name)
                item.setSizeHint(QSize(400, 280))
                widget = self.create_modpack_widget(pack_name, pack_data)
                self.modpack_list.addItem(item)
                self.modpack_list.setItemWidget(item, widget)


    def create_modpack_widget(self, pack_name, pack_data):
        t = self.translator.get
        widget = QFrame()
        widget.setObjectName("ModpackItemWidget")
        widget.setFixedSize(240, 250) 
        
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        image_label = QLabel()
        image_label.setObjectName("ModpackImage")
        image_label.setFixedSize(215, 130) 
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        img_path = pack_data.get("image")
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path)
            scaled_pixmap = pixmap.scaled(image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
        else:
            image_label.setText(t("modpack_no_image"))
        
        name_label = ElidedLabel(pack_name, self)
        name_label.setObjectName("ModpackNameLabel")
        
        author_text = f"{t('details_author_prefix_simple')} {pack_data.get('author', 'N/A')}"
        author_label = ElidedLabel(author_text, self)
        author_label.setObjectName("ModpackAuthorLabel")

        button_layout = QHBoxLayout()
        export_button = QPushButton(t("modpack_export"))
        export_button.setObjectName("ModpackActionButton")
        export_button.clicked.connect(lambda: self.export_modpack(pack_name))
        
        delete_button = QPushButton(t("btn_delete"))
        delete_button.setObjectName("DeleteButton")
        delete_button.clicked.connect(lambda: self.delete_modpack(pack_name))
        
        button_layout.addStretch(1)
        button_layout.addWidget(export_button)
        button_layout.addWidget(delete_button)

        main_layout.addWidget(image_label)
        main_layout.addWidget(name_label)
        main_layout.addWidget(author_label)
        main_layout.addStretch(1)
        main_layout.addLayout(button_layout)
        
        return widget

    def on_modpack_selected(self, current_item, previous_item):
        self.modpack_mod_list.clear()
        if current_item is None:
            if self.config.get("active_modpack") is not None:
                self._deactivate_all_active_mods()
                self.update_mod_list()
            return

        pack_name = current_item.data(Qt.ItemDataRole.UserRole)
        pack_data = self.config["modpacks"].get(pack_name, {})
        
        for mod_info in sorted(pack_data.get("mods", []), key=lambda x: x['display_name']):
            self.modpack_mod_list.addItem(mod_info['display_name'])
        
        self.activate_modpack(pack_name)

    def activate_modpack(self, pack_name):
        t = self.translator.get
        if self.config.get("active_modpack") == pack_name:
            return

        if not self.modding_power_button.isChecked():
            QMessageBox.warning(self, t("dialog_modding_deactivated_title"), t("dialog_modding_deactivated_action_text"))
            self.modpack_list.setCurrentItem(None)
            return
        
        self._deactivate_all_active_mods()
        
        pack_data = self.config["modpacks"].get(pack_name)
        if not pack_data or not pack_data.get("path"): return

        mods_to_activate = pack_data.get("mods", [])
        pack_mods_path = os.path.join(pack_data["path"], "mods")
        missing_mods = []
        
        for mod_info in mods_to_activate:
            mod_folder_name = mod_info['folder_name']
            if os.path.isdir(os.path.join(pack_mods_path, mod_folder_name)):
                self._apply_mod_state(mod_folder_name, True, None, None, base_path=pack_mods_path)
            else:
                missing_mods.append(mod_info['display_name'])
        
        self.config["active_modpack"] = pack_name
        self.save_config()
        self.update_mod_list()

        if missing_mods:
            QMessageBox.warning(self, t("modpack_activation_warning_title"), t("modpack_missing_mods_text").format(mods=", ".join(missing_mods)))
        self.statusBar().showMessage(t("modpack_activated_success").format(pack_name=pack_name), 4000)

    def create_modpack(self):
        t = self.translator.get
        available_mods_data = {}
        for folder_name, mod_info in self.config["mods"].items():
            display_name = folder_name
            if mod_info.get("gamebanana_info") and mod_info["gamebanana_info"].get("_sName"):
                display_name = mod_info["gamebanana_info"]["_sName"]
            available_mods_data[folder_name] = display_name

        if not available_mods_data:
            QMessageBox.information(self, t("modpack_creation_error_title"), t("modpack_no_mods_to_create"))
            return
        
        dialog = ModpackCreationDialog(available_mods_data, self.translator, self)
        if dialog.exec():
            data = dialog.get_data()
            name = data["name"].strip()
            if not name:
                QMessageBox.warning(self, t("modpack_creation_error_title"), t("modpack_name_required"))
                return
            if name in self.config["modpacks"]:
                QMessageBox.warning(self, t("modpack_creation_error_title"), t("modpack_name_exists"))
                return
            
            pack_storage_path = os.path.join(MODPACKS_LIBRARY_DIR, name)
            os.makedirs(os.path.join(pack_storage_path, "mods"), exist_ok=True)

            new_image_path = None
            source_image_path = data["image"]

            if source_image_path:
                filename = os.path.basename(source_image_path)
                dest_path = os.path.join(MODPACKS_DATA_DIR, f"{name.replace(' ', '_')}_{filename}")
                shutil.copy(source_image_path, dest_path)
                new_image_path = dest_path
            else:
                default_image_path = resource_path("img/icon_pack.png")
                if os.path.exists(default_image_path):
                    dest_filename = f"{name.replace(' ', '_')}_icon.png"
                    dest_path = os.path.join(MODPACKS_DATA_DIR, dest_filename)
                    shutil.copy(default_image_path, dest_path)
                    new_image_path = dest_path

            mods_metadata = []
            for mod_folder_name in data["mods"]:
                source_mod = os.path.join(MODS_DIR, mod_folder_name)
                dest_mod = os.path.join(pack_storage_path, "mods", mod_folder_name)
                if os.path.isdir(source_mod):
                    shutil.copytree(source_mod, dest_mod)
                    
                display_name = mod_folder_name
                if mod_folder_name in self.config["mods"] and self.config["mods"][mod_folder_name].get("gamebanana_info"):
                    display_name = self.config["mods"][mod_folder_name]["gamebanana_info"].get("_sName", mod_folder_name)
                mods_metadata.append({"folder_name": mod_folder_name, "display_name": display_name})

            self.config["modpacks"][name] = {"author": data["author"], "image": new_image_path, "mods": mods_metadata, "path": pack_storage_path}
            self.save_config()
            self.populate_modpack_list()
    
    def delete_modpack(self, pack_name):
        t = self.translator.get
        if QMessageBox.question(self, t("dialog_confirm_delete_title"), t("modpack_confirm_delete").format(pack_name=pack_name)) == QMessageBox.StandardButton.Yes:
            if self.config.get("active_modpack") == pack_name:
                self._deactivate_all_active_mods()
            
            pack_data = self.config["modpacks"].pop(pack_name, None)
            if pack_data:
                if pack_data.get("image") and os.path.exists(pack_data["image"]):
                    try: os.remove(pack_data["image"])
                    except Exception as e: print(f"Error al eliminar imagen: {e}")
                if pack_data.get("path") and os.path.exists(pack_data["path"]):
                    try: shutil.rmtree(pack_data["path"])
                    except Exception as e: print(f"Error al eliminar carpeta del modpack: {e}")
            
            self.save_config()
            self.populate_modpack_list()
            self.modpack_mod_list.clear()

    def export_modpack(self, pack_name):
        t = self.translator.get
        pack_data = self.config["modpacks"].get(pack_name)
        if not pack_data or not pack_data.get("path"): return

        file_path, _ = QFileDialog.getSaveFileName(self, t("modpack_export_title"), f"{pack_name}.zmmpack", f"Zero Mod Manager Pack (*.zmmpack)")
        if not file_path: return

        try:
            with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                metadata = {
                    "name": pack_name,
                    "author": pack_data.get("author", ""),
                    "mods": pack_data.get("mods", [])
                }
                img_path = pack_data.get("image")
                if img_path and os.path.exists(img_path):
                    img_filename = os.path.basename(img_path)
                    zf.write(img_path, img_filename)
                    metadata["image"] = img_filename
                zf.writestr("modpack.json", json.dumps(metadata, indent=4))

                pack_mods_path = os.path.join(pack_data["path"], "mods")
                for root, _, files in os.walk(pack_mods_path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, pack_data["path"])
                        zf.write(full_path, arcname)

            self.statusBar().showMessage(t("modpack_export_success").format(pack_name=pack_name), 5000)
        except Exception as e:
            QMessageBox.critical(self, t("modpack_export_error_title"), f"Error: {e}")

    def import_modpack(self,):
        t = self.translator.get
        file_path, _ = QFileDialog.getOpenFileName(self, t("modpack_import_title"), "", "Zero Mod Manager Pack (*.zmmpack)")
        if not file_path: return
        
        temp_dir = f"temp_import_{int(time.time())}"
        try:
            os.makedirs(temp_dir, exist_ok=True)
            with zipfile.ZipFile(file_path, 'r') as zf:
                zf.extractall(temp_dir)
            
            metadata_path = os.path.join(temp_dir, "modpack.json")
            if not os.path.exists(metadata_path):
                raise ValueError(t("modpack_import_error_no_metadata"))
            with open(metadata_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
            
            pack_name = metadata.get("name")
            if not pack_name or pack_name in self.config["modpacks"]:
                raise ValueError(t("modpack_import_error_name_conflict").format(pack_name=pack_name))
            
            pack_storage_path = os.path.join(MODPACKS_LIBRARY_DIR, pack_name)
            mods_source_dir = os.path.join(temp_dir, "mods")
            if os.path.isdir(mods_source_dir):
                shutil.copytree(mods_source_dir, os.path.join(pack_storage_path, "mods"))
            
            new_image_path = None
            if metadata.get("image"):
                img_source = os.path.join(temp_dir, metadata["image"])
                if os.path.exists(img_source):
                    filename = os.path.basename(img_source)
                    dest_path = os.path.join(MODPACKS_DATA_DIR, f"{pack_name.replace(' ', '_')}_{filename}")
                    shutil.copy(img_source, dest_path)
                    new_image_path = dest_path

            self.config["modpacks"][pack_name] = {
                "author": metadata.get("author", ""),
                "image": new_image_path,
                "mods": metadata.get("mods", []), 
                "path": pack_storage_path
            }
            self.save_config()
            self.populate_modpack_list()
            self.statusBar().showMessage(t("modpack_import_success").format(pack_name=pack_name), 5000)
        except Exception as e:
            QMessageBox.critical(self, t("modpack_import_error_title"), f"Error: {e}")
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("img/icon.png")))
    window = ZeroManager()
    window.show()
    sys.exit(app.exec())