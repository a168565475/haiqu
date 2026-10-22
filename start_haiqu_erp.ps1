[CmdletBinding()]
param(
    [int]$DockerTimeoutSeconds = 180,
    [int]$DatabaseRecoveryTimeoutSeconds = 1800,
    [int]$ServiceTimeoutSeconds = 240,
    [switch]$NoBrowser,
    [ValidateSet('Ask', 'Yes', 'No')][string]$QuickTunnel = 'Ask'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot 'compose.yml'
$LogDirectory = Join-Path $ProjectRoot 'logs'
$FrontendUrl = 'http://localhost:8080'
$HealthUrl = 'http://localhost:8000/api/health/'
$QuickTunnelUrl = $null
$QuickTunnelUsedDnsFallback = $false
$QuickTunnelUsedSystemProxy = $false
$QuickTunnelStateFile = Join-Path $LogDirectory 'cloudflared_quick_current.json'
$DesktopDirectory = [Environment]::GetFolderPath('Desktop')
$QuickTunnelDesktopRecord = Join-Path $DesktopDirectory 'haiqu ERP 当前公网地址.txt'
$QuickTunnelDesktopShortcut = Join-Path $DesktopDirectory '打开 haiqu ERP 公网版.url'
$DockerDesktopPath = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$ExpectedContainers = [ordered]@{
    postgres = 'haiqu-postgres'
    redis = 'haiqu-redis'
    backend = 'haiqu-backend'
    frontend = 'haiqu-frontend'
}
$RequiredPorts = @(15432, 16379, 8000, 8080)

if (-not (Test-Path -LiteralPath $LogDirectory)) {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
}

$LogFile = Join-Path $LogDirectory ("startup_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))

function Write-StartupLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet('INFO', 'OK', 'WARN', 'ERROR')][string]$Level = 'INFO'
    )

    $displayLevel = switch ($Level) {
        'OK' { '成功' }
        'WARN' { '提示' }
        'ERROR' { '错误' }
        default { '进行' }
    }
    $line = '[{0}] [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $displayLevel, $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8

    $color = switch ($Level) {
        'OK' { 'Green' }
        'WARN' { 'Yellow' }
        'ERROR' { 'Red' }
        default { 'Cyan' }
    }
    Write-Host $line -ForegroundColor $color
}

function Write-StartupHeader {
    Write-Host ''
    Write-Host '========================================' -ForegroundColor Cyan
    Write-Host '        haiqu ERP 开发环境一键启动        ' -ForegroundColor Cyan
    Write-Host '========================================' -ForegroundColor Cyan
}

function Read-QuickTunnelChoice {
    param([ValidateSet('Ask', 'Yes', 'No')][string]$Mode)

    if ($Mode -eq 'Yes') {
        return $true
    }
    if ($Mode -eq 'No') {
        return $false
    }

    Write-Host ''
    Write-Host '是否同时启动 Cloudflare 公网访问？' -ForegroundColor Yellow
    Write-Host 'Y = 启动/复用公网访问，并生成可发给同事的 HTTPS 地址' -ForegroundColor DarkYellow
    Write-Host 'N = 关闭已有 haiqu 公网隧道，仅保留本机 ERP' -ForegroundColor DarkYellow
    do {
        $answer = (Read-Host '请输入 Y 或 N').Trim().ToUpperInvariant()
        if ($answer -notin @('Y', 'N')) {
            Write-Host '输入无效，请只输入 Y 或 N。' -ForegroundColor Yellow
        }
    } while ($answer -notin @('Y', 'N'))

    return ($answer -eq 'Y')
}

function Convert-ServiceStateToChinese {
    param([string]$State)

    switch ($State) {
        'healthy' { return '健康' }
        'starting' { return '正在启动' }
        'running' { return '运行中（无健康检查）' }
        'created' { return '已创建，尚未启动' }
        'restarting' { return '正在重启' }
        'exited' { return '已退出' }
        'dead' { return '已停止' }
        'unhealthy' { return '不健康' }
        'missing' { return '未找到容器' }
        default { return $State }
    }
}

function Convert-ServiceNameToChinese {
    param([string]$Name)

    switch ($Name) {
        'postgres' { return 'PostgreSQL 数据库' }
        'redis' { return 'Redis 缓存' }
        'backend' { return '后端服务' }
        'frontend' { return '前端服务' }
        default { return $Name }
    }
}

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Quiet,
        [switch]$AllowFailure
    )

    $commandText = 'docker ' + ($Arguments -join ' ')
    if (-not $Quiet) {
        Write-StartupLog "执行：$commandText"
    }

    # Windows PowerShell 5.1 把原生程序 stderr 包装成错误记录。
    # 临时使用 Continue，才能按退出码处理 Docker 未启动等预期失败。
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& docker @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($output.Count -gt 0) {
        Add-Content -LiteralPath $LogFile -Value ($output -join [Environment]::NewLine) -Encoding UTF8
    }

    if (($exitCode -ne 0) -and (-not $AllowFailure)) {
        throw "Docker 命令执行失败（退出码 $exitCode）：$commandText`n$($output -join [Environment]::NewLine)"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Test-DockerEngine {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $dockerCommand) {
        return $false
    }

    # Docker Desktop 假死时，docker info 可能永久不返回。这里使用独立进程并设置
    # 硬超时，避免桌面启动入口一直卡在“开始启动开发环境”。
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $dockerCommand.Source
    $startInfo.Arguments = 'info --format "{{.ServerVersion}}"'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            return $false
        }

        if (-not $process.WaitForExit(8000)) {
            try {
                $process.Kill()
            }
            catch {
                # 进程可能刚好自行退出，无需影响后续 Docker Desktop 启动流程。
            }
            return $false
        }

        $serverVersion = $process.StandardOutput.ReadToEnd().Trim()
        return ($process.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($serverVersion))
    }
    catch {
        return $false
    }
    finally {
        $process.Dispose()
    }
}

