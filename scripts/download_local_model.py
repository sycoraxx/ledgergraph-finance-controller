"""Download the pinned local Qwen GGUF and CUDA llama.cpp runtime.

Artifacts are kept inside the project so the demo remains portable and does not
depend on Ollama's global model store. Every large artifact is checksum-verified
before it is accepted.
"""

from __future__ import annotations

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import hf_hub_download


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "qwen3.5-4b"
MODEL_NAME = "Qwen3.5-4B-Q4_K_M.gguf"
MODEL_SHA256 = "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"
RUNTIME_DIR = ROOT / "runtime" / "llama.cpp"
DOWNLOAD_DIR = ROOT / "runtime" / ".downloads"

LLAMA_RELEASE = "b10582"
RUNTIME_ARCHIVES = {
    "llama-b10582-bin-win-cuda-12.4-x64.zip": (
        "https://github.com/ggml-org/llama.cpp/releases/download/b10582/"
        "llama-b10582-bin-win-cuda-12.4-x64.zip",
        "44f119af159540bd41131498a7c13adb31f846154c171bcca601842289f569b1",
    ),
    "cudart-llama-bin-win-cuda-12.4-x64.zip": (
        "https://github.com/ggml-org/llama.cpp/releases/download/b10582/"
        "cudart-llama-bin-win-cuda-12.4-x64.zip",
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, expected: str) -> None:
    actual = sha256(path)
    if actual != expected:
        path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )
    print(f"Verified {path.name} ({path.stat().st_size / 1024**3:.2f} GiB)")


def download_file(url: str, destination: Path) -> None:
    if destination.exists():
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "finance-controller-local-model/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    print(f"Downloading {destination.name} (resuming at {offset / 1024**2:.0f} MiB)...")
    with urllib.request.urlopen(request, timeout=60) as response:
        append = offset > 0 and response.status == 206
        mode = "ab" if append else "wb"
        if not append:
            offset = 0
        total = response.headers.get("Content-Length")
        total_bytes = offset + int(total) if total else None
        downloaded = offset
        next_report = downloaded + 128 * 1024 * 1024
        with partial.open(mode) as handle:
            while chunk := response.read(4 * 1024 * 1024):
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_report:
                    suffix = f" / {total_bytes / 1024**2:.0f} MiB" if total_bytes else " MiB"
                    print(f"  {downloaded / 1024**2:.0f}{suffix}")
                    next_report += 128 * 1024 * 1024
    partial.replace(destination)


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading Qwen 3.5 4B Q4_K_M from Hugging Face...")
    model_path = Path(hf_hub_download(
        repo_id="unsloth/Qwen3.5-4B-GGUF",
        filename=MODEL_NAME,
        local_dir=MODEL_DIR,
    ))
    verify(model_path, MODEL_SHA256)

    manifest = RUNTIME_DIR / "INSTALLATION.txt"
    existing_server = RUNTIME_DIR / "llama-server.exe"
    runtime_current = (
        existing_server.exists()
        and manifest.exists()
        and f"llama.cpp release: {LLAMA_RELEASE}" in manifest.read_text(encoding="utf-8")
    )
    if runtime_current:
        print(f"Reusing verified llama.cpp {LLAMA_RELEASE} runtime.")
    else:
        for name, (url, expected_hash) in RUNTIME_ARCHIVES.items():
            archive = DOWNLOAD_DIR / name
            download_file(url, archive)
            verify(archive, expected_hash)
            print(f"Extracting {name}...")
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(RUNTIME_DIR)

    server = next(RUNTIME_DIR.rglob("llama-server.exe"), None)
    if server is None:
        raise RuntimeError("llama-server.exe was not found after extraction")
    if server.parent != RUNTIME_DIR:
        for item in server.parent.iterdir():
            target = RUNTIME_DIR / item.name
            if item.is_file() and not target.exists():
                shutil.copy2(item, target)

    manifest.write_text(
        f"llama.cpp release: {LLAMA_RELEASE}\n"
        f"model: unsloth/Qwen3.5-4B-GGUF/{MODEL_NAME}\n"
        f"model sha256: {MODEL_SHA256}\n",
        encoding="utf-8",
    )
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    print("\nLocal model runtime is ready.")
    print(f"Model:  {model_path}")
    print(f"Server: {RUNTIME_DIR / 'llama-server.exe'}")


if __name__ == "__main__":
    main()
