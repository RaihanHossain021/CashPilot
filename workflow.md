# CashPilot End-to-End System Workflow & Manual Verification Guide

This document explains how **CashPilot** works from startup to finish across every layer—environment configuration, authentication, ledger accounting, inventory, deterministic financial analytics, cash-flow forecasting, readiness scoring, rule-based recommendations, the interactive Scenario Lab, and the tool-grounded AI Advisor—along with a structured **checkpoint-by-checkpoint manual testing playbook** and recommended improvements.

---

## 1. High-Level Architecture & Data Flow

CashPilot follows a **finance-first, AI-assisted** architecture where **all numbers come deterministically from PostgreSQL and Python financial services**, never from LLM guesses or client-side math.

```text
[React + Vite UI (5173)]
        │  Bearer JWT + /api/v1 proxy
        ▼
[FastAPI Backend (8000)]
  ├── Auth & Tenant Gate: get_current_user / get_current_business_id
  ├── Write Layer (Ledger & Master Data):
  │     Products, Customers, Suppliers, Transactions, Payments, Opening Cash/Stock
  │         │  Writes immutable CashMovements & InventoryMovements
  │         ▼
  ├── Deterministic Read Engines (Read-Only):
  │     ├── finance.py   -> cash position, receivables, payables, stock velocity, P&L
  │     ├── forecast.py  -> 7/14/30d daily cash trajectory, reserve gaps, causes
  │     ├── readiness.py -> 4-dimension green/amber/red profile + evidence
  │     ├── scenario.py  -> ephemeral forecast overrides (zero DB writes)
  │     └── recommend.py -> ranked internal-capital-first actions + scenario links
  └── AI Advisor Layer (advisor/agent.py + advisor/tools.py):
        ├── Gemini function-calling loop (max 6 tool calls, tenant-scoped)
        ├── Backend-resolved figures & normalized number-check guardrail
        ├── Deterministic template fallback (200 OK if API key missing/fails)
        └── Audit logging in AdvisorLog
```

### Core System Guarantees
- **Tenant isolation:** `business_id` is always derived from the JWT (`owner_id == current_user.id`) via `get_current_business_id`. Client payloads and advisor tools cannot supply or override `business_id`.
- **Single source of truth (`as_of`):** Analytics default to server `dt.date.today()`. Scenario Lab and AI Advisor always lock `as_of` on the server.
- **No double-counting:**
  - Opening cash uses upsert semantics in `POST /api/v1/cash/opening`.
  - Daily forecast baseline (`forecast.py`) averages *same-day* operating cash movements (`CashMovement.date == Transaction.date`, excluding `kind == "opening"`) over the prior 14 days, then overlays exact open receivables/payables and active `ScheduledEvent` outflows separately.
- **Idempotency:** Transactions and payments include client-generated `idempotency_key` values enforced by partial unique indexes so retries never double-post.

---

## 2. Pre-Flight Checkpoints (Setup & Boot)

### Checkpoint 0: Environment & Database Verification
**How it works:**
Backend settings are loaded from `.env` at the repo root (`ENVIRONMENT`, `DATABASE_URL`, `TEST_DATABASE_URL`, `JWT_SECRET`, `JWT_EXPIRE_HOURS`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `ADVISOR_TIMEOUT_SECONDS`, `ADVISOR_RATE_LIMIT_PER_MIN`). On FastAPI startup (`lifespan` in `backend/app/main.py`), SQLAlchemy calls `check_db_connection()` and runs `Base.metadata.create_all(bind=engine)` if PostgreSQL is reachable.

**Manual Test Steps:**
1. Verify PostgreSQL is running and databases (`fin_intel`, `fin_intel_test`) exist.
2. Confirm `.env` exists at `d:\hackathon 3.2\CashPilot\.env` with valid PostgreSQL credentials and (optionally) a valid `GEMINI_API_KEY`.
3. Start the backend server:
   ```powershell
   backend\.venv\Scripts\uvicorn.exe app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
   ```
4. Start the frontend dev server in a second terminal:
   ```powershell
   npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
   ```
