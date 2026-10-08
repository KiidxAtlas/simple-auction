; Inno Setup definition for the per-user Simple Auction installer.
; The release build passes the project version as /DAppVersion=<version>.
#ifndef AppVersion
  #error AppVersion must be supplied by scripts/build_installer.py
#endif

#define AppName "Simple Auction"
#define AppExeName "SimpleAuction.exe"
#define AppIdValue "{{757059EE-506A-44D2-A82E-9B1892DF0A8A}}"

[Setup]
AppId={#AppIdValue}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=KiidxAtlas
AppPublisherURL=https://github.com/KiidxAtlas/simple-auction
AppSupportURL=https://github.com/KiidxAtlas/simple-auction/issues
AppUpdatesURL=https://github.com/KiidxAtlas/simple-auction/releases
DefaultDirName={localappdata}\Programs\Simple Auction
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SimpleAuction-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Uninstallable=yes
CloseApplications=yes
RestartApplications=no
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\SimpleAuction\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall
