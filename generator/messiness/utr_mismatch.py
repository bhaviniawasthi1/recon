"""
Issue: UTR-vs-internal-ID mismatch.

Real-world cause: the aggregator's settlement report references payouts by
UTR, but the bank statement narration truncates, reformats, or garbles that
same UTR (fixed-width field truncation, whitespace, batch-settlement
concatenation). A naive exact-string-match reconciliation fails to link the
settlement to the bank credit even though the money is the same money.

Ground truth: expected_match stays True (the payout still happened), but
the correct matching strategy is NOT bank_ref==utr; it must fall back to
internal_txn_id + amount + date.
"""
from __future__ import annotations

import random

from schemas.models import IssueType


def apply(rng: random.Random, txn, settlement, bank_entry, truth, difficulty: str):
    real_utr = settlement.utr
    variant = rng.choice(["truncate", "prefix_batch", "whitespace", "case_shuffle"])

    if variant == "truncate":
        # Bank narration truncates to a fixed-width field.
        garbled = real_utr[:10]
    elif variant == "prefix_batch":
        # Bank batches multiple settlements into one narration line.
        garbled = f"BATCH{rng.randint(1000,9999)}/{real_utr[-8:]}"
    elif variant == "whitespace":
        garbled = " ".join(list(real_utr[:6])) + real_utr[6:]
    else:  # case_shuffle
        garbled = real_utr.swapcase()

    bank_entry.bank_ref = garbled
    bank_entry.narration = f"NEFT-{garbled}-SETTLEMENT"

    truth.issue_type = IssueType.UTR_MISMATCH
    truth.bank_ref = garbled
    truth.expected_match = True
    truth.expected_verdict = (
        "matched via internal_txn_id + amount + date fallback "
        f"(bank narration UTR '{garbled}' does not string-match settlement UTR "
        f"'{real_utr}', but it is the same payout)"
    )
    truth.difficulty = difficulty
    truth.notes = f"variant={variant}; true_utr={real_utr}"
    return txn, settlement, bank_entry, truth
