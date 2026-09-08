param([ValidateSet('Prepare','BeforeCompile','Report')][string]$Mode = 'Report')
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Storage setup is restricted to Windows GitHub Actions runners.'
}
$volumes = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object { $_.FileSystem -eq 'NTFS' } | Sort-Object FreeSpace -Descending)
foreach ($volume in $volumes) { Write-Host ('DISK {0}: free {1:N1} GiB / total {2:N1} GiB' -f $volume.DeviceID,($volume.FreeSpace/1GB),($volume.Size/1GB)) }
if ($Mode -eq 'Report') { return }
if ($Mode -eq 'Prepare') {
    if (-not $volumes.Count -or $volumes[0].FreeSpace -lt 40GB) { throw 'No NTFS volume has the required initial 40 GiB free. Stopping before source/dependency downloads.' }
    if ($env:GITHUB_RUN_ID -notmatch '^\d+$' -or $env:GITHUB_RUN_ATTEMPT -notmatch '^\d+$') { throw 'Invalid run identity.' }
    $buildPath = Join-Path ($volumes[0].DeviceID + '\') 'TelegramPersonalBuildV22'
    if (Test-Path -LiteralPath $buildPath) { throw 'Build directory already exists; refusing to reuse unknown content.' }
    New-Item -ItemType Directory -Path $buildPath | Out-Null
    & compact.exe /C /Q $buildPath
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enable NTFS build-directory compression.' }
    if (-not ((Get-Item -LiteralPath $buildPath).Attributes -band [IO.FileAttributes]::Compressed)) { throw 'NTFS compression attribute was not applied.' }
    New-Item -ItemType Directory -Path (Join-Path $buildPath 'Libraries'),(Join-Path $buildPath 'Temp') | Out-Null
    $link = Join-Path $env:GITHUB_WORKSPACE 'TBuild'
    New-Item -ItemType Junction -Path $link -Target $buildPath | Out-Null
    "TBUILD=$link" >> $env:GITHUB_ENV
    "BUILD_STORAGE=$buildPath" >> $env:GITHUB_ENV
    "STORAGE_KEY=$($volumes[0].DeviceID.TrimEnd(':'))" >> $env:GITHUB_ENV
    "LibrariesPath=$link\Libraries\win64" >> $env:GITHUB_ENV
    "TEMP=$buildPath\Temp" >> $env:GITHUB_ENV
    "TMP=$buildPath\Temp" >> $env:GITHUB_ENV
    Write-Host "Actual compressed build storage: $buildPath"
    return
}
$actual = (Get-Item -LiteralPath $env:TBUILD).Target
if (-not $env:BUILD_STORAGE -or $actual -ne $env:BUILD_STORAGE) { throw 'Unexpected build storage target.' }
# Restored archives can override compression flags. Reapply only to this run's build tree.
& compact.exe /C /S:$env:BUILD_STORAGE /Q
if ($LASTEXITCODE -ne 0) { throw 'Build tree compression failed.' }
$drive = [IO.Path]::GetPathRoot($env:BUILD_STORAGE).TrimEnd('\')
$volume = Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DeviceID -eq $drive }
Write-Host ('Before Telegram compilation: {0:N1} GiB free on {1}' -f ($volume.FreeSpace/1GB),$drive)
# Conservative guard, not a measured guarantee of the final build's peak usage.
if ($volume.FreeSpace -lt 25GB) { throw 'Less than 25 GiB free after dependencies. Stopping before the lengthy Telegram compilation; a larger build disk is required.' }
