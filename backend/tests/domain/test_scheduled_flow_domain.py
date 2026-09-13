"""Unit 13 (MEADOWOPS-DOM-006): pure decision-logic tests for the scheduled
procure-to-stock/order-to-ship flow. No DB — see
tests/services/test_scheduled_flow.py for the transactional layer.

Unit 27 (MEADOWOPS-DOM-021, business id MEADOWOPS-DOMAIN-016, PRD 3.4/5.2)
adds warehouse-transfer donor/deficit logic and carrier-variability
lateness jitter to this same pure-decision module.
"""

import random
from decimal import Decimal

import pytest

from app.db.enums import ProductCategory, Variability
from app.domain.scheduled_flow import (
    BOOTSTRAP_REORDER_THRESHOLD,
    MINIMUM_REORDER_QUANTITY,
    NoMatchingSupplierError,
    SupplierCandidate,
    assign_supplier,
    carrier_actual_transit_days,
    is_below_reorder_point,
    jittered_lead_time_days,
    pick_demand_products,
    pick_demand_quantity,
    pick_requested_date_offset,
    pick_transfer_donor,
    reorder_quantity,
    roll_partial_receipt_fraction,
    transferable_surplus,
    warehouse_deficit,
)


class TestAssignSupplier:
    def test_matches_supplier_whose_category_focus_contains_the_keyword(self) -> None:
        suppliers = [
            SupplierCandidate(id="S-003", category_focus="Shipping/Labeling Supplies"),
            SupplierCandidate(id="S-002", category_focus="Protective Packaging"),
        ]
        result = assign_supplier(ProductCategory.PROTECTIVE_PACKAGING, suppliers)
        assert result.id == "S-002"

    def test_is_case_insensitive(self) -> None:
        suppliers = [SupplierCandidate(id="S-001", category_focus="CORRUGATED PACKAGING")]
        result = assign_supplier(ProductCategory.CORRUGATED_PACKAGING, suppliers)
        assert result.id == "S-001"

    def test_multiple_matches_deterministically_picks_the_lowest_id(self) -> None:
        # S-001 and S-004 (baseline data) both match "corrugated".
        suppliers = [
            SupplierCandidate(id="S-004", category_focus="Corrugated + Protective"),
            SupplierCandidate(id="S-001", category_focus="Corrugated Packaging"),
        ]
        result = assign_supplier(ProductCategory.CORRUGATED_PACKAGING, suppliers)
        assert result.id == "S-001"

    def test_same_input_always_resolves_to_the_same_supplier(self) -> None:
        suppliers = [
            SupplierCandidate(id="S-004", category_focus="Corrugated + Protective"),
            SupplierCandidate(id="S-001", category_focus="Corrugated Packaging"),
        ]
        first = assign_supplier(ProductCategory.CORRUGATED_PACKAGING, suppliers)
        second = assign_supplier(ProductCategory.CORRUGATED_PACKAGING, suppliers)
        assert first.id == second.id

    def test_no_matching_supplier_raises_rather_than_silently_picking_one(self) -> None:
        suppliers = [SupplierCandidate(id="S-003", category_focus="Shipping/Labeling Supplies")]
        with pytest.raises(NoMatchingSupplierError):
            assign_supplier(ProductCategory.PROTECTIVE_PACKAGING, suppliers)


class TestJitteredLeadTimeDays:
    def test_low_variability_stays_within_a_narrow_band(self) -> None:
        rng = random.Random("test-seed")
        for _ in range(50):
            result = jittered_lead_time_days(7, Variability.LOW, rng)
            assert 6 <= result <= 8

    def test_high_variability_allows_a_wider_band(self) -> None:
        rng = random.Random("test-seed")
        results = {jittered_lead_time_days(10, Variability.HIGH, rng) for _ in range(50)}
        assert max(results) - min(results) > 2  # wider spread than LOW's band

    def test_never_returns_less_than_one_day(self) -> None:
        rng = random.Random("test-seed")
        for _ in range(200):
            assert jittered_lead_time_days(1, Variability.HIGH, rng) >= 1

    def test_same_rng_state_is_deterministic(self) -> None:
        first = jittered_lead_time_days(7, Variability.MEDIUM, random.Random("fixed"))
        second = jittered_lead_time_days(7, Variability.MEDIUM, random.Random("fixed"))
        assert first == second


