import logging
import sys
from src.config.settings import settings

def setup_logger(name: str) -> logging.Logger:
    """
    Configures and returns a standard logger for the application.
    Output is directed to STDOUT for Railway's log aggregation.
    """
    logger = logging.getLogger(name)
    
    # Only configure if no handlers exist to prevent duplication
    if not logger.handlers:
        level = getattr(logging, settings.log_level.upper(), logging.INFO)
        logger.setLevel(level)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        
    return logger

logger = setup_logger("UnifiedMCP")
