# OctoProc M4 — Vendor Reconciliation & Closure

A standalone prototype for **Module 4** of the OctoProc MRO management platform.
Upload a CSV of purchase, receipt and invoice lines; the system reconciles them
deterministically, auto-closes clean matches, and routes every exception to a
human whose decision is permanently auditable.

**Live:** https://octo-snowy.vercel.app

This project is independent of the existing MRO codebase. It shares no code,
database or deployment with it.

---

## How it works

```
upload CSV → validate → stage → map columns → normalize
           → reconcile → results → human review → decision log
```

One CSV row describes a single item across all three documents — what was
ordered, what arrived, what was billed. Normalization fans each row out into
separate purchase order, GRN and invoice records, all linked back to the staging
row they came from, so any decision in the audit log is one join away from the
exact line of the file that produced it.

### The two rules everything else follows from

**Reconciliation is deterministic.** No model is involved anywhere in the
verdict path. Same data plus same tolerances always yields the same result —
which is what makes a human sign-off meaningful rather than an argument with a
black box.

**The system's verdict is never overwritten.** `reconciliation_results.system_status`
is written once by the engine. Human outcomes are *appended* to `decision_log`,
and `current_status` is derived from the newest one. The original machine
judgment stays recoverable no matter how many times a person overturns it.

---

## Reconciliation rules

| ID | Check | Tolerance |
|----|-------|-----------|
| R1 | PO reference present and resolvable | — |
| R2 | PO quantity vs GRN quantity | `qty_tolerance_abs`, `qty_tolerance_pct` |
| R3 | GRN quantity vs invoice quantity | same |
| R4 | PO unit price vs invoice unit price | `price_tolerance_pct` |
| R5 | Tax consistency (`qty × price × rate`) | `tax_tolerance_abs` |
| R6 | Duplicate invoice line | exact |
| R7 | Record completeness | — |

Statuses resolve by first-match-wins precedence:

```
INCOMPLETE → DUPLICATE → MISMATCH → REVIEW → MATCHED
```

`MATCHED` then auto-closes to `AUTO_CLOSED`, recorded as a system decision.

Two behaviours worth knowing:

- **R6 keys on `(vendor, invoice_number, item)`.** The same invoice number across
  different items is a normal multi-line invoice and is not flagged — keying on
  invoice number alone would raise false exceptions on most real files.
- **A skipped check downgrades to REVIEW, never MATCHED.** "We could not verify
  this" must not read as "this is clean."

Tolerances are frozen onto each reconciliation run, so a result stays explainable
even after the configured defaults change.

---

## CSV format

Required: `po_number`, `vendor`, `item`, `po_quantity`, `grn_quantity`,
`invoice_quantity`, `po_unit_price`, `invoice_unit_price`

Optional: `invoice_number`, `tax`, `po_date`, `grn_date`, `invoice_date`,
`vendor_code`, `item_code`, `currency`

Column names need not match exactly — common variants (`PO No.`, `Ordered Qty`,
`Received Qty`, `GST Amount`, …) resolve automatically through a fixed alias
table, and anything unrecognised can be mapped by hand on the Mapping screen.

Download a template from `/api/v1/template.csv`, or see [`sample-data/`](sample-data/).

---

## Running locally

Requires Python 3.12+, Node 22+, and a Postgres connection string.

```bash
cp .env.example .env          # fill in DATABASE_URL (pooled) and DIRECT_URL

python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/alembic upgrade head

./.venv/bin/uvicorn app.main:app --reload    # :8000
cd frontend && npm install && npm run dev    # :5173, proxies /api to :8000
```

```bash
./.venv/bin/pytest tests/ -q                 # 57 tests
```

Tests run against the database in `DIRECT_URL`, each inside a transaction that is
rolled back, so nothing is left behind.

---

## Deployment

One Vercel project serves both halves from a single origin, so there is no CORS
configuration to get wrong:

- `/api/*` → a Python serverless function (`api/index.py`) wrapping the FastAPI app
- everything else → the built SPA from `frontend/dist`

Environment variables (set in Vercel, never committed):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | **Pooled** connection. Mandatory — serverless spawns many short-lived invocations, and a direct connection per invocation exhausts the database's connection limit. |
| `DIRECT_URL` | Unpooled. Used by Alembic only; the pooler runs in transaction mode and cannot execute session-level DDL. |

Migrations are an explicit release step, run locally — Vercel builds have no
Alembic hook:

```bash
./.venv/bin/alembic upgrade head
```

---

## What this prototype deliberately does not do

No authentication (the acting user is an `X-Actor` header). No AI or ML anywhere.
No queues or background workers. No ERP integrations — CSV is the only input. No
multi-tenancy. No cross-run duplicate detection. No FX conversion. No other MRO
modules.

Uploads are capped at **4.5 MB** by the Vercel request-body limit, and raw files
are stored in Postgres because serverless functions have no persistent disk.

See [DESIGN.md](DESIGN.md) for the full architecture and the reasoning behind it.
