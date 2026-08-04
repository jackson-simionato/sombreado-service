"""Operator alert seam for backup and integrity failures."""

from __future__ import annotations

from sombreado.logging import get_logger


class LoggingAlerter:
    """Emit backup/integrity alerts to the process logger (stderr/journald)."""

    def alert(self, message: str) -> None:
        get_logger("sombreado.backup").error("ALERT %s", message)
