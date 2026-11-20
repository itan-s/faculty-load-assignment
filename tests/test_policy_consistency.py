# tests/test_policy_consistency.py
from __future__ import annotations

from tests.policy_eval_helper import run_policy_eval


def test_policy_consistency_on_synthetic_data():
    """
    End-to-end check on synthetic Excel data under data/raw.

    - Uses real OR-Tools faculty assignment and room solver.
    - Uses real deterministic validate_plan and compute_metrics.
    """

    metrics = run_policy_eval(constraints_path="data/processed/constraints.json")

    coverage = metrics.num_sections_assigned / max(1, metrics.num_sections)
    # We require high coverage on this scenario
    assert coverage >= 0.9, f"Coverage too low: {coverage:.1%}"

    # Everything else we treat as **reported metrics**, not hard assertions.
    print("\n=== Policy consistency metrics on synthetic data ===")
    for k, v in metrics.to_dict().items():
        print(f"{k}: {v}")
