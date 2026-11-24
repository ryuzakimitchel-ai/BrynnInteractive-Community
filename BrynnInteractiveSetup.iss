#define MyAppName "Brynn Interactive"
#define MyAppVersion "0.60.12"
#define MyAppPublisher "Brynn Interactive"
#define MyAppExeName "BrynnInteractiveDesktop.exe"
#define MyBuildDir "dist\BrynnInteractiveDesktop"

[Setup]
AppId={{B8D7A2E5-619F-4B5A-99D9-A9A4F67E34D2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Instalador de Brynn Interactive
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
DefaultDirName={localappdata}\Programs\Brynn Interactive
DefaultGroupName=Brynn Interactive
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=installer_output
OutputBaseFilename=BrynnInteractive-Setup-0.60.12
SetupIconFile={#SourcePath}\brynn_default.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
AppVerName={#MyAppName} {#MyAppVersion}
CloseApplicationsFilter=BrynnInteractiveDesktop.exe
SetupLogging=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "{#MyBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Brynn Interactive"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Brynn Interactive"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Brynn Interactive"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ExistingInstallDir: string;
  ExistingVersion: string;
  UpgradeDetected: Boolean;

function ReadExistingInstall(): Boolean;
var
  Key: string;
begin
  Result := False;
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B8D7A2E5-619F-4B5A-99D9-A9A4F67E34D2}_is1';
  if RegQueryStringValue(HKCU, Key, 'InstallLocation', ExistingInstallDir) then
  begin
    RegQueryStringValue(HKCU, Key, 'DisplayVersion', ExistingVersion);
    Result := ExistingInstallDir <> '';
    exit;
  end;
  if RegQueryStringValue(HKLM, Key, 'InstallLocation', ExistingInstallDir) then
  begin
    RegQueryStringValue(HKLM, Key, 'DisplayVersion', ExistingVersion);
    Result := ExistingInstallDir <> '';
  end;
end;

function InitializeSetup(): Boolean;
begin
  UpgradeDetected := ReadExistingInstall();
  Result := True;
end;

procedure InitializeWizard();
begin
  if UpgradeDetected then
  begin
    WizardForm.WelcomeLabel1.Caption := 'Actualizar Brynn Interactive';
    WizardForm.WelcomeLabel2.Caption :=
      'Se detectó Brynn Interactive ' + ExistingVersion + ' en:' + #13#10 +
      ExistingInstallDir + #13#10#13#10 +
      'El instalador actualizará los archivos del programa en esa misma carpeta. ' +
      'Tus configuraciones, emotes, ranking, economía y demás datos de AppData no se borrarán.';
  end;
end;
