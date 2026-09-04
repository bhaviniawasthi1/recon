# ReconArena Explorer (dashboard)

A single self-contained `index.html` — the interactive UI for browsing the
baseline agent's verdicts against ground truth across the easy/medium/hard
tiers. All dataset JSON (transactions, settlements, bank statement, ground
truth, agent output for all 3 tiers) is embedded directly in the page at
build time, so it needs no backend, API, or build step to deploy.

## Regenerating this file after the datasets change

If you rerun `run_benchmark.py` at the repo root and the datasets change,
this file goes stale (it has last run's data baked in). Regenerate it with:

```bash
python3 - << 'PYEOF'
import json, pathlib
bundle = {}
for tier in ["easy", "medium", "hard"]:
    d = pathlib.Path("datasets") / tier
    bundle[tier] = {
        "transactions": json.loads((d/"transactions.json").read_text()),
        "settlements": json.loads((d/"settlements.json").read_text()),
        "bank_statement": json.loads((d/"bank_statement.json").read_text()),
        "ground_truth": json.loads((d/"ground_truth.json").read_text()),
        "agent_output": json.loads((d/"agent_output.json").read_text()),
    }
html = pathlib.Path("dashboard/index.html").read_text()
import re
new_payload = json.dumps(bundle, separators=(",", ":"))
html = re.sub(
    r'(<script id="bundle-data" type="application/json">)(.*?)(</script>)',
    lambda m: m.group(1) + new_payload + m.group(3),
    html, flags=re.S,
)
pathlib.Path("dashboard/index.html").write_text(html)
print("updated dashboard/index.html")
PYEOF
```

## Deploying to Vercel

From the **repo root** (not this folder):

```bash
npm i -g vercel   # one-time
vercel login      # one-time
vercel --prod
```

`vercel.json` at the repo root points Vercel at this folder
(`outputDirectory: dashboard`) with no build step — it's plain static HTML,
so there's nothing to compile. Accept the default project settings when
prompted (Framework Preset: **Other**).

Or, without the CLI: go to vercel.com → **Add New Project** → import this
GitHub repo → in the project's **Build & Development Settings**, set
**Output Directory** to `dashboard` and **Build Command** to empty →
Deploy.
