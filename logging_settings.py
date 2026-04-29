import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_logging(app_name="app"):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    summary = TimedRotatingFileHandler(
        LOG_DIR / f"{app_name}_summary.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    summary.setLevel(logging.INFO)
    summary.setFormatter(fmt)

    debug = TimedRotatingFileHandler(
        LOG_DIR / f"{app_name}_debug.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
        utc=False,
    )
    debug.setLevel(logging.DEBUG)
    debug.setFormatter(fmt)

    errors = TimedRotatingFileHandler(
        LOG_DIR / f"{app_name}_errors.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    errors.setLevel(logging.ERROR)
    errors.setFormatter(fmt)

    logger.handlers.clear()
    logger.addHandler(summary)
    logger.addHandler(debug)
    logger.addHandler(errors)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("ultralytics").setLevel(logging.INFO)