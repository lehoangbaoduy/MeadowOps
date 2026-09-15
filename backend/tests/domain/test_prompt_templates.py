"""RED-first tests for prompt template skeletons (spec MEADOWOPS-INFRA-003,
PRD line 470: "Prompt template skeletons drafted (generation, stakeholder
roleplay, evaluation)").

These tests check the templates carry the content PRD 6.4/6.8/ER-1 actually
require - not just that a string exists - and that rendering is a real
substitution (missing context raises, full context leaves no placeholder
behind), per the "who mutates it and when" / vacuous-test lessons from
DD-14/DD-15 and Unit 10's KPI SQL semantic tests.
"""

from __future__ import annotations

import string

import pytest

from app.domain.prompt_templates import (
    ALL_TEMPLATES,
    EVALUATION_TEMPLATE,
    GENERATION_TEMPLATE,
    STAKEHOLDER_ROLEPLAY_TEMPLATE,
    SUFFICIENCY_CHECK_TEMPLATE,
    PromptRenderError,
)


def _placeholders_in(template_text: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template_text)
        if field_name
    }


class TestTemplateRegistry:
    def test_exactly_five_templates_are_registered(self):
        # Three from PRD line 470's original skeleton set, plus
        # sufficiency_check (Unit 23, PRD 6.13 - not part of that original
        # three-way list since 6.13's own sufficiency check post-dates it),
        # plus stakeholder_opening (Unit 35, follow-on to Unit 23 - a
        # sibling to stakeholder_roleplay, not an edit to it).
        assert len(ALL_TEMPLATES) == 5

    def test_registered_templates_match_the_prd_use_cases(self):
        names = {t.name for t in ALL_TEMPLATES}
        assert names == {
            "scenario_generation",
            "stakeholder_roleplay",
            "stakeholder_opening",
            "sufficiency_check",
            "draft_evaluation",
        }

    def test_every_template_has_a_version(self):
        for template in ALL_TEMPLATES:
            assert template.version

    def test_name_version_pairs_are_unique(self):
        keys = [(t.name, t.version) for t in ALL_TEMPLATES]
        assert len(keys) == len(set(keys))

    @pytest.mark.parametrize("template", ALL_TEMPLATES, ids=lambda t: t.name)
    def test_template_placeholders_exactly_match_required_context(self, template):
        assert _placeholders_in(template.template) == template.required_context


class TestGenerationTemplate:
    CONTEXT = {
        "scenario_type": "inventory_discrepancy",
        "difficulty_tier": "2",
        "competency_cluster": "diagnostic_reasoning",
        "evidence_package": "product P-001 at warehouse W-01: on_hand=40",
    }

    def test_renders_with_full_context_and_leaves_no_placeholder(self):
        rendered = GENERATION_TEMPLATE.render(self.CONTEXT)
        for key in GENERATION_TEMPLATE.required_context:
            assert "{" + key + "}" not in rendered

    def test_rendered_output_includes_the_supplied_context_values(self):
        rendered = GENERATION_TEMPLATE.render(self.CONTEXT)
        assert "inventory_discrepancy" in rendered
        assert "product P-001 at warehouse W-01: on_hand=40" in rendered

    def test_missing_required_context_raises_prompt_render_error(self):
        incomplete = dict(self.CONTEXT)
        del incomplete["evidence_package"]
        with pytest.raises(PromptRenderError):
            GENERATION_TEMPLATE.render(incomplete)

    def test_instructs_against_fabricating_level_1_or_level_2_facts(self):
        text = GENERATION_TEMPLATE.template
        assert "fabricated" in text.lower()
        assert "Level 1" in text
        assert "Level 2" in text


class TestStakeholderRoleplayTemplate:
    CONTEXT = {
        "persona_name": "Procurement Manager",
        "persona_priorities": "price, supplier reliability, lead time",
        "persona_style": "cost-focused, comparative",
        "known_information": "supplier S-005 lead time is 12 days",
        "conversation_history": "Analyst: what's the lead time on S-005?",
        "analyst_message": "Can we expedite the next order?",
    }

    def test_renders_with_full_context_and_leaves_no_placeholder(self):
        rendered = STAKEHOLDER_ROLEPLAY_TEMPLATE.render(self.CONTEXT)
        for key in STAKEHOLDER_ROLEPLAY_TEMPLATE.required_context:
            assert "{" + key + "}" not in rendered

    def test_is_parameterized_by_persona_not_hardcoded_to_one(self):
        cfo_context = dict(self.CONTEXT)
        cfo_context.update(
            persona_name="CFO",
            persona_priorities="financial impact, cost, risk",
            persona_style="concise, financially oriented",
        )
        procurement_rendered = STAKEHOLDER_ROLEPLAY_TEMPLATE.render(self.CONTEXT)
        cfo_rendered = STAKEHOLDER_ROLEPLAY_TEMPLATE.render(cfo_context)
        assert procurement_rendered != cfo_rendered
        assert "CFO" in cfo_rendered
        assert "Procurement Manager" in procurement_rendered

    def test_missing_required_context_raises_prompt_render_error(self):
        incomplete = dict(self.CONTEXT)
        del incomplete["known_information"]
        with pytest.raises(PromptRenderError):
            STAKEHOLDER_ROLEPLAY_TEMPLATE.render(incomplete)