5. Check backend health in your browser or terminal:
   - Open `http://127.0.0.1:8000/health` (expected: `200 OK`, `{"status":"ok","database":"connected"}`).
   - Open `http://127.0.0.1:8000/docs` (expected: Swagger UI loads all endpoints).
   - Open `http://127.0.0.1:5173/` (expected: CashPilot login screen loads via Vite proxy).

---

## 3. Authentication, Onboarding & Demo Seeding Checkpoints

### Checkpoint 1: User Registration & Business Onboarding (Fresh Merchant Path)
**How it works:**
- `POST /api/v1/auth/register` hashes the password, creates a `User` with lowercase unique email, and returns a Bearer JWT (`access_token`).
- `App.tsx` stores the token (`localStorage`), calls `GET /api/v1/business`. When no `Business` exists yet (`404`), `App.tsx` displays **Step 2 of 2 · Business Profile** in `AuthPage.tsx`.
- Submitting **Create business workspace** calls `POST /api/v1/business` with `name`, `vertical` (`grocery` | `service` | `other`), `currency`, `min_cash_reserve`, and `slow_stock_days_threshold` (default `45`).

**Manual Test Steps:**
1. On `http://127.0.0.1:5173/`, click **Create account**.
2. Enter your name, a fresh email (e.g., `owner.test@cashpilot.local`), and password (`>= 8` characters), then click **Register & continue**.
3. Verify the **Step 2 of 2 · Business Profile** form appears.
4. Enter Business name (e.g., `Corner Store`), select `Grocery`, currency `BDT`, Min cash reserve `15000`, and click **Create business workspace**.
5. **Expected:** You enter the main `AppShell` workspace with header showing `Corner Store`, `grocery · BDT · Reserve 15,000`, and tabs: `Dashboard`, `Ledger`, `Parties`, `Inventory`, `Advisor`, `Scenario Lab`.
6. Click `Dashboard`:
   - **Expected:** `Incomplete data: set opening cash` badge appears because no opening cash exists yet.
   - **Expected:** **Readiness -> Record completeness** is `RED` (`opening_cash_set: false`).
   - **Expected:** **Recommended Actions** shows **only** `"Set your opening cash balance first"` (`SET_OPENING_CASH`) without gap-based recommendations and with no `Test in Scenario Lab →` button.
7. Click **Sign out** in the top right and sign back in using the **Sign in** tab with your newly created email/password. Verify you land directly on your workspace.

---

### Checkpoint 2: Development Demo Seeder (`FreshBasket Mart`)
**How it works:**
- Clicking **Load FreshBasket Mart Demo** triggers `POST /api/v1/dev/seed` (enabled only when `ENVIRONMENT=development`; returns `403` in production) and logs in as `grocery.demo@cashpilot.local` / `demo-password-123`.
- `seed_grocery_demo()` wipes only the existing `FreshBasket Mart` demo user/business (leaving any other merchant accounts untouched) and creates deterministic, date-relative records:
  - Opening cash at `today - 35`: `51,000 BDT`
  - 5 tracked products with opening stock at `today - 35`:
    - Fast movers: `Basmati Rice 5kg` (`RICE-5KG`), `Soybean Oil 2L` (`OIL-2L`), `Refined Sugar 1kg` (`SUGAR-1KG`)
    - Slow/non-moving luxury stock (`0` recent sales): `Imported Olive Oil Tin 2L` (`10 × 2,000 = 20,000 BDT`) and `Gourmet Saffron Gift Box` (`10 × 1,500 = 15,000 BDT`) -> **Total slow stock = `35,000 BDT`**
  - Overdue credit sales:
    - `Karim Traders` (`due today - 5`): `25,000` invoice, `5,000` paid -> **`20,000 BDT` overdue**
    - `Nadia Catering` (`due today - 2`): `20,000` invoice, `0` paid -> **`20,000 BDT` overdue**
    - **Total overdue dues = `40,000 BDT`**
  - Daily retail counter sales (`6,000/day` for 14 days = `84,000`) minus cash restock (`45,000`), rent (`15,000`), and wages (`10,000`) -> `+14,000` net (`+1,000/day`). Combined with `51,000` opening + `5,000` partial receipt = **`70,000 BDT` Cash on hand**.
  - Upcoming bulk supplier bill: `Metro Distribution` **`90,000 BDT`** due at `today + 9`.
  - Scheduled outflow event: `"Planned staple reorder"` **`2,500 BDT`** expected at `today + 12`.

