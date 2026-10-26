#define MyAppName "YouTube Downloader Pro"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "YouTube Downloader Pro"
#define MyAppExeName "YouTubeDownloader.exe"

[Setup]
AppId={{B7801DA8-7C74-4D67-8F1E-43C0A9B5E16A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\YouTube Downloader Pro
DefaultGroupName=YouTube Downloader Pro
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=YouTubeDownloader-Setup
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern dynamic
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
Uninstallable=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
VersionInfoDescription=Arabic desktop downloader for videos, playlists and audio.

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب"; GroupDescription: "اختصارات إضافية:"; Flags: unchecked

[Files]
Source: "dist\YouTubeDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\YouTube Downloader Pro"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\YouTube Downloader Pro"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل YouTube Downloader Pro"; Flags: nowait postinstall skipifsilent
