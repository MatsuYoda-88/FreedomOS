; FreedomOS - Windows installer (Inno Setup 6)
; Built automatically by .github/workflows/build.yml. To build it yourself on Windows:
;   1. Build WiBro:  dotnet publish app\browser\src\FreedomOS.csproj -c Release -r win-x64 --self-contained true -o app\browser\builds\b0
;   2. Stamp it:     python installer\stamp_build.py
;   3. Compile:      iscc installer\FreedomOS.iss
; No admin needed - installs for your Windows user only, in %LOCALAPPDATA%\FreedomOS.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B0C2E8B-4F7A-4D51-9C3E-F5E0A1D7C935}
AppName=FreedomOS
AppVersion={#AppVersion}
AppVerName=FreedomOS {#AppVersion}
AppPublisher=MatsuYoda-88
AppPublisherURL=https://github.com/MatsuYoda-88/FreedomOS
AppSupportURL=https://github.com/MatsuYoda-88/FreedomOS/issues
DefaultDirName={localappdata}\FreedomOS
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=FreedomOS-Setup-{#AppVersion}
SetupIconFile=..\app\f35.ico
UninstallDisplayIcon={app}\f35.ico
UninstallDisplayName=FreedomOS
WizardStyle=modern
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a FreedomOS shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
; your settings + handbook are only written the first time, so updates never wipe your changes
Source: "..\app\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\app\crew handbook.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\app\*"; DestDir: "{app}"; Excludes: "config.json,crew handbook.txt,venv,engine,engine_vulkan,logs,memory,outputs,__pycache__,*.pyc,bin,obj,crew_key.txt"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{userdocs}\FreedomOS"; Flags: uninsneveruninstall

[Icons]
Name: "{userprograms}\FreedomOS\FreedomOS"; Filename: "{app}\FreedomOS.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\f35.ico"; Flags: runminimized
Name: "{userprograms}\FreedomOS\FreedomOS Setup (repair or add features)"; Filename: "{app}\FreedomOS Setup.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\f35.ico"
Name: "{userprograms}\FreedomOS\Edit the crew handbook"; Filename: "notepad.exe"; Parameters: """{app}\crew handbook.txt"""; IconFilename: "{app}\f35.ico"
Name: "{userprograms}\FreedomOS\Settings (config.json)"; Filename: "notepad.exe"; Parameters: """{app}\config.json"""
Name: "{userprograms}\FreedomOS\FreedomOS work folder"; Filename: "{userdocs}\FreedomOS"
Name: "{userprograms}\FreedomOS\Setup guide (online)"; Filename: "https://github.com/MatsuYoda-88/FreedomOS/blob/main/docs/SETUP.md"
Name: "{userprograms}\FreedomOS\Uninstall FreedomOS"; Filename: "{uninstallexe}"
Name: "{userdesktop}\FreedomOS"; Filename: "{app}\FreedomOS.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\f35.ico"; Flags: runminimized; Tasks: desktopicon

[Registry]
; FreedomOS adds this itself on first start (so it starts with Windows) - listed here so uninstall removes it
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "FreedomOS"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\FreedomOS Setup.cmd"; WorkingDir: "{app}"; Description: "Finish setup and start FreedomOS (downloads Python + the brain engine)"; Flags: postinstall shellexec nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""$p = 7777; try {{ $p = (Get-Content -Raw '{app}\config.json' | ConvertFrom-Json).port }} catch {{}}; try {{ Invoke-WebRequest -Method Post -UseBasicParsing -TimeoutSec 4 http://127.0.0.1:$p/shutdown | Out-Null }} catch {{}}; Start-Sleep 2"""; Flags: runhidden; RunOnceId: "StopServer"
Filename: "taskkill.exe"; Parameters: "/f /im FreedomOS.exe"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "taskkill.exe"; Parameters: "/f /im llama-server.exe"; Flags: runhidden; RunOnceId: "StopEngine"

[UninstallDelete]
; the big downloaded stuff (Python toolbox, engine, browser builds) goes too. Your Documents\FreedomOS folder stays.
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\engine"
Type: filesandordirs; Name: "{app}\engine_vulkan"
Type: filesandordirs; Name: "{app}\imagegen"
Type: filesandordirs; Name: "{app}\pixelshop\venv"
Type: filesandordirs; Name: "{app}\browser"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\FreedomOS startup.vbs"

[Messages]
WelcomeLabel2=This installs FreedomOS: your own local AI crew, a full-screen desktop, the WiBro browser, WiMix music, the Discord overlay, the Pixel Shop and file sync between your PCs.%n%nAfter the files are copied, a setup window downloads Python and the brain engine (internet needed, about 10 minutes).