**Manual Test Steps:**
1. Sign out of the fresh merchant account and click **Load FreshBasket Mart Demo** on `AuthPage`.
2. **Expected:** Logs into `FreshBasket Mart` (`grocery · BDT · Reserve 15,000`).
3. Keep `FreshBasket Mart` active for Checkpoints 3–11 below (or switch back to your custom merchant account to test manual ledger creation first).

---

## 4. Core Operational Checkpoints (Parties, Inventory & Ledger)

### Checkpoint 3: Master Data & Balances (`Parties` Tab)
**How it works:**
- `GET/POST /api/v1/customers` and `GET/POST /api/v1/suppliers` manage customer/supplier records scoped to the current business.
- `GET /api/v1/parties/balances` aggregates open balances, overdue amounts (`due_date < as_of`), and earliest due dates directly from posted transactions and cash movements.

**Manual Test Steps:**
1. Open the **Parties** tab.
2. Verify **Customers** lists `Karim Traders` (`20,000 BDT` owes you & overdue), `Nadia Catering` (`20,000 BDT` owes you & overdue), and `Walk-In Retail` (`0 BDT`). Both overdue customers display a red `Overdue` badge.
3. Switch to **Suppliers** toggle and verify `Metro Distribution` (`90,000 BDT` you owe, `0` overdue because it is due in 9 days) and `Padma Wholesale` (`0 BDT`).
4. Add a new customer (e.g., `Bhuiyan Hotel`, phone `01700-112233`) -> verify it immediately appears in the customer card grid with `0 BDT` balance due.

---

### Checkpoint 4: Product Catalog, Opening Stock & Velocity (`Inventory` Tab)
**How it works:**
- `GET/POST /api/v1/products` creates tracked goods or services (`sku` must be unique per business; duplicate SKU returns `409 Conflict`).
- `POST /api/v1/inventory/opening` inserts an `opening` `InventoryMovement` and recomputes quantity on hand.
- `GET /api/v1/inventory` calculates weighted-average cost (`avg_cost`), stock value (`on_hand_qty * avg_cost`), 14-day sales velocity (`qty_sold / 14`), `days_of_stock`, `low_stock` (`on_hand <= reorder_level`), and `slow_stock` (`stock_value > 0` and either `daily_velocity == 0` with no recent sales or `days_of_stock >= slow_stock_days_threshold`).

**Manual Test Steps:**
1. Open the **Inventory** tab on `FreshBasket Mart`.
2. Verify summary cards:
   - **Slow-stock value flagged:** `35,000 BDT` (`Imported Olive Oil Tin 2L` + `Gourmet Saffron Gift Box`).
   - **Velocity window / threshold:** `14d / >= 45d`.
3. Verify the table marks `Imported Olive Oil Tin 2L` and `Gourmet Saffron Gift Box` as **`No sales`** and **`Slow capital`**.
4. Under **Add product**, create a new product (e.g., `Green Tea Pack`, SKU `TEA-100`, Unit `box`, Sale price `300`, Initial cost `200`, Reorder level `5`).
5. Under **Record opening stock**, select `Green Tea Pack (TEA-100)`, Qty `10`, Unit cost `200`, and click **Post opening stock**.
6. **Expected:** Table refreshes showing `10 box` on hand, `2,000 BDT` stock value (and total stock value rises by `2,000 BDT`).

---

### Checkpoint 5: Ledger Entries, Opening Cash & Partial Payments (`Ledger` Tab)
**How it works:**
- `POST /api/v1/cash/opening` sets/updates opening cash without creating duplicate opening entries.
- `POST /api/v1/transactions` runs atomically inside one DB transaction:
  - Validates stock availability for tracked goods on sales/purchase returns (rolls back cleanly if insufficient stock).
  - Updates weighted-average cost on purchases, decrements/increments `InventoryMovement`, creates immediate `CashMovement` for `paid_amount`, and computes `total`, `amount_paid`, and `balance_due`.
