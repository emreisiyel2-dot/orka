# Phase 3A: Multi-Room Brainstorm System

## Status: Revised (v2 — incorporating critical improvements)

## Overview

ORKA evolves from task execution to idea incubation. Users describe ideas, and multiple agents brainstorm collaboratively in persistent, isolated rooms. When the idea is refined, it spawns a project workspace with initial tasks, memory, and agent assignments.

## Constraints

- Do not break existing Phase 1/2/2.5 functionality
- Autonomy-first: agents auto-rotate with minimal user interruption
- Brainstorm rooms are fully isolated from each other
- Brainstorm agents are separate from execution agents but architecturally compatible
- Clean agent interface designed for future LLM integration
- User can interrupt, steer, or finalize at any time
- Brainstorm context MUST transfer to execution agents on spawn
- Rotation is hybrid: frontend-triggered with backend auto-advance fallback
- Skill detection is deterministic and keyword-based, not random
- Simulated agents use multiple templates with variation

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

### Simulated Agent Variation

Each agent type has **multiple response templates** per contribution type. On each invocation, a template is selected using a deterministic but varied strategy:

```python
class SimulatedBrainstormAgent(BrainstormAgentBase):
    # Each agent type has 3-5 templates per contribution type
    TEMPLATES = {
        "orchestrator": {
            "analysis": [
                "Based on the idea '{idea}', I see {count} major areas to address: {areas}. Each has dependencies we need to map.",
                "Looking at '{idea}', this breaks down into {areas}. The critical path runs through {primary_area}.",
                ...
            ],
            "question": [...],
            "suggestion": [...],
        },
        ...
    }

    def _pick_template(self, templates: list[str], round_number: int, agent_type: str) -> str:
        """Deterministic selection: hash(round + agent_type + len(templates)) % len."""
        idx = (round_number * 7 + hash(agent_type)) % len(templates)
        return templates[idx]
```

This provides variation without randomness — same room always produces same output for reproducibility, but different rooms produce different phrasing.

### Deterministic Skill Detection

Skill detection uses a **keyword → skill mapping** with explicit relevance reasons:

```python
SKILL_RULES = {
    "web_development": {
        "keywords": ["web", "website", "app", "dashboard", "frontend", "react", "nextjs", "landing page"],
        "skills": [
            {"name": "Frontend Development", "description": "UI/UX implementation", "reason": "Project involves web interface development"},
            {"name": "Responsive Design", "description": "Mobile-friendly layouts", "reason": "Web project needs cross-device support"},
        ]
    },
    "api_backend": {
        "keywords": ["api", "backend", "server", "database", "rest", "endpoint", "microservice"],
        "skills": [
            {"name": "Backend Development", "description": "API and data layer", "reason": "Project requires server-side logic"},
            {"name": "Database Design", "description": "Schema and queries", "reason": "Backend projects typically need data persistence"},
        ]
    },
    "mobile": {
        "keywords": ["mobile", "ios", "android", "react native", "app store"],
        "skills": [...]
    },
    ...
}

class SkillDetector:
    def detect(self, idea_text: str, agent_messages: list) -> list[dict]:
        """Match idea + agent discussion against keyword rules.
        Returns list of suggested skills with relevance reasons."""
        matched_rules = set()
        text_lower = idea_text.lower()
        for rule_key, rule in SKILL_RULES.items():
            for kw in rule["keywords"]:
                if kw in text_lower:
                    matched_rules.add(rule_key)
                    break
        # Also scan agent messages for additional signals
        ...
        return deduplicated_skills_with_reasons
```

Properties:
- **Deterministic**: same input always produces same skill suggestions
- **Explainable**: every suggestion includes a clear reason string
- **Extendable**: add new rule groups without changing detection logic
- **LLM-ready**: the `SkillDetector` class can be swapped for an LLM-based detector later

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
  Injects brainstorm context summary into project memory
  Sets room status to spawned, links project_id
  Response: { project_id: string, room: BrainstormRoom }
```

### Brainstorm → Execution Context Bridge (MANDATORY)

When a room is spawned, the system generates a `BrainstormContextSummary` and injects it into the project's `MemorySnapshot`. This ensures execution agents can access the full brainstorm context.

```python
class BrainstormContextBridge:
    async def generate_summary(
        self, room: BrainstormRoom, messages: list[BrainstormMessage]
    ) -> str:
        """Synthesize brainstorm into structured context for execution agents."""
        # Returns a formatted string containing:
        # - Key decisions made during brainstorm
        # - Architecture direction agreed upon
        # - Risks identified by agents
        # - Assumptions stated
        # - Important discussion points
        # - Accepted skills and their purpose
```

The summary is stored in `MemorySnapshot.next_step` field as a structured block. The `last_completed` field is set to "Project spawned from brainstorm". Execution agents read this on first task assignment.

Format injected into memory:
```
[Brainstorm Context]
Idea: {room.idea_text}
Key Decisions: {extracted decisions}
Architecture: {architecture direction}
Risks: {identified risks}
Assumptions: {stated assumptions}
Skills Locked: {accepted skills with reasons}
Agent Discussion Summary: {condensed highlights}
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

## Auto-Rotation Flow (Hybrid Model)

### Primary: Frontend-Triggered

User calls `/advance` → agents generate responses → round completes.

### Fallback: Backend Auto-Advance

Background task in `main.py` monitors brainstorm rooms:

```python
async def _auto_advance_stale_rooms():
    """If a brainstorming room has had no activity for 60s, auto-trigger next round."""
    while True:
        await asyncio.sleep(30)
        rooms = find rooms where status == "brainstorming"
            and current_round < max_rounds
            and (now - updated_at) > 60 seconds
        for room in rooms:
            await advance_room(room.id)
```

This prevents stalled sessions while preserving user control. The 60-second timeout is generous enough that active users won't be preempted.

### Full Lifecycle

1. Room created → 6 BrainstormAgents auto-created with turn_order
2. Frontend calls `/advance` OR backend auto-triggers after 60s idle
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
7. Status → spawned, Project created, brainstorm context injected into project memory

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
2. BrainstormAgentBase + SimulatedBrainstormAgent (with multi-template variation)
3. SkillDetector (deterministic keyword-based detection)
4. Brainstorm API routes (CRUD + flow control + skills)
5. Auto-rotation logic + SpawnPlanGenerator
6. BrainstormContextBridge (brainstorm → execution context injection)
7. Backend auto-advance fallback timer (in main.py)
8. Frontend types + API client methods
9. Global Lobby page
10. Brainstorm Room page
11. Integration testing
