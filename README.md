# Investment Mandate Compliance Monitor

Topic 5 group project: extract investment constraints from documents, check holdings and proposed trades, explain breaches, and verify remediation proposals.

## Quick start

Run from this project directory:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local URL printed in the terminal. The teaching demo runs without an API key.

Generate a demonstration report:

```bash
python cli.py demo
```

Check a standardized input bundle:

```bash
python cli.py check --bundle data/demo/bundle.json --document data/demo/mandate.txt
```

## Four-step interface

1. **Documents and rules** — Upload the prospectus, SAI and supplements together, then specify the target fund. Alternatively select the downloaded ESGU PDFs. Claude reads all text in overlapping chunks of 30,000 characters with a 1,500-character overlap. Each chunk requires an API call. Review the candidates in the table, including evidence, fund applicability, limits, denominators, timing, exceptions and effective dates. Set `approved` and `needs_review` appropriately, identify the reviewer, confirm coverage, and send the rules to step 2.
2. **Holdings and trade checks** — Upload an original iShares holdings CSV or the standard CSV template provided in the interface. The downloaded ESGU holdings can also be selected. Add supplemental reference data if needed. Enter positive USD amounts for buys and negative amounts for sells, plus fees. The engine checks current holdings and the simulated adjusted portfolio automatically. Leave trades empty to check current holdings only.
3. **Explanation and remediation** — View the engine-generated sales-to-cash proposal without using an API, or ask Claude for a plain-English explanation and structured remediation trades. The engine independently accounts for the proposed trades and rechecks all rules. Download the report, audit, and Claude proposal.
4. **Public resources** — Access the official source links and downloaded documents.

Normal web use does not require writing or assembling JSON. The CLI bundle remains available for reproducible testing.

Pre-trade clearance uses the simulated post-trade portfolio. After actual execution, upload updated actual holdings to verify the realized portfolio. No orders are sent to a broker.

Changing the documents or target fund invalidates previously confirmed rules. Changing holdings or trades hides outdated Claude proposals. Teaching demo mode provides a separate, fully populated offline workflow.

## Rule review and extraction failures

All model candidates start unapproved and require review. Full-text coverage does not guarantee that every relevant constraint was correctly identified. Cross-document amendments, duplicate candidates, conflicts and exceptions require human interpretation.

Quotes that cannot be located verbatim are retained as quarantined candidates with `evidence_verified=false`. They do not stop the remaining extraction, but they cannot support automatic clearance. Correct the evidence from the source before approving them. Do not delete difficult rules merely to obtain a PASS.

Failed requests or malformed responses identify the failing chunk and offer a diagnostic download without the API key. Successful chunks remain in the current Streamlit session and are reused on retry. Do not refresh or close the browser if you need to retain this in-memory progress. A previously failed quotation response can be reprocessed without another request when it remains available in the session.

## Inputs

The standard holdings CSV contains:

```text
security_id,market_value,asset_type,as_of,currency,issuer_id,sector,rating,esg_excluded,source
```

The required columns are `security_id`, `market_value`, `asset_type`, `as_of` and `currency`. Use one valuation date per file and USD market values. Cash rows use `asset_type=Cash`.

Supplemental reference CSV columns:

```text
security_id,issuer_id,sector,asset_type,rating,esg_excluded,as_of,source
```

Use the same `issuer_id` for different securities of a single issuer. ESG flags must be `true`, `false` or blank. Missing reference information is not inferred from company names. Templates are available in step 2. Provide reference records for any new securities you intend to buy.

## Teaching demonstration

`data/demo/mandate.txt` is an explicitly synthetic investment mandate, not a real fund document. All securities and reference attributes in the demo are fictional. The rules take effect on January 1, 2026 and apply continuously:

| Rule | Requirement |
|---|---|
| Issuer concentration | At most 25% of NAV, aggregating all securities of an issuer |
| Sector concentration | At most 40% of NAV |
| Cash | At least 5% of NAV |
| Prohibited security | TOBACCO |
| Prohibited asset types | Future, Option, Swap |
| Bond rating | At least BBB-, using one rating field |
| ESG exclusion | esg_excluded=true is prohibited; a missing value is not a pass |

Initial NAV is $1,000,000, cash is $100,000, and the valuation date is October 23, 2026.

| Measure | Before trades | After proposed trades | After remediation |
|---|---:|---:|---:|
| ALPHA issuer weight (two share classes) | 20% | 35% | 25% |
| Technology sector weight | 35% | 50% | 40% |
| Cash weight | 10% | 1% | 15% |
| TOBACCO market value | $0 | $40,000 | $0 |
| Overall status | PASS | FAIL | PASS |

Proposed trades sell $100,000 of BOND-A, buy $150,000 of ALPHA-A and buy $40,000 of TOBACCO. The engine remediation sells $100,000 of ALPHA exposure, allocated proportionally between ALPHA-A and ALPHA-B, then sells the $40,000 TOBACCO position. All rules are checked again.

