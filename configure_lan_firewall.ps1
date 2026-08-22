[CmdletBinding()]
param(
    [string]$RemoteSubnet = '192.168.1.0/24'
)

$ErrorActionPreference = 'Stop'
$rules = @(
    @{ Name = 'haiqu ERP Frontend (LAN)'; Port = 5173 },
    @{ Name = 'haiqu ERP Backend (LAN)'; Port = 8000 }
)

foreach ($rule in $rules) {
    Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction Stop

    New-NetFirewallRule `
        -DisplayName $rule.Name `
        -Description "Allow haiqu ERP development access from $RemoteSubnet only." `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $rule.Port `
        -RemoteAddress $RemoteSubnet `
        -Profile Any | Out-Null
}

Write-Host "haiqu ERP firewall rules created for $RemoteSubnet on TCP 5173 and 8000." -ForegroundColor Green
