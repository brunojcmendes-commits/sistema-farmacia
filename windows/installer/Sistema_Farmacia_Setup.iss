#define MyAppName "Sistema Farmácia"
#define MyAppVersion "1.2.5"
#define MyAppPublisher "9º Batalhão de Saúde"

[Setup]
AppId={{845553B7-0FC9-44A7-8C2D-B17436017520}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SistemaFarmacia
DefaultGroupName=Sistema Farmácia
PrivilegesRequired=lowest
OutputDir=Saida
OutputBaseFilename=Sistema_Farmacia_Setup_1.2.5
SetupIconFile=Arquivos_do_Programa\Gerente_Farmacia.ico
UninstallDisplayIcon={app}\Gerente_Farmacia.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
AllowNoIcons=no
VersionInfoVersion=1.2.5.0
VersionInfoCompany=9º Batalhão de Saúde
VersionInfoDescription=Gerente Farmácia e Cliente Farmácia
VersionInfoProductName=Sistema Farmácia
VersionInfoProductVersion=1.2.5
VersionInfoCopyright=9º Batalhão de Saúde

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Types]
Name: "completa"; Description: "Instalação completa"
Name: "personalizada"; Description: "Instalação personalizada"; Flags: iscustom

[Components]
Name: "gerente"; Description: "Gerente Farmácia (Gerente e Administradores)"; Types: completa personalizada
Name: "cliente"; Description: "Cliente Farmácia (Solicitação de produtos)"; Types: completa personalizada

[Files]
Source: "Arquivos_do_Programa\Gerente_Farmacia.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: gerente
Source: "Arquivos_do_Programa\Gerente_Farmacia.ico"; DestDir: "{app}"; Flags: ignoreversion; Components: gerente
Source: "Arquivos_do_Programa\Cliente_Farmacia.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: cliente
Source: "Arquivos_do_Programa\Cliente_Farmacia.ico"; DestDir: "{app}"; Flags: ignoreversion; Components: cliente

[InstallDelete]
Type: files; Name: "{autodesktop}\Gestor Farmacia.lnk"
Type: files; Name: "{autodesktop}\Solicitacao de Material - Farmacia.lnk"
Type: files; Name: "{group}\Gestor Farmacia.lnk"
Type: files; Name: "{group}\Solicitacao de Material - Farmacia.lnk"

[Icons]
Name: "{autodesktop}\Gerente Farmácia"; Filename: "{app}\Gerente_Farmacia.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Gerente_Farmacia.ico"; Components: gerente
Name: "{autodesktop}\Cliente Farmácia"; Filename: "{app}\Cliente_Farmacia.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Cliente_Farmacia.ico"; Components: cliente
Name: "{group}\Gerente Farmácia"; Filename: "{app}\Gerente_Farmacia.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Gerente_Farmacia.ico"; Components: gerente
Name: "{group}\Cliente Farmácia"; Filename: "{app}\Cliente_Farmacia.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Cliente_Farmacia.ico"; Components: cliente

[Run]
Filename: "{app}\Gerente_Farmacia.exe"; Description: "Abrir Gerente Farmácia"; Flags: nowait postinstall skipifsilent; Components: gerente
Filename: "{app}\Cliente_Farmacia.exe"; Description: "Abrir Cliente Farmácia"; Flags: nowait postinstall skipifsilent unchecked; Components: cliente
