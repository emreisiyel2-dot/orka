# ORKA — AI Command Center

Single-user multi-agent dashboard for managing AI agent teams from one interface.

## Architecture

- **Frontend:** Next.js 14 (App Router) + TypeScript + Tailwind CSS
- **Backend:** FastAPI + SQLAlchemy (async) + SQLite
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

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard runs at http://localhost:3000

## API Endpoints

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

## Flow

1. Create a project
2. Submit a task (e.g., "Fix payment bug")
3. Click "Distribute" — Orchestrator splits into subtasks
4. Each agent picks up its subtask (simulated 3s processing)
5. Activity feed shows real-time progress
6. Memory panel tracks last completed, blockers, next steps
7. Summary gives a human-readable status overview

## Phases

- **Phase 1 (MVP):** Dashboard, task system, agent simulation, memory, summary
- **Phase 2:** Remote Windows worker integration
- **Phase 3:** Agent-to-agent messaging, auto task splitting
- **Phase 4:** Notifications, analytics
