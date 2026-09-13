"""Unit 13 (MEADOWOPS-DOM-006): APScheduler wiring. _run_tick's own logic
(call order, commit-vs-rollback, failure containment) is what's under
test here — advance_simulation/run_scheduled_tick are mocked throughout,
never exercised against the real shared dev database, so nothing here can
leave its clock or data mutated (the same discipline every other DB test
in this suite follows, just via mocking instead of rollback since
_run_tick's own contract is to commit).
"""

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine

from app.domain.scheduler import JOB_ID, _run_tick, build_scheduler
from app.services.simulation_clock_ops import SimulationPausedError


class TestBuildScheduler:
    def test_registers_a_job_with_the_configured_interval(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        scheduler = build_scheduler(engine, interval_seconds=45)
        job = scheduler.get_job(JOB_ID)
        assert job is not None
        assert job.trigger.interval.total_seconds() == 45
        engine.dispose()

    def test_max_instances_is_one_to_prevent_overlapping_ticks(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        scheduler = build_scheduler(engine, interval_seconds=60)
        job = scheduler.get_job(JOB_ID)
        assert job.max_instances == 1
        engine.dispose()


class TestRunTick:
    def test_paused_clock_rolls_back_and_never_calls_run_scheduled_tick(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        with (
            patch("app.domain.scheduler.advance_simulation", side_effect=SimulationPausedError()),
            patch("app.domain.scheduler.run_scheduled_tick") as mock_tick,
        ):
            _run_tick(engine)
            mock_tick.assert_not_called()
        engine.dispose()

    def test_success_path_advances_then_ticks_then_evaluates_exceptions_then_snapshots_kpis_then_commits(
        self,
    ) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date) as mock_advance,
            patch("app.domain.scheduler.run_scheduled_tick") as mock_tick,
            patch("app.domain.scheduler.sync_reporting_layer") as mock_sync_reporting,
            patch("app.domain.scheduler.evaluate_exceptions") as mock_evaluate_exceptions,
            patch("app.domain.scheduler.compute_and_snapshot_kpis") as mock_snapshot_kpis,
            patch("app.domain.scheduler.flag_stale") as mock_flag_stale,
            patch("app.domain.scheduler.sweep_thread_deadlines") as mock_sweep_deadlines,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine)
            mock_advance.assert_called_once_with(mock_session)
            mock_tick.assert_called_once_with(mock_session, fake_date)
            # B9: evaluate_exceptions/compute_and_snapshot_kpis previously had
            # no caller anywhere in the running system (exception_flag and
            # kpi_snapshot/days_of_supply_snapshot stayed empty even with the
            # scheduler enabled) — Unit 16 wires both in here so the dashboard
            # has real rows to read and drill into.
            mock_sync_reporting.assert_called_once_with(mock_session, fake_date, lag_days=2)
            mock_evaluate_exceptions.assert_called_once_with(mock_session, fake_date)
            mock_snapshot_kpis.assert_called_once_with(mock_session, fake_date)
            # Unit 24: flag_stale runs too, just not under test here - its
            # own call-order/args assertions live in
            # test_success_path_also_flags_stale_decisions below.
            mock_flag_stale.assert_called_once()
            # Unit 30a: same reasoning - own assertions live in
            # test_success_path_also_sweeps_thread_deadlines below.
            mock_sweep_deadlines.assert_called_once()
            mock_session.commit.assert_called_once()
        engine.dispose()

    def test_a_failing_tick_is_logged_and_still_commits_rather_than_rolling_back(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch(
                "app.domain.scheduler.run_scheduled_tick", side_effect=RuntimeError("boom")
            ),
            patch("app.domain.scheduler.evaluate_exceptions") as mock_evaluate_exceptions,
            patch("app.domain.scheduler.compute_and_snapshot_kpis") as mock_snapshot_kpis,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine)  # must not raise — a bad tick shouldn't kill the scheduler thread
            mock_session.commit.assert_called_once()
            mock_session.rollback.assert_not_called()
            # run_scheduled_tick failed, so this tick's exception/KPI pass is
            # skipped entirely (they'd be evaluating a flow that half-ran) —
            # the next successful tick re-evaluates exceptions fresh from
            # scratch and simply produces one fewer day of KPI history, both
            # already-accepted properties of these two functions.
            mock_evaluate_exceptions.assert_not_called()
            mock_snapshot_kpis.assert_not_called()
        engine.dispose()

    def test_a_failing_exception_or_kpi_pass_is_logged_and_still_commits(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch("app.domain.scheduler.run_scheduled_tick"),
            patch(
                "app.domain.scheduler.evaluate_exceptions", side_effect=RuntimeError("boom")
            ),
            patch("app.domain.scheduler.compute_and_snapshot_kpis") as mock_snapshot_kpis,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine)  # must not raise
            mock_session.commit.assert_called_once()
            mock_session.rollback.assert_not_called()
            # evaluate_exceptions blew up before compute_and_snapshot_kpis ran
            # — same short-circuit-on-failure contract as run_scheduled_tick.
            mock_snapshot_kpis.assert_not_called()
        engine.dispose()

    def test_success_path_syncs_the_reporting_layer_before_evaluating_exceptions(
        self,
    ) -> None:
        # Unit 17 (MEADOWOPS-DOM-009): sync_reporting_layer must run before
        # evaluate_exceptions, not after — so a lag-staleness/conflict
        # condition it produces is visible to the same tick's exception
        # evaluation rather than one tick late.
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        call_order: list[str] = []
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch("app.domain.scheduler.run_scheduled_tick"),
            patch(
                "app.domain.scheduler.sync_reporting_layer",
                side_effect=lambda *a, **kw: call_order.append("sync_reporting_layer"),
            ) as mock_sync,
            patch(
                "app.domain.scheduler.evaluate_exceptions",
                side_effect=lambda *a, **kw: call_order.append("evaluate_exceptions"),
            ),
            patch("app.domain.scheduler.compute_and_snapshot_kpis"),
            patch("app.domain.scheduler.flag_stale"),
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine, reporting_lag_days=3)
            mock_sync.assert_called_once_with(mock_session, fake_date, lag_days=3)
            assert call_order == ["sync_reporting_layer", "evaluate_exceptions"]
        engine.dispose()

    def test_a_failing_reporting_sync_is_logged_and_still_commits(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch("app.domain.scheduler.run_scheduled_tick"),
            patch(
                "app.domain.scheduler.sync_reporting_layer", side_effect=RuntimeError("boom")
            ),
            patch("app.domain.scheduler.evaluate_exceptions") as mock_evaluate_exceptions,
            patch("app.domain.scheduler.compute_and_snapshot_kpis") as mock_snapshot_kpis,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine)  # must not raise
            mock_session.commit.assert_called_once()
            mock_session.rollback.assert_not_called()
            mock_evaluate_exceptions.assert_not_called()
            mock_snapshot_kpis.assert_not_called()
        engine.dispose()

    def test_success_path_also_flags_stale_decisions(self) -> None:
        # Unit 24 (MEADOWOPS-DOM-018, PRD 4.4): "flagged after a configurable
        # period rather than sitting in limbo indefinitely" - wall-clock
        # datetime.now(), not the simulation date, since DecisionEvent
        # timestamps are already wall-clock (app.services.scenario_service.
        # approve_scenario's own approved_at convention).
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        fixed_now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch("app.domain.scheduler.run_scheduled_tick"),
            patch("app.domain.scheduler.sync_reporting_layer"),
            patch("app.domain.scheduler.evaluate_exceptions"),
            patch("app.domain.scheduler.compute_and_snapshot_kpis"),
            patch("app.domain.scheduler.flag_stale") as mock_flag_stale,
            patch("app.domain.scheduler.datetime") as mock_datetime,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_datetime.now.return_value = fixed_now
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine, stale_decision_after_days=30)
            mock_flag_stale.assert_called_once_with(mock_session, as_of=fixed_now, after_days=30)
        engine.dispose()

    def test_a_failing_tick_skips_stale_flagging_too(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch(
                "app.domain.scheduler.run_scheduled_tick", side_effect=RuntimeError("boom")
            ),
            patch("app.domain.scheduler.flag_stale") as mock_flag_stale,
            patch("app.domain.scheduler.sweep_thread_deadlines") as mock_sweep_deadlines,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine)  # must not raise
            mock_session.commit.assert_called_once()
            mock_flag_stale.assert_not_called()
            mock_sweep_deadlines.assert_not_called()
        engine.dispose()

    def test_success_path_also_sweeps_thread_deadlines(self) -> None:
        # Unit 30a (MEADOWOPS-UI-003, PRD 6.1, B12): wall-clock now(), same
        # reasoning as flag_stale's own as_of — deadlines are real-world
        # days (PRD 6.1's "Response windows... real-world days per round"),
        # not simulation days.
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        fixed_now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch("app.domain.scheduler.run_scheduled_tick"),
            patch("app.domain.scheduler.sync_reporting_layer"),
            patch("app.domain.scheduler.evaluate_exceptions"),
            patch("app.domain.scheduler.compute_and_snapshot_kpis"),
            patch("app.domain.scheduler.flag_stale"),
            patch("app.domain.scheduler.sweep_thread_deadlines") as mock_sweep_deadlines,
            patch("app.domain.scheduler.datetime") as mock_datetime,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_datetime.now.return_value = fixed_now
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine, chat_deadline_approaching_within_hours=12)
            mock_sweep_deadlines.assert_called_once_with(
                mock_session, now=fixed_now, approaching_within=timedelta(hours=12)
            )
        engine.dispose()

    def test_a_failing_exception_or_kpi_pass_also_skips_deadline_sweep(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch("app.domain.scheduler.run_scheduled_tick"),
            patch("app.domain.scheduler.sync_reporting_layer"),
            patch(
                "app.domain.scheduler.evaluate_exceptions", side_effect=RuntimeError("boom")
            ),
            patch("app.domain.scheduler.compute_and_snapshot_kpis"),
            patch("app.domain.scheduler.flag_stale"),
            patch("app.domain.scheduler.sweep_thread_deadlines") as mock_sweep_deadlines,
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine)  # must not raise
            mock_sweep_deadlines.assert_not_called()
        engine.dispose()

    def test_build_scheduler_passes_stale_decision_after_days_through(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        scheduler = build_scheduler(engine, interval_seconds=60, stale_decision_after_days=45)
        job = scheduler.get_job(JOB_ID)
        assert job.args[2] == 45
        engine.dispose()

    def test_build_scheduler_passes_chat_deadline_approaching_within_hours_through(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        scheduler = build_scheduler(
            engine, interval_seconds=60, chat_deadline_approaching_within_hours=6
        )
        job = scheduler.get_job(JOB_ID)
        assert job.args[-1] == 6
        engine.dispose()

    def test_a_db_level_failure_rolls_back_before_the_fallback_commit(self) -> None:
        # A genuine DB-level error (IntegrityError, invalidated connection,
        # etc.) — as opposed to a pure-Python exception — leaves the
        # session's transaction in a "partial rollback" state
        # (session.is_active becomes False, matching SQLAlchemy's own
        # is_active contract). Committing directly on top of that would
        # raise PendingRollbackError and mask the original failure — the
        # same trap app.services.scheduled_flow.run_scheduled_tick's own
        # recovery write already guards against with an explicit
        # rollback() first.
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        fake_date = date(2026, 3, 5)
        with (
            patch("app.domain.scheduler.advance_simulation", return_value=fake_date),
            patch("app.domain.scheduler.run_scheduled_tick"),
            patch(
                "app.domain.scheduler.sync_reporting_layer", side_effect=RuntimeError("db boom")
            ),
            patch("app.domain.scheduler.evaluate_exceptions"),
            patch("app.domain.scheduler.compute_and_snapshot_kpis"),
            patch("app.domain.scheduler.Session") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.is_active = False  # simulates the aborted-transaction state
            mock_session_cls.return_value.__enter__.return_value = mock_session
            _run_tick(engine)  # must not raise
            mock_session.rollback.assert_called_once()
            mock_session.commit.assert_called_once()
        engine.dispose()


class TestBuildSchedulerReportingLagDays:
    def test_passes_reporting_lag_days_through_to_the_job_args(self) -> None:
        engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
        scheduler = build_scheduler(engine, interval_seconds=60, reporting_lag_days=4)
        job = scheduler.get_job(JOB_ID)
        assert job.args == (engine, 4, 30, 24)
        engine.dispose()
