param(
    [string]$CodexHome = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if ($CodexHome) {
    py -3 -m codex_session_doctor --codex-home $CodexHome gui
} else {
    py -3 -m codex_session_doctor gui
}