function Start-DockerEngine {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -ne $dockerCommand -and (Test-DockerEngine)) {
        Write-StartupLog 'Docker 引擎已经运行。' 'OK'
        return
    }

    Write-StartupLog 'Docker 引擎未运行，正在启动 Docker Desktop...' 'WARN'
    if (Test-Path -LiteralPath $DockerDesktopPath) {
        Start-Process -FilePath $DockerDesktopPath -WindowStyle Hidden | Out-Null
    }
    else {
        $desktopCommand = Get-Command docker -ErrorAction Stop
        Start-Process -FilePath $desktopCommand.Source -ArgumentList @('desktop', 'start') -WindowStyle Hidden | Out-Null
    }

    $deadline = (Get-Date).AddSeconds($DockerTimeoutSeconds)
    do {
        Start-Sleep -Seconds 3
        if (Test-DockerEngine) {
            Write-StartupLog 'Docker 引擎启动成功。' 'OK'
            return
        }
        Write-Host '.' -NoNewline -ForegroundColor DarkGray
    } while ((Get-Date) -lt $deadline)

    throw "等待 Docker Desktop 超时（$DockerTimeoutSeconds 秒）。请手动打开 Docker Desktop，确认其完成启动后再次双击启动入口。"
}

function Get-ProjectPublishedPorts {
    $result = Invoke-Docker -Arguments @(
        'ps',
        '--filter', 'label=com.docker.compose.project=haiqu-erp',
        '--format', '{{.Ports}}'
    ) -Quiet -AllowFailure

    if ($result.ExitCode -ne 0) {
        return @()
    }

    $ports = @()
    foreach ($line in $result.Output) {
        foreach ($match in [regex]::Matches([string]$line, ':(\d+)->')) {
            $ports += [int]$match.Groups[1].Value
        }
    }
    return @($ports | Select-Object -Unique)
}

function Test-RequiredPorts {
    Write-StartupLog '检查主机端口 15432、16379、8000、8080...'
    $projectPorts = @(Get-ProjectPublishedPorts)

    foreach ($port in $RequiredPorts) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
        if ($listeners.Count -eq 0) {
            continue
        }

        if ($projectPorts -contains $port) {
            Write-StartupLog "端口 $port 已由本项目容器使用，继续执行。" 'OK'
            continue
        }

        $processDescriptions = foreach ($listener in $listeners) {
            $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
            if ($null -ne $process) {
                'PID={0}, 进程={1}' -f $listener.OwningProcess, $process.ProcessName
            }
            else {
                'PID={0}, 进程=未知' -f $listener.OwningProcess
            }
        }
        throw "端口 $port 已被其他程序占用（$($processDescriptions -join '; ')）。脚本不会自动终止该程序，请处理冲突后重试。"
    }

    Write-StartupLog '端口检查通过。' 'OK'
}

function Get-ContainerHealth {
    param([Parameter(Mandatory = $true)][string]$ContainerName)

    $result = Invoke-Docker -Arguments @(
        'inspect',
        '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}',
        $ContainerName
    ) -Quiet -AllowFailure

    if ($result.ExitCode -ne 0 -or $result.Output.Count -eq 0) {
        return 'missing'
    }
    return ([string]$result.Output[0]).Trim()
}

function Wait-ForPostgresRecovery {
    Write-StartupLog "等待 PostgreSQL 真正完成恢复，最长 $DatabaseRecoveryTimeoutSeconds 秒..."
    $startedAt = Get-Date
    $deadline = $startedAt.AddSeconds($DatabaseRecoveryTimeoutSeconds)
    $nextProgressAt = $startedAt

    do {
        $state = Get-ContainerHealth -ContainerName 'haiqu-postgres'
        if ($state -eq 'healthy') {
            $elapsedSeconds = [int]((Get-Date) - $startedAt).TotalSeconds
            Write-StartupLog "PostgreSQL 已可接受连接，恢复等待 $elapsedSeconds 秒。" 'OK'
            return
        }

        if ($state -in @('exited', 'dead', 'missing')) {
            throw "PostgreSQL 容器无法继续恢复，当前状态：$state"
        }

        $now = Get-Date
        if ($now -ge $nextProgressAt) {
            $elapsedSeconds = [int]($now - $startedAt).TotalSeconds
            Write-StartupLog "PostgreSQL 正在自动恢复，当前状态：$state；已等待 $elapsedSeconds 秒。请保持窗口和 Docker Desktop 运行。" 'WARN'
            $nextProgressAt = $now.AddSeconds(30)
        }

        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)

    throw "等待 PostgreSQL 自动恢复超时（$DatabaseRecoveryTimeoutSeconds 秒）。请查看 PostgreSQL 日志；不要删除 data 目录。"
}

