# CashPilot (Small Business Financial Intelligence)

**A finance-first cash-flow copilot for small merchants.** Record sales, purchases and payments cleanly, monitor financial health and liquidity risk, see a forecasted cash gap with its causes, surface capital tied up in slow stock before assuming new borrowing, test affordability and recovery scenarios, and view a transparent financial-readiness profile.

> **Design principle:** the backend calculates every number. The AI only calls approved tools and explains their results. It never invents or computes financial figures, and the system never issues a formal credit score or lending approval decision.

---

## Contents

1. [Problem](#1-problem)
2. [Features](#2-features)
3. [Tech stack](#3-tech-stack)
4. [Architecture](#4-architecture)
5. [Data model](#5-data-model)
6. [Financial rules](#6-financial-rules)
7. [AI advisor](#7-ai-advisor)
8. [API reference](#8-api-reference)
9. [Frontend pages](#9-frontend-pages)
10. [Repository structure](#10-repository-structure)
11. [Build plan](#11-build-plan)
12. [Testing](#12-testing)
13. [Demo script](#13-demo-script)
14. [Getting started](#14-getting-started)
15. [Limitations and future work](#15-limitations-and-future-work)

---

## 1. Problem

Small merchants often track sales in notebooks or memory. A shop can look profitable while running out of cash because:

- Credit sales have not been collected yet (revenue is not cash).
- Supplier payments are due soon.
- Money is tied up in slow-moving stock.
- Shortages are noticed only when they become urgent.

**Goal:** improve business records, show where cash is vs. where it is committed, surface a forecasted cash gap and its causes early, unlock capital trapped in slow stock before assuming new borrowing, and present a transparent financial-readiness profile.

*This is a decision-support tool. It is not an accounting system, a formal credit score, a lending approval decision, or financial advice.*

---

## 2. Features

| # | Feature | What the merchant gets |
|---|---|---|
| 1 | **Ledger** | Record sales, purchases, expenses, returns, partial payments, and opening balances for cleaner records |
| 2 | **Dashboard & Readiness** | Cash on hand, receivables, payables, slow-stock value flagged, financial-readiness profile, and alerts |
| 3 | **Cash-Flow Radar** | 7/14/30-day forecast, estimated cash gap, shortage date, and ranked cause drivers |
| 4 | **Stock insights** | Slow-moving stock, days of stock, trapped capital flagged before borrowing, and reorder risk |
| 5 | **AI Advisor** | Chat that answers affordability and liquidity questions from tool results with cited evidence |
| 6 | **Scenario Lab** | Baseline vs. alternatives (collect dues, delay payment, reorder less, planned purchase) with projected cash improvement |

**Supported businesses:** one shared data model with two seeded demo businesses, a **grocery shop** and a **service business**. A `track_inventory` flag and an optional `expiry_date` cover the differences. There are no per-industry rule engines.

---

## 3. Tech stack

| Layer | Choice |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, Recharts, TanStack Query |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy |
| Database | PostgreSQL (local install or a free hosted instance such as Neon or Supabase) |
| AI | Gemini function calling behind a thin `llm.py` wrapper |
| Money | Python `Decimal` and `NUMERIC` columns, never floats |
| Auth | JWT authenticates the user; the backend resolves `business_id` from the current user and filters every query |
| Tests | Pytest for the financial services and tenant isolation |

Single FastAPI application, single database, no message queue, no microservices.

---

## 4. Architecture

```mermaid
flowchart LR
    UI[React app] --> API[FastAPI]
    API --> LEDGER[Ledger service]
    API --> ENGINE[Finance engine<br/>cash, dues, stock, readiness,<br/>cash gap forecast, scenarios, impact]
    API --> ADVISOR[Advisor<br/>one LLM + read-only tool loop]
    ADVISOR --> TOOLS[Tool registry]
    TOOLS --> ENGINE
    LEDGER --> DB[(PostgreSQL)]
    ENGINE --> DB
```

| Component | Responsibility |
|---|---|
| **Ledger service** | Validates and posts transactions, payments, returns, and stock movements |
| **Finance engine** | Deterministic Python functions for cash, dues, slow-stock capital, financial-readiness signals, cash-gap forecast, scenario deltas, and internal-capital-first recommendations |
| **Advisor** | One LLM loop that picks typed, read-only tools, receives JSON, and explains liquidity, affordability, and readiness without inventing numbers or recommending borrowing prematurely |
| **Number check** | After the model answers, code verifies every figure in the text appears in a tool result. On mismatch it retries once, then falls back to the raw tool output |
| **Frontend** | Displays backend values, readiness breakdowns, and scenario impact deltas only; never calculates balances |

---

## 5. Data model

Eleven tables. Every business-owned table carries `business_id`. IDs are UUIDs and money is `NUMERIC(19,4)`.

| Table | Key fields |
|---|---|
| `users` | email, password_hash, name |
| `businesses` | owner_id, name, vertical (`grocery`/`service`/`other`), currency, min_cash_reserve, slow_stock_days_threshold |
| `customers` | business_id, name, phone |
| `suppliers` | business_id, name, phone |
| `products` | business_id, name, sku, kind (`goods`/`service`), unit, track_inventory, reorder_level, sale_price, avg_cost, expiry_date? |
| `transactions` | business_id, type (`sale`/`purchase`/`expense`/`sale_return`/`purchase_return`), original_transaction_id?, customer_id?, supplier_id?, date, due_date?, total, discount, status (`posted`/`void`), idempotency_key?, notes |
| `transaction_items` | transaction_id, product_id?, qty, unit_price, unit_cost_snapshot |
| `cash_movements` | business_id, date, signed_amount (+in / −out), kind (`opening`/`payment`/`refund`/`manual`), transaction_id? (null = opening cash or manual entry), idempotency_key?, note |
| `inventory_movements` | business_id, product_id, date, qty_delta, unit_cost, type (`opening`/`purchase`/`sale`/`return`/`adjust`), transaction_id? |
| `scheduled_events` | business_id, direction, label, amount, expected_on, certainty (`confirmed`/`expected`), status (`active`/`completed`/`cancelled`), transaction_id? |
| `advisor_logs` | business_id, user_id, question, answer, tools_called (JSON), created_at |

**Modelling rules**
- A payment is a `cash_movement` linked to a transaction. Partial payments are several movements on one transaction.
- Posted transactions are never edited. Corrections use a return (`original_transaction_id`) or adjustment record.
- Forecast obligations and expected collections are derived directly from open transaction balances (`total − returns − payments`), not copied into `scheduled_events`. `scheduled_events` holds manual items only (e.g., rent, wages, planned purchases).
- Cash comes only from `cash_movements`, and stock only from `inventory_movements`.
- Opening receivables and payables in v1 can be entered as backdated credit transactions (known limitation: they appear in historical sales/purchases).
- Forecasts and scenarios are computed on request, not stored.

---

## 6. Financial rules

These are implemented first and covered by tests.

```text
Cash on hand      = Σ cash_movements.signed_amount
Customers owe     = Σ posted sales − Σ payments linked to sales − Σ sale returns
We owe suppliers  = Σ posted purchases − Σ payments linked to purchases − Σ purchase returns
On-hand quantity  = Σ inventory_movements.qty_delta
Stock value       = on-hand quantity × weighted-average cost
Daily velocity    = units sold in last 30 days ÷ 30
Days of stock     = on-hand quantity ÷ velocity   (undefined if velocity = 0)
Net sales         = gross sales − discounts − returns
Gross profit      = net sales − Σ (qty × unit_cost_snapshot)
Gross margin %    = gross profit ÷ net sales
```

### Cash-flow forecast & cash gap

For each day: `closing cash = opening cash + inflows − outflows`

| Source | Examples |
|---|---|
| **Confirmed** | Open supplier payables due (derived from ledger; overdue payables `due_date <= as_of` land on day 1), active manual scheduled expenses (rent, wages) |
| **Expected** | Open customer receivables with `due_date > as_of` (derived from ledger; overdue receivables `due_date <= as_of` stay out of baseline inflows) |
| **Estimated** | Baseline daily cash inflows (14-day moving average of **same-day** cash sales) and baseline daily cash outflows (14-day moving average of **same-day** cash purchases, expenses, and refunds) — excluding opening cash and later settlements of prior credit transactions |

- A credit sale is never counted as cash until it is paid.
- Overdue means `due_date <= as_of`. Overdue payables land conservatively on day 1, while overdue receivables are excluded from baseline inflows and surfaced as gap causes/scenarios.
- Days where closing cash falls below `min_cash_reserve` are flagged.
- **Estimated cash gap:** `max(0, min_cash_reserve − min_projected_cash)` (gap vs. reserve) and `max(0, −min_projected_cash)` (gap vs. zero), returned with `lowest_cash_date`, `lowest_cash_amount`, and `gap_window`.
- With fewer than 14 days of history, the forecast is labelled **limited data**.
- Each day is returned split by source so the UI can colour confirmed, expected, and estimated amounts differently.
- **Cash gap cause:** the largest outflows and overdue/missing inflows leading up to the first shortage date. Slow-stock capital is surfaced separately as **unlockable capital** (a mitigation), not a cause of the gap.

### Scenarios & measurable impact

Each scenario copies the baseline inputs, applies one change, reruns the same forecast, and returns both projections plus measurable impact deltas (`projected_cash_improvement`, `gap_reduction`, and `reserve_breach_days_avoided`).

| Scenario | Change applied |
|---|---|
| Collect dues | X% of overdue customer dues arrive earlier |
| Delay payment | A supplier payment or purchase moves back N days |
| Reorder less | A planned reorder quantity drops by X% |
| Planned purchase (affordability) | A new purchase/outflow of amount X on date D tests whether cash stays above `min_cash_reserve` |

### Transparent financial-readiness profile

Computed deterministically in `readiness.py` from real records — **not** a formal credit score or lending approval decision. Returns each dimension's green/amber/red status, underlying evidence figures, and concrete actions to improve it:

| Dimension | What it measures |
|---|---|
| **Record completeness** | Opening cash set, days of history (`data_coverage`), transactions linked to parties and due dates |
| **Liquidity & reserve buffer** | Cash on hand vs. `min_cash_reserve`, projected cash gap, days until reserve breach |
| **Receivables & payables balance** | Overdue customer dues ratio and near-term supplier obligation concentration |
| **Working-capital efficiency** | Stock value flagged as slow-moving (`days_of_stock >= slow_stock_days_threshold` or zero recent sales) |
| **Affordability resilience** | Whether cash + expected collections absorb upcoming obligations without breaching reserve |

### Rule-based recommendations (internal capital first)

| Condition | Suggestion |
|---|---|
| Overdue customer dues and a projected cash gap | Collect these dues before considering external borrowing |
| Slow stock, high stock value flagged, many days of stock | Pause or reduce the next reorder to release trapped working capital before borrowing |
| Large supplier payment inside a cash-gap window | Negotiate or delay that payment |

Each recommendation compares the `estimated_cash_gap` against trapped internal capital (`slow_stock_value_flagged` + overdue receivables) and shows the issue, evidence, suggested action, estimated impact (or "not quantifiable"), and limitations.

---

## 7. AI advisor

The advisor has read-only, tenant-scoped, Pydantic-validated tools:

| Tool | Returns |
|---|---|
| `get_cash_position` | Cash on hand and reserve |
| `get_receivables` / `get_payables` | Totals, overdue amounts, top parties |
| `forecast_cash(days)` | Daily projection, estimated cash gap, shortage date, cause |
| `get_slow_stock` | Slow items, stock value flagged, days of stock |
| `get_financial_readiness` | Transparent readiness profile, evidence, and record-quality gaps |
| `get_product_margin` | Margin by product |
| `get_profit_summary` | Net sales, gross profit, expenses |
| `run_scenario(type, params)` | Baseline vs. scenario projection and projected cash improvement (including `planned_purchase` affordability) |
| `get_data_coverage` | Days of history, missing information |

**Response shape (JSON):** `summary`, `figures`, `evidence` (tool names and record ids), `assumptions`, `limitations`.

**Safety rules**
- The advisor cannot write to the ledger, and never issues a formal credit score or loan approval decision.
- Always surface trapped internal capital (slow stock + overdue receivables) before suggesting external borrowing.
- Merchant notes are treated as untrusted text, never as instructions.
- Every tool call is logged to `advisor_logs`.
- Missing data produces a qualified answer, not a guess.

**Example:** *"Can I afford a 15,000 purchase?"* The advisor calls `get_cash_position`, `get_payables`, `get_receivables`, `get_slow_stock` and `run_scenario("planned_purchase", ...)`, then reports whether cash covers it, the lowest projected balance and its date, whether trapped stock capital should be freed first, and whether the stock is actually needed.

---

## 8. API reference

All endpoints are under `/api/v1` and require a JWT, except register and login. Every query is filtered by the `business_id` resolved from the authenticated user.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | Account access |
| GET / POST | `/business` | Get or create business |
| GET / POST | `/customers`, `/suppliers`, `/products` | Master data |
| GET / POST | `/transactions` | List, or create and post (server recalculates totals) |
| POST | `/transactions/{id}/payments` | Record a payment |
| POST | `/cash/opening` | Set opening cash |
| GET | `/dashboard` | Cash, dues, slow-stock value flagged, estimated cash gap, readiness summary, alerts |
| GET | `/readiness` | Transparent financial-readiness profile with evidence and improvement actions |
| GET | `/cashflow/forecast?days=7\|14\|30` | Forecast, estimated cash gap, and shortage cause |
| GET | `/inventory` | Stock table with slow-stock flags and trapped capital |
| GET | `/profitability` | Margins |
| POST | `/scenarios` | Run a scenario and return baseline vs. simulated projections and projected cash improvement |
| POST | `/advisor/ask` | Question in, answer and tools used out |
| POST | `/dev/seed` | Load demo data (development only) |

Interactive docs are served at `/docs` by FastAPI.

---

## 9. Frontend pages

| Page | Contents |
|---|---|
| **Dashboard** | KPI cards (including estimated cash gap & slow-stock value flagged), forecast chart, transparent financial-readiness profile, shortage alert, top internal-capital-first recommendations |
| **Ledger** | Add sale, purchase, expense, or payment; transaction list |
| **Parties** | Customers and suppliers with balances |
| **Inventory** | Products, quantity, value, days of stock, slow-stock flags and trapped capital |
| **Advisor** | Chat with "tools used / evidence" under each answer |
| **Scenario Lab** | Pick a scenario (including planned purchase affordability), edit inputs, compare baseline vs. simulated charts and projected cash improvement |

Settings (currency, minimum reserve) is a small modal. Every number shows its currency and period. Actual, expected, estimated, and simulated values use distinct colours.

---

## 10. Repository structure

```text
small-business-financial-intelligence/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app and router registration
│   │   ├── config.py            # Environment settings
│   │   ├── db.py                # Engine and session
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── schemas.py           # Pydantic schemas
│   │   ├── auth.py              # JWT and business scoping
│   │   ├── routers/             # auth, master data, ledger, reports, advisor
│   │   ├── services/
│   │   │   ├── ledger.py        # Posting, payments, returns, stock movements
│   │   │   ├── finance.py       # Cash, dues, stock, margins
│   │   │   ├── readiness.py     # Transparent financial-readiness profile
│   │   │   ├── forecast.py      # Forecast and shortage cause
│   │   │   ├── scenario.py      # Four scenarios (collect dues, delay payment, reorder less, planned purchase)
│   │   │   └── recommend.py     # Rule-based recommendations
│   │   ├── advisor/
│   │   │   ├── llm.py           # Gemini wrapper
│   │   │   ├── tools.py         # Tool registry mapped to services
│   │   │   └── agent.py         # Tool loop and number check
│   │   └── seed.py              # Grocery and service demo data
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/               # Dashboard, Ledger, Parties, Inventory, Advisor, ScenarioLab
│       ├── components/
│       ├── api.ts
│       └── main.tsx
├── .env.example
├── .gitignore
└── README.md
```

---

## 11. Build plan

Work is split into two parallel tracks so one to three people can build at once: **Backend (B)** and **Frontend (F)**. A solo builder follows the same phase order. Hour estimates are indicative.

### Phase overview

| Phase | Focus | Est. hours | Track | Done when |
|---|---|---|---|---|
| **0** | Setup | 2 | B + F | Backend serves `/docs`, frontend runs, both connect to the database |
| **1** | Auth and data foundation | 3 | B | Register, login, create business, `business_id` filter works; response schemas frozen |
| **2** | Ledger | 5 | B | Sale, purchase, expense, partial payment, return, and opening balances post correctly |
| **3** | Seed data | 2 | B | `seed.py` populates the demo businesses via the ledger service and validates posting |
| **4** | Finance engine (`finance.py`) and tests | 5 | B | Cash, dues, slow-stock capital, profitability, coverage, and invariants pass |
| **5** | Forecast and cash gap (`forecast.py`) | 4 | B | 7/14/30-day forecast returns confirmed, expected, same-day estimated parts, cash gap, and cause |
| **6** | Readiness, recommendations, and Core UI | 10 | B + F | `readiness.py`, `/dashboard`, `/readiness`, `recommend.py`, and Core UI pages work against the API |
| **7** | AI advisor | 5 | B + F | Chat answers using tools and shows tools used |
| **8** | Scenario Lab | 4 | B + F | Scenarios (including planned purchase affordability) compare against baseline with impact deltas |
| **9** | Recommendations | 2 | B + F | Rule-based actions appear on the dashboard |
| **10** | Polish and demo rehearsal | 4 | All | The demo script runs end to end without errors |
| **11** | Deploy (optional) | 2 | All | Public URL works |

Phases 0–6 are the **must-have core**. Phases 7–9 are the **differentiators**. Phases 10–11 make it presentable.

### Phase detail

**Phase 0: Setup.** Create the repository structure, a Python virtual environment, `npm create vite`, the database, and `.env`. Confirm the frontend can call a `/health` endpoint.

**Phase 1: Auth and data foundation.** Create models and tables. Implement register and login with hashed passwords and JWT. Add a dependency that resolves the current user's `business_id` and use it in every query. Freeze response schemas for dashboard, forecast, readiness, and scenarios early so frontend work can run in parallel.

**Phase 2: Ledger.** Implement `ledger.py`: create and post transactions idempotently with server-side totals, create inventory movements with cost snapshots and `with_for_update` stock locking, record payments as cash movements, handle returns linked via `original_transaction_id`, and set opening cash and stock. Forecast events are derived from open balances rather than duplicated into `scheduled_events`.

**Phase 3: Seed data.** Build a deterministic, date-relative `seed.py` using the ledger service right after Phase 2 works so it doubles as an integration test for posting. Size the grocery business first (strong sales, a large supplier payment due in about nine days, uncollected credit sales, and slow stock whose flagged value exceeds the cash gap); add the service business only after the grocery story passes.

**Phase 4: Finance engine.** Implement `finance.py` from the rules in section 6 (cash, receivables, payables, slow-stock capital flagged, profitability, and data coverage with consistent `as_of` filtering). Write tests with hand-calculated expected values before moving on.

**Phase 5: Forecast & cash gap.** Implement `forecast.py`: same-day 14-day moving averages, derived open balances (overdue payables on day 1, overdue receivables excluded), active manual scheduled events, 30-day simulation sliced for 7/14/30, estimated cash gap (`vs_reserve` and `vs_zero`), shortage cause, unlockable capital, and the limited-data label.

**Phase 6: Readiness, recommendations & Core UI.** Implement `readiness.py` (pure threshold-based green/amber/red function), `recommend.py` (internal capital first), `/dashboard`, and `/readiness`, then build the layout, navigation, Dashboard, Ledger forms, Parties, and Inventory UI.

**Phase 7: AI advisor.** Wrap Gemini in `llm.py`, register the tools (including `get_financial_readiness`), implement the tool loop with limits and the number check, and build the chat UI with a tools-used panel.

**Phase 8: Scenario Lab.** Implement the scenarios in `scenario.py` (including `planned_purchase` affordability and `projected_cash_improvement` impact deltas), expose `/scenarios`, and build the side-by-side chart.

**Phase 9: Recommendations.** Implement the internal-capital-first rules in `recommend.py` (highlighting slow stock and overdue dues before borrowing) and display them on the dashboard with their evidence.

**Phase 10: Polish.** Add loading, empty, and error states. Check currency and period labels. Rehearse the demo script and fix anything that breaks.

**Phase 11: Deploy.** Host the backend (for example Render or Railway) and the frontend (for example Vercel or Netlify) with a hosted PostgreSQL instance. Keep API keys on the backend only.

### Suggested split for a team of three

| Person | Phases |
|---|---|
| **Backend lead** | 1, 2, 3, 4, 5 |
| **Frontend lead** | 0, 6, then 8 and 9 (UI side) |
| **AI and integration** | 7, then 8 and 9 (backend side), 10 |

### If time runs short, cut in this order

1. Deployment (demo from localhost)
2. Recommendations
3. Second demo business
4. Scenario types (keep only "collect dues")
5. Charts polish

**Never cut:** ledger correctness tests, the forecast, and the advisor's tool-grounded answers.

---

## 12. Testing

| Case | Expected result |
|---|---|
| Cash sale | Revenue and cash both increase |
| Credit sale | Revenue and receivable increase, cash unchanged |
| Partial customer payment | Receivable drops by the amount paid, cash rises by the same amount |
| Credit purchase | Payable and stock increase, cash unchanged |
| Partial supplier payment | Payable and cash both drop by the amount paid |
| Sales return | Revenue, stock, and receivable are reversed |
| Large upcoming obligation | Forecast drops on its due date |
| Missing opening cash | Dashboard shows "incomplete data" |
| Duplicate payment submission | Counted once |
| Another business's id in a request | Rejected, no data returned |

**Invariants:** on-hand quantity equals the sum of movements, each cash movement is counted exactly once, and a payment is never double-counted with its scheduled event.

**Advisor checks:** a fixed list of questions with the expected tools and expected figures. Verify that the answer numbers match tool output and that limitations are disclosed.

Run with `pytest backend/tests`.

---

## 13. Demo script

Three minutes, using the seeded grocery shop, measured by **estimated cash gap identified**, **slow-stock value flagged**, and **projected cash improvement**:

1. **Dashboard:** strong sales, but an estimated cash gap identified in about nine days alongside a transparent financial-readiness profile.
2. **Warning & trapped capital:** the gap cause is a supplier payment, uncollected dues, and slow-stock value flagged (showing internal capital to unlock before considering borrowing).
3. **Advisor:** ask *"Why could I run out of cash next week?"* and show the grounded answer with tools used.
4. **Advisor:** ask *"Can I afford a 15,000 purchase?"* and show the affordability check, lowest projected balance, and assumptions.
5. **Scenario Lab:** compare collect dues, delay payment, and reorder less against the baseline, highlighting the projected cash improvement.
6. **Ledger:** record a partial customer payment and watch the cash gap, readiness profile, and forecast update.

---

## 14. Getting started

**Requirements:** Python 3.11+, Node.js 20+, PostgreSQL 15+ (or a hosted instance), a Gemini API key.

```bash
# 1. Configuration
cp .env.example .env
# set DATABASE_URL, JWT_SECRET, GEMINI_API_KEY

# 2. Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload    # http://localhost:8000/docs

# 3. Seed demo data (new terminal)
curl -X POST http://localhost:8000/api/v1/dev/seed

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

**`.env.example`**

```text
DATABASE_URL=postgresql://user:password@localhost:5432/fin_intel
JWT_SECRET=change-me
GEMINI_API_KEY=your-key
```

Tables are created automatically on startup. There are no migrations in this version.

---

## 15. Limitations and future work

**Current limitations**
- One currency per business. No multi-currency or exchange rates.
- Operational ledger for decision support, not double-entry accounting.
- Forecasts are baseline estimates and need history to be reliable. Short history is labelled.
- The advisor is read-only and cannot change records.
- Forecasts are labelled estimates. There is no guarantee that any suggested action prevents a shortage or increases profit.
- Demo data is synthetic. Passwords are hashed and API keys stay on the backend.

**Future work**
- Multi-agent orchestration on top of the existing tool registry
- Background jobs and scheduled alerts, with streaming task updates
- Batch, expiry, and serial tracking and more merchant profiles
- CSV import, receipt scanning, bank and POS integrations
- Formal double-entry accounting and migrations
- Anonymized benchmarking across merchant cohorts