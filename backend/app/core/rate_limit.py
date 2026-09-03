"""Per-email login rate limiting (Unit 17a, MEADOWOPS-DOM-010). Security
design review of this unit: switching from a high-entropy shared bearer
token to human-chosen passwords against two predictable email addresses
makes online credential-guessing a real threat that didn't exist before.
Keyed per-email, not per-IP — every browser attempt reaches FastAPI via the
same Next.js server-side proxy, so a per-IP bucket would collapse into one
shared limit across both real users.

A single in-process instance (app.state, created in create_app) is
sufficient at this project's documented single-worker scale — the same
already-accepted tradeoff as build_scheduler's own max_instances=1 comment
and _lock_sync_state's non-race-proof singleton row. Single-worker does not
mean single-threaded, though: `login` is a sync `def` route, so Starlette
dispatches concurrent requests to it from FastAPI's anyio threadpool — a
`threading.Lock` around the read-modify-write below prevents a burst of
parallel requests for the same email from each reading the same
pre-append list and all passing the limit check.

`check_and_record` runs before the DB lookup in app.api.auth (an unknown
email must still cost one rate-limit check, not skip it), so `email` here
is fully attacker-controlled input, not a validated account — an attacker
sending one request per distinct fabricated address would otherwise grow
`_attempts` without bound, since a key is only ever removed by `reset()`
on that exact email's own successful login. `_sweep_stale` amortizes a
periodic full-dict prune (probabilistic, not on every call, so a single
`check_and_record` stays O(1) rather than paying an O(n) sweep on every
request) to bound memory to recently-active keys.
"""

import random
import threading
import time
from collections.abc import Callable

_SWEEP_PROBABILITY = 0.01


class LoginRateLimiter:
    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(self, email: str) -> bool:
        key = email.strip().lower()
        now = self._clock()
        cutoff = now - self._window_seconds
        with self._lock:
            recent = [t for t in self._attempts.get(key, []) if t > cutoff]
            if len(recent) >= self._max_attempts:
                self._attempts[key] = recent
                self._sweep_stale(cutoff)
                return False
            recent.append(now)
            self._attempts[key] = recent
            self._sweep_stale(cutoff)
            return True

    def reset(self, email: str) -> None:
        with self._lock:
            self._attempts.pop(email.strip().lower(), None)

    def _sweep_stale(self, cutoff: float) -> None:
        """Caller already holds `self._lock`. Probabilistic so this stays a
        rare O(n) sweep rather than running on every call."""
        if random.random() >= _SWEEP_PROBABILITY:
            return
        stale_keys = [
            key
            for key, timestamps in self._attempts.items()
            if not any(t > cutoff for t in timestamps)
        ]
        for key in stale_keys:
            del self._attempts[key]