- `POST /api/v1/transactions/{id}/payments` records partial/full settlements (`paid_amount` cannot exceed `balance_due`), is idempotent by `idempotency_key`, and immediately reduces party `balance_due` and `overdue_amount`.

**Manual Test Steps:**
1. Open the **Ledger** tab.
2. Test **Transactions Filters**: switch `All types` dropdown (`Sales`, `Purchases`, `Expenses`) and toggle **Unpaid only** -> verify only `Karim Traders`, `Nadia Catering`, and `Metro Distribution` appear when `Unpaid only` is checked.
3. Test **Posting a Sale**:
   - Select `sale`, choose customer `Bhuiyan Hotel` (created in Checkpoint 3), product `Basmati Rice 5kg`, Qty `2`, leave unit price blank (defaults to `600`), Paid now `500`, Discount `0`, Due date = tomorrow. Click **Post sale**.
   - **Expected:** New sale row appears (`Total: 1,200 BDT`, `Paid: 500 BDT`, `Balance due: 700 BDT`). Check **Inventory** (`Basmati Rice 5kg` drops by 2 bags) and **Parties** (`Bhuiyan Hotel` shows `700 BDT` owed).
4. Test **Partial Payment**:
   - Click **Record payment** on the `Bhuiyan Hotel` row (or `Karim Traders`), enter `300`, keep today's date, add note `Part payment`, and click **Confirm payment**.
   - **Expected:** Row `Paid` increases by `300`, `Balance due` drops by `300`, and **Cash on hand** on the Dashboard increases by `+300`.
5. Test **Posting an Expense**:
   - Switch `Record entry` toggle to `expense`, enter Expense amount `500`, Paid now `500`, click **Post expense**. Verify transaction table and cash on hand update.
6. Test **Insufficient Stock Guard**:
   - Post a `sale` for `Gourmet Saffron Gift Box` with Qty `999`. **Expected:** Error message from server (`400`/`422`), no partial rows created.
7. Test **Opening Cash Upsert** (best verified on your Checkpoint 1 fresh account or after noting current balance):
   - Click **Set opening cash**, enter an amount and date, click **Save opening cash**. Opening cash updates cleanly without doubling previous opening entries.

*(Tip: After modifying `FreshBasket Mart` in Checkpoints 3–5, click **Sign out** -> **Load FreshBasket Mart Demo** if you want exact baseline numbers `70,000 / 26,000 / 75,000` restored before testing Dashboard/Scenario Lab/Advisor.)*

---

## 5. Intelligence, Forecasting & Scenario Checkpoints

### Checkpoint 6: Dashboard KPIs, Cash-Flow Radar & Gap Causes (`Dashboard` Tab)
**How it works:**
- `GET /api/v1/dashboard?days=14` combines `get_cash_position`, `get_receivables`, `get_payables`, `get_inventory_insights`, `get_data_coverage`, `build_forecast`, `evaluate_readiness`, and `build_recommendations`.
- `GET /api/v1/cashflow/forecast?days=7|14|30` returns daily series where `closing_cash = opening_cash + expected_inflows + estimated_inflows - confirmed_outflows - estimated_outflows`.
  - Overdue payables (`due_date <= as_of`) land conservatively on Day 1.
  - Overdue receivables (`due_date < as_of`) are **excluded** from automatic inflows until collected (surfaced instead as mitigation opportunities).

**Manual Test Steps (on clean `FreshBasket Mart`):**
1. Open the **Dashboard** tab.
2. Verify **Command Banner**:
   - Badge: `Projected Cash Gap Alert (14-day radar)`
   - Headline: `Estimated cash gap of 26,000 BDT below reserve by <today+9>`
   - Body: mentions `11,000 BDT` deficit below zero and `75,000 BDT` in unlockable internal capital (`35,000 BDT` slow stock + `40,000 BDT` overdue dues).
3. Verify the **5 KPI Cards**:
   - Cash on hand: `70,000 BDT` (Reserve `15,000 BDT`)
   - Estimated cash gap (14d): `26,000 BDT` (Lowest on `<today+9>`)
   - Slow-stock flagged: `35,000 BDT`
   - Customers owe: `40,000 BDT` (`40,000 BDT overdue`)
   - We owe suppliers: `90,000 BDT`
