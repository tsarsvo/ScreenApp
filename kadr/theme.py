"""Светлая / тёмная тема. Системная схема берётся из Qt (6.5+), с фолбэком по палитре."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette


@dataclass(frozen=True)
class Tokens:
    dark: bool
    bg: str          # фон окна
    surface: str     # карточки, панели
    raised: str      # поле ввода / нажатая кнопка
    border: str
    text: str
    muted: str
    hover: str
    accent: str
    accent_text: str
    danger: str

    def q(self, name: str) -> QColor:
        return QColor(getattr(self, name))


LIGHT = Tokens(
    dark=False, bg="#F4F4F6", surface="#FFFFFF", raised="#F0F0F3", border="#E2E2E7",
    text="#1C1C1E", muted="#8A8A90", hover="#EDEDF1", accent="#3F6BFF",
    accent_text="#FFFFFF", danger="#E5484D",
)
DARK = Tokens(
    dark=True, bg="#161618", surface="#212124", raised="#2A2A2E", border="#333338",
    text="#F2F2F5", muted="#8E8E96", hover="#2E2E33", accent="#6A8CFF",
    accent_text="#FFFFFF", danger="#FF6369",
)


def system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        value = scheme()
        if value == Qt.ColorScheme.Dark:
            return True
        if value == Qt.ColorScheme.Light:
            return False
    # Фолбэк: тёмный ли системный фон окна
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


class ThemeManager(QObject):
    """Отдаёт текущие токены и сообщает, когда тема сменилась (в т.ч. системная)."""

    changed = Signal()

    def __init__(self, mode: str = "system") -> None:
        super().__init__()
        self._mode = mode
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self._on_system_changed())

    @property
    def tokens(self) -> Tokens:
        if self._mode == "dark":
            return DARK
        if self._mode == "light":
            return LIGHT
        return DARK if system_is_dark() else LIGHT

    def set_mode(self, mode: str) -> None:
        if mode != self._mode:
            self._mode = mode
            self.changed.emit()

    def _on_system_changed(self) -> None:
        if self._mode == "system":
            self.changed.emit()


def settings_stylesheet(t: Tokens, check_icon: str) -> str:
    """QSS для окна настроек. Всё строится на токенах, поэтому тема меняется на лету."""
    return f"""
    QWidget#Root {{ background: {t.bg}; }}
    QScrollArea#Scroll {{ background: {t.bg}; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}
    QWidget {{ color: {t.text}; font-size: 13px; }}
    QLabel#Title {{ font-size: 17px; font-weight: 600; }}
    QLabel#Muted, QLabel#SectionTitle {{ color: {t.muted}; }}
    QLabel#SectionTitle {{ font-size: 11px; font-weight: 600; letter-spacing: 0.6px;
                           padding: 0 4px; }}
    QLabel#Error {{ color: {t.danger}; font-size: 11px; }}
    QFrame#Card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px; }}
    QFrame#Divider {{ background: {t.border}; max-height: 1px; min-height: 1px; border: none; }}

    QPushButton {{
        background: {t.raised}; border: 1px solid {t.border}; border-radius: 8px;
        padding: 6px 12px; min-height: 18px;
    }}
    QPushButton:hover {{ background: {t.hover}; }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton:disabled {{ color: {t.muted}; }}
    QComboBox:disabled, QLineEdit:disabled {{ color: {t.muted}; }}
    QPushButton#Segment {{ border-radius: 0; padding: 5px 14px; border-left-width: 0; }}
    QPushButton#Segment[first="true"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px;
                                          border-left-width: 1px; }}
    QPushButton#Segment[last="true"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
    QPushButton#Segment:checked {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
    QPushButton#Hotkey {{ min-width: 150px; font-weight: 500; }}
    QPushButton#Hotkey[recording="true"] {{ border: 1px solid {t.accent}; color: {t.accent}; }}
    QPushButton#Primary {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent};
                           font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {t.accent}; border-color: {t.text}; }}
        QPushButton#Danger {{ color: {t.danger}; background: transparent; border: 1px solid {t.danger};
                          padding: 6px 14px; }}
    QPushButton#Danger:hover {{ background: {t.danger}; color: #FFFFFF; }}
        QPushButton#Link {{ background: transparent; border: none; color: {t.accent}; padding: 4px 6px; }}
    QPushButton#Link:hover {{ text-decoration: underline; }}

    QLineEdit {{
        background: {t.raised}; border: 1px solid {t.border}; border-radius: 8px;
        padding: 6px 8px; selection-background-color: {t.accent};
    }}
    QComboBox {{
        background: {t.raised}; border: 1px solid {t.border}; border-radius: 8px;
        padding: 5px 10px; min-width: 120px;
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {t.surface}; border: 1px solid {t.border}; selection-background-color: {t.accent};
        selection-color: {t.accent_text}; outline: none; padding: 4px;
    }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 5px; border: 1px solid {t.border};
        background: {t.raised};
    }}
    QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
        image: url("{check_icon}"); }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
        background: {t.surface}; border: 1px solid {t.border};
    }}
    QSlider::sub-page:disabled {{ background: {t.border}; }}
    QSlider::handle:disabled {{ background: {t.raised}; }}
    QLabel:disabled {{ color: {t.muted}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px 6px; }}
    """
