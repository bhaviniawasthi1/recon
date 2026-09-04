"""
Converts ReconArena's precision/recall metrics into a rupee number --
"how much money was at stake, and how much did each agent actually catch."

Accuracy percentages are easy to skim past; a rupee figure is not. This
module computes, per tier and in aggregate:
  - total gross transaction value in the tier
  - amount "at risk" -- gross value of transactions carrying a real
    (non-clean, non-red-herring) injected issue
  - amount an agent actually caught -- gross value of at-risk transactions
    the agent correctly flagged (matched_flagged with the right cause)
  - amount an agent missed -- the rest

Usage:
    python3 -m scorer.impact --datasets-dir datasets --agent-output-file agent_output_smart.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TIERS = ["easy", "medium", "hard"]


def compute_tier_impact(tier_dir: Path, agent_output_file: str) -> dict:
    transactions = {t["payment_id"]: t for t in json.loads((tier_dir / "transactions.json").read_text())}
    ground_truth = json.loads((tier_dir / "ground_truth.json").read_text())
    agent_output = {a["payment_id"]: a for a in json.loads((tier_dir / agent_output_file).read_text())}

    at_risk_total = 0.0
    caught_total = 0.0
    missed_total = 0.0
    n_at_risk = 0

    for g in ground_truth:
        has_real_issue = g["issue_type"] != "clean" and g["expected_match"]
        if not has_real_issue:
            continue
        n_at_risk += 1
        amount = transactions[g["payment_id"]]["amount"]
        at_risk_total += amount

        agent = agent_output.get(g["payment_id"])
        caught = bool(agent) and agent["verdict"] == "matched_flagged"
        if caught:
            caught_total += amount
        else:
            missed_total += amount

    return {
        "n_at_risk": n_at_risk,
        "at_risk_inr": round(at_risk_total, 2),
        "caught_inr": round(caught_total, 2),
        "missed_inr": round(missed_total, 2),
        "caught_pct": round(caught_total / at_risk_total, 4) if at_risk_total else None,
    }


def compute_all(datasets_dir: Path, agent_output_file: str) -> dict:
    per_tier = {tier: compute_tier_impact(datasets_dir / tier, agent_output_file) for tier in TIERS}
    total_at_risk = sum(t["at_risk_inr"] for t in per_tier.values())
    total_caught = sum(t["caught_inr"] for t in per_tier.values())
    total_missed = sum(t["missed_inr"] for t in per_tier.values())
    return {
        "per_tier": per_tier,
        "overall": {
            "at_risk_inr": round(total_at_risk, 2),
            "caught_inr": round(total_caught, 2),
            "missed_inr": round(total_missed, 2),
            "caught_pct": round(total_caught / total_at_risk, 4) if total_at_risk else None,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Compute ReconArena's rupee-value impact for one agent")
    parser.add_argument("--datasets-dir", type=str, default="datasets")
    parser.add_argument("--agent-output-file", type=str, default="agent_output_smart.json")
    args = parser.parse_args()

    result = compute_all(Path(args.datasets_dir), args.agent_output_file)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
