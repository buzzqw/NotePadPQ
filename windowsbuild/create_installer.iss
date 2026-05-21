; create_installer.iss
; Script Inno Setup 6 per NotePadPQ
; Crea un installer .exe professionale da una delle cartelle dist\
;
; Uso da linea di comando:
;   ISCC.exe /DMyAppVersion="0.9.10" /DEdition="Full" create_installer.iss
;   ISCC.exe /DMyAppVersion="0.9.10" /DEdition="Lite" create_installer.iss
;
; Nota: i percorsi usano ..\dist\NotePadPQ_Full o NotePadPQ_Lite
;       quindi va eseguito dalla cartella windowsbuild\

#ifndef MyAppVersion
  #define MyAppVersion "0.9.10"
#endif

#ifndef Edition
  #define Edition "Full"
#endif

#define MyAppName      "NotePadPQ"
#define MyAppPublisher "NotePadPQ"
#define MyAppURL       "https://github.com/azanzani/NotePadPQ"
#define MyAppExeName   "NotePadPQ.exe"
#define SourceDir      "..\dist\NotePadPQ_" + Edition
#define OutputDir      "..\dist"

[Setup]
AppId={{A3F2B1C4-8D7E-4F9A-B2C1-D5E6F7A8B9C0}
AppName={#MyAppName} ({#Edition})
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} ({#Edition})
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\EUPL-1.2 EN.txt
OutputDir={#OutputDir}
OutputBaseFilename=NotePadPQ_v{#MyAppVersion}_{#Edition}_Setup
SetupIconFile=..\icons\NotePadPQ.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64

; Crea associazione file per tipi comuni di testo
ChangesAssociations=yes

[Languages]
Name: "english";   MessagesFile: "compiler:Default.isl"
Name: "italian";   MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon";    Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode
Name: "associate_txt";  Description: "Associa file .txt a NotePadPQ"; GroupDescription: "Associazioni file:"; Flags: unchecked
Name: "associate_md";   Description: "Associa file .md e .markdown a NotePadPQ"; GroupDescription: "Associazioni file:"; Flags: unchecked
Name: "associate_py";   Description: "Associa file .py a NotePadPQ"; GroupDescription: "Associazioni file:"; Flags: unchecked

[Files]
; Copia l'intera cartella dist\NotePadPQ_<Edition>\
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";     Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Associazione .txt
Root: HKA; Subkey: "Software\Classes\.txt\OpenWithProgids"; ValueType: string; ValueName: "NotePadPQ.txt"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate_txt
Root: HKA; Subkey: "Software\Classes\NotePadPQ.txt"; ValueType: string; ValueName: ""; ValueData: "Text Document"; Flags: uninsdeletekey; Tasks: associate_txt
Root: HKA; Subkey: "Software\Classes\NotePadPQ.txt\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate_txt
Root: HKA; Subkey: "Software\Classes\NotePadPQ.txt\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate_txt

; Associazione .md
Root: HKA; Subkey: "Software\Classes\.md\OpenWithProgids"; ValueType: string; ValueName: "NotePadPQ.md"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate_md
Root: HKA; Subkey: "Software\Classes\NotePadPQ.md"; ValueType: string; ValueName: ""; ValueData: "Markdown Document"; Flags: uninsdeletekey; Tasks: associate_md
Root: HKA; Subkey: "Software\Classes\NotePadPQ.md\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate_md
Root: HKA; Subkey: "Software\Classes\NotePadPQ.md\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate_md

; Associazione .py
Root: HKA; Subkey: "Software\Classes\.py\OpenWithProgids"; ValueType: string; ValueName: "NotePadPQ.py"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate_py
Root: HKA; Subkey: "Software\Classes\NotePadPQ.py"; ValueType: string; ValueName: ""; ValueData: "Python Script"; Flags: uninsdeletekey; Tasks: associate_py
Root: HKA; Subkey: "Software\Classes\NotePadPQ.py\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associate_py
Root: HKA; Subkey: "Software\Classes\NotePadPQ.py\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associate_py

; Voce "Apri con NotePadPQ" nel menu contestuale per tutti i file
Root: HKA; Subkey: "Software\Classes\*\shell\NotePadPQ"; ValueType: string; ValueName: ""; ValueData: "Apri con NotePadPQ"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\*\shell\NotePadPQ"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKA; Subkey: "Software\Classes\*\shell\NotePadPQ\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