4. Verify **Cash-Flow Radar Chart**:
   - Toggle `7d` -> **Expected:** Amber note appears warning that the 7-day view stops before the reserve breach shown on the 14-day radar.
   - Toggle `14d` and `30d` -> **Expected:** Red dashed `Min Reserve` line (`15,000`), closing cash line dipping to `-11,000` on day 9, hover tooltip formatting currency correctly.
5. Verify **Gap Causes & Mitigations**:
   - Lists `Metro Distribution` outflow (`90,000 BDT` due `<today+9>`), `Planned staple reorder` (`2,500 BDT`), and overdue receivable causes (`Karim Traders` `20,000 BDT`, `Nadia Catering` `20,000 BDT`).

---

### Checkpoint 7: Transparent Financial-Readiness Profile (`Dashboard` Tab)
**How it works:**
- Pure rule evaluator (`readiness.py`) scores 4 dimensions (`green`, `amber`, `red`) with explicit thresholds and zero opaque ML scores:
  1. **Record completeness:** `red` if opening cash missing; `amber` if `< 14` history days or credit tx missing due date; `green` otherwise.
  2. **Current liquidity buffer:** `green` if `cash >= 1.5x reserve`; `amber` if `>= 1.0x reserve`; `red` otherwise.
  3. **Projected cash resilience:** `red` if lowest cash `< 0`; `amber` if `0 <= lowest < reserve`; `green` if `>= reserve`.
  4. **Working-capital efficiency:** `red` if `slow_stock_% > 25%` or `overdue_% > 50%`; `amber` if `>= 10%` or `>= 20%`; `green` otherwise.
- `overall_status` is the worst status among the 4 dimensions, paired with the disclaimer: *"for decision support only; not a credit score or lending decision."*

**Manual Test Steps:**
1. Scroll to **Transparent Financial-Readiness Profile** on the Dashboard.
2. On `FreshBasket Mart`, verify:
   - Overall badge is `RED` (driven by Projected resilience `-11,000 < 0` and Working-capital efficiency `100% overdue` / `>25%` slow stock).
   - **Record completeness** is `GREEN` (`opening_cash_set: true`, `history_days: 35`, `tx_missing_due_date: 0`).
   - **Current liquidity buffer** is `GREEN` (`70,000 / 15,000 = 4.67x >= 1.5x`).
   - Each card shows its exact `evidence` key-value pairs and a concrete `Next:` improvement action.

---

### Checkpoint 8: Rule-Based Recommendations & Scenario Deep Links (`Dashboard` -> `Scenario Lab`)
**How it works:**
- Both `GET /api/v1/dashboard` and `GET /api/v1/recommendations` call the exact same `recommend.build_recommendations()` service:
  - Missing opening cash -> returns only `SET_OPENING_CASH` (no `suggested_scenario`).
  - Zero reserve gap -> returns `[]` ("No urgent cash-gap action needed").
  - Otherwise ranks up to 5 actionable cards (`COLLECT_OVERDUE_DUES` -> `RELEASE_SLOW_STOCK` -> single deduplicated `DELAY_LARGE_PAYABLE`) using `(priority, -impact, id)`.
  - Each card attaches a `suggested_scenario` matching the `ScenarioRequest` Pydantic schema (or `null` if no active scheduled reorder exists).

**Manual Test Steps:**
1. On `FreshBasket Mart` **Dashboard**, scroll to **Recommended Actions (Internal Capital First)**.
2. Verify 3 cards appear in priority order:
   1. **Collect overdue customer dues first** (`+20,000 BDT` lowest cash impact at 50%) — has **Test in Scenario Lab →**.
   2. **Trim planned reorders and clear slow-moving stock** (targets `Planned staple reorder` `2,500 BDT` at 50%) — has **Test in Scenario Lab →**.
   3. **Negotiate or stagger upcoming supplier payment** (`Metro Distribution` `90,000 BDT` delayed 7 days -> `+90,000` cash impact, marked `payment moves outside this period` on 14d if `9 + 7 = 16 > 14`!) — has **Test in Scenario Lab →**.
