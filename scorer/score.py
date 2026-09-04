"""
Compares an agent's output.json against a tier's ground_truth.json and
computes benchmark metrics.

Two separate scoring dimensions, because they fail independently:

1. MATCHING metrics -- did the agent correctly decide whether a
   transaction has a corresponding settlement/bank credit at all
   (expected_match True/False), i.e. matched vs unmatched.
     precision = TP / (TP + FP)
     recall    = TP / (TP + FN)
     where "positive" = agent claims a match exists.

2. ISSUE-DETECTION metrics -- for transactions that DO have a real
   underlying data-quality issue (issue_type != clean), did the agent's
   verdict flag it (verdict == matched_flagged) and, more strictly, did it
   attribute the right issue_type. Also computes false-positive rate: how
   often the agent flagged a transaction that ground truth says was
   actually CLEAN (this is what the rounding_noise red herring tests).

Usage:
    python3 -m scorer.score --tier-dir datasets/easy
    python3 -m scorer.score --tier-dir datasets/easy --agent-output datasets/easy/agent_output.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(tier_dir: Path, agent_output_path: Path | None):
    ground_truth = json.loads((tier_dir / "ground_truth.json").read_text())
    out_path = agent_output_path or (tier_dir / "agent_output_smart.json")
    agent_output = json.loads(out_path.read_text())
    return ground_truth, agent_output


def score_tier(tier_dir: Path, agent_output_path: Path | None = None) -> dict:
    ground_truth, agent_output = _load(tier_dir, agent_output_path)
    truth_by_id = {g["payment_id"]: g for g in ground_truth}
    agent_by_id = {a["payment_id"]: a for a in agent_output}

    match_tp = match_fp = match_fn = match_tn = 0
    issue_tp = issue_fp = issue_fn = issue_correct_attribution = 0
    n_real_issues = 0
    unscored = []

    for payment_id, truth in truth_by_id.items():
        agent = agent_by_id.get(payment_id)
        if agent is None:
            unscored.append(payment_id)
            continue

        agent_says_matched = agent["verdict"] in ("matched_clean", "matched_flagged")
        truth_says_matched = truth["expected_match"]

        if truth_says_matched and agent_says_matched:
            match_tp += 1
        elif (not truth_says_matched) and agent_says_matched:
            match_fp += 1
        elif truth_says_matched and (not agent_says_matched):
            match_fn += 1
        else:
            match_tn += 1

        has_real_issue = truth["issue_type"] != "clean" and truth_says_matched
        agent_flagged = agent["verdict"] == "matched_flagged"

        if has_real_issue:
            n_real_issues += 1
            if agent_flagged:
                issue_tp += 1
                agent_issue = agent.get("issue_type")
                is_overlap = "overlap" in truth.get("notes", "")
                if agent_issue == truth["issue_type"] or (is_overlap and agent_issue == "multiple"):
                    issue_correct_attribution += 1
            else:
                issue_fn += 1
        else:
            # ground truth says clean (or unmatched) -- flagging is a false positive
            if agent_flagged:
                issue_fp += 1

    def _pr(tp, fp, fn):
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision and recall and (precision + recall) else None)
        return precision, recall, f1

    match_precision, match_recall, match_f1 = _pr(match_tp, match_fp, match_fn)
    issue_precision, issue_recall, issue_f1 = _pr(issue_tp, issue_fp, issue_fn)

    n_clean_or_unmatched = len(truth_by_id) - n_real_issues
    false_positive_rate = (issue_fp / n_clean_or_unmatched) if n_clean_or_unmatched else None
    attribution_accuracy = (issue_correct_attribution / issue_tp) if issue_tp else None

    return {
        "tier": tier_dir.name,
        "n_records": len(truth_by_id),
        "n_unscored_missing_from_agent_output": len(unscored),
        "matching": {
            "tp": match_tp, "fp": match_fp, "fn": match_fn, "tn": match_tn,
            "precision": match_precision, "recall": match_recall, "f1": match_f1,
        },
        "issue_detection": {
            "n_real_issues": n_real_issues,
            "tp": issue_tp, "fp": issue_fp, "fn": issue_fn,
            "precision": issue_precision, "recall": issue_recall, "f1": issue_f1,
            "false_positive_rate": false_positive_rate,
            "attribution_accuracy": attribution_accuracy,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Score an agent's output against ReconArena ground truth")
    parser.add_argument("--tier-dir", type=str, required=True)
    parser.add_argument("--agent-output", type=str, default=None)
    args = parser.parse_args()

    result = score_tier(Path(args.tier_dir),
                         Path(args.agent_output) if args.agent_output else None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
