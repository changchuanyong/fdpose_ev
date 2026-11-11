[CmdletBinding()]
param([switch]$Install)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $projectRoot 'artifacts\installers\vs_BuildTools_2022.exe'
$componentConfig = Join-Path $projectRoot 'config\windows-build-tools.vsconfig'
$installRoot = 'C:\BuildTools\Fdonpose'
$expectedHash = '972D771C33C2887B13900C2052E5D2E88208531F6D5EE3C4405D7648E853009B'
$installerArgs = @(
    '--installPath', ('"{0}"' -f $installRoot),
    '--config', ('"{0}"' -f $componentConfig),
    '--passive', '--wait', '--norestart', '--nocache'
)

if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Missing reviewed installer: $installer"
}
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Installer hash changed; verify the new Microsoft download before installing.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'A valid Microsoft Corporation signature is required.'
}
if (Test-Path -LiteralPath $installRoot) {
    throw "Refusing to change an existing installation: $installRoot"
}
$config = Get-Content -LiteralPath $componentConfig -Raw | ConvertFrom-Json
$required = @(
    'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
    'Microsoft.VisualStudio.Component.VC.14.38.17.8.x86.x64',
    'Microsoft.VisualStudio.Component.Windows11SDK.22621'
)
if (Compare-Object -ReferenceObject $required -DifferenceObject @($config.components)) {
    throw 'The component list differs from the reviewed installation scope.'
}

Write-Output "Installer: $installer"
Write-Output "Arguments: $($installerArgs -join ' ')"
Write-Output 'Scope: new VS 2022 instance, MSVC 14.38, Windows SDK 22621 and their required dependencies.'
if (-not $Install) {
    Write-Output 'PREVIEW ONLY. No system changes. Use -Install only after explicit system-install approval.'
    return
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run from an elevated PowerShell after system-install approval.'
}
$journalDir = Join-Path $projectRoot ('artifacts\environment\build-tools-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $journalDir | Out-Null
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
& $vswhere -all -products '*' -format json -utf8 | Set-Content -LiteralPath (Join-Path $journalDir 'before.json') -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Could not record the existing Visual Studio installations.' }
$receipt = [ordered]@{
    installer_sha256 = $expectedHash
    install_root = $installRoot
    components = $required
    install_exit_code = $null
    rollback_exit_code = $null
    reboot_required = $false
}
try {
    $process = Start-Process -FilePath $installer -ArgumentList $installerArgs -WindowStyle Hidden -Wait -PassThru
    $receipt.install_exit_code = $process.ExitCode
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "Visual Studio installation failed with exit code $($process.ExitCode)."
    }
    $receipt.reboot_required = $process.ExitCode -eq 3010
    Write-Output "Installer completed. Reboot required: $($receipt.reboot_required). Run check_environment.cmd before builds."
}
catch {
    # The path did not exist before this invocation; target only this new instance.
    if (Test-Path -LiteralPath $installRoot) {
        $rollbackArgs = @('uninstall', '--installPath', ('"{0}"' -f $installRoot), '--quiet', '--wait', '--norestart')
        $rollback = Start-Process -FilePath $installer -ArgumentList $rollbackArgs -WindowStyle Hidden -Wait -PassThru
        $receipt.rollback_exit_code = $rollback.ExitCode
        if ($rollback.ExitCode -notin @(0, 3010)) {
            Write-Warning "Rollback requires attention (exit $($rollback.ExitCode)); preserve the journal."
        }
    }
    throw
}
finally {
    $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $journalDir 'receipt.json') -Encoding utf8
    & $vswhere -all -products '*' -format json -utf8 | Set-Content -LiteralPath (Join-Path $journalDir 'after.json') -Encoding utf8
}
