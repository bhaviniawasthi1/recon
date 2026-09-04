"""
CLI: generates the easy/medium/hard ReconArena datasets.

Usage:
    python3 -m generator.generate_dataset [--seed 42] [--out datasets]

Each tier directory gets five JSON files:
    transactions.json     -- list[Transaction]      (customer side)
    settlements.json      -- list[SettlementRecord]  (aggregator side, SHUFFLED)
    bank_statement.json   -- list[BankStatementEntry] (bank side, SHUFFLED)
    vendor_rates.json     -- {vendor_id: commission_rate} master data (legitimate
                              reference data, NOT ground truth -- a real agent
                              would be given a vendor-commission contract table
                              like this alongside the raw settlement feed)
    ground_truth.json     -- list[GroundTruthLabel]  (answer key -- NOT given to agents)

settlements.json and bank_statement.json are independently shuffled so an
agent cannot cheat by matching on list position -- it must actually
reconcile on IDs/amounts/dates.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

from generator.base_data import make_clean_triple
from generator.messiness import utr_mismatch, tds, gst_mdr, structural, commission_chain
from generator.constants import VENDOR_COMMISSION_RATE_RANGE

BASE_DATE = datetime(2026, 7, 1)
VENDOR_IDS = [f"vendor_{i}" for i in range(1, 10)]

# (weight, applier) pools per tier. "clean" means no injector runs.
SINGLE_ISSUE_APPLIERS = {
    "utr_mismatch": utr_mismatch.apply,
    "tds_miscalc": tds.apply,
    "gst_mdr_miscalc": gst_mdr.apply,
    "missing_settlement": structural.apply_missing_settlement,
    "amount_mismatch": structural.apply_amount_mismatch,
    "commission_miscalc": commission_chain.apply,  # needs vendor_rates -- special-cased below
}

TIER_CONFIG = {
    "easy": {
        "n": 30,
        "clean_ratio": 0.42,
        "issue_mix": ["utr_mismatch", "tds_miscalc", "gst_mdr_miscalc",
                       "missing_settlement", "amount_mismatch", "commission_miscalc"],
        "overlap_ratio": 0.0,      # never combine two issues on one record
        "red_herring_ratio": 0.0,  # no rounding-noise decoys
    },
    "medium": {
        "n": 45,
        "clean_ratio": 0.27,
        "issue_mix": ["utr_mismatch", "tds_miscalc", "gst_mdr_miscalc",
                       "missing_settlement", "amount_mismatch", "commission_miscalc"],
        "overlap_ratio": 0.20,     # 20% of issue records get a 2nd overlapping issue
        "red_herring_ratio": 0.10,
    },
    "hard": {
        "n": 60,
        "clean_ratio": 0.18,
        "issue_mix": ["utr_mismatch", "tds_miscalc", "gst_mdr_miscalc",
                       "missing_settlement", "amount_mismatch", "commission_miscalc"],
        "overlap_ratio": 0.35,
        "red_herring_ratio": 0.20,
    },
}

# Issue types that can be layered onto another as an "overlap" -- excludes
# missing_settlement (withholds the settlement entirely, nothing to layer
# onto) and commission_miscalc is only combinable when the record already
# has a vendor_id (checked at call time).
COMBINABLE = ["utr_mismatch", "tds_miscalc", "gst_mdr_miscalc", "amount_mismatch",
              "commission_miscalc"]

# Fixed (not hash()-based) per-tier seed offsets -- Python's string hash() is
# randomized per-process (PYTHONHASHSEED), so using hash(tier) silently broke
# --seed reproducibility across runs. Keep this mapping stable.
TIER_SEED_OFFSET = {"easy": 0, "medium": 1, "hard": 2}


def _apply_issue(name, rng, txn, settlement, bank_entry, truth, difficulty, vendor_rates):
    if name == "commission_miscalc":
        return commission_chain.apply(rng, txn, settlement, bank_entry, truth, difficulty,
                                       vendor_rates)
    return SINGLE_ISSUE_APPLIERS[name](rng, txn, settlement, bank_entry, truth, difficulty)


def make_vendor_rates(rng: random.Random) -> dict:
    lo, hi = VENDOR_COMMISSION_RATE_RANGE
    return {vid: round(rng.uniform(lo, hi), 3) for vid in VENDOR_IDS}


def generate_tier(tier: str, rng: random.Random):
    cfg = TIER_CONFIG[tier]
    vendor_rates = make_vendor_rates(rng)
    transactions, settlements, bank_entries, ground_truth = [], [], [], []

    for i in range(cfg["n"]):
        roll = rng.random()
        is_clean_slot = roll < cfg["red_herring_ratio"] + cfg["clean_ratio"]
        is_red_herring = roll < cfg["red_herring_ratio"]

        primary = None
        if not is_clean_slot:
            primary = rng.choice(cfg["issue_mix"])

        # commission_miscalc requires a vendor-linked transaction -- force
        # vendor assignment when it's the chosen issue; otherwise vendor_id
        # is assigned at the normal ~35% marketplace-order rate.
        if primary == "commission_miscalc":
            vendor_id = rng.choice(VENDOR_IDS)
        else:
            vendor_id = rng.choice(VENDOR_IDS) if rng.random() < 0.35 else None

        txn, settlement, bank_entry, truth = make_clean_triple(
            rng, BASE_DATE, tier, vendor_id, vendor_rates)

        if is_red_herring:
            txn, settlement, bank_entry, truth = structural.apply_rounding_noise(
                rng, txn, settlement, bank_entry, truth, tier)
        elif is_clean_slot:
            pass  # stays clean, no injector
        else:
            txn, settlement, bank_entry, truth = _apply_issue(
                primary, rng, txn, settlement, bank_entry, truth, tier, vendor_rates)
            # possibly overlap a second, independent issue on top (only for
            # issue types that both still produce a settlement+bank_entry)
            if settlement is not None and primary in COMBINABLE and rng.random() < cfg["overlap_ratio"]:
                secondary_choices = [c for c in COMBINABLE if c != primary]
                if vendor_id is None:
                    secondary_choices = [c for c in secondary_choices if c != "commission_miscalc"]
                secondary = rng.choice(secondary_choices)
                txn, settlement, bank_entry, truth = _apply_issue(
                    secondary, rng, txn, settlement, bank_entry, truth, tier, vendor_rates)
                truth.notes = f"[overlap: {primary} + {secondary}] " + truth.notes

        transactions.append(txn)
        if settlement is not None:
            settlements.append(settlement)
        if bank_entry is not None:
            bank_entries.append(bank_entry)
        ground_truth.append(truth)

    rng.shuffle(settlements)
    rng.shuffle(bank_entries)
    return transactions, settlements, bank_entries, ground_truth, vendor_rates


def write_tier(tier: str, out_root: Path, rng: random.Random):
    transactions, settlements, bank_entries, ground_truth, vendor_rates = generate_tier(tier, rng)
    tier_dir = out_root / tier
    tier_dir.mkdir(parents=True, exist_ok=True)

    (tier_dir / "transactions.json").write_text(
        json.dumps([t.to_dict() for t in transactions], indent=2))
    (tier_dir / "settlements.json").write_text(
        json.dumps([s.to_dict() for s in settlements], indent=2))
    (tier_dir / "bank_statement.json").write_text(
        json.dumps([b.to_dict() for b in bank_entries], indent=2))
    (tier_dir / "vendor_rates.json").write_text(json.dumps(vendor_rates, indent=2))
    (tier_dir / "ground_truth.json").write_text(
        json.dumps([g.to_dict() for g in ground_truth], indent=2))

    print(f"[{tier}] {len(transactions)} txns, {len(settlements)} settlements, "
          f"{len(bank_entries)} bank entries -> {tier_dir}")


def main():
    parser = argparse.ArgumentParser(description="Generate ReconArena datasets")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="datasets")
    args = parser.parse_args()

    out_root = Path(args.out)
    for tier in ["easy", "medium", "hard"]:
        rng = random.Random(args.seed + TIER_SEED_OFFSET[tier])
        write_tier(tier, out_root, rng)


if __name__ == "__main__":
    main()