function Wait-ForServices {
    Write-StartupLog "等待全部服务通过健康检查，最长 $ServiceTimeoutSeconds 秒..."
    $deadline = (Get-Date).AddSeconds($ServiceTimeoutSeconds)
    $previousSummary = ''

    do {
        $states = [ordered]@{}
        foreach ($entry in $ExpectedContainers.GetEnumerator()) {
            $states[$entry.Key] = Get-ContainerHealth -ContainerName $entry.Value
        }

        $summary = ($states.GetEnumerator() | ForEach-Object { '{0}={1}' -f (Convert-ServiceNameToChinese $_.Key), (Convert-ServiceStateToChinese $_.Value) }) -join '；'
        if ($summary -ne $previousSummary) {
            Write-StartupLog "当前状态：$summary"
            $previousSummary = $summary
        }

        $failed = @($states.GetEnumerator() | Where-Object { $_.Value -in @('exited', 'dead', 'unhealthy', 'missing') })
        if ($failed.Count -gt 0) {
            $failedSummary = ($failed | ForEach-Object { '{0}={1}' -f (Convert-ServiceNameToChinese $_.Key), (Convert-ServiceStateToChinese $_.Value) }) -join '；'
            throw "服务启动失败：$failedSummary"
        }

        $notHealthy = @($states.GetEnumerator() | Where-Object { $_.Value -ne 'healthy' })
        if ($notHealthy.Count -eq 0) {
    Write-StartupLog 'PostgreSQL、Redis、后端服务、前端服务均已健康。' 'OK'
            return
        }

        Start-Sleep -Seconds 4
    } while ((Get-Date) -lt $deadline)

    throw "等待服务健康检查超时（$ServiceTimeoutSeconds 秒）。最后状态：$previousSummary"
}

