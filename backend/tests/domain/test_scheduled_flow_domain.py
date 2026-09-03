"""Unit 13 (MEADOWOPS-DOM-006): pure decision-logic tests for the scheduled
procure-to-stock/order-to-ship flow. No DB — see
tests/services/test_scheduled_flow.py for the transactional layer.
"""

import random

import pytest

from app.db.enums import ProductCategory, Variability
from app.domain.scheduled_flow import (
    BOOTSTRAP_REORDER_THRESHOLD,
    MINIMUM_REORDER_QUANTITY,
    NoMatchingSupplierError,
    SupplierCandidate,
    assign_supplier,
    is_below_reorder_point,
    jittered_lead_time_days,
    pick_demand_products,
    pick_demand_quantity,
    pick_requested_date_offset,
    reorder_quantity,
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
