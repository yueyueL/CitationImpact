"""Rate limiting utilities for API clients"""

import time
from typing import Dict


class RateLimiter:
    """Simple rate limiter for API requests"""

    def __init__(self, min_intervals: Dict[str, float]):
        """
        Initialize rate limiter

        Args:
            min_intervals: Dict mapping API names to minimum seconds between requests
                          e.g., {'semantic_scholar': 0.1, 'openalex': 0.05}
        """
        self.min_intervals = min_intervals
        self.last_request_time: Dict[str, float] = {}

    def wait(self, api: str):
        """
        Wait if necessary to respect rate limits

        Args:
            api: API name (must be in min_intervals dict)
        """
        # Initialize if first request
        if api not in self.last_request_time:
            self.last_request_time[api] = 0

        # Calculate time since last request
        elapsed = time.time() - self.last_request_time[api]
        min_interval = self.min_intervals.get(api, 0.1)

        # Wait if we're going too fast
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        # Update last request time
        self.last_request_time[api] = time.time()
