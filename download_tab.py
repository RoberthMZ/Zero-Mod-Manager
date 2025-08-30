import os
import re
import requests
import threading
import urllib.parse
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QScrollArea, QGridLayout, QLabel,
                             QFrame, QPushButton, QMessageBox, QDialog, QListWidget,
                             QListWidgetItem, QDialogButtonBox, QHBoxLayout, QLineEdit,
                             QComboBox, QCheckBox, QSpacerItem, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QUrl, QSize
from PyQt6.QtGui import QPixmap, QDesktopServices

from translation import Translator

SPARKING_ZERO_GAMEBANANA_ID = 21179
DOWNLOADS_DIR = "downloads"
MODS_PER_PAGE = 18
API_MODS_PER_CALL = 18

def format_timestamp(ts, translator: Translator):
    now = datetime.now()
    dt_object = datetime.fromtimestamp(ts)
    diff = now - dt_object

    if diff.days > 0:
        key = "time.days_ago" if diff.days == 1 else "time.days_ago_plural"
        return translator.get(key).format(count=diff.days)
    
    hours = diff.seconds // 3600
    if hours > 0:
        key = "time.hours_ago" if hours == 1 else "time.hours_ago_plural"
        return translator.get(key).format(count=hours)

    minutes = diff.seconds // 60
    if minutes > 0:
        key = "time.minutes_ago" if minutes == 1 else "time.minutes_ago_plural"
        return translator.get(key).format(count=minutes)
        
    return translator.get("time.seconds_ago")

def _extract_category_id_from_url(url):
    if not url: return None
    match = re.search(r'/cats/(\d+)', url)
    if match: return int(match.group(1))
    return None


