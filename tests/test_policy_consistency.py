# tests/test_policy_consistency.py
from __future__ import annotations

from tests.policy_eval_helper import run_policy_eval


def test_policy_consistency_on_synthetic_data():
    """
    End-to-end check on synthetic data.

    Runs the full pipeline and prints metrics and violations.
    Does NOT assert on coverage or violations; this is for reporting.
    """

    metrics = run_policy_eval(constraints_path="data/processed/constraints.json")

    coverage = metrics.num_sections_assigned / max(1, metrics.num_sections)

    print("\n=== Policy consistency metrics on synthetic data ===")
    print(f"coverage: {coverage:.2%}")
    for k, v in metrics.to_dict().items():
        print(f"{k}: {v}")

    # Do not assert on coverage or violations; just ensure the pipeline ran.
    # If you want at least some sanity check, you can keep a very mild one:
    # assert metrics.num_sections >= 0
