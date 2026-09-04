# ReconArena Architecture

## 1. Data model

Four entities, defined in `schemas/models.py`:

| Entity | Represents | Key fields |
|---|---|---|
| `Transaction` | The customer-facing payment | `payment_id`, `order_id`, `amount`, `method`, `upi_sub_rail`, `status` |
| `SettlementRecord` | Aggregator's payout report line | `settlement_id`, `utr`, `internal_txn_id`, `gross_amount`, `mdr_fee`, `gst_on_mdr`, `tds_amount`, `net_amount` |
| `BankStatementEntry` | The actual bank credit the merchant sees | `bank_ref`, `credit_amount`, `credit_date`, `narration` |
| `GroundTruthLabel` | The answer key | `payment_id`, `settlement_id`, `bank_ref`, `issue_type`, `expected_match`, `expected_verdict`, `difficulty` |

`internal_txn_id` on `SettlementRecord` always equals `Transaction.payment_id`
— this is the one reliable join key between the customer side and the
aggregator side, deliberately kept clean so the benchmark isolates the
*settlement-to-bank* reconciliation problem (where the real India-specific
messiness lives) rather than conflating it with a second, unrelated
join-key problem.

`settlements.json` and `bank_statement.json` are shuffled independently at
generation time, so an agent cannot cheat by matching on list position.

## 2. Messiness taxonomy (v1)

Implemented with full, calculable ground truth:

1. **`utr_mismatch`** (`generator/messiness/utr_mismatch.py`) — the bank
   narration's UTR is truncated, batch-prefixed, whitespace-mangled, or
   case-shuffled relative to the settlement's UTR. `expected_match` stays
   `True`; the correct strategy is `internal_txn_id` + amount/date
   fallback, not an exact UTR string match.
2. **`tds_miscalc`** (`generator/messiness/tds.py`) — simulates three
   real bugs against the correct Sec 194O rate (0.1% of gross): applying
   the old 1% rate, omitting TDS entirely, or double-deducting it.
3. **`gst_mdr_miscalc`** (`generator/messiness/gst_mdr.py`) — simulates
   omitting the 18%-of-MDR GST line, silently folding it into the MDR fee
   (so MDR looks inflated but isn't itemised), or applying the wrong
   rate (12% instead of 18%).

Two structural issue types (`generator/messiness/structural.py`) add
variety without new tax logic:

4. **`missing_settlement`** — the settlement/bank leg never arrives at
   all; `expected_match` becomes `False`. Tests that an agent correctly
   reports "unreconciled" instead of hallucinating a match or silently
   dropping the record.
5. **`amount_mismatch`** — a partial refund applied after settlement,
   producing a bank-credit shortfall unrelated to tax logic. Tests that
   an agent doesn't blindly attribute every delta to GST/TDS.

Plus one **red herring** used only in medium/hard tiers:

6. **`rounding_noise`** — a sub-paisa (±0.04 INR) float artifact on the
   bank credit. Ground truth `issue_type` stays `clean` and
   `expected_match` stays `True` — a correct agent must recognize this as
   noise and NOT flag it. This is what makes false-positive rate a
   meaningful, gameable-if-ignored metric.

## 3. Difficulty tiers

| Tier | N | Clean ratio | Overlap ratio | Red-herring ratio |
|---|---|---|---|---|
| easy | 30 | 45% | 0% | 0% |
| medium | 45 | 30% | 20% | 10% |
| hard | 60 | 20% | 35% | 20% |

"Overlap" means a record gets a second, independent issue applied on top
of the first (e.g. `utr_mismatch` + `tds_miscalc` on the same
transaction) — this simulates the real-world case where a record isn't
just wrong in one way. Ground truth stores the *last-applied* issue type
plus a `notes` field flagging the overlap (`"[overlap: tds_miscalc +
gst_mdr_miscalc] ..."`), so the scorer can credit an agent that reports
`issue_type: "multiple"` on a genuinely overlapping record.

## 4. Baseline agent

`baseline_agent/agent.py` is deterministic and rule-based — no LLM, no
network calls, fully reproducible. Strategy:

1. Join `Transaction` → `SettlementRecord` via `internal_txn_id ==
   payment_id` (always reliable by design — see §1).
2. Join `SettlementRecord` → `BankStatementEntry` via exact
   `utr == bank_ref` first; if that fails, fall back to amount-tolerance
   (±₹1) + date-proximity (±5 days) matching. This fallback is what
   makes the agent resilient to `utr_mismatch`.
3. Recompute the *textbook-correct* TDS (0.1% of gross) and GST-on-MDR
   (18% of `mdr_fee`) from the settlement's own reported `gross_amount`
   and `mdr_fee`, and diff against what the settlement actually deducted.
4. Any bank-credit delta not explained by the TDS/GST discrepancies is
   reported as an unattributed amount discrepancy (catches
   `amount_mismatch`).
5. Deltas under ₹0.05 total are treated as rounding noise and not
   flagged (this is the mechanism that gives a 0% false-positive rate
   against the `rounding_noise` red herring in this reference
   implementation).

It exists to prove the benchmark is falsifiable: a benchmark that ships
only a data generator, with nothing able to attempt it, has no evidence
it produces signal. The baseline's own score gradient across tiers
(observed: ~100% → 96% → 96% issue-detection recall, attribution accuracy
~100% → 79-83% → 87-90% across easy/medium/hard on seed 42) is itself part
of the benchmark's credibility case — harder tiers should be, and are,
measurably harder for the same fixed agent.

## 5. Scoring methodology

`scorer/score.py` computes two independent metric families per tier,
because a reconciliation agent can fail at either step separately:

**Matching** (did the agent decide the right transactions are linked at
all — matched vs. genuinely unreconciled):
`precision`, `recall`, `f1` over the binary "is this transaction
matched?" decision.

**Issue detection** (for transactions with a real underlying data-quality
issue, did the agent flag it, and attribute the right cause):
`precision`, `recall`, `f1`, `false_positive_rate` (flagging a record
ground truth says was actually clean — this is what catches an agent
that's too trigger-happy), and `attribution_accuracy` (did the flagged
`issue_type` match ground truth, crediting `"multiple"` on genuine
overlap records).

## 6. Known limitations / v2 candidates

- Ground truth records only one canonical `issue_type` string per record
  even under overlap; the scorer works around this by pattern-matching
  the `notes` field rather than a proper multi-label ground truth. A v2
  schema could make `issue_type` a list.
- No `split_settlement` / multi-vendor commission chain modeling, no UPI
  sub-rail interchange fee modeling, and no multi-aggregator chargeback
  attribution — these are the deepest India-specific gaps identified
  in research but were deprioritized for a single-weekend build in favor
  of getting three issue types fully, defensibly correct rather than six
  shallow ones.
- No LLM-based agent is included; the rule-based baseline is a floor,
  not a ceiling. Comparing an LLM agent's score against this baseline on
  the same datasets is the natural "before/after proof of value" demo.