function Assert-DataMount {
    param(
        [Parameter(Mandatory = $true)][string]$ContainerName,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$ExpectedHostPath
    )

    # 使用 JSON 避免 Windows PowerShell 5.1 对 Docker Go 模板双引号的错误转义。
    $result = Invoke-Docker -Arguments @('inspect', $ContainerName) -Quiet
    $inspectData = @($result.Output | Out-String | ConvertFrom-Json)
    $mount = @($inspectData[0].Mounts | Where-Object { $_.Destination -eq $Destination })
    if ($mount.Count -ne 1 -or $mount[0].Type -ne 'bind') {
        throw "$ContainerName 的 $Destination 未使用唯一的主机 bind mount。"
    }

    $actualSource = [string]$mount[0].Source
    $expectedFullPath = [System.IO.Path]::GetFullPath($ExpectedHostPath).TrimEnd('\')
    $actualFullPath = [System.IO.Path]::GetFullPath($actualSource).TrimEnd('\')
    if (-not $actualFullPath.Equals($expectedFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$ContainerName 数据挂载路径不符合预期：实际=$actualSource；预期=$expectedFullPath"
    }
    Write-StartupLog "$ContainerName 数据已挂载到主机：$expectedFullPath" 'OK'
}

function Test-ApplicationEndpoints {
    Write-StartupLog '验证 Health API、PostgreSQL、Redis 与前端页面...'

    $health = $null
    $healthDeadline = (Get-Date).AddSeconds(120)
    do {
        try {
            $candidateHealth = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 10
            if (
                $candidateHealth.status -eq 'ok' -and
                $candidateHealth.database -eq 'ok' -and
                $candidateHealth.redis -eq 'ok'
            ) {
                $health = $candidateHealth
                break
            }
        }
        catch {
            # Django 开发服务器在迁移或源码变化后可能短暂重载，继续按实际状态等待。
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $healthDeadline)

    if ($null -eq $health) {
        throw "后端健康检查在 120 秒内无法访问（$HealthUrl）。请确认 Backend 容器已健康、8000 端口未被拦截；详细原始错误已写入启动日志。"
    }
    Write-StartupLog '后端健康检查通过：服务、数据库、Redis 均正常。' 'OK'

    $postgres = Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile, 'exec', '-T', 'postgres',
        'sh', '-c', 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    ) -Quiet
    if (($postgres.Output -join ' ') -notmatch 'accepting connections') {
        throw "PostgreSQL 验证失败：$($postgres.Output -join ' ')"
    }
    Write-StartupLog 'PostgreSQL 数据库：连接正常。' 'OK'

    $redis = Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile, 'exec', '-T', 'redis', 'redis-cli', 'ping'
    ) -Quiet
    if ((($redis.Output -join '').Trim()) -ne 'PONG') {
        throw "Redis 验证失败：$($redis.Output -join ' ')"
    }
    Write-StartupLog 'Redis 缓存：连接正常。' 'OK'

    $frontendResponse = $null
    $frontendDeadline = (Get-Date).AddSeconds(120)
    do {
        try {
            $candidateFrontend = Invoke-WebRequest -Uri $FrontendUrl -Method Get -UseBasicParsing -TimeoutSec 10
            if ($candidateFrontend.StatusCode -eq 200) {
                $frontendResponse = $candidateFrontend
                break
            }
        }
        catch {
            # Windows 端口转发可能比容器内健康状态稍晚就绪，继续等待。
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $frontendDeadline)

    if ($null -eq $frontendResponse) {
        throw "前端页面在 120 秒内无法访问（$FrontendUrl）。请确认 Frontend 容器已健康，并检查 8080 端口是否可用；详细原始错误已写入启动日志。"
    }
    Write-StartupLog '前端页面：访问正常。' 'OK'

}

function Get-CloudflaredExecutable {
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if ($null -ne $command -and (Test-Path -LiteralPath $command.Source)) {
        return $command.Source
    }

    $candidates = @(
        'C:\Program Files (x86)\cloudflared\cloudflared.exe',
        'C:\Program Files\cloudflared\cloudflared.exe',
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\cloudflared.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

function Get-ExistingQuickTunnelProcess {
    return @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like '*tunnel*' -and $_.CommandLine -like '*--url*http://localhost:8080*'
    } | Sort-Object CreationDate -Descending | Select-Object -First 1)
}

function Stop-ExistingQuickTunnel {
    $processes = @(Get-ExistingQuickTunnelProcess)
    if ($processes.Count -eq 0) {
        Write-StartupLog '当前没有运行中的 haiqu Quick Tunnel。' 'OK'
    }
    else {
        foreach ($process in $processes) {
            Stop-Process -Id ([int]$process.ProcessId) -ErrorAction Stop
        }
        Write-StartupLog "已关闭 $($processes.Count) 个 haiqu Quick Tunnel；公网临时地址已失效。" 'OK'
    }

    if (Test-Path -LiteralPath $QuickTunnelStateFile) {
        Remove-Item -LiteralPath $QuickTunnelStateFile -Force
    }

    if (Test-Path -LiteralPath $QuickTunnelDesktopShortcut) {
        Remove-Item -LiteralPath $QuickTunnelDesktopShortcut -Force
    }
    @(
        'haiqu ERP 公网访问状态：已关闭'
        "更新时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        ''
        '下次双击“启动 haiqu ERP.cmd”并选择 Y 后，新的公网地址会自动写入本文件。'
    ) | Set-Content -LiteralPath $QuickTunnelDesktopRecord -Encoding UTF8
    Write-StartupLog "桌面公网地址记录已标记为关闭：$QuickTunnelDesktopRecord" 'OK'
}

function Get-QuickTunnelUrlFromFiles {
    $candidates = @()
    if (Test-Path -LiteralPath $QuickTunnelStateFile) {
        try {
            $state = Get-Content -LiteralPath $QuickTunnelStateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([string]$state.url -match '^https://[a-z0-9-]+\.trycloudflare\.com$') {
                $candidates += [string]$state.url
            }
        }
        catch {
            Write-StartupLog '现有 Quick Tunnel 状态文件无法读取，将从日志重新识别地址。' 'WARN'
        }
    }

    $logFiles = @(Get-ChildItem -LiteralPath $LogDirectory -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'cloudflared-quick-*.log' } |
        Sort-Object LastWriteTime -Descending)
    foreach ($logFile in $logFiles) {
        $content = Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction SilentlyContinue
        if ([string]::IsNullOrWhiteSpace([string]$content)) {
            continue
        }
        $match = [regex]::Match([string]$content, 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($match.Success) {
            $candidates += $match.Value
        }
    }

    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        if (Test-QuickTunnelUrl -Url $candidate) {
            return $candidate
        }
    }
    return $null
}

function Invoke-CurlQuickTunnelCheck {
    param(
        [Parameter(Mandatory = $true)][string]$CurlPath,
        [Parameter(Mandatory = $true)][string]$Url,
        [string]$ResolveIp,
        [string]$ProxyUrl
    )

    $resolveArguments = @()
    if (-not [string]::IsNullOrWhiteSpace($ResolveIp)) {
        $hostName = ([uri]$Url).DnsSafeHost
        $resolveArguments = @('--resolve', "${hostName}:443:$ResolveIp")
    }

    $proxyArguments = @()
    if (-not [string]::IsNullOrWhiteSpace($ProxyUrl)) {
        $proxyArguments = @('--proxy', $ProxyUrl)
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $rootOutput = @(& $CurlPath @proxyArguments @resolveArguments -sS -o NUL -w '%{http_code}' --connect-timeout 5 --max-time 15 "$Url/" 2>$null)
        $rootExitCode = $LASTEXITCODE
        $healthOutput = @(& $CurlPath @proxyArguments @resolveArguments -sS -w "`n%{http_code}" --connect-timeout 5 --max-time 15 "$Url/api/health/" 2>$null)
        $healthExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($rootExitCode -ne 0 -or $healthExitCode -ne 0 -or $rootOutput.Count -eq 0 -or $healthOutput.Count -lt 2) {
        return $false
    }

    $rootStatus = ([string]$rootOutput[-1]).Trim()
    $healthStatus = ([string]$healthOutput[-1]).Trim()
    $healthBody = (($healthOutput | Select-Object -First ($healthOutput.Count - 1)) -join [Environment]::NewLine)
    try {
        $health = $healthBody | ConvertFrom-Json
    }
    catch {
        return $false
    }
    return (
        $rootStatus -eq '200' -and
        $healthStatus -eq '200' -and
        $health.status -eq 'ok' -and
        $health.database -eq 'ok' -and
        $health.redis -eq 'ok'
    )
}

function Get-WindowsSystemProxyUrl {
    try {
        $settings = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop
        if ([int]$settings.ProxyEnable -ne 1 -or [string]::IsNullOrWhiteSpace([string]$settings.ProxyServer)) {
            return $null
        }

        $proxyServer = [string]$settings.ProxyServer
        if ($proxyServer -match '(?:^|;)https=([^;]+)') {
            $proxyServer = $Matches[1]
        }
        elseif ($proxyServer -match '(?:^|;)http=([^;]+)') {
            $proxyServer = $Matches[1]
        }
        if ($proxyServer -notmatch '^https?://') {
            $proxyServer = "http://$proxyServer"
        }

        $proxyUri = [uri]$proxyServer
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $proxyUri.Port -ErrorAction SilentlyContinue)
        if ($proxyUri.IsLoopback -and $listeners.Count -eq 0) {
            return $null
        }
        return $proxyUri.AbsoluteUri.TrimEnd('/')
    }
    catch {
        return $null
    }
}

function Test-QuickTunnelUrl {
    param([Parameter(Mandatory = $true)][string]$Url)

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -ne $curl) {
        if (Invoke-CurlQuickTunnelCheck -CurlPath $curl.Source -Url $Url) {
            return $true
        }

        # Clash Verge 等代理软件会把域名解析到 198.18.0.0/15，并要求浏览器通过
        # Windows 系统代理访问。curl 默认不读取该设置，因此显式复用系统代理验证。
        $systemProxyUrl = Get-WindowsSystemProxyUrl
        if (-not [string]::IsNullOrWhiteSpace($systemProxyUrl) -and
            (Invoke-CurlQuickTunnelCheck -CurlPath $curl.Source -Url $Url -ProxyUrl $systemProxyUrl)) {
            $script:QuickTunnelUsedSystemProxy = $true
            return $true
        }

        $hostName = ([uri]$Url).DnsSafeHost
        $publicDnsAddresses = @(Resolve-DnsName -Name $hostName -Type A -Server 1.1.1.1 -DnsOnly -ErrorAction SilentlyContinue |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.IPAddress) } |
            Select-Object -ExpandProperty IPAddress -Unique)
        foreach ($address in $publicDnsAddresses) {
            if (Invoke-CurlQuickTunnelCheck -CurlPath $curl.Source -Url $Url -ResolveIp ([string]$address)) {
                $script:QuickTunnelUsedDnsFallback = $true
                return $true
            }
        }
        return $false
    }

    try {
        $root = Invoke-WebRequest -Uri "$Url/" -Method Get -UseBasicParsing -TimeoutSec 20
        $healthResponse = Invoke-WebRequest -Uri "$Url/api/health/" -Method Get -UseBasicParsing -TimeoutSec 20
        $health = $healthResponse.Content | ConvertFrom-Json
        return (
            $root.StatusCode -eq 200 -and
            $healthResponse.StatusCode -eq 200 -and
            $health.status -eq 'ok' -and
            $health.database -eq 'ok' -and
            $health.redis -eq 'ok'
        )
    }
    catch {
        return $false
    }
}

