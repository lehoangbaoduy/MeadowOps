"""Unit 25 (MEADOWOPS-DOM-019, PRD 6.7): pure domain-layer difficulty-tier
resolution over a competency cluster's recent Evaluation.difficulty_
recommendation history. No DB or session access - app.services.evaluation
is the one module that knows how to fetch that history and calls into
this module.
"""

from __future__ import annotations

from app.db.enums import DifficultyRecommendation

# PRD 6.7: "A tier change requires evidence across multiple relevant
# interactions, not one response" - 2 is the literal minimum satisfying
# "multiple" itself. No PRD-specified exact number, same "tunable, not
# guessed" style as Unit 24's Settings.stale_decision_after_days.
MINIMUM_OBSERVATIONS = 2


def resolve_cluster_tier(
    recent_recommendations: list[DifficultyRecommendation],
) -> DifficultyRecommendation:
    """`recent_recommendations` is ordered most-recent-first (the caller's
    query already orders by Evaluation.created_at desc) - this function
    evaluates exactly the sample it's given; it does not itself decide how
    many observations to fetch.

    Edge case #27 (progress doc, "Adaptive Difficulty & Evaluation"):
    fewer than MINIMUM_OBSERVATIONS data points -> HOLD, "insufficient
    evidence", never a forced guess.

    Edge case #28: the sampled observations disagree -> HOLD, a defined
    trend rule (unanimous agreement across the sample required), not ad
    hoc judgment. A recommendation of HOLD itself in the sample forces
    disagreement with any real tier by construction - no special-casing
    needed for it.
    """
    if len(recent_recommendations) < MINIMUM_OBSERVATIONS:
        return DifficultyRecommendation.HOLD
    sample = recent_recommendations[:MINIMUM_OBSERVATIONS]
    if len(set(sample)) != 1:
        return DifficultyRecommendation.HOLD
    return sample[0]
