@echo off
rem Установка и запуск Kadr из исходников — просто дважды кликните по этому файлу.
rem Создаёт виртуальное окружение, ставит зависимости, скачивает FFmpeg
rem и делает ярлыки «Kadr» на рабочем столе и в меню «Пуск».
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Не найден Python. Установите Python 3.10 или новее с https://www.python.org/downloads/
    echo и отметьте галочку "Add python.exe to PATH".
    pause
    exit /b 1
)

echo [1/4] Виртуальное окружение...
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto :error

echo [2/4] Зависимости...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :error

echo [3/4] FFmpeg для записи повтора...
if not exist "kadr\bin\ffmpeg.exe" ".venv\Scripts\python.exe" scripts\fetch_ffmpeg.py || echo    Не удалось скачать FFmpeg: скриншоты работают, запись повтора - нет.

echo [4/4] Ярлыки...
set "TARGET=%~dp0.venv\Scripts\pythonw.exe"
set "SCRIPT=%~dp0main.py"
set "ICON=%~dp0kadr\resources\logo.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $l = $s.CreateShortcut((Join-Path $dir 'Kadr.lnk'));" ^
  "  $l.TargetPath = $env:TARGET; $l.Arguments = '\"' + $env:SCRIPT + '\"';" ^
  "  $l.WorkingDirectory = (Split-Path $env:SCRIPT); $l.IconLocation = $env:ICON; $l.Save() }"

echo.
echo Готово! Kadr запускается — значок появится в трее (возле часов).
echo Дальше запускайте его ярлыком "Kadr" на рабочем столе или в меню "Пуск".
start "" "%TARGET%" "%SCRIPT%"
timeout /t 4 >nul
exit /b 0

:error
echo.
echo Ошибка установки. Скопируйте текст выше и пришлите разработчику.
pause
exit /b 1
