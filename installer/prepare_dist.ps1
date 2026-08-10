# 准备 Inno 安装用的发布目录：代码 + 内嵌 .venv（不含开发机营业库/备份）
# 本文件须 UTF-8 带 BOM，否则本机 Windows PowerShell 会把中文文件名写乱
$ErrorActionPreference = 'Stop'

$InstallerDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $InstallerDir
$StagingRoot = Join-Path $InstallerDir 'staging'
$AppDir = Join-Path $StagingRoot 'app'
$VenvSrc = Join-Path $ProjectRoot '.venv'
$ReqFile = Join-Path $ProjectRoot 'requirements.txt'

Write-Host "项目根目录: $ProjectRoot"
Write-Host "发布目录: $AppDir"

if (-not (Test-Path $VenvSrc)) {
    throw "找不到项目虚拟环境：$VenvSrc 。请先在本机创建 .venv 并 pip install -r requirements.txt"
}
if (-not (Test-Path $ReqFile)) {
    throw "找不到 requirements.txt"
}

# 清空旧 staging
if (Test-Path $StagingRoot) {
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null

function Copy-TreeFiltered {
    param(
        [string]$Source,
        [string]$Dest,
        [string[]]$ExcludeDirNames
    )
    if (-not (Test-Path $Source)) { return }
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        if ($_.PSIsContainer) {
            if ($ExcludeDirNames -contains $_.Name) { return }
            Copy-TreeFiltered -Source $_.FullName -Dest (Join-Path $Dest $_.Name) -ExcludeDirNames $ExcludeDirNames
        } else {
            # 测试文件与开发机托盘密码不进安装包
            if ($_.Name -like 'test_*.py') { return }
            if ($_.Name -like '*_test.py') { return }
            if ($_.Name -eq 'tray_local_settings.json') { return }
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Dest $_.Name) -Force
        }
    }
}

# 整夹不进 V1 安装包（私人材料 / 开发工具 / 空夹等）
$ExcludeDirs = @(
    '.git', '.venv', 'venv', 'env', 'backup', 'logs', 'media', 'staticfiles',
    '__pycache__', '.cursor', '.vscode', 'installer', 'dist', 'build', 'owner_toolkit',
    'node_modules', '.pytest_cache', 'htmlcov', 'agent-transcripts', 'test_media_dbg2',
    'private', 'scripts', 'tools'
)

# 根目录单个文件不进包（开发残留 / 本机备忘 / 认证名录 / Git 元数据 / 仓库手册正本等）
$ExcludeRootFiles = @(
    '服务器启动命令以及网址等.txt',
    '_恢复旧聊天窗口.bat',
    '_restore_cursor_chats.py',
    'cursor聊天记录.md',
    '新建文本文档.txt',
    '规则模板-developer-profile.mdc',
    'CERTIFIED_DIRECTORY.md',
    '_qr_fixed.pdf',
    'owner_toolkit.zip',
    '野草系统-正式上线前清查备忘录.md',
    '无为系统-核心规则速查手册.md',
    '.gitignore',
    '.gitattributes',
    '.env.example',
    '野草系统-核心规则速查手册.md',
    '野草系统-数据安全与隐私说明.md',
    '野草系统-品牌标识说明.md',
    '野草数据安全·白话总览.md'
)

Write-Host "复制程序文件…"
Get-ChildItem -LiteralPath $ProjectRoot -Force | ForEach-Object {
    $name = $_.Name
    if ($ExcludeDirs -contains $name) { return }
    if ($name -like '_cursor_chat_recovery*') { return }
    if ($name -eq 'db.sqlite3') { return }
    if ($name -like 'db.sqlite3*') { return }
    if ($name -eq '.env') { return }
    if ($name -like '.env.*') { return }
    if ($ExcludeRootFiles -contains $name) { return }
    if ($_.Name -like 'test_*.py') { return }

    $dest = Join-Path $AppDir $name
    if ($_.PSIsContainer) {
        Write-Host "  目录 $name"
        Copy-TreeFiltered -Source $_.FullName -Dest $dest -ExcludeDirNames @(
            '__pycache__', '.pytest_cache', 'tests_data', '.mypy_cache'
        )
        Get-ChildItem -LiteralPath $dest -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
    }
}

Write-Host "复制虚拟环境 .venv（较大，请稍候）…"
$VenvDest = Join-Path $AppDir '.venv'
& robocopy $VenvSrc $VenvDest /E /NFL /NDL /NJH /NJS /nc /ns /np `
    /XD '__pycache__' '.pytest_cache' `
    /XF '*.pyc' '*.pyo'
if ($LASTEXITCODE -ge 8) {
    throw "robocopy 复制 .venv 失败，退出码 $LASTEXITCODE"
}

Write-Host "写入安装专用文件并裁剪文档…"
New-Item -ItemType Directory -Path (Join-Path $AppDir 'backup') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $AppDir 'media') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $AppDir 'logs') -Force | Out-Null

$py = Join-Path $VenvSrc 'Scripts\python.exe'
$helper = Join-Path $InstallerDir '_write_staging_extras.py'
$env:YECAO_STAGING_APP = $AppDir
& $py $helper
if ($LASTEXITCODE -ne 0) {
    throw "写入安装专用中文文件失败"
}

# 确保发布用虚拟环境有 WhiteNoise，并收集静态文件（安装包 YECAO_DEBUG=0 须正式送样式）
Write-Host "安装/核对 WhiteNoise…"
$pyStaging = Join-Path $AppDir '.venv\Scripts\python.exe'
& $pyStaging -m pip install "whitenoise>=6.6,<7" -q
if ($LASTEXITCODE -ne 0) {
    throw "发布目录安装 whitenoise 失败"
}
Write-Host "收集静态文件 collectstatic…"
Push-Location $AppDir
$env:YECAO_DEBUG = '0'
& $pyStaging manage.py collectstatic --noinput
$collectExit = $LASTEXITCODE
Pop-Location
Remove-Item Env:YECAO_DEBUG -ErrorAction SilentlyContinue
if ($collectExit -ne 0) {
    throw "collectstatic 失败，退出码 $collectExit"
}
if (-not (Test-Path (Join-Path $AppDir 'staticfiles'))) {
    throw "collectstatic 后仍无 staticfiles 目录"
}

function Get-DirMB([string]$p) {
    if (-not (Test-Path $p)) { return 0 }
    $sum = (Get-ChildItem -LiteralPath $p -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if (-not $sum) { return 0 }
    return [math]::Round($sum / 1MB, 1)
}

$appMb = Get-DirMB $AppDir
$venvMb = Get-DirMB (Join-Path $AppDir '.venv')
Write-Host ""
Write-Host "发布目录准备完成。"
Write-Host "  合计约 ${appMb} MB（其中 .venv 约 ${venvMb} MB）"
Write-Host "  路径: $AppDir"
