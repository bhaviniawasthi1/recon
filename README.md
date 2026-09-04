# ReconArena

**The arena where India's reconciliation agents prove themselves.**

Built for the **Razorpay AI Buildathon** — Open Track (05).

> ReconArena is not a reconciliation agent. It is infrastructure for
> *testing* one — the way ImageNet is infrastructure for testing an image
> classifier, not a classifier itself.

---

## The problem

Every fintech team building a reconciliation agent — matching a customer
transaction against an aggregator settlement against a bank credit —
ships it on vibes. A handful of manually-checked spreadsheets, a demo
that works on the happy path, and a hope that it holds up in production.
There is no standard, scored, India-specific way to answer the question
that actually matters: **how good is this agent, really, and how much
money would it have missed?**

ReconArena answers that question. It generates realistic, deliberately
broken Indian payment data across three linked ledgers, ships a known
correct answer for every record, and scores any agent's output against
it — precision, recall, false-positive rate, attribution accuracy, and a
rupee-value figure for exactly how much leakage the agent caught versus
missed.

## What it does, in one picture

```
generator/            →  three linked, deliberately messy datasets
  (India-specific        (Transaction · SettlementRecord · BankStatementEntry)
   messiness injectors)     +  ground_truth.json (the answer key, withheld from agents)

        ↓

baseline_agent/       →  two reference agents attempt every tier
  smart agent             (rule-based UTR fallback + textbook tax/fee recompute)
  naive agent             (exact-match only — models a weak real-world system)

        ↓

scorer/                →  score · rank on a leaderboard · rupee-value impact
  score.py, leaderboard.py, impact.py

        ↓

dashboard/index.html   →  a self-contained, deployable explorer for all of it
```

## The four India-specific failure modes it tests

Global reconciliation benchmarks model generic ledger/invoice mismatches.
Indian payment stacks add layers those tools never touch. ReconArena
implements four of them with full, calculable ground truth:

| Issue type | Real-world cause |
|---|---|
| **UTR mismatch** | Bank statement narrations truncate, garble, or batch the UTR the settlement report cites — a naive exact-string match fails even though the money genuinely moved. |
| **TDS miscalc (Sec 194O)** | Marketplace sellers are paid net of 0.1% TDS; settlement systems sometimes apply the old 1% rate, skip it, or double-deduct it. |
| **GST-on-MDR miscalc** | 18% GST applies to the gateway's own transaction fee, not the order itself — this line is sometimes omitted, folded silently into the MDR fee, or charged at the wrong rate. |
| **Vendor commission miscalc** | Multi-vendor marketplace settlements deduct the vendor's contracted commission (8–20% of gross) before computing net payout — systems sometimes apply a stale rate, a flat default rate, or skip the deduction entirely. |

Two structural issue types round out the taxonomy — `missing_settlement`
(never reconciles at all) and `amount_mismatch` (a post-settlement
refund/chargeback bite unrelated to tax logic) — plus a `rounding_noise`
**red herring** in the medium/hard tiers that a correct agent must *not*
flag, which is what makes false-positive rate a meaningful metric rather
than a formality.

## Three difficulty tiers, by design

| Tier | Records | Clean ratio | Overlapping issues | Red herrings |
|---|---|---|---|---|
| Easy | 30 | 42% | never | none |
| Medium | 45 | 27% | 20% of issue records | 10% |
| Hard | 60 | 18% | 35% of issue records | 20% |

Difficulty isn't cosmetic — it's engineered to produce a real capability
gradient, which is exactly what the leaderboard below demonstrates.

## The Arena: two agents, one leaderboard

A benchmark that only ever scores one agent can prove a task is
*solvable*. It can't prove the benchmark *discriminates* between agent
quality. So ReconArena ships two deterministic reference agents and
ranks them against each other on the identical datasets:

| Rank | Agent | Strategy | Overall score |
|---|---|---|---|
| 🥇 1 | **Rule-based reference agent** (`baseline_agent/agent.py`) | UTR exact-match with an amount/date fallback + textbook TDS/GST/commission recomputation | **0.9959** |
| 🥈 2 | **Naive exact-match agent** (`baseline_agent/naive_agent.py`) | Exact UTR string match only, no fallback, no recomputation — models what a lot of real, unsophisticated systems still run | **0.4564** |

That's not a rounding difference — it's the gap between an agent that
actually reconciles and one that only handles the happy path. The naive
agent silently misses **every single** tax/fee/commission miscalculation
and any UTR that doesn't match character-for-character, because it never
attempts to recompute or fall back. The benchmark catches that.

### Why this matters more than the score itself

We didn't just build infrastructure and claim it works — we tested it
against a real agent, and in doing so **caught and fixed real bugs in our
own ground truth**: a `hash()`-based seed that silently broke
reproducibility across runs, and a sign error in the reference agent's
tax-discrepancy attribution that was double-counting TDS/GST deltas.
Without dogfooding the benchmark against a working agent, both bugs would
have shipped silently and the answer key itself would have been wrong.
That's the proof, not just the claim.

## Rupee-value impact — what leakage actually costs

Scores are abstract. Money isn't. `scorer/impact.py` converts every
ground-truth issue into its rupee value and reports what each agent
actually caught:

| Agent | At-risk value | Caught | Missed | Caught % |
|---|---|---|---|---|
| Rule-based reference agent | ₹16,98,372.31 | ₹16,70,688.01 | ₹27,684.30 | **98.37%** |
| Naive exact-match agent | ₹16,98,372.31 | ₹0.00 | ₹16,98,372.31 | **0.00%** |

