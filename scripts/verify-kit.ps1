param([string]$Git = 'git', [string]$Source = '', [switch]$Cloud)
$ErrorActionPreference = 'Stop'
$KitRoot = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $KitRoot 'kit.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function Git-Checked([string[]]$Arguments) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $result = @(& $Git @Arguments 2>&1); $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $oldPreference }
    if ($code -ne 0) { throw ($result -join "`n") }
    return $result
}
$manifest = Get-Content -LiteralPath (Join-Path $KitRoot 'SHA256SUMS.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$uploaded = Get-Content -LiteralPath (Join-Path $KitRoot 'upload-files.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.PSObject.Properties) {
    if ($Cloud -and $uploaded -notcontains $entry.Name) { continue }
    $actual = (Get-FileHash -LiteralPath (Join-Path $KitRoot $entry.Name) -Algorithm SHA256).Hash
    if ($actual -ne $entry.Value) { throw "构建包文件校验失败：$($entry.Name)。请重新解压完整 V2.2 包。" }
}
$patch = Join-Path $KitRoot $config.patch_file
if ((Get-FileHash -LiteralPath $patch).Hash -ne $config.patch_sha256) { throw 'Patch SHA-256 mismatch.' }
if ($Cloud) {
    if (-not $Source) { throw 'Cloud preflight needs a source directory.' }
    $head = (Git-Checked @('-C',$Source,'rev-parse','HEAD')) -join ''
    if ($head -ne $config.source_commit) { throw 'Pinned source commit mismatch.' }
    $dirty = Git-Checked @('-C',$Source,'status','--porcelain','--untracked-files=all')
    if ($dirty) { throw 'Upstream source is not clean before patching.' }
} else {
    $Source = Join-Path $KitRoot ('work\preflight-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Source -Force | Out-Null
    Expand-Archive -LiteralPath (Join-Path $KitRoot 'source-baseline.zip') -DestinationPath $Source
    Git-Checked @('init','--quiet',$Source) | Out-Null
    Git-Checked @('-C',$Source,'config','core.autocrlf','false') | Out-Null
    Git-Checked @('-C',$Source,'add','.') | Out-Null
    Git-Checked @('-C',$Source,'-c','user.name=V2.2 Preflight','-c','user.email=preflight@localhost','-c','commit.gpgsign=false','commit','--quiet','-m','Verified pinned file baseline (partial tree)') | Out-Null
}
foreach ($entry in $config.baseline_blobs.PSObject.Properties) {
    $hash = (Git-Checked @('-C',$Source,'hash-object',('--path=' + $entry.Name),(Join-Path $Source $entry.Name))) -join ''
    if ($hash -ne $entry.Value) { throw "Pinned original blob mismatch: $($entry.Name)" }
}
Git-Checked @('-C',$Source,'apply','--check','--whitespace=error',$patch) | Out-Null
Git-Checked @('-C',$Source,'apply','--whitespace=error',$patch) | Out-Null
foreach ($path in $config.new_files) { Git-Checked @('-C',$Source,'add','-N',$path) | Out-Null }
Git-Checked @('-C',$Source,'diff','--check') | Out-Null
$changed = @(Git-Checked @('-C',$Source,'diff','--name-only')) | Sort-Object
if (Compare-Object @($config.changed_files | Sort-Object) @($changed)) { throw 'Unexpected patch file set.' }
Write-Host 'V2.2 预检通过：固定源码文件哈希、补丁、空白检查和修改文件集合均正确。' -ForegroundColor Green
return $Source
