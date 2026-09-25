; Установщик Kadr для Windows (Inno Setup 6).
; Собирается автоматически из scripts/build.py:  iscc /DAppVersion=1.0.0 installer\kadr.iss
; Ставится для текущего пользователя — права администратора не нужны.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F2A7C1E-4B8D-4E3A-9C51-7D0B2E8F4A61}
AppName=Kadr
AppVersion={#AppVersion}
AppPublisher=Kadr
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
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; При обновлении закрыть запущенный Kadr
CloseApplications=force

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Kadr\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Kadr"; Filename: "{app}\Kadr.exe"
Name: "{autodesktop}\Kadr"; Filename: "{app}\Kadr.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kadr.exe"; Description: "{cm:LaunchProgram,Kadr}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Kadr.exe /F"; Flags: runhidden; RunOnceId: "StopKadr"

[Registry]
; Убираем запись автозапуска (её создаёт галочка в настройках) при удалении программы
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Kadr"; Flags: uninsdeletevalue dontcreatekey
