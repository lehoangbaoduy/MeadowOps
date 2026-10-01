"""Unit 40: the single-flight background runner behind "Reset & regenerate to
today". A rebuild takes far longer than an HTTP request should, so it runs on
a worker thread and the Builder polls its status."""

import threading

from app.services.repopulate_job import RepopulateJob, RepopulateState


def test_starts_idle() -> None:
    status = RepopulateJob().status()

    assert status.state == RepopulateState.IDLE
    assert status.started_at is None


def test_a_successful_run_reports_succeeded_with_its_message() -> None:
    job = RepopulateJob()

    started = job.start(lambda progress: "Rebuilt 3 days")
    job.join(timeout=5)

    status = job.status()
    assert started is True
    assert status.state == RepopulateState.SUCCEEDED
    assert status.message == "Rebuilt 3 days"
    assert status.started_at is not None and status.finished_at is not None


def test_progress_updates_are_visible_while_running() -> None:
    job = RepopulateJob()
    reported = threading.Event()
    release = threading.Event()

    def work(progress) -> str:
        progress(2, 5)
        reported.set()
        release.wait(timeout=5)
        return "done"

    job.start(work)
    assert reported.wait(timeout=5)
    status = job.status()
    release.set()
    job.join(timeout=5)

    assert status.state == RepopulateState.RUNNING
    assert (status.days_done, status.days_total) == (2, 5)


def test_a_second_start_while_running_is_refused() -> None:
    job = RepopulateJob()
    release = threading.Event()
    job.start(lambda progress: release.wait(timeout=5) and "done")

    second = job.start(lambda progress: "never runs")
    release.set()
    job.join(timeout=5)

    assert second is False
    assert job.status().message == "done"


def test_a_failure_is_reported_without_leaking_the_exception_text() -> None:
    job = RepopulateJob()

    def boom(progress) -> str:
        raise RuntimeError("password=hunter2 host=db.internal")

    job.start(boom)
    job.join(timeout=5)

    status = job.status()
    assert status.state == RepopulateState.FAILED
    assert "hunter2" not in (status.message or "")
    assert "server logs" in (status.message or "")


def test_it_can_run_again_after_finishing() -> None:
    job = RepopulateJob()
    job.start(lambda progress: "first")
    job.join(timeout=5)

    started = job.start(lambda progress: "second")
    job.join(timeout=5)

    assert started is True
    assert job.status().message == "second"
