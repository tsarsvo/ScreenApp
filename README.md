<p align="center"><img src="kadr/resources/logo.png" width="96" alt="Kadr"></p>

<h1 align="center">Kadr</h1>
<p align="center">Минималистичное кроссплатформенное приложение для скриншотов — аналог Lightshot.</p>

<p align="center">
  <img src="docs/overlay-light.png" width="49%"> <img src="docs/overlay-dark.png" width="49%">
</p>

## Возможности

- **Весь экран по горячей клавише**: файл сразу сохраняется в выбранную папку, без промежуточных окон. Если мониторов несколько, они склеиваются в один снимок в том же расположении, что и на рабочем столе.
- **Выделение области**: плавное затемнение фона вокруг выделения, ручки для изменения размера, перемещение, размер в пикселях. Простой клик выделяет весь экран.
- **Инструменты рисования**: кисть, стрелка, прямоугольник, овал, текст. Цвет выбирается из палитры, толщина — слайдером или **Ctrl + колесо мыши**. С **Shift** получаются квадрат/круг и стрелка с шагом 45°.
- **Undo / Redo**: кнопки «Назад»/«Вперёд» на панели, **Ctrl+Z**, **Ctrl+Y** / **Ctrl+Shift+Z**.
- **Результат**: копирование в буфер (**Ctrl+C** / **Enter** / двойной клик) или сохранение в папку (**Ctrl+S**).
- **Настройки**: горячие клавиши, папка, формат PNG / JPG / WEBP с качеством, курсор на снимке, автозапуск, тема.
- **Значок в трее** (на macOS — в строке меню): клик открывает настройки, меню — захват, папку и выход.
- Светлая и тёмная темы (по умолчанию — как в системе), тонкие иконки в едином стиле и собственный логотип.

<p align="center">
  <img src="docs/settings-light.png" width="40%"> <img src="docs/settings-dark.png" width="40%">
</p>

---

## 1. Архитектура и стек

**Python 3.10+ и PySide6 (Qt 6)**

| Требование | Как решается | Почему не альтернатива |
|---|---|---|
| Кроссплатформенность | Qt работает нативно на Windows, macOS и Linux | C#/WPF — только Windows |
| Скорость и лёгкость | Qt рисует нативно, запуск за доли секунды, ~60–80 МБ ОЗУ | Electron тянет Chromium: 150–300 МБ и медленный холодный старт |
| Захват экрана | `QScreen.grabWindow()` с корректным HiDPI; запасной вариант — `mss` (BitBlt / CoreGraphics / XShm) | — |
| Глобальные хоткеи | Windows: нативный `RegisterHotKey` (без хуков и прав, сочетание «съедается»). macOS/Linux: `pynput` | В Electron есть `globalShortcut`, но всё остальное тяжелее |
| Рисование, прозрачность, анимации | `QPainter` с антиалиасингом, `QPropertyAnimation` | — |
| Трей, буфер обмена, диалоги | Всё есть в Qt | — |

### Как устроено

```
               ┌──────────── KadrApp (app.py) ────────────┐
 глобальный    │  трей · одна копия (QLocalServer) · тема │
 хоткей ──────▶│  HotkeyManager ──▶ capture_full / region │
               └──────┬───────────────────────┬───────────┘
                      │ full                   │ region
            grab_full_desktop()           grab_screens()
                      │                        │
                 save_image()          CaptureSession
                                  (по Overlay на каждый монитор)
                                        │
                        Overlay: выделение, фигуры, History
                        Toolbar + StylePopup (дочерние виджеты)
                                        │
                              render_selection() → QImage
                                  │                 │
                          copy_to_clipboard    save_image
```

Ключевые решения:

- **Отдельный оверлей на каждый монитор.** Так корректно работают экраны с разным масштабом (например, 100% и 200%). Выделение на одном мониторе сбрасывает выделение на остальных.
- **Двойная система координат.** Интерфейс работает в логических пикселях, снимок хранится в физических. При экспорте фрагмент вырезается в физических пикселях, а фигуры перерисовываются в том же масштабе, поэтому результат на Retina/4K остаётся чётким.
- **Панели — дочерние виджеты оверлея**, а не отдельные окна. Они не отбирают фокус, не прячутся за окном «поверх всех» и не требуют прав на новые окна.
- **Изменения в настройках применяются сразу** (записываются в JSON атомарно).
- **Одна копия приложения**: повторный запуск передаёт команду уже запущенному процессу. Например, `main.py --region` можно повесить на системное сочетание клавиш.

## 2. Структура проекта

