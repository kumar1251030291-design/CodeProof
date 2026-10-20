"""Small process-local sliding-window limiter for paid AI draft requests."""

from collections import OrderedDict, deque
from threading import Lock
import time
from uuid import UUID


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)


class ProcessLocalRateLimiter:
    """Limit one user to a bounded number of calls per worker process."""

    def __init__(self, *, limit: int = 5, window_seconds: int = 60, max_users: int = 10_000) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_users = max_users
        self._requests: OrderedDict[UUID, tuple[deque[float], float]] = OrderedDict()
        self._lock = Lock()

    def check(self, user_id: UUID) -> None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            while self._requests:
                oldest_user, (oldest_requests, last_seen) = next(iter(self._requests.items()))
                if last_seen > cutoff:
                    break
                self._requests.pop(oldest_user)

            entry = self._requests.get(user_id)
            if entry is None:
                if len(self._requests) >= self.max_users:
                    raise RateLimitExceeded(self.window_seconds)
                requests: deque[float] = deque()
            else:
                requests, _last_seen = entry
                while requests and requests[0] <= cutoff:
                    requests.popleft()

            if len(requests) >= self.limit:
                raise RateLimitExceeded(int(requests[0] + self.window_seconds - now + 0.999))
            requests.append(now)
            self._requests[user_id] = (requests, now)
            self._requests.move_to_end(user_id)

    def clear(self) -> None:
        """Clear state for deterministic tests and controlled process shutdown."""
        with self._lock:
            self._requests.clear()
