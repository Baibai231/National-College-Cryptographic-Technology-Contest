[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [string]$MeasureToken = "",
    [switch]$NoBrowser,
    [switch]$SkipInstall,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$venvRoot = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$pidPath = Join-Path $PSScriptRoot ".local-web.pid"
$stdoutPath = Join-Path $PSScriptRoot "local-web.stdout.log"
$stderrPath = Join-Path $PSScriptRoot "local-web.stderr.log"

function Stop-LocalDashboard {
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return
    }
    $rawRecord = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    try {
        $record = $rawRecord | ConvertFrom-Json -ErrorAction Stop
        $savedPid = [int]$record.pid
    } catch {
        throw "PID 文件格式无效，请确认没有旧服务后删除：$pidPath"
    }
    $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        $actualPath = $process.Path
        $actualRoot = [System.IO.Path]::GetFullPath([string]$record.project_root)
        $expectedRoot = [System.IO.Path]::GetFullPath($projectRoot)
        $allowedExecutables = @($venvPython, [string]$record.base_executable) |
            Where-Object { $_ } |
            ForEach-Object { [System.IO.Path]::GetFullPath($_) }
        $pathMatches = $actualPath -and
            ($allowedExecutables -contains [System.IO.Path]::GetFullPath($actualPath))
        $rootMatches = $actualRoot -eq $expectedRoot
        $recordedStart = [DateTimeOffset]::Parse([string]$record.started_at).UtcDateTime
        $actualStart = $process.StartTime.ToUniversalTime()
        $startMatches = [Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -le 10
        if ($pathMatches -and $rootMatches -and $startMatches) {
            Stop-Process -Id $savedPid -Force
            $process.WaitForExit()
        } else {
            throw "PID $savedPid 与本项目服务记录不一致，拒绝停止该进程。"
        }
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

if ($Stop) {
    Stop-LocalDashboard
    Write-Host "本地 Dashboard 已停止。"
    exit 0
}

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        & $launcher.Source -3 -m venv $venvRoot
    } else {
        $launcher = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $launcher) {
            throw "未找到 Python。请安装 Python 3.10+，然后重新运行本脚本。"
        }
        & $launcher.Source -m venv $venvRoot
    }
}

if (-not $SkipInstall) {
    & $venvPython -c "import fastapi, selenium, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "首次运行：正在安装项目依赖……"
        & $venvPython -m pip install -r "webapp\requirements-server.txt"
        if ($LASTEXITCODE -ne 0) {
            throw "依赖安装失败。"
        }
    }
}

$databaseArgs = @(
    "scripts\build_site_database.py",
    "--input", "reports\sites\sites_latest.jsonl"
)
$policyInput = Get-ChildItem -LiteralPath "reports\archive" -File |
    Where-Object { $_.BaseName -match '^full\d+_policy_\d{8}$' } |
    Sort-Object @{
        Expression = {
            if ($_.BaseName -match '_(\d{8})$') { [int64]$Matches[1] } else { 0 }
        }; Descending = $true
    }, @{
        Expression = {
            if ($_.BaseName -match '^full(\d+)_') { [int]$Matches[1] } else { 0 }
        }; Descending = $true
    } |
    Select-Object -First 1
if ($null -ne $policyInput) {
    $relativePolicy = "reports\archive\" + $policyInput.Name
    $databaseArgs += @("--input", $relativePolicy)
    Write-Host "合并历史实测口令策略：$relativePolicy"
}

Write-Host "正在重建本地展示数据库……"
& $venvPython @databaseArgs
if ($LASTEXITCODE -ne 0) {
    throw "数据库构建失败。"
}

Stop-LocalDashboard
if (-not $MeasureToken) {
    $MeasureToken = [guid]::NewGuid().ToString("N")
}
$env:SITES_HEADLESS = "1"
$env:SITES_MEASURE_TOKEN = $MeasureToken
$url = "http://127.0.0.1:$Port/"

$server = Start-Process -FilePath $venvPython -ArgumentList @(
    "-m", "webapp.local_server", "--port", "$Port", "--pid-file", $pidPath
) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

$healthy = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($server.HasExited) { break }
    try {
        $null = Invoke-RestMethod -Uri ($url + "api/stats") -TimeoutSec 2
        $healthy = $true
        break
    } catch {
        # The service may still be importing modules or opening SQLite.
    }
}
if (-not $healthy) {
    $tail = if (Test-Path -LiteralPath $stderrPath) {
        (Get-Content -LiteralPath $stderrPath -Tail 20) -join [Environment]::NewLine
    } else { "无错误日志" }
    throw "本地 Dashboard 启动失败。`n$tail"
}

Write-Host "本地 Dashboard 已启动：$url"
Write-Host "实时测量口令：$MeasureToken"
Write-Host "停止命令：.\webapp\run_local.ps1 -Stop"
if (-not $NoBrowser) {
    Start-Process $url
}