3. Click **Test in Scenario Lab →** on any card (e.g., **Collect overdue customer dues first**).
4. **Expected:** Automatically switches to **Scenario Lab**, pre-populates the exact scenario type, horizon (`14d`), slider/parameter values, and renders the simulation immediately.
5. *(Optional API check)* Hit `http://127.0.0.1:8000/api/v1/recommendations?days=14` directly with Bearer JWT and confirm identical recommendation `id` order to `/dashboard`.

---

### Checkpoint 9: Scenario Lab Simulation, Pinning & Validation (`Scenario Lab` Tab)
**How it works:**
- `GET /api/v1/scenarios/options` returns up to 20 sorted overdue receivables, open payables, and active scheduled reorders with party-labeled dropdown labels.
- `POST /api/v1/scenarios` clones nothing in the DB (strictly read-only) and computes `baseline`, `simulated`, and `impact` (`cash_impact`, `gap_reduction_vs_reserve`, signed `breach_days_change`, `trapped_internal_capital`, `moved_beyond_horizon`, `affordable_above_reserve`, and explicit `assumption_note` / `affordability_note`).
- Slider/input edits debounce by `300ms`; previous result dims (`opacity-60`) while loading; Y-axis stays synchronized across baseline, active simulation, and pinned curves.

**Manual Test Steps:**
1. Open **Scenario Lab**.
2. **Test Collect dues:**
   - Select **Collect dues**, slider at `50%`, target `All overdue customer invoices`.
   - **Expected:** `Cash impact (Simulated)` = `+20,000 BDT`, `Lowest: 9,000 BDT`, `Gap reduction vs. reserve` = `+20,000 BDT`, `Simulated gap: 6,000 BDT`.
   - Drag slider to `100%` -> **Expected (after ~300ms):** `Cash impact` = `+40,000 BDT`, `Lowest: 29,000 BDT` (`Simulated gap: 0 BDT`), closing line stays entirely above the red `Min Reserve` line!
   - Caption checks: `"Simulated: assumes customers pay ..."` and `Trapped internal capital (Context only)` stays `75,000 BDT` (`Unchanged by scenario`).
3. **Test Delay payment & Beyond-Horizon Note:**
   - Switch to **Delay payment** at `14d` horizon, select `Metro Distribution` (or default largest payable), set `Delay by days` to `7d` (due `today + 9 + 7 = today + 16 > 14`).
   - **Expected:** Amber pill **`Payment moves outside this period`** appears next to `Pin to compare`, explaining why the `90,000 BDT` bill shifted out of the 14-day window rather than disappearing permanently.
   - Switch horizon to `30d` -> `today + 16` is now inside the 30-day window, so `moved_beyond_horizon` clears and shows the real delayed spike on day 16. Switch back to `14d`.
4. **Test Reorder less:**
   - Switch to **Reorder less**, `50%`, target `Planned staple reorder` (`2,500 BDT` on day 12).
   - **Expected:** Shows reduction effect on day 12 (does not affect day-9 trough `-11,000` unless day-12 becomes higher/lower, cleanly reflected in chart and impact).
5. **Test Planned purchase (Affordability Check):**
   - Switch to **Planned purchase**, enter Amount `15000`, Date = `today + 3`.
   - **Expected:** `Cash impact` = **`-15,000 BDT`** (red negative impact), `Not affordable (breaches reserve)`, `affordability_note` clarifies this measures cash coverage vs. reserve only.
   - Increase Amount to `65000` on `today + 3` -> `Breach days change` becomes positive (`+6 days` or more), showing earlier reserve breach.
6. **Test Side-by-Side Comparison & Pinning:**
   - Click **Compare defaults side-by-side** in the top bar.
   - **Expected:** Up to 3 simulated lines (`Collect 50% dues`, `Delay payable 7d`, `Reorder 50% less`) overlay on the chart AND appear in the **Side-by-Side Pinned Comparison** table below.
   - Adjust a custom scenario (e.g., `Collect 100% dues`) and click **Pin to compare** -> updates the comparison table/chart; click **Clear pins** to reset.
7. **Test Empty State Guard (optional on fresh merchant):**
   - On a merchant with no overdue dues, verify the **Collect dues** tab is disabled with tooltip/text `"No overdue customer dues"`.

---

