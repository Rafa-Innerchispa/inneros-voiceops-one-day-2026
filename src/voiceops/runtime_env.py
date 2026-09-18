from __future__ import annotations

import os
from pathlib import Path


def load_runtime_env() -> None:
    """Load KEY=VALUE pairs from local runtime env files without overwriting existing env."""
    candidates = [
        Path(__file__).resolve().parents[2] / ".env",
        Path.home() / ".config" / "inneros" / "voiceops.env",
        Path.home() / ".inneros" / "voiceops.env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
