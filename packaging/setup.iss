#ifndef ProjectRoot
  #define ProjectRoot ".."
#endif
#ifndef AppVersion
  #define AppVersion "1.3.4"
#endif
#ifndef ReleaseName
  #define ReleaseName "PDFedit-" + AppVersion
#endif
#define SourceRelease ProjectRoot + "\dist\" + ReleaseName

[Setup]
AppId={{C05DAF4C-6C99-4453-9A6C-23C417726D72}
AppName=合页
AppVersion={#AppVersion}
AppVerName=合页 {#AppVersion}
AppPublisher=合页
DefaultDirName={localappdata}\Programs\Heye
DisableDirPage=no
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
AllowNetworkDrive=no
CloseApplications=no
RestartApplications=no
UninstallDisplayName=合页 {#AppVersion}
UninstallDisplayIcon={app}\合页.exe
OutputDir={#ProjectRoot}\releases
OutputBaseFilename=合页-{#AppVersion}-安装程序
SetupIconFile={#ProjectRoot}\assets\app.ico
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110,100
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=合页 图片与 PDF 合并 安装程序
VersionInfoProductName=合页
VersionInfoProductVersion={#AppVersion}
DirExistsWarning=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "{#ProjectRoot}\packaging\ChineseSimplified.isl"

[Messages]
WelcomeLabel2=将安装合页 {#AppVersion}：把图片和 PDF 按页排序合并为 PDF，并添加文字或图片水印。%n%n软件自带运行环境，无需 Python，无需联网。请选择有写入权限的本地文件夹。
SelectDirLabel3=软件及运行数据将保存在所选文件夹中。
FinishedLabel=合页已安装完成。%n%n打开安装目录中的“合页.exe”即可使用。安装目录内的“使用说明.txt”包含操作和备份说明。

[Tasks]
Name: "mergecontext"; Description: "添加图片和 PDF 右键菜单：合并为 PDF（合页）"; GroupDescription: "使用方式："
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "使用方式："; Flags: unchecked

[Files]
Source: "{#SourceRelease}\{#ReleaseName}.exe"; DestDir: "{app}"; DestName: "合页.exe"; Flags: ignoreversion
Source: "{#SourceRelease}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRelease}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRelease}\使用说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRelease}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRelease}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\packaging\使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\合页"; Filename: "{app}\合页.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\合页.exe"; Parameters: "--install-menu"; Tasks: mergecontext; Flags: runhidden waituntilterminated
Filename: "{app}\合页.exe"; Description: "立即运行合页"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\合页.exe"; Parameters: "--uninstall-menu"; Flags: runhidden waituntilterminated; Check: MenuOwnedByThisInstall; RunOnceId: "RemoveOwnedMergeMenu"

[Code]
function GetFileAttributesW(FileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function InstallationPathError: String;
var
  Folder, Parent: String;
  Attributes: Cardinal;
begin
  Result := '';
  Folder := ExpandFileName(ExpandConstant('{app}'));
  if (Length(Folder) <= 3) or (Copy(Folder, 2, 2) <> ':\') then
  begin
    Result := '请选择本地磁盘的子文件夹。';
    Exit;
  end;
  while Length(Folder) > 0 do
  begin
    Attributes := GetFileAttributesW(Folder);
    if (Attributes <> $FFFFFFFF) and ((Attributes and $400) <> 0) then
    begin
      Result := '安装目录及其上级不能使用符号链接或 junction，请选择普通本地文件夹。';
      Exit;
    end;
    Parent := ExtractFileDir(RemoveBackslashUnlessRoot(Folder));
    if Parent = Folder then Break;
    Folder := Parent;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var ErrorMessage: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    ErrorMessage := InstallationPathError;
    Result := ErrorMessage = '';
    if not Result then MsgBox(ErrorMessage, mbError, MB_OK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := InstallationPathError;
end;

function MenuOwnedByThisInstall: Boolean;
var Command, Expected: String;
begin
  Result := False;
  if RegQueryStringValue(HKCU,
    'Software\Classes\SystemFileAssociations\.png\shell\PDFedit.Merge\command',
    '', Command) then
  begin
    Expected := ExpandConstant('{app}\合页.exe');
    Result := (CompareText(Command, '"' + Expected + '" "%1"') = 0) or
              (CompareText(Command, Expected + ' "%1"') = 0);
  end;
end;