class TestSufficiencyCheckTemplate:
    CONTEXT = {
        "ground_truth_package": "Known cause: reorder point misconfigured",
        "analyst_message": "It looks like the reorder point is too low, can we raise it?",
    }

    def test_renders_with_full_context_and_leaves_no_placeholder(self):
        rendered = SUFFICIENCY_CHECK_TEMPLATE.render(self.CONTEXT)
        for key in SUFFICIENCY_CHECK_TEMPLATE.required_context:
            assert "{" + key + "}" not in rendered

    def test_rendered_output_includes_the_supplied_context_values(self):
        rendered = SUFFICIENCY_CHECK_TEMPLATE.render(self.CONTEXT)
        assert "reorder point misconfigured" in rendered
        assert "can we raise it?" in rendered

    def test_missing_required_context_raises_prompt_render_error(self):
        incomplete = dict(self.CONTEXT)
        del incomplete["analyst_message"]
        with pytest.raises(PromptRenderError):
            SUFFICIENCY_CHECK_TEMPLATE.render(incomplete)

    def test_instructs_a_json_only_response_naming_both_keys(self):
        text = SUFFICIENCY_CHECK_TEMPLATE.template
        assert "JSON" in text
        assert '"verdict"' in text
        assert '"suggested_pushback"' in text
        assert "sufficient" in text
        assert "insufficient" in text

    def test_is_labeled_a_recommendation_only_distinct_from_a_final_evaluation(self):
        # PRD 6.13: "This is a recommendation only... distinct from the
        # post-submission Draft AI evaluation (6.8)."
        assert "recommendation only" in SUFFICIENCY_CHECK_TEMPLATE.template

    def test_instructs_suggested_pushback_to_avoid_stating_ground_truth_facts_directly(self):
        # Security review of this unit: suggested_pushback is generated with
        # the *full*, unredacted ground truth in context and is meant to
        # seed a message a Builder may paste straight into the Analyst-
        # visible thread (PRD 6.6 step 5) - without an explicit instruction,
        # an honest model answer could naturally cite a specific grading-only
        # fact (a supporting signal, distractor, expected consideration, or
        # conclusion) in its suggested nudge text.
        assert "Never state a specific ground-truth fact" in SUFFICIENCY_CHECK_TEMPLATE.template


class TestEvaluationTemplate:
    CONTEXT = {
        "ground_truth_package": "Known cause: reorder point misconfigured",
        "evidence_package": "product P-001 at warehouse W-01: on_hand=40",
        "stakeholder_context": "Warehouse Manager flagged workload concern",
        "expected_cluster_behaviors": "diagnostic_reasoning: identify root cause",
        "analyst_responses": "Analyst proposed raising the reorder point",
        "outcome": "Correct root cause identified, remediation proposed",
    }

    def test_renders_with_full_context_and_leaves_no_placeholder(self):
        rendered = EVALUATION_TEMPLATE.render(self.CONTEXT)
        for key in EVALUATION_TEMPLATE.required_context:
            assert "{" + key + "}" not in rendered

    def test_missing_required_context_raises_prompt_render_error(self):
        incomplete = dict(self.CONTEXT)
        del incomplete["outcome"]
        with pytest.raises(PromptRenderError):
            EVALUATION_TEMPLATE.render(incomplete)

    def test_is_labeled_draft_not_authoritative_per_er_1(self):
        text = EVALUATION_TEMPLATE.template
        assert "DRAFT" in text
        assert "NOT AUTHORITATIVE" in text

    @pytest.mark.parametrize(
        "required_section",
        [
            "Strengths",
            "Gaps",
            "Evidence",
            "Senior Analyst Pushback",
            "Final Verdict",
            "Suggested Next Skill Focus",
            "Difficulty Recommendation",
        ],
    )
    def test_requests_every_section_required_by_prd_6_8(self, required_section):
        assert required_section in EVALUATION_TEMPLATE.template

    def test_instructs_that_no_single_number_is_the_sole_representation(self):
        assert "No single number" in EVALUATION_TEMPLATE.template