```
ScreenApp/
├── main.py                     # точка входа: python main.py [--region|--full|--settings]
├── requirements.txt
├── kadr/
│   ├── __init__.py             # имя, id, версия
│   ├── app.py                  # контроллер: трей, одна копия, хоткеи, запуск захвата
│   ├── config.py               # Settings (dataclass) + хранение в JSON
│   ├── capture.py              # захват экранов, склейка мониторов, отрисовка курсора
│   ├── hotkeys.py              # модель сочетания + backend'ы Win32 / pynput
│   ├── autostart.py            # автозапуск: реестр / LaunchAgent / XDG autostart
│   ├── saver.py                # PNG/JPG/WEBP, уникальные имена, буфер обмена
│   ├── theme.py                # токены светлой/тёмной темы, QSS, системная тема
│   ├── icons.py                # тонкие SVG-иконки + логотип
│   ├── overlay/
│   │   ├── session.py          # оверлеи на все мониторы, общий результат
│   │   ├── overlay.py          # выделение, рисование, клавиатура, отрисовка, экспорт
│   │   ├── shapes.py           # кисть, стрелка, прямоугольник, овал, текст
│   │   ├── history.py          # undo / redo
│   │   └── toolbar.py          # плавающая панель и панель «цвет + толщина»
│   ├── ui/
│   │   ├── settings_window.py  # окно настроек
│   │   └── widgets.py          # ToggleSwitch, HotkeyEdit, Segmented
│   └── resources/              # logo.svg / .png / .ico (генерирует scripts/build.py)
├── scripts/build.py            # сборка .exe / .app через PyInstaller
├── tests/test_core.py          # тесты (pytest, работают без дисплея)
└── docs/                       # скриншоты для README
```

## 3. Установка и запуск

```bash
git clone https://github.com/tsarsvo/ScreenApp.git && cd ScreenApp
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

При первом запуске откроется окно настроек. Дальше приложение работает в трее.

| Действие | Windows / Linux | macOS |
|---|---|---|
| Выделить область | `PrtSc` | `Ctrl+Shift+2` |
| Весь экран → сразу в файл | `Shift+PrtSc` | `Ctrl+Shift+1` |

Сочетания можно поменять в настройках: нажмите на кнопку и затем нужное сочетание. `Esc` отменяет запись, `Backspace` отключает хоткей.

**Внутри оверлея:** `V` выделение/перемещение · `P` кисть · `A` стрелка · `R` прямоугольник · `E` овал · `T` текст · `Ctrl+колесо` толщина · `Ctrl+Z` / `Ctrl+Y` · `Ctrl+C` или `Enter` копировать · `Ctrl+S` сохранить · `Esc` или ПКМ закрыть. В режиме «Текст»: `Enter` завершает ввод, `Shift+Enter` переносит строку, `Ctrl+V` вставляет текст. На macOS вместо `Ctrl` используется `Cmd`.

### Особенности платформ

- **Windows 11.** Если `PrtSc` открывает системную «Ножницы», выключите это: *Параметры → Специальные возможности → Клавиатура → «Использовать PrtSc для открытия захвата экрана»*. Если не хотите, назначьте в Kadr другое сочетание.
- **macOS.** Нужны два разрешения в *Системные настройки → Конфиденциальность и безопасность*: **Запись экрана** (иначе на снимке будут только обои) и **Универсальный доступ / Мониторинг ввода** (для глобальных хоткеев). Выдайте их терминалу или собранному `Kadr.app` и перезапустите приложение.
- **Linux.** Полностью поддерживается X11. На Wayland программы не могут перехватывать глобальные клавиши и читать экран напрямую. Используйте сессию X11 или (частично) привяжите в настройках DE сочетание к команде `python /путь/main.py --region`. В GNOME для значка в трее нужно расширение *AppIndicator*. Для pynput может понадобиться `sudo apt install python3-xlib`.

### Тесты и сборка

```bash
pip install pytest
QT_QPA_PLATFORM=offscreen python -m pytest -q      # 14 тестов, дисплей не нужен

pip install pyinstaller
python scripts/build.py                              # → dist/Kadr.exe, dist/Kadr.app или dist/Kadr
```

## 4. Автозапуск на Windows / macOS / Linux

Галочка «Запускать при входе в систему» вызывает `kadr/autostart.py`. Модуль прописывает в автозагрузку ОС команду запуска текущей копии: путь к `.exe`/бинарнику для сборки или `pythonw main.py` при запуске из исходников. Если галочка включена, запись обновляется при каждом старте, поэтому переезд папки ничего не ломает. Права администратора ни на одной ОС не нужны.

### Windows — ключ реестра `Run`
```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
    Kadr = "C:\...\pythonw.exe" "C:\...\main.py"      (или "C:\...\Kadr.exe")
```
Пишется через стандартный модуль `winreg`. Используется `pythonw.exe`, поэтому окно консоли не появляется. Запись видна в *Диспетчер задач → Автозагрузка*, там же её можно отключить.

### macOS — LaunchAgent
Файл `~/Library/LaunchAgents/app.kadr.screenshot.plist`:
```xml
<dict>
  <key>Label</key><string>app.kadr.screenshot</string>
  <key>ProgramArguments</key><array><string>/path/to/python</string><string>/path/to/main.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
</dict>
```
`launchd` запускает агента при входе пользователя. Для подписанного `.app`, который распространяется через App Store, лучше использовать `SMAppService.mainApp.register()` (macOS 13+) через pyobjc. Для обычного распространения LaunchAgent проще и надёжнее.

### Linux — XDG Autostart
Файл `~/.config/autostart/kadr.desktop` (учитывается `$XDG_CONFIG_HOME`):
```ini
[Desktop Entry]
Type=Application
Name=Kadr
Exec="/usr/bin/python3" "/path/to/main.py"
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=2
```
Этот стандарт понимают GNOME, KDE Plasma, XFCE, Cinnamon, MATE и LXQt. Задержка в 2 секунды нужна, чтобы трей успел загрузиться. Для оконных менеджеров без поддержки XDG (i3, bspwm) добавьте `main.py` в их конфиг, например `exec` в i3.
