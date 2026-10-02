#define AppVersion "1.0.5"

[Setup]
AppId={{D7F5651E-6A74-47CD-A931-A3C136469A83}
AppName=WT Flight
AppVersion={#AppVersion}
AppPublisher=WT Flight
DefaultDirName=D:\WT Flight
DefaultGroupName=WT Flight
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release
OutputBaseFilename=WT-Flight-Setup-{#AppVersion}
SetupIconFile=..\data\wt-flight.ico
UninstallDisplayIcon={app}\WT Flight.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Dirs]
Name: "{userappdata}\WTFlightAssistant"
Name: "{userappdata}\WTFlightAssistant\sounds"
Name: "{userappdata}\WTFlightAssistant\logs"

[Files]
Source: "..\dist\WT Flight\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\WT Flight"; Filename: "{app}\WT Flight.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userprograms}\WT Flight"; Filename: "{app}\WT Flight.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\WT Flight.exe"; Description: "Запустить WT Flight"; Flags: nowait postinstall skipifsilent