Across the sample datasets alone, the gap between a reconciliation agent
that actually works and one that doesn't is **over ₹16.9 lakh** of
undetected leakage. That's the number a judge — or a merchant risk team —
actually cares about.

## Model-agnostic by design

ReconArena ships two deterministic, rule-based reference agents on
purpose — it keeps the benchmark reproducible and free to run for anyone
grading a submission. But the leaderboard's agent contract
(`scorer/leaderboard.py`'s `AGENTS` registry) only requires an agent to
consume a tier's `transactions.json` / `settlements.json` /
`bank_statement.json` / `vendor_rates.json` and emit verdicts in one
fixed schema (`payment_id`, `verdict`, `issue_type`, `explanation`).

Any agent that meets that contract — rule-based, classical ML, or
LLM-based — plugs directly into the leaderboard and scorer with **zero
changes to ReconArena itself**. This demo intentionally stays free and
deterministic; a production LLM-based reconciliation agent — Razorpay's
own included — could be benchmarked here as-is.

## Interactive dashboard

`dashboard/index.html` is a single self-contained HTML file (no backend,
no build step) that turns the scored results into an explorer:

- **Explorer view** — filter by tier, agent (smart vs. naive), verdict,
  and injected issue type; free-text search by payment ID; a
  mismatches-only toggle.
- **Scorecards** — overall accuracy, matching F1, issue recall,
  attribution accuracy, false-positive rate, and the ₹-impact card
  (caught vs. at-risk) per tier, live.
- **Row detail** — expand any transaction to see its full
  Transaction → Settlement → Bank Statement trail side by side, with the
  ground-truth expected verdict against what the agent actually
  concluded.
- **Live Run** — a button that re-executes the reconciliation logic
  entirely client-side, in JavaScript, against the raw embedded data —
  proving the scored numbers aren't just baked into a static report.
- **Leaderboard view** — the smart-vs-naive ranking above, rendered live
  from the same embedded data.

Deploys to Vercel with zero configuration (`vercel.json` is already set
up, `outputDirectory: dashboard`) — see `dashboard/README.md` for the
one-command deploy and how to regenerate the embedded data bundle after
rerunning the benchmark.

## Quickstart

No third-party dependencies — Python 3.10+ standard library only.

```bash
# Run the full pipeline: generate -> both agents -> leaderboard -> impact -> HTML report
python3 run_benchmark.py --out report.html
```

Or step by step:

```bash
python3 -m generator.generate_dataset --seed 42 --out datasets
python3 -m baseline_agent.agent --tier-dir datasets/easy
python3 -m baseline_agent.naive_agent --tier-dir datasets/easy
python3 -m scorer.score --tier-dir datasets/easy
python3 -m scorer.leaderboard --datasets-dir datasets
python3 -m scorer.report --datasets-dir datasets --out report.html
```

To browse the interactive dashboard locally, just open
`dashboard/index.html` in a browser (or serve the folder with any static
file server — no build step, no dependencies).

## Project structure

```
recon/
  schemas/
    models.py               -- Transaction, SettlementRecord, BankStatementEntry,
                                GroundTruthLabel, IssueType (the shared data model)
  generator/
    constants.py             -- India-specific rates: GST-on-MDR (18%), TDS (0.1% Sec 194O), MDR
    base_data.py              -- builds one arithmetically-correct, clean triple
    generate_dataset.py       -- CLI: assembles the three easy/medium/hard tiers
    messiness/
      utr_mismatch.py         -- UTR string-mismatch injector
      tds.py                   -- Sec 194O TDS miscalculation injector
      gst_mdr.py               -- GST-on-MDR miscalculation injector
      commission_chain.py      -- marketplace vendor-commission miscalculation injector
      structural.py            -- missing settlement, amount mismatch, rounding-noise red herring
  baseline_agent/
    agent.py                  -- the "smart" rule-based reference agent
    naive_agent.py             -- the deliberately weak reference agent
  scorer/
    score.py                  -- matching + issue-detection scoring for one agent, one tier
    leaderboard.py             -- ranks all registered agents against each other
    impact.py                  -- rupee-value leakage caught vs. missed, per agent
    report.py                  -- renders the static HTML score report
  dashboard/
    index.html                -- the self-contained interactive explorer (deployable)
    README.md                 -- Vercel deploy steps + how to regenerate the embedded bundle
  docs/
    architecture.md            -- full schema, messiness taxonomy, scoring methodology, known limitations
  run_benchmark.py            -- end-to-end pipeline: generate -> agents -> leaderboard -> impact -> report
  vercel.json                 -- static deploy config for dashboard/
```

## Who this is for

ReconArena doesn't serve the end merchant directly — it serves the teams
that build reconciliation agents *for* them: a payment platform's own
QA/eng teams validating an agent before it goes live, third-party
fintechs building reconciliation tooling on top of a payments API, and CA
firms or audit teams that need a repeatable way to check an automated
reconciliation process rather than trusting it blind.

## Known limitations

- Ground truth is synthetic, not sourced from real production data — by
  design, so it can ship publicly with no PII/compliance risk, but real
  production data has messiness patterns this generator doesn't yet model.
- Two reference agents are both deterministic/rule-based; no LLM-based
  agent is registered yet (see "Model-agnostic by design" above — the
  leaderboard is built to take one without modification).
- Tier sizes (30/45/60 records) are small enough to run instantly and
  score by hand-verification; a larger dataset would strengthen
  statistical confidence in the score gap.

See `docs/architecture.md` for the full design writeup, including the
complete messiness taxonomy and scoring methodology.

## License

MIT — see `LICENSE`.
