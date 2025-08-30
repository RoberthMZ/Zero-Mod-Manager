import os
import sys
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QHBoxLayout, QSpacerItem, QSizePolicy
from PyQt6.QtGui import QPixmap, QPainter, QBrush, QColor, QDesktopServices, QPainterPath
from PyQt6.QtCore import Qt, QTimer, QUrl, QPropertyAnimation, pyqtProperty

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class InfoCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._border_color = QColor("#4a3a6a") 

    def getBorderColor(self):
        return self._border_color

    def setBorderColor(self, color):
        self._border_color = color
        self.setStyleSheet(f"""
            #InfoCard {{
                border: 2px solid {self._border_color.name()};
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2a1a4a, stop:1 #201538);
                border-radius: 15px;
            }}
        """)

    borderColor = pyqtProperty(QColor, getBorderColor, setBorderColor)

class ClickableLabel(QLabel):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl(self.url))
        super().mousePressEvent(event)

class InfoTab(QWidget):
    def __init__(self, main_window=None):
        super().__init__(parent=main_window)
        self.main_window = main_window

        if self.main_window and hasattr(self.main_window, 'translator'):
            self.translator = self.main_window.translator
        else:
            from translation import Translator
            self.translator = Translator()
            self.translator.load_language('es')

        self.setObjectName("InfoTab")
        self.setup_ui()
        self.start_saiyan_animation()

    def create_circular_pixmap(self, source_pixmap, size):
        if source_pixmap.isNull():
            return None

        scaled_pixmap = source_pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        target = QPixmap(size, size)
        target.fill(Qt.GlobalColor.transparent)

        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        
        x = (size - scaled_pixmap.width()) / 2
        y = (size - scaled_pixmap.height()) / 2
        painter.drawPixmap(int(x), int(y), scaled_pixmap)
        painter.end()

        return target

    def create_rounded_pixmap(self, source_pixmap, width, height, radius):
        if source_pixmap.isNull():
            return None

        scaled_pixmap = source_pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        target = QPixmap(scaled_pixmap.size())
        target.fill(Qt.GlobalColor.transparent)

        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0, 0, scaled_pixmap.width(), scaled_pixmap.height(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, scaled_pixmap)
        painter.end()

        return target

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setContentsMargins(20, 20, 20, 20)

        self.info_card = InfoCard()
        self.info_card.setObjectName("InfoCard")
        self.info_card.setMinimumSize(600, 680)
        self.info_card.setMaximumSize(800, 900)
        card_layout = QVBoxLayout(self.info_card)
        card_layout.setSpacing(15)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        card_layout.addSpacing(30)

        author_layout = QHBoxLayout()
        author_layout.setSpacing(20)
        author_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.author_image_label = QLabel()
        self.author_image_label.setObjectName("AuthorImageLabel")
        self.author_image_label.setFixedSize(120, 120)
        author_pixmap = QPixmap(resource_path("img/perfil.png"))
        circular_pixmap = self.create_circular_pixmap(author_pixmap, 120)
        if circular_pixmap:
            self.author_image_label.setPixmap(circular_pixmap)
        else:
            self.author_image_label.setText("R09")
            self.author_image_label.setStyleSheet("background-color: #5a4a7a; border-radius: 60px; font-size: 40px; font-weight: bold; color: #ffc900;")

        author_name_layout = QVBoxLayout()
        author_name_layout.setSpacing(2)
        self.modder_name_label = QLabel("XxR09xX")
        self.modder_name_label.setObjectName("AuthorNameLabel")
        self.real_name_label = QLabel("/ Roberth Monsalve")
        self.real_name_label.setObjectName("AuthorRealNameLabel")
        
        self.github_label = ClickableLabel("https://github.com/RoberthMZ/Zero-Mod-Manager")
        self.github_label.setObjectName("GitHubLabel")

        author_name_layout.addWidget(self.modder_name_label)
        author_name_layout.addWidget(self.real_name_label)
        author_name_layout.addWidget(self.github_label)

        author_layout.addWidget(self.author_image_label)
        author_layout.addLayout(author_name_layout)
        card_layout.addLayout(author_layout)

        separator1 = QFrame()
        separator1.setFrameShape(QFrame.Shape.HLine)
        separator1.setObjectName("Separator")
        card_layout.addWidget(separator1)

        self.version_label = QLabel("Zero Mod Manager v1.0.7")
        self.version_label.setObjectName("VersionLabel")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.thanks_label = QLabel()
        self.thanks_label.setObjectName("ThanksLabel")
        self.thanks_label.setWordWrap(True)
        self.thanks_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        card_layout.addWidget(self.version_label)
        card_layout.addWidget(self.thanks_label)


        self.donation_title_label = QLabel()
        self.donation_title_label.setObjectName("DonationTitleLabel")
        self.donation_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.donate_image_label = ClickableLabel("https://ko-fi.com/roberthmz")
        self.donate_image_label.setObjectName("DonateImage")
        kofi_pixmap = QPixmap(resource_path("img/card_ko-fi.jpg"))
        rounded_kofi_pixmap = self.create_rounded_pixmap(kofi_pixmap, 420, 210, 15)
        if rounded_kofi_pixmap:
            self.donate_image_label.setPixmap(rounded_kofi_pixmap)

        self.make_with_love = QLabel()
        self.make_with_love.setObjectName("MakeWithLove")
        self.make_with_love.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(self.donation_title_label)
        card_layout.addWidget(self.donate_image_label, 0, Qt.AlignmentFlag.AlignCenter)
        card_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        card_layout.addWidget(self.make_with_love)
        main_layout.addWidget(self.info_card)

        
        self.retranslate_ui()

    def retranslate_ui(self):
        t = self.translator.get
        self.thanks_label.setText(t("info.thanks_message"))
        self.donation_title_label.setText(t("info.donation_title"))
        self.make_with_love.setText(t("info.with_love"))
        self.github_label.setText(f"<a href='https://github.com/RoberthMZ/Zero-Mod-Manager' style='color: #a291d4; text-decoration: none;'>{t('info.github_link_text')}</a>")


    def start_saiyan_animation(self):
        self.animation = QPropertyAnimation(self.info_card, b"borderColor")
        self.animation.setDuration(6000)
        self.animation.setLoopCount(-1)

        self.animation.setKeyValueAt(0.0, QColor("#ffc900"))
        self.animation.setKeyValueAt(0.25, QColor("#00d1c1"))
        self.animation.setKeyValueAt(0.5, QColor("#ff8c00"))
        self.animation.setKeyValueAt(0.75, QColor("#856ec4"))
        self.animation.setKeyValueAt(1.0, QColor("#ffc900"))

        self.animation.start()