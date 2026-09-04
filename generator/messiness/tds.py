"""
Issue: TDS (Tax Deducted at Source) miscalculation -- Sec 194O.

Real-world cause: e-commerce marketplace sellers are paid net of TDS under
Sec 194O. The correct rate is 0.1% of gross sale value (post Apr-2026
transition to Sec 393(1); same 0.1% rate carried forward). Settlement
systems sometimes still apply the old 1% rate, skip TDS entirely, or
double-deduct it.

Ground truth: expected_match stays True (it is still the right payout to
link), but net_amount/tds_amount are wrong and must be flagged with the
expected-vs-actual TDS delta.
"""
from __future__ import annotations

import random

from schemas.models import IssueType
from generator.constants import TDS_RATE_194O, TDS_RATE_LEGACY


def apply(rng: random.Random, txn, settlement, bank_entry, truth, difficulty: str):
    correct_tds = round(txn.amount * TDS_RATE_194O, 2)
    variant = rng.choice(["legacy_rate", "omitted", "double_deducted"])

    if variant == "legacy_rate":
        wrong_tds = round(txn.amount * TDS_RATE_LEGACY, 2)
    elif variant == "omitted":
        wrong_tds = 0.0
    else:  # double_deducted
        wrong_tds = round(correct_tds * 2, 2)

    delta = round(wrong_tds - correct_tds, 2)
    settlement.tds_amount = wrong_tds
    settlement.net_amount = round(settlement.net_amount - delta, 2)
    bank_entry.credit_amount = settlement.net_amount

    truth.issue_type = IssueType.TDS_MISCALC
    truth.expected_match = True
    truth.expected_verdict = (
        f"matched, but flag TDS discrepancy: settlement applied INR {wrong_tds} "
        f"({variant}), correct Sec 194O TDS on gross INR {txn.amount} is "
        f"INR {correct_tds} (delta INR {delta})"
    )
    truth.difficulty = difficulty
    truth.notes = f"variant={variant}; correct_tds={correct_tds}; wrong_tds={wrong_tds}"
    return txn, settlement, bank_entry, truth
