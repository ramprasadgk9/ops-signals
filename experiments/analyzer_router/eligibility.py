from __future__ import annotations

from dataclasses import dataclass

from .analyzer_registry import AnalyzerCapability
from .models import SeriesProfile, ValidationDecision


# The data every change-detecting analyzer needs. Data Health opts out of the missing-data limit,
# so it can report the gaps; everything else is ruled out below either one.
MAX_MISSING_PERCENTAGE = 30.0
MIN_VALID_SAMPLES = 30


def too_little_data_to_check(missing_percentage: float | None, valid_sample_count: int | None) -> bool:
    """True when a series fails the limits below for every analyzer that looks for changes."""
    return float(missing_percentage or 0.0) > MAX_MISSING_PERCENTAGE or int(valid_sample_count or 0) < MIN_VALID_SAMPLES


@dataclass(slots=True)
class EligibilityResult:
    eligible: bool
    eligibility_score: float
    reasons: list[str]
    warnings: list[str]


def evaluate_eligibility(capability: AnalyzerCapability, profile: SeriesProfile) -> EligibilityResult:
    rules = capability.eligibility_rules
    reasons: list[str] = []
    warnings: list[str] = []
    score = 1.0

    min_samples = int(rules.get("min_samples", 0) or 0)
    if min_samples and profile.valid_sample_count < min_samples:
        return EligibilityResult(False, 0.0, [f"Needs at least {min_samples} valid samples."], warnings)
    if min_samples:
        reasons.append(f"Has {profile.valid_sample_count} valid samples, which meets the minimum of {min_samples}.")

    if rules.get("requires_regular_sampling") and not profile.regular_sampling:
        return EligibilityResult(False, 0.2, ["Regular sampling is required for this analyzer."], ["Sampling is irregular."])
    if rules.get("requires_regular_sampling"):
        reasons.append("Sampling is regular enough for this analyzer.")

    if rules.get("requires_timestamp") and profile.duration_seconds is None:
        return EligibilityResult(False, 0.0, ["A usable timestamp column is required."], warnings)

    if rules.get("requires_numeric") and profile.valid_sample_count <= 0:
        return EligibilityResult(False, 0.0, ["No valid numeric observations remain."], warnings)

    # A data-health style analyzer exists to report exactly the flat, gappy or zero-variance
    # series the checks below reject for everyone else - it opts out of those three.
    accepts_flat_or_gappy = bool(rules.get("accepts_flat_or_gappy_series"))

    if profile.constant_value_percentage >= 95.0 and not accepts_flat_or_gappy:
        return EligibilityResult(False, 0.0, ["The series is effectively constant."], ["Constant signal detected."])

    if profile.missing_percentage > MAX_MISSING_PERCENTAGE and not accepts_flat_or_gappy:
        return EligibilityResult(False, 0.0, ["Missing or invalid values exceed the rejection threshold."], ["High missingness."])

    if profile.valid_sample_count < MIN_VALID_SAMPLES:
        return EligibilityResult(False, 0.0, [f"Fewer than {MIN_VALID_SAMPLES} valid samples remain after cleaning."], warnings)

    if profile.irregular_sampling_percentage > 40 and rules.get("requires_regular_sampling"):
        return EligibilityResult(False, 0.0, ["The series is too irregular for this analyzer."], ["Irregular sampling exceeds threshold."])

    if profile.stddev == 0 and not accepts_flat_or_gappy:
        return EligibilityResult(False, 0.0, ["The signal has no variance."], warnings)

    if profile.variance < float(rules.get("min_variance", 0.0) or 0.0):
        score = 0.7
        warnings.append("Variance is low; the analyzer may be technically eligible but not highly informative.")

    return EligibilityResult(True, score, reasons or ["The series meets the technical requirements."], warnings)
