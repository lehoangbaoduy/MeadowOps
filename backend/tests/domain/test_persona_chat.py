"""Unit 23 (MEADOWOPS-DOM-017, business id MEADOWOPS-DOMAIN-012, PRD 6.5/
6.6/6.13): pure domain-layer tests for the persona-roleplay pushback
suggestion and AI sufficiency check. No DB access - see app.domain.
persona_chat's own docstring for why the ground_truth/thread lookups live
in app.services.persona_chat instead.
"""

from __future__ import annotations

import json
import typing

import pytest

from app.db.enums import StakeholderPersona
from app.domain.claude_client import ClaudeAPIError, ClaudeResponse, ClaudeTimeoutError, MockClaudeClient
from app.domain.persona_chat import (
    PERSONA_PROFILES,
    Attitude,
    PersonaMessageGenerationFailedError,
    SufficiencyCheckFailedError,
    SufficiencyCheckSchemaError,
    SufficiencyVerdict,
    build_known_information,
    build_opening_prompt,
    build_pushback_prompt,
    parse_sufficiency_response,
    run_sufficiency_check,
    suggest_opening_message,
    suggest_pushback_message,
)

_FULL_GROUND_TRUTH = {
    "known_cause": "Reorder point misconfigured for SKU-COR-001 at WH-EAST",
    "evidence": {"product_id": "SKU-COR-001", "warehouse_id": "WH-EAST", "on_hand": 12},
    "supporting_signals": ["SECRET-SIGNAL-lead-time-spike"],
    "distractors": ["SECRET-DISTRACTOR-warehouse-relocation"],
    "expected_considerations": ["SECRET-CONSIDERATION-check-reorder-point"],
    "acceptable_conclusions": ["SECRET-CONCLUSION-raise-reorder-point"],
    "unacceptable_conclusions": ["SECRET-CONCLUSION-blame-supplier"],
    "uncertainty": "SECRET-UNCERTAINTY-moderate confidence in demand forecast",
}

_GRADING_ONLY_KEYS = (
    "supporting_signals",
    "distractors",
    "expected_considerations",
    "acceptable_conclusions",
    "unacceptable_conclusions",
    "uncertainty",
)

_VALID_SUFFICIENCY_PAYLOAD = {"verdict": "insufficient", "suggested_pushback": "But what about lead time?"}


class TestAttitudeSchemaSync:
    def test_the_schema_literal_matches_the_domain_enum_exactly(self) -> None:
        # Code review finding: app.schemas.chat.Attitude (a Pydantic
        # Literal, validated at the API boundary) and this module's
        # Attitude enum (converted via `Attitude(payload.attitude)` in
        # app.api.chat.suggest_pushback_route, *outside* that route's own
        # try/except) have no guard tying them together, unlike
        # StakeholderPersona/PERSONA_PROFILES above. A schema-Literal value
        # added without a matching enum member would 422 at validation but
        # then raise an unhandled ValueError -> 500 at the route - this
        # pins the two sets equal so that drift fails here first.
        from app.schemas.chat import Attitude as AttitudeSchema

        schema_values = set(typing.get_args(AttitudeSchema))
        domain_values = {attitude.value for attitude in Attitude}
        assert schema_values == domain_values


class TestPersonaProfiles:
    def test_every_stakeholder_persona_has_a_profile(self):
        assert set(PERSONA_PROFILES) == set(StakeholderPersona)

    def test_every_profile_has_nonblank_priorities_and_style(self):
        for profile in PERSONA_PROFILES.values():
            assert profile.name.strip()
            assert profile.priorities.strip()
            assert profile.style.strip()


class TestBuildKnownInformation:
    def test_includes_known_cause_and_evidence(self):
        known_information = build_known_information(_FULL_GROUND_TRUTH)
        assert known_information["known_cause"] == _FULL_GROUND_TRUTH["known_cause"]
        assert known_information["evidence"] == _FULL_GROUND_TRUTH["evidence"]

    @pytest.mark.parametrize("grading_key", _GRADING_ONLY_KEYS)
    def test_excludes_every_grading_only_key(self, grading_key):
        known_information = build_known_information(_FULL_GROUND_TRUTH)
        assert grading_key not in known_information

    def test_tolerates_a_ground_truth_missing_known_cause_or_evidence(self):
        # U18's own build_ground_truth_from_exception_flag always includes
        # both, but this function should not crash on a partial dict.
        assert build_known_information({}) == {}


