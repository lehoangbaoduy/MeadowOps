"""Unit 40 (MEADOWOPS-DOM-028): "Reset & regenerate to today" - wipe the
generated operational data and rebuild a fresh history that ends on today's
real date. Every test works inside one transaction that is rolled back at the
end, so the shared dev database is never left rebuilt."""

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.db.auth import User
from app.db.chat import ChatThread
from app.db.dimensions import Customer, Product, Supplier, Warehouse
from app.db.enums import (
    CompetencyCluster,
    DifficultyTier,
    ScenarioStatus,
    ScenarioType,
    StakeholderPersona,
)
from app.db.exception_flags import ExceptionFlag
from app.db.facts import InventoryTransaction, PurchaseOrder, SalesOrder
from app.db.kpi import KpiSnapshot
from app.db.scenario import Scenario
from app.db.scheduling import ScheduledTick
from app.db.world_state import SimulationClock, WorldState, WorldStateKind
from app.domain.simulation_clock import ClockStatus
from app.services.baseline_data import seed_master_data
from app.services.chat import get_or_create_thread
from app.services.exception_rule_defaults import seed_exception_rule_thresholds
from app.services.scenario_service import create_scenario_from_exception_flag
from app.services.simulation_clock_ops import seed_initial_world_state_and_clock
from app.services import world_repopulate
from app.services.world_repopulate import repopulate_world

_EMAIL = "zztest-repopulate-admin@meadowops.local"
_TODAY = date(2026, 9, 20)
_DAYS = 4


@pytest.fixture
def session():
    engine = create_engine(os.environ["MEADOWOPS_DATABASE_URL"])
    with Session(engine) as session:
        session.execute(delete(User).where(User.email == _EMAIL))
        session.commit()
        seed_master_data(session)
        seed_exception_rule_thresholds(session)
        seed_initial_world_state_and_clock(session)
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(User).where(User.email == _EMAIL))
        session.commit()
    engine.dispose()


@pytest.fixture
def admin_id(session: Session) -> uuid.UUID:
    user = User(email=_EMAIL, password_hash="x", role="admin", is_active=True)
    session.add(user)
    session.flush()
    return user.id


def _scenario(
    session: Session,
    admin_id: uuid.UUID,
    *,
    title: str,
    status: ScenarioStatus,
    warehouse_id: str = "WH-EAST",
    product_id: str = "SKU-COR-001",
) -> Scenario:
    flag = ExceptionFlag(
        category="low_stock_days_of_supply",
        product_id=product_id,
        warehouse_id=warehouse_id,
        simulation_date=date(2026, 1, 20),
        first_detected_simulation_date=date(2026, 1, 10),
        measured_value=Decimal("4.00"),
        threshold_value=Decimal("10.00"),
    )
    session.add(flag)
    session.flush()
    scenario = create_scenario_from_exception_flag(
        session,
        exception_flag_id=flag.id,
        scenario_type=ScenarioType.DATA_QUALITY_ISSUE,
        competency_cluster=CompetencyCluster.ANALYSIS_DIAGNOSIS,
        difficulty_tier=DifficultyTier.STANDARD,
        title=title,
        created_by=admin_id,
    )
    scenario.status = status
    session.flush()
    return scenario


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


