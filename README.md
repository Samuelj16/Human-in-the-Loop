# Human in the Loop (HITL) Research Assistant

An autonomous, deep research assistant engineered with an interactive **Human-in-the-Loop** approval gate, telemetry feed, live source vetoing, and strict token spend caps.

---

## Key Architecture & Design

```
   [User Research Inquiry]
             │
             ▼
      ┌──────────────┐
      │  Job 1:      │
      │  draft_plan  │
      └──────┬───────┘
             │
             ▼
   ════════════════════════════════════════════════════════════════
   🛡️  HUMAN APPROVAL GATE (Status: `awaiting_approval`)
       - Review & edit formulated research plan steps
       - Answer clarifying questions (scope, timeframes, domains)
       - Add/remove/reorder research steps
       - Zero additional tokens spent until human confirms
   ════════════════════════════════════════════════════════════════
             │
             ▼ (User Approves & Launches)
      ┌──────────────┐
      │  Job 2:      │
      │ run_research │ ◄── [Live Telemetry Feed + Real-time Source Veto]
      └──────┬───────┘
             │
             ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ Comprehensive Markdown Report + Numbered Inline Citations    │
   │ Cost / Token / Search Metrics + Public Shareable Link        │
   └──────────────────────────────────────────────────────────────┘
```

### 1. The Human-in-the-Loop Gate

Autonomous research loops without human alignment frequently veer off-topic or exhaust budgets. HITL splits execution into two explicit phases:

- **Phase 1 (Drafting)**: Generates a 3–6 step actionable plan, 0–3 clarifying questions, and a restated question. It then **halts** and transitions to `awaiting_approval`.
- **Phase 2 (Execution)**: Incorporates user answers and edited plan steps into the researcher prompt.

### 2. Live Source Veto

During execution, retrieved web sources stream to the user in real time. Users can click **Veto** on any source to exclude it from being cited in the synthesis report.

### 3. Spend Caps & Guardrails

- `max_tool_iterations`: Turn limit prevents infinite reasoning loops.
- `max_searches_per_task`: Limits web search API costs.
- `max_output_tokens_per_task`: Enforces token budget per task.
- `max_tasks_per_user_per_day`: Protects against runaway quota consumption.

> **Security deployment note:** The built-in authentication throttles use a
> single-process sliding window, and the task allowance is scoped to a user-created
> account. Before public or multi-worker deployment, move throttling to a shared
> atomic store or trusted edge gateway, require a non-self-issued entitlement
> (such as an invitation, verified organization, or billing tenant), and enforce
> tenant/global spend quotas at task creation.

---

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0 (Async), Pydantic v2, aiosqlite / asyncpg, python-jose, bcrypt, arq
- **Models**: Anthropic (Claude Opus 5 / Sonnet 5 with adaptive thinking) & OpenAI (GPT-5) via a provider-neutral abstraction
- **Search**: Tavily Search Client with a deterministic offline `StubSearch` fallback
- **Frontend**: Next.js 16 (App Router), React 19, Tailwind CSS v4, TypeScript

---

## Quickstart

### 1. Prerequisites

- Python 3.11+
- Node.js 20+

### 2. Backend Setup & Run

```bash
# Navigate to api directory
cd api

# Activate virtual environment
source .venv/bin/activate

# Copy environment variables, then generate and set JWT_SECRET as documented there
cp ../.env.example .env

# Run FastAPI backend
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

The API will boot at `http://localhost:8000` (Swagger docs available at `http://localhost:8000/docs`).

### 3. Frontend Setup & Run

```bash
# In a new terminal tab, navigate to web directory
cd web

# Run development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Running the Automated Test Suite

Run the full pytest suite covering authentication, task lifecycle, agent loops, search tool execution, budget caps, and public report sharing:

```bash
./api/.venv/bin/pytest -v
```

All 19 test cases run asynchronously against an isolated SQLite test environment with zero external network dependencies.

---

## API Reference

| Method | Endpoint                                     | Description                                           | Auth Required |
| :----- | :------------------------------------------- | :---------------------------------------------------- | :-----------: |
| `POST` | `/api/auth/register`                         | Register a new user                                   |      No       |
| `POST` | `/api/auth/login`                            | Login with email and password                         |      No       |
| `GET`  | `/api/auth/me`                               | Retrieve current authenticated user profile           |      Yes      |
| `POST` | `/api/tasks`                                 | Create a new research task & trigger plan draft       |      Yes      |
| `GET`  | `/api/tasks`                                 | List all tasks for current user                       |      Yes      |
| `GET`  | `/api/tasks/{id}`                            | Get task detail with live events and source ledger    |      Yes      |
| `POST` | `/api/tasks/{id}/approve`                    | Submit edited plan + clarifications & launch research |      Yes      |
| `POST` | `/api/tasks/{id}/cancel`                     | Cancel an active task                                 |      Yes      |
| `POST` | `/api/tasks/{id}/sources/{source_id}/toggle` | Toggle source exclusion / veto                        |      Yes      |
| `POST` | `/api/tasks/{id}/share`                      | Toggle public visibility & get share ID               |      Yes      |
| `GET`  | `/api/public/reports/{share_id}`             | View public research report                           |      No       |
| `GET`  | `/api/health`                                | Health check endpoint                                 |      No       |