class TestBuildPushbackPrompt:
    def _kwargs(self, **overrides) -> dict:
        base = dict(
            persona=StakeholderPersona.CFO,
            attitude=Attitude.NEUTRAL,
            known_information=build_known_information(_FULL_GROUND_TRUTH),
            conversation_history="Analyst: what's driving the stockout?",
            analyst_message="I think the reorder point is fine.",
        )
        base.update(overrides)
        return base

    def test_includes_persona_priorities_and_style(self):
        prompt = build_pushback_prompt(**self._kwargs())
        profile = PERSONA_PROFILES[StakeholderPersona.CFO]
        assert profile.priorities in prompt
        assert profile.style in prompt

    def test_includes_the_attitude_description_as_a_suffix(self):
        neutral_prompt = build_pushback_prompt(**self._kwargs(attitude=Attitude.NEUTRAL))
        frustrated_prompt = build_pushback_prompt(**self._kwargs(attitude=Attitude.FRUSTRATED))
        assert neutral_prompt != frustrated_prompt
        assert "frustrated" in frustrated_prompt.lower()

    @pytest.mark.parametrize("grading_marker", ["SECRET-SIGNAL", "SECRET-DISTRACTOR", "SECRET-CONSIDERATION", "SECRET-CONCLUSION", "SECRET-UNCERTAINTY"])
    def test_never_leaks_a_grading_field_when_given_the_redacted_projection(self, grading_marker):
        # End-to-end guard against the realistic mistake: this asserts what
        # actually reaches Claude's prompt, given the known_information a
        # real caller is expected to pass (build_known_information's own
        # output) - not the full ground_truth. build_known_information's
        # exclusion of each grading key is asserted directly above; this
        # confirms that exclusion actually survives prompt rendering too.
        prompt = build_pushback_prompt(**self._kwargs())
        assert grading_marker not in prompt

    def test_does_not_mutate_the_frozen_template_text(self):
        from app.domain.prompt_templates import STAKEHOLDER_ROLEPLAY_TEMPLATE

        before = STAKEHOLDER_ROLEPLAY_TEMPLATE.template
        build_pushback_prompt(**self._kwargs())
        assert STAKEHOLDER_ROLEPLAY_TEMPLATE.template == before


class TestSuggestPushbackMessage:
    def _kwargs(self) -> dict:
        return dict(
            persona=StakeholderPersona.CFO,
            attitude=Attitude.SKEPTICAL,
            known_information=build_known_information(_FULL_GROUND_TRUTH),
            conversation_history="Analyst: what's driving the stockout?",
            analyst_message="I think the reorder point is fine.",
        )

    def test_succeeds_on_the_first_call(self):
        client = MockClaudeClient(script=[ClaudeResponse(content="That doesn't add up to me.")])

        message = suggest_pushback_message(client, **self._kwargs())

        assert message == "That doesn't add up to me."
        assert len(client.call_log) == 1

    def test_retries_once_after_a_claude_api_error_then_succeeds(self):
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeResponse(content="Still not convinced.")]
        )

        message = suggest_pushback_message(client, **self._kwargs())

        assert message == "Still not convinced."
        assert len(client.call_log) == 2

    def test_retries_once_after_a_timeout_then_succeeds(self):
        client = MockClaudeClient(
            script=[ClaudeTimeoutError("timed out"), ClaudeResponse(content="Please explain further.")]
        )

        message = suggest_pushback_message(client, **self._kwargs())

        assert len(client.call_log) == 2
        assert message

    def test_retries_once_after_an_empty_response_then_succeeds(self):
        client = MockClaudeClient(
            script=[ClaudeResponse(content="   "), ClaudeResponse(content="A real reply.")]
        )

        message = suggest_pushback_message(client, **self._kwargs())

        assert message == "A real reply."
        assert len(client.call_log) == 2

    def test_raises_after_the_retry_is_also_exhausted(self):
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeAPIError("rate limited again")]
        )

        with pytest.raises(PersonaMessageGenerationFailedError):
            suggest_pushback_message(client, **self._kwargs())
        assert len(client.call_log) == 2

    def test_does_not_attempt_a_third_call(self):
        client = MockClaudeClient(
            script=[
                ClaudeAPIError("1"),
                ClaudeAPIError("2"),
                ClaudeResponse(content="unused"),
            ]
        )

        with pytest.raises(PersonaMessageGenerationFailedError):
            suggest_pushback_message(client, **self._kwargs())
        assert len(client.call_log) == 2