class TestRepopulateWorld:
    def test_the_rebuilt_history_ends_on_today(self, session: Session) -> None:
        repopulate_world(session, today=_TODAY, history_days=_DAYS)

        tick_dates = sorted(session.scalars(select(ScheduledTick.simulation_date)))
        assert tick_dates == [_TODAY - timedelta(days=n) for n in range(_DAYS - 1, -1, -1)]
        kpi_dates = sorted(session.scalars(select(KpiSnapshot.simulation_date)))
        assert kpi_dates == tick_dates

    def test_old_generated_data_is_gone(self, session: Session, admin_id: uuid.UUID) -> None:
        _scenario(session, admin_id, title="zztest old", status=ScenarioStatus.DRAFT)
        old_flag_ids = set(session.scalars(select(ExceptionFlag.id)))
        assert old_flag_ids

        repopulate_world(session, today=_TODAY, history_days=_DAYS)

        remaining = set(session.scalars(select(ExceptionFlag.id)))
        assert not (old_flag_ids & remaining)
        assert session.scalar(
            select(func.count()).select_from(ScheduledTick).where(
                ScheduledTick.simulation_date < _TODAY - timedelta(days=_DAYS)
            )
        ) == 0

    def test_the_rebuild_generates_real_activity(self, session: Session) -> None:
        repopulate_world(session, today=_TODAY, history_days=_DAYS)

        assert _count(session, PurchaseOrder) > 0
        assert _count(session, SalesOrder) > 0

    def test_master_data_and_users_are_untouched(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        before = {
            model: _count(session, model) for model in (Product, Warehouse, Supplier, Customer, User)
        }

        repopulate_world(session, today=_TODAY, history_days=_DAYS)

        after = {model: _count(session, model) for model in before}
        assert after == before

    def test_the_clock_lands_on_today_and_runs(self, session: Session) -> None:
        clock = session.get(SimulationClock, 1)
        clock.status = ClockStatus.PAUSED
        session.flush()

        repopulate_world(session, today=_TODAY, history_days=_DAYS)

        session.refresh(clock)
        assert clock.simulation_date == _TODAY
        assert clock.status == ClockStatus.RUNNING
        head = session.get(WorldState, clock.current_world_state_id)
        assert head.kind == WorldStateKind.RESET
        assert head.simulation_date == _TODAY
        assert str(_TODAY) in head.label

    def test_live_scenarios_are_cancelled_but_kept_with_their_chats(
        self, session: Session, admin_id: uuid.UUID
    ) -> None:
        warehouses = list(session.scalars(select(Warehouse.id).order_by(Warehouse.id)))
        draft = _scenario(
            session, admin_id, title="zztest draft", status=ScenarioStatus.DRAFT,
            warehouse_id=warehouses[0],
        )
        approved = _scenario(
            session, admin_id, title="zztest approved", status=ScenarioStatus.APPROVED,
            warehouse_id=warehouses[1],
        )
        active = _scenario(
            session, admin_id, title="zztest active", status=ScenarioStatus.ACTIVE,
            warehouse_id=warehouses[2],
        )
        done = _scenario(
            session, admin_id, title="zztest done", status=ScenarioStatus.CANCELLED,
            warehouse_id=warehouses[2], product_id="SKU-COR-002",
        )
        thread = get_or_create_thread(
            session, scenario_id=active.id, persona=StakeholderPersona.CFO
        )

        result = repopulate_world(session, today=_TODAY, history_days=_DAYS)

        for scenario in (draft, approved, active, done):
            session.refresh(scenario)
            assert scenario.status == ScenarioStatus.CANCELLED
        assert session.get(ChatThread, thread.id) is not None
        assert result.scenarios_cancelled == 3

    def test_progress_is_reported_per_day(self, session: Session) -> None:
        seen: list[tuple[int, int]] = []

        repopulate_world(
            session, today=_TODAY, history_days=_DAYS, on_progress=lambda done, total: seen.append((done, total))
        )

        assert seen == [(n, _DAYS) for n in range(1, _DAYS + 1)]

    def test_rejects_a_history_shorter_than_one_day(self, session: Session) -> None:
        with pytest.raises(ValueError):
            repopulate_world(session, today=_TODAY, history_days=0)

    def test_a_failing_day_aborts_everything_it_did(
        self, session: Session, admin_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _scenario(session, admin_id, title="zztest keep", status=ScenarioStatus.ACTIVE)
        session.commit()
        flags_before = set(session.scalars(select(ExceptionFlag.id)))
        real_tick = world_repopulate.run_scheduled_tick
        calls = {"n": 0}

        def flaky_tick(sess, day):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("boom")
            return real_tick(sess, day)

        monkeypatch.setattr(world_repopulate, "run_scheduled_tick", flaky_tick)

        with pytest.raises(RuntimeError, match="boom"):
            repopulate_world(session, today=_TODAY, history_days=_DAYS)
        session.rollback()

        assert set(session.scalars(select(ExceptionFlag.id))) == flags_before
        scenario = session.scalars(select(Scenario).where(Scenario.title == "zztest keep")).one()
        assert scenario.status == ScenarioStatus.ACTIVE
        session.execute(delete(Scenario).where(Scenario.title == "zztest keep"))
        session.execute(delete(ExceptionFlag).where(ExceptionFlag.id.in_(flags_before)))
        session.commit()
