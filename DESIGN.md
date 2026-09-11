# M4 — Vendor Reconciliation & Closure · Prototype Design (Step 1)

**Status:** proposed, awaiting approval before Step 2
**Location:** `/home/yash/octoproc-m4/` — new, standalone. No dependency on `/home/yash/octoproc/`.
**Target:** fully hosted — Vercel (frontend + API) + managed Postgres
**Rule version at v0:** `m4-v0.1`

---

## 0. The one structural decision everything else follows from

The CSV is **flat**: one row carries PO, GRN and Invoice facts for a single item.
The required schema is **normalized**: six canonical tables across three documents.

So the core of ingestion is a **fan-out**. One staging row becomes:

```
row → vendor (upsert)
    → purchase_order (upsert, scoped to run) → purchase_order_line
    → grn            (synthesized header)    → grn_line       → links to PO line
    → invoice        (upsert by inv. number) → invoice_line   → links to PO line
```

Two consequences worth stating up front:

- **GRN headers are synthesized.** The CSV has no `grn_number` field, so each PO in a run gets one generated GRN header (`GRN-{run_id}-{po_number}`). Real GRN references become a field later without schema change.
- **Canonical records are scoped to the ingestion run.** `purchase_orders` is unique on `(ingestion_run_id, po_number)`, not on `po_number` alone. Step 9 requires independent repeatable runs; run-scoping is what makes re-uploading the same file safe instead of a collision. Cross-run identity resolution is an explicit Phase-2 upgrade, not a v0 concern.

`tax`, being on a per-item row, is treated as **line-level tax on the invoice line**; the invoice header carries the sum.

---

## 1. Prototype architecture

One Vercel project, one database. No third service.

```
              ┌──────────────── vercel.app (single origin) ────────────────┐
              │                                                            │
   browser ──▶│  /            → static SPA   (React + TS + Vite + Tailwind)│
              │  /api/*       → Python serverless function (FastAPI ASGI)  │
              └──────────────────────────┬─────────────────────────────────┘
                                         │ SQLAlchemy · pooled connection
                                         ▼
                              Managed Postgres (Neon / Supabase)
                                         │
                                         └── raw CSV bytes live here too
```

- **Single origin, therefore no CORS.** The SPA and the API are served from the same Vercel domain; `/api/*` rewrites to one Python function. This removes an entire class of deployment friction compared with two separately-hosted services.
- **Synchronous processing.** No queue, no worker. Prototype datasets are thousands of rows; a request-scoped pandas pass is the correct amount of machinery.
- **Staged, not one-shot.** Upload/validate/stage is one call. Normalize is a *second*, explicit call. Reconcile is a *third*. That separation is not ceremony — it's what makes the mapping-review step in the middle real rather than decorative, and it's what the UI's step flow maps onto.
- **The M4 engine never imports FastAPI.** All reconciliation, mapping and normalization logic lives in `app/modules/m4/` as plain Python over Pydantic models and SQLAlchemy sessions. Routes are a thin HTTP skin. This single constraint is what lets M4 be lifted into the larger MRO platform later without a rewrite.
- **No auth.** The acting user arrives as an `X-Actor` header supplied by a UI user-picker, and is persisted on every decision. Swapping in real auth means changing one dependency function.

### What serverless changes (and why)

| Constraint | Consequence | Resolution |
|---|---|---|
| **No persistent disk** — the function filesystem is ephemeral | `./storage/uploads/` cannot exist | Raw CSV bytes are stored in Postgres (`uploaded_files.content`). Keeps the audit trail intact, adds no fourth service. |
| **4.5 MB request body cap** | Upload size is bounded (~25–40k rows of this shape) | Explicit client-side *and* server-side guard with a plain-English error. Recorded as a known limitation. |
| **Function timeout** (10s default, configurable) | A very large file could exceed it | `maxDuration: 60` in `vercel.json`; bulk inserts, not row-by-row. |
| **Many short-lived invocations** | A direct Postgres connection per invocation exhausts the pool | **Pooled connection string** (Neon pooler / Supabase port 6543) + SQLAlchemy `NullPool`. This is the single most common way these deployments break. |
| **Migrations can't run in a deploy** | Alembic has no hook | `alembic upgrade head` runs locally against the remote DB as an explicit release step. |

**On pandas:** it inflates the bundle (~50 MB with numpy) and therefore cold starts. It stays, because `read_csv` handles encodings, BOMs and quoting robustly and that is genuinely load-bearing for "user uploads an arbitrary CSV". If cold starts become irritating, the swap to stdlib `csv` + `decimal` is contained to two files.

