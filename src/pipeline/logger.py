import logging
import logging.handlers


def get_logger(name):
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times if get_logger is called more than once
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Log to console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Log to file with rotation (max 5MB per file, keep last 3 files)
    file_handler = logging.handlers.RotatingFileHandler(
        "pipeline.log", maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger