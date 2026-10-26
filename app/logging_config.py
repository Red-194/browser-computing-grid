import logging
import os


DEFAULT_LOG_LEVEL = logging.DEBUG
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: int = DEFAULT_LOG_LEVEL) -> None:
    """Configure application logging once for the grid components.

    GRID_LOG_LEVEL (DEBUG, INFO, WARNING, ...) overrides the default.
    """
    level = getattr(logging, os.environ.get("GRID_LOG_LEVEL", "").upper(), level)
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger("grid").setLevel(level)
