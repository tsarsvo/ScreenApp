"""Окно настроек. Изменения применяются и сохраняются сразу — без кнопки «Сохранить»."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, autostart, icons
from ..config import SettingsStore
from ..theme import ThemeManager, settings_stylesheet
from .widgets import HotkeyEdit, Segmented, ToggleSwitch


class SettingsWindow(QWidget):
    hotkey_recording = Signal(bool)   # приложение отключает глобальные хоткеи на время записи
    _mics_loaded = Signal(list)        # из фонового потока → GUI

    def __init__(self, store: SettingsStore, theme: ThemeManager, replay=None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.store = store
        self.theme = theme
        self.replay = replay
        s = store.data

        self.setObjectName("Root")
        self.setWindowTitle(f"{APP_NAME} — настройки")
        self.setWindowIcon(icons.logo_icon())
        self.setMinimumWidth(500)
        self._toggles: list[ToggleSwitch] = []

        # Содержимое прокручивается — окно помещается и на маленьких экранах
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setObjectName("Scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("Root")
        scroll.setWidget(content)
        outer.addWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        # --- Шапка с логотипом
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        px = QPixmap.fromImage(icons.logo_image(80))
        px.setDevicePixelRatio(2)
        logo.setPixmap(px)
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        sub = QLabel(f"Скриншоты без лишнего · v{__version__}")
        sub.setObjectName("Muted")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        head.addWidget(logo)
        head.addLayout(title_col)
        head.addStretch(1)
        root.addLayout(head)
        root.addSpacing(6)

        # --- Горячие клавиши
        self.hk_full = HotkeyEdit(s.hotkey_full)
        self.hk_region = HotkeyEdit(s.hotkey_region)
        self.hk_replay = HotkeyEdit(s.hotkey_replay)
        self.hk_error = QLabel("")
        self.hk_error.setObjectName("Error")
        self.hk_error.setWordWrap(True)
        self.hk_error.hide()
        self._hotkey_edits = {"hotkey_full": self.hk_full, "hotkey_region": self.hk_region,
                              "hotkey_replay": self.hk_replay}
        for field, edit in self._hotkey_edits.items():
            edit.recording_changed.connect(self.hotkey_recording)
            edit.hotkey_changed.connect(lambda v, f=field: self._set_hotkey(f, v))
            edit.error.connect(self.show_hotkey_error)
        card = self._card("ГОРЯЧИЕ КЛАВИШИ", root)
        self._row(card, "Скриншот всего экрана", self.hk_full, "Сразу сохраняется в папку")
        self._divider(card)
        self._row(card, "Выделение области", self.hk_region)
        self._divider(card)
        self._row(card, "Сохранить повтор", self.hk_replay, "Последние минуты записи экрана")
        card.addWidget(self.hk_error)

        # --- Сохранение
        card = self._card("СОХРАНЕНИЕ", root)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        self.folder = QLineEdit(s.save_dir)
        self.folder.setReadOnly(True)
        self.folder.setMinimumWidth(200)
        browse = QPushButton("Изменить…")
        browse.clicked.connect(self._choose_folder)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        self._row(card, "Папка", folder_row)
        self._divider(card)

        fmt = Segmented([("png", "PNG"), ("jpg", "JPG"), ("webp", "WEBP")], s.image_format)
        fmt.changed.connect(self._set_format)
        self._row(card, "Формат", fmt)
        self._divider(card)

        q_row = QHBoxLayout()
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(1, 100)
        self.quality.setValue(s.quality)
        self.quality.setFixedWidth(170)
        self.quality_label = QLabel(f"{s.quality}%")
        self.quality_label.setFixedWidth(36)
        self.quality_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.quality.valueChanged.connect(lambda v: self.quality_label.setText(f"{v}%"))
        # Пишем на диск не на каждый шаг слайдера, а когда пользователь остановился
        self._q_timer = QTimer(self, singleShot=True, interval=300)
        self._q_timer.timeout.connect(lambda: self.store.set("quality", self.quality.value()))
        self.quality.valueChanged.connect(lambda _v: self._q_timer.start())
        q_row.addWidget(self.quality)
        q_row.addWidget(self.quality_label)
        self.quality_row = self._row(card, "Качество", q_row, "Для JPG и WEBP")
        self._update_quality_enabled()

        # --- Повтор экрана
        self._build_replay_card(root, s)

        # --- Поведение
        card = self._card("ПОВЕДЕНИЕ", root)
        self._row(card, "Показывать курсор на скриншоте", self._toggle("show_cursor"))
        self._divider(card)
        self._row(card, "Уведомление после сохранения", self._toggle("notify_on_save"))
        self._divider(card)
        self.autostart = QCheckBox()
        self.autostart.setChecked(autostart.is_enabled())
        self.autostart.toggled.connect(self._set_autostart)
        self.autostart_error = QLabel("")
        self.autostart_error.setObjectName("Error")
        self.autostart_error.hide()
        self._row(card, "Запускать при входе в систему", self.autostart)
        card.addWidget(self.autostart_error)
        self._divider(card)
        self.theme_box = QComboBox()
        for key, text in (("system", "Как в системе"), ("light", "Светлая"), ("dark", "Тёмная")):
            self.theme_box.addItem(text, key)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(s.theme)))
        self.theme_box.currentIndexChanged.connect(lambda _i: self.store.set("theme", self.theme_box.currentData()))
        self._row(card, "Тема", self.theme_box)

        # --- Низ
        root.addSpacing(4)
        foot = QHBoxLayout()
        open_btn = QPushButton("Открыть папку со скриншотами")
        open_btn.setObjectName("Link")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._open_folder)
        hint = QLabel("Сохраняется автоматически")
        hint.setObjectName("Muted")
        foot.addWidget(open_btn)
        foot.addStretch(1)
        foot.addWidget(hint)
        root.addLayout(foot)

        self._mics_loaded.connect(self._fill_microphones)
        self.theme.changed.connect(self.apply_theme)
        self.apply_theme()

    # ------------------------------------------------------------ layout utils
    def _card(self, title: str, root: QVBoxLayout) -> QVBoxLayout:
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        root.addWidget(label)
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(8)
        root.addWidget(frame)
        root.addSpacing(6)
        return lay

    def _row(self, card: QVBoxLayout, text: str, control, hint: str | None = None) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 2, 0, 2)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(QLabel(text))
        if hint:
            h = QLabel(hint)
            h.setObjectName("Muted")
            h.setStyleSheet("font-size: 11px;")
            col.addWidget(h)
        row.addLayout(col, 1)
        if isinstance(control, QHBoxLayout):
            row.addLayout(control)
        else:
            row.addWidget(control, 0, Qt.AlignmentFlag.AlignRight)
        card.addWidget(w)
        return w

    def _divider(self, card: QVBoxLayout) -> None:
        line = QFrame()
        line.setObjectName("Divider")
        card.addWidget(line)

    def _toggle(self, field: str) -> ToggleSwitch:
        t = ToggleSwitch()
        t.setChecked(bool(getattr(self.store.data, field)))
        t.toggled.connect(lambda v: self.store.set(field, v))
        t.setProperty("field", field)
        self._toggles.append(t)
        return t

    # ------------------------------------------------------------------ replay
    def _build_replay_card(self, root: QVBoxLayout, s) -> None:
        card = self._card("ПОВТОР ЭКРАНА", root)
        self._row(card, "Записывать повтор", self._toggle("replay_enabled"),
                  "Экран пишется в фоне, по сочетанию сохраняются последние минуты")
        self.replay_status = QLabel("")
        self.replay_status.setObjectName("Muted")
        self.replay_status.setStyleSheet("font-size: 11px;")
        card.addWidget(self.replay_status)

        # Всё, что ниже, активно только при включённой записи
        self.replay_opts = QWidget()
        box = QVBoxLayout(self.replay_opts)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        card.addWidget(self.replay_opts)

        self._divider(box)
        minutes = Segmented([(str(m), f"{m} мин") for m in range(1, 6)], str(s.replay_minutes))
        minutes.changed.connect(lambda v: self.store.set("replay_minutes", int(v)))
        self._row(box, "Длительность", minutes)
        self._divider(box)

        fps = Segmented([("30", "30 fps"), ("60", "60 fps")], str(s.replay_fps))
        fps.changed.connect(lambda v: self.store.set("replay_fps", int(v)))
        self._row(box, "Частота кадров", fps)
        self._divider(box)

        res = QComboBox()
        for key, text in ((0, "Исходное"), (1080, "1080p"), (720, "720p")):
            res.addItem(text, key)
        res.setCurrentIndex(max(0, res.findData(s.replay_height)))
        res.currentIndexChanged.connect(lambda _i: self.store.set("replay_height", res.currentData()))
        self._row(box, "Разрешение", res, "Меньше — легче файл и нагрузка")

        screens = QGuiApplication.screens()
        if len(screens) > 1:
            self._divider(box)
            mon = QComboBox()
            for i, scr in enumerate(screens):
                g = scr.geometry()
                mon.addItem(f"{i + 1}: {scr.name()} ({round(g.width() * scr.devicePixelRatio())}×"
                            f"{round(g.height() * scr.devicePixelRatio())})", i)
            mon.setCurrentIndex(max(0, mon.findData(s.replay_monitor)))
            mon.currentIndexChanged.connect(lambda _i: self.store.set("replay_monitor", mon.currentData()))
            self._row(box, "Монитор", mon)

        self._divider(box)
        self._row(box, "Звук системы", self._toggle("replay_system_audio"))
        self._divider(box)
        self._row(box, "Микрофон", self._toggle("replay_mic"))
        self.mic_box = QComboBox()
        self.mic_box.setMinimumWidth(260)
        self.mic_box.addItem("По умолчанию", "")
        self.mic_box.currentIndexChanged.connect(self._on_mic_chosen)
        self.mic_row = self._row(box, "Устройство", self.mic_box)
        self._load_microphones()

        self.store.changed.connect(self._on_store_changed)
        if self.replay is not None:
            self.replay.running_changed.connect(lambda _r: self._update_replay_ui())
        self._update_replay_ui()

    def _load_microphones(self) -> None:
        """Список микрофонов собираем в фоне — FFmpeg опрашивает устройства ~1 с."""
        import threading

        from ..replay import ffmpeg as ff

        def work():
            names = ff.list_microphones(ff.find_ffmpeg())
            self._mics_loaded.emit(names)

        threading.Thread(target=work, daemon=True).start()

    def _fill_microphones(self, names: list) -> None:
        current = self.store.data.replay_mic_device
        self.mic_box.blockSignals(True)
        self.mic_box.clear()
        self.mic_box.addItem("По умолчанию", "")
        for n in names:
            self.mic_box.addItem(n, n)
        if current and current not in names:  # устройство отключено — оставляем в списке
            self.mic_box.addItem(f"{current} (не подключён)", current)
        self.mic_box.setCurrentIndex(max(0, self.mic_box.findData(current)))
        self.mic_box.blockSignals(False)

    def _on_mic_chosen(self, _i: int) -> None:
        self.store.set("replay_mic_device", self.mic_box.currentData() or "")

    def _on_store_changed(self, name: str) -> None:
        # Настройку могли поменять из меню трея — синхронизируем тумблеры
        for t in self._toggles:
            if t.property("field") == name and t.isChecked() != getattr(self.store.data, name):
                t.setChecked(getattr(self.store.data, name))
        if name.startswith("replay_"):
            self._update_replay_ui()

    def _update_replay_ui(self) -> None:
        d = self.store.data
        self.replay_opts.setEnabled(d.replay_enabled)
        self.mic_row.setEnabled(d.replay_enabled and d.replay_mic)
        if not d.replay_enabled:
            text = "Выключено"
        elif self.replay is not None and self.replay.running:
            enc = {"h264_nvenc": "NVIDIA NVENC", "h264_amf": "AMD AMF", "h264_qsv": "Intel Quick Sync",
                   "h264_mf": "Media Foundation"}.get(self.replay.encoder or "", self.replay.encoder or "")
            text = f"● Идёт запись · кодер: {enc}"
        else:
            text = "Запуск…"
        self.replay_status.setText(text)

    # ---------------------------------------------------------------- actions
    def apply_theme(self) -> None:
        t = self.theme.tokens
        self.setStyleSheet(settings_stylesheet(t, icons.check_mark_file(t.accent_text)))
        for tg in self._toggles:
            tg.apply_theme(t)

    def show_hotkey_error(self, text: str) -> None:
        self.hk_error.setText(text)
        self.hk_error.setVisible(bool(text))

    def _set_hotkey(self, field: str, value: str) -> None:
        others = [getattr(self.store.data, f) for f in self._hotkey_edits if f != field]
        if value and value in others:
            self.show_hotkey_error("Это сочетание уже используется для другого действия")
            self._hotkey_edits[field].set_value(getattr(self.store.data, field))
            return
        self.show_hotkey_error("")
        self.store.set(field, value)

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Папка для скриншотов", self.store.data.save_dir)
        if path:
            self.folder.setText(path)
            self.store.set("save_dir", path)

    def _open_folder(self) -> None:
        folder = Path(self.store.data.save_dir)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _set_format(self, fmt: str) -> None:
        self.store.set("image_format", fmt)
        self._update_quality_enabled()

    def _update_quality_enabled(self) -> None:
        self.quality_row.setEnabled(self.store.data.image_format in ("jpg", "webp"))

    def _set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
            self.store.set("autostart", enabled)
            self.autostart_error.hide()
        except OSError as exc:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(not enabled)
            self.autostart.blockSignals(False)
            self.autostart_error.setText(f"Не удалось изменить автозапуск: {exc}")
            self.autostart_error.show()

    def present(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def sizeHint(self) -> QSize:
        return QSize(560, 760)