---

## 2. Folder structure

Vercel-native layout: the Python function at `/api`, the SPA in `/frontend`, one repo.

```
octoproc-m4/
├── README.md
├── DESIGN.md
├── vercel.json                     # routing, maxDuration, includeFiles, build cmd
├── requirements.txt                # python deps for the serverless function
├── .env.example                    # DATABASE_URL (pooled), DIRECT_URL (migrations)
├── api/
│   └── index.py                    # ASGI entry — `from app.main import app`
├── app/                            # backend package, bundled via includeFiles
│   ├── main.py                     # app factory, router mount
│   ├── config.py                   # pydantic-settings; tolerances, DB URLs
│   ├── database.py                 # engine (NullPool), SessionLocal, get_db
│   ├── models/
│   │   ├── base.py
│   │   ├── ingestion.py            # uploaded_files, ingestion_runs, staging_records
│   │   ├── canonical.py            # vendors, po/po_lines, grns/grn_lines, invoices/invoice_lines
│   │   └── reconciliation.py       # recon_runs, recon_results, decision_log
│   ├── schemas/                    # Pydantic request/response contracts
│   ├── api/
│   │   ├── router.py               # /api/v1
│   │   └── routes/
│   │       ├── health.py
│   │       ├── ingestion.py
│   │       ├── reconciliation.py
│   │       └── decisions.py
│   └── modules/m4/                 # ← the transplantable core
│       ├── column_map.py           # alias dictionary + deterministic resolver
│       ├── validation.py           # file / column / row-level validation
│       ├── normalize.py            # staging → canonical fan-out
│       ├── rules.py                # tolerance config, rule definitions, explanations
│       ├── engine.py               # deterministic reconciliation
│       └── decisions.py            # review + append-only decision service
├── alembic.ini
├── migrations/versions/            # run locally against DIRECT_URL
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json
│   └── src/
│       ├── main.tsx, App.tsx, routes.tsx
│       ├── api/client.ts           # typed fetch wrapper (same-origin /api/v1)
│       ├── types.ts                # mirrors backend schemas
│       ├── theme.css               # Tailwind v4 @theme tokens (§7)
│       ├── components/             # AppShell, Card, DataTable, StatusPill,
│       │                           # StatCard, Button, Drawer, FileDrop, FieldMapRow
│       └── pages/
│           ├── Overview.tsx
│           ├── Upload.tsx
│           ├── Mapping.tsx
│           ├── Results.tsx
│           ├── ResultDetail.tsx
│           └── DecisionLog.tsx
├── tests/
│   ├── test_validation.py
│   ├── test_mapping.py
│   ├── test_normalize.py
│   ├── test_engine.py
│   └── test_e2e.py
└── sample-data/
    ├── template.csv
    ├── clean.csv                   # all matched
    ├── messy-headers.csv           # alias-heavy column names
    ├── exceptions.csv              # every exception type
    └── invalid.csv                 # fails validation deliberately
```

**Local development** runs `uvicorn` + `vite dev` (with a `/api` proxy) against the *same* managed Postgres — so there is no local database to install and no drift between dev and deployed behaviour. If the provider is Neon, dev gets its own branch.

---

## 3. Data flow

```
① POST /ingestion/uploads  (multipart, ≤ 4.5 MB)
   → persist raw bytes + metadata to uploaded_files (sha256, size, filename)
   → create ingestion_run (status=UPLOADED)
   → pandas parse
   → resolve columns against alias dictionary
   → structural validation
        ├─ required canonical field unresolved → 422 + detected mapping
        │                                          + unmapped columns
        │                                          + expected template
        │                                          run.status = FAILED_VALIDATION
        └─ ok ↓
   → row-level validation (types, negatives, zero quantities, blanks)
   → write EVERY row to staging_records (raw JSON + mapped JSON + errors[])
   → run.status = STAGED
   → return { mapping, unmapped_columns, row_error_summary, preview }

② PUT /ingestion/runs/{id}/mapping        [optional, only if user overrides]
   → re-resolve, re-validate, rewrite staging, return updated mapping

③ POST /ingestion/runs/{id}/normalize
   → fan-out valid rows into canonical entities (§0)
   → rows with blocking errors are NOT normalized, but are carried forward
     so they still surface later as INCOMPLETE — they never silently vanish
   → run.status = NORMALIZED

④ POST /reconciliation/runs   { ingestion_run_id, tolerances? }
   → create reconciliation_run with rule_version + frozen tolerance snapshot
   → engine evaluates each (PO line, GRN line, Invoice line) triple
   → one reconciliation_result per staging row  ← 1:1 trace back to the CSV row
   → MATCHED results auto-close, writing a SYSTEM row to decision_log
   → run.status = RECONCILED, counts by status stored

⑤ GET results → user opens an exception → POST /decisions
   → appends to decision_log (never mutates system_status)
   → result.current_status is recomputed from the latest decision
```

