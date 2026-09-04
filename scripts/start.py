"""Start the Finance Controller API and web app on any supported platform."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def package_command() -> list[str]:
    pnpm = shutil.which("pnpm")
    if pnpm:
        return [pnpm]
    corepack = shutil.which("corepack")
    if corepack:
        return [corepack, "pnpm"]
    raise RuntimeError("pnpm/Corepack was not found. Run python scripts/setup.py first.")


def process_group_options() -> dict[str, object]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=3000)
    args = parser.parse_args()

    load_env()
    if not (WEB / "node_modules").exists():
        raise RuntimeError("Frontend dependencies are missing. Run python scripts/setup.py.")

    env = os.environ.copy()
    env.setdefault("NEXT_PUBLIC_API_URL", f"http://127.0.0.1:{args.api_port}")
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "dashboard.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.api_port),
        ],
        cwd=ROOT,
        env=env,
        **process_group_options(),
    )
    web = subprocess.Popen(
        [
            *package_command(),
            "exec",
            "vinext",
            "dev",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.web_port),
        ],
        cwd=WEB,
        env=env,
        **process_group_options(),
    )
    processes = [api, web]

    def handle_signal(_signum: int, _frame: object) -> None:
        for process in reversed(processes):
            stop(process)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    print("\nFinance Controller is starting:")
    print(f"  Dashboard  http://localhost:{args.web_port}")
    print(f"  API        http://127.0.0.1:{args.api_port}/api/health")
    print("  Stop       Ctrl+C\n")
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        failed = next((process.returncode for process in processes if process.returncode), 0)
        if failed:
            raise SystemExit(failed)
    finally:
        for process in reversed(processes):
            stop(process)


if __name__ == "__main__":
    main()
