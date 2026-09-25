; Установщик Kadr для Windows (Inno Setup 6).
; Собирается автоматически из scripts/build.py:  iscc /DAppVersion=1.0.0 installer\kadr.iss
; Ставится для текущего пользователя — права администратора не нужны.
; Файл хранится в UTF-8 с BOM — иначе Inno Setup прочитает кириллицу как ANSI.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F2A7C1E-4B8D-4E3A-9C51-7D0B2E8F4A61}
AppName=Kadr
AppVersion={#AppVersion}
AppPublisher=Kadr
AppPublisherURL=https://github.com/tsarsvo/ScreenApp
AppSupportURL=https://github.com/tsarsvo/ScreenApp/issues
AppUpdatesURL=https://github.com/tsarsvo/ScreenApp/releases
AppCopyright=Kadr
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Kadr — установка
VersionInfoProductName=Kadr
DefaultDirName={localappdata}\Programs\Kadr
DefaultGroupName=Kadr
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Kadr-Setup
SetupIconFile=..\kadr\resources\logo.ico
UninstallDisplayIcon={app}\Kadr.exe
UninstallDisplayName=Kadr
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
; Фирменное оформление: баннер слева на приветствии/финале и логотип в шапке страниц.
; Картинки рисует scripts/build.py (installer/generated), несколько размеров — под масштаб экрана.
DisableWelcomePage=no
WizardImageFile=generated\wizard-164.bmp,generated\wizard-246.bmp,generated\wizard-328.bmp
WizardSmallImageFile=generated\small-55.bmp,generated\small-83.bmp,generated\small-110.bmp
WizardImageStretch=yes
ShowLanguageDialog=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; При обновлении закрыть запущенный Kadr
CloseApplications=force

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Messages]
ru.WelcomeLabel1=Установка Kadr
ru.WelcomeLabel2=Kadr — лёгкие скриншоты с рисованием и повтор последних минут экрана.%n%nПрограмма поселится в трее возле часов. Скриншот области — клавиша PrtSc, весь экран — Shift+PrtSc, сохранить повтор — Alt+Shift+R.%n%nНажмите «Далее», чтобы продолжить.
ru.FinishedHeadingLabel=Kadr установлен
ru.FinishedLabel=Значок Kadr появится в трее возле часов. Нажмите на него, чтобы открыть настройки.
ru.ClickFinish=Нажмите «Завершить», чтобы закрыть мастер.

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать Kadr при входе в Windows"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\Kadr\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Kadr"; Filename: "{app}\Kadr.exe"
Name: "{autodesktop}\Kadr"; Filename: "{app}\Kadr.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kadr.exe"; Description: "{cm:LaunchProgram,Kadr}"; Flags: nowait postinstall skipifsilent
; Автообновление ставит новую версию тихо — после этого запускаем Kadr снова
Filename: "{app}\Kadr.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Kadr.exe /F"; Flags: runhidden; RunOnceId: "StopKadr"

[Registry]
; Галочка «Запускать при входе в Windows» (её же потом можно менять в настройках программы)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Kadr"; ValueData: """{app}\Kadr.exe"""; Tasks: autostart; Flags: uninsdeletevalue
; Убираем запись автозапуска (её создаёт галочка в настройках) при удалении программы
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Kadr"; Flags: uninsdeletevalue dontcreatekey
