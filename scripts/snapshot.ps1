<#
.SYNOPSIS
  Stage snapshot: verify the repo is clean and the stage tag is pushed, then shut down WSL,
  export the distro and write a SHA256 file.

.DESCRIPTION
  Run from a normal (non-admin) Windows PowerShell. Copy this file to C:\wsl-snapshots\ first:
  the script runs wsl --shutdown, after which \\wsl.localhost paths are gone.
  ASCII only on purpose: Windows PowerShell 5.1 misreads UTF-8 files without a BOM.

.EXAMPLE
  Copy-Item \\wsl.localhost\Ubuntu-24.04\home\llm\projects\llm-gateway-governance\scripts\snapshot.ps1 C:\wsl-snapshots\ -Force
  powershell -ExecutionPolicy Bypass -File C:\wsl-snapshots\snapshot.ps1 -Stage p1-models
  powershell -ExecutionPolicy Bypass -File C:\wsl-snapshots\snapshot.ps1 -Stage p1-models -CopyTo E:\wsl-snapshots
#>
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^p\d[a-z0-9-]*$')][string]$Stage,
    [string]$Distro = 'Ubuntu-24.04',
    [string]$RepoPath = '/home/llm/projects/llm-gateway-governance',
    [string]$OutDir = 'C:\wsl-snapshots',
    [string]$CopyTo = ''
)
$ErrorActionPreference = 'Stop'

function Fail([string]$msg) { Write-Host "FAIL $msg" -ForegroundColor Red; exit 1 }
function Pass([string]$msg) { Write-Host "PASS $msg" -ForegroundColor Green }

function Invoke-RepoGit([string[]]$GitArgs) {
    # PS 5.1 turns native stderr into terminating errors under 'Stop'; relax it locally
    $ErrorActionPreference = 'Continue'
    $out = & wsl.exe -d $Distro --cd $RepoPath --exec git @GitArgs 2>&1
    return @{ Code = $LASTEXITCODE; Out = (($out | ForEach-Object { "$_" }) -join "`n").Trim() }
}

# 1. Working tree clean
$r = Invoke-RepoGit @('status', '--porcelain')
if ($r.Code -ne 0) { Fail "cannot read repo status: $($r.Out)" }
if ($r.Out) { Fail "uncommitted changes, commit first:`n$($r.Out)" }
Pass 'working tree clean'

# 2. Every local commit is pushed
$r = Invoke-RepoGit @('rev-list', '--count', '@{u}..HEAD')
if ($r.Code -ne 0) { Fail "cannot compare with upstream: $($r.Out)" }
if ([int]$r.Out -gt 0) { Fail "$($r.Out) commit(s) not pushed, run git push" }
Pass 'all commits pushed'

# 3. Stage tag points at HEAD and is on origin
$head = (Invoke-RepoGit @('rev-parse', 'HEAD')).Out
$r = Invoke-RepoGit @('rev-list', '-n', '1', $Stage)
if ($r.Code -ne 0) { Fail "no local tag $Stage, run git tag $Stage" }
if ($r.Out -ne $head) { Fail "tag $Stage is not HEAD (tag=$($r.Out.Substring(0,7)) HEAD=$($head.Substring(0,7)))" }
$r = Invoke-RepoGit @('ls-remote', '--tags', 'origin', "refs/tags/$Stage")
if ($r.Code -ne 0 -or -not $r.Out) { Fail "tag $Stage not on origin, run git push origin $Stage" }
Pass "tag $Stage = HEAD and pushed"

# 4. Target file and disk space
New-Item -ItemType Directory -Force $OutDir | Out-Null
$tar = Join-Path $OutDir "$Stage.tar"
$sha = Join-Path $OutDir "$Stage.sha256.txt"
if (Test-Path $tar) { Fail "$tar exists; rename or delete it first" }
$free = (Get-PSDrive -Name ($OutDir.Substring(0, 1))).Free / 1GB
$lxss = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
$base = Get-ChildItem $lxss -ErrorAction SilentlyContinue | ForEach-Object { Get-ItemProperty $_.PSPath } |
        Where-Object { $_.DistributionName -eq $Distro } | Select-Object -First 1 -ExpandProperty BasePath
$vhd = if ($base) { Join-Path ($base -replace '^\\\\\?\\', '') 'ext4.vhdx' } else { '' }
if ($vhd -and (Test-Path $vhd)) {
    $need = (Get-Item $vhd).Length / 1GB
    Write-Host ("Disk: {0:N1} GB free, distro vhdx {1:N1} GB" -f $free, $need)
    if ($free -lt $need) { Write-Host 'WARN free space is below the vhdx size; export may fail' -ForegroundColor Yellow }
} else {
    Write-Host ("Disk: {0:N1} GB free (vhdx not found, size check skipped)" -f $free)
}

# 5. Shut down WSL and export
Write-Host 'Shutting down WSL (close all Ubuntu terminals and VS Code first)...'
& wsl.exe --shutdown
Start-Sleep -Seconds 5
Write-Host "Exporting $Distro -> $tar ..."
$t0 = Get-Date
& wsl.exe --export $Distro $tar
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $tar)) { Fail 'export failed' }
$mins = ((Get-Date) - $t0).TotalMinutes
$gb = (Get-Item $tar).Length / 1GB
$hash = (Get-FileHash $tar -Algorithm SHA256).Hash.ToLower()
"$hash  $Stage.tar" | Out-File -Encoding ascii $sha
Pass ("exported {0}, {1:N2} GB in {2:N1} min" -f $tar, $gb, $mins)
Write-Host "SHA256 $hash"

# 6. Optional: copy to an external drive and verify
if ($CopyTo) {
    New-Item -ItemType Directory -Force $CopyTo | Out-Null
    Copy-Item $tar, $sha -Destination $CopyTo -Force
    $copyHash = (Get-FileHash (Join-Path $CopyTo "$Stage.tar") -Algorithm SHA256).Hash.ToLower()
    if ($copyHash -ne $hash) { Fail "hash mismatch after copying to $CopyTo" }
    Pass "copied to $CopyTo, hash verified"
}

Write-Host ''
Write-Host 'Row for docs/progress.md (paste it next time Ubuntu is open):'
Write-Host ("| {0} | {1:yyyy-MM-dd} | {2:N2} GB | {3} |" -f $Stage, (Get-Date), $gb, $hash.Substring(0, 16))
