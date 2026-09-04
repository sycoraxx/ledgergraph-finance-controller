"""Export a secret-free, read-only dashboard snapshot for static hosting."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.api import dashboard_overview  # noqa: E402


def main() -> None:
    overview = dashboard_overview()
    overview["razorpay_feed"] = {
        "configured": False,
        "mode": "test",
        "read_only": True,
        "live_keys_blocked": True,
        "controller_ready": False,
        "data_classification": "synthetic",
        "real_money": False,
        "missing_independent_sources": ["simulated bank", "simulated cashbook"],
        "last_sync": None,
    }
    overview["runtime"] = {
        **overview["runtime"],
        "language_model": "Deterministic evidence renderer",
        "model_provider": "none",
        "model_available": False,
        "model_status": "disabled",
        "mode": "read-only sample",
    }
    target = ROOT / "web" / "public" / "demo-overview.json"
    target.write_text(
        json.dumps(overview, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Wrote {target.relative_to(ROOT)} ({target.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
