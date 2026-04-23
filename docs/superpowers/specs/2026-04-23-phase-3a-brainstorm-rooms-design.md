# Phase 3A: Multi-Room Brainstorm System

## Status: Approved

## Overview

ORKA evolves from task execution to idea incubation. Users describe ideas, and multiple agents brainstorm collaboratively in persistent, isolated rooms. When the idea is refined, it spawns a project workspace with initial tasks, memory, and agent assignments.

## Constraints

- Do not break existing Phase 1/2/2.5 functionality
- Autonomy-first: agents auto-rotate with minimal user interruption
- Brainstorm rooms are fully isolated from each other
- Brainstorm agents are separate from execution agents but architecturally compatible
- Clean agent interface designed for future LLM integration
- User can interrupt, steer, or finalize at any time

---

## Data Models

### BrainstormRoom

| Field | Type | Notes |
|-------|------|-------|
| id | String(36) PK | UUID |
| title | String(200) | Auto-generated from idea |
| idea_text | Text | Original user idea |
| status | Enum | brainstorming, refining, ready_to_spawn, spawned |
| current_round | Integer | Starts at 0, increments per auto-rotation |
| max_rounds | Integer | Default 3, configurable |
| project_id | String(36) FK nullable | Set after spawn |
| spawn_plan | Text nullable | JSON string with generated plan |
| created_at | DateTime | |
| updated_at | DateTime | |

### BrainstormMessage

| Field | Type | Notes |
|-------|------|-------|
| id | String(36) PK | UUID |
| room_id | String(36) FK | |
| agent_id | String(36) FK nullable | Null for user messages |
| agent_type | String nullable | Denormalized for quick access |
| role | Enum | user, agent, system |
| content | Text | |
| message_type | Enum | idea, question, analysis, risk, suggestion, plan, challenge |
| round_number | Integer | Which brainstorm round this belongs to |
| created_at | DateTime | |

### BrainstormAgent

| Field | Type | Notes |
|-------|------|-------|
| id | String(36) PK | UUID |
| room_id | String(36) FK | |
| agent_type | String | orchestrator, backend, frontend, qa, docs, memory |
| agent_name | String | Display name |
| status | Enum | active, paused, completed |
| turn_order | Integer | Order in auto-rotation |
| created_at | DateTime | |

### BrainstormSkill

| Field | Type | Notes |
|-------|------|-------|
| id | String(36) PK | UUID |
| room_id | String(36) FK | |
| skill_name | String | |
| description | Text | What this skill does |
| relevance_reason | Text | Why it's relevant to this project |
| status | Enum | suggested, accepted, rejected, locked |
| created_at | DateTime | |

---

## Brainstorm Agent Interface

```python
class BrainstormAgentBase(ABC):
    @abstractmethod
    async def generate_response(
        self,
        agent_type: str,
        idea_text: str,
        conversation: list[BrainstormMessage],
        round_number: int,
    ) -> BrainstormResponse:
        pass

class BrainstormResponse:
    content: str
    message_type: str  # analysis, question, risk, suggestion, challenge
```

SimulatedBrainstormAgent implements this with per-type templates. In Phase 3B, LLMBrainstormAgent will implement the same interface with model routing.

### Simulated Agent Behaviors

**Orchestrator**: Analyzes scope, decomposes into areas, identifies dependencies
**Backend**: Suggests API design, data models, service architecture, integration points
**Frontend**: Proposes UI components, user flows, state management, responsive approach
**QA**: Flags risks, edge cases, testing strategy, failure modes
**Docs**: Suggests documentation needs, API docs, user guides
**Memory**: Summarizes progress, identifies gaps, tracks open questions

Each agent generates 1-3 contribution types per round based on conversation context.

---

## API Design

### Brainstorm Room CRUD

```
POST   /api/brainstorms
  Body: { idea_text: string, title?: string }
  Response: BrainstormRoom (status: brainstorming, agents auto-created)

GET    /api/brainstorms
  Query: status (optional filter)
  Response: BrainstormRoom[]

GET    /api/brainstorms/{id}
  Response: BrainstormRoomDetail (room + messages + agents + skills)

DELETE /api/brainstorms/{id}
  Response: { deleted: true }
```

### Brainstorm Flow Control