function Save-QuickTunnelState {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Url,
        [string]$StandardOutputLog,
        [string]$StandardErrorLog
    )

    [ordered]@{
        process_id = $ProcessId
        url = $Url
        origin = $FrontendUrl
        started_at = (Get-Date).ToString('o')
        stdout_log = $StandardOutputLog
        stderr_log = $StandardErrorLog
    } | ConvertTo-Json | Set-Content -LiteralPath $QuickTunnelStateFile -Encoding UTF8
}

function Save-QuickTunnelDesktopRecord {
    param([Parameter(Mandatory = $true)][string]$Url)

    $processId = $null
    if (Test-Path -LiteralPath $QuickTunnelStateFile) {
        try {
            $state = Get-Content -LiteralPath $QuickTunnelStateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $processId = $state.process_id
        }
        catch {
            Write-StartupLog '无法从状态文件读取 Quick Tunnel 进程号，桌面记录仍将保存网址。' 'WARN'
        }
    }

    @(
        'haiqu ERP 当前公网访问地址'
        '========================================'
        "生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        "公网地址：$Url"
        "进程 PID：$processId"
        '状态：已经通过 ERP 首页和后端健康接口验证'
        ''
        '说明：'
        '1. 可将“公网地址”复制给同事。'
        '2. 也可以直接双击桌面的“打开 haiqu ERP 公网版”快捷网址。'
        '3. 电脑关机、选择 N 或 cloudflared 停止后，此临时地址会失效。'
        '4. 下次选择 Y 生成新地址时，本文件和快捷网址会自动更新。'
    ) | Set-Content -LiteralPath $QuickTunnelDesktopRecord -Encoding UTF8

    @(
        '[InternetShortcut]'
        "URL=$Url"
    ) | Set-Content -LiteralPath $QuickTunnelDesktopShortcut -Encoding ASCII

    Write-StartupLog "当前公网地址已保存到桌面：$QuickTunnelDesktopRecord" 'OK'
    Write-StartupLog "公网访问快捷网址已更新：$QuickTunnelDesktopShortcut" 'OK'
}