### Checkpoint 10: AI Advisor, Guardrails & Audit Log (`Advisor` Tab)
**How it works:**
- `POST /api/v1/advisor/ask` enforces:
  - Input length `1..500` chars and per-user rate limit (`ADVISOR_RATE_LIMIT_PER_MIN`, default `10/min` -> `429` if exceeded).
  - Pre-checks out-of-scope write requests (`"record a sale..."`) and off-topic questions immediately without modifying DB or leaking prompt instructions.
  - Runs Gemini tool loop (if `GEMINI_API_KEY` is configured and non-placeholder) with automatic function calling disabled, `MAX_TOOL_CALLS = 6`, identical call deduplication, quoted/truncated party names (prompt-injection defense; notes excluded), and server-set `as_of`.
  - Final structured JSON step maps `{label, tool, field}` references back to exact backend tool values and runs normalized number-checking (rejects `k`/`lakh`/`crore` abbreviations or ungrounded numbers with 1 retry, then safe fallback).
  - If `GEMINI_API_KEY` is missing, invalid, rate-limited upstream, or times out (`ADVISOR_TIMEOUT_SECONDS=25`), returns **`200 OK`** with `fallback_used: true` generated directly from backend tools.
  - Every Q&A is saved to `AdvisorLog` and returned by `GET /api/v1/advisor/history`.

**Manual Test Steps:**
1. Open the **Advisor** tab on `FreshBasket Mart`.
2. Click each quick-ask demo prompt:
   - `"Why could I run out of cash next week?"` -> verify it surfaces `Metro Distribution` (`90,000`), cash on hand (`70,000`), lowest cash (`-11,000`), and gap (`26,000`).
   - `"Can I afford a 15,000 purchase?"` -> verify it runs scenario simulation (`run_scenario`), reports not affordable/reserve impact, and surfaces `75,000` trapped internal capital.
   - `"How much cash is tied up in slow stock and overdue dues?"` -> verify `35,000` slow stock + `40,000` overdue dues = `75,000` total.
   - `"Should I take a loan?"` -> verify it **never approves or rejects** a loan, states that a lender decides eligibility, and shows `26,000` gap vs. `75,000` trapped internal capital.
3. Expand **`Show tools used & evidence`** on any answer:
   - Verify exact backend tools called (`get_financial_snapshot`, `forecast_cash`, `run_scenario`, etc.) and verified record IDs / badges (`Numbers verified` or `Generated directly from your data` if running in fallback mode).
4. **Test Safety Guardrails:**
   - Ask `"Record a sale of 5,000 BDT for Walk-In Retail"` -> verify it refuses cleanly (read-only) and creates zero new transactions in **Ledger**.
   - Ask `"What is the weather in Dhaka tomorrow?"` -> verify polite out-of-scope response without fake numbers.
   - Refresh the page and verify **Recent Advisor Audit Log** loads saved questions and answers from `GET /api/v1/advisor/history`.

---

### Checkpoint 11: Settings Modal & Live Recalculation (`Settings`)
**How it works:**
- `SettingsModal.tsx` calls `PATCH /api/v1/business` to update `name`, `currency`, `min_cash_reserve`, and `slow_stock_days_threshold`, then invalidates all TanStack Query caches (`queryClient.invalidateQueries()`).

**Manual Test Steps:**
1. Click **Settings** in the top navigation bar.
2. Change **Minimum cash reserve** from `15000` to `5000`, click **Save changes**.
3. **Expected:**
   - Top bar updates to `Reserve 5,000`.
   - On **Dashboard**, `Estimated cash gap (14d)` changes from `26,000 BDT` to `16,000 BDT` (`5,000 - (-11,000)`), and the red `Min Reserve` reference line moves down to `5,000`.
   - Restore `Minimum cash reserve` back to `15000` when finished.

---

### Checkpoint 12: Automated Regression Check (Optional Developer Gate)
Before demoing or tagging a release, run the full automated checks:
```powershell
# Backend (31 tests across health, auth, ledger, seed, finance, forecast, readiness, advisor, scenarios, recommendations)
backend\.venv\Scripts\pytest.exe backend\tests -v

# Frontend static checks & production bundle
npm --prefix frontend run lint
npm --prefix frontend run build
```

---

