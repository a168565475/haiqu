[CmdletBinding()]
param(
    [int]$DockerTimeoutSeconds = 180,
    [int]$ServiceTimeoutSeconds = 240,
    [switch]$NoBrowser
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot 'compose.yml'
$LogDirectory = Join-Path $ProjectRoot 'logs'
$FrontendUrl = 'http://localhost:5173'
$HealthUrl = 'http://localhost:8000/api/health/'
$LanIp = $null
$DockerDesktopPath = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$ExpectedContainers = [ordered]@{
    postgres = 'haiqu-postgres'
    redis = 'haiqu-redis'
    backend = 'haiqu-backend'
    frontend = 'haiqu-frontend'
}
$RequiredPorts = @(5432, 6380, 8000, 5173)

if (-not (Test-Path -LiteralPath $LogDirectory)) {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
}

$LogFile = Join-Path $LogDirectory ("startup_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))

function Write-StartupLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet('INFO', 'OK', 'WARN', 'ERROR')][string]$Level = 'INFO'
    )

    $line = '[{0}] [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8

    $color = switch ($Level) {
        'OK' { 'Green' }
        'WARN' { 'Yellow' }
        'ERROR' { 'Red' }
        default { 'Cyan' }
    }
    Write-Host $line -ForegroundColor $color
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
        throw "命令失败（退出码 $exitCode）：$commandText`n$($output -join [Environment]::NewLine)"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Test-DockerEngine {
    $result = Invoke-Docker -Arguments @('info', '--format', '{{.ServerVersion}}') -Quiet -AllowFailure
    return ($result.ExitCode -eq 0)
}

