param(
    [switch]$SkipModel,
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host 'Finance Controller · Windows setup' -ForegroundColor Cyan
Write-Host "Project: $projectRoot" -ForegroundColor DarkGray

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw 'Python was not found. Install Miniforge/Miniconda, run `conda activate base`, and retry.'
}

$pythonVersion = & $pythonCommand.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
$pythonSupported = & $pythonCommand.Source -c "import sys; print(int(sys.version_info >= (3, 10)))"
if ($pythonSupported -ne '1') {
    throw "Python 3.10+ is required; found $pythonVersion."
}
if ($env:CONDA_DEFAULT_ENV -and $env:CONDA_DEFAULT_ENV -ne 'base') {
    throw "Activate the Conda base environment first; current environment is '$env:CONDA_DEFAULT_ENV'."
}
Write-Host "Python $pythonVersion" -ForegroundColor Green

Push-Location $projectRoot
try {
    Write-Host 'Installing pinned Python dependencies...' -ForegroundColor DarkGray
    & $pythonCommand.Source -m pip install -r requirements.txt

    $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
    $corepackCommand = Get-Command corepack -ErrorAction SilentlyContinue
    if ($pnpmCommand) {
        $packageCommand = $pnpmCommand.Source
        $packagePrefix = @()
    } elseif ($corepackCommand) {
        $packageCommand = $corepackCommand.Source
        $packagePrefix = @('pnpm')
    } else {
        throw 'pnpm/Corepack was not found. Install Node.js 22+, reopen PowerShell, and retry.'
    }

    Write-Host 'Installing the pinned frontend dependency graph...' -ForegroundColor DarkGray
    Push-Location (Join-Path $projectRoot 'web')
    try {
        & $packageCommand @packagePrefix install --frozen-lockfile
    } finally {
        Pop-Location
    }

    if (-not $SkipModel) {
        Write-Host 'Downloading checksum-pinned Qwen and CUDA llama.cpp artifacts...' -ForegroundColor DarkGray
        & $pythonCommand.Source scripts\download_local_model.py
    } else {
        Write-Host 'Skipped model download. Deterministic pipeline commands will still work.' -ForegroundColor Yellow
    }

    if (-not $SkipChecks) {
        Write-Host 'Running deterministic tests...' -ForegroundColor DarkGray
        & $pythonCommand.Source -m unittest discover -v
        Push-Location (Join-Path $projectRoot 'web')
        try {
            & $packageCommand @packagePrefix run lint
            & $packageCommand @packagePrefix run build
        } finally {
            Pop-Location
        }
    }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host 'Start the complete local demo with: .\start-dashboard.ps1' -ForegroundColor Cyan
