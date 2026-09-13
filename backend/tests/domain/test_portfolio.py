"""Unit 26 (MEADOWOPS-DOM-020, PRD 6.10): pure-assembly tests for the
compiled portfolio export document. No DB access - see app.domain.
portfolio's own docstring for why this is testable without one."""

from __future__ import annotations

from app.domain.portfolio import build_portfolio_export

_MESSAGES = [
    {"sender_role": "admin", "body": "East's service is getting worse.", "sent_at": "2026-06-01T10:00:00Z"},
    {"sender_role": "analyst", "body": "Investigating now.", "sent_at": "2026-06-01T11:00:00Z"},
]

_EVALUATION = {
    "id": "eval-1",
    "strengths": "Correctly identified the reorder point issue.",
    "difficulty_recommendation": "standard",
}


class TestBuildPortfolioExport:
    def _export(self, **overrides) -> dict:
        kwargs = {
            "scenario_title": "East service decline",
            "scenario_type": "root_cause_investigation",
            "competency_cluster": "analysis_diagnosis",
            "messages": _MESSAGES,
            "evaluation": _EVALUATION,
            "human_review": None,
            "reflection": None,
        }
        kwargs.update(overrides)
        return build_portfolio_export(**kwargs)

    def test_trigger_is_the_first_messages_body(self) -> None:
        export = self._export()
        assert export["trigger"] == "East's service is getting worse."

    def test_trigger_is_none_when_there_are_no_messages(self) -> None:
        export = self._export(messages=[])
        assert export["trigger"] is None

    def test_includes_the_scenario_summary(self) -> None:
        export = self._export()
        assert export["scenario"] == {
            "title": "East service decline",
            "scenario_type": "root_cause_investigation",
            "competency_cluster": "analysis_diagnosis",
        }

    def test_includes_every_message_in_order(self) -> None:
        export = self._export()
        assert export["messages"] == _MESSAGES

    def test_includes_the_evaluation_verbatim(self) -> None:
        export = self._export()
        assert export["evaluation"] == _EVALUATION

    def test_human_review_and_reflection_default_to_none(self) -> None:
        export = self._export()
        assert export["human_review"] is None
        assert export["reflection"] is None

    def test_human_review_and_reflection_pass_through_when_present(self) -> None:
        review = {"verdict": "override"}
        reflection = {"reflection_what_happened": "text"}
        export = self._export(human_review=review, reflection=reflection)
        assert export["human_review"] == review
        assert export["reflection"] == reflection
