# 🚀 ORKA — MVP PLAN

## 1. PRODUCT DEFINITION

Orka is a **single-user AI command center** that allows managing multiple AI agents from one dashboard.

- User controls everything from a web interface
- Execution happens on a remote Windows machine (worker)
- Agents collaborate internally
- System tracks "where we left off"
- Mobile-friendly control

---

## 2. CORE GOAL

Solve:
- Too many terminals
- Losing track of progress
- No centralized memory

Provide:
- One dashboard
- Multiple AI agents
- Task distribution
- Persistent memory
- Live progress tracking

---

## 3. SYSTEM ARCHITECTURE

### Components

1. **Frontend (Dashboard)**
- Next.js
- Responsive (mobile + desktop)

2. **Backend (Orchestrator)**
- FastAPI
- Task routing
- Agent coordination

3. **Database**
- PostgreSQL
- Stores projects, tasks, logs, memory

4. **Worker (Windows Machine)**
- Runs terminal + Claude Code
- Executes tasks
- Sends logs back

5. **Realtime Layer**
- WebSocket / SSE

---

## 4. AGENT SYSTEM

### Agents

#### 1. Orchestrator
- Splits tasks
- Assigns work
- Merges outputs

#### 2. Backend Agent
- API
- Database
- Payment systems

#### 3. Frontend Agent
- UI
- State
- UX flow

#### 4. QA Agent
- Finds bugs
- Validates logic

#### 5. Docs Agent
- Creates summaries
- Writes presentations

#### 6. Memory Agent
- Tracks progress
- Stores "last state"

---

## 5. CORE FEATURES (MVP)

### 1. Project Management
- Create project
- Select project

### 2. Agent Dashboard
Each agent shows:
- Status
- Last action
- Current task

### 3. Task Input
Single input box:

Example:
"Fix payment issue and improve menu"

System splits into subtasks.

### 4. Activity Feed
Timeline:
- Actions
- Updates
- Errors

### 5. Memory System
Stores:
- Last completed task
- Current blockers
- Next step

### 6. Summary Button
"What is the current status?"

Returns:
- Progress
- Issues
- Next steps

---

## 6. MOBILE EXPERIENCE

Must support:
- Task creation
- Status viewing
- Summary view
- Notifications (future)

---

## 7. WORKER SYSTEM (WINDOWS)

### Responsibilities
- Execute terminal commands
- Run Claude Code
- Return logs

### Behavior
- Receives tasks from backend
- Executes safely
- Sends results back

---

## 8. DATA MODELS (SIMPLIFIED)

### Project
- id
- name
- description

### Task
- id
- project_id
- content
- status

### Agent
- id
- name
- type

### Message
- id
- agent_id
- content

### Memory
- project_id
- summary
- last_state

---

## 9. DEVELOPMENT PHASES

### Phase 1 (MVP)
- Dashboard UI
- Task system
- Agent display
- Memory tracking

### Phase 2
- Worker connection
- Terminal logs

### Phase 3
- Agent-to-agent communication
- Auto task splitting

### Phase 4
- Notifications
- Advanced analytics

---

## 10. TECH STACK

Frontend:
- Next.js

Backend:
- FastAPI

Database:
- PostgreSQL

Realtime:
- WebSocket

Worker:
- Python agent runner

---

## 11. INITIAL PROMPT FOR CLAUDE CODE

Build a system called "Orka" with:

- Next.js dashboard (responsive)
- FastAPI backend
- PostgreSQL database

Features:
- Create projects
- Create tasks
- Assign tasks to agents
- Display agent status
- Activity feed
- Memory system (last state)

Also create:
- Simple agent simulation (no real AI yet)
- API endpoints for tasks and agents

---

## 12. SUCCESS CRITERIA

System works if:

- You can create a task
- Task appears in agents
- Agents update status
- Memory updates correctly
- Dashboard shows live progress

---

## 13. FUTURE VISION

- Full Claude Code integration
- Real terminal control
- Autonomous agent collaboration
- Multi-project orchestration

---

🔥 This is your AI command center.