function Start-QuickTunnel {
    $cloudflared = Get-CloudflaredExecutable
    if ([string]::IsNullOrWhiteSpace($cloudflared)) {
        throw '未找到 cloudflared。请先执行 winget install --id Cloudflare.cloudflared，再重新启动。'
    }

    $existingProcesses = @(Get-ExistingQuickTunnelProcess)
    if ($existingProcesses.Count -gt 0) {
        $existingUrl = Get-QuickTunnelUrlFromFiles
        if (-not [string]::IsNullOrWhiteSpace($existingUrl) -and (Test-QuickTunnelUrl -Url $existingUrl)) {
            Save-QuickTunnelState -ProcessId ([int]$existingProcesses[0].ProcessId) -Url $existingUrl
            Write-StartupLog "检测到可用的 Quick Tunnel，已直接复用：$existingUrl" 'OK'
            return $existingUrl
        }
        throw "检测到 cloudflared 已在转发 $FrontendUrl，但无法确认其公网地址。为避免重复隧道，脚本没有再启动；请先停止该 cloudflared 进程后重试。"
    }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutLog = Join-Path $LogDirectory "cloudflared-quick-$stamp.out.log"
    $stderrLog = Join-Path $LogDirectory "cloudflared-quick-$stamp.err.log"
    Write-StartupLog '正在创建 Cloudflare Quick Tunnel（无需域名或账号）...'

    $process = Start-Process -FilePath $cloudflared `
        -ArgumentList @('tunnel', '--url', $FrontendUrl, '--no-autoupdate', '--protocol', 'http2') `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $url = $null
    $addressDeadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 1
        $process.Refresh()
        if ($process.HasExited) {
            break
        }

        $content = @()
        if (Test-Path -LiteralPath $stdoutLog) {
            $content += Get-Content -LiteralPath $stdoutLog -Raw -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $stderrLog) {
            $content += Get-Content -LiteralPath $stderrLog -Raw -ErrorAction SilentlyContinue
        }
        $match = [regex]::Match(($content -join [Environment]::NewLine), 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($match.Success) {
            $url = $match.Value
            break
        }
    } while ((Get-Date) -lt $addressDeadline)

    if ([string]::IsNullOrWhiteSpace($url)) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        throw "Quick Tunnel 未能在 60 秒内生成公网地址。请检查网络；日志：$stderrLog"
    }

    Write-StartupLog "已生成公网地址，正在验证登录页和后端健康接口：$url"
    $publicDeadline = (Get-Date).AddSeconds(120)
    $isPublicReady = $false
    do {
        if (Test-QuickTunnelUrl -Url $url) {
            $isPublicReady = $true
            break
        }
        Start-Sleep -Seconds 3
        $process.Refresh()
        if ($process.HasExited) {
            break
        }
    } while ((Get-Date) -lt $publicDeadline)

    if (-not $isPublicReady) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        throw "Quick Tunnel 已生成地址但未能在 120 秒内通过公网验证，已停止本次隧道。请查看日志：$stderrLog"
    }

    Save-QuickTunnelState -ProcessId $process.Id -Url $url -StandardOutputLog $stdoutLog -StandardErrorLog $stderrLog
    Write-StartupLog "Cloudflare 公网访问启动成功：$url" 'OK'
    return $url
}