**Traceability chain, end to end:**

```
uploaded_files → ingestion_runs → staging_records → canonical lines
              → reconciliation_results → decision_log
```

Every `reconciliation_result` holds `staging_record_id`, so the original CSV row is always one join away from any decision in the audit log.

---

## 4. Minimum database entities

All thirteen tables, with the columns that matter. UUID PKs, `created_at` everywhere.

| Table | Key columns |
|---|---|
| `uploaded_files` | original_filename, **content** (BYTEA — no disk on serverless), content_type, size_bytes, sha256, uploaded_by |
| `ingestion_runs` | uploaded_file_id → , status, source_filename, row_count, valid_row_count, error_row_count, **column_mapping** (JSONB), normalized_at |
| `staging_records` | ingestion_run_id → , row_number, **raw_data** (JSONB), **mapped_data** (JSONB), is_valid, **errors** (JSONB) |
| `vendors` | vendor_code, name, normalized_name · unique `(ingestion_run_id, normalized_name)` |
| `purchase_orders` | ingestion_run_id → , po_number, vendor_id → , po_date, currency · unique `(ingestion_run_id, po_number)` |
| `purchase_order_lines` | purchase_order_id → , line_number, item, item_code, quantity, unit_price, staging_record_id → |
| `grns` | ingestion_run_id → , grn_ref *(synthesized)*, purchase_order_id → , grn_date |
| `grn_lines` | grn_id → , purchase_order_line_id → , item, quantity, staging_record_id → |
| `invoices` | ingestion_run_id → , invoice_number, vendor_id → , purchase_order_id → , invoice_date, tax_total, currency |
| `invoice_lines` | invoice_id → , purchase_order_line_id → , item, quantity, unit_price, tax, staging_record_id → |
| `reconciliation_runs` | ingestion_run_id → , **rule_version**, **tolerances** (JSONB snapshot), status, started_at, completed_at, **status_counts** (JSONB) |
| `reconciliation_results` | reconciliation_run_id → , staging_record_id → , po_line_id → , grn_line_id → , invoice_line_id → , **system_status** *(immutable)*, **current_status**, **findings** (JSONB), explanation (text) |
| `decision_log` | reconciliation_result_id → , actor, action, from_status, to_status, reason, rule_version, is_system, decided_at |

**The immutability guarantee:** `reconciliation_results.system_status` is written once by the engine and never updated. Human outcomes live only as appended `decision_log` rows; `current_status` is a derived convenience column recomputed from the newest decision. The original machine verdict is therefore permanently recoverable — which is the entire point of an audit log.

---

## 5. API boundaries

`/api/v1`

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | service + DB connectivity |
| GET | `/schema` | required/optional fields + known aliases (drives UI help text) |
| GET | `/template.csv` | CSV template download |
| POST | `/ingestion/uploads` | multipart CSV → validate → stage |
| GET | `/ingestion/runs` | run history |
| GET | `/ingestion/runs/{id}` | run detail: mapping, counts, validation summary |
| GET | `/ingestion/runs/{id}/rows` | staged rows, paginated, `?invalid_only=true` |
| PUT | `/ingestion/runs/{id}/mapping` | manual column mapping override |
| POST | `/ingestion/runs/{id}/normalize` | staging → canonical |
| POST | `/reconciliation/runs` | execute engine (optional tolerance override) |
| GET | `/reconciliation/runs` | list |
| GET | `/reconciliation/runs/{id}` | summary + status counts |
| GET | `/reconciliation/runs/{id}/results` | paginated, `?status=`, `?q=` |
| GET | `/reconciliation/results/{id}` | full detail: raw row, three-way values, every check, decision history |
| POST | `/decisions` | `{result_id, action, reason}` → append |
| GET | `/decisions` | audit log, filterable by run/actor/action |
| GET | `/config/tolerances` | current defaults |

**Boundary rule:** routes handle HTTP, validation of the request envelope, and serialization — nothing else. Every business operation is a function in `modules/m4/`.

---

## 6. M4 reconciliation responsibilities

### Checks