class TestReorderQuantity:
    def test_scales_with_average_daily_demand_and_target_days(self) -> None:
        assert reorder_quantity(avg_daily_demand=10.0, target_days_of_supply=30) == 300

    def test_rounds_a_fractional_result_up_not_down(self) -> None:
        # 3.1 * 10 = 31.0 exactly; use a value that actually produces a
        # fraction to prove ceil, not round-half.
        assert reorder_quantity(avg_daily_demand=3.34, target_days_of_supply=10) == 34

    def test_floors_at_the_minimum_even_for_near_zero_demand(self) -> None:
        assert reorder_quantity(avg_daily_demand=0.1, target_days_of_supply=14) == MINIMUM_REORDER_QUANTITY


class TestIsBelowReorderPoint:
    def test_true_when_position_would_run_out_within_the_safety_window(self) -> None:
        assert is_below_reorder_point(current_position=5, avg_daily_demand=2.0, reorder_safety_days=14) is True

    def test_false_when_position_comfortably_covers_the_safety_window(self) -> None:
        assert is_below_reorder_point(current_position=100, avg_daily_demand=2.0, reorder_safety_days=14) is False

    def test_zero_demand_and_zero_position_still_bootstraps_a_first_order(self) -> None:
        assert is_below_reorder_point(current_position=0, avg_daily_demand=0.0, reorder_safety_days=14) is True

    def test_zero_demand_with_existing_stock_does_not_trigger(self) -> None:
        result = is_below_reorder_point(
            current_position=BOOTSTRAP_REORDER_THRESHOLD + 1, avg_daily_demand=0.0, reorder_safety_days=14
        )
        assert result is False


class TestWarehouseDeficit:
    def test_zero_when_position_meets_the_threshold(self) -> None:
        assert warehouse_deficit(current_position=100, avg_daily_demand=2.0, reorder_safety_days=14) == 0

    def test_ceils_the_shortfall_below_the_threshold(self) -> None:
        # threshold = max(2.5*14, BOOTSTRAP) = 35; 35 - 30 = 5 exactly.
        assert warehouse_deficit(current_position=30, avg_daily_demand=2.5, reorder_safety_days=14) == 5

    def test_uses_the_same_bootstrap_floor_as_is_below_reorder_point(self) -> None:
        # Zero demand still uses BOOTSTRAP_REORDER_THRESHOLD as the floor.
        assert (
            warehouse_deficit(current_position=0, avg_daily_demand=0.0, reorder_safety_days=14)
            == BOOTSTRAP_REORDER_THRESHOLD
        )


class TestTransferableSurplus:
    def test_zero_when_position_is_at_or_below_its_own_threshold(self) -> None:
        assert (
            transferable_surplus(
                current_position=35, allocated=0, avg_daily_demand=2.5, reorder_safety_days=14
            )
            == 0
        )

    def test_floors_the_spare_amount_above_the_threshold_and_allocations(self) -> None:
        # threshold = 35; spare = 100 - 10 (allocated) - 35 = 55.
        assert (
            transferable_surplus(
                current_position=100, allocated=10, avg_daily_demand=2.5, reorder_safety_days=14
            )
            == 55
        )

    def test_never_returns_a_negative_amount(self) -> None:
        assert (
            transferable_surplus(
                current_position=5, allocated=20, avg_daily_demand=2.5, reorder_safety_days=14
            )
            == 0
        )