function Write-FriendlyFailure {
    param([Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord)

    $rawMessage = $ErrorRecord.Exception.Message
    $title = '启动过程出现错误'
    $reason = '启动过程中发生了未分类的异常。'
    $solution = '请查看完整启动日志；若仍无法判断，将日志文件发给开发人员。'

    if ($rawMessage -match 'ports are not available') {
        $portMatch = [regex]::Match($rawMessage, 'TCP .*?:(\d+)')
        $portText = if ($portMatch.Success) { $portMatch.Groups[1].Value } else { '目标端口' }
        $title = '主机端口无法绑定'
        if ($rawMessage -match 'forbidden by its access permissions') {
            $reason = "Windows 拒绝绑定端口 $portText。通常是该端口处于系统保留范围，而不是普通程序占用。"
            $solution = '不要删除 Windows 端口保留规则。请改用经检查可用的端口，并同步更新 Compose、CORS、防火墙和文档。'
        }
        else {
            $reason = "端口 $portText 已被其他程序或容器占用。"
            $solution = '关闭可确认的占用程序，或为本项目选择新的可用端口；脚本不会自动结束其他进程。'
        }
    }
    elseif ($rawMessage -match 'Unable to connect remote server|前端页面无法访问') {
        $title = '前端页面无法访问'
        $reason = '前端容器可能未启动、端口未发布到 Windows，或 Windows 防火墙/端口策略阻止了访问。'
        $solution = '先确认 Frontend 状态为“健康”，再检查 8080 端口；如容器健康但页面仍不可达，重新创建 Frontend 容器可恢复端口映射。'
    }
    elseif ($rawMessage -match '后端健康检查无法访问') {
        $title = '后端健康检查失败'
        $reason = '后端服务未在 8000 端口正常响应，或依赖服务尚未完全就绪。'
        $solution = '确认 Backend、PostgreSQL、Redis 均为“健康”，然后查看启动日志中的 Backend 首个错误。'
    }
    elseif ($rawMessage -match '等待 Docker Desktop 超时|docker API|dockerDesktopLinuxEngine') {
        $title = 'Docker Desktop 未就绪'
        $reason = 'Docker 引擎在等待时间内未能提供服务。'
        $solution = '手动打开 Docker Desktop，等待状态显示为 Running 后再次双击启动入口。'
    }
    elseif ($rawMessage -match '等待 PostgreSQL 自动恢复超时|PostgreSQL 容器无法继续恢复') {
        $title = 'PostgreSQL 恢复未完成'
        $reason = $rawMessage.Split([Environment]::NewLine)[0]
        $solution = '保持 Docker Desktop 和电脑运行，检查磁盘状态及 PostgreSQL 日志；不要删除 data 目录或执行 down -v。'
    }
    elseif ($rawMessage -match 'dependency.*postgres.*failed|container haiqu-postgres is unhealthy') {
        $title = 'PostgreSQL 尚未完成恢复'
        $reason = '上次异常关机后，数据库自动恢复时间超过了旧的健康检查等待时间。'
        $solution = '请保持 Docker Desktop 运行并重新启动；脚本现已延长数据库恢复等待时间，不要删除 data 目录。'
    }
    elseif ($rawMessage -match '端口 \d+ 已被其他程序占用') {
        $title = '所需端口被其他程序占用'
        $reason = $rawMessage
        $solution = '根据提示中的 PID 和进程名确认占用者；仅关闭明确可以关闭的程序，然后重试。'
    }
    elseif ($rawMessage -match '服务启动失败|健康检查超时') {
        $title = '服务未能完成启动'
        $reason = $rawMessage.Split([Environment]::NewLine)[0]
        $solution = '查看完整日志中的首个容器错误；不要反复重启、删除 data 目录或执行 Docker 清理命令。'
    }
    elseif ($rawMessage -match '未找到 docker 命令') {
        $title = '未安装 Docker Desktop'
        $reason = '系统找不到 docker 命令。'
        $solution = '安装 Docker Desktop，完成首次初始化后再次双击启动入口。'
    }
    elseif ($rawMessage -match 'Quick Tunnel|cloudflared') {
        $title = 'Cloudflare 公网访问启动失败'
        $reason = $rawMessage.Split([Environment]::NewLine)[0]
        $solution = '本机 ERP 数据不会受影响。请按提示检查 cloudflared、网络和对应日志；不要删除 Docker 数据卷或 data 目录。'
    }

    Write-Host ''
    Write-Host '================ 启动失败 ================' -ForegroundColor Red
    Write-Host "问题：$title" -ForegroundColor Red
    Write-Host "原因：$reason" -ForegroundColor Yellow
    Write-Host "处理：$solution" -ForegroundColor Yellow
    Write-Host '==========================================' -ForegroundColor Red

    Write-StartupLog "中文诊断 - 问题：$title；原因：$reason；处理：$solution" 'ERROR'
}

function Write-FailureDiagnostics {
    param([Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord)

    Add-Content -LiteralPath $LogFile -Value "`n--- 原始异常 ---`n$($ErrorRecord.Exception.Message)" -Encoding UTF8
    Write-FriendlyFailure -ErrorRecord $ErrorRecord
    Write-StartupLog "完整启动日志：$LogFile" 'ERROR'

    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -ne $dockerCommand -and (Test-DockerEngine)) {
        Write-Host ''
        Write-Host '当前核心服务状态：' -ForegroundColor Yellow
        foreach ($entry in $ExpectedContainers.GetEnumerator()) {
            $state = Get-ContainerHealth -ContainerName $entry.Value
            Write-Host ('- {0}：{1}' -f (Convert-ServiceNameToChinese $entry.Key), (Convert-ServiceStateToChinese $state)) -ForegroundColor Yellow
        }

        $fullLogs = Invoke-Docker -Arguments @('compose', '-f', $ComposeFile, 'logs', '--tail=200', '--no-color') -Quiet -AllowFailure
        if ($fullLogs.Output.Count -gt 0) {
            Add-Content -LiteralPath $LogFile -Value "`n--- 最近 200 行容器日志 ---" -Encoding UTF8
        }
    }

    Write-Host ''
    Write-Host '说明：脚本不会停止其他程序，也不会删除 Docker 卷、数据库或 data 目录。' -ForegroundColor DarkYellow
}

$exitCode = 0
try {
    Write-StartupHeader
    $enableQuickTunnel = Read-QuickTunnelChoice -Mode $QuickTunnel
    if ($enableQuickTunnel) {
        Write-StartupLog '本次选择：启动 Cloudflare 公网访问。'
    }
    else {
        Write-StartupLog '本次选择：关闭 Cloudflare 公网访问，仅启动本机 ERP。'
        Stop-ExistingQuickTunnel
    }
    Write-StartupLog '开始启动 haiqu ERP 开发环境。'
    Write-StartupLog "项目目录：$ProjectRoot"

    if (-not (Test-Path -LiteralPath $ComposeFile)) {
        throw "未找到 Compose 文件：$ComposeFile"
    }
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '未找到 docker 命令，请先安装 Docker Desktop。'
    }

    Start-DockerEngine
    Invoke-Docker -Arguments @('compose', '-f', $ComposeFile, 'config', '--quiet') | Out-Null
    Write-StartupLog 'Docker Compose 配置检查通过。' 'OK'

    Test-RequiredPorts

    Write-StartupLog '先启动 PostgreSQL、Redis 和可选的 ClamAV 基础服务。'
    Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile,
        'up', '-d', 'postgres', 'redis', 'clamav'
    ) | Out-Null

    # 后端依赖 PostgreSQL 健康。先按真实状态等待数据库恢复，避免 Compose 在
    # 异常关机恢复期间提前判定依赖失败并把后端、前端留在 Created 状态。
    Wait-ForPostgresRecovery

    Write-StartupLog '数据库已就绪，启动后端和前端并检查镜像依赖更新。'
    Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile,
        'up', '-d', '--build', 'backend', 'frontend'
    ) | Out-Null

    Wait-ForServices

    Write-StartupLog '执行数据库增量迁移；已有迁移会自动跳过。'
    Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile,
        'exec', '-T', 'backend',
        'python', 'manage.py', 'migrate', '--noinput'
    ) | Out-Null
    Write-StartupLog '数据库增量迁移检查完成。' 'OK'

    Write-StartupLog '启动业务通知自动发送进程。'
    Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile,
        'up', '-d', '--no-deps', 'notification-worker'
    ) | Out-Null
    $notificationWorkerState = Get-ContainerHealth -ContainerName 'haiqu-notification-worker'
    if ($notificationWorkerState -notin @('running', 'healthy')) {
        throw "通知发送进程未运行：$notificationWorkerState"
    }
    Write-StartupLog '通知发送进程已运行；缺少企业微信配置时自动等待配置。' 'OK'

    Assert-DataMount -ContainerName 'haiqu-postgres' -Destination '/var/lib/postgresql/data' -ExpectedHostPath (Join-Path $ProjectRoot 'data\postgres')
    Assert-DataMount -ContainerName 'haiqu-redis' -Destination '/data' -ExpectedHostPath (Join-Path $ProjectRoot 'data\redis')

    Test-ApplicationEndpoints

    if ($enableQuickTunnel) {
        $QuickTunnelUrl = Start-QuickTunnel
    }

    Write-StartupLog 'haiqu ERP 启动与联调验证全部成功。' 'OK'
    Write-Host ''
    Write-Host '本机前端地址： http://localhost:8080' -ForegroundColor Green
    Write-Host '本机后端地址： http://localhost:8000' -ForegroundColor Green
    Write-Host '健康检查地址： http://localhost:8000/api/health/' -ForegroundColor Green
    Write-Host '本机数据库：   127.0.0.1:15432（容器内 postgres:5432）' -ForegroundColor Green
    Write-Host '本机 Redis：   127.0.0.1:16379（容器内 redis:6379）' -ForegroundColor Green
    if (-not [string]::IsNullOrWhiteSpace($QuickTunnelUrl)) {
        Save-QuickTunnelDesktopRecord -Url $QuickTunnelUrl
        Write-Host ''
        Write-Host '========== 公网访问启动成功 ==========' -ForegroundColor Green
        Write-Host "公网地址：$QuickTunnelUrl" -ForegroundColor Green
        Write-Host '该地址已通过首页和后端健康检查，可发送给同事。' -ForegroundColor Green
        Write-Host '电脑关机或 cloudflared 停止后，该临时地址会失效。' -ForegroundColor Yellow
        Write-Host '桌面已保存：haiqu ERP 当前公网地址.txt' -ForegroundColor Green
        Write-Host '桌面可双击：打开 haiqu ERP 公网版.url' -ForegroundColor Green
        if ($QuickTunnelUsedDnsFallback) {
            Write-Host '提示：本机默认 DNS 尚未同步该新域名；Cloudflare 公共 DNS 验证已通过。' -ForegroundColor Yellow
            Write-Host '若同事提示域名无法解析，可让其启用浏览器“安全 DNS（Cloudflare）”。' -ForegroundColor Yellow
        }
        elseif ($QuickTunnelUsedSystemProxy) {
            Write-Host '提示：当前电脑通过 Windows 系统代理完成公网验证。' -ForegroundColor Yellow
        }
        Write-Host '======================================' -ForegroundColor Green
        try {
            Set-Clipboard -Value $QuickTunnelUrl
            Write-StartupLog '公网地址已复制到剪贴板。' 'OK'
        }
        catch {
            Write-StartupLog '无法自动复制公网地址，请从窗口中手动复制。' 'WARN'
        }
    }
    Write-Host "日志      : $LogFile" -ForegroundColor Green

    if (-not $NoBrowser) {
        Write-StartupLog "打开浏览器：$FrontendUrl"
        Start-Process $FrontendUrl | Out-Null
    }

    Write-Host ''
    $closeDelaySeconds = if ([string]::IsNullOrWhiteSpace($QuickTunnelUrl)) { 5 } else { 15 }
    Write-Host "启动窗口将在 $closeDelaySeconds 秒后关闭。" -ForegroundColor DarkGray
    Start-Sleep -Seconds $closeDelaySeconds
}
catch {
    $exitCode = 1
    Write-FailureDiagnostics -ErrorRecord $_
}

exit $exitCode
