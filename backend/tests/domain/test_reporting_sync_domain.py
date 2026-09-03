"""Unit 17 (MEADOWOPS-DOM-009): pure decision logic for the Reporting-layer
sync (SR-2/S1-FR-9) and its one seeded conflicting-source case (SR-4).
No DB access here — mirrors the domain/service split of
app.domain.scheduled_flow / app.services.scheduled_flow.
"""

from datetime import date

from app.domain.reporting_sync import (
    is_lag_stale,
    pick_conflict_entity,
    target_sync_date,
)


class TestTargetSyncDate:
    def test_subtracts_lag_days_from_simulation_date(self) -> None:
        assert target_sync_date(date(2026, 3, 10), lag_days=2) == date(2026, 3, 8)

    def test_zero_lag_returns_the_same_date(self) -> None:
        assert target_sync_date(date(2026, 3, 10), lag_days=0) == date(2026, 3, 10)


class TestIsLagStale:
    def test_not_stale_when_lag_is_within_the_max_window(self) -> None:
        assert (
            is_lag_stale(
                simulation_date=date(2026, 3, 10),
                last_synced_simulation_date=date(2026, 3, 8),
                max_lag_days=5,
            )
            is False
        )

    def test_stale_once_lag_exceeds_the_max_window(self) -> None:
        assert (
            is_lag_stale(
                simulation_date=date(2026, 3, 10),
                last_synced_simulation_date=date(2026, 3, 1),
                max_lag_days=5,
            )
            is True
        )

    def test_exactly_at_the_max_window_is_not_yet_stale(self) -> None:
        # (2026, 3, 10) - (2026, 3, 5) = 5 days; the boundary itself is
        # still within the configured window, matching
        # evaluate_at_risk_purchase_order's own strict-greater-than
        # convention (app.domain.exception_engine).
        assert (
            is_lag_stale(
                simulation_date=date(2026, 3, 10),
                last_synced_simulation_date=date(2026, 3, 5),
                max_lag_days=5,
            )
            is False
        )

    def test_never_synced_is_not_stale(self) -> None:
        # Before the reporting layer's first-ever sync there is no live
        # history yet for it to lag behind — "hasn't synced" is not
        # evidence of a broken sync, the same inconclusive-verdict posture
        # app.domain.exception_engine.evaluate_low_stock takes for an
        # undefined days-of-supply ratio.
        assert (
            is_lag_stale(
                simulation_date=date(2026, 3, 10),
                last_synced_simulation_date=None,
                max_lag_days=5,
            )
            is False
        )


class TestPickConflictEntity:
    def test_picks_the_lexicographically_smallest_pair(self) -> None:
        candidates = [
            ("SKU-COR-002", "WH-EAST"),
            ("SKU-COR-001", "WH-WEST"),
            ("SKU-COR-001", "WH-EAST"),
        ]
        assert pick_conflict_entity(candidates) == ("SKU-COR-001", "WH-EAST")

    def test_empty_candidates_returns_none(self) -> None:
        assert pick_conflict_entity([]) is None

    def test_deterministic_regardless_of_input_order(self) -> None:
        a = [("SKU-B", "WH-1"), ("SKU-A", "WH-2")]
        b = [("SKU-A", "WH-2"), ("SKU-B", "WH-1")]
        assert pick_conflict_entity(a) == pick_conflict_entity(b)
