# Spike helper: drop the test datapack into the newest 1.21.11 world.
#
# Searches both the shared saves folder and per-version isolated saves,
# picks the most recently modified world, and copies spike/testpack in.
# Throwaway.

$ErrorActionPreference = "Stop"
$packSrc = Join-Path $PSScriptRoot "testpack"

$roots = @("$env:APPDATA\.minecraft\saves")
Get-ChildItem "$env:APPDATA\.minecraft\versions" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object {
        $s = Join-Path $_.FullName "saves"
        if (Test-Path $s) { $roots += $s }
    }

$candidates = @()
foreach ($r in $roots) {
    Get-ChildItem $r -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        if (Test-Path (Join-Path $_.FullName "level.dat")) { $candidates += $_ }
    }
}

if ($candidates.Count -eq 0) { Write-Output "No worlds found."; exit 1 }

$newest = $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Output "Newest world: $($newest.FullName)"
Write-Output "Last modified: $($newest.LastWriteTime)"

$dpDir = Join-Path $newest.FullName "datapacks"
if (-not (Test-Path $dpDir)) { New-Item -ItemType Directory -Force $dpDir | Out-Null }

$dest = Join-Path $dpDir "testpack"
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
Copy-Item $packSrc $dest -Recurse -Force

Write-Output ""
Write-Output "Installed datapack -> $dest"
Write-Output "Back in game, run:  /reload"
Write-Output "then:               /function tt:setup"
Write-Output "then:               /function tt:messages"