class Downloader(QObject):
    finished = pyqtSignal(str, str, dict)
    error = pyqtSignal(str)
    progress_updated = pyqtSignal(str, int)

    def run(self):
        try:
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            safe_file_name = re.sub(r'[/*?:"<>|]', "", self.file_name)
            final_path = os.path.join(DOWNLOADS_DIR, safe_file_name)

            with requests.get(self.url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                
                with open(final_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        if total_size > 0:
                            downloaded_size += len(chunk)
                            progress = int((downloaded_size * 100) / total_size)
                            self.progress_updated.emit(self.mod_name, progress)
            
            self.progress_updated.emit(self.mod_name, 100)
            self.finished.emit(final_path, self.mod_name, self.mod_info)

        except Exception as e:
            self.error.emit(str(e))

    def __init__(self, url, file_name, mod_name, mod_info):
        super().__init__()
        self.url = url
        self.file_name = file_name
        self.mod_name = mod_name
        self.mod_info = mod_info

    def run(self):
        try:
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            safe_file_name = re.sub(r'[/*?:"<>|]', "", self.file_name)
            final_path = os.path.join(DOWNLOADS_DIR, safe_file_name)
            with requests.get(self.url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(final_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
            self.finished.emit(final_path, self.mod_name, self.mod_info)
        except Exception as e:
            self.error.emit(str(e))

class FileSelectionDialog(QDialog):
    def __init__(self, files_data, translator: Translator, parent=None):
        super().__init__(parent)
        self.selected_file_info = None
        self.translator = translator
        self.setMinimumWidth(500)
        
        self.setStyleSheet("""
            QDialog { background-color: rgba(44, 31, 77, 0.9); border: 1px solid #4a3a6a; border-radius: 8px; color: #f0f0f0; font-family: 'Bahnschrift', 'Segoe UI', sans-serif; }
            QLabel { color: #e0d8f0; font-size: 16px; font-weight: bold; margin-bottom: 10px; padding: 5px; }
            QListWidget { background-color: #3a2a5a; border: 1px solid #6a5a8a; border-radius: 5px; padding: 5px; color: #f0f0f0; }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #4a3a6a; margin: 0px; }
            QListWidget::item:hover { background-color: rgba(67, 51, 99, 0.8); }
            QListWidget::item:selected { background-color: rgba(67, 51, 99, 1); border: 1px solid #856ec4; border-left: 3px solid #ffc900; color: #fff; }
            QPushButton { background-color: #3a2a5a; color: #e0d8f0; border: 1px solid #6a5a8a; border-radius: 5px; padding: 8px 12px; font-size: 14px; min-height: 22px; }
            QPushButton:hover { background-color: #4a3a6a; border-color: #856ec4; color: #fff; }
            QPushButton:pressed { background-color: #2a1a4a; }
            QPushButton:disabled { background-color: #2c1f4d; color: #6a5a8a; border-color: #4a3a6a; }
        """)

        layout = QVBoxLayout(self)
        self.instruction_label = QLabel()
        layout.addWidget(self.instruction_label)

        self.list_widget = QListWidget()
        for file_info in files_data:
            size_bytes = file_info.get('_nFilesize', 0)
            size_str = f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes > (1024 * 1024) else f"{size_bytes / 1024:.2f} KB"
            download_count = file_info.get('_nDownloadCount', 0)
            download_text = self.translator.get("file_dialog.downloads").format(count=download_count)
            item_text = f"{file_info['_sFile']} ({size_str}) - {download_text}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, file_info)
            self.list_widget.addItem(item)
        
        self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.retranslate_ui() 

    def retranslate_ui(self):
        t = self.translator.get
        self.setWindowTitle(t("file_dialog.title"))
        self.instruction_label.setText(t("file_dialog.instruction"))
        ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button: ok_button.setText(t("file_dialog.ok"))
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button: cancel_button.setText(t("file_dialog.cancel"))

    def accept(self):
        selected_item = self.list_widget.currentItem()
        if selected_item:
            self.selected_file_info = selected_item.data(Qt.ItemDataRole.UserRole)
        super().accept()

class ModCard(QFrame):
    mod_ready_to_install = pyqtSignal(str, str, dict)
    
    def __init__(self, mod_info, parent_tab, translator: Translator):
        super().__init__()
        self.translator = translator
        self.t = self.translator.get
        self.mod_info = {
            '_idRow': mod_info.get('_idRow', mod_info.get('id')),
            '_sName': mod_info.get('_sName', mod_info.get('name', 'Nombre no disponible')),
            'author_name': mod_info.get('_aSubmitter', {}).get('_sName', mod_info.get('author', 'Autor desconocido')),
            'image_url': mod_info.get('image_url'),
            'views': mod_info.get('_nViewCount', mod_info.get('views', 0)),
            'likes': mod_info.get('_nLikeCount', mod_info.get('likes', 0)),
            '_tsDateAdded': mod_info.get('_tsDateAdded', mod_info.get('created', 0)),
            '_tsDateModified': mod_info.get('_tsDateModified', mod_info.get('last_updated', 0)),
            '_sProfileUrl': mod_info.get('_sProfileUrl', mod_info.get('profile_url', '')),
            'update_available': False
        }
        self.parent_tab = parent_tab
        self.setObjectName("ModCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.name_label = QLabel(self.mod_info['_sName'])
        self.name_label.setObjectName("ModCardName")
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.name_label)
        
        self.author_label = QLabel(self.t("mod_card.author_prefix").format(author=self.mod_info['author_name']))
        self.author_label.setObjectName("ModCardAuthor")
        self.author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.author_label)

        self.url_label = QLabel(f'<a href="{self.mod_info["_sProfileUrl"]}" style="color: #00a2d4;">{self.t("mod_card.go_to_gb")}</a>')
        self.url_label.setObjectName("ModCardUrl")
        self.url_label.setOpenExternalLinks(True)
        self.url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.url_label.setWordWrap(True)
        main_layout.addWidget(self.url_label)
        
        self.image_label = QLabel()
        self.image_label.setFixedSize(260, 146)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setObjectName("ModCardImage")
        main_layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.load_image(self.mod_info.get('image_url'))

        stats_layout = QHBoxLayout()
        stats_layout.addStretch()
        stats_layout.addWidget(QLabel(f"👁️ {self.mod_info['views']}"))
        stats_layout.addWidget(QLabel(f"❤️ {self.mod_info['likes']}"))
        stats_layout.addStretch()
        main_layout.addLayout(stats_layout)

        created_ts = self.mod_info.get('_tsDateAdded', 0)
        last_updated_ts = self.mod_info.get('_tsDateModified', 0)
        is_update = last_updated_ts != created_ts
        status_text = self.t("mod_card.date_updated") if is_update else self.t("mod_card.date_published")
        timestamp = last_updated_ts if is_update else created_ts
        self.date_label = QLabel(f"{status_text}: {format_timestamp(timestamp, self.translator)}")
        self.date_label.setObjectName("ModCardDate")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.date_label)

        main_layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        
        self.download_button = QPushButton(self.t("mod_card.download_install"))
        self.download_button.setObjectName("DownloadButton")
        self.download_button.clicked.connect(self.select_file_to_download)
        main_layout.addWidget(self.download_button)

    def load_image(self, url):
        if url:
            threading.Thread(target=ModCard._fetch_image_threaded,
                             args=(url, self.mod_info['_idRow'], self.parent_tab.mod_image_loaded_signal),
                             daemon=True).start()
        else:
            self.image_label.setText(self.t("mod_card.no_image"))
            self.parent_tab.mod_image_loaded_signal.emit(self.mod_info['_idRow'], QPixmap())

    @staticmethod
    def _fetch_image_threaded(url, mod_id, signal_to_report_to):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            signal_to_report_to.emit(mod_id, pixmap)
        except Exception:
            signal_to_report_to.emit(mod_id, QPixmap())

    def select_file_to_download(self):
        self.download_button.setEnabled(False)
        self.download_button.setText(self.t("mod_card.searching_files"))
        threading.Thread(target=self._fetch_files_and_show_dialog, args=(self.mod_info.get('_idRow'),), daemon=True).start()

    def _fetch_files_and_show_dialog(self, mod_id):
        try:
            api_url = f"https://gamebanana.com/apiv11/Mod/{mod_id}/Files"
            response = requests.get(api_url, timeout=15)
            response.raise_for_status()
            files_data = response.json()
            if not files_data: raise ValueError("No files found for this mod.")
            self.parent_tab.show_file_dialog_signal.emit(files_data, self)
        except Exception as e:
            self.on_download_error(self.t("mod_card.get_files_error").format(error=e))

    def start_download(self, file_info):
        self.download_button.setText(self.t("mod_card.downloading"))
        downloader = Downloader(file_info['_sDownloadUrl'], file_info['_sFile'], self.mod_info['_sName'], self.mod_info)
        downloader.finished.connect(self.on_download_finished)
        downloader.error.connect(self.on_download_error)
        threading.Thread(target=downloader.run, daemon=True).start()

    def on_download_finished(self, file_path, mod_name, mod_info):
        self.download_button.setText(self.t("mod_card.installing"))
        self.mod_ready_to_install.emit(file_path, mod_name, mod_info)
        self.download_button.setText(self.t("mod_card.installed"))
        self.download_button.setEnabled(False)

    def on_download_error(self, error_msg):
        self.download_button.setEnabled(True)
        self.download_button.setText(self.t("mod_card.retry_download"))
        if error_msg: 
            self.parent_tab.show_error_message_signal.emit(
                self.t("mod_card.download_error_dialog_title"),
                self.t("mod_card.download_error_dialog_text").format(error=error_msg)
            )

class DownloadTab(QWidget):
    mod_downloaded = pyqtSignal(str, str, bool, dict)
    show_file_dialog_signal = pyqtSignal(list, ModCard)
    show_error_message_signal = pyqtSignal(str, str)
    update_categories_signal = pyqtSignal(list)
    update_gamebanana_logo_signal = pyqtSignal(QPixmap)
    mod_image_loaded_signal = pyqtSignal(int, QPixmap)
    create_mod_card_ui_signal = pyqtSignal(dict)
    update_main_status = pyqtSignal(str, int)
    show_main_message_box = pyqtSignal(str, str, int)
    _one_click_info_ready = pyqtSignal(str, str, str, dict)

    def __init__(self, translator: Translator, parent=None):
        super().__init__(parent)
        self.translator = translator
        self.t = self.translator.get 
        self.mods_loaded = False
        self.setStyleSheet("background: transparent;")
        self.current_page = 1
        self.current_sort = "new"
        self.current_category, self.current_search = None, ""
        self.show_nsfw = False
        self.current_status_message = ""
        self.active_downloaders = set() 

        self._accumulated_filtered_mods_cache = []
        self._last_api_page_scanned = 0
        self._all_api_mods_scanned = False
        self.CARD_MIN_WIDTH, self.CARD_SPACING, self.num_columns = 280, 15, 1

        self.show_file_dialog_signal.connect(self.show_file_selection_dialog)
        self.show_error_message_signal.connect(lambda title, msg: QMessageBox.critical(self, title, msg))
        self.update_categories_signal.connect(self.populate_categories_combobox)
        self.update_gamebanana_logo_signal.connect(self.set_gamebanana_logo)
        self.mod_image_loaded_signal.connect(self._update_mod_card_image)
        self.create_mod_card_ui_signal.connect(self._create_and_add_mod_card_to_layout)
        self._one_click_info_ready.connect(self._start_download_from_worker)
        self.setup_ui()
        self.retranslate_ui()
        threading.Thread(target=self._fetch_gamebanana_logo_thread, daemon=True).start()

    def retranslate_ui(self):
        self.sort_label.setText(self.t("download_tab.sort_by"))
        self.sort_combo.setItemText(0, self.t("download_tab.sort_newest"))
        self.sort_combo.setItemText(1, self.t("download_tab.sort_last_updated"))
        self.sort_combo.setItemText(2, self.t("download_tab.sort_default"))
        
        self.category_label.setText(self.t("download_tab.section"))
        if self.category_combo.count() == 0 or self.category_combo.itemData(0) is not None:
             self.populate_categories_combobox([]) 
        else: 
             self.category_combo.setItemText(0, self.t("download_tab.all_sections"))

        self.search_label.setText(self.t("download_tab.by_name"))
        self.search_bar.setPlaceholderText(self.t("download_tab.search_placeholder"))
        self.nsfw_checkbox.setText(self.t("download_tab.allow_nsfw"))
        
        self.prev_button.setText(self.t("download_tab.prev_page"))
        self.next_button.setText(self.t("download_tab.next_page"))
        self.page_label.setText(self.t("download_tab.page").format(page=self.current_page))
        
        if self.current_status_message:
            self.show_status_message(self.current_status_message) 

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        top_bar_frame = QFrame()
        top_bar_frame.setObjectName("TopBarFrame")
        top_bar_layout = QHBoxLayout(top_bar_frame)
        top_bar_layout.setContentsMargins(10, 10, 10, 10)
        top_bar_layout.setSpacing(10)
        
        self.gamebanana_logo_label = QLabel()
        self.gamebanana_logo_label.setFixedSize(230, 30)
        self.gamebanana_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gamebanana_logo_label.setObjectName("GameBananaLogo")
        top_bar_layout.addWidget(self.gamebanana_logo_label)
        top_bar_layout.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        
        self.sort_label = QLabel()
        top_bar_layout.addWidget(self.sort_label)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("", "new") 
        self.sort_combo.addItem("", "updated")
        self.sort_combo.addItem("", "default")
        self.sort_combo.activated.connect(self.trigger_reload)
        top_bar_layout.addWidget(self.sort_combo)

        self.category_label = QLabel()
        top_bar_layout.addWidget(self.category_label)
        self.category_combo = QComboBox()
        self.category_combo.setEnabled(False)
        self.category_combo.activated.connect(self.trigger_reload)
        top_bar_layout.addWidget(self.category_combo)

        self.search_label = QLabel()
        top_bar_layout.addWidget(self.search_label)
        self.search_bar = QLineEdit()
        self.search_bar.returnPressed.connect(self.trigger_reload)
        top_bar_layout.addWidget(self.search_bar)

        self.nsfw_checkbox = QCheckBox()
        self.nsfw_checkbox.stateChanged.connect(self.trigger_reload)
        top_bar_layout.addWidget(self.nsfw_checkbox)
        top_bar_layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        main_layout.addWidget(top_bar_frame)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("ModCardScrollArea")
        self.mod_cards_widget = QWidget()
        self.mod_cards_layout = QGridLayout(self.mod_cards_widget)
        self.mod_cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.mod_cards_layout.setContentsMargins(10, 10, 10, 10)
        self.mod_cards_layout.setSpacing(self.CARD_SPACING)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setObjectName("StatusMessageLabel")
        self.status_label.hide()
        self.mod_cards_layout.addWidget(self.status_label, 0, 0, 1, self.num_columns)
        scroll_area.setWidget(self.mod_cards_widget)
        main_layout.addWidget(scroll_area)
        
        pagination_layout = QHBoxLayout()
        self.prev_button = QPushButton()
        self.prev_button.clicked.connect(self.prev_page)
        self.page_label = QLabel()
        self.next_button = QPushButton()
        self.next_button.clicked.connect(self.next_page)
        pagination_layout.addStretch()
        pagination_layout.addWidget(self.prev_button)
        pagination_layout.addWidget(self.page_label)
        pagination_layout.addWidget(self.next_button)
        pagination_layout.addStretch()
        main_layout.addLayout(pagination_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_grid_layout()
    
    def start_one_click_download(self, url):
        t = self.t 
        try:
            self.update_main_status.emit(t("download_tab_one_click_fetching_info"), 0)
            
            payload = url.split(":", 1)[1]

            parts = payload.split(',')
            if len(parts) < 3:
                raise ValueError(t("one_click_error_missing_params"))

            download_url = parts[0]
            mod_id_str = parts[2]
            mod_id = int(mod_id_str)
            
            try:
                file_id_str = download_url.split('/')[-1]
                file_id_to_find = int(file_id_str)
            except (IndexError, ValueError):
                raise ValueError(t("one_click_error_invalid_file_id", "No se pudo extraer un ID de archivo válido de la URL de descarga."))
            
            print(f"Parseo exitoso -> ModID: {mod_id}, FileID a buscar: {file_id_to_find}")

            threading.Thread(target=self._fetch_info_and_download, args=(mod_id, file_id_to_find, download_url), daemon=True).start()

        except Exception as e:
            print(f"!!! ERROR en start_one_click_download: {e}")
            self.show_error_message_signal.emit(t("one_click_error_title"), str(e))

    def _fetch_info_and_download(self, mod_id, file_id_to_find, download_url):
        t = self.t
        try:
            files_api_url = f"https://gamebanana.com/apiv11/Mod/{mod_id}/Files"
            headers = {'User-Agent': 'ZeroModManager/1.0'}
            files_response = requests.get(files_api_url, headers=headers, timeout=15)
            files_response.raise_for_status()
            files_data = files_response.json()
            target_file = next((f for f in files_data if f.get('_idRow') == file_id_to_find), None)

            if not target_file:
                raise ValueError(f"No se encontró un archivo con ID {file_id_to_find} en la respuesta de la API.")

            mod_api_url = f"https://gamebanana.com/apiv11/Mod/{mod_id}"
            params = {'_csvProperties': '@gbprofile'}
            mod_response = requests.get(mod_api_url, params=params, headers=headers, timeout=10)
            mod_response.raise_for_status()
            raw_mod_metadata = mod_response.json()

            mod_name_for_display = raw_mod_metadata.get('_sName', target_file.get('_sFile'))

            self._one_click_info_ready.emit(
                download_url,
                target_file['_sFile'],
                mod_name_for_display,
                raw_mod_metadata
            )

        except Exception as e:
            error_msg = t("one_click_error_api_failed").format(error=str(e))
            self.show_error_message_signal.emit(t("one_click_error_title"), error_msg)
            print(f"!!! Error detallado en _fetch_info_and_download: {e}")


    def _update_grid_layout(self):
        margin_left = self.mod_cards_layout.contentsMargins().left()
        margin_right = self.mod_cards_layout.contentsMargins().right()
        available_width = self.mod_cards_widget.width() - margin_left - margin_right
        if available_width <= 0: return
        card_total_width = self.CARD_MIN_WIDTH + self.CARD_SPACING
        new_num_columns = max(1, (available_width + self.CARD_SPACING) // card_total_width)
        if new_num_columns != self.num_columns:
            self.num_columns = new_num_columns
            self._rebuild_mod_card_layout_from_cache()
        if self.current_status_message and not self._get_mod_cards_in_layout():
            self.mod_cards_layout.removeWidget(self.status_label)
            self.mod_cards_layout.addWidget(self.status_label, 0, 0, 1, self.num_columns)
            self.status_label.setText(self.t(self.current_status_message))
            self.status_label.show()

    def _fetch_gamebanana_logo_thread(self):
        try:
            response = requests.get("https://images.gamebanana.com/static/img/logo.png", timeout=5)
            response.raise_for_status()
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            self.update_gamebanana_logo_signal.emit(pixmap)
        except Exception as e:
            print(f"Error cargando el logo de GameBanana: {e}")
            self.update_gamebanana_logo_signal.emit(QPixmap())

    def set_gamebanana_logo(self, pixmap):
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(self.gamebanana_logo_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.gamebanana_logo_label.setPixmap(scaled_pixmap)
        else:
            self.gamebanana_logo_label.setText("GameBanana")
        self.gamebanana_logo_label.show()

    def load_mods_if_needed(self):
        if self.mods_loaded: return
        self.mods_loaded = True
        threading.Thread(target=self._load_initial_categories_thread, daemon=True).start()
        self.load_mods()

    def _load_initial_categories_thread(self):
        try:
            api_url = f"https://gamebanana.com/apiv11/Mod/Categories"
            params = {"_idGameRow": SPARKING_ZERO_GAMEBANANA_ID, "_sSort": "a_to_z"}
            response = requests.get(api_url, params=params, timeout=15)
            response.raise_for_status()
            self.update_categories_signal.emit(response.json())
        except Exception as e:
            print(f"Error al cargar categorías: {e}")
            self.update_categories_signal.emit([])

    def populate_categories_combobox(self, categories):
        current_selection = self.category_combo.currentData()
        self.category_combo.clear()
        self.category_combo.addItem(self.t("download_tab.all_sections"), None)
        for cat in categories:
            self.category_combo.addItem(cat.get('_sName'), cat.get('_idRow'))
        
        index_to_set = self.category_combo.findData(current_selection)
        self.category_combo.setCurrentIndex(index_to_set if index_to_set != -1 else 0)
        self.category_combo.setEnabled(True)

    def trigger_reload(self):
        self.current_page = 1
        self._accumulated_filtered_mods_cache = []
        self._last_api_page_scanned = 0
        self._all_api_mods_scanned = False
        self.load_mods()

    def next_page(self):
        self.current_page += 1
        self.load_mods()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_mods()

    def load_mods(self):
        self.current_sort = self.sort_combo.currentData()
        self.current_category = self.category_combo.currentData()
        self.current_search = self.search_bar.text().strip()
        self.show_nsfw = self.nsfw_checkbox.isChecked()
        self.page_label.setText(self.t("download_tab.page").format(page=self.current_page))
        self.prev_button.setEnabled(self.current_page > 1)
        self.show_status_message("download_tab.searching_mods")
        self._update_grid_layout()
        threading.Thread(target=self._fetch_mods_thread, daemon=True).start()

    def _fetch_mods_thread(self):
        try:
            api_url = f"https://gamebanana.com/apiv11/Game/{SPARKING_ZERO_GAMEBANANA_ID}/Subfeed"
            start_index_for_display = (self.current_page - 1) * MODS_PER_PAGE
            end_index_for_current_page = start_index_for_display + MODS_PER_PAGE
            api_page = self._last_api_page_scanned + 1 if self._last_api_page_scanned > 0 else 1

            while len(self._accumulated_filtered_mods_cache) < end_index_for_current_page + 1 and not self._all_api_mods_scanned:
                params = {'_csvModelInclusions': 'Mod', '_nPage': api_page, '_sSort': self.current_sort}
                if self.current_search: params['_sName'] = self.current_search
                
                response = requests.get(api_url, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
                records = data.get('_aRecords', [])
                self._last_api_page_scanned = api_page
                if not records:
                    self._all_api_mods_scanned = True
                    break
                
                for mod in records:
                    cat_match = self.current_category is None or _extract_category_id_from_url(mod.get('_aRootCategory', {}).get('_sProfileUrl')) == self.current_category
                    nsfw_match = self.show_nsfw or not mod.get('_bHasContentRatings', False)
                    if cat_match and nsfw_match: self._accumulated_filtered_mods_cache.append(mod)
                
                api_page += 1
            
            self.show_status_message("") 
            self._rebuild_mod_card_layout_from_cache()

        except Exception as e:
            error_msg = self.t("download_tab.load_mods_error").format(error=e)
            self.show_status_message(error_msg, is_key=False) 

    def _clear_mod_card_widgets_only(self):
        for widget in self._get_mod_cards_in_layout():
            self.mod_cards_layout.removeWidget(widget)
            widget.deleteLater()

    def _rebuild_mod_card_layout_from_cache(self):
        self._clear_mod_card_widgets_only()
        for i in range(self.mod_cards_layout.columnCount()): self.mod_cards_layout.setColumnStretch(i, 0)
        for i in range(self.num_columns): self.mod_cards_layout.setColumnStretch(i, 1)

        start = (self.current_page - 1) * MODS_PER_PAGE
        end = start + MODS_PER_PAGE
        mods_to_display = self._accumulated_filtered_mods_cache[start:end]

        if not mods_to_display:
            msg_key = "download_tab.no_mods_found" if self.current_page == 1 else "download_tab.no_more_mods"
            self.show_status_message(msg_key, page=self.current_page)
            self.next_button.setEnabled(False)
            return

        self.status_label.hide()
        self.current_status_message = ""
        
        for mod_record in mods_to_display:
            image_url = mod_record.get('_sPreviewUrl')
            if not image_url and '_aPreviewMedia' in mod_record and '_aImages' in mod_record['_aPreviewMedia']:
                images = mod_record['_aPreviewMedia']['_aImages']
                if images: image_url = f"{images[0].get('_sBaseUrl', '')}/{images[0].get('_sFile530', '')}"
            
            mod_info = {
                'id': mod_record.get('_idRow'), 'name': mod_record.get('_sName'),
                'author': mod_record.get('_aSubmitter', {}).get('_sName'), 'image_url': image_url,
                'views': mod_record.get('_nViewCount', 0), 'likes': mod_record.get('_nLikeCount', 0),
                'created': mod_record.get('_tsDateAdded'), 'last_updated': mod_record.get('_tsDateModified'),
                'profile_url': mod_record.get('_sProfileUrl', '')
            }
            self.create_mod_card_ui_signal.emit(mod_info)

        should_enable_next = len(self._accumulated_filtered_mods_cache) > end
        self.next_button.setEnabled(should_enable_next or not self._all_api_mods_scanned)
        self.prev_button.setEnabled(self.current_page > 1)
        self.page_label.setText(self.t("download_tab.page").format(page=self.current_page))

    def _get_mod_cards_in_layout(self):
        return [self.mod_cards_layout.itemAt(i).widget() for i in range(self.mod_cards_layout.count()) if isinstance(self.mod_cards_layout.itemAt(i).widget(), ModCard)]

    def show_status_message(self, message_key_or_text, is_key=True, **kwargs):
        self._clear_mod_card_widgets_only()
        self.current_status_message = message_key_or_text if is_key else ""
        
        message = self.t(message_key_or_text).format(**kwargs) if is_key and message_key_or_text else message_key_or_text

        if message:
            self.status_label.setText(message)
            if self.mod_cards_layout.indexOf(self.status_label) != -1: self.mod_cards_layout.removeWidget(self.status_label)
            self.mod_cards_layout.addWidget(self.status_label, 0, 0, 1, self.num_columns)
            self.status_label.show()
        else:
            self.status_label.hide()

    def _create_and_add_mod_card_to_layout(self, mod_info):
        self.status_label.hide()
        card = ModCard(mod_info, self, self.translator)
        card.mod_ready_to_install.connect(lambda path, name, info: self.mod_downloaded.emit(path, name, True, info))
        current_card_count = len(self._get_mod_cards_in_layout())
        row, col = current_card_count // self.num_columns, current_card_count % self.num_columns
        self.mod_cards_layout.addWidget(card, row, col)

    def _update_mod_card_image(self, mod_id, pixmap):
        for card in self._get_mod_cards_in_layout():
            if card.mod_info['_idRow'] == mod_id:
                if pixmap and not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(card.image_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    card.image_label.setPixmap(scaled_pixmap)
                else:
                    card.image_label.setText(self.t("mod_card.image_load_error"))
                return

    def show_file_selection_dialog(self, files_data, card_instance):
        dialog = FileSelectionDialog(files_data, self.translator, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_file = dialog.selected_file_info
            if selected_file:
                card_instance.start_download(selected_file)
            else:
                card_instance.on_download_error(self.t("file_dialog.no_file_selected"))
        else:
            card_instance.on_download_error(self.t("file_dialog.selection_cancelled"))


    def _start_download_from_worker(self, download_url, file_name, mod_name, mod_metadata):
        downloader = Downloader(download_url, file_name, mod_name, mod_metadata)
        downloader.setParent(self) 

        downloader.progress_updated.connect(self._on_download_progress)
        downloader.finished.connect(self._on_download_finished_for_1_click)
        downloader.error.connect(self._on_download_error_for_1_click)
        
        downloader.finished.connect(downloader.deleteLater)
        downloader.error.connect(downloader.deleteLater)
        
        threading.Thread(target=downloader.run, daemon=True).start()
        
    def _on_download_progress(self, mod_name, percentage):
            message = self.t("download_tab_downloading_progress").format(mod_name=mod_name, progress=percentage)
            self.update_main_status.emit(message, 0) 

    def _on_download_finished_for_1_click(self, file_path, mod_name, mod_info):
        install_starting_msg = self.t("status_starting_install").format(mod_name=mod_name)
        self.update_main_status.emit(install_starting_msg, 4000)

        self.mod_downloaded.emit(file_path, mod_name, True, mod_info)

    def _on_download_error_for_1_click(self, error_msg):
        self.update_main_status.emit(self.t("download_error_status"), 5000)

        self.show_main_message_box.emit(
            self.t("mod_card.download_error_dialog_title"),
            error_msg,
            QMessageBox.Icon.Critical.value
        )