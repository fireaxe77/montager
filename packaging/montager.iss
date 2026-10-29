; Montager installer (Inno Setup 6). Built by packaging/make_release.py:
;   ISCC.exe /DAppVersion=9.3.1 /DSourceDir=<dist\Montager> /DOutDir=<folder> packaging\montager.iss
; Per-user install (no admin): %LOCALAPPDATA%\Programs\Montager. User data lives in %LOCALAPPDATA%\Montager\montage_data
; (settings, caches, logs) and is NOT removed by the uninstaller.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\dist\Montager"
#endif
#ifndef OutDir
  #define OutDir "..\build\release"
#endif

[Setup]
AppId={{6E0B2C5A-2F7D-4F6B-9C61-6D4E0E9A9B21}
AppName=Montager
AppVersion={#AppVersion}
AppVerName=Montager {#AppVersion}
AppPublisher=fireaxe77
AppPublisherURL=https://github.com/fireaxe77/montager
AppSupportURL=https://github.com/fireaxe77/montager/issues
AppUpdatesURL=https://github.com/fireaxe77/montager/releases/latest
DefaultDirName={localappdata}\Programs\Montager
DefaultGroupName=Montager
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=Montager-Setup-{#AppVersion}
SetupIconFile=assets\montager.ico
UninstallDisplayIcon={app}\Montager.exe
UninstallDisplayName=Montager {#AppVersion}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
; a new version replaces the old program files completely (never the user data, which is elsewhere)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Montager"; Filename: "{app}\Montager.exe"; WorkingDir: "{app}"; AppUserModelID: "fireaxe.montager"; Comment: "Kill montages from your clips"
Name: "{group}\Montager setup check"; Filename: "{app}\Montager-CLI.exe"; WorkingDir: "{app}"; Comment: "What is missing before Montager can make a montage"
Name: "{group}\Montager settings and logs folder"; Filename: "{localappdata}\Montager\montage_data"
Name: "{autodesktop}\Montager"; Filename: "{app}\Montager.exe"; WorkingDir: "{app}"; AppUserModelID: "fireaxe.montager"; Tasks: desktopicon

[Dirs]
Name: "{localappdata}\Montager\montage_data"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\Montager.exe"; Description: "Start Montager now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; only the program folder; %LOCALAPPDATA%\Montager (your settings, caches and logs) is kept
Type: filesandordirs; Name: "{app}\_internal"

[Messages]
FinishedLabel=Montager is installed.%n%nOn the first start it shows what is still missing (your clip folders, songs and in-game name). Your settings and caches are kept in %LOCALAPPDATA%\Montager, also when you uninstall.
