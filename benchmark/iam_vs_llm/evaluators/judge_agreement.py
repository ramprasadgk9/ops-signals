from __future__ import annotations

from typing import Sequence


def calculate_fleiss_kappa(ratings: list[list[int]], num_categories: int = 5) -> float:
    """Calculates Fleiss' kappa for inter-rater agreement across multiple raters.
    
    Args:
        ratings: List of subjects, where each subject is a list of ratings from n raters.
                 Values should be integers between 1 and num_categories (or 0 and num_categories - 1).
        num_categories: The number of rating categories (default 5 for 1-5 Likert scale).
        
    Returns:
        Fleiss' kappa score between -1.0 and 1.0 (1.0 = perfect agreement).
    """
    if not ratings:
        return 1.0

    num_subjects = len(ratings)
    num_raters = len(ratings[0])
    if num_raters <= 1 or num_subjects == 0:
        return 1.0

    # Detect if categories are 1-indexed (e.g. 1..5) or 0-indexed (e.g. 0..4)
    min_val = min(min(row) for row in ratings)
    offset = min_val if min_val == 0 else 1

    # Build N x k count matrix where cell [i][j] is the number of raters who gave category j to subject i
    counts: list[list[int]] = [[0] * num_categories for _ in range(num_subjects)]
    for i, row in enumerate(ratings):
        for val in row:
            cat_idx = val - offset
            if 0 <= cat_idx < num_categories:
                counts[i][cat_idx] += 1

    total_assignments = num_subjects * num_raters

    # p_j: proportion of all assignments to category j
    p_j = [0.0] * num_categories
    for j in range(num_categories):
        p_j[j] = sum(counts[i][j] for i in range(num_subjects)) / total_assignments

    # P_i: degree of agreement for subject i
    p_i = [0.0] * num_subjects
    denom = num_raters * (num_raters - 1)
    for i in range(num_subjects):
        sum_sq = sum(counts[i][j] * (counts[i][j] - 1) for j in range(num_categories))
        p_i[i] = sum_sq / denom

    p_bar = sum(p_i) / num_subjects
    p_e = sum(pj ** 2 for pj in p_j)

    if abs(1.0 - p_e) < 1e-9:
        return 1.0

    kappa = (p_bar - p_e) / (1.0 - p_e)
    return round(float(kappa), 4)


def calculate_krippendorff_alpha(
    ratings: list[list[float | None]],
    level_of_measurement: str = "ordinal",
) -> float:
    """Calculates Krippendorff's alpha reliability coefficient supporting missing data.
    
    Args:
        ratings: Matrix of shape (num_subjects, num_raters), where each row corresponds
                 to a subject and columns correspond to raters. Entries can be None to
                 signify missing ratings.
        level_of_measurement: One of 'nominal', 'ordinal', 'interval'. Default is 'ordinal'.
        
    Returns:
        Krippendorff's alpha score between -1.0 and 1.0 (1.0 = perfect reliability).
    """
    if not ratings:
        return 1.0

    # Ensure ratings are structured as subjects x raters
    # Filter subjects with at least 2 non-None ratings
    valid_subjects: list[list[float]] = []
    for row in ratings:
        cleaned = [r for r in row if r is not None]
        if len(cleaned) >= 2:
            valid_subjects.append(cleaned)

    if not valid_subjects:
        return 1.0

    # Collect all unique values and their global marginal frequencies
    all_values: list[float] = [val for row in valid_subjects for val in row]
    unique_vals = sorted(list(set(all_values)))
    v_to_idx = {v: idx for idx, v in enumerate(unique_vals)}
    num_vals = len(unique_vals)

    if num_vals <= 1:
        return 1.0

    # Marginal counts val_frequencies
    val_frequencies = [0] * num_vals
    for v in all_values:
        val_frequencies[v_to_idx[v]] += 1

    total_observations = sum(val_frequencies)
    if total_observations <= 1:
        return 1.0

    # Distance function delta^2(v, v')
    def diff_sq(v1: float, v2: float) -> float:
        if level_of_measurement == "nominal":
            return 0.0 if v1 == v2 else 1.0
        elif level_of_measurement == "interval":
            return (v1 - v2) ** 2
        elif level_of_measurement == "ordinal":
            idx1 = v_to_idx[v1]
            idx2 = v_to_idx[v2]
            rank_low, rank_high = min(idx1, idx2), max(idx1, idx2)
            if rank_low == rank_high:
                return 0.0
            sum_between = sum(val_frequencies[k] for k in range(rank_low, rank_high + 1))
            delta = sum_between - (val_frequencies[rank_low] + val_frequencies[rank_high]) / 2.0
            return delta ** 2
        else:
            return (v1 - v2) ** 2

    # Observed disagreement D_o
    d_o_sum = 0.0

    for row in valid_subjects:
        raters_count = len(row)
        if raters_count < 2:
            continue
        # Count frequency of each value in this subject
        subj_counts: dict[float, int] = {}
        for val in row:
            subj_counts[val] = subj_counts.get(val, 0) + 1

        row_diff = 0.0
        keys = list(subj_counts.keys())
        for i in range(len(keys)):
            val_a = keys[i]
            count_a = subj_counts[val_a]
            for j in range(i + 1, len(keys)):
                val_b = keys[j]
                count_b = subj_counts[val_b]
                row_diff += count_a * count_b * diff_sq(val_a, val_b)

        d_o_sum += row_diff / (raters_count - 1)

    d_o = (2.0 * d_o_sum) / total_observations if total_observations > 0 else 0.0

    # Expected disagreement D_e
    d_e_sum = 0.0
    for i in range(num_vals):
        val_a = unique_vals[i]
        count_a = val_frequencies[i]
        for j in range(i + 1, num_vals):
            val_b = unique_vals[j]
            count_b = val_frequencies[j]
            d_e_sum += count_a * count_b * diff_sq(val_a, val_b)

    d_e = (2.0 * d_e_sum) / (total_observations * (total_observations - 1)) if total_observations > 1 else 0.0

    if d_e == 0.0:
        return 1.0

    alpha = 1.0 - (d_o / d_e)
    return round(float(alpha), 4)
