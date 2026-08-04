import logging


def configure_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
