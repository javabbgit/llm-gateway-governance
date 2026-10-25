<#
.SYNOPSIS
  Keep the WSL distro, and the gateway containers in it, running after the last Ubuntu window closes (P5).

.DESCRIPTION
  WSL stops a distro a few seconds after its last session ends (P1 measured it). vmIdleTimeout in .wslconfig
  governs the VM, not the distro, and does not prevent this. The reliable fix is one long-lived process inside
  the distro: this script runs "sleep infinity" in a hidden wsl.exe and records its PID.
  wsl --shutdown (for example in snapshot.ps1) ends it; run "start" again afterwards.
  ASCII only on purpose: Windows PowerShell 5.1 misreads UTF-8 files without a BOM.

.EXAMPLE
  Copy-Item \\wsl.localhost\Ubuntu-24.04\home\llm\projects\llm-gateway-governance\scripts\keepalive.ps1 C:\wsl-snapshots\ -Force
  powershell -ExecutionPolicy Bypass -File C:\wsl-snapshots\keepalive.ps1 start
  powershell -ExecutionPolicy Bypass -File C:\wsl-snapshots\keepalive.ps1 status
  powershell -ExecutionPolicy Bypass -File C:\wsl-snapshots\keepalive.ps1 stop
#>
param(
    [ValidateSet('start', 'stop', 'status')][string]$Action = 'status',
    [string]$Distro = 'Ubuntu-24.04'
)
$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $env:LOCALAPPDATA 'llm-gateway-keepalive.pid'

function Get-Keeper {
    if (-not (Test-Path $pidFile)) { return $null }
    $id = 0
    if (-not [int]::TryParse((Get-Content $pidFile -Raw).Trim(), [ref]$id)) { return $null }
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -eq 'wsl') { return $p }
    return $null
}

function Test-DistroRunning {
    $ErrorActionPreference = 'Continue'
    $out = & wsl.exe --list --running --quiet 2>$null
    $names = $out | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ }
    return ($names -contains $Distro)
}

switch ($Action) {
    'start' {
        $k = Get-Keeper
        if ($k) { Write-Host "PASS keep-alive already running (PID $($k.Id))" -ForegroundColor Green; break }
        $p = Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d', $Distro, '--exec', 'sleep', 'infinity') -WindowStyle Hidden -PassThru
        Set-Content -Path $pidFile -Value $p.Id -Encoding ascii
        Start-Sleep -Seconds 5
        if ((Get-Keeper) -and (Test-DistroRunning)) {
            Write-Host "PASS keep-alive started (PID $($p.Id)); $Distro keeps running after Ubuntu windows close" -ForegroundColor Green
        } else {
            Write-Host 'FAIL keep-alive did not stay up; check with: wsl -l -v' -ForegroundColor Red
            exit 1
        }
    }
    'stop' {
        $k = Get-Keeper
        if ($k) { Stop-Process -Id $k.Id; Write-Host "PASS keep-alive stopped (PID $($k.Id)); WSL may stop once no session is open" -ForegroundColor Green }
        else { Write-Host 'INFO keep-alive was not running' }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
    'status' {
        $k = Get-Keeper
        $run = Test-DistroRunning
        Write-Host ("keep-alive: {0}   {1}: {2}" -f $(if ($k) { "running (PID $($k.Id))" } else { 'not running' }), $Distro, $(if ($run) { 'Running' } else { 'Stopped' }))
    }
}
