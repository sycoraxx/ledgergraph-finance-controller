# Local Setup and Reproduction

This guide runs Finance Controller locally on Windows with the Conda base
environment and an NVIDIA GPU. The deterministic reconciliation and evaluation
commands also work without downloading the language model.

## Hardware used for the demo

- NVIDIA RTX 3050 Laptop GPU with 4 GB VRAM
- CUDA-capable NVIDIA driver compatible with the bundled CUDA 12.4 runtime
- At least 8 GB system RAM recommended
- Approximately 6 GB free disk space for the model, runtime, dependencies, and
  generated artifacts

## Software prerequisites

1. Git for Windows
2. Miniforge or Miniconda with Python 3.10+
3. Node.js 22.13 or newer
4. PowerShell 5.1 or newer

pnpm does not need to be installed globally when Node's Corepack command is
available. The project pins pnpm in `web/package.json` and all frontend package
versions in `web/pnpm-lock.yaml`.

## Clone

```powershell
git clone https://github.com/sycoraxx/ledgergraph-finance-controller.git
cd ledgergraph-finance-controller
conda activate base
```

## Recommended setup

The setup script installs pinned Python and frontend dependencies, downloads
the checksum-verified Qwen GGUF and Windows CUDA llama.cpp runtime, and runs the
test/build gates:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

The model download is several gigabytes. To install and validate only the
deterministic controller:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -SkipModel
```

## Start the complete dashboard

```powershell
.\start-dashboard.ps1
```

If the machine blocks local PowerShell scripts:

```powershell
.\start-dashboard.cmd
```

The launcher starts and monitors three local services:

| Service | Address | Purpose |
|---|---|---|
| Dashboard | <http://localhost:3000> | Judge-facing control room |
| Controller API | <http://127.0.0.1:8000> | LangGraph workflow and evidence API |
| Local Qwen server | <http://127.0.0.1:8001> | Read-only local explanation layer |

Qwen is launched with all supported layers on `CUDA0`. Press `Ctrl+C` in the
launcher terminal to stop all services.

## Manual installation

```powershell
conda activate base
python -m pip install -r requirements.txt

cd web
corepack pnpm install --frozen-lockfile
cd ..

python scripts\download_local_model.py
```

If `pnpm` is installed globally, `pnpm install --frozen-lockfile` is equivalent
to the Corepack command.

## Run without the language model

The LLM never participates in reconciliation, money arithmetic, journal
construction, or evaluation. These commands need only Python:

```powershell
python run.py
python -m eval.suite
python -m unittest discover -v
```

`python run.py` regenerates and evaluates the current interactive batch.
`python -m eval.suite` runs the slower five-seed robustness suite, known-miss
regression replay, and hash-locked post-freeze fraud holdout.

## Start services manually

After the model runtime has been downloaded:

```powershell
# Terminal 1: Qwen on GPU
.\runtime\llama.cpp\llama-server.exe `
  --model .\models\qwen3.5-4b\Qwen3.5-4B-Q4_K_M.gguf `
  --ctx-size 4096 --parallel 1 --device CUDA0 --gpu-layers all `
  --host 127.0.0.1 --port 8001 --alias qwen3.5-4b-q4_k_m `
  --jinja --reasoning off

# Terminal 2: API
conda activate base
$env:FINCTRL_MODEL_URL='http://127.0.0.1:8001/v1'
$env:FINCTRL_MODEL='qwen3.5-4b-q4_k_m'
python -m uvicorn dashboard.api:app --host 127.0.0.1 --port 8000

# Terminal 3: frontend
cd web
corepack pnpm run dev
```

## Optional Razorpay Test Mode feed

No credentials are required for the committed synthetic dataset. To demonstrate
schema compatibility with Razorpay's hosted Test Mode API:

1. Copy `.env.example` to a **file** named `.env` in the repository root.
2. Insert only Test Mode credentials beginning with `rzp_test_`.
3. Restart the API and use **Sync API feed** in the dashboard.

```powershell
Copy-Item .env.example .env
```

Never commit `.env`. Live credentials are rejected, and the connector exposes
only allowlisted read-only endpoints. The simulated bank statement and ERP
cashbook remain locally generated because Razorpay does not provide those
independent merchant records.

## Verification commands

```powershell
# Python safety and invariant tests
python -m unittest discover -v

# Current batch
python run.py

# Full offline evaluation
python -m eval.suite

# Frontend checks
cd web
corepack pnpm run lint
corepack pnpm run build
```

Expected frozen high-level outputs:

- 28 Python tests pass
- 87 bank entries checked
- 47 balanced journal proposals, none automatically posted
- LedgerGraph 11/11 adversarial cases exact with zero false selections
- known-miss GraphShield replay: 100% recall, explicitly regression-only
- fresh post-freeze holdout: 0/35 recall, explicitly disclosed

## Common problems

### `pnpm` is not recognized

Use Corepack:

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm run dev
```

If `corepack` is also unavailable, install Node.js 22+, reopen PowerShell, and
rerun the setup script.

### PowerShell blocks the launcher

Use the provided command wrapper:

```powershell
.\start-dashboard.cmd
```

### Qwen does not use the GPU

1. Update the NVIDIA driver.
2. Confirm `nvidia-smi` works.
3. Check that the model server starts with `--device CUDA0 --gpu-layers all`.
4. Close other GPU-heavy applications if 4 GB VRAM is exhausted.

The dashboard API health response reports the configured device. The
deterministic controller remains usable even if the Qwen service is disabled.

### Port already in use

The demo expects ports 3000, 8000, and 8001. Stop the previous demo instance or
the process using the conflicting port before starting a new launcher.

### Model checksum mismatch

Delete only the failed `.part` download inside `runtime/.downloads` and rerun:

```powershell
python scripts\download_local_model.py
```

The downloader refuses to accept a model or runtime archive whose SHA-256 does
not match the pinned manifest.
