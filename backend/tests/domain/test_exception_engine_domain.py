"""Unit 15 (MEADOWOPS-DOM-008): pure decision logic for the exception
engine — no DB access here, same domain/service split as scheduled_flow
and simulation_clock. Three categories match the three default rows
Unit 10 seeded into exception_rule_threshold: low_stock_days_of_supply,
at_risk_po_grace_days, late_shipment_grace_days.
"""

from datetime import date
from decimal import Decimal

from app.db.enums import PurchaseOrderStatus, ShipmentStatus
from app.domain.exception_engine import (
    evaluate_at_risk_purchase_order,
    evaluate_late_shipment,
    evaluate_low_stock,
)


class TestEvaluateLowStock:
    def test_flags_when_days_of_supply_below_threshold(self) -> None:
        assert evaluate_low_stock(Decimal("5.0"), threshold_days=Decimal("14")) is True

    def test_does_not_flag_when_days_of_supply_at_or_above_threshold(self) -> None:
        assert evaluate_low_stock(Decimal("14.0"), threshold_days=Decimal("14")) is False
        assert evaluate_low_stock(Decimal("20.0"), threshold_days=Decimal("14")) is False

    def test_does_not_flag_when_days_of_supply_is_none(self) -> None:
        # None means "undefined" (no shipment activity in the trailing 30
        # days, per days_of_supply.sql's own NULLIF guard) — not the same
        # as "zero days of supply." An undefined ratio can't be compared
        # against a threshold, so it's never flagged, consistent with
        # Unit 10's documented graceful-degradation behavior.
        assert evaluate_low_stock(None, threshold_days=Decimal("14")) is False

    def test_flags_zero_days_of_supply(self) -> None:
        assert evaluate_low_stock(Decimal("0"), threshold_days=Decimal("14")) is True


class TestEvaluateAtRiskPurchaseOrder:
    def test_flags_when_past_expected_delivery_plus_grace_and_still_open(self) -> None:
        result = evaluate_at_risk_purchase_order(
            expected_delivery_date=date(2026, 3, 1),
            simulation_date=date(2026, 3, 2),
            grace_days=0,
            status=PurchaseOrderStatus.SUBMITTED,
        )
        assert result is True

    def test_does_not_flag_within_grace_period(self) -> None:
        result = evaluate_at_risk_purchase_order(
            expected_delivery_date=date(2026, 3, 1),
            simulation_date=date(2026, 3, 3),
            grace_days=3,
            status=PurchaseOrderStatus.SUBMITTED,
        )
        assert result is False

    def test_does_not_flag_on_the_expected_delivery_date_itself(self) -> None:
        result = evaluate_at_risk_purchase_order(
            expected_delivery_date=date(2026, 3, 1),
            simulation_date=date(2026, 3, 1),
            grace_days=0,
            status=PurchaseOrderStatus.SUBMITTED,
        )
        assert result is False

    def test_does_not_flag_a_received_purchase_order(self) -> None:
        result = evaluate_at_risk_purchase_order(
            expected_delivery_date=date(2026, 3, 1),
            simulation_date=date(2026, 3, 10),
            grace_days=0,
            status=PurchaseOrderStatus.RECEIVED,
        )
        assert result is False

    def test_does_not_flag_a_cancelled_purchase_order(self) -> None:
        result = evaluate_at_risk_purchase_order(
            expected_delivery_date=date(2026, 3, 1),
            simulation_date=date(2026, 3, 10),
            grace_days=0,
            status=PurchaseOrderStatus.CANCELLED,
        )
        assert result is False

    def test_flags_a_partially_received_purchase_order_still_past_due(self) -> None:
        result = evaluate_at_risk_purchase_order(
            expected_delivery_date=date(2026, 3, 1),
            simulation_date=date(2026, 3, 2),
            grace_days=0,
            status=PurchaseOrderStatus.PARTIALLY_RECEIVED,
        )
        assert result is True


class TestEvaluateLateShipment:
    def test_flags_an_undelivered_shipment_past_promised_date_plus_grace(self) -> None:
        result = evaluate_late_shipment(
            promised_delivery_date=date(2026, 3, 1),
            actual_delivery_date=None,
            simulation_date=date(2026, 3, 2),
            grace_days=0,
            status=ShipmentStatus.IN_TRANSIT,
        )
        assert result is True

    def test_does_not_flag_an_undelivered_shipment_within_grace(self) -> None:
        result = evaluate_late_shipment(
            promised_delivery_date=date(2026, 3, 1),
            actual_delivery_date=None,
            simulation_date=date(2026, 3, 2),
            grace_days=2,
            status=ShipmentStatus.IN_TRANSIT,
        )
        assert result is False

    def test_flags_a_delivered_shipment_that_arrived_late(self) -> None:
        result = evaluate_late_shipment(
            promised_delivery_date=date(2026, 3, 1),
            actual_delivery_date=date(2026, 3, 4),
            simulation_date=date(2026, 3, 10),
            grace_days=0,
            status=ShipmentStatus.DELIVERED,
        )
        assert result is True

    def test_does_not_flag_a_delivered_shipment_that_arrived_on_time(self) -> None:
        result = evaluate_late_shipment(
            promised_delivery_date=date(2026, 3, 1),
            actual_delivery_date=date(2026, 3, 1),
            simulation_date=date(2026, 3, 10),
            grace_days=0,
            status=ShipmentStatus.DELIVERED,
        )
        assert result is False

    def test_does_not_flag_a_delivered_shipment_within_grace(self) -> None:
        result = evaluate_late_shipment(
            promised_delivery_date=date(2026, 3, 1),
            actual_delivery_date=date(2026, 3, 3),
            simulation_date=date(2026, 3, 10),
            grace_days=2,
            status=ShipmentStatus.DELIVERED,
        )
        assert result is False

    def test_does_not_flag_a_pending_shipment_not_yet_past_promised_date(self) -> None:
        result = evaluate_late_shipment(
            promised_delivery_date=date(2026, 3, 5),
            actual_delivery_date=None,
            simulation_date=date(2026, 3, 2),
            grace_days=0,
            status=ShipmentStatus.PENDING,
        )
        assert result is False
