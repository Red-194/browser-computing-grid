import logging


DEFAULT_LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: int = DEFAULT_LOG_LEVEL) -> None:
    """Configure application logging once for the grid components."""
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger("grid").setLevel(level)
