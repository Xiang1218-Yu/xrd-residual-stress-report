"""Trusted post-pytest scorer for the XRD task.

This file is invoked after pytest exits from a verifier-private virtualenv.
It accepts only a complete JUnit report for the known test inventory and
performs the sole final write to the Harbor reward file.
"""
from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Behaviour groups are intentionally unequal: physical fitting and safety
# decisions carry more weight than duplicate tie-break formatting details.
GROUPS: dict[str, tuple[float, tuple[str, ...]]] = {
    "physical_fit": (
        0.35,
        (
            "test_positive_zero_correction",
            "test_negative_zero_correction",
            "test_directions_are_fitted_separately",
            "test_worst_direction_summary",
            "test_near_zero_tilt_variation_requires_review",
        ),
    ),
    "classification_and_limits": (
        0.25,
        (
            "test_tensile_classification",
            "test_compressive_classification",
            "test_limit_boundary_passes",
            "test_limit_exceedance_rejects",
            "test_tensile_boundary_does_not_mask_compressive_exceedance",
        ),
    ),
    "measurement_screening_and_dedup": (
        0.22,
        (
            "test_low_quality_is_excluded",
            "test_duplicate_keeps_higher_quality",
            "test_duplicate_result_is_order_invariant",
            "test_equal_quality_duplicate_tie_is_stable",
            "test_invalid_measurements_are_reported",
        ),
    ),
    "review_and_failure_side_effects": (
        0.18,
        (
            "test_insufficient_points_requires_review",
            "test_invalid_limits_are_rejected_without_side_effects",
        ),
    ),
}
EXPECTED = {test for _, tests in GROUPS.values() for test in tests}


def atomic_write(path: Path, content: str) -> None:
    """Replace the protected reward with a complete, mode-600 file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".reward.", dir=path.parent, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def fail_closed(reward_file: Path) -> int:
    atomic_write(reward_file, "0.000\n")
    return 1


def testcase_name(case: ET.Element) -> str:
    # The task has no parameterized cases.  A parameter suffix therefore means
    # a runner/test inventory mismatch and must not receive a score.
    name = case.attrib.get("name", "")
    return name if name in EXPECTED else ""


def score() -> float | None:
    if os.environ.get("PYTEST_STATUS") not in {"0", "1"}:
        return None
    report = Path(os.environ["RESULT_XML"])
    if not report.is_file():
        return None
    try:
        root = ET.parse(report).getroot()
    except (ET.ParseError, OSError):
        return None

    outcomes: dict[str, bool] = {}
    for case in root.iter("testcase"):
        name = testcase_name(case)
        if not name or name in outcomes:
            return None
        # A skipped/error/failure node is not a passed behavioural test.
        outcomes[name] = not any(child.tag in {"failure", "error", "skipped"} for child in case)

    if set(outcomes) != EXPECTED:
        return None
    return sum(weight * (sum(outcomes[name] for name in tests) / len(tests)) for weight, tests in GROUPS.values())


def main() -> int:
    try:
        reward_file = Path(os.environ["REWARD_FILE"])
        value = score()
        if value is None:
            return fail_closed(reward_file)
        atomic_write(reward_file, f"{value:.3f}\n")
        return 0
    except (KeyError, OSError, ValueError):
        # Do not preserve a reward from any earlier process on scorer failure.
        reward = Path(os.environ.get("REWARD_FILE", "/logs/verifier/reward.txt"))
        return fail_closed(reward)


if __name__ == "__main__":
    raise SystemExit(main())
