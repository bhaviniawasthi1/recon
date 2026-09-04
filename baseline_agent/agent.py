"""
ReconArena rule-based reference agent ("smart" agent).

Given a tier's transactions.json / settlements.json / bank_statement.json /
vendor_rates.json (NO ground_truth.json -- that would be cheating), this
agent reconciles the three transactional sides and produces a verdict per
transaction:

    matched_clean          -- linked, amounts/tax/commission all correct
    matched_flagged        -- linked, but a discrepancy was found and
                               attributed to a specific cause
    unmatched               -- no settlement/bank credit could be found

It exists to prove the benchmark produces signal: a benchmark that only
ships a data generator, with nothing able to attempt it, is not
falsifiable. This agent is intentionally simple (deterministic, no LLM) so
its score is a reproducible floor other (smarter) agents should beat --
see baseline_agent/naive_agent.py for a deliberately weaker floor below
this one, and scorer/leaderboard.py for how multiple agents are ranked
against each other.

Matching strategy (in order):
  1. internal_txn_id == payment_id  links Transaction -> SettlementRecord.
     (This is always reliable in our schema -- it is the "clean" join key,
     independent of the UTR mismatch problem, which only affects the
     settlement<->bank leg.)
  2. settlement.utr == bank_entry.bank_ref (exact match) links
     SettlementRecord -> BankStatementEntry.
  3. If no exact UTR match, fall back to (amount tolerance + date
     proximity) to find the bank entry -- this is what makes the agent
     resilient to utr_mismatch.

Discrepancy attribution (once linked):
  - Recompute the TEXTBOOK-CORRECT TDS (0.1% of gross, Sec 194O),
    GST-on-MDR (18% of mdr_fee), and -- for marketplace transactions --
    vendor commission (looked up from vendor_rates.json, the merchant
    commission contract table) and compare each to what the settlement
    actually deducted.
  - Any bank-credit delta not explained by TDS/GST/commission is reported
    as an "unexplained amount discrepancy".
  - A total delta under ROUNDING_TOLERANCE is treated as noise and not
    flagged, to keep the false-positive rate sane against the
    rounding_noise red herring.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from generator.constants import GST_ON_MDR_RATE, TDS_RATE_194O

ROUNDING_TOLERANCE = 0.05        # INR -- below this, a delta is float noise
AMOUNT_MATCH_TOLERANCE = 1.00    # INR -- fallback bank-entry amount matching
DATE_MATCH_WINDOW_DAYS = 5       # fallback bank-entry date proximity window


def _load_tier(tier_dir: Path):
    transactions = json.loads((tier_dir / "transactions.json").read_text())
    settlements = json.loads((tier_dir / "settlements.json").read_text())
    bank_entries = json.loads((tier_dir / "bank_statement.json").read_text())
    vendor_rates_path = tier_dir / "vendor_rates.json"
    vendor_rates = json.loads(vendor_rates_path.read_text()) if vendor_rates_path.exists() else {}
    return transactions, settlements, bank_entries, vendor_rates


def _find_settlement(txn, settlements):
    for s in settlements:
        if s["internal_txn_id"] == txn["payment_id"]:
            return s
    return None


def _find_bank_entry(settlement, bank_entries):
    # 1. exact UTR match
    for b in bank_entries:
        if b["bank_ref"] == settlement["utr"]:
            return b, "exact_utr"
    # 2. fallback: amount + date proximity (handles utr_mismatch)
    settle_date = date.fromisoformat(settlement["settlement_date"])
    best, best_gap = None, None
    for b in bank_entries:
        amt_gap = abs(b["credit_amount"] - settlement["net_amount"])
        if amt_gap > AMOUNT_MATCH_TOLERANCE:
            continue
        day_gap = abs((date.fromisoformat(b["credit_date"]) - settle_date).days)
        if day_gap > DATE_MATCH_WINDOW_DAYS:
            continue
        score = amt_gap + day_gap * 0.01
        if best is None or score < best_gap:
            best, best_gap = b, score
    if best is not None:
        return best, "fallback_amount_date"
    return None, None


def reconcile_transaction(txn, settlements, bank_entries, vendor_rates):
    settlement = _find_settlement(txn, settlements)
    if settlement is None:
        return {
            "payment_id": txn["payment_id"],
            "settlement_id": None,
            "bank_ref": None,
            "verdict": "unmatched",
            "issue_type": "missing_settlement",
            "explanation": "no settlement record found for this transaction",
        }

    bank_entry, match_method = _find_bank_entry(settlement, bank_entries)
    if bank_entry is None:
        return {
            "payment_id": txn["payment_id"],
            "settlement_id": settlement["settlement_id"],
            "bank_ref": None,
            "verdict": "unmatched",
            "issue_type": "missing_settlement",
            "explanation": "settlement exists but no matching bank credit found",
        }

    gross = settlement["gross_amount"]
    expected_tds = round(gross * TDS_RATE_194O, 2)
    expected_gst = round(settlement["mdr_fee"] * GST_ON_MDR_RATE, 2)

    vendor_id = settlement.get("vendor_id")
    expected_commission = 0.0
    if vendor_id and vendor_id in vendor_rates:
        expected_commission = round(gross * vendor_rates[vendor_id], 2)

    tds_delta = round(settlement["tds_amount"] - expected_tds, 2)
    gst_delta = round(settlement["gst_on_mdr"] - expected_gst, 2)
    commission_delta = round(settlement.get("vendor_commission", 0.0) - expected_commission, 2)

    # Use the TEXTBOOK-CORRECT tds/gst/commission here (not settlement's own
    # reported values, which may themselves be wrong) so that the per-cause
    # deltas and "remaining" don't double-count the same discrepancy.
    textbook_expected_net = round(gross - settlement["mdr_fee"] - expected_gst
                                   - expected_tds - expected_commission, 2)
    unexplained_delta = round(bank_entry["credit_amount"] - textbook_expected_net, 2)
    remaining = round(unexplained_delta + tds_delta + gst_delta + commission_delta, 2)

    findings = []
    issue_type = "clean"
    if abs(tds_delta) > ROUNDING_TOLERANCE:
        findings.append(f"TDS discrepancy: settlement deducted INR {settlement['tds_amount']}, "
                         f"expected INR {expected_tds} under Sec 194O (delta INR {tds_delta})")
        issue_type = "tds_miscalc"
    if abs(gst_delta) > ROUNDING_TOLERANCE:
        findings.append(f"GST-on-MDR discrepancy: settlement shows INR {settlement['gst_on_mdr']}, "
                         f"expected INR {expected_gst} (18% of MDR fee INR {settlement['mdr_fee']}, "
                         f"delta INR {gst_delta})")
        issue_type = "gst_mdr_miscalc" if issue_type == "clean" else "multiple"
    if vendor_id and abs(commission_delta) > ROUNDING_TOLERANCE:
        findings.append(f"vendor commission discrepancy for {vendor_id}: settlement deducted "
                         f"INR {settlement.get('vendor_commission', 0.0)}, expected INR "
                         f"{expected_commission} at contracted rate (delta INR {commission_delta})")
        issue_type = "commission_miscalc" if issue_type == "clean" else "multiple"
    if abs(remaining) > ROUNDING_TOLERANCE:
        findings.append(f"unexplained amount discrepancy of INR {remaining} not attributable "
                         f"to TDS/GST/commission -- investigate refund/chargeback")
        issue_type = "amount_mismatch" if issue_type == "clean" else "multiple"

    if match_method == "fallback_amount_date":
        findings.insert(0, f"UTR mismatch: bank ref '{bank_entry['bank_ref']}' does not "
                            f"string-match settlement UTR '{settlement['utr']}'; linked via "
                            f"internal_txn_id + amount/date fallback")
        issue_type = "utr_mismatch" if issue_type == "clean" else "multiple"

    verdict = "matched_clean" if not findings else "matched_flagged"
    return {
        "payment_id": txn["payment_id"],
        "settlement_id": settlement["settlement_id"],
        "bank_ref": bank_entry["bank_ref"],
        "verdict": verdict,
        "issue_type": issue_type,
        "explanation": "; ".join(findings) if findings else "all amounts reconcile",
    }


def run_agent(tier_dir: Path) -> list[dict]:
    transactions, settlements, bank_entries, vendor_rates = _load_tier(tier_dir)
    return [reconcile_transaction(t, settlements, bank_entries, vendor_rates) for t in transactions]


def main():
    parser = argparse.ArgumentParser(description="Run the ReconArena rule-based baseline agent")
    parser.add_argument("--tier-dir", type=str, required=True,
                         help="e.g. datasets/easy")
    parser.add_argument("--out", type=str, default=None,
                         help="where to write agent_output.json (defaults to <tier-dir>/agent_output.json)")
    args = parser.parse_args()

    tier_dir = Path(args.tier_dir)
    output = run_agent(tier_dir)
    out_path = Path(args.out) if args.out else tier_dir / "agent_output_smart.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"wrote {len(output)} verdicts -> {out_path}")


if __name__ == "__main__":
    main()
