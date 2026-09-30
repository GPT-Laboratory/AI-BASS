import logging
import sys
import os
from datetime import datetime

def setup_logging():
    """
    Setup logging configuration for Docker environment.
    Logs to stdout for Docker container output.
    """
    # Get log level from environment variable
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Create formatter for Docker-friendly output
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Create console handler that outputs to stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level, logging.INFO))
    console_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    root_logger.addHandler(console_handler)

    # Silence noisy third-party loggers
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    return root_logger

# Initialize logging when module is imported
logger = setup_logging()
