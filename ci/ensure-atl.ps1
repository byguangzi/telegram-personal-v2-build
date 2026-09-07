param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'This dependency setup is only for a Windows GitHub Actions runner.'
}
if (-not $env:VSINSTALLDIR -or -not $env:VCToolsInstallDir -or $env:VCToolsVersion -notlike '14.44.*') {
    throw 'Initialize the pinned MSVC 14.44 x64 environment first.'
}
$atlInclude = Join-Path $env:VCToolsInstallDir 'atlmfc\include'
$atlLib = Join-Path $env:VCToolsInstallDir 'atlmfc\lib\x64'
function Test-AtlFiles {
    return ((Test-Path -LiteralPath (Join-Path $atlInclude 'atlbase.h')) -and
        (Test-Path -LiteralPath (Join-Path $atlInclude 'atlcomcli.h')) -and
        (Test-Path -LiteralPath (Join-Path $atlLib 'atls.lib')))
}
if (-not (Test-AtlFiles)) {
    if ($VerifyOnly) { throw 'MSVC 14.44 ATL headers/libraries still missing after installation.' }
    $setup = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\setup.exe'
    if (-not (Test-Path -LiteralPath $setup)) { throw 'Visual Studio Installer is not available on the runner.' }
    $installPath = $env:VSINSTALLDIR.TrimEnd('\')
    $component = 'Microsoft.VisualStudio.Component.VC.14.44.17.14.ATL'
    Write-Host "Installing matching ATL component: $component"
    # setup.exe modify waits for its operation; --wait is a bootstrapper option.
    $arguments = 'modify --installPath "' + $installPath + '" --add ' + $component + ' --quiet --norestart --nocache'
    $process = Start-Process -FilePath $setup -ArgumentList $arguments -WorkingDirectory $env:RUNNER_TEMP -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -notin @(0,3010)) { throw "ATL installation failed with exit code $($process.ExitCode)." }
    Write-Host 'Installer finished. The next step refreshes and verifies the compiler environment.'
    return
}
if (-not $VerifyOnly) { Write-Host 'Matching MSVC 14.44 ATL files already exist.'; return }
# Old GYP projects use a legacy VC\atlmfc include path. Supplying the actual
# selected toolset paths also covers those projects through INCLUDE and LIB.
$env:INCLUDE = $atlInclude + ';' + $env:INCLUDE
$env:LIB = $atlLib + ';' + $env:LIB
"INCLUDE=$env:INCLUDE" >> $env:GITHUB_ENV
"LIB=$env:LIB" >> $env:GITHUB_ENV
$probe = Join-Path $env:RUNNER_TEMP 'personal-atl-probe.cpp'
$object = Join-Path $env:RUNNER_TEMP 'personal-atl-probe.obj'
$exe = Join-Path $env:RUNNER_TEMP 'personal-atl-probe.exe'
@'
#include <atlbase.h>
#include <atlcomcli.h>
int main() {
    ATL::CComPtr<IUnknown> pointer;
    ATL::CComBSTR text(L"ATL probe");
    return (pointer.p == nullptr && text.Length() == 9) ? 0 : 1;
}
'@ | Set-Content -LiteralPath $probe -Encoding ASCII
& cl /nologo /EHsc /MT /O2 $probe "/Fo$object" "/Fe$exe" /link ole32.lib oleaut32.lib
if ($LASTEXITCODE -ne 0) { throw 'ATL compile/link probe failed before dependency preparation.' }
& $exe
if ($LASTEXITCODE -ne 0) { throw 'ATL runtime probe failed.' }
Write-Host 'PASS: MSVC 14.44 x64 ATL headers, static library, compile/link and runtime probe.'
