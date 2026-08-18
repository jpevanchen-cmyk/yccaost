# 准备 Inno 安装用的发布目录：代码 + 可带走的内嵌 Python（不含开发机营业库/备份）
# 本文件须 UTF-8 带 BOM，否则本机 Windows PowerShell 会把中文文件名写乱
$ErrorActionPreference = 'Stop'

$InstallerDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $InstallerDir
$StagingRoot = Join-Path $InstallerDir 'staging'
$AppDir = Join-Path $StagingRoot 'app'
$VenvSrc = Join-Path $ProjectRoot '.venv'
$ReqFile = Join-Path $ProjectRoot 'requirements.txt'
$CacheDir = Join-Path $InstallerDir 'cache'
$EmbedZipName = 'python-3.11.9-embed-amd64.zip'
$EmbedUrl = "https://www.python.org/ftp/python/3.11.9/$EmbedZipName"
$GetPipName = 'get-pip.py'
$GetPipUrl = 'https://bootstrap.pypa.io/get-pip.py'

Write-Host "项目根目录: $ProjectRoot"
Write-Host "发布目录: $AppDir"

if (-not (Test-Path $VenvSrc)) {
    throw "找不到项目虚拟环境：$VenvSrc 。请先在本机创建 .venv 并 pip install -r requirements.txt（打包脚本本身要用它写安装专用文件）"
}
if (-not (Test-Path $ReqFile)) {
    throw "找不到 requirements.txt"
}

function Get-CachedDownload([string]$Url, [string]$DestFile, [string]$What) {
    if (Test-Path $DestFile) {
        Write-Host "使用已缓存的 $What"
        return
    }
    Write-Host "正在下载 $What …"
    New-Item -ItemType Directory -Path (Split-Path -Parent $DestFile) -Force | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $DestFile -UseBasicParsing
    if (-not (Test-Path $DestFile)) {
        throw "下载失败：$What"
    }
}

function Add-TkinterFromFullPython([string]$DestDir) {
    # 官方精简包没有窗口零件；托盘控制台必须用它，须从本机完整 Python 拷入
    $devPy = Join-Path $VenvSrc 'Scripts\python.exe'
    $base = (& $devPy -c "import sys; print(sys.base_prefix)").Trim()
    if (-not $base) {
        throw "读不到本机完整 Python 路径，无法拷入窗口零件。"
    }
    $tclSrc = Join-Path $base 'tcl'
    $tkSrc = Join-Path $base 'Lib\tkinter'
    $pydSrc = Join-Path $base 'DLLs\_tkinter.pyd'
    if (-not (Test-Path $tclSrc) -or -not (Test-Path $tkSrc) -or -not (Test-Path $pydSrc)) {
        throw "本机完整 Python 里找不到窗口零件（tcl / tkinter），无法打进安装包。路径：$base"
    }
    Write-Host "拷入窗口零件（托盘控制台用）…"
    $tclDest = Join-Path $DestDir 'tcl'
    if (Test-Path $tclDest) {
        Remove-Item -LiteralPath $tclDest -Recurse -Force
    }
    Copy-Item -LiteralPath $tclSrc -Destination $tclDest -Recurse -Force
    $libDest = Join-Path $DestDir 'Lib'
    New-Item -ItemType Directory -Path $libDest -Force | Out-Null
    $tkDest = Join-Path $libDest 'tkinter'
    if (Test-Path $tkDest) {
        Remove-Item -LiteralPath $tkDest -Recurse -Force
    }
    Copy-Item -LiteralPath $tkSrc -Destination $tkDest -Recurse -Force
    Get-ChildItem -LiteralPath $tkDest -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $pydSrc -Destination (Join-Path $DestDir '_tkinter.pyd') -Force
    $dllDir = Join-Path $base 'DLLs'
    Get-ChildItem -LiteralPath $dllDir -Filter 'tcl*.dll' -ErrorAction SilentlyContinue |
        Copy-Item -Destination $DestDir -Force
    Get-ChildItem -LiteralPath $dllDir -Filter 'tk*.dll' -ErrorAction SilentlyContinue |
        Copy-Item -Destination $DestDir -Force
    $zlib = Join-Path $dllDir 'zlib1.dll'
    if (Test-Path $zlib) {
        Copy-Item -LiteralPath $zlib -Destination (Join-Path $DestDir 'zlib1.dll') -Force
    }
}

