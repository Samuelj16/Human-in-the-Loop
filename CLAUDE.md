# CLAUDE.md — Human in the Loop Research Assistant

This repository contains a full-stack **Human-in-the-Loop** research assistant with FastAPI backend and Next.js frontend.

---

## 🛠️ Essential Commands

### 1. Run the Backend (FastAPI)

```bash
cd api
source .venv/bin/activate
PYTHONPATH=. uvicorn app.main:app --reload --port 8005
```

- API Health: `http://localhost:8005/api/health`
- Swagger Docs: `http://localhost:8005/docs`

### 2. Run the Frontend (Next.js)

```bash
cd web
npm run dev
```

- Web App: `http://localhost:3000`

### 3. Run Automated Tests

```bash
# Must run from api/ - pytest.ini lives there, and without it
# asyncio_mode is unset and ~65 async tests error out.
cd api && .venv/bin/python -m pytest -v
```

### 4. Run Frontend Tests

```bash
cd web
npm run test:run   # Vitest + React Testing Library, 28 tests
```

### 5. Build Frontend for Production

```bash
cd web
npm run build
```

---

## 🧠 LLM & Search Configuration

In `.env` (or `api/.env`):

- **Google Gemini (Default LLM Provider)**:

  ```env
  LLM_PROVIDER=gemini
  GEMINI_API_KEY="your-gemini-api-key"
  GEMINI_MODEL="gemini-3.6-flash"
  ```

- **Claude (Anthropic)**:

  ```env
  LLM_PROVIDER=anthropic
  ANTHROPIC_API_KEY="your-anthropic-api-key"
  ANTHROPIC_MODEL="claude-opus-5"
  ANTHROPIC_ENABLE_FALLBACKS=true
  ```

- **Web Search (Tavily)**:
  ```env
  TAVILY_API_KEY="your-tavily-api-key"
  # (Leave empty to use deterministic offline Stub search)
  ```

---

## 🏗️ Architecture & Codebase Layout

- `api/app/agent/loop.py`: The core two-phase agent research loop:
  - `draft_plan`: Generates 3-6 steps + clarifying questions, then enters `awaiting_approval`.
  - `run_research`: Runs approved plan, gathers sources, manages budget caps, writes final markdown report.
- `api/app/routers/`:
  - `auth.py`: Self-hosted registration & JWT issue/verify.
  - `tasks.py`: Full task lifecycle (`create`, `list`, `get`, `approve`, `cancel`, `sources/{id}/toggle`, `share`).
  - `public.py`: Unauthenticated public report viewer.
- `api/tests/`: Pytest suite (34 async unit & integration tests).
- `web/src/components/`:
  - `PlanApprovalGate.tsx`: Interactive human approval gate (edit/reorder steps, answer questions).
  - `LiveResearchTimeline.tsx`: Live telemetry feed with source veto buttons.
  - `ReportView.tsx`: Markdown report rendering with inline citation badges.
