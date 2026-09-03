"""Unit 18 (MEADOWOPS-DOM-011): pure domain-layer tests for the scenario
builder's state machine, approve-time validation, and deterministic
ground-truth snapshot builder. No DB — app.domain.scenario takes plain
dataclasses/dicts, matching app.domain.ledger/reporting_sync's own layering.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.domain.scenario import (
    REQUIRED_GROUND_TRUTH_FIELDS,
    ExceptionFlagNotOpenError,
    ExceptionFlagSnapshot,
    build_ground_truth_from_exception_flag,
    can_transition,
    validate_for_approval,
)

_OPEN_FLAG = ExceptionFlagSnapshot(
    id="11111111-1111-1111-1111-111111111111",
    category="low_stock",
    product_id="ZZTEST-SKU-01",
    warehouse_id="ZZTEST-WH-01",
    purchase_order_id=None,
    shipment_id=None,
    simulation_date=date(2026, 6, 1),
    first_detected_simulation_date=date(2026, 5, 20),
    measured_value=Decimal("4.00"),
    threshold_value=Decimal("10.00"),
    resolved_at=None,
)

_RESOLVED_FLAG = ExceptionFlagSnapshot(
    id="22222222-2222-2222-2222-222222222222",
    category="low_stock",
    product_id="ZZTEST-SKU-02",
    warehouse_id="ZZTEST-WH-01",
    purchase_order_id=None,
    shipment_id=None,
    simulation_date=date(2026, 6, 1),
    first_detected_simulation_date=date(2026, 5, 20),
    measured_value=Decimal("12.00"),
    threshold_value=Decimal("10.00"),
    resolved_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
)


class TestStateMachine:
    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            ("draft", "approved"),
            ("draft", "cancelled"),
            ("approved", "active"),
            ("approved", "cancelled"),
        ],
    )
    def test_valid_transitions_are_allowed(self, from_status: str, to_status: str) -> None:
        assert can_transition(from_status, to_status) is True

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            ("draft", "active"),
            ("approved", "draft"),
            ("active", "draft"),
            ("active", "approved"),
            ("active", "cancelled"),
            ("cancelled", "draft"),
            ("cancelled", "approved"),
            ("cancelled", "active"),
        ],
    )
    def test_invalid_transitions_are_rejected(self, from_status: str, to_status: str) -> None:
        assert can_transition(from_status, to_status) is False


class TestBuildGroundTruthFromExceptionFlag:
    def test_populates_all_seven_required_fields(self) -> None:
        result = build_ground_truth_from_exception_flag(_OPEN_FLAG)
        assert set(result.keys()) == set(REQUIRED_GROUND_TRUTH_FIELDS)

    def test_known_cause_and_evidence_are_derived_from_the_flag(self) -> None:
        result = build_ground_truth_from_exception_flag(_OPEN_FLAG)
        assert "low_stock" in result["known_cause"]
        assert result["evidence"]["source_exception_flag_id"] == _OPEN_FLAG.id
        assert result["evidence"]["threshold_value"] == "10.00"

    def test_narrative_fields_start_empty_for_the_builder_to_edit(self) -> None:
        result = build_ground_truth_from_exception_flag(_OPEN_FLAG)
        assert result["supporting_signals"] == []
        assert result["distractors"] == []
        assert result["uncertainty"] == ""

    def test_raises_when_the_flag_has_already_resolved(self) -> None:
        with pytest.raises(ExceptionFlagNotOpenError):
            build_ground_truth_from_exception_flag(_RESOLVED_FLAG)


class TestValidateForApproval:
    def _complete_ground_truth(self) -> dict:
        gt = build_ground_truth_from_exception_flag(_OPEN_FLAG)
        gt["supporting_signals"] = ["signal"]
        gt["distractors"] = ["distractor"]
        gt["expected_considerations"] = ["consideration"]
        gt["acceptable_conclusions"] = ["ok conclusion"]
        gt["unacceptable_conclusions"] = ["bad conclusion"]
        gt["uncertainty"] = "moderate confidence"
        return gt

    def test_complete_package_with_targeting_passes(self) -> None:
        errors = validate_for_approval(
            ground_truth=self._complete_ground_truth(),
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
        )
        assert errors == []

    def test_missing_difficulty_tier_is_rejected(self) -> None:
        errors = validate_for_approval(
            ground_truth=self._complete_ground_truth(),
            difficulty_tier=None,
            competency_cluster="analysis_diagnosis",
        )
        assert any("difficulty_tier" in e for e in errors)

    def test_missing_competency_cluster_is_rejected(self) -> None:
        errors = validate_for_approval(
            ground_truth=self._complete_ground_truth(),
            difficulty_tier="standard",
            competency_cluster=None,
        )
        assert any("competency_cluster" in e for e in errors)

    def test_freshly_built_ground_truth_is_rejected_until_the_builder_edits_it(self) -> None:
        # The Builder-edit gap is the whole point (6.4's own required
        # rejection-path test case, DD-24 point 3) — a scenario cannot be
        # approved on the auto-derived skeleton alone.
        errors = validate_for_approval(
            ground_truth=build_ground_truth_from_exception_flag(_OPEN_FLAG),
            difficulty_tier="standard",
            competency_cluster="analysis_diagnosis",
        )
        assert errors != []
        assert any("supporting_signals" in e for e in errors)
        assert any("uncertainty" in e for e in errors)

    def test_missing_evidence_key_is_rejected(self) -> None:
        gt = self._complete_ground_truth()
        del gt["evidence"]
        errors = validate_for_approval(
            ground_truth=gt, difficulty_tier="standard", competency_cluster="analysis_diagnosis"
        )
        assert any("evidence" in e for e in errors)
