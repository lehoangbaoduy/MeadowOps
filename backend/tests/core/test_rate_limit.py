"""Unit 17a (MEADOWOPS-DOM-010): per-email login rate limiting. Security
design review of this unit: switching from a high-entropy shared bearer
token to human-chosen passwords against two predictable email addresses
makes online credential-guessing a real threat that didn't exist before.
Keyed per-email, not per-IP — every browser request arrives at FastAPI via
the same Next.js server-side proxy, so a per-IP bucket would collapse into
one shared limit across both real users.
"""

import pytest

from app.core import rate_limit as rate_limit_module
from app.core.rate_limit import LoginRateLimiter


def test_allows_attempts_under_the_limit() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=900)
    assert limiter.check_and_record("admin@meadowops.local") is True
    assert limiter.check_and_record("admin@meadowops.local") is True
    assert limiter.check_and_record("admin@meadowops.local") is True


def test_blocks_once_the_limit_is_reached() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=900)
    for _ in range(3):
        limiter.check_and_record("admin@meadowops.local")
    assert limiter.check_and_record("admin@meadowops.local") is False


def test_tracks_each_email_independently() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=900)
    assert limiter.check_and_record("admin@meadowops.local") is True
    assert limiter.check_and_record("analyst@meadowops.local") is True
    assert limiter.check_and_record("admin@meadowops.local") is False


def test_email_matching_is_case_insensitive() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=900)
    assert limiter.check_and_record("Admin@Meadowops.local") is True
    assert limiter.check_and_record("admin@meadowops.local") is False


def test_a_successful_login_can_reset_the_counter() -> None:
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=900)
    assert limiter.check_and_record("admin@meadowops.local") is True
    limiter.reset("admin@meadowops.local")
    assert limiter.check_and_record("admin@meadowops.local") is True


def test_window_expiry_allows_attempts_again() -> None:
    current_time = [1000.0]
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=900, clock=lambda: current_time[0])
    assert limiter.check_and_record("admin@meadowops.local") is True
    assert limiter.check_and_record("admin@meadowops.local") is False
    current_time[0] += 901.0
    assert limiter.check_and_record("admin@meadowops.local") is True


def test_concurrent_attempts_for_the_same_email_never_exceed_the_limit() -> None:
    # Security design review of this unit: check_and_record's
    # read-modify-write must be atomic — a burst of parallel requests for
    # the same email (login is a sync `def` route, dispatched from
    # FastAPI's anyio threadpool) must not each read the same pre-append
    # state and all pass the limit check.
    import threading

    limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)
    results: list[bool] = []
    results_lock = threading.Lock()

    def attempt() -> None:
        outcome = limiter.check_and_record("admin@meadowops.local")
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 5


def test_sweep_eventually_evicts_keys_with_no_recent_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A distinct dict entry is created per attacker-controlled email string
    # (check_and_record runs before any DB lookup validates the address) —
    # entries for emails that stop attempting must not survive forever.
    # Sweep probability forced to 1.0 so eviction is deterministic rather
    # than merely overwhelmingly likely (avoid flaky timeout/probability-
    # based assertions).
    monkeypatch.setattr(rate_limit_module, "_SWEEP_PROBABILITY", 1.0)
    current_time = [0.0]
    limiter = LoginRateLimiter(
        max_attempts=100, window_seconds=10, clock=lambda: current_time[0]
    )
    for i in range(500):
        limiter.check_and_record(f"attacker-{i}@example.com")

    current_time[0] += 20.0  # every prior attempt is now outside the window
    limiter.check_and_record("trigger@example.com")

    assert len(limiter._attempts) == 1
