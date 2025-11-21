import time
import logging
from functools import wraps

logger = logging.getLogger("orders")


def log_execution_time(action):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"{action} completed",
                    extra={
                        "action": action,
                        "duration_ms": round(duration_ms, 2),
                        "status": "success",
                    },
                )
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000

                logger.error(
                    f"{action} failed",
                    extra={
                        "action": action,
                        "duration_ms": round(duration_ms, 2),
                        "status": "error",
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                raise

        return wrapper

    return decorator
