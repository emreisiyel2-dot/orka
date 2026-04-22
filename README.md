# ORKA — AI Command Center

Single-user multi-agent dashboard for managing AI agent teams from one interface.

## Architecture

- **Frontend:** Next.js 14 (App Router) + TypeScript + Tailwind CSS
- **Backend:** FastAPI + SQLAlchemy (async) + SQLite
- **Worker:** Standalone Python process for remote task execution
- **Agents:** Simulated 6-agent system (orchestrator, backend, frontend, QA, docs, memory)
- **Realtime:** WebSocket stub (ready for full implementation)

## Quick Start

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Server runs at http://localhost:8000

### Worker

```bash
cd worker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Worker connects to backend, registers itself, polls for tasks, and executes them with autonomous prompt handling. Runs in simulation mode by default.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard runs at http://localhost:3000

## API Endpoints

### Core (Phase 1)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | GET/POST | List or create projects |
| `/api/projects/{id}` | GET | Get project details |
| `/api/tasks` | GET/POST | List or create tasks |
| `/api/tasks/{id}/assign` | POST | Assign task to agent |
| `/api/tasks/{id}/complete` | POST | Mark task complete |
| `/api/tasks/{id}/distribute` | POST | Orchestrator splits task into subtasks |
| `/api/agents` | GET | List all agents with status |
| `/api/agents/{id}` | GET | Get agent details |
| `/api/agents/{id}/status` | PUT | Update agent status |
| `/api/activity` | GET | Activity feed (filter by project_id) |
| `/api/memory/{project_id}` | GET/POST | Memory snapshots |
| `/api/summary/{project_id}` | GET | Project summary with human-readable message |
| `/ws` | WebSocket | Realtime agent status updates |

### Worker Integration (Phase 2)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workers/register` | POST | Worker registers itself |
| `/api/workers` | GET | List all workers |
| `/api/workers/{id}/heartbeat` | PUT | Keep-alive heartbeat |
| `/api/workers/{id}/tasks` | GET | Worker fetches assigned tasks |
| `/api/workers/sessions` | POST | Create execution session |
| `/api/workers/sessions/{id}` | PUT | Update session (status, waiting_for_input) |
| `/api/workers/sessions/{id}/logs` | POST | Stream execution logs |
| `/api/workers/sessions/{id}/decisions` | POST | Log autonomous decisions |
| `/api/sessions` | GET | Dashboard: list sessions |
| `/api/sessions/{id}` | GET | Dashboard: session detail with logs |
| `/api/sessions/{id}/input` | POST | Dashboard: send input to waiting session |
| `/api/sessions/{id}/logs` | GET | Dashboard: get session logs |
| `/api/sessions/{id}/decisions` | GET | Dashboard: get autonomous decisions |

## Agent System

6 agents are seeded on startup:

| Agent | Type | Role |
|-------|------|------|
| Orchestrator | orchestrator | Splits tasks, distributes work |
| Backend Agent | backend | API, database, services |
| Frontend Agent | frontend | UI, state, UX |
| QA Agent | qa | Testing, validation |
| Docs Agent | docs | Documentation, summaries |
| Memory Agent | memory | Progress tracking |

## Worker Autonomy Model

The worker operates in **default autonomous mode**:

**Auto-resolved (safe):** `[y/N]`, `[Y/n]`, "Press Enter", "Continue?", "Is this ok?"
**Escalated (critical):** production systems, credentials, destructive actions, sudo, database drops

Every autonomous decision is logged with the decision, reason, and whether it was auto-resolved or escalated.

## Flow

1. Create a project
2. Submit a task (e.g., "Fix payment bug")
3. Click "Distribute" — Orchestrator splits into subtasks
4. Worker picks up assigned tasks and executes them
5. Safe prompts auto-resolved, critical prompts escalated to dashboard
6. Dashboard shows live session status, logs, and input prompts
7. Activity feed tracks all progress
8. Memory panel tracks last completed, blockers, next steps

## Phases

- **Phase 1 (MVP):** Dashboard, task system, agent simulation, memory, summary
- **Phase 2 (Current):** Remote worker integration, session management, autonomous prompt handling, decision logging
- **Phase 3:** Agent-to-agent messaging, auto task splitting
- **Phase 4:** Notifications, analytics
