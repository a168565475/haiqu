[CmdletBinding()]
param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status')

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$BridgePython = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$BridgeScript = Join-Path $PSScriptRoot 'bridge\supervisor.py'
$BridgeState = 'E:\CodexData\.codex\private\haiqu-erp-local-codex'
if (-not (Test-Path -LiteralPath $BridgePython -PathType Leaf)) { throw '找不到已配置的 Python 运行环境。' }

if ($Action -eq 'Start') {
    if (-not (Test-Path -LiteralPath $BridgeState)) {
        New-Item -ItemType Directory -Path $BridgeState | Out-Null
    }
    $StateItem = Get-Item -LiteralPath $BridgeState
    if (-not $StateItem.PSIsContainer -or ($StateItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw '连接桥状态路径不是普通目录。'
    }
    $Sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $StateAcl = New-Object System.Security.AccessControl.DirectorySecurity
    $StateAcl.SetOwner($Sid)
    $StateAcl.SetAccessRuleProtection($true, $false)
    foreach ($Identity in @($Sid, [System.Security.Principal.SecurityIdentifier]'S-1-5-18')) {
        $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule($Identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $StateAcl.AddAccessRule($Rule)
    }
    Set-Acl -LiteralPath $BridgeState -AclObject $StateAcl
    # Python 内部持有单实例锁；重复 Start 不会建立第二条连接桥。
    Start-Process -FilePath $BridgePython -ArgumentList @('-I', '-B', '-u', ('"' + $BridgeScript + '"'), 'run') -WindowStyle Hidden | Out-Null
    Write-Output '连接桥已请求启动；可用 -Action Status 查看。模型是否就绪以 ERP 连接设置为准。'
} else {
    & $BridgePython -I -B $BridgeScript $Action.ToLowerInvariant()
    if ($LASTEXITCODE -ne 0) { throw '连接桥控制操作失败。' }
}
