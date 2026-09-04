"""
Additional issue types used to round out difficulty tiers:

- missing_settlement: the settlement/bank leg never arrives (a real
  "unreconciled" case) -- expected_match becomes False.
- amount_mismatch: a generic amount discrepancy unrelated to tax logic
  (e.g. a partial refund applied after settlement, not yet reflected) --
  tests that the agent doesn't blindly attribute every delta to GST/TDS.
- rounding_noise (hard-tier red herring): a sub-paisa rounding difference
  that LOOKS like a discrepancy but is expected_match=True / issue_type
  CLEAN -- a correct agent must NOT flag it. This is what makes false
  positive rate a meaningful metric.
"""
from __future__ import annotations

import random

from schemas.models import IssueType


def apply_missing_settlement(rng: random.Random, txn, settlement, bank_entry, truth, difficulty: str):
    truth.issue_type = IssueType.MISSING_SETTLEMENT
    truth.expected_match = False
    truth.expected_verdict = (
        "no match: settlement/bank credit never arrived for this transaction "
        "-- should be flagged as unreconciled, not silently dropped"
    )
    truth.difficulty = difficulty
    truth.notes = "settlement and bank_entry are withheld by the generator"
    return txn, None, None, truth


def apply_amount_mismatch(rng: random.Random, txn, settlement, bank_entry, truth, difficulty: str):
    # Simulate a partial refund that happened after settlement was computed,
    # so the bank credit is short by an amount unrelated to MDR/GST/TDS.
    refund_bite = round(rng.uniform(50, min(500, txn.amount * 0.3)), 2)
    bank_entry.credit_amount = round(bank_entry.credit_amount - refund_bite, 2)

    truth.issue_type = IssueType.AMOUNT_MISMATCH
    truth.expected_match = True
    truth.expected_verdict = (
        f"matched, but flag amount discrepancy of INR {refund_bite} not explained "
        "by MDR/GST/TDS -- investigate partial refund/chargeback applied post-settlement"
    )
    truth.difficulty = difficulty
    truth.notes = f"unexplained_delta={refund_bite}"
    return txn, settlement, bank_entry, truth


def apply_rounding_noise(rng: random.Random, txn, settlement, bank_entry, truth, difficulty: str):
    noise = round(rng.uniform(-0.04, 0.04), 2)  # sub-paisa float rounding artifact
    bank_entry.credit_amount = round(bank_entry.credit_amount + noise, 2)

    truth.issue_type = IssueType.CLEAN
    truth.expected_match = True
    truth.expected_verdict = (
        f"matched, no real issue -- INR {noise} is float rounding noise, "
        "must NOT be flagged as a discrepancy"
    )
    truth.difficulty = difficulty
    truth.notes = f"rounding_noise={noise} (red herring)"
    return txn, settlement, bank_entry, truth
