# STABILIZATION: 2026-05-04 — Enhanced retry with timeout-specific exceptions + jitter
import time
import random
import logging

logger = logging.getLogger(__name__)


def retry_with_backoff(max_retries=3, base_delay=1, max_delay=30, exceptions=(Exception,)):
    """
    Retry decorator with jittered exponential backoff.
    Added 2026-05-04 to handle timeout and connection failures gracefully.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        raise
                    # Jittered exponential backoff — 2026-05-04
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} for {func.__name__} after {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
        return wrapper
    return decorator


# Pre-configured for network ops — 2026-05-04
network_retry = retry_with_backoff(
    max_retries=3,
    base_delay=1,
    max_delay=15,
    exceptions=(Exception,)
)


# Backward-compatible alias — 2026-05-04
def retry(max_attempts=3, delay=2):
    """Simple fixed-delay retry for backward compatibility."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
        return wrapper
    return decorator
