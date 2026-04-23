from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config.paths import LOG_FILE, LOG_DIR


def setup_logging() -> logging.Logger:
    logger = logging.getLogger('tg_cli')
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s')

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
