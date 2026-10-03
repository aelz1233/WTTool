#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{D7F5651E-6A74-47CD-A931-A3C136469A83}
AppName=WT Flight
AppVersion={#AppVersion}
AppPublisher=WT Flight
DefaultDirName={code:DefaultInstallDir}
DefaultGroupName=WT Flight
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release
OutputBaseFilename=WT-Flight-Setup-{#AppVersion}
SetupIconFile=..\wtflight\resources\wt-flight.ico
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
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

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
Filename: "{app}\WT Flight.exe"; Description: "{cm:LaunchProgram,WT Flight}"; Flags: nowait postinstall skipifsilent

[Code]
function DefaultInstallDir(Param: String): String;
begin
  if DirExists('D:\') then
    Result := 'D:\WT Flight'
  else
    Result := ExpandConstant('{localappdata}\Programs\WT Flight');
end;
