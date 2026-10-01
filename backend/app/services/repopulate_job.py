"""Unit 40 (MEADOWOPS-DOM-028): single-flight background runner for the
"Reset & regenerate to today" rebuild.

A rebuild runs one simulated day at a time against the database and can take
minutes, far past what an HTTP request (or the Builder app's serverless proxy)
should wait for. So the route starts the work on a worker thread and returns
at once; the Builder polls `status()`.

State is in-process by design: the app runs as one instance (see
app.domain.scheduler's own note on multiple workers). If the process
restarts mid-run the rebuild's single transaction is rolled back by the
database, so the world is left as it was and the status simply reads idle.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]
RepopulateWork = Callable[[ProgressCallback], str]

# What a client is told when a run fails: the real exception goes to the
# server log only, since it can carry connection details or table names.
FAILURE_MESSAGE = "The rebuild failed and nothing was changed. Check the server logs for details."


class RepopulateState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class RepopulateStatus:
    state: RepopulateState = RepopulateState.IDLE
    started_at: datetime | None = None
    finished_at: datetime | None = None
    days_done: int = 0
    days_total: int = 0
    message: str | None = None


class RepopulateJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = RepopulateStatus()
        self._thread: threading.Thread | None = None

    def status(self) -> RepopulateStatus:
        with self._lock:
            return self._status

    def start(self, work: RepopulateWork) -> bool:
        """False (and nothing started) when a run is already in progress."""
        with self._lock:
            if self._status.state == RepopulateState.RUNNING:
                return False
            self._status = RepopulateStatus(
                state=RepopulateState.RUNNING, started_at=datetime.now(timezone.utc)
            )
            self._thread = threading.Thread(
                target=self._run, args=(work,), name="repopulate-world", daemon=True
            )
            self._thread.start()
            return True

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _update(self, **changes) -> None:
        with self._lock:
            self._status = replace(self._status, **changes)

    def _progress(self, done: int, total: int) -> None:
        self._update(days_done=done, days_total=total)

    def _run(self, work: RepopulateWork) -> None:
        try:
            message = work(self._progress)
        except Exception:  # noqa: BLE001 - reported via status, detail only in the log
            logger.exception("Repopulate run failed")
            self._update(
                state=RepopulateState.FAILED,
                finished_at=datetime.now(timezone.utc),
                message=FAILURE_MESSAGE,
            )
            return
        self._update(
            state=RepopulateState.SUCCEEDED,
            finished_at=datetime.now(timezone.utc),
            message=message,
        )
