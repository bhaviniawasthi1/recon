"""
ReconArena core data schema.

Four entities model the India-specific reconciliation problem:

- Transaction: the customer-facing payment (what the buyer paid).
- SettlementRecord: the aggregator's payout report (what actually gets
  paid out to the merchant/vendor, net of MDR, GST-on-MDR, TDS).
- BankStatementEntry: the raw bank credit line the merchant sees land
  in their account. This is the "ground truth" money movement.
- GroundTruthLabel: the answer key -- which Transaction/Settlement/Bank
  records belong together, what messiness (if any) was injected, and
  what a correct reconciliation agent should conclude.

All monetary amounts are in INR, represented as float rupees rounded to
paise (2 decimals) for readability -- this is a benchmark, not a ledger,
so we intentionally avoid Decimal/paise-integer plumbing.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class PaymentMethod(str, Enum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    WALLET = "wallet"


class UpiSubRail(str, Enum):
    BANK_ACCOUNT = "bank_account"      # zero-interchange
    WALLET_ON_UPI = "wallet_on_upi"    # interchange-bearing (~9% of volume)
    RUPAY_CREDIT_ON_UPI = "rupay_credit_on_upi"  # interchange above INR 2000


class TransactionStatus(str, Enum):
    CAPTURED = "captured"
    REFUNDED = "refunded"
    FAILED = "failed"


class IssueType(str, Enum):
    CLEAN = "clean"
    UTR_MISMATCH = "utr_mismatch"
    TDS_MISCALC = "tds_miscalc"
    GST_MDR_MISCALC = "gst_mdr_miscalc"
    MISSING_SETTLEMENT = "missing_settlement"
    AMOUNT_MISMATCH = "amount_mismatch"
    COMMISSION_MISCALC = "commission_miscalc"


@dataclass
class Transaction:
    """Customer-facing payment, as the merchant's order system sees it."""
    payment_id: str            # e.g. "pay_5f3a9c2b1e7d4a"
    order_id: str              # e.g. "order_9a1c3e7b2f4d6a"
    amount: float              # gross amount paid by customer, INR
    method: PaymentMethod
    status: TransactionStatus
    created_at: str            # ISO 8601 timestamp
    vendor_id: Optional[str] = None       # set for marketplace/split orders
    upi_sub_rail: Optional[UpiSubRail] = None  # set only when method == UPI

    def to_dict(self) -> dict:
        d = asdict(self)
        d["method"] = self.method.value
        d["status"] = self.status.value
        d["upi_sub_rail"] = self.upi_sub_rail.value if self.upi_sub_rail else None
        return d


@dataclass
class SettlementRecord:
    """Aggregator's settlement/payout report line for one transaction."""
    settlement_id: str         # e.g. "setl_2b7f9a1c3e5d8a"
    utr: str                   # Unique Transaction Reference for the payout
    internal_txn_id: str       # aggregator's internal id (normally == payment_id)
    order_id: str
    gross_amount: float        # = Transaction.amount, before deductions
    mdr_fee: float             # merchant discount rate fee charged by gateway
    gst_on_mdr: float          # 18% GST applied to mdr_fee (India-specific)
    tds_amount: float          # tax deducted at source, Sec 194O
    net_amount: float          # gross - mdr_fee - gst_on_mdr - tds_amount
    settlement_date: str       # ISO 8601 date
    vendor_id: Optional[str] = None
    vendor_commission: float = 0.0   # marketplace commission deducted, if any

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BankStatementEntry:
    """One credit line as it actually appears in the merchant's bank statement."""
    bank_ref: str               # UTR string as printed by the bank (source of truth)
    credit_amount: float
    credit_date: str            # ISO 8601 date
    narration: str              # free-text bank narration, sometimes truncated/garbled

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GroundTruthLabel:
    """The answer key for one (transaction, settlement, bank) triple."""
    payment_id: str
    settlement_id: str
    bank_ref: str
    issue_type: IssueType
    expected_match: bool        # should a correct agent link these 3 records?
    expected_verdict: str       # human-readable description of correct action
    difficulty: str             # "easy" | "medium" | "hard"
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["issue_type"] = self.issue_type.value
        return d
