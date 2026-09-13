from app.db.enums import DifficultyRecommendation
from app.domain.difficulty_engine import MINIMUM_OBSERVATIONS, resolve_cluster_tier

FOUNDATIONAL = DifficultyRecommendation.FOUNDATIONAL
STANDARD = DifficultyRecommendation.STANDARD
STRETCH = DifficultyRecommendation.STRETCH
HOLD = DifficultyRecommendation.HOLD


class TestResolveClusterTier:
    def test_no_observations_holds_for_insufficient_evidence(self) -> None:
        assert resolve_cluster_tier([]) == HOLD

    def test_one_observation_holds_for_insufficient_evidence(self) -> None:
        # Edge case #27: "multiple relevant interactions, not one response".
        assert resolve_cluster_tier([STANDARD]) == HOLD

    def test_minimum_observations_constant_is_two(self) -> None:
        assert MINIMUM_OBSERVATIONS == 2

    def test_two_agreeing_observations_resolve_to_that_tier(self) -> None:
        assert resolve_cluster_tier([STANDARD, STANDARD]) == STANDARD

    def test_two_conflicting_observations_hold(self) -> None:
        # Edge case #28: a defined trend rule (unanimous agreement), not ad
        # hoc judgment.
        assert resolve_cluster_tier([STANDARD, FOUNDATIONAL]) == HOLD

    def test_only_the_most_recent_sample_is_considered(self) -> None:
        # Ordered most-recent-first - a third, older, disagreeing
        # observation must not affect the two-observation resolution.
        assert resolve_cluster_tier([STRETCH, STRETCH, FOUNDATIONAL]) == STRETCH

    def test_a_stale_disagreement_still_holds_when_the_recent_sample_disagrees(self) -> None:
        assert resolve_cluster_tier([STRETCH, STANDARD, STANDARD]) == HOLD

    def test_a_hold_in_the_sample_forces_disagreement(self) -> None:
        assert resolve_cluster_tier([STANDARD, HOLD]) == HOLD

    def test_two_agreeing_holds_resolve_to_hold(self) -> None:
        assert resolve_cluster_tier([HOLD, HOLD]) == HOLD
