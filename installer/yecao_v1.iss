; 野草 V1 本地营业 · Inno Setup 6 安装脚本
; 编译前请先运行：installer\prepare_dist.bat
; 编译：用 Inno Setup 打开本文件，或 ISCC.exe yecao_v1.iss

#define MyAppName "野草本地营业"
#define MyAppNameEn "YecaoST"
#define MyAppVersion "1.01"
#define MyAppPublisher "野草系统"
#define MyAppURL "https://yichbo.com"
#define MyAppExeName "启动野草.bat"
#define StagingDir "staging\\app"

[Setup]
AppId={{8F3C2A71-9B4E-4D6A-A1F0-7E5C91D2B8A3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={code:GetDefaultInstallDir}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 允许非管理员安装到 D 盘/用户目录
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=野草本地营业_V1.01_安装包
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
CloseApplications=no
RestartApplications=no
DirExistsWarning=no
UsePreviousAppDir=yes
; 卸载时不主动删用户后来产生的营业数据（见 [Dirs] uninsneveruninstall）

[Languages]
; 简体中文语言包正本在 E 盘开发者规范目录（本机 Inno 自带 Languages 里没有）
Name: "chinesesimplified"; MessagesFile: "E:\DeveloperProfile我的专用规范\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked
Name: "autostart"; Description: "开机时启动野草（托盘）"; GroupDescription: "附加选项:"; Flags: unchecked

[Files]
; 发布目录整包复制（由 prepare_dist 生成，已含 .venv）
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\backup"; Flags: uninsneveruninstall
Name: "{app}\media"; Flags: uninsneveruninstall
Name: "{app}\logs"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\启动野草"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\本机忘记密码重置"; Filename: "{app}\本机忘记密码重置.bat"; WorkingDir: "{app}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"; WorkingDir: "{app}"
Name: "{group}\卸载野草本地营业"; Filename: "{uninstallexe}"
Name: "{autodesktop}\启动野草"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; 开机自启（当前用户）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "YecaoST"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\首次准备数据库.bat"; StatusMsg: "正在初始化营业数据库…"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动野草"; Flags: nowait postinstall skipifsilent shellexec

[Code]
function DriveExists(const Drive: String): Boolean;
begin
  Result := DirExists(Drive + ':\');
end;

function GetDefaultInstallDir(Param: String): String;
begin
  { 优先 D 盘；没有则放到当前用户文档下 }
  if DriveExists('D') then
    Result := 'D:\YecaoST'
  else
    Result := ExpandConstant('{userdocs}\YecaoST');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Dir := WizardDirValue;
    { 装到 Windows 目录下给出白话警告，仍允许继续 }
    if (Pos(UpperCase(ExpandConstant('{win}')), UpperCase(Dir)) = 1) or
       (Pos('\PROGRAM FILES', UpperCase(Dir)) > 0) then
    begin
      if MsgBox('不建议装到系统盘的 Program Files 或 Windows 目录。' + #13#10 +
                '营业数据和备份最好放在普通文件夹（例如 D:\YecaoST）。' + #13#10 +
                '仍要继续吗？', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    MsgBox('卸载不会自动删除营业数据库与 backup 备份文件夹中的营业数据。' + #13#10 +
           '若要彻底清除，请手动删除安装目录里剩余的文件。', mbInformation, MB_OK);
  end;
end;