| ID | Check | Tolerance | Absent-data behaviour |
|---|---|---|---|
| R1 | PO reference present & resolvable | — | fail → INCOMPLETE |
| R2 | PO qty vs GRN qty | `qty_abs`, `qty_pct` | — |
| R3 | GRN qty vs Invoice qty | `qty_abs`, `qty_pct` | — |
| R4 | PO unit price vs Invoice unit price | `price_pct` | — |
| R5 | Tax consistency | `tax_abs` | skipped with reason if `tax` not supplied |
| R6 | Duplicate invoice line | exact | skipped if `invoice_number` absent |
| R7 | Completeness — required values present, numeric, non-negative, qty > 0 | — | — |

**R5 (tax)** — computed as `expected = invoice_quantity × invoice_unit_price × expected_tax_rate`, compared against the supplied `tax` within `tax_abs`. *This is the one rule where the brief ("tax where available") leaves the semantics open, and I've inferred them — flagged for confirmation.*

**R6 (duplicate)** — key is `(vendor_normalized, invoice_number, item_normalized)`. The same `invoice_number` across *different* items is a legitimate multi-line invoice and is **not** flagged; only a repeated line identity is. First occurrence keeps its real verdict; later occurrences become DUPLICATE. Scoped within the run at v0.

### Status resolution — first match wins

```
1. INCOMPLETE   required data missing / unparseable / PO reference unresolvable
2. DUPLICATE    R6 hit
3. MISMATCH     any hard check outside tolerance
4. REVIEW       all checks pass, but variance non-zero within tolerance,
                or a check was skipped for missing optional data
5. MATCHED      everything exact
```

Then closure policy: `MATCHED` + `auto_close_matched` → `current_status = AUTO_CLOSED`, with a SYSTEM row in `decision_log`. All six required statuses are produced; `system_status` stays the assessment, `AUTO_CLOSED` is a closure state on top of it.

### Default tolerances (configurable, snapshotted per run)

```python
qty_tolerance_abs   = 0
qty_tolerance_pct   = 0.0
price_tolerance_pct = 0.5
tax_tolerance_abs   = 1.00
expected_tax_rate   = 0.18
auto_close_matched  = True
rule_version        = "m4-v0.1"
```

### Every finding carries

`rule_id · label · expected · actual · variance · variance_pct · tolerance_applied · passed · explanation`

Explanations are **templated strings**, not generated text — e.g.
`"Invoice quantity 100 exceeds GRN quantity 98 by 2 units (2.04%), outside the 0-unit tolerance."`

### Explicitly not M4's job

Fuzzy vendor/item matching · learning from past decisions · payment execution · GL posting · fetching from ERPs.

---

## 7. Frontend screens

| # | Screen | Contents |
|---|---|---|
| 1 | **Overview** | Status tiles from the latest reconciliation run; run history table (ingestion + recon, status, rows, timestamp); primary CTA to upload. All live data. |
| 2 | **Upload Dataset** | Drop zone; template download; required vs optional field reference; on failure, an inline panel naming exactly what's wrong, which rows, and the expected format. |
| 3 | **Validation / Mapping** | `detected column → canonical field` table with match source (exact / alias / unmapped); per-column dropdown override; unmapped & ignored columns; row-error list; "Confirm mapping & normalize". |
| 4 | **Reconciliation Results** | Status tiles; dense filterable table — PO, vendor, item, PO/GRN/Inv qty, prices, variance, status pill; filter by exception type; row click-through. |
| 5 | **Reconciliation Detail** | Three-column PO / GRN / Invoice comparison; per-rule check list with pass/fail and explanation; the original CSV row verbatim; decision panel (approve / reject / resolve / override + reason); decision history for that result. |
| 6 | **Decision Log** | Append-only audit table — timestamp, actor, result ref, action, system status, resulting status, reason, rule version; filterable. |

### Visual tokens — taken from the live octoproc.com stylesheet

The site is **Tailwind v4 + Inter**, and its accent is the **teal** scale — not a bespoke green. Matching it therefore needs no colour guesswork: the same framework and the same token names reproduce it exactly.

One correction to the brief worth recording: **there is no navy on the site.** Headings are `gray-900`; the dark surfaces are `teal-900`/`teal-800`, a deep blue-green that reads as navy but isn't. We follow the site, not the description.

```
font      Inter
surface   white            page bg     gray-50
ink       gray-900         ink-muted   gray-600 / gray-500
border    gray-200         radius      md (6px) · lg (8px)
accent    teal-600         accent-dark teal-700
                           accent-soft teal-50 / teal-100
deep      teal-900         (sidebar / header)

MATCHED / AUTO_CLOSED  teal-600
REVIEW                 blue-600
MISMATCH               amber-700
DUPLICATE              red-600
INCOMPLETE             gray-500
```

