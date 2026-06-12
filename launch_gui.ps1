param(
    [string]$CodexHome = "",
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Get-PythonLauncher {
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $oldPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $versionOutput = & py -3 --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                return @{ Command = 'py'; Prefix = @('-3') }
            }
        } finally {
            $ErrorActionPreference = $oldPreference
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $oldPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $versionOutput = & python --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                return @{ Command = 'python'; Prefix = @() }
            }
        } finally {
            $ErrorActionPreference = $oldPreference
        }
    }

    throw 'Python 3.10+ was not found. Please make sure py or python is available.'
}

$Python = Get-PythonLauncher

if ($SmokeTest) {
    Write-Output 'Smoke test passed.'
    exit 0
}

$PythonArgs = @()
$PythonArgs += $Python.Prefix
$PythonArgs += @('-m', 'codex_session_doctor')

if ($CodexHome) {
    $PythonArgs += @('--codex-home', $CodexHome, 'gui')
} else {
    $PythonArgs += 'gui'
}

& $Python.Command @PythonArgs