## Claude integration

Enter an Anthropic API key and a model ID available to your account in the sidebar. Alternatively set `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` in the environment. `.env.example` is a reference only; the application does not automatically load `.env` files.

- API calls occur only when the corresponding Claude button is clicked and may incur charges.
- Extraction sends document text; explanation sends the current report, including holdings.
- Keys are not included in exported reports or diagnostics.
- Claude is instructed to write descriptions, explanations and rationale in English. Evidence remains a verbatim quotation in the source language.
- Document hashes and source quotations are checked. A matching quotation does not prove a correct interpretation.
- Model proposals are restricted to existing holdings. Invalid trades, oversells and insufficient cash are rejected; valid trades are simulated and independently rechecked.
- Audit records include model ID, prompt, raw response, token usage and source hashes.
- Automated tests mock the API. They do not measure actual model extraction accuracy.

Text-based PDF, TXT and Markdown documents are supported, up to 20 MB per document. PDF parsing uses pypdf or the system `pdftotext` fallback. Scanned documents require OCR first. The web workflow processes long documents in chunks without silently truncating them. The legacy single-document helper retains its 100,000-character limit but is not used by the current web flow.

## Public materials

Official URLs, file sizes and SHA256 values are recorded in `data/public/manifest.json`.

- `esgu_prospectus.pdf`: US ESG series prospectus and supplements that include ESGU.
- `esgu_sai.pdf`: multi-fund iShares Trust Statement of Additional Information. Confirm which provisions apply to the target fund.
- `esgu_holdings.csv`: official ESGU holdings dated October 23, 2026 in the file header.
- `rejected/`: an unrelated emerging-markets prospectus retained as an excluded-source record. It is not used in checks.

Public documents are kept separate from the synthetic mandate. The importer retains coverage gaps for unsupported asset types, including futures with zero market value but nonzero notional exposure. Such gaps remain unresolved after remediation. Public holdings alone do not supply complete issuer, credit-rating or ESG reference data. This project does not claim to have completed a comprehensive real-fund ESGU compliance assessment.

## Calculation scope and statuses

- USD-denominated, long-only cash, equities and ordinary bonds. NAV equals cash plus security market values; no borrowing or liabilities.
- Trades are signed USD market-value amounts at fixed snapshot prices, not share quantities. Buys consume cash, sells add cash and fees reduce NAV.
- Batches settle on a net basis; intraday execution ordering is not modeled. Oversells and insufficient net cash are rejected.
- Issuer limits aggregate multiple securities; cash is not issuer or sector exposure.
- Reference data may be up to 30 calendar days old. Future-dated and missing values cannot establish compliance.
- Limits are inclusive, with a numerical comparison tolerance of 1e-8.
- **PASS**: passed under the reviewed rules, coverage declaration, supplied data and assumptions.
- **FAIL**: at least one confirmed breach.
- **UNKNOWN**: missing/stale reference data or unsupported exposure prevents a determination.
- **REVIEW**: unapproved or unverified rules, inapplicable dates, incomplete coverage, or complex interpretation requirements.
- Overall precedence is FAIL > UNKNOWN > REVIEW > PASS. Detailed findings preserve all unresolved items.
- Derivatives, purchase-only conditions, complex denominators and exceptions are not automatically cleared.
- Remediation is a sales-to-cash heuristic, not portfolio optimization. It assumes zero fees, no slippage and fractional dollar amounts. It is verified only if all checks return PASS. Recheck actual execution prices and costs.

## Files and outputs

```text
app.py                   Streamlit interface
cli.py                   Command-line report entry point
mandate/models.py        Input and rule schemas
mandate/documents.py     Document extraction, hashing and evidence validation
mandate/imports.py       Multi-document packaging and holdings CSV import
mandate/llm.py           Claude extraction, explanation and proposals
mandate/engine.py        Deterministic checks, accounting and remediation
mandate/workflow.py      Workflow, English HTML report and audit exports
data/demo/               Synthetic mandate and input bundle
data/public/             Official documents, holdings and provenance manifest
tests/                   Engine, import, API-contract and interface tests
outputs/                 Reports, diagnostics and test results
```

Each CLI report run creates an output directory with `report.html`, `audit.json` and `proposed_remediation.json`. The HTML report includes current holdings checks, proposed trades, simulated post-trade checks, remediation and verification. It can be printed to PDF using a browser. Audit files contain the inputs, evidence, findings and hashes. No report constitutes comprehensive legal compliance certification.

## Verification

```bash
python -m unittest discover -s tests -v
```

Tests cover issuer aggregation, boundary limits, fee reconciliation, oversells, insufficient cash, duplicates, ratings, missing ESG data, stale/future references, document changes, evidence quarantine, approval gates, HTML escaping, import coverage, chunk resumption, model proposal verification and the four-step interface. Passing synthetic tests is not evidence of real-world extraction accuracy.
