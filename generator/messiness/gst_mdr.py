"""
Issue: GST-on-MDR miscalculation.

Real-world cause: 18% GST applies not just to the order but to the
gateway's own transaction (MDR) fee -- a separate ITC-eligible line item.
Settlement systems sometimes omit this line, fold it silently into the MDR
fee (so MDR looks inflated by 18% but isn't itemised), or apply the wrong
GST rate.

Ground truth: expected_match stays True, but gst_on_mdr/net_amount are
wrong and must be flagged with the correct recomputation.
"""
from __future__ import annotations

import random

from schemas.models import IssueType
from generator.constants import GST_ON_MDR_RATE


def apply(rng: random.Random, txn, settlement, bank_entry, truth, difficulty: str):
    correct_gst = round(settlement.mdr_fee * GST_ON_MDR_RATE, 2)
    variant = rng.choice(["omitted", "folded_into_mdr", "wrong_rate"])

    if variant == "omitted":
        wrong_gst = 0.0
        delta = round(wrong_gst - correct_gst, 2)
    elif variant == "folded_into_mdr":
        # GST is added into mdr_fee itself instead of being a separate line.
        settlement.mdr_fee = round(settlement.mdr_fee + correct_gst, 2)
        wrong_gst = 0.0
        delta = round(wrong_gst - correct_gst, 2)
    else:  # wrong_rate (e.g. old 12% slab applied instead of 18%)
        wrong_rate = 0.12
        wrong_gst = round(settlement.mdr_fee * wrong_rate, 2)
        delta = round(wrong_gst - correct_gst, 2)

    settlement.gst_on_mdr = wrong_gst
    settlement.net_amount = round(settlement.net_amount - delta, 2)
    bank_entry.credit_amount = settlement.net_amount

    truth.issue_type = IssueType.GST_MDR_MISCALC
    truth.expected_match = True
    truth.expected_verdict = (
        f"matched, but flag GST-on-MDR discrepancy: settlement shows INR {wrong_gst} "
        f"({variant}), correct 18% GST on MDR fee INR {settlement.mdr_fee} is "
        f"INR {correct_gst} (delta INR {delta})"
    )
    truth.difficulty = difficulty
    truth.notes = f"variant={variant}; correct_gst={correct_gst}; wrong_gst={wrong_gst}"
    return txn, settlement, bank_entry, truth
