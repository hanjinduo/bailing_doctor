<#
百灵医生 · 自动部署守护（改完保存 -> 自动上线）

用法（项目根目录下执行）：
  powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1
  powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1 -VM 192.168.232.130
  powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1 -QuietSeconds 15
  powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1 -NoRestart
  powershell -ExecutionPolicy Bypass -File .\deploy\auto_watch.ps1 -Once     # 检测到一次改动并部署后退出

工作机制：
  1) 用 FileSystemWatcher 监听项目根的所有改动，忽略 node_modules/.git/static/logs 等噪音目录
  2) 改动停止 QuietSeconds 秒（默认 8 秒）后才真正部署，避免编辑器一次保存触发多次
  3) 若本轮改动只涉及后端 .py，自动加 -SkipBuild 跳过 npm build，单次约 6 秒
  4) 部署期间暂停监听，部署完成后重新取基线，避免 static/ 构建产物自触发循环
  5) 全程日志写入 logs\autodeploy.log

停止：在窗口内按 Ctrl+C
#>

param(
    [string]$VM = "192.168.232.128",
    [int]$QuietSeconds = 8,
    [switch]$NoRestart,
    [switch]$Once,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ROOT   = Split-Path -Parent $PSScriptRoot
$DEPLOY = Join-Path $PSScriptRoot "deploy_update.ps1"
$LOGDIR = Join-Path $ROOT "logs"
$LOG    = Join-Path $LOGDIR "autodeploy.log"

if (-not (Test-Path $LOGDIR)) { New-Item -ItemType Directory -Path $LOGDIR -Force | Out-Null }
if (-not (Test-Path $DEPLOY)) { Write-Host "[x] 找不到 deploy_update.ps1" -ForegroundColor Red; exit 1 }

# 变更过滤：这些路径的变化不算“代码改动”
$EXCLUDE_RE = '(?i)(^|\\)(node_modules|\.git|\.idea|\.pytest_cache|__pycache__|\.venv|venv|logs|uploads|deploy|dist|\.vite)(\\|$)|(^|\\)static(\\|$)|\.pyc$|\.log$|(^|\\)bailing\.db'
$FRONTEND_RE = '(?i)^(frontend|index\.html$|vite\.config|package\.json)'

function Write-Log([string]$msg, [string]$color = "Gray") {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line -ForegroundColor $color
    Add-Content -LiteralPath $LOG -Value $line -Encoding UTF8
}

Write-Log "==== 自动部署守护已启动 ====" "Cyan"
Write-Log "项目根  : $ROOT"
Write-Log "目标机  : $VM"
Write-Log "静默阈值: $QuietSeconds 秒（改动停止这么久后触发部署）"
Write-Log "日志    : $LOG"
Write-Log "按 Ctrl+C 停止监听" "Yellow"

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $ROOT
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]::LastWrite -bor [System.IO.NotifyFilters]::FileName -bor [System.IO.NotifyFilters]::DirectoryName
$watcher.InternalBufferSize = 65536
$watcher.EnableRaisingEvents = $true

$pending    = @{}
$lastChange = $null
$deployCount = 0

try {
    while ($true) {
        # ---- 收集事件（外层 1 秒节拍） ----
        $r = $watcher.WaitForChanged([System.IO.WatcherChangeTypes]::All, 1000)
        while (-not $r.TimedOut) {
            $rel = [string]$r.Name
            if ($rel -and $rel -notmatch $EXCLUDE_RE) {
                $pending[$rel] = $true
                $lastChange = Get-Date
            }
            $r = $watcher.WaitForChanged([System.IO.WatcherChangeTypes]::All, 120)
        }

        if ($pending.Count -eq 0 -or -not $lastChange) { continue }
        if (((Get-Date) - $lastChange).TotalSeconds -lt $QuietSeconds) { continue }

        # ---- 到达静默阈值，开始部署 ----
        $files = @($pending.Keys) | Sort-Object
        $needBuild = @($files | Where-Object { $_ -match $FRONTEND_RE }).Count -gt 0

        Write-Log "" 
        Write-Log "检测到 $($files.Count) 个文件改动：" "Cyan"
        $files | Select-Object -First 8 | ForEach-Object { Write-Log "  · $_" }
        if ($files.Count -gt 8) { Write-Log "  · ...另外 $($files.Count - 8) 个" }
        Write-Log ("部署模式: " + $(if ($needBuild) { "前端+后端（含 npm build）" } else { "仅后端（跳过 build）" }))

        $pending = @{}
        $lastChange = $null

        # 暂停监听并清空积压事件，防止自身产物触发循环
        $watcher.EnableRaisingEvents = $false
        do { $d = $watcher.WaitForChanged([System.IO.WatcherChangeTypes]::All, 100) } while (-not $d.TimedOut)

        $deployCount++
        Write-Log "---- 第 $deployCount 次部署开始 ----" "Yellow"
        $psArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $DEPLOY, "-VM", $VM)
        if (-not $needBuild) { $psArgs += "-SkipBuild" }
        if ($NoRestart)      { $psArgs += "-NoRestart" }

        if ($DryRun) {
            Write-Log ("[DryRun] 将执行: powershell " + ($psArgs -join " ")) "Magenta"
            Write-Log "[DryRun] 未实际部署，仅验证监听链路" "Magenta"
            $watcher.EnableRaisingEvents = $true
            do { $d = $watcher.WaitForChanged([System.IO.WatcherChangeTypes]::All, 100) } while (-not $d.TimedOut)
            if ($Once) { break }
            continue
        }

        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        & powershell @psArgs 2>&1 | ForEach-Object {
            Write-Host "    $_"
            Add-Content -LiteralPath $LOG -Value ("    " + $_) -Encoding UTF8
        }
        $sw.Stop()
        $code = $LASTEXITCODE

        if ($code -eq 0) {
            Write-Log ("---- 部署成功，耗时 {0:N1} 秒 ----" -f $sw.Elapsed.TotalSeconds) "Green"
        } else {
            Write-Log ("---- 部署失败（exit $code），耗时 {0:N1} 秒，请查看上方输出 ----" -f $sw.Elapsed.TotalSeconds) "Red"
        }

        # 恢复监听，重新取基线
        $watcher.EnableRaisingEvents = $true
        Start-Sleep -Milliseconds 500
        do { $d = $watcher.WaitForChanged([System.IO.WatcherChangeTypes]::All, 100) } while (-not $d.TimedOut)

        if ($Once) { Write-Log "已按 -Once 退出" "Yellow"; break }
        Write-Log "继续监听中 ..."
    }
}
finally {
    if ($watcher) { $watcher.EnableRaisingEvents = $false; $watcher.Dispose() }
    Write-Log "==== 守护进程已退出，累计部署 $deployCount 次 ====" "Yellow"
}