function Install-PortablePython([string]$DestDir) {
    New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
    $zip = Join-Path $CacheDir $EmbedZipName
    $getPip = Join-Path $CacheDir $GetPipName
    Get-CachedDownload -Url $EmbedUrl -DestFile $zip -What "可带走的 Python 3.11.9"
    Get-CachedDownload -Url $GetPipUrl -DestFile $getPip -What "pip 安装脚本"

    if (Test-Path $DestDir) {
        Remove-Item -LiteralPath $DestDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    Write-Host "解压可带走的 Python 到发布目录…"
    Expand-Archive -LiteralPath $zip -DestinationPath $DestDir -Force

    $pth = Get-ChildItem -LiteralPath $DestDir -Filter "python*._pth" | Select-Object -First 1
    if (-not $pth) {
        throw "解压后找不到 python*._pth，内嵌包不完整。"
    }
    @(
        'python311.zip'
        '.'
        '..'
        'Lib'
        'Lib\site-packages'
        'import site'
        ''
    ) | Set-Content -LiteralPath $pth.FullName -Encoding ascii

    Add-TkinterFromFullPython -DestDir $DestDir

    $embedPy = Join-Path $DestDir 'python.exe'
    if (-not (Test-Path $embedPy)) {
        throw "解压后找不到 python.exe"
    }
    if (-not (Test-Path (Join-Path $DestDir 'pythonw.exe'))) {
        throw "解压后找不到 pythonw.exe"
    }

    Write-Host "为可带走的 Python 安装 pip…"
    & $embedPy $getPip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        throw "安装 pip 失败"
    }

    Write-Host "安装程序依赖（按 requirements.txt）…"
    & $embedPy -m pip install --retries 20 --timeout 120 -r $ReqFile "whitenoise>=6.6,<7"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "网上安装失败，改从本机已缓存的包装入…"
        $wheelDir = Join-Path $CacheDir 'wheels'
        New-Item -ItemType Directory -Path $wheelDir -Force | Out-Null
        $devPy = Join-Path $VenvSrc 'Scripts\python.exe'
        & $devPy -m pip download -r $ReqFile "whitenoise>=6.6,<7" -d $wheelDir
        if ($LASTEXITCODE -ne 0) {
            throw "下载依赖包到本地缓存失败"
        }
        & $embedPy -m pip install --no-index --find-links $wheelDir -r $ReqFile "whitenoise>=6.6,<7"
        if ($LASTEXITCODE -ne 0) {
            throw "安装依赖失败"
        }
    }

    Write-Host "核对可带走的 Python 能否独立运行…"
    & $embedPy -c "import django; print('django', django.get_version())"
    if ($LASTEXITCODE -ne 0) {
        throw "可带走的 Python 自检失败"
    }
    & $embedPy -c "import tkinter; print('tkinter ok')"
    if ($LASTEXITCODE -ne 0) {
        throw "窗口零件自检失败（托盘控制台打不开）"
    }
    $cfg = Join-Path $DestDir 'pyvenv.cfg'
    if (Test-Path $cfg) {
        throw "发布目录里不应再有会写死开发机路径的 pyvenv.cfg"
    }
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

Write-Host "安装可带走的 Python（不拷贝开发机 .venv）…"
$VenvDest = Join-Path $AppDir '.venv'
Install-PortablePython -DestDir $VenvDest

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

Write-Host "收集静态文件 collectstatic…"
$pyStaging = Join-Path $AppDir '.venv\python.exe'
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

$scanRoot = Join-Path $AppDir '.venv'
$scanFiles = Get-ChildItem -LiteralPath $scanRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Extension -in @('.cfg', '.pth') -or $_.Name -like '*._pth'
    }
$hit = $scanFiles | Select-String -Pattern 'C:\Users\user\AppData\Local\Programs\Python' -SimpleMatch -ErrorAction SilentlyContinue
if ($hit) {
    throw "发布目录运行环境仍含开发机 Python 路径，请检查打包脚本。"
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
