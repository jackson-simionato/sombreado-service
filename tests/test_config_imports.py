"""Import-order smoke for sombreado.config (regression for circular imports)."""

from __future__ import annotations

import subprocess
import sys


def test_get_settings_importable_before_store() -> None:
    """Fresh process: importing get_settings must not require store to load first."""
    result = subprocess.run(
        [sys.executable, "-c", "from sombreado.config import get_settings; get_settings()"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