**Deliberate divergence from the marketing site:** octoproc.com uses `rounded-2xl`/`3xl`, teal gradients (`from-teal-600 → to-teal-400`) and `shadow-xl`. Those are landing-page traits. The application takes the palette and typography but drops them in favour of `rounded-md`/`lg`, flat teal fills and `shadow-sm` — which is what the brief means by "restrained rounded corners" and "do not build a marketing website". Same brand, different register.

Dense tables, no gradients, no hero sections, no marketing copy. Every number on screen comes from an API call.

---

## 8. What is intentionally NOT included

- **No auth, roles or SSO** — actor is a UI-selected name on a header
- **No AI / ML / LLM in the reconciliation path** — column mapping and every rule are deterministic (see §9)
- **No queues or background workers** — synchronous, bounded by the function timeout
- **No ERP or API integrations** — CSV upload is the only input path
- **No other MRO modules**
- **No multi-tenancy or org model**
- **No object storage** — raw files live in Postgres; uploads capped at 4.5 MB by the platform
- **No fuzzy matching** beyond case/whitespace normalization of vendor and item names
- **No cross-run duplicate detection** at v0 (schema supports it; explicit Phase 2)
- **No payment execution, GL posting, or notifications**
- **No FX conversion** — currency is captured, never converted
- **No post-normalization editing of canonical data** — re-upload instead
- **No Kubernetes, microservices, Kafka, containers, or CI/CD** — Vercel build + a manual Alembic step is the whole release process

---

## 9. Where models do and don't belong

**v0 uses no models at all.** The brief is explicit twice over — "deterministic reconciliation rules, not AI/ML" and "deterministic mappings, not an LLM" — and that is the right call: an auditable reconciliation engine whose verdicts a human signs off on must be reproducible, and a model in that path would make every exception arguable.

So a Groq OSS model has exactly two places it could earn its keep, both *outside* the engine:

| | Where | What it does | Why it stays safe |
|---|---|---|---|
| **A** | Column mapping fallback | When a header matches no alias, propose a canonical field | The deterministic dictionary always wins; the model only sees the unmatched remainder, and its output is a **suggestion the user confirms** on the Mapping screen — never silently applied |
| **B** | Exception narration | Turn the templated findings into a plain-English paragraph on the detail screen | Presentation only; the stored `findings` and `explanation` remain templated and authoritative |

**(A) is the one with real value** — it directly attacks the "we got a CSV with headers nobody anticipated" failure mode, which is the most likely reason a demo stalls. **(B) is decoration** over explanations that are already readable.

Recommendation: ship v0 deterministic as specified, add (A) as a flagged enhancement once the pipeline is proven. Awaiting your call on whether to bring (A) into scope now.

---

## 10. Deployment

| | |
|---|---|
| **Hosting** | One Vercel project. `vercel.json` rewrites `/api/*` to the Python function; everything else serves the SPA build. |
| **Build** | `cd frontend && npm run build` → `frontend/dist`. Python function built from root `requirements.txt`. |
| **Database** | Managed Postgres (Neon or Supabase). Two URLs: `DATABASE_URL` (**pooled** — used by the app) and `DIRECT_URL` (unpooled — used by Alembic only). |
| **Migrations** | `alembic upgrade head` run locally against `DIRECT_URL`, as an explicit release step before deploy. |
| **Secrets** | Vercel project environment variables. Nothing in the repo; `.env.example` documents the shape. |
| **Environments** | Vercel preview deploys per push; production on the main branch. Neon branching gives dev its own database if that's the provider. |

---

## Open items before Step 2

**Resolved:** tax rule R5 confirmed · visual language extracted from the live site (§7) · hosting target set to Vercel + managed Postgres.

**Still needed:**

1. **Postgres connection strings** — the **pooled** URL (Neon pooler host, or Supabase port `6543`), and ideally the direct URL for migrations. A direct-only URL will exhaust connections under serverless.
2. **How I deploy to Vercel.** `/home/yash` is not a git repository, so neither path exists yet:
   - a `VERCEL_TOKEN` → I deploy straight from the CLI, no GitHub needed *(fastest)*
   - or I `git init` and you give me a GitHub remote to push to, then connect it in Vercel
3. **Groq scope** — deterministic-only for v0, or include mapping fallback (A) in §9? A Groq API key is only needed if (A) is in.