class TestPickTransferDonor:
    def test_picks_the_candidate_with_the_greatest_surplus(self) -> None:
        candidates = [("WH-EAST", 10), ("WH-CENTRAL", 40), ("WH-WEST", 25)]
        assert pick_transfer_donor(candidates) == ("WH-CENTRAL", 40)

    def test_breaks_a_tie_by_the_lowest_warehouse_id(self) -> None:
        candidates = [("WH-WEST", 30), ("WH-CENTRAL", 30)]
        assert pick_transfer_donor(candidates) == ("WH-CENTRAL", 30)

    def test_returns_none_when_no_candidate_has_any_surplus(self) -> None:
        candidates = [("WH-EAST", 0), ("WH-CENTRAL", -5)]
        assert pick_transfer_donor(candidates) is None

    def test_returns_none_for_an_empty_candidate_list(self) -> None:
        assert pick_transfer_donor([]) is None


class TestCarrierActualTransitDays:
    def test_a_perfectly_reliable_carrier_is_always_on_time(self) -> None:
        rng = random.Random("test-seed")
        for _ in range(50):
            assert carrier_actual_transit_days(4, Variability.HIGH, 100.0, rng) == 4

    def test_an_unreliable_carrier_eventually_arrives_late(self) -> None:
        rng = random.Random("test-seed")
        results = {carrier_actual_transit_days(4, Variability.MEDIUM, 0.0, rng) for _ in range(50)}
        assert all(r > 4 for r in results)
        assert max(results) - 4 <= 3  # MEDIUM's spread

    def test_late_arrival_never_exceeds_the_variability_tiers_spread(self) -> None:
        rng = random.Random("test-seed")
        for _ in range(200):
            result = carrier_actual_transit_days(5, Variability.LOW, 0.0, rng)
            assert 5 < result <= 5 + 1  # LOW's spread is 1 day

    def test_same_rng_state_is_deterministic(self) -> None:
        first = carrier_actual_transit_days(4, Variability.MEDIUM, 50.0, random.Random("fixed"))
        second = carrier_actual_transit_days(4, Variability.MEDIUM, 50.0, random.Random("fixed"))
        assert first == second


class TestDemandPicking:
    def test_pick_demand_products_returns_between_one_and_three_distinct_ids(self) -> None:
        rng = random.Random("test-seed")
        product_ids = [f"SKU-{i}" for i in range(20)]
        for _ in range(50):
            picked = pick_demand_products(rng, product_ids)
            assert 1 <= len(picked) == len(set(picked)) <= 3

    def test_pick_demand_products_empty_catalog_returns_empty(self) -> None:
        rng = random.Random("test-seed")
        assert pick_demand_products(rng, []) == []

    def test_pick_demand_quantity_within_bounds(self) -> None:
        rng = random.Random("test-seed")
        for _ in range(100):
            qty = pick_demand_quantity(rng)
            assert 1 <= qty <= 20

    def test_pick_requested_date_offset_within_bounds(self) -> None:
        rng = random.Random("test-seed")
        for _ in range(100):
            offset = pick_requested_date_offset(rng)
            assert 1 <= offset <= 3


class TestRollPartialReceiptFraction:
    """Unit 30 (MEADOWOPS-DOM-030, PRD 9.2 catalog row 4): a real, seeded
    chance that a PO receipt tick only partially fulfills a line, making
    PurchaseOrderStatus.PARTIALLY_RECEIVED reachable for the first time."""

    def test_returns_none_or_a_fraction_strictly_between_0_and_1(self) -> None:
        rng = random.Random("test-seed")
        for _ in range(200):
            result = roll_partial_receipt_fraction(rng)
            assert result is None or Decimal("0") < result < Decimal("1")

    def test_both_outcomes_are_reachable_over_enough_rolls(self) -> None:
        rng = random.Random("test-seed")
        results = {roll_partial_receipt_fraction(rng) for _ in range(200)}
        assert None in results
        assert any(r is not None for r in results)

    def test_same_rng_state_is_deterministic(self) -> None:
        first = roll_partial_receipt_fraction(random.Random("fixed"))
        second = roll_partial_receipt_fraction(random.Random("fixed"))
        assert first == second
