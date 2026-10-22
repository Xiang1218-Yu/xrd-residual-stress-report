import os
from pathlib import Path

WEIGHTS = {
    "test_positive_zero_correction": 0.05,
    "test_negative_zero_correction": 0.07,
    "test_tensile_classification": 0.05,
    "test_compressive_classification": 0.07,
    "test_directions_are_fitted_separately": 0.08,
    "test_worst_direction_summary": 0.05,
    "test_low_quality_is_excluded": 0.07,
    "test_duplicate_keeps_higher_quality": 0.07,
    "test_duplicate_result_is_order_invariant": 0.05,
    "test_invalid_measurements_are_reported": 0.07,
    "test_insufficient_points_requires_review": 0.07,
    "test_equal_quality_duplicate_tie_is_stable": 0.05,
    "test_limit_boundary_passes": 0.04,
    "test_limit_exceedance_rejects": 0.04,
    "test_tensile_boundary_does_not_mask_compressive_exceedance": 0.04,
    "test_near_zero_tilt_variation_requires_review": 0.05,
    "test_invalid_limits_are_rejected_without_side_effects": 0.08,
}
PASSED = set()


def pytest_runtest_logreport(report):
    if report.when == "call" and report.outcome == "passed":
        PASSED.add(report.nodeid.rsplit("::", 1)[-1])


def pytest_sessionfinish(session, exitstatus):
    reward_file = Path(os.environ.get("REWARD_FILE", "/logs/verifier/reward.txt"))
    reward_file.parent.mkdir(parents=True, exist_ok=True)
    if exitstatus in (2, 3, 4, 5) or not session.testscollected:
        score = 0.0
    else:
        score = sum(weight for name, weight in WEIGHTS.items() if name in PASSED)
    reward_file.write_text(f"{score:.3f}\n", encoding="utf-8")
