import logging
import sys
from config import LOG_FILE, LOG_LEVEL
def setup_logging() -> logging.Logger:
    logger = logging.getLogger("discordboost")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    if logger.handlers:
        return logger
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger
