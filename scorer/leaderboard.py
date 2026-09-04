"""
Ranks multiple agents against each other on the same ReconArena datasets --
the actual "Arena" part of ReconArena.

A benchmark that only ever scores one agent can't prove it discriminates
between agent quality; it can only prove the task is solvable at all.
This module runs the full three-tier score_tier() comparison for however
many agents are registered and produces a single ranked leaderboard, plus
per-tier breakdowns, so the difference in capability is the headline
number rather than something buried in a report.

Usage:
    python3 -m scorer.leaderboard --datasets-dir datasets
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scorer.score import score_tier

TIERS = ["easy", "medium", "hard"]

# Registered agents: (display name, output filename per tier dir, one-line description)
AGENTS = [
    {
        "id": "smart",
        "name": "Rule-based reference agent",
        "output_file": "agent_output_smart.json",
        "description": "Fallback UTR matching + textbook tax/fee recomputation "
                        "(baseline_agent/agent.py).",
    },
    {
        "id": "naive",
        "name": "Naive exact-match agent",
        "output_file": "agent_output_naive.json",
        "description": "Exact UTR string match only, no fallback, no recomputation "
                        "(baseline_agent/naive_agent.py) -- models what a lot of "
                        "real unsophisticated systems still run.",
    },
]


def _overall_score(tier_results: dict) -> float | None:
    """A single aggregate score per agent: mean of matching F1 and issue-detection
    F1 across tiers, weighted by tier record count. None components are treated
    as 0 (an agent that can't attempt issue detection at all shouldn't average
    that away)."""
    weighted_sum, weight_total = 0.0, 0
    for tier in TIERS:
        r = tier_results[tier]
        n = r["n_records"]
        match_f1 = r["matching"]["f1"] or 0.0
        issue_f1 = r["issue_detection"]["f1"] or 0.0
        tier_score = (match_f1 + issue_f1) / 2
        weighted_sum += tier_score * n
        weight_total += n
    return round(weighted_sum / weight_total, 4) if weight_total else None


def run_leaderboard(datasets_dir: Path) -> dict:
    board = []
    per_agent_tier_results = {}
    for agent in AGENTS:
        tier_results = {}
        missing = False
        for tier in TIERS:
            out_path = datasets_dir / tier / agent["output_file"]
            if not out_path.exists():
                missing = True
                break
            tier_results[tier] = score_tier(datasets_dir / tier, out_path)
        if missing:
            continue
        per_agent_tier_results[agent["id"]] = tier_results
        board.append({
            "id": agent["id"],
            "name": agent["name"],
            "description": agent["description"],
            "overall_score": _overall_score(tier_results),
            "tiers": tier_results,
        })

    board.sort(key=lambda a: a["overall_score"] or 0, reverse=True)
    for rank, entry in enumerate(board, start=1):
        entry["rank"] = rank
    return {"agents": board}


def main():
    parser = argparse.ArgumentParser(description="Rank all registered ReconArena agents")
    parser.add_argument("--datasets-dir", type=str, default="datasets")
    args = parser.parse_args()

    result = run_leaderboard(Path(args.datasets_dir))
    for entry in result["agents"]:
        print(f"#{entry['rank']} {entry['name']} -- overall score {entry['overall_score']}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
