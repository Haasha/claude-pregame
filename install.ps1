# claude-pregame installer for Windows.
#   irm https://raw.githubusercontent.com/Haasha/claude-pregame/main/install.ps1 | iex
$ErrorActionPreference = 'Stop'

$raw = if ($env:PREGAME_RAW) { $env:PREGAME_RAW } else { 'https://raw.githubusercontent.com/Haasha/claude-pregame/main' }
$dir = Join-Path $env:LOCALAPPDATA 'claude-pregame'

function Fail($msg) { Write-Host "pregame: $msg" -ForegroundColor Red; exit 1 }

# Find a real Python 3.8+ (skips the Microsoft Store "python" alias, which isn't Python).
$py = $null
foreach ($cand in @('py -3', 'python', 'python3')) {
    $parts = $cand -split ' '
    $rest = @($parts | Select-Object -Skip 1)
    if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
    try {
        $exe = & $parts[0] @rest -c 'import sys; assert sys.version_info >= (3, 8); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { $py = $exe.Trim(); break }
    } catch { }
}
if (-not $py) { Fail 'Python 3.8+ not found. Install it with: winget install Python.Python.3.12   (then open a new terminal and re-run)' }

$claudeFound = (Get-Command claude -ErrorAction SilentlyContinue) -or (Test-Path "$env:USERPROFILE\.local\bin\claude.exe")
if (-not $claudeFound) { Fail 'Claude Code not found. Install it first: https://claude.com/claude-code' }

New-Item -ItemType Directory -Force -Path $dir | Out-Null
$target = Join-Path $dir 'pregame.py'
$local = if ($PSScriptRoot) { Join-Path $PSScriptRoot 'pregame.py' } else { $null }
if ($local -and (Test-Path $local) -and ($PSScriptRoot -ne $dir)) {
    Copy-Item $local $target -Force
} else {
    Invoke-WebRequest -UseBasicParsing "$raw/pregame.py" -OutFile $target
}

Write-Host 'Installing claude-pregame...'
& $py $target install
if ($LASTEXITCODE -ne 0) { Fail 'install failed (see above)' }

$bin = Join-Path $env:USERPROFILE '.local\bin'
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (($userPath -split ';') -contains $bin)) {
    Write-Host ''
    Write-Host "Note: add $bin to your PATH to use the 'pregame' command."
}
Write-Host ''
Write-Host 'Done. Commands: pregame status | pregame logs | pregame uninstall'
