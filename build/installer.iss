; Instalador do Minerador 3D (Inno Setup 6). Por usuário, sem pedir administrador.
; Compile com: iscc /DAppVersion=1.0.0 build\installer.iss   (build\build.py faz isso)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6D1E2F4A-7B3C-4C8D-9A5E-3F1B2C4D5E6F}
AppName=Minerador 3D
AppVersion={#AppVersion}
AppPublisher=leoplanello
AppPublisherURL=https://github.com/leoplanello/minerador-3d
DefaultDirName={localappdata}\Programs\Minerador3D
DefaultGroupName=Minerador 3D
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Minerador3D-Setup-{#AppVersion}
SetupIconFile=minerador.ico
UninstallDisplayIcon={app}\Minerador3D.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "..\dist\Minerador3D\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Minerador 3D"; Filename: "{app}\Minerador3D.exe"
Name: "{autodesktop}\Minerador 3D"; Filename: "{app}\Minerador3D.exe"; Tasks: desktopicon

[Run]
; instalação normal: oferece abrir; atualização automática (/RELAUNCH=1): reabre sozinho
Filename: "{app}\Minerador3D.exe"; Description: "Abrir o Minerador 3D"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Minerador3D.exe"; Flags: nowait; Check: Relaunch

[Code]
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

{ Os dados do usuário (banco, produtos, perfis do Chrome) ficam em %LOCALAPPDATA%\Minerador3D\data e não são tocados na atualização nem na desinstalação. }
