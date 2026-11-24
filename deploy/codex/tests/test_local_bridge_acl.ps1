$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# 只加载纯权限判定函数；绝不执行启动脚本主体、Set-Acl 或连接桥。
$ScriptPath = Join-Path $PSScriptRoot '..\local_codex_bridge.ps1'
$Tokens = $null
$ParseErrors = $null
$Syntax = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count -ne 0) { throw 'BRIDGE_SCRIPT_SYNTAX_ERROR' }
$Function = $Syntax.Find({ param($Node)
    $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Test-BridgeStateAcl'
}, $true)
if ($null -eq $Function) { throw 'MISSING_TEST_BRIDGE_STATE_ACL' }
. ([ScriptBlock]::Create($Function.Extent.Text))

$CurrentSid = [System.Security.Principal.SecurityIdentifier]'S-1-5-21-100-200-300-500'
$SystemSid = [System.Security.Principal.SecurityIdentifier]'S-1-5-18'
$OtherSid = [System.Security.Principal.SecurityIdentifier]'S-1-5-21-100-200-300-501'

function New-TestAcl {
    $Acl = New-Object System.Security.AccessControl.DirectorySecurity
    $Acl.SetOwner($CurrentSid)
    $Acl.SetAccessRuleProtection($true, $false)
    foreach ($Identity in @($CurrentSid, $SystemSid)) {
        $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule($Identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $Acl.AddAccessRule($Rule)
    }
    return $Acl
}

function Assert-AclResult {
    param([string]$Name, [System.Security.AccessControl.DirectorySecurity]$Acl, [bool]$Expected)
    if ((Test-BridgeStateAcl -Acl $Acl -CurrentSid $CurrentSid) -ne $Expected) { throw "ACL_TEST_FAILED: $Name" }
    Write-Output "PASS $Name"
}

Assert-AclResult 'exact_owner_and_rules' (New-TestAcl) $true

$Acl = New-TestAcl
$Acl.SetSecurityDescriptorSddlForm($Acl.GetSecurityDescriptorSddlForm('Owner,Access').Replace('D:P', 'D:PAI'))
Assert-AclResult 'auto_inherit_metadata_with_identical_rules' $Acl $true

$Acl = New-TestAcl
$Acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($OtherSid, 'Read', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
Assert-AclResult 'extra_allow_rule_rejected' $Acl $false

$Acl = New-TestAcl
$Acl.SetAccessRuleProtection($false, $true)
Assert-AclResult 'inheritance_enabled_rejected' $Acl $false

$Acl = New-TestAcl
$Acl.SetOwner($OtherSid)
Assert-AclResult 'different_owner_rejected' $Acl $false

$Acl = New-TestAcl
$Acl.SetAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($CurrentSid, 'Read', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
Assert-AclResult 'reduced_rights_rejected' $Acl $false

$Acl = New-TestAcl
$Acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($CurrentSid, 'Write', 'ContainerInherit,ObjectInherit', 'None', 'Deny')))
Assert-AclResult 'extra_deny_rule_rejected' $Acl $false

$Acl = New-TestAcl
$Acl.SetSecurityDescriptorSddlForm($Acl.GetSecurityDescriptorSddlForm('Owner,Access').Replace('(A;OICI;', '(A;OICIID;'))
Assert-AclResult 'inherited_rules_rejected' $Acl $false

$Acl = New-TestAcl
$Acl.SetAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($CurrentSid, 'FullControl', 'None', 'None', 'Allow')))
Assert-AclResult 'missing_child_inheritance_rejected' $Acl $false

Write-Output 'BRIDGE_ACL_TESTS_PASSED 9'
