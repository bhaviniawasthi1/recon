"""
Issue: marketplace vendor-commission miscalculation.

Real-world cause: multi-vendor marketplace settlements deduct the vendor's
commission (8-20% of gross, per that vendor's contracted rate) before
computing the net payout -- on top of MDR, GST-on-MDR, and TDS. Settlement
systems sometimes apply a stale/wrong rate for a vendor, apply a flat
"default" rate instead of that vendor's actual contracted rate, or skip
the deduction entirely (so the vendor is overpaid).

This only applies to marketplace transactions (txn.vendor_id is set) --
the generator only calls this on such records. The correct rate is looked
up from the tier's vendor_rates.json master data (a per-vendor commission
table, analogous to what a real reconciliation agent would be given
alongside the raw settlement data -- this is NOT ground truth, it's
legitimate reference data).

Ground truth: expected_match stays True, but net_amount/vendor_commission
are wrong and must be flagged with the expected-vs-actual delta.
"""
from __future__ import annotations

import random

from schemas.models import IssueType


def apply(rng: random.Random, txn, settlement, bank_entry, truth, difficulty: str,
          vendor_rates: dict):
    if txn.vendor_id is None or not vendor_rates:
        # Not a marketplace transaction -- this issue type doesn't apply;
        # caller (generate_dataset.py) is responsible for only invoking us
        # on vendor transactions, but we no-op defensively just in case.
        return txn, settlement, bank_entry, truth

    correct_rate = vendor_rates.get(txn.vendor_id, 0.0)
    correct_commission = round(txn.amount * correct_rate, 2)
    variant = rng.choice(["stale_rate", "flat_default_rate", "omitted"])

    if variant == "stale_rate":
        # Applies some OTHER vendor's rate by mistake.
        other_rates = [r for vid, r in vendor_rates.items() if vid != txn.vendor_id]
        wrong_rate = rng.choice(other_rates) if other_rates else correct_rate * 1.5
        wrong_commission = round(txn.amount * wrong_rate, 2)
    elif variant == "flat_default_rate":
        wrong_commission = round(txn.amount * 0.10, 2)  # generic "default" 10%
    else:  # omitted
        wrong_commission = 0.0

    delta = round(wrong_commission - correct_commission, 2)
    settlement.vendor_commission = wrong_commission
    settlement.net_amount = round(settlement.net_amount - delta, 2)
    bank_entry.credit_amount = settlement.net_amount

    truth.issue_type = IssueType.COMMISSION_MISCALC
    truth.expected_match = True
    truth.expected_verdict = (
        f"matched, but flag vendor commission discrepancy: settlement deducted "
        f"INR {wrong_commission} ({variant}), correct commission for {txn.vendor_id} "
        f"at contracted rate {correct_rate*100:.1f}% of gross INR {txn.amount} is "
        f"INR {correct_commission} (delta INR {delta})"
    )
    truth.difficulty = difficulty
    truth.notes = (f"variant={variant}; vendor={txn.vendor_id}; "
                    f"correct_commission={correct_commission}; wrong_commission={wrong_commission}")
    return txn, settlement, bank_entry, truth
