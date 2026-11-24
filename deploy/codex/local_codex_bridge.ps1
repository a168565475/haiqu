[CmdletBinding()]
param([ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status')

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Test-BridgeStateAcl {
    param(
        [System.Security.AccessControl.DirectorySecurity]$Acl,
        [System.Security.Principal.SecurityIdentifier]$CurrentSid
    )
    if ($Acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $CurrentSid.Value -or
        -not $Acl.AreAccessRulesProtected -or -not $Acl.AreAccessRulesCanonical) { return $false }
    $Rules = @($Acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
    if ($Rules.Count -ne 2) { return $false }
    $ExpectedSids = @($CurrentSid.Value, 'S-1-5-18')
    $RuleSids = @()
    foreach ($Rule in $Rules) {
        if ($ExpectedSids -notcontains $Rule.IdentityReference.Value -or $Rule.IsInherited -or
            $Rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $Rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
            $Rule.InheritanceFlags -ne [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit' -or
            $Rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None) { return $false }
        $RuleSids += $Rule.IdentityReference.Value
    }
    return $RuleSids[0] -ne $RuleSids[1]
}

$BridgePython = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$BridgeScript = Join-Path $PSScriptRoot 'bridge\supervisor.py'
$BridgeState = 'E:\CodexData\.codex\private\haiqu-erp-local-codex'
if (-not (Test-Path -LiteralPath $BridgePython -PathType Leaf)) { throw '找不到已配置的 Python 运行环境。' }

if ($Action -eq 'Start') {
    $StateCreated = -not (Test-Path -LiteralPath $BridgeState)
    if ($StateCreated) {
        New-Item -ItemType Directory -Path $BridgeState | Out-Null
    }
    $StateItem = Get-Item -LiteralPath $BridgeState
    if (-not $StateItem.PSIsContainer -or ($StateItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw '连接桥状态路径不是普通目录。'
    }
    $Sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($StateCreated) {
        $StateAcl = New-Object System.Security.AccessControl.DirectorySecurity
        $StateAcl.SetOwner($Sid)
        $StateAcl.SetAccessRuleProtection($true, $false)
        foreach ($Identity in @($Sid, [System.Security.Principal.SecurityIdentifier]'S-1-5-18')) {
            $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule($Identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
            $StateAcl.AddAccessRule($Rule)
        }
        Set-Acl -LiteralPath $BridgeState -AclObject $StateAcl
    }
    # 已有目录只核验所有者和完整 DACL，避免无必要地请求写入安全描述符。
    if (-not (Test-BridgeStateAcl -Acl (Get-Acl -LiteralPath $BridgeState) -CurrentSid $Sid)) {
        throw '连接桥状态目录权限不符合要求；请先由管理员修复，未启动连接桥。'
    }
    # Python 内部持有单实例锁；重复 Start 不会建立第二条连接桥。
    Start-Process -FilePath $BridgePython -ArgumentList @('-I', '-B', '-u', ('"' + $BridgeScript + '"'), 'run') -WindowStyle Hidden | Out-Null
    Write-Output '连接桥已请求启动；可用 -Action Status 查看。模型是否就绪以 ERP 连接设置为准。'
} else {
    & $BridgePython -I -B $BridgeScript $Action.ToLowerInvariant()
    if ($LASTEXITCODE -ne 0) { throw '连接桥控制操作失败。' }
}
