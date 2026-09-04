"""
ReconArena naive reference agent.

This is a deliberately WEAK agent -- it models the kind of reconciliation
logic a lot of real, unsophisticated systems still run: exact string
matching only, no fallback, no tax/fee recomputation. It exists purely to
prove that ReconArena actually DISCRIMINATES between agent quality --
a benchmark where every agent scores the same isn't measuring anything.
See scorer/leaderboard.py, which ranks this agent against the smarter
baseline_agent/agent.py on the same datasets.

Logic:
  1. Link Transaction -> SettlementRecord via internal_txn_id == payment_id
     (same reliable join key the smart agent uses).
  2. Link SettlementRecord -> BankStatementEntry via EXACT utr == bank_ref
     string match ONLY. No amount/date fallback -- so any utr_mismatch
     record is reported unmatched, even though the money genuinely moved.
  3. No tax/fee recomputation at all -- if matched, it is always reported
     "matched_clean", even when TDS/GST/commission are wrong. So every
     tds_miscalc / gst_mdr_miscalc / commission_miscalc / amount_mismatch
     record is silently missed.

Usage mirrors baseline_agent/agent.py:
    python3 -m baseline_agent.naive_agent --tier-dir datasets/easy
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_tier(tier_dir: Path):
    transactions = json.loads((tier_dir / "transactions.json").read_text())
    settlements = json.loads((tier_dir / "settlements.json").read_text())
    bank_entries = json.loads((tier_dir / "bank_statement.json").read_text())
    return transactions, settlements, bank_entries


def reconcile_transaction(txn, settlements, bank_entries):
    settlement = next((s for s in settlements if s["internal_txn_id"] == txn["payment_id"]), None)
    if settlement is None:
        return {
            "payment_id": txn["payment_id"], "settlement_id": None, "bank_ref": None,
            "verdict": "unmatched", "issue_type": "missing_settlement",
            "explanation": "no settlement record found (exact match only)",
        }

    bank_entry = next((b for b in bank_entries if b["bank_ref"] == settlement["utr"]), None)
    if bank_entry is None:
        return {
            "payment_id": txn["payment_id"], "settlement_id": settlement["settlement_id"],
            "bank_ref": None, "verdict": "unmatched", "issue_type": "missing_settlement",
            "explanation": "bank UTR does not exact-match settlement UTR; no fallback attempted",
        }

    return {
        "payment_id": txn["payment_id"], "settlement_id": settlement["settlement_id"],
        "bank_ref": bank_entry["bank_ref"], "verdict": "matched_clean", "issue_type": "clean",
        "explanation": "UTR matched exactly; no further checks performed",
    }


def run_agent(tier_dir: Path) -> list[dict]:
    transactions, settlements, bank_entries = _load_tier(tier_dir)
    return [reconcile_transaction(t, settlements, bank_entries) for t in transactions]


def main():
    parser = argparse.ArgumentParser(description="Run the ReconArena naive (exact-match-only) agent")
    parser.add_argument("--tier-dir", type=str, required=True)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    tier_dir = Path(args.tier_dir)
    output = run_agent(tier_dir)
    out_path = Path(args.out) if args.out else tier_dir / "agent_output_naive.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"wrote {len(output)} verdicts -> {out_path}")


if __name__ == "__main__":
    main()
