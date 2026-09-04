$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$condaPython = Join-Path $env:USERPROFILE 'miniforge3\python.exe'
$bundledRuntime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$bundledNode = Join-Path $bundledRuntime 'node\bin\node.exe'
$bundledPnpm = Join-Path $bundledRuntime 'bin\fallback\pnpm.cmd'
$modelPath = Join-Path $projectRoot 'models\qwen3.5-4b\Qwen3.5-4B-Q4_K_M.gguf'
$llamaServer = Join-Path $projectRoot 'runtime\llama.cpp\llama-server.exe'

if (-not (Test-Path -LiteralPath $modelPath) -or -not (Test-Path -LiteralPath $llamaServer)) {
    throw "The project-local Qwen runtime is missing. From $projectRoot run: python scripts\download_local_model.py"
}

$systemPython = Get-Command python -ErrorAction SilentlyContinue
$pythonExecutable = if ($systemPython -and $env:CONDA_DEFAULT_ENV -eq 'base') {
    $systemPython.Source
} elseif (Test-Path -LiteralPath $condaPython) {
    $condaPython
} elseif ($systemPython) {
    $systemPython.Source
} else {
    throw 'Python was not found. Activate Conda base or install Python 3.10+.'
}

$systemPnpm = Get-Command pnpm -ErrorAction SilentlyContinue
$systemCorepack = Get-Command corepack -ErrorAction SilentlyContinue
$pnpmExecutable = if ($systemPnpm) {
    $systemPnpm.Source
} elseif (Test-Path -LiteralPath $bundledPnpm) {
    if (-not (Test-Path -LiteralPath $bundledNode)) {
        throw 'The bundled pnpm runtime exists, but its Node executable is missing.'
    }
    $env:Path = (Split-Path -Parent $bundledNode) + [IO.Path]::PathSeparator + $env:Path
    $bundledPnpm
} elseif ($systemCorepack) {
    $systemCorepack.Source
} else {
    throw 'pnpm/Corepack was not found. Install Node.js 22+, then run scripts\setup_windows.ps1.'
}
$pnpmPrefix = if ($systemPnpm -or (Test-Path -LiteralPath $bundledPnpm)) { @() } else { @('pnpm') }

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'web\node_modules'))) {
    throw 'Frontend dependencies are missing. Run scripts\setup_windows.ps1 first.'
}

$modelJob = $null
$apiJob = $null
try {
    $modelReady = $false
    try {
        $modelHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -TimeoutSec 1
        $modelCatalog = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/v1/models' -TimeoutSec 2
        $modelReady = (
            $modelHealth.status -in @('ok', 'no slot available') -and
            $modelCatalog.data.id -contains 'qwen3.5-4b-q4_k_m'
        )
    } catch {}
    if ($modelReady) {
        Write-Host 'Reusing the healthy project-local Qwen server on port 8001.' -ForegroundColor DarkGray
    } else {
        $modelJob = Start-Job -ScriptBlock {
            param($serverPath, $weightsPath, $workingDirectory)
            Set-Location -LiteralPath $workingDirectory
            & $serverPath --model $weightsPath --ctx-size 4096 --parallel 1 --device CUDA0 --split-mode none --gpu-layers all --fit off --host 127.0.0.1 --port 8001 --alias qwen3.5-4b-q4_k_m --jinja --reasoning off
        } -ArgumentList $llamaServer, $modelPath, $projectRoot
        Write-Host 'Loading project-local Qwen 3.5 4B on the GPU...' -ForegroundColor DarkGray
        for ($attempt = 0; $attempt -lt 240; $attempt++) {
            if ($modelJob.State -in @('Completed', 'Failed', 'Stopped')) {
                $modelFailure = Receive-Job -Job $modelJob | Out-String
                throw "The local Qwen server stopped during startup.`n$modelFailure"
            }
            try {
                $modelHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -TimeoutSec 1
                if ($modelHealth.status -in @('ok', 'no slot available')) {
                    $modelReady = $true
                    break
                }
            } catch {
                Start-Sleep -Milliseconds 500
            }
        }
    }
    if (-not $modelReady) {
        throw 'The local Qwen server did not become ready on port 8001.'
    }

    $env:FINCTRL_MODEL_URL = 'http://127.0.0.1:8001/v1'
    $env:FINCTRL_MODEL = 'qwen3.5-4b-q4_k_m'
    $env:FINCTRL_MODEL_PROVIDER = 'local'

    $apiReady = $false
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1
        $apiReady = $health.status -eq 'ok' -and $health.orchestrator -eq 'langgraph'
    } catch {}
    if ($apiReady) {
        Write-Host 'Reusing the healthy dashboard API on port 8000.' -ForegroundColor DarkGray
    } else {
        $apiJob = Start-Job -ScriptBlock {
            param($pythonPath, $workingDirectory)
            Set-Location -LiteralPath $workingDirectory
            $env:FINCTRL_MODEL_URL = 'http://127.0.0.1:8001/v1'
            $env:FINCTRL_MODEL = 'qwen3.5-4b-q4_k_m'
            $env:FINCTRL_MODEL_PROVIDER = 'local'
            & $pythonPath -m uvicorn dashboard.api:app --host 127.0.0.1 --port 8000
        } -ArgumentList $pythonExecutable, $projectRoot
        for ($attempt = 0; $attempt -lt 24; $attempt++) {
            if ($apiJob.State -in @('Completed', 'Failed', 'Stopped')) {
                $apiFailure = Receive-Job -Job $apiJob | Out-String
                throw "The dashboard API stopped during startup.`n$apiFailure"
            }
            try {
                $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1
                if ($health.status -eq 'ok') {
                    $apiReady = $true
                    break
                }
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }
    }
    if (-not $apiReady) {
        throw 'The dashboard API did not become ready on port 8000.'
    }

    Write-Host ''
    Write-Host 'Finance Controller is ready:' -ForegroundColor Green
    Write-Host '  Dashboard  http://localhost:3000' -ForegroundColor Cyan
    Write-Host '  API        http://127.0.0.1:8000/api/health' -ForegroundColor DarkGray
    Write-Host '  Qwen       http://127.0.0.1:8001/health' -ForegroundColor DarkGray
    Write-Host 'Press Ctrl+C to stop all three services.' -ForegroundColor DarkGray
    Write-Host ''

    Push-Location (Join-Path $projectRoot 'web')
    try {
        & $pnpmExecutable @pnpmPrefix run dev
    } finally {
        Pop-Location
    }
} finally {
    if ($apiJob) {
        Stop-Job -Job $apiJob -ErrorAction SilentlyContinue
        Remove-Job -Job $apiJob -Force -ErrorAction SilentlyContinue
    }
    if ($modelJob) {
        Stop-Job -Job $modelJob -ErrorAction SilentlyContinue
        Remove-Job -Job $modelJob -Force -ErrorAction SilentlyContinue
    }
}