class TestBuildOpeningPrompt:
    """Unit 35 (follow-on to Unit 23): mirrors TestBuildPushbackPrompt
    above, but there is no analyst_message/conversation_history to react
    to yet - STAKEHOLDER_OPENING_TEMPLATE has neither slot, unlike
    STAKEHOLDER_ROLEPLAY_TEMPLATE."""

    def _kwargs(self, **overrides) -> dict:
        base = dict(
            persona=StakeholderPersona.CFO,
            attitude=Attitude.NEUTRAL,
            known_information=build_known_information(_FULL_GROUND_TRUTH),
        )
        base.update(overrides)
        return base

    def test_includes_persona_priorities_and_style(self):
        prompt = build_opening_prompt(**self._kwargs())
        profile = PERSONA_PROFILES[StakeholderPersona.CFO]
        assert profile.priorities in prompt
        assert profile.style in prompt

    def test_includes_the_attitude_description_as_a_suffix(self):
        neutral_prompt = build_opening_prompt(**self._kwargs(attitude=Attitude.NEUTRAL))
        frustrated_prompt = build_opening_prompt(**self._kwargs(attitude=Attitude.FRUSTRATED))
        assert neutral_prompt != frustrated_prompt
        assert "frustrated" in frustrated_prompt.lower()

    @pytest.mark.parametrize("attitude", [Attitude.SKEPTICAL, Attitude.APPRECIATIVE])
    def test_skeptical_and_appreciative_do_not_reference_a_nonexistent_prior_analyst_turn(self, attitude):
        # Code review finding: build_pushback_prompt's shared
        # _ATTITUDE_DESCRIPTIONS wording for these two ("...the Analyst's
        # claims", "...the Analyst's work so far") presupposes a prior
        # Analyst message that cannot exist yet on an opening message -
        # build_opening_prompt must use its own wording for these two,
        # not the pushback-oriented one.
        prompt = build_opening_prompt(**self._kwargs(attitude=attitude))
        assert "analyst's claims" not in prompt.lower()
        assert "analyst's work" not in prompt.lower()

    @pytest.mark.parametrize("grading_marker", ["SECRET-SIGNAL", "SECRET-DISTRACTOR", "SECRET-CONSIDERATION", "SECRET-CONCLUSION", "SECRET-UNCERTAINTY"])
    def test_never_leaks_a_grading_field_when_given_the_redacted_projection(self, grading_marker):
        prompt = build_opening_prompt(**self._kwargs())
        assert grading_marker not in prompt

    def test_does_not_mutate_the_frozen_roleplay_template(self):
        # This function must render its own new template, never the
        # existing frozen STAKEHOLDER_ROLEPLAY_TEMPLATE (ER-6 discipline -
        # see that template's own "must not be edited" precedent).
        from app.domain.prompt_templates import STAKEHOLDER_ROLEPLAY_TEMPLATE

        before = STAKEHOLDER_ROLEPLAY_TEMPLATE.template
        build_opening_prompt(**self._kwargs())
        assert STAKEHOLDER_ROLEPLAY_TEMPLATE.template == before


class TestSuggestOpeningMessage:
    def _kwargs(self) -> dict:
        return dict(
            persona=StakeholderPersona.CFO,
            attitude=Attitude.URGENT,
            known_information=build_known_information(_FULL_GROUND_TRUTH),
        )

    def test_succeeds_on_the_first_call(self):
        client = MockClaudeClient(script=[ClaudeResponse(content="We need to talk about this.")])

        message = suggest_opening_message(client, **self._kwargs())

        assert message == "We need to talk about this."
        assert len(client.call_log) == 1

    def test_retries_once_after_a_claude_api_error_then_succeeds(self):
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeResponse(content="Second attempt.")]
        )

        message = suggest_opening_message(client, **self._kwargs())

        assert message == "Second attempt."
        assert len(client.call_log) == 2

    def test_retries_once_after_an_empty_response_then_succeeds(self):
        client = MockClaudeClient(
            script=[ClaudeResponse(content="   "), ClaudeResponse(content="A real opening.")]
        )

        message = suggest_opening_message(client, **self._kwargs())

        assert message == "A real opening."
        assert len(client.call_log) == 2

    def test_raises_after_the_retry_is_also_exhausted(self):
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeAPIError("rate limited again")]
        )

        with pytest.raises(PersonaMessageGenerationFailedError):
            suggest_opening_message(client, **self._kwargs())
        assert len(client.call_log) == 2

    def test_does_not_attempt_a_third_call(self):
        client = MockClaudeClient(
            script=[
                ClaudeAPIError("1"),
                ClaudeAPIError("2"),
                ClaudeResponse(content="unused"),
            ]
        )

        with pytest.raises(PersonaMessageGenerationFailedError):
            suggest_opening_message(client, **self._kwargs())
        assert len(client.call_log) == 2


