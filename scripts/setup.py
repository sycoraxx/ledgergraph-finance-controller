"""Cross-platform project setup for Windows, macOS, and Linux."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def package_command() -> list[str]:
    pnpm = shutil.which("pnpm")
    if pnpm:
        return [pnpm]
    corepack = shutil.which("corepack")
    if corepack:
        return [corepack, "pnpm"]
    raise RuntimeError(
        "pnpm/Corepack was not found. Install Node.js 22.13 or newer and retry."
    )


def check_node() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js was not found. Install Node.js 22.13 or newer.")
    output = subprocess.check_output([node, "--version"], text=True).strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", output)
    if not match or tuple(map(int, match.groups())) < (22, 13, 0):
        raise RuntimeError(f"Node.js 22.13 or newer is required; found {output}.")


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-local-model",
        action="store_true",
        help="download the pinned Windows CUDA Qwen bundle",
    )
    parser.add_argument(
        "--check", action="store_true", help="run backend tests and frontend checks"
    )
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        raise RuntimeError(
            f"Python 3.10 or newer is required; found {sys.version.split()[0]}."
        )
    check_node()
    pnpm = package_command()

    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    run([*pnpm, "install", "--frozen-lockfile"], cwd=WEB)

    if args.with_local_model:
        if sys.platform != "win32":
            raise RuntimeError(
                "The pinned local-model bundle currently targets Windows CUDA. "
                "Use a hosted provider or install llama.cpp for your platform."
            )
        run([sys.executable, "scripts/download_local_model.py"])

    if args.check:
        run([sys.executable, "-m", "unittest", "discover", "-v"])
        run([*pnpm, "run", "lint"], cwd=WEB)
        run([*pnpm, "run", "build"], cwd=WEB)

    print("\nSetup complete. Start the product with: python scripts/start.py")


if __name__ == "__main__":
    main()
