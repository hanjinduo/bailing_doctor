<#
百灵医生 · 一键更新部署脚本（Windows -> CentOS7 虚拟机）
用法（在 PowerShell 中执行，工作目录随意）：
  powershell -ExecutionPolicy Bypass -File deploy_update.ps1                 # 后端+前端全量更新并重启
  powershell -ExecutionPolicy Bypass -File deploy_update.ps1 -SkipBuild      # 只改了后端 Python，跳过 npm build
  powershell -ExecutionPolicy Bypass -File deploy_update.ps1 -NoRestart      # 只同步文件，不重启服务
  powershell -ExecutionPolicy Bypass -File deploy_update.ps1 -VM 192.168.232.130

设计要点：
  1) 排除 .env / uploads / logs / bailing.db / node_modules / __pycache__，避免覆盖生产配置与用户数据
  2) 覆盖前自动在远端打备份包 /root/backup/app_<时间戳>.tar.gz
  3) 表结构变更无需手工 SQL：app.py 启动时 db.init_schema + MIGRATE_COLS 自动建表/补列
  4) 重启后自动做健康检查（systemd active + HTTP 200）
#>

param(
    [string]$VM = "192.168.232.128",
    [switch]$SkipBuild,
    [switch]$SkipDeps,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$APP      = "/root/app"
$PY       = "/opt/miniconda3/envs/bailing/bin/python"
$PIP      = "/opt/miniconda3/envs/bailing/bin/pip"
$LOCAL    = Split-Path -Parent $PSScriptRoot          # bailing_doctor 项目根
$STAMP    = Get-Date -Format "yyyyMMdd_HHmmss"
$TARLOCAL = Join-Path $env:TEMP "bailing_update_$STAMP.tar.gz"
$TGT      = "root@$VM"
$SSHOPT   = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10")

function Say($msg, $color = "") { Write-Output $msg }
function RunSSH([string]$cmd) {
    $ErrorActionPreference = "Continue"   # 允许 native 命令的 stderr 不中断脚本
    $out = & ssh @SSHOPT $TGT $cmd 2>&1
    if ($LASTEXITCODE -ne 0) { throw "远端命令失败(exit $LASTEXITCODE): $cmd`n$out" }
    return ($out | Where-Object { $_ -notmatch "Warning: Permanently added" })
}

Say "==== 百灵医生 更新部署 -> $VM ===="
Say "本地项目根: $LOCAL"

# ---------- 1. 连通性预检 ----------
Say "`n[1/6] 预检虚拟机连通性 ..."
$null = RunSSH "echo pong; systemctl is-active bailing"
Say "  虚拟机可达，服务当前状态正常"

# ---------- 2. 前端构建 ----------
if ($SkipBuild) {
    Say "`n[2/6] 跳过前端构建（-SkipBuild），沿用本地现有 static/"
} else {
    Say "`n[2/6] 构建前端 (vite build -> static/) ..."
    Push-Location (Join-Path $LOCAL "frontend")
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败，已中止部署（远端未改动）" }
    } finally { Pop-Location }
    $idx = Join-Path $LOCAL "static\index.html"
    if (-not (Test-Path $idx)) { throw "构建后未找到 static\index.html" }
    Say "  构建完成，static/index.html 时间 $((Get-Item $idx).LastWriteTime)"
}

# ---------- 3. 打包 ----------
Say "`n[3/6] 打包（排除生产配置与数据）..."
$excludes = @(
    "--exclude=.env", "--exclude=.env.*",
    "--exclude=bailing.db", "--exclude=logs", "--exclude=uploads",
    "--exclude=node_modules", "--exclude=__pycache__", "--exclude=*.pyc",
    "--exclude=.git", "--exclude=.idea", "--exclude=.pytest_cache",
    "--exclude=deploy"
)
Push-Location $LOCAL
try {
    & tar -czf $TARLOCAL @excludes .
    if ($LASTEXITCODE -ne 0) { throw "打包失败" }
} finally { Pop-Location }
$size = [math]::Round((Get-Item $TARLOCAL).Length / 1KB, 1)
Say "  包体 $size KB -> $TARLOCAL"

# ---------- 4. 上传 + 远端备份 ----------
Say "`n[4/6] 上传并备份远端旧版本 ..."
$ErrorActionPreference = "Continue"
$null = & scp @SSHOPT $TARLOCAL "${TGT}:/root/bailing_update.tar.gz" 2>&1
if ($LASTEXITCODE -ne 0) { throw "上传失败" }
$null = RunSSH "mkdir -p /root/backup && tar -czf /root/backup/app_$STAMP.tar.gz -C $APP . && du -h /root/backup/app_$STAMP.tar.gz"
Say "  已备份: /root/backup/app_$STAMP.tar.gz"

# ---------- 5. 覆盖解压 + 依赖 ----------
Say "`n[5/6] 覆盖解压 ..."
$null = RunSSH "cd $APP && tar -xzf /root/bailing_update.tar.gz && rm -f /root/bailing_update.tar.gz && echo unpacked"
Say "  代码已更新（.env / uploads / logs 保持原样）"

if ($SkipDeps) {
    Say "  跳过 pip 依赖安装（-SkipDeps）"
} else {
    Say "  同步 Python 依赖（requirements.txt 无变化时秒过）..."
    $null = RunSSH "$PIP install -q -r $APP/requirements.txt && echo deps-ok"
    Say "  依赖检查完成"
}

# ---------- 6. 重启 + 健康检查 ----------
if ($NoRestart) {
    Say "`n[6/6] 跳过重启（-NoRestart）。改动需执行 systemctl restart bailing 后生效"
} else {
    Say "`n[6/6] 重启服务并做健康检查 ..."
    $null = RunSSH "systemctl restart bailing"
    $ok = $false
    for ($i = 1; $i -le 3; $i++) {
        Start-Sleep -Seconds 3
        $code = RunSSH "curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8010/ ; echo"
        $api  = RunSSH "curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8010/api/health ; echo"
        $codeStr = $code -join ''
        $apiStr  = $api  -join ''
        Say "  第 $i 次探测：首页 HTTP $codeStr  |  接口 HTTP $apiStr"
        if ($codeStr -match "200" -and $apiStr -match "200") { $ok = $true; break }
    }
    if (-not $ok) {
        RunSSH "journalctl -u bailing -n 30 --no-pager" | ForEach-Object { Say "    $_" }
        throw "健康检查失败，请查看上方日志"
    }
    Say "  健康检查通过 ✓"
}

Say "`n==== 部署完成 $(Get-Date -Format 'HH:mm:ss') ===="
Say "内网访问: http://$VM/"
Say "公网访问: 需在宿主机重新启动 启动公网隧道.bat（每次启动域名会变）"
Say "回滚命令: tar -xzf /root/backup/app_$STAMP.tar.gz -C $APP && systemctl restart bailing"

if (Test-Path $TARLOCAL) { Remove-Item $TARLOCAL -Force }