class TestParseSufficiencyResponse:
    def test_parses_an_insufficient_verdict(self):
        verdict = parse_sufficiency_response(json.dumps(_VALID_SUFFICIENCY_PAYLOAD))

        assert isinstance(verdict, SufficiencyVerdict)
        assert verdict.verdict == "insufficient"
        assert verdict.suggested_pushback == "But what about lead time?"

    def test_parses_a_sufficient_verdict_with_null_pushback(self):
        payload = {"verdict": "sufficient", "suggested_pushback": None}

        verdict = parse_sufficiency_response(json.dumps(payload))

        assert verdict.verdict == "sufficient"
        assert verdict.suggested_pushback is None

    def test_forces_suggested_pushback_to_none_on_sufficient_even_if_present(self):
        payload = {"verdict": "sufficient", "suggested_pushback": "ignored anyway"}

        verdict = parse_sufficiency_response(json.dumps(payload))

        assert verdict.suggested_pushback is None

    def test_raises_on_invalid_json(self):
        with pytest.raises(SufficiencyCheckSchemaError):
            parse_sufficiency_response("not json at all")

    def test_raises_a_schema_error_not_a_recursion_error_on_deeply_nested_json(self):
        deeply_nested = "[" * 3000 + "]" * 3000
        with pytest.raises(SufficiencyCheckSchemaError):
            parse_sufficiency_response(deeply_nested)

    def test_raises_when_response_is_a_json_array_not_object(self):
        with pytest.raises(SufficiencyCheckSchemaError):
            parse_sufficiency_response("[1, 2, 3]")

    @pytest.mark.parametrize("bad_verdict", ["maybe", "SUFFICIENT", "", None, 1])
    def test_raises_on_an_invalid_verdict_value(self, bad_verdict):
        payload = {"verdict": bad_verdict, "suggested_pushback": None}
        with pytest.raises(SufficiencyCheckSchemaError):
            parse_sufficiency_response(json.dumps(payload))

    def test_raises_when_insufficient_has_no_suggested_pushback(self):
        payload = {"verdict": "insufficient", "suggested_pushback": None}
        with pytest.raises(SufficiencyCheckSchemaError):
            parse_sufficiency_response(json.dumps(payload))

    def test_raises_when_insufficient_has_a_blank_suggested_pushback(self):
        payload = {"verdict": "insufficient", "suggested_pushback": "   "}
        with pytest.raises(SufficiencyCheckSchemaError):
            parse_sufficiency_response(json.dumps(payload))

    def test_raises_when_suggested_pushback_is_the_wrong_type(self):
        payload = {"verdict": "insufficient", "suggested_pushback": 123}
        with pytest.raises(SufficiencyCheckSchemaError):
            parse_sufficiency_response(json.dumps(payload))


class TestRunSufficiencyCheck:
    def _kwargs(self) -> dict:
        return dict(ground_truth=_FULL_GROUND_TRUTH, analyst_message="I think the reorder point is fine.")

    def test_succeeds_on_the_first_call(self):
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_SUFFICIENCY_PAYLOAD))])

        verdict = run_sufficiency_check(client, **self._kwargs())

        assert verdict.verdict == "insufficient"
        assert len(client.call_log) == 1

    def test_the_full_ground_truth_package_reaches_the_prompt(self):
        client = MockClaudeClient(script=[ClaudeResponse(content=json.dumps(_VALID_SUFFICIENCY_PAYLOAD))])

        run_sufficiency_check(client, **self._kwargs())

        sent_prompt = client.call_log[0]["messages"][0]["content"]
        assert "SECRET-SIGNAL-lead-time-spike" in sent_prompt

    def test_retries_once_after_a_claude_api_error_then_succeeds(self):
        client = MockClaudeClient(
            script=[
                ClaudeAPIError("rate limited"),
                ClaudeResponse(content=json.dumps(_VALID_SUFFICIENCY_PAYLOAD)),
            ]
        )

        verdict = run_sufficiency_check(client, **self._kwargs())

        assert verdict.verdict == "insufficient"
        assert len(client.call_log) == 2

    def test_retries_once_after_malformed_output_then_succeeds(self):
        client = MockClaudeClient(
            script=[
                ClaudeResponse(content="not json"),
                ClaudeResponse(content=json.dumps(_VALID_SUFFICIENCY_PAYLOAD)),
            ]
        )

        verdict = run_sufficiency_check(client, **self._kwargs())

        assert len(client.call_log) == 2
        assert verdict.verdict == "insufficient"

    def test_raises_after_the_retry_is_also_exhausted(self):
        client = MockClaudeClient(
            script=[ClaudeAPIError("rate limited"), ClaudeAPIError("rate limited again")]
        )

        with pytest.raises(SufficiencyCheckFailedError):
            run_sufficiency_check(client, **self._kwargs())
        assert len(client.call_log) == 2

    def test_does_not_attempt_a_third_call(self):
        client = MockClaudeClient(
            script=[
                ClaudeAPIError("1"),
                ClaudeAPIError("2"),
                ClaudeResponse(content=json.dumps(_VALID_SUFFICIENCY_PAYLOAD)),
            ]
        )

        with pytest.raises(SufficiencyCheckFailedError):
            run_sufficiency_check(client, **self._kwargs())
        assert len(client.call_log) == 2