```
POST   /api/brainstorms/{id}/advance
  Triggers next auto-rotation round
  All active agents generate responses in turn_order
  If round >= max_rounds, auto-transitions to refining
  Response: BrainstormMessage[] (new messages)

POST   /api/brainstorms/{id}/message
  Body: { content: string, target_agent_type?: string }
  User sends message to room or specific agent
  Targeted agents respond, then auto-rotation continues
  Response: BrainstormMessage[] (user msg + agent responses)

POST   /api/brainstorms/{id}/skip
  Skip to next state (brainstorming → refining → ready_to_spawn)
  Response: BrainstormRoom (updated)

GET    /api/brainstorms/{id}/plan
  Response: SpawnPlan (scope, architecture, risks, agents, skills)
  Only available in refining or ready_to_spawn state
```

### Spawn

```
POST   /api/brainstorms/{id}/spawn
  Confirms spawn plan, creates project workspace
  Creates: Project, initial Tasks, MemorySnapshot
  Sets room status to spawned, links project_id
  Response: { project_id: string, room: BrainstormRoom }
```

### Skills

```
GET    /api/brainstorms/{id}/skills
  Response: BrainstormSkill[]

PUT    /api/brainstorms/{id}/skills/{skill_id}
  Body: { status: "accepted" | "rejected" }
  Response: BrainstormSkill
```

---

## Auto-Rotation Flow

1. Room created → 6 BrainstormAgents auto-created with turn_order
2. User calls `/advance` or system auto-triggers
3. Round N begins:
   - For each agent in turn_order:
     - Generate response using BrainstormAgentBase
     - Create BrainstormMessage
   - Round N complete
4. After round >= max_rounds (default 3):
   - Status → refining
   - System generates spawn_plan (JSON):
     - project_name, description
     - mvp_scope: string[]
     - risks: string[]
     - architecture_direction: string
     - recommended_agents: string[]
     - suggested_skills: BrainstormSkill[]
5. Status → ready_to_spawn
6. User reviews plan and confirms spawn
7. Status → spawned, Project created

### User Override Points

- **Message to room**: inject user perspective, agents respond
- **Message to specific agent**: targeted question, only that agent responds
- **Skip**: jump to next state immediately
- **Manual spawn**: force spawn even in brainstorming state
- **Pause agent**: stop an agent from contributing to further rounds

---

## Spawn Plan Generation

When transitioning to `refining`, the system synthesizes all brainstorm messages into a structured plan:

```python
class SpawnPlanGenerator:
    def generate(self, room: BrainstormRoom, messages: list[BrainstormMessage]) -> dict:
        # Extract from conversation:
        # - Key themes and requirements
        # - Technical suggestions from each agent
        # - Identified risks
        # - Architecture recommendations
        # - Suggested skills based on project type detection
        return spawn_plan_dict
```

The spawn plan is stored as JSON in `room.spawn_plan` and presented to the user for review.

---

## Frontend Changes

### New Page: `/` (Global Lobby - replaces current project selector)

Layout:
- Header with ORKA branding
- "New Brainstorm" prominent button
- Two sections:
  1. Brainstorm Rooms (cards with status badge, title, round count)
  2. Project Rooms (existing project list)

### New Page: `/brainstorm/{id}` (Brainstorm Room)

Layout:
- Header with room title, status badge, round indicator
- Main area: multi-agent chat panel
  - Messages styled per agent type (color-coded)
  - Agent name + type label on each message
  - User messages distinct styling
  - System messages for state transitions
- Sidebar:
  - Agent list with status
  - Skill suggestions (accept/reject)
  - Action buttons (Advance Round, Skip, Spawn)
  - Spawn plan preview (when available)
- Input bar: send message to room or @mention specific agent
- "Finalize & Spawn" button (appears when ready_to_spawn)

### Existing Page: `/project/[id]` — No changes

### Color Coding for Agent Types

| Agent | Color | Tailwind Class |
|-------|-------|---------------|
| Orchestrator | Blue | text-info |
| Backend | Green | text-healthy |
| Frontend | Purple | text-purple-400 |
| QA | Red | text-error |
| Docs | Amber | text-amber-400 |
| Memory | Cyan | text-cyan-400 |

---

## Existing Functionality — Unchanged

The following are NOT modified:
- Agent, Task, Project models and APIs
- Worker system (registration, sessions, heartbeat)
- Coordination service (dependencies, handoffs)
- Agent simulator
- Task distributor
- Memory service
- All existing project dashboard components
- WebSocket broadcast

---

## Implementation Order

1. Backend data models (BrainstormRoom, BrainstormMessage, BrainstormAgent, BrainstormSkill)
2. BrainstormAgentBase + SimulatedBrainstormAgent
3. Brainstorm API routes
4. Auto-rotation logic + SpawnPlanGenerator
5. Frontend types + API client methods
6. Global Lobby page
7. Brainstorm Room page
8. Integration testing
