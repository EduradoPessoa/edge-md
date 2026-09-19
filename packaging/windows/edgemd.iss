; Instalador do EdgeMD para Windows, para o Inno Setup 6 ou superior.
;
; Compilar:
;   iscc packaging\windows\edgemd.iss
;
; Gera um instalador por usuário (sem UAC) que:
;   * copia o programa para %LOCALAPPDATA%\Programs\EdgeMD;
;   * cria atalhos no Menu Iniciar e, opcionalmente, na área de trabalho;
;   * registra a associação de .md em HKEY_CURRENT_USER;
;   * deixa um desinstalador que desfaz tudo, inclusive as associações.
;
; Antes de compilar, gere o bundle:
;   pyinstaller edgemd.spec --noconfirm --clean
;
; Sobre o modo de instalação: PrivilegesRequired=lowest instala só para o
; usuário atual, que é o que combina com o app — ele nunca pede administrador
; para nada. Instalar para todos exigiria UAC e gravaria em HKLM/Arquivos de
; Programas, contrariando o resto do projeto.

#define AppName "EdgeMD"
#define AppVersion "0.1.0"
#define AppPublisher "Eduardo Maurício Pessoa de Souza"
#define AppURL "https://github.com/EduradoPessoa/edge-md"
#define AppExeName "edgemd.exe"
#define SourceDir "..\..\dist\edgemd"

[Setup]
AppId={{8F1C4A62-5B7D-4E31-9A2C-7D6E1B0F3A54}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Por usuário: sem UAC, e alinhado com o fato de o app não pedir admin.
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=EdgeMD-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\..\src\edgemd\resources\icons\edgemd.ico
LicenseFile=..\..\LICENSE
; O aplicativo roda com a janela fechando para a bandeja; o instalador não
; precisa saber disso, mas o desinstalador precisa encerrá-lo.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; O bundle inteiro, gerado pelo PyInstaller.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; "Abrir com" já funciona após a instalação; tornar padrão é escolha do
; usuário, e o app oferece isso no menu Ferramentas.
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
; --- Tipo de documento (ProgID) -------------------------------------------
Root: HKCU; Subkey: "Software\Classes\EdgeMD.Document"; ValueType: string; ValueName: ""; ValueData: "Documento Markdown"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\EdgeMD.Document"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Documento Markdown"
Root: HKCU; Subkey: "Software\Classes\EdgeMD.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"
Root: HKCU; Subkey: "Software\Classes\EdgeMD.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""

; --- Extensões: entra em "Abrir com" sem roubar o padrão atual -------------
; OpenWithProgids é uma lista de VALORES nomeados, não de subchaves.
Root: HKCU; Subkey: "Software\Classes\.md\OpenWithProgids"; ValueType: none; ValueName: "EdgeMD.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.markdown\OpenWithProgids"; ValueType: none; ValueName: "EdgeMD.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mdown\OpenWithProgids"; ValueType: none; ValueName: "EdgeMD.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mkd\OpenWithProgids"; ValueType: none; ValueName: "EdgeMD.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mkdn\OpenWithProgids"; ValueType: none; ValueName: "EdgeMD.Document"; ValueData: ""; Flags: uninsdeletevalue

; --- Capabilities: aparece em Configurações > Aplicativos padrão ----------
Root: HKCU; Subkey: "Software\EdgeMD\EdgeMD\Capabilities"; ValueType: string; ValueName: ""; ValueData: "EdgeMD"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\EdgeMD\EdgeMD\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "EdgeMD"
Root: HKCU; Subkey: "Software\EdgeMD\EdgeMD\Capabilities\FileAssociations"; ValueType: string; ValueName: ".md"; ValueData: "EdgeMD.Document"
Root: HKCU; Subkey: "Software\EdgeMD\EdgeMD\Capabilities\FileAssociations"; ValueType: string; ValueName: ".markdown"; ValueData: "EdgeMD.Document"
Root: HKCU; Subkey: "Software\EdgeMD\EdgeMD\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mdown"; ValueData: "EdgeMD.Document"
Root: HKCU; Subkey: "Software\EdgeMD\EdgeMD\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mkd"; ValueData: "EdgeMD.Document"
Root: HKCU; Subkey: "Software\EdgeMD\EdgeMD\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mkdn"; ValueData: "EdgeMD.Document"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "EdgeMD"; ValueData: "Software\EdgeMD\EdgeMD\Capabilities"; Flags: uninsdeletevalue

[UninstallDelete]
; O bundle do PyInstaller cria arquivos que o Inno não rastreia (caches do Qt).
Type: filesandordirs; Name: "{app}"

[Code]
// O Windows só relê as associações se for avisado. Sem isto, os ícones e o
// programa padrão continuam desatualizados até o Explorer reiniciar.
procedure SHChangeNotify();
  external 'SHChangeNotify@shell32.dll stdcall';
  
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SHChangeNotify();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    SHChangeNotify();
end;
