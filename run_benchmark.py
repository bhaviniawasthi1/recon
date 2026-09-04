#!/usr/bin/env python3
"""
End-to-end ReconArena pipeline:

    generate datasets -> run all registered agents -> score each ->
    rank on the leaderboard -> compute rupee-value impact -> render report

Usage:
    python3 run_benchmark.py [--seed 42] [--datasets-dir datasets] [--out report.html]
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path
import json

from generator.generate_dataset import write_tier, TIER_SEED_OFFSET
from baseline_agent.agent import run_agent as run_smart_agent
from baseline_agent.naive_agent import run_agent as run_naive_agent
from scorer.report import render_html, TIERS
from scorer.score import score_tier
from scorer.leaderboard import run_leaderboard, AGENTS
from scorer.impact import compute_all


def main():
    parser = argparse.ArgumentParser(description="Run the full ReconArena pipeline")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--datasets-dir", type=str, default="datasets")
    parser.add_argument("--out", type=str, default="report.html")
    args = parser.parse_args()

    datasets_dir = Path(args.datasets_dir)

    print("== 1/5: generating datasets ==")
    for tier in TIERS:
        rng = random.Random(args.seed + TIER_SEED_OFFSET[tier])
        write_tier(tier, datasets_dir, rng)

    print("== 2/5: running agents ==")
    for tier in TIERS:
        tier_dir = datasets_dir / tier
        smart_output = run_smart_agent(tier_dir)
        (tier_dir / "agent_output_smart.json").write_text(json.dumps(smart_output, indent=2))
        naive_output = run_naive_agent(tier_dir)
        (tier_dir / "agent_output_naive.json").write_text(json.dumps(naive_output, indent=2))
        print(f"  [{tier}] {len(smart_output)} smart verdicts, {len(naive_output)} naive verdicts")

    print("== 3/5: leaderboard ==")
    leaderboard = run_leaderboard(datasets_dir)
    (datasets_dir / "leaderboard.json").write_text(json.dumps(leaderboard, indent=2))
    for entry in leaderboard["agents"]:
        print(f"  #{entry['rank']} {entry['name']} -- overall score {entry['overall_score']}")

    print("== 4/5: rupee-value impact ==")
    impact_by_agent = {}
    for agent in AGENTS:
        impact_by_agent[agent["id"]] = compute_all(datasets_dir, agent["output_file"])
        overall = impact_by_agent[agent["id"]]["overall"]
        pct = overall["caught_pct"]
        print(f"  [{agent['id']}] at-risk INR {overall['at_risk_inr']:,.0f}, "
              f"caught {pct*100:.1f}%" if pct is not None else f"  [{agent['id']}] no at-risk records")
    (datasets_dir / "impact.json").write_text(json.dumps(impact_by_agent, indent=2))

    print("== 5/5: scoring + rendering report (smart agent) ==")
    results = {tier: score_tier(datasets_dir / tier) for tier in TIERS}
    html = render_html(results)
    Path(args.out).write_text(html)
    print(f"wrote report -> {args.out}")

    for tier in TIERS:
        i = results[tier]["issue_detection"]
        print(f"  [{tier}] issue-detection recall={i['recall']:.2f} "
              f"attribution={i['attribution_accuracy']:.2f} fpr={i['false_positive_rate']:.2f}")


if __name__ == "__main__":
    main()