## 6. Recommended Modifications to Make Functionality Work Even Better

Based on what is currently implemented vs. what real merchants and live demos encounter, here are the highest-value improvements:

1. **Sales Return & Purchase Return UI in `Ledger.tsx`**
   - *Current state:* The backend ledger service and `/transactions` endpoint already support `sale_return` and `purchase_return` (including the filter dropdown in `Ledger.tsx`), but the **Record entry** form only submits `sale`, `purchase`, and `expense`.
   - *Improvement:* Add `sale_return` and `purchase_return` creation (or a `"Return"` button on an existing posted sale/purchase row referencing `reference_transaction_id`) so merchants can handle damaged/returned goods directly in the UI.

2. **Scheduled Events / Planned Reorders Management UI**
   - *Current state:* `ScheduledEvent` records exist in PostgreSQL (`Planned staple reorder` is created by `seed.py`) and power `reorder_less` scenarios and recommendations, yet there is no UI or CRUD endpoint for merchants to add, edit, or mark planned reorders/rent/salary events as completed.
   - *Improvement:* Add `GET/POST/PATCH/DELETE /api/v1/scheduled-events` and a **Planned Outflows / Reorders** panel in **Inventory** or **Ledger** so non-seeded businesses can use the `Reorder less` tab in Scenario Lab instead of seeing `"No planned reorders"`.

3. **Profitability & Product Margin Page in the Frontend**
   - *Current state:* `GET /api/v1/profitability` and the advisor's margin tool already compute revenue, COGS, gross profit, gross margin %, operating expenses, net profit, and top/bottom margin SKUs, but the React app has no dedicated UI screen displaying product-level margins.
   - *Improvement:* Add a **Margins / P&L** section (either inside `Inventory` or as a sub-view on `Dashboard`) showing top/lowest margin products and net profit breakdown over `7d / 14d / 30d`.

4. **Multi-Item Invoice Entry in `Ledger.tsx`**
   - *Current state:* The backend `TransactionCreate` schema accepts an `items: list[TransactionItemCreate]` array, while `Ledger.tsx` currently submits a single product line item per form submit.
   - *Improvement:* Allow adding/removing multiple line items (`+ Add item`) in the **Record entry** form with a live client preview of subtotal and net total before posting.

5. **Multi-Lever Combined Scenarios & Scenario Persistence**
   - *Current state:* `ScenarioRequest` evaluates one lever at a time (`collect_dues` OR `delay_payment` OR `reorder_less` OR `planned_purchase`), and pinned scenarios live only in component state (cleared on page reload).
   - *Improvement:* Support combining multiple actions in one scenario (e.g., *"Collect 50% of Karim Traders + Delay Metro Distribution 7 days + Test 15,000 purchase"*), and store pinned scenarios in `localStorage` or the database so comparisons survive navigation between `Dashboard` and `Scenario Lab`.

6. **Customer/Supplier Payment Quick-Action from `Parties.tsx`**
   - *Current state:* Payments can only be recorded per-invoice from the **Ledger** table.
   - *Improvement:* Add an *"Open unpaid invoices"* drawer or *"Collect dues"* button directly on each overdue card in `Parties.tsx` (and a *"Jump to Scenario Lab"* shortcut per party).

7. **AI Advisor Follow-Up Context & Persistent Rate Limiting**
   - *Current state:* Each advisor question runs statelessly (`Each question stands alone`), and `rate_limiter` in `agent.py` uses an in-memory per-process `deque` (resets on worker restart and isn't shared across multiple Uvicorn workers).
   - *Improvement:* Move rate-limit counters to Redis or PostgreSQL for multi-worker deployments, and optionally pass bounded read-only prior Q&A turn summaries when the user explicitly clicks a *"Follow up"* mode.

8. **Database Migrations (Alembic) & Frontend Automated Tests**
   - *Current state:* Tables are auto-created via `Base.metadata.create_all()` at startup, and the frontend relies on `oxlint` + `tsc -b` without Vitest/Playwright UI tests.
   - *Improvement:* Introduce Alembic migrations for safe production schema changes, and add Vitest + Playwright smoke tests covering login, posting a sale, Scenario Lab sliders, and Advisor fallback rendering.
