"""Application errors shared across entry points."""


class PublicApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
