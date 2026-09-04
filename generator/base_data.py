"""
Generates one internally-consistent, CLEAN (transaction, settlement, bank
entry) triple. Messiness injectors in generator/messiness/ then mutate a
clean triple to introduce a specific, scoreable problem while updating the
matching GroundTruthLabel.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

from schemas.models import (
    Transaction, SettlementRecord, BankStatementEntry, GroundTruthLabel,
    PaymentMethod, UpiSubRail, TransactionStatus, IssueType,
)
from generator.constants import (
    GST_ON_MDR_RATE, TDS_RATE_194O,
    MDR_RATE_CARD, MDR_RATE_UPI_BANK, MDR_RATE_UPI_WALLET,
    MDR_RATE_UPI_RUPAY_CREDIT, MDR_RATE_NETBANKING,
)


def _hex_id(prefix: str, rng: random.Random, length: int = 14) -> str:
    return f"{prefix}_{uuid.UUID(int=rng.getrandbits(128)).hex[:length]}"


def _mdr_rate(method: PaymentMethod, sub_rail: UpiSubRail | None) -> float:
    if method == PaymentMethod.CARD:
        return MDR_RATE_CARD
    if method == PaymentMethod.NETBANKING:
        return MDR_RATE_NETBANKING
    if method == PaymentMethod.WALLET:
        return MDR_RATE_UPI_WALLET
    if method == PaymentMethod.UPI:
        if sub_rail == UpiSubRail.WALLET_ON_UPI:
            return MDR_RATE_UPI_WALLET
        if sub_rail == UpiSubRail.RUPAY_CREDIT_ON_UPI:
            return MDR_RATE_UPI_RUPAY_CREDIT
        return MDR_RATE_UPI_BANK
    return 0.0


def make_clean_triple(rng: random.Random, base_date: datetime, difficulty: str,
                       vendor_id: str | None = None,
                       vendor_rates: dict | None = None) -> tuple[
        Transaction, SettlementRecord, BankStatementEntry, GroundTruthLabel]:
    """Build one fully clean, arithmetically-correct triple + ground truth.

    vendor_rates: {vendor_id: commission_rate} master data, fixed per vendor
    for the whole tier (mirrors a real merchant-commission contract table).
    When vendor_id is set, the correct vendor commission is deducted as an
    additional line before computing net_amount -- this is what
    generator/messiness/commission_chain.py can later corrupt.
    """
    method = rng.choice(list(PaymentMethod))
    sub_rail = rng.choice(list(UpiSubRail)) if method == PaymentMethod.UPI else None
    amount = round(rng.uniform(150, 45000), 2)

    payment_id = _hex_id("pay", rng)
    order_id = _hex_id("order", rng)
    settlement_id = _hex_id("setl", rng)
    utr = _hex_id("UTR", rng, length=12).upper().replace("UTR_", "UTR")

    created_at = base_date + timedelta(hours=rng.randint(0, 20))
    settlement_date = created_at + timedelta(days=rng.choice([1, 2, 3]))

    mdr_rate = _mdr_rate(method, sub_rail)
    mdr_fee = round(amount * mdr_rate, 2)
    gst_on_mdr = round(mdr_fee * GST_ON_MDR_RATE, 2)
    tds_amount = round(amount * TDS_RATE_194O, 2)

    vendor_commission = 0.0
    if vendor_id is not None and vendor_rates:
        rate = vendor_rates.get(vendor_id, 0.0)
        vendor_commission = round(amount * rate, 2)

    net_amount = round(amount - mdr_fee - gst_on_mdr - tds_amount - vendor_commission, 2)

    txn = Transaction(
        payment_id=payment_id, order_id=order_id, amount=amount, method=method,
        status=TransactionStatus.CAPTURED, created_at=created_at.isoformat(),
        vendor_id=vendor_id, upi_sub_rail=sub_rail,
    )
    settlement = SettlementRecord(
        settlement_id=settlement_id, utr=utr, internal_txn_id=payment_id,
        order_id=order_id, gross_amount=amount, mdr_fee=mdr_fee,
        gst_on_mdr=gst_on_mdr, tds_amount=tds_amount, net_amount=net_amount,
        settlement_date=settlement_date.date().isoformat(), vendor_id=vendor_id,
        vendor_commission=vendor_commission,
    )
    bank_entry = BankStatementEntry(
        bank_ref=utr, credit_amount=net_amount,
        credit_date=settlement_date.date().isoformat(),
        narration=f"NEFT-{utr}-SETTLEMENT",
    )
    truth = GroundTruthLabel(
        payment_id=payment_id, settlement_id=settlement_id, bank_ref=utr,
        issue_type=IssueType.CLEAN, expected_match=True,
        expected_verdict="matched: all fields reconcile exactly",
        difficulty=difficulty,
    )
    return txn, settlement, bank_entry, truth
