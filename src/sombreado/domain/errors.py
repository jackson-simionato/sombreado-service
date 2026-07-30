"""Application errors shared across entry points (not HTTP-specific)."""


class ServiceError(Exception):
    """Domain/application failure with a stable public error code."""

    def __init__(self, *, code: str, message: str | None = None):
        self.code = code
        self.message = message