function Get-ActiveLanIPv4 {
    $configurations = @(Get-NetIPConfiguration -ErrorAction SilentlyContinue | Where-Object {
        $null -ne $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up'
    })

    foreach ($configuration in $configurations) {
        $address = @($configuration.IPv4Address | Where-Object {
            $_.AddressState -eq 'Preferred' -and
            $_.IPAddress -notlike '127.*' -and
            $_.IPAddress -notlike '169.254.*'
        } | Select-Object -First 1)
        if ($address.Count -gt 0) {
            return [string]$address[0].IPAddress
        }
    }
    return $null
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
    Write-StartupLog '检查主机端口 5432、6380、8000、5173...'
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

function Wait-ForServices {
    Write-StartupLog "等待全部服务通过健康检查，最长 $ServiceTimeoutSeconds 秒..."
    $deadline = (Get-Date).AddSeconds($ServiceTimeoutSeconds)
    $previousSummary = ''

    do {
        $states = [ordered]@{}
        foreach ($entry in $ExpectedContainers.GetEnumerator()) {
            $states[$entry.Key] = Get-ContainerHealth -ContainerName $entry.Value
        }

        $summary = ($states.GetEnumerator() | ForEach-Object { '{0}={1}' -f $_.Key, $_.Value }) -join ', '
        if ($summary -ne $previousSummary) {
            Write-StartupLog "当前状态：$summary"
            $previousSummary = $summary
        }

        $failed = @($states.GetEnumerator() | Where-Object { $_.Value -in @('exited', 'dead', 'unhealthy', 'missing') })
        if ($failed.Count -gt 0) {
            $failedSummary = ($failed | ForEach-Object { '{0}={1}' -f $_.Key, $_.Value }) -join ', '
            throw "服务启动失败：$failedSummary"
        }

        $notHealthy = @($states.GetEnumerator() | Where-Object { $_.Value -ne 'healthy' })
        if ($notHealthy.Count -eq 0) {
            Write-StartupLog 'PostgreSQL、Redis、Backend、Frontend 均已 healthy。' 'OK'
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

    $health = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 10
    if (($health.status -ne 'ok') -or ($health.database -ne 'ok') -or ($health.redis -ne 'ok')) {
        throw "Health API 返回异常：$($health | ConvertTo-Json -Compress)"
    }
    Write-StartupLog 'Health API：status=ok, database=ok, redis=ok。' 'OK'

    $postgres = Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile, 'exec', '-T', 'postgres',
        'sh', '-c', 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    ) -Quiet
    if (($postgres.Output -join ' ') -notmatch 'accepting connections') {
        throw "PostgreSQL 验证失败：$($postgres.Output -join ' ')"
    }
    Write-StartupLog 'PostgreSQL：accepting connections。' 'OK'

    $redis = Invoke-Docker -Arguments @(
        'compose', '-f', $ComposeFile, 'exec', '-T', 'redis', 'redis-cli', 'ping'
    ) -Quiet
    if ((($redis.Output -join '').Trim()) -ne 'PONG') {
        throw "Redis 验证失败：$($redis.Output -join ' ')"
    }
    Write-StartupLog 'Redis：PONG。' 'OK'

    $frontendResponse = Invoke-WebRequest -Uri $FrontendUrl -Method Get -UseBasicParsing -TimeoutSec 10
    if ($frontendResponse.StatusCode -ne 200) {
        throw "前端验证失败：HTTP $($frontendResponse.StatusCode)"
    }
    Write-StartupLog 'Frontend：HTTP 200。' 'OK'

    if (-not [string]::IsNullOrWhiteSpace($script:LanIp)) {
        $lanHealthUrl = "http://$script:LanIp`:8000/api/health/"
        $lanFrontendUrl = "http://$script:LanIp`:5173"
        $lanHealth = Invoke-RestMethod -Uri $lanHealthUrl -Method Get -TimeoutSec 10
        $lanFrontend = Invoke-WebRequest -Uri $lanFrontendUrl -Method Get -UseBasicParsing -TimeoutSec 10
        if (($lanHealth.status -ne 'ok') -or ($lanHealth.database -ne 'ok') -or ($lanHealth.redis -ne 'ok') -or ($lanFrontend.StatusCode -ne 200)) {
            throw '局域网地址验证失败。'
        }
        Write-StartupLog "局域网访问验证成功：$lanFrontendUrl；$lanHealthUrl" 'OK'
    }
}

function Write-FailureDiagnostics {
    param([Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord)

    Write-StartupLog $ErrorRecord.Exception.Message 'ERROR'
    Write-StartupLog "完整启动日志：$LogFile" 'ERROR'

    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -ne $dockerCommand -and (Test-DockerEngine)) {
        Write-Host ''
        Write-Host '--- 服务状态 ---' -ForegroundColor Yellow
        $status = Invoke-Docker -Arguments @('compose', '-f', $ComposeFile, 'ps', '-a') -Quiet -AllowFailure
        if ($status.Output.Count -gt 0) {
            $status.Output | ForEach-Object { Write-Host $_ }
        }

        Write-Host ''
        Write-Host '--- 最近 80 行容器日志 ---' -ForegroundColor Yellow
        $shortLogs = Invoke-Docker -Arguments @('compose', '-f', $ComposeFile, 'logs', '--tail=80', '--no-color') -Quiet -AllowFailure
        if ($shortLogs.Output.Count -gt 0) {
            $shortLogs.Output | ForEach-Object { Write-Host $_ }
        }

        $fullLogs = Invoke-Docker -Arguments @('compose', '-f', $ComposeFile, 'logs', '--tail=200', '--no-color') -Quiet -AllowFailure
        if ($fullLogs.Output.Count -gt 0) {
            Add-Content -LiteralPath $LogFile -Value "`n--- 最近 200 行容器日志 ---" -Encoding UTF8
            Add-Content -LiteralPath $LogFile -Value ($fullLogs.Output -join [Environment]::NewLine) -Encoding UTF8
        }
    }

    Write-Host ''
    Write-Host '排查建议：确认 Docker Desktop 已启动、所需端口未被其他程序占用，并查看上面的首个错误。' -ForegroundColor Yellow
    Write-Host '脚本不会停止其他程序，也不会删除 Docker 卷或 data 目录。' -ForegroundColor Yellow
}

$exitCode = 0
try {
    Write-StartupLog '开始启动 haiqu ERP 开发环境。'
    Write-StartupLog "项目目录：$ProjectRoot"

    $LanIp = Get-ActiveLanIPv4
    if ([string]::IsNullOrWhiteSpace($LanIp)) {
        Write-StartupLog '未检测到带默认网关的局域网 IPv4，将使用 .env 中的 LAN_IP。' 'WARN'
    }
    else {
        $env:LAN_IP = $LanIp
        Write-StartupLog "检测到局域网 IPv4：$LanIp；本次 Compose 配置将自动使用该地址。" 'OK'
    }

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

    Write-StartupLog '启动服务。首次运行或镜像缺失时，Docker Compose 会自动构建所需镜像。'
    Invoke-Docker -Arguments @('compose', '-f', $ComposeFile, 'up', '-d') | Out-Null

    Wait-ForServices

    Assert-DataMount -ContainerName 'haiqu-postgres' -Destination '/var/lib/postgresql/data' -ExpectedHostPath (Join-Path $ProjectRoot 'data\postgres')
    Assert-DataMount -ContainerName 'haiqu-redis' -Destination '/data' -ExpectedHostPath (Join-Path $ProjectRoot 'data\redis')

    Test-ApplicationEndpoints

    Write-StartupLog 'haiqu ERP 启动与联调验证全部成功。' 'OK'
    Write-Host ''
    Write-Host 'Frontend : http://localhost:5173' -ForegroundColor Green
    Write-Host 'Backend  : http://localhost:8000' -ForegroundColor Green
    Write-Host 'Health   : http://localhost:8000/api/health/' -ForegroundColor Green
    Write-Host 'PostgreSQL: 127.0.0.1:5432' -ForegroundColor Green
    Write-Host 'Redis     : 127.0.0.1:6380（容器内 redis:6379）' -ForegroundColor Green
    if (-not [string]::IsNullOrWhiteSpace($LanIp)) {
        Write-Host "局域网前端: http://$LanIp`:5173" -ForegroundColor Green
        Write-Host "局域网后端: http://$LanIp`:8000" -ForegroundColor Green
    }
    Write-Host "日志      : $LogFile" -ForegroundColor Green

    if (-not $NoBrowser) {
        Write-StartupLog "打开浏览器：$FrontendUrl"
        Start-Process $FrontendUrl | Out-Null
    }

    Write-Host ''
    Write-Host '启动窗口将在 5 秒后关闭。' -ForegroundColor DarkGray
    Start-Sleep -Seconds 5
}
catch {
    $exitCode = 1
    Write-FailureDiagnostics -ErrorRecord $_
}

exit $exitCode
