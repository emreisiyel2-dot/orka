# Phase 3A: Multi-Room Brainstorm System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-room brainstorm system with auto-rotating agents, deterministic skill detection, spawn plan generation, and context bridge to execution agents.

**Architecture:** New subsystem with 4 data models, 4 service classes, 1 API router, 1 background task. Fully additive — no existing files modified except `database.py` (one import line) and `main.py` (router + background task registration). Frontend gets 2 new pages and the lobby page replaces the current homepage.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic, Next.js 14, TypeScript, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-04-23-phase-3a-brainstorm-rooms-design.md`

---

## File Structure

### Backend — New Files

| File | Responsibility |
|------|---------------|
| `backend/app/services/brainstorm_agent.py` | `BrainstormAgentBase` ABC + `SimulatedBrainstormAgent` with multi-template variation |
| `backend/app/services/skill_detector.py` | `SkillDetector` — keyword-based deterministic skill detection |
| `backend/app/services/spawn_plan_generator.py` | `SpawnPlanGenerator` + Pydantic `SpawnPlan` schema |
| `backend/app/services/brainstorm_context_bridge.py` | `BrainstormContextBridge` — transfers brainstorm context to project memory |
| `backend/app/api/brainstorms.py` | All brainstorm API routes (CRUD, advance, message, skip, spawn, skills) |

### Backend — Modified Files

| File | Change |
|------|--------|
| `backend/app/models.py` | Add 4 new models at end of file |
| `backend/app/schemas.py` | Add brainstorm Pydantic schemas at end of file |
| `backend/app/database.py` | Add new model imports |
| `backend/app/main.py` | Add brainstorm router + auto-advance background task |

### Frontend — New Files

| File | Responsibility |
|------|---------------|
| `frontend/app/brainstorm/[id]/page.tsx` | Brainstorm room page |
| `frontend/components/BrainstormChat.tsx` | Multi-agent chat panel |
| `frontend/components/BrainstormSidebar.tsx` | Agents, skills, actions sidebar |

### Frontend — Modified Files

| File | Change |
|------|--------|
| `frontend/lib/types.ts` | Add brainstorm types at end of file |
| `frontend/lib/api.ts` | Add brainstorm API methods |
| `frontend/app/page.tsx` | Replace with Global Lobby (brainstorm rooms + project rooms) |

---

## Task 1: Backend Data Models + Pydantic Schemas

**Files:**
- Modify: `backend/app/models.py` (append after `TaskDependency` class)
- Modify: `backend/app/schemas.py` (append after Phase 3 schemas)
- Modify: `backend/app/database.py` (update imports)

- [ ] **Step 1: Add brainstorm models to models.py**

Append after the `TaskDependency` class at the end of `backend/app/models.py`:

```python


# ──────────────────────────────────────────────
# Phase 3A: Brainstorm System
# ──────────────────────────────────────────────


class BrainstormRoom(Base):
    __tablename__ = "brainstorm_rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    idea_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(
            "brainstorming",
            "refining",
            "ready_to_spawn",
            "spawned",
            name="brainstorm_status",
        ),
        nullable=False,
        default="brainstorming",
    )
    current_round: Mapped[int] = mapped_column(default=0)
    max_rounds: Mapped[int] = mapped_column(default=3)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=True
    )
    spawn_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=_utcnow, onupdate=_utcnow
    )

    project: Mapped["Project | None"] = relationship("Project")
    messages: Mapped[list["BrainstormMessage"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    agents: Mapped[list["BrainstormAgent"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )
    skills: Mapped[list["BrainstormSkill"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class BrainstormMessage(Base):
    __tablename__ = "brainstorm_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brainstorm_rooms.id"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brainstorm_agents.id"), nullable=True
    )
    agent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[str] = mapped_column(
        SAEnum("user", "agent", "system", name="brainstorm_msg_role"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(
        SAEnum(
            "idea",
            "question",
            "analysis",
            "risk",
            "suggestion",
            "plan",
            "challenge",
            name="brainstorm_msg_type",
        ),
        nullable=False,
        default="idea",
    )
    round_number: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    room: Mapped["BrainstormRoom"] = relationship(back_populates="messages")
    agent: Mapped["BrainstormAgent | None"] = relationship(
        back_populates="messages"
    )


class BrainstormAgent(Base):
    __tablename__ = "brainstorm_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brainstorm_rooms.id"), nullable=False
    )
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum("active", "paused", "completed", name="brainstorm_agent_status"),
        nullable=False,
        default="active",
    )
    turn_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    room: Mapped["BrainstormRoom"] = relationship(back_populates="agents")
    messages: Mapped[list["BrainstormMessage"]] = relationship(
        back_populates="agent"
    )


class BrainstormSkill(Base):
    __tablename__ = "brainstorm_skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("brainstorm_rooms.id"), nullable=False
    )
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    relevance_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(
            "suggested",
            "accepted",
            "rejected",
            "locked",
            name="brainstorm_skill_status",
        ),
        nullable=False,
        default="suggested",
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    room: Mapped["BrainstormRoom"] = relationship(back_populates="skills")
```

- [ ] **Step 2: Add brainstorm Pydantic schemas to schemas.py**

Append after the `TaskDependencyResponse` class at the end of `backend/app/schemas.py`:

```python


# ──────────────────────────────────────────────
# Phase 3A: Brainstorm System
# ──────────────────────────────────────────────


class BrainstormRoomCreate(BaseModel):
    idea_text: str
    title: str | None = None


class BrainstormRoomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    idea_text: str
    status: str
    current_round: int
    max_rounds: int
    project_id: str | None = None
    spawn_plan: str | None = None
    created_at: datetime
    updated_at: datetime


class BrainstormAgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_type: str
    agent_name: str
    status: str
    turn_order: int


class BrainstormMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    room_id: str
    agent_id: str | None = None
    agent_type: str | None = None
    role: str
    content: str
    message_type: str
    round_number: int
    created_at: datetime


class BrainstormSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skill_name: str
    description: str
    relevance_reason: str
    status: str


class BrainstormRoomDetail(BrainstormRoomResponse):
    messages: list[BrainstormMessageResponse] = []
    agents: list[BrainstormAgentResponse] = []
    skills: list[BrainstormSkillResponse] = []


class BrainstormUserMessage(BaseModel):
    content: str
    target_agent_type: str | None = None


class BrainstormSkillUpdate(BaseModel):
    status: str


# ──────────────────────────────────────────────
# Phase 3A: Spawn Plan Schemas
# ──────────────────────────────────────────────


class SpawnPlanTask(BaseModel):
    title: str
    agent_type: str
    depends_on: list[str] | None = None
    priority: str = "medium"
    estimated_complexity: str = "moderate"


class SpawnPlanRisk(BaseModel):
    description: str
    severity: str
    mitigation: str


class SpawnPlanSkillItem(BaseModel):
    name: str
    description: str
    reason: str


class SpawnPlan(BaseModel):
    project_name: str
    description: str
    tasks: list[SpawnPlanTask]
    architecture_notes: list[str]
    risks: list[SpawnPlanRisk]
    next_steps: list[str]
    skills: list[SpawnPlanSkillItem]
```

- [ ] **Step 3: Update database.py imports**

Replace the import line in `backend/app/database.py`:

```python
from app.models import Agent, Base, Worker, WorkerSession, WorkerLog, AutonomousDecision, AgentMessage, TaskDependency, BrainstormRoom, BrainstormMessage, BrainstormAgent, BrainstormSkill
```

This ensures the new tables are created by `Base.metadata.create_all`.

- [ ] **Step 4: Verify backend starts**

Run: `cd backend && source venv/bin/activate && rm -f orka.db && python -c "from app.main import app; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/schemas.py backend/app/database.py
git commit -m "feat(3a): brainstorm data models and schemas — BrainstormRoom, BrainstormMessage, BrainstormAgent, BrainstormSkill, SpawnPlan"
```

---

## Task 2: SimulatedBrainstormAgent (Multi-Template Variation)

**Files:**
- Create: `backend/app/services/brainstorm_agent.py`

- [ ] **Step 1: Create brainstorm_agent.py**

```python
"""Brainstorm agent interface — simulated now, LLM-ready for Phase 3B."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class BrainstormResponse:
    content: str
    message_type: str  # analysis, question, risk, suggestion, challenge


class BrainstormAgentBase(ABC):
    """Base class for brainstorm agents. Swap implementation for LLM later."""

    @abstractmethod
    def generate_response(
        self,
        agent_type: str,
        idea_text: str,
        conversation: list[dict],
        round_number: int,
    ) -> BrainstormResponse:
        pass


AGENT_NAMES = {
    "orchestrator": "Orchestrator",
    "backend": "Backend Agent",
    "frontend": "Frontend Agent",
    "qa": "QA Agent",
    "docs": "Docs Agent",
    "memory": "Memory Agent",
}

AGENT_ORDER = ["orchestrator", "backend", "frontend", "qa", "docs", "memory"]

# Multi-template variation: 3+ templates per agent type per contribution type
# Deterministic selection via hash(round + agent_type) % len(templates)
TEMPLATES: dict[str, dict[str, list[str]]] = {
    "orchestrator": {
        "analysis": [
            "This idea breaks down into {count} key areas: {areas}. The critical path starts with the foundation layer.",
            "I see {count} major components in this: {areas}. We should prioritize the core first, then build outward.",
            "Looking at this holistically, there are {areas} to address. Let me map the dependency chain.",
        ],
        "question": [
            "What is the primary user problem this solves? Understanding the core pain point will shape everything.",
            "Who are the target users? Their technical level affects our architecture choices.",
            "What's the expected scale? This determines whether we need a simple or distributed architecture.",
        ],
        "suggestion": [
            "I recommend starting with a minimal viable scope. We can always expand based on feedback.",
            "Let's define clear milestones. Breaking this into phases reduces risk and enables early validation.",
            "We should identify the single most critical feature and build around that first.",
        ],
    },
    "backend": {
        "analysis": [
            "From a backend perspective, we'll need a data model for {areas} and API endpoints to expose CRUD operations.",
            "The server architecture should handle {areas}. I'd suggest a RESTful API with clear resource boundaries.",
            "Backend-wise, the core challenge is managing {areas}. We need a solid persistence layer first.",
        ],
        "question": [
            "What data persistence approach fits best? SQL gives structure, NoSQL gives flexibility.",
            "Are there external integrations needed? Third-party APIs affect our error handling strategy.",
            "What's the expected read/write ratio? This shapes our caching and indexing approach.",
        ],
        "suggestion": [
            "Start with the data model design. Getting the schema right early prevents expensive migrations later.",
            "I suggest a layered architecture: routes → services → repositories. Clean separation of concerns.",
            "Let's define the API contract first. OpenAPI spec before implementation keeps frontend unblocked.",
        ],
        "risk": [
            "Database schema changes late in development can cascade. We should nail the core entities early.",
            "Without rate limiting, the API is vulnerable to abuse. Plan for authentication from the start.",
        ],
    },
    "frontend": {
        "analysis": [
            "The UI needs {areas} as core views. Each view should be responsive and accessible from day one.",
            "From a frontend angle, the user flows map to {areas}. State management will be critical here.",
            "The interface revolves around {areas}. We should prioritize the most-used views for polish.",
        ],
        "question": [
            "What's the primary device target? Mobile-first and desktop-first lead to very different layouts.",
            "Should this be a single-page app or multi-page? It affects routing and state management.",
            "Are there existing design guidelines or brand assets we should follow?",
        ],
        "suggestion": [
            "Build a component library first. Reusable components speed up all subsequent view development.",
            "I recommend a state management pattern early. Context + hooks for simple cases, store for complex.",
            "Start with the core layout and navigation shell, then fill in each view progressively.",
        ],
        "risk": [
            "Without early responsive testing, mobile layouts break at the worst time. Test on real devices weekly.",
            "State management sprawl is a real risk. Define data flow patterns before writing components.",
        ],
    },
    "qa": {
        "analysis": [
            "I see several risk areas: {areas}. Each needs a specific testing strategy — unit, integration, or E2E.",
            "From a quality perspective, the critical paths are {areas}. A failure in any of these is a showstopper.",
            "Testing this properly means covering {areas}. I'll map out the test pyramid for each.",
        ],
        "question": [
            "What's the tolerance for bugs in the initial release? This determines testing depth.",
            "Are there compliance or security requirements? These add mandatory test categories.",
            "What's the expected user concurrency? Load testing requirements depend on this.",
        ],
        "risk": [
            "Rushing to release without integration tests means bugs surface in production when users find them.",
            "If data validation is inconsistent between frontend and backend, we'll see silent data corruption.",
            "Third-party dependencies can fail silently. Every external call needs error handling and fallbacks.",
            "Missing edge cases in auth flows can expose security holes. Test unauthorized access paths explicitly.",
        ],
        "suggestion": [
            "Define acceptance criteria for each feature before implementation. Test against those criteria.",
            "Set up CI from day one. Automated tests that don't run automatically don't get run.",
            "I suggest a risk-based testing approach: test critical paths deeply, edge cases moderately.",
        ],
    },
    "docs": {
        "analysis": [
            "Documentation needs cover {areas}. API docs, user guides, and developer onboarding are the essentials.",
            "From a documentation angle, we'll need {areas}. Good docs reduce support burden significantly.",
            "The docs strategy should address {areas}. Different audiences need different documentation.",
        ],
        "suggestion": [
            "Start with API documentation alongside development. Auto-generated docs from code stay current.",
            "A getting-started guide is the highest-value doc. New users (and developers) hit this first.",
            "Consider inline code documentation as part of the definition of done. Not an afterthought.",
        ],
        "question": [
            "Who are the docs primarily for? Developers, end users, or both? This changes tone and depth.",
            "Is there existing documentation infrastructure we should integrate with?",
        ],
    },
    "memory": {
        "analysis": [
            "Progress summary: We've identified {count} key areas to address. The team has raised {issues} important points so far.",
            "Status check: The discussion has covered {areas}. There are open questions we should resolve before spawning.",
            "Tracking this discussion: {count} topics covered, key open items remain around architecture and scope.",
        ],
        "suggestion": [
            "I recommend we converge on scope now. The core areas are clear — let's define the MVP boundary.",
            "Based on the discussion so far, we have enough to generate a solid plan. I suggest moving to refining.",
            "Key decisions are documented. The remaining unknowns can be resolved during execution.",
        ],
        "question": [
            "Are there unresolved disagreements? It's better to align now than to discover conflicts during execution.",
            "Is the scope well-defined enough to estimate effort? Vague scope leads to vague execution.",
        ],
    },
}


def _extract_areas(idea_text: str) -> str:
    """Extract potential areas from idea text for template filling."""
    words = idea_text.lower().split()
    areas = []
    keywords_map = {
        "api": "API design",
        "database": "data layer",
        "ui": "user interface",
        "frontend": "frontend architecture",
        "backend": "backend services",
        "auth": "authentication",
        "payment": "payment flow",
        "dashboard": "dashboard views",
        "mobile": "mobile experience",
        "web": "web platform",
        "app": "application core",
        "user": "user management",
        "data": "data handling",
        "real-time": "realtime layer",
        "notification": "notification system",
        "search": "search functionality",
        "chat": "chat system",
        "ai": "AI integration",
        "ml": "ML pipeline",
    }
    for kw, area in keywords_map.items():
        if kw in words and area not in areas:
            areas.append(area)
    if not areas:
        areas = ["core functionality", "data layer", "user interface"]
    return ", ".join(areas[:4])


class SimulatedBrainstormAgent(BrainstormAgentBase):
    """Template-based deterministic brainstorm agent with variation."""

    def generate_response(
        self,
        agent_type: str,
        idea_text: str,
        conversation: list[dict],
        round_number: int,
    ) -> BrainstormResponse:
        areas = _extract_areas(idea_text)
        agent_templates = TEMPLATES.get(agent_type, TEMPLATES["orchestrator"])

        # Determine contribution type based on round and agent position
        contribution_types = self._get_contribution_types(
            agent_type, round_number, len(conversation)
        )
        msg_type = contribution_types[0]

        templates = agent_templates.get(msg_type, agent_templates["analysis"])

        # Deterministic template selection: hash-based index
        idx = (round_number * 7 + hash(agent_type)) % len(templates)
        template = templates[idx]

        content = template.format(
            count=min(len(areas.split(",")), 5),
            areas=areas,
            issues=len(conversation),
        )

        return BrainstormResponse(content=content, message_type=msg_type)

    def _get_contribution_types(
        self, agent_type: str, round_number: int, conv_len: int
    ) -> list[str]:
        """Each agent contributes differently based on round."""
        if agent_type == "qa":
            if round_number <= 1:
                return ["risk"]
            return ["risk", "question"]
        if agent_type == "memory":
            if round_number >= 2:
                return ["suggestion"]
            return ["analysis"]
        if round_number == 0:
            return ["analysis"]
        if round_number == 1:
            return ["question", "suggestion"]
        return ["suggestion", "analysis"]
```

- [ ] **Step 2: Verify import works**

Run: `cd backend && source venv/bin/activate && python -c "from app.services.brainstorm_agent import SimulatedBrainstormAgent; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/brainstorm_agent.py
git commit -m "feat(3a): SimulatedBrainstormAgent with multi-template variation and deterministic selection"
```

---

## Task 3: SkillDetector (Deterministic Keyword-Based)

**Files:**
- Create: `backend/app/services/skill_detector.py`

- [ ] **Step 1: Create skill_detector.py**

```python
"""Deterministic skill detection — keyword-based rules, LLM-ready for Phase 3B."""

from dataclasses import dataclass


@dataclass
class DetectedSkill:
    name: str
    description: str
    relevance_reason: str


SKILL_RULES: dict[str, dict] = {
    "web_development": {
        "keywords": [
            "web", "website", "dashboard", "landing page", "portal",
            "spa", "single page", "frontend", "ui",
        ],
        "skills": [
            DetectedSkill(
                name="Frontend Development",
                description="UI/UX implementation with modern frameworks",
                relevance_reason="Project involves web interface development",
            ),
            DetectedSkill(
                name="Responsive Design",
                description="Mobile-friendly layouts and cross-device support",
                relevance_reason="Web projects need cross-device compatibility",
            ),
        ],
    },
    "api_backend": {
        "keywords": [
            "api", "backend", "server", "database", "rest", "endpoint",
            "microservice", "crud", "graphql",
        ],
        "skills": [
            DetectedSkill(
                name="Backend Development",
                description="Server-side API and business logic",
                relevance_reason="Project requires server-side logic and APIs",
            ),
            DetectedSkill(
                name="Database Design",
                description="Schema design, queries, and data modeling",
                relevance_reason="Backend projects typically need data persistence",
            ),
        ],
    },
    "mobile": {
        "keywords": [
            "mobile", "ios", "android", "react native", "app store",
            "play store", "native app", "hybrid app",
        ],
        "skills": [
            DetectedSkill(
                name="Mobile Development",
                description="Native or cross-platform mobile app development",
                relevance_reason="Project targets mobile platforms",
            ),
            DetectedSkill(
                name="Push Notifications",
                description="Mobile notification integration",
                relevance_reason="Mobile apps typically need notification support",
            ),
        ],
    },
    "ai_ml": {
        "keywords": [
            "ai", "ml", "machine learning", "model", "nlp", "chatbot",
            "neural", "training", "inference", "llm", "gpt", "claude",
        ],
        "skills": [
            DetectedSkill(
                name="AI Integration",
                description="LLM and AI model integration",
                relevance_reason="Project involves AI/ML capabilities",
            ),
            DetectedSkill(
                name="Prompt Engineering",
                description="Designing effective prompts and AI workflows",
                relevance_reason="AI projects need well-designed prompts",
            ),
        ],
    },
    "realtime": {
        "keywords": [
            "realtime", "real-time", "websocket", "live", "streaming",
            "chat", "collaboration", "sync", "sse",
        ],
        "skills": [
            DetectedSkill(
                name="Real-time Communication",
                description="WebSocket and live data streaming",
                relevance_reason="Project requires real-time data updates",
            ),
        ],
    },
    "ecommerce": {
        "keywords": [
            "payment", "ecommerce", "shop", "store", "cart", "checkout",
            "stripe", "billing", "subscription", "invoice",
        ],
        "skills": [
            DetectedSkill(
                name="Payment Integration",
                description="Payment processing and billing",
                relevance_reason="Project involves payment transactions",
            ),
            DetectedSkill(
                name="Security & Compliance",
                description="PCI compliance and secure data handling",
                relevance_reason="Payment systems require security compliance",
            ),
        ],
    },
    "auth": {
        "keywords": [
            "auth", "login", "signup", "oauth", "jwt", "session",
            "user account", "password", "sso", "identity",
        ],
        "skills": [
            DetectedSkill(
                name="Authentication & Authorization",
                description="User identity and access control",
                relevance_reason="Project needs user authentication",
            ),
        ],
    },
    "data_pipeline": {
        "keywords": [
            "etl", "pipeline", "data processing", "analytics", "warehouse",
            "migration", "import", "export", "batch", "queue",
        ],
        "skills": [
            DetectedSkill(
                name="Data Pipeline Engineering",
                description="ETL and data processing workflows",
                relevance_reason="Project involves data transformation or migration",
            ),
        ],
    },
}


class SkillDetector:
    """Deterministic keyword-based skill detector."""

    def detect(self, idea_text: str, agent_messages: list[dict] | None = None) -> list[DetectedSkill]:
        text_lower = idea_text.lower()
        # Also scan agent messages for additional signals
        if agent_messages:
            for msg in agent_messages:
                text_lower += " " + msg.get("content", "").lower()

        seen_names: set[str] = set()
        results: list[DetectedSkill] = []

        for rule_key, rule in SKILL_RULES.items():
            matched = False
            for kw in rule["keywords"]:
                if kw in text_lower:
                    matched = True
                    break
            if matched:
                for skill in rule["skills"]:
                    if skill.name not in seen_names:
                        seen_names.add(skill.name)
                        results.append(skill)

        if not results:
            results.append(
                DetectedSkill(
                    name="General Development",
                    description="Software development fundamentals",
                    relevance_reason="Default skill for general-purpose projects",
                )
            )

        return results
```

- [ ] **Step 2: Verify import**

Run: `cd backend && source venv/bin/activate && python -c "from app.services.skill_detector import SkillDetector; d = SkillDetector(); print(len(d.detect('Build a web dashboard with API')))" `

Expected: `4` (Frontend Dev, Responsive Design, Backend Dev, Database Design)

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/skill_detector.py
git commit -m "feat(3a): deterministic SkillDetector with keyword-to-skill rule mapping"
```

---

## Task 4: SpawnPlanGenerator + BrainstormContextBridge

**Files:**
- Create: `backend/app/services/spawn_plan_generator.py`
- Create: `backend/app/services/brainstorm_context_bridge.py`

- [ ] **Step 1: Create spawn_plan_generator.py**

```python
"""Generate structured spawn plans from brainstorm conversations."""

from app.schemas import (
    SpawnPlan,
    SpawnPlanTask,
    SpawnPlanRisk,
    SpawnPlanSkillItem,
)
from app.services.skill_detector import SkillDetector


class SpawnPlanGenerator:
    """Synthesizes brainstorm messages into a machine-readable SpawnPlan."""

    def generate(
        self,
        idea_text: str,
        messages: list[dict],
    ) -> SpawnPlan:
        title = idea_text[:60].strip()
        if len(idea_text) > 60:
            title = title.rsplit(" ", 1)[0]

        # Extract areas from messages
        areas = self._extract_areas_from_messages(messages)

        # Generate tasks with dependencies
        tasks = self._generate_tasks(idea_text, areas)

        # Extract risks from QA messages
        risks = self._extract_risks(messages)

        # Get skills
        detector = SkillDetector()
        detected = detector.detect(idea_text, messages)
        skills = [
            SpawnPlanSkillItem(
                name=s.name, description=s.description, reason=s.relevance_reason
            )
            for s in detected
        ]

        return SpawnPlan(
            project_name=title,
            description=f"Project spawned from brainstorm: {idea_text[:200]}",
            tasks=tasks,
            architecture_notes=self._extract_architecture_notes(messages),
            risks=risks,
            next_steps=self._generate_next_steps(tasks),
            skills=skills,
        )

    def _extract_areas_from_messages(self, messages: list[dict]) -> list[str]:
        areas = []
        for msg in messages:
            if msg.get("message_type") == "analysis" and msg.get("content"):
                content = msg["content"]
                if ":" in content:
                    parts = content.split(":", 1)[1].strip()
                    for area in parts.split(","):
                        area = area.strip().rstrip(".")
                        if area and area not in areas:
                            areas.append(area)
        return areas[:6]

    def _generate_tasks(
        self, idea_text: str, areas: list[str]
    ) -> list[SpawnPlanTask]:
        base_title = idea_text[:40].strip()
        tasks = [
            SpawnPlanTask(
                title=f"Design and implement backend for: {base_title}",
                agent_type="backend",
                depends_on=None,
                priority="high",
                estimated_complexity="complex",
            ),
            SpawnPlanTask(
                title=f"Build frontend interface for: {base_title}",
                agent_type="frontend",
                depends_on=["Design and implement backend for: " + base_title],
                priority="high",
                estimated_complexity="complex",
            ),
            SpawnPlanTask(
                title=f"QA testing for: {base_title}",
                agent_type="qa",
                depends_on=["Build frontend interface for: " + base_title],
                priority="medium",
                estimated_complexity="moderate",
            ),
            SpawnPlanTask(
                title=f"Write documentation for: {base_title}",
                agent_type="docs",
                depends_on=["QA testing for: " + base_title],
                priority="low",
                estimated_complexity="simple",
            ),
        ]
        return tasks

    def _extract_risks(self, messages: list[dict]) -> list[SpawnPlanRisk]:
        risks = []
        for msg in messages:
            if msg.get("message_type") == "risk" and msg.get("content"):
                risks.append(
                    SpawnPlanRisk(
                        description=msg["content"][:200],
                        severity="medium",
                        mitigation="Address during implementation phase",
                    )
                )
        if not risks:
            risks.append(
                SpawnPlanRisk(
                    description="Scope creep — brainstorm scope may differ from execution reality",
                    severity="medium",
                    mitigation="Regular scope reviews during execution",
                )
            )
        return risks[:5]

    def _extract_architecture_notes(self, messages: list[dict]) -> list[str]:
        notes = []
        for msg in messages:
            if msg.get("agent_type") == "backend" and msg.get("message_type") in (
                "analysis",
                "suggestion",
            ):
                notes.append(msg["content"][:150])
        if not notes:
            notes.append("Architecture to be defined during implementation.")
        return notes[:4]

    def _generate_next_steps(self, tasks: list[SpawnPlanTask]) -> list[str]:
        steps = []
        if tasks:
            steps.append(f"Start with: {tasks[0].title}")
        steps.extend([
            "Review and refine task breakdown",
            "Set up development environment",
            "Begin first sprint",
        ])
        return steps
```

- [ ] **Step 2: Create brainstorm_context_bridge.py**

```python
"""Transfer brainstorm context to execution agents on spawn."""


class BrainstormContextBridge:
    """Generates a structured summary from brainstorm for project memory."""

    def generate_summary(
        self,
        idea_text: str,
        messages: list[dict],
        spawn_plan: dict,
    ) -> str:
        decisions = self._extract_by_type(messages, "suggestion")
        risks = self._extract_by_type(messages, "risk")
        questions = self._extract_by_type(messages, "question")

        sections = [
            "[Brainstorm Context]",
            f"Idea: {idea_text}",
            "",
            "[Key Decisions]",
        ]
        for i, d in enumerate(decisions[:5], 1):
            sections.append(f"  {i}. {d}")

        sections.append("")
        sections.append("[Architecture Direction]")
        for note in spawn_plan.get("architecture_notes", [])[:3]:
            sections.append(f"  - {note}")

        sections.append("")
        sections.append("[Risks Identified]")
        for risk in spawn_plan.get("risks", [])[:5]:
            sections.append(f"  - {risk['description']} ({risk['severity']})")

        sections.append("")
        sections.append("[Open Questions]")
        for i, q in enumerate(questions[:5], 1):
            sections.append(f"  {i}. {q}")

        sections.append("")
        sections.append("[Locked Skills]")
        for skill in spawn_plan.get("skills", []):
            sections.append(f"  - {skill['name']}: {skill['reason']}")

        sections.append("")
        sections.append("[Discussion Highlights]")
        for msg in messages[-8:]:
            role = msg.get("agent_type") or msg.get("role", "unknown")
            content = msg.get("content", "")[:100]
            sections.append(f"  [{role}] {content}")

        return "\n".join(sections)

    def _extract_by_type(self, messages: list[dict], msg_type: str) -> list[str]:
        results = []
        for msg in messages:
            if msg.get("message_type") == msg_type and msg.get("content"):
                results.append(msg["content"][:200])
        return results
```

- [ ] **Step 3: Verify both imports**

Run: `cd backend && source venv/bin/activate && python -c "from app.services.spawn_plan_generator import SpawnPlanGenerator; from app.services.brainstorm_context_bridge import BrainstormContextBridge; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/spawn_plan_generator.py backend/app/services/brainstorm_context_bridge.py
git commit -m "feat(3a): SpawnPlanGenerator and BrainstormContextBridge"
```

---

## Task 5: Brainstorm API Routes

**Files:**
- Create: `backend/app/api/brainstorms.py`

- [ ] **Step 1: Create brainstorms.py**

```python
"""Brainstorm room API — CRUD, advance, message, skip, spawn, skills."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    BrainstormRoom,
    BrainstormMessage,
    BrainstormAgent,
    BrainstormSkill,
    Project,
    Task,
    MemorySnapshot,
    ActivityLog,
)
from app.schemas import (
    BrainstormRoomCreate,
    BrainstormRoomResponse,
    BrainstormRoomDetail,
    BrainstormAgentResponse,
    BrainstormMessageResponse,
    BrainstormSkillResponse,
    BrainstormUserMessage,
    BrainstormSkillUpdate,
    SpawnPlan,
)
from app.services.brainstorm_agent import (
    SimulatedBrainstormAgent,
    AGENT_ORDER,
    AGENT_NAMES,
)
from app.services.skill_detector import SkillDetector
from app.services.spawn_plan_generator import SpawnPlanGenerator
from app.services.brainstorm_context_bridge import BrainstormContextBridge

router = APIRouter(prefix="/api/brainstorms", tags=["brainstorms"])

 brainstorm_agent = SimulatedBrainstormAgent()
skill_detector = SkillDetector()
plan_generator = SpawnPlanGenerator()
context_bridge = BrainstormContextBridge()


def _room_to_response(room: BrainstormRoom) -> dict:
    return {
        "id": room.id,
        "title": room.title,
        "idea_text": room.idea_text,
        "status": room.status,
        "current_round": room.current_round,
        "max_rounds": room.max_rounds,
        "project_id": room.project_id,
        "spawn_plan": room.spawn_plan,
        "created_at": room.created_at,
        "updated_at": room.updated_at,
    }


def _agent_to_response(agent: BrainstormAgent) -> dict:
    return {
        "id": agent.id,
        "agent_type": agent.agent_type,
        "agent_name": agent.agent_name,
        "status": agent.status,
        "turn_order": agent.turn_order,
    }


def _msg_to_response(msg: BrainstormMessage) -> dict:
    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "agent_id": msg.agent_id,
        "agent_type": msg.agent_type,
        "role": msg.role,
        "content": msg.content,
        "message_type": msg.message_type,
        "round_number": msg.round_number,
        "created_at": msg.created_at,
    }


def _skill_to_response(skill: BrainstormSkill) -> dict:
    return {
        "id": skill.id,
        "skill_name": skill.skill_name,
        "description": skill.description,
        "relevance_reason": skill.relevance_reason,
        "status": skill.status,
    }


async def _get_room_or_404(room_id: str, db: AsyncSession) -> BrainstormRoom:
    result = await db.execute(
        select(BrainstormRoom).where(BrainstormRoom.id == room_id)
    )
    room = result.scalars().first()
    if room is None:
        raise HTTPException(status_code=404, detail="Brainstorm room not found")
    return room


async def _create_room_agents(room: BrainstormRoom, db: AsyncSession) -> None:
    """Create 6 brainstorm agents for a new room."""
    for i, agent_type in enumerate(AGENT_ORDER):
        agent = BrainstormAgent(
            room_id=room.id,
            agent_type=agent_type,
            agent_name=AGENT_NAMES[agent_type],
            turn_order=i,
        )
        db.add(agent)
    await db.flush()


async def _create_initial_skills(room: BrainstormRoom, db: AsyncSession) -> None:
    """Detect and create skills for a new room."""
    detected = skill_detector.detect(room.idea_text)
    for skill in detected:
        db.add(BrainstormSkill(
            room_id=room.id,
            skill_name=skill.name,
            description=skill.description,
            relevance_reason=skill.relevance_reason,
        ))
    await db.flush()


async def _generate_agent_round(room: BrainstormRoom, db: AsyncSession) -> list[BrainstormMessage]:
    """Generate responses from all active agents for the current round."""
    agents_result = await db.execute(
        select(BrainstormAgent)
        .where(BrainstormAgent.room_id == room.id, BrainstormAgent.status == "active")
        .order_by(BrainstormAgent.turn_order)
    )
    agents = agents_result.scalars().all()

    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room.id)
        .order_by(BrainstormMessage.created_at)
    )
    conversation = [
        {"content": m.content, "message_type": m.message_type, "agent_type": m.agent_type}
        for m in msgs_result.scalars().all()
    ]

    new_messages = []
    for agent in agents:
        response = brainstorm_agent.generate_response(
            agent_type=agent.agent_type,
            idea_text=room.idea_text,
            conversation=conversation,
            round_number=room.current_round,
        )
        msg = BrainstormMessage(
            room_id=room.id,
            agent_id=agent.id,
            agent_type=agent.agent_type,
            role="agent",
            content=response.content,
            message_type=response.message_type,
            round_number=room.current_round,
        )
        db.add(msg)
        new_messages.append(msg)
        conversation.append({
            "content": response.content,
            "message_type": response.message_type,
            "agent_type": agent.agent_type,
        })

    await db.flush()
    return new_messages


async def _transition_to_refining(room: BrainstormRoom, db: AsyncSession) -> None:
    """Generate spawn plan and transition room to ready_to_spawn."""
    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room.id)
        .order_by(BrainstormMessage.created_at)
    )
    messages = msgs_result.scalars().all()
    message_dicts = [
        {"content": m.content, "message_type": m.message_type, "agent_type": m.agent_type}
        for m in messages
    ]

    spawn_plan = plan_generator.generate(room.idea_text, message_dicts)
    room.spawn_plan = spawn_plan.model_dump_json()
    room.status = "ready_to_spawn"
    room.updated_at = datetime.now(timezone.utc)


# ── CRUD ──────────────────────────────────────────────


@router.post("", response_model=BrainstormRoomResponse, status_code=201)
async def create_room(
    payload: BrainstormRoomCreate,
    db: AsyncSession = Depends(get_db),
):
    title = payload.title or payload.idea_text[:80]
    room = BrainstormRoom(
        title=title,
        idea_text=payload.idea_text,
    )
    db.add(room)
    await db.flush()
    await db.refresh(room)

    await _create_room_agents(room, db)
    await _create_initial_skills(room, db)

    await db.refresh(room)
    return _room_to_response(room)


@router.get("", response_model=list[BrainstormRoomResponse])
async def list_rooms(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BrainstormRoom).order_by(BrainstormRoom.created_at.desc())
    if status:
        stmt = stmt.where(BrainstormRoom.status == status)
    result = await db.execute(stmt)
    rooms = result.scalars().all()
    return [_room_to_response(r) for r in rooms]


@router.get("/{room_id}", response_model=BrainstormRoomDetail)
async def get_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room_id)
        .order_by(BrainstormMessage.created_at)
    )
    agents_result = await db.execute(
        select(BrainstormAgent)
        .where(BrainstormAgent.room_id == room_id)
        .order_by(BrainstormAgent.turn_order)
    )
    skills_result = await db.execute(
        select(BrainstormSkill).where(BrainstormSkill.room_id == room_id)
    )

    resp = _room_to_response(room)
    resp["messages"] = [_msg_to_response(m) for m in msgs_result.scalars().all()]
    resp["agents"] = [_agent_to_response(a) for a in agents_result.scalars().all()]
    resp["skills"] = [_skill_to_response(s) for s in skills_result.scalars().all()]
    return resp


@router.delete("/{room_id}")
async def delete_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)
    await db.delete(room)
    return {"deleted": True}


# ── Flow Control ──────────────────────────────────────


@router.post("/{room_id}/advance", response_model=list[BrainstormMessageResponse])
async def advance_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")

    if room.status in ("refining", "ready_to_spawn"):
        raise HTTPException(400, "Room is past brainstorming phase")

    # Hard round limit: max 4
    if room.current_round >= room.max_rounds:
        await _transition_to_refining(room, db)
        await db.flush()
        return []

    room.current_round += 1
    room.updated_at = datetime.now(timezone.utc)

    new_messages = await _generate_agent_round(room, db)

    # Check if we hit the round limit after this round
    if room.current_round >= room.max_rounds:
        await _transition_to_refining(room, db)

    await db.flush()
    return [_msg_to_response(m) for m in new_messages]


@router.post("/{room_id}/message", response_model=list[BrainstormMessageResponse])
async def send_message(
    room_id: str,
    payload: BrainstormUserMessage,
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")
    if room.status in ("refining", "ready_to_spawn"):
        raise HTTPException(400, "Room is past brainstorming phase")

    # Create user message
    user_msg = BrainstormMessage(
        room_id=room.id,
        agent_id=None,
        agent_type=None,
        role="user",
        content=payload.content,
        message_type="idea",
        round_number=room.current_round,
    )
    db.add(user_msg)
    await db.flush()

    results = [user_msg]

    # If targeted at a specific agent, only that agent responds
    if payload.target_agent_type:
        agent_result = await db.execute(
            select(BrainstormAgent).where(
                BrainstormAgent.room_id == room.id,
                BrainstormAgent.agent_type == payload.target_agent_type,
                BrainstormAgent.status == "active",
            )
        )
        agent = agent_result.scalars().first()
        if agent:
            response = brainstorm_agent.generate_response(
                agent_type=agent.agent_type,
                idea_text=room.idea_text,
                conversation=[{"content": payload.content}],
                round_number=room.current_round,
            )
            agent_msg = BrainstormMessage(
                room_id=room.id,
                agent_id=agent.id,
                agent_type=agent.agent_type,
                role="agent",
                content=response.content,
                message_type="response",
                round_number=room.current_round,
            )
            db.add(agent_msg)
            results.append(agent_msg)

    room.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return [_msg_to_response(m) for m in results]


@router.post("/{room_id}/skip", response_model=BrainstormRoomResponse)
async def skip_room(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    if room.status == "brainstorming":
        await _transition_to_refining(room, db)
    elif room.status == "refining":
        room.status = "ready_to_spawn"

    room.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(room)
    return _room_to_response(room)


# ── Spawn ─────────────────────────────────────────────


@router.post("/{room_id}/spawn")
async def spawn_project(room_id: str, db: AsyncSession = Depends(get_db)):
    room = await _get_room_or_404(room_id, db)

    if room.status == "spawned":
        raise HTTPException(400, "Room already spawned")

    # If still brainstorming, force-generate plan
    if room.status in ("brainstorming", "refining"):
        if not room.spawn_plan:
            await _transition_to_refining(room, db)

    # Parse spawn plan
    import json
    plan_data = json.loads(room.spawn_plan) if room.spawn_plan else {}
    plan = SpawnPlan(**plan_data) if plan_data else None

    # Create project
    project_name = plan.project_name if plan else room.title
    project_desc = plan.description if plan else room.idea_text
    project = Project(name=project_name, description=project_desc)
    db.add(project)
    await db.flush()
    await db.refresh(project)

    # Create tasks from spawn plan
    if plan:
        task_map = {}
        for task_def in plan.tasks:
            task = Task(
                project_id=project.id,
                content=task_def.title,
                status="pending",
            )
            db.add(task)
            await db.flush()
            await db.refresh(task)
            task_map[task_def.title] = task

        # Resolve dependencies
        for task_def in plan.tasks:
            if task_def.depends_on:
                child_task = task_map.get(task_def.title)
                for dep_title in task_def.depends_on:
                    parent_task = task_map.get(dep_title)
                    if child_task and parent_task:
                        from app.models import TaskDependency
                        db.add(TaskDependency(
                            task_id=child_task.id,
                            depends_on_task_id=parent_task.id,
                        ))

    # Inject brainstorm context into project memory
    msgs_result = await db.execute(
        select(BrainstormMessage)
        .where(BrainstormMessage.room_id == room.id)
        .order_by(BrainstormMessage.created_at)
    )
    messages = msgs_result.scalars().all()
    message_dicts = [
        {"content": m.content, "message_type": m.message_type, "agent_type": m.agent_type, "role": m.role}
        for m in messages
    ]

    context_summary = context_bridge.generate_summary(
        idea_text=room.idea_text,
        messages=message_dicts,
        spawn_plan=plan_data,
    )

    memory = MemorySnapshot(
        project_id=project.id,
        last_completed="Project spawned from brainstorm",
        current_blocker="",
        next_step=context_summary,
    )
    db.add(memory)

    # Link room to project
    room.status = "spawned"
    room.project_id = project.id
    room.updated_at = datetime.now(timezone.utc)

    # Log activity
    db.add(ActivityLog(
        project_id=project.id,
        action="project_spawned",
        details=f"Project spawned from brainstorm room: {room.title}",
    ))

    await db.flush()
    return {"project_id": project.id, "room": _room_to_response(room)}


# ── Skills ────────────────────────────────────────────


@router.get("/{room_id}/skills", response_model=list[BrainstormSkillResponse])
async def list_skills(room_id: str, db: AsyncSession = Depends(get_db)):
    await _get_room_or_404(room_id, db)
    result = await db.execute(
        select(BrainstormSkill).where(BrainstormSkill.room_id == room_id)
    )
    return [_skill_to_response(s) for s in result.scalars().all()]


@router.put("/{room_id}/skills/{skill_id}", response_model=BrainstormSkillResponse)
async def update_skill(
    room_id: str,
    skill_id: str,
    payload: BrainstormSkillUpdate,
    db: AsyncSession = Depends(get_db),
):
    await _get_room_or_404(room_id, db)
    result = await db.execute(
        select(BrainstormSkill).where(
            BrainstormSkill.id == skill_id,
            BrainstormSkill.room_id == room_id,
        )
    )
    skill = result.scalars().first()
    if skill is None:
        raise HTTPException(404, "Skill not found")

    if payload.status not in ("accepted", "rejected", "suggested"):
        raise HTTPException(400, "Invalid status. Use: accepted, rejected, suggested")

    skill.status = payload.status
    await db.flush()
    return _skill_to_response(skill)
```

- [ ] **Step 2: Verify import**

Run: `cd backend && source venv/bin/activate && python -c "from app.api.brainstorms import router; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/brainstorms.py
git commit -m "feat(3a): brainstorm API routes — CRUD, advance, message, skip, spawn, skills"
```

---

## Task 6: Register Router + Auto-Advance Background Task

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add brainstorm router import and registration**

Add this import near the top of `main.py`, after the existing router imports:

```python
from app.api.brainstorms import router as brainstorms_router
```

Add this after the other `app.include_router` lines:

```python
app.include_router(brainstorms_router)
```

- [ ] **Step 2: Add auto-advance background task**

Add this background task function before the `lifespan` function in `main.py`:

```python
async def _auto_advance_stale_rooms() -> None:
    """Auto-advance brainstorm rooms idle for 60+ seconds."""
    from datetime import timedelta
    from app.models import BrainstormRoom

    while True:
        await asyncio.sleep(30)
        try:
            async with async_session() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
                result = await db.execute(
                    select(BrainstormRoom).where(
                        BrainstormRoom.status == "brainstorming",
                        BrainstormRoom.updated_at < cutoff,
                        BrainstormRoom.current_round < BrainstormRoom.max_rounds,
                    )
                )
                stale = result.scalars().all()
                for room in stale:
                    room.current_round += 1
                    room.updated_at = datetime.now(timezone.utc)
                    # Generate agent responses
                    from app.api.brainstorms import _generate_agent_round
                    await _generate_agent_round(room, db)
                    # Check round limit
                    if room.current_round >= room.max_rounds:
                        from app.api.brainstorms import _transition_to_refining
                        await _transition_to_refining(room, db)
                if stale:
                    await db.commit()
        except Exception:
            pass
```

- [ ] **Step 3: Register the auto-advance task in lifespan**

In the `lifespan` function, add after the existing `asyncio.create_task` lines:

```python
auto_advance_task = asyncio.create_task(_auto_advance_stale_rooms())
```

And add `auto_advance_task` to the cancel tuple:

```python
for t in (broadcast_task, cleanup_task, stale_worker_task, dep_task, auto_advance_task):
```

- [ ] **Step 4: Verify backend starts**

Run: `cd backend && source venv/bin/activate && rm -f orka.db && python -c "from app.main import app; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(3a): register brainstorm router and auto-advance stale rooms background task"
```

---

## Task 7: Frontend Types + API Client

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add brainstorm types to types.ts**

Append at end of `frontend/lib/types.ts`:

```typescript
// ──────────────────────────────────────────────
// Phase 3A: Brainstorm System
// ──────────────────────────────────────────────

export type BrainstormStatus = "brainstorming" | "refining" | "ready_to_spawn" | "spawned";

export interface BrainstormRoom {
  id: string;
  title: string;
  idea_text: string;
  status: BrainstormStatus;
  current_round: number;
  max_rounds: number;
  project_id: string | null;
  spawn_plan: string | null;
  created_at: string;
  updated_at: string;
}

export interface BrainstormAgent {
  id: string;
  agent_type: string;
  agent_name: string;
  status: "active" | "paused" | "completed";
  turn_order: number;
}

export type BrainstormMsgRole = "user" | "agent" | "system";
export type BrainstormMsgType = "idea" | "question" | "analysis" | "risk" | "suggestion" | "plan" | "challenge" | "response";

export interface BrainstormMessage {
  id: string;
  room_id: string;
  agent_id: string | null;
  agent_type: string | null;
  role: BrainstormMsgRole;
  content: string;
  message_type: BrainstormMsgType;
  round_number: number;
  created_at: string;
}

export type BrainstormSkillStatus = "suggested" | "accepted" | "rejected" | "locked";

export interface BrainstormSkill {
  id: string;
  skill_name: string;
  description: string;
  relevance_reason: string;
  status: BrainstormSkillStatus;
}

export interface BrainstormRoomDetail extends BrainstormRoom {
  messages: BrainstormMessage[];
  agents: BrainstormAgent[];
  skills: BrainstormSkill[];
}
```

- [ ] **Step 2: Add brainstorm API methods to api.ts**

Add the import types at the top — add `BrainstormRoom, BrainstormRoomDetail, BrainstormSkill` to the existing import from `./types`.

Append at end of `api` object in `api.ts`:

```typescript
  // Brainstorm Rooms
  getBrainstormRooms: (status?: string) =>
    fetchJSON<BrainstormRoom[]>(`${API_BASE}/api/brainstorms${status ? `?status=${status}` : ""}`),

  createBrainstormRoom: (data: { idea_text: string; title?: string }) =>
    fetchJSON<BrainstormRoom>(`${API_BASE}/api/brainstorms`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getBrainstormRoom: (id: string) =>
    fetchJSON<BrainstormRoomDetail>(`${API_BASE}/api/brainstorms/${id}`),

  deleteBrainstormRoom: (id: string) =>
    fetchJSON<{ deleted: boolean }>(`${API_BASE}/api/brainstorms/${id}`, {
      method: "DELETE",
    }),

  advanceBrainstormRoom: (id: string) =>
    fetchJSON<BrainstormMessage[]>(`${API_BASE}/api/brainstorms/${id}/advance`, {
      method: "POST",
    }),

  sendBrainstormMessage: (id: string, content: string, target_agent_type?: string) =>
    fetchJSON<BrainstormMessage[]>(`${API_BASE}/api/brainstorms/${id}/message`, {
      method: "POST",
      body: JSON.stringify({ content, target_agent_type }),
    }),

  skipBrainstormRoom: (id: string) =>
    fetchJSON<BrainstormRoom>(`${API_BASE}/api/brainstorms/${id}/skip`, {
      method: "POST",
    }),

  spawnBrainstormRoom: (id: string) =>
    fetchJSON<{ project_id: string; room: BrainstormRoom }>(`${API_BASE}/api/brainstorms/${id}/spawn`, {
      method: "POST",
    }),

  getBrainstormSkills: (id: string) =>
    fetchJSON<BrainstormSkill[]>(`${API_BASE}/api/brainstorms/${id}/skills`),

  updateBrainstormSkill: (roomId: string, skillId: string, status: string) =>
    fetchJSON<BrainstormSkill>(`${API_BASE}/api/brainstorms/${roomId}/skills/${skillId}`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts
git commit -m "feat(3a): frontend brainstorm types and API client methods"
```

---

## Task 8: Global Lobby Page

**Files:**
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: Replace page.tsx with Global Lobby**

This replaces the current project selector with a lobby showing brainstorm rooms and project rooms. The project creation and selection functionality is preserved.

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Project, BrainstormRoom } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  brainstorming: "bg-info/10 text-info",
  refining: "bg-amber-500/10 text-amber-400",
  ready_to_spawn: "bg-healthy/10 text-healthy",
  spawned: "bg-zinc-700/50 text-zinc-500",
};

const STATUS_LABELS: Record<string, string> = {
  brainstorming: "Brainstorming",
  refining: "Refining",
  ready_to_spawn: "Ready to Spawn",
  spawned: "Spawned",
};

export default function GlobalLobby() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [brainstormRooms, setBrainstormRooms] = useState<BrainstormRoom[]>([]);
  const [newIdea, setNewIdea] = useState("");
  const [showNewIdea, setShowNewIdea] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [projs, rooms] = await Promise.all([
        api.getProjects(),
        api.getBrainstormRooms(),
      ]);
      setProjects(projs);
      setBrainstormRooms(rooms);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  async function handleCreateIdea() {
    if (!newIdea.trim()) return;
    try {
      const room = await api.createBrainstormRoom({ idea_text: newIdea.trim() });
      router.push(`/brainstorm/${room.id}`);
    } catch {}
  }

  async function handleCreateProject() {
    const name = prompt("Project name:");
    if (!name) return;
    try {
      const project = await api.createProject({ name, description: "" });
      router.push(`/project/${project.id}`);
    } catch {}
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 border-2 border-info border-t-transparent rounded-full animate-spin" />
          <span className="text-zinc-400">Loading...</span>
        </div>
      </div>
    );
  }

  const activeRooms = brainstormRooms.filter((r) => r.status !== "spawned");
  const spawnedRooms = brainstormRooms.filter((r) => r.status === "spawned");

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-border px-4 sm:px-6 py-6">
        <div className="max-w-[1200px] mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">ORKA</h1>
            <p className="text-sm text-zinc-500 mt-1">AI Command Center</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowNewIdea(!showNewIdea)}
              className="px-4 py-2 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors"
            >
              New Idea
            </button>
            <button
              onClick={handleCreateProject}
              className="px-4 py-2 rounded-lg bg-zinc-800 text-zinc-300 text-sm font-medium hover:bg-zinc-700 transition-colors"
            >
              New Project
            </button>
          </div>
        </div>
      </header>

      {/* New Idea Input */}
      {showNewIdea && (
        <div className="border-b border-border px-4 sm:px-6 py-4">
          <div className="max-w-[1200px] mx-auto">
            <div className="flex gap-3">
              <input
                type="text"
                value={newIdea}
                onChange={(e) => setNewIdea(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateIdea()}
                placeholder="Describe your idea... (agents will brainstorm it)"
                className="flex-1 bg-base-50 border border-border rounded-lg px-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-info/50"
                autoFocus
              />
              <button
                onClick={handleCreateIdea}
                disabled={!newIdea.trim()}
                className="px-6 py-2.5 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Start Brainstorm
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="max-w-[1200px] mx-auto px-4 sm:px-6 py-8 space-y-10">
        {/* Active Brainstorm Rooms */}
        <section>
          <h2 className="text-sm font-medium text-zinc-400 mb-4 uppercase tracking-wider">
            Brainstorm Rooms ({activeRooms.length})
          </h2>
          {activeRooms.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-border rounded-lg">
              <p className="text-zinc-500 text-sm">No active brainstorm rooms</p>
              <p className="text-zinc-600 text-xs mt-1">Click &quot;New Idea&quot; to start one</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {activeRooms.map((room) => (
                <button
                  key={room.id}
                  onClick={() => router.push(`/brainstorm/${room.id}`)}
                  className="text-left bg-base-50 border border-border rounded-lg p-4 hover:border-info/30 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <h3 className="text-sm font-medium truncate flex-1">
                      {room.title}
                    </h3>
                    <span className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_STYLES[room.status]}`}>
                      {STATUS_LABELS[room.status]}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 line-clamp-2 mb-2">
                    {room.idea_text}
                  </p>
                  <div className="flex items-center gap-3 text-[10px] text-zinc-600">
                    <span>Round {room.current_round}/{room.max_rounds}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Project Rooms */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
              Project Rooms ({projects.length})
            </h2>
          </div>
          {projects.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-border rounded-lg">
              <p className="text-zinc-500 text-sm">No projects yet</p>
              <p className="text-zinc-600 text-xs mt-1">Spawn from a brainstorm or create directly</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {projects.map((project) => {
                const spawnedFrom = spawnedRooms.find(
                  (r) => r.project_id === project.id
                );
                return (
                  <button
                    key={project.id}
                    onClick={() => router.push(`/project/${project.id}`)}
                    className="text-left bg-base-50 border border-border rounded-lg p-4 hover:border-healthy/30 transition-colors"
                  >
                    <h3 className="text-sm font-medium truncate">
                      {project.name}
                    </h3>
                    {project.description && (
                      <p className="text-xs text-zinc-500 line-clamp-2 mt-1">
                        {project.description}
                      </p>
                    )}
                    {spawnedFrom && (
                      <span className="inline-block mt-2 px-2 py-0.5 rounded text-[10px] font-medium bg-info/10 text-info">
                        From brainstorm
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/app/page.tsx
git commit -m "feat(3a): Global Lobby page — brainstorm rooms + project rooms"
```

---

## Task 9: Brainstorm Room Components

**Files:**
- Create: `frontend/components/BrainstormChat.tsx`
- Create: `frontend/components/BrainstormSidebar.tsx`

- [ ] **Step 1: Create BrainstormChat.tsx**

```tsx
"use client";

import { useState } from "react";
import type { BrainstormMessage } from "@/lib/types";

type Props = {
  messages: BrainstormMessage[];
  onSendMessage: (content: string, targetAgentType?: string) => void;
  disabled?: boolean;
};

const AGENT_COLORS: Record<string, string> = {
  orchestrator: "text-info border-info/30",
  backend: "text-healthy border-healthy/30",
  frontend: "text-purple-400 border-purple-400/30",
  qa: "text-error border-error/30",
  docs: "text-amber-400 border-amber-400/30",
  memory: "text-cyan-400 border-cyan-400/30",
};

const AGENT_BG: Record<string, string> = {
  orchestrator: "bg-info/5",
  backend: "bg-healthy/5",
  frontend: "bg-purple-400/5",
  qa: "bg-error/5",
  docs: "bg-amber-400/5",
  memory: "bg-cyan-400/5",
};

const TYPE_LABELS: Record<string, string> = {
  analysis: "Analysis",
  question: "Question",
  risk: "Risk",
  suggestion: "Suggestion",
  plan: "Plan",
  challenge: "Challenge",
  response: "Response",
  idea: "Idea",
};

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ago`;
}

export default function BrainstormChat({ messages, onSendMessage, disabled }: Props) {
  const [input, setInput] = useState("");
  const [targetAgent, setTargetAgent] = useState<string>("");

  function handleSubmit() {
    if (!input.trim() || disabled) return;
    onSendMessage(input.trim(), targetAgent || undefined);
    setInput("");
    setTargetAgent("");
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1 pb-4">
        {messages.length === 0 && (
          <div className="text-center py-12 text-zinc-500 text-sm">
            No messages yet. Start the discussion!
          </div>
        )}
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          const isSystem = msg.role === "system";
          const agentType = msg.agent_type || "orchestrator";
          const colorClass = AGENT_COLORS[agentType] || AGENT_COLORS.orchestrator;
          const bgClass = AGENT_BG[agentType] || "";

          return (
            <div
              key={msg.id}
              className={`rounded-lg border p-3 ${
                isUser
                  ? "bg-info/5 border-info/20 ml-8"
                  : isSystem
                  ? "bg-zinc-800/50 border-zinc-700 mx-4"
                  : `${bgClass} ${colorClass.split(" ")[1] || "border-border"}`
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                {isUser ? (
                  <span className="text-xs font-medium text-info">You</span>
                ) : isSystem ? (
                  <span className="text-xs font-medium text-zinc-400">System</span>
                ) : (
                  <span className={`text-xs font-medium ${colorClass.split(" ")[0]}`}>
                    {msg.agent_type === "orchestrator"
                      ? "Orchestrator"
                      : msg.agent_type === "backend"
                      ? "Backend"
                      : msg.agent_type === "frontend"
                      ? "Frontend"
                      : msg.agent_type === "qa"
                      ? "QA"
                      : msg.agent_type === "docs"
                      ? "Docs"
                      : "Memory"}
                  </span>
                )}
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-500">
                  {TYPE_LABELS[msg.message_type] || msg.message_type}
                </span>
                <span className="text-[10px] text-zinc-600 ml-auto">
                  R{msg.round_number} · {relativeTime(msg.created_at)}
                </span>
              </div>
              <p className="text-sm text-zinc-300 leading-relaxed">{msg.content}</p>
            </div>
          );
        })}
      </div>

      {/* Input */}
      <div className="border-t border-border pt-3 mt-auto">
        <div className="flex gap-2">
          <select
            value={targetAgent}
            onChange={(e) => setTargetAgent(e.target.value)}
            className="bg-zinc-800 border border-border rounded-lg px-2 py-2 text-xs text-zinc-400 focus:outline-none"
          >
            <option value="">All agents</option>
            <option value="orchestrator">Orchestrator</option>
            <option value="backend">Backend</option>
            <option value="frontend">Frontend</option>
            <option value="qa">QA</option>
            <option value="docs">Docs</option>
            <option value="memory">Memory</option>
          </select>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder={disabled ? "Room is locked..." : "Type a message or question..."}
            disabled={disabled}
            className="flex-1 bg-base-50 border border-border rounded-lg px-4 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-info/50 disabled:opacity-50"
          />
          <button
            onClick={handleSubmit}
            disabled={disabled || !input.trim()}
            className="px-4 py-2 rounded-lg bg-info text-white text-sm font-medium hover:bg-info/90 transition-colors disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create BrainstormSidebar.tsx**

```tsx
"use client";

import type { BrainstormAgent, BrainstormSkill } from "@/lib/types";

type Props = {
  agents: BrainstormAgent[];
  skills: BrainstormSkill[];
  status: string;
  currentRound: number;
  maxRounds: number;
  onAdvance: () => void;
  onSkip: () => void;
  onSpawn: () => void;
  onSkillUpdate: (skillId: string, status: string) => void;
};

const AGENT_COLORS: Record<string, string> = {
  orchestrator: "bg-info",
  backend: "bg-healthy",
  frontend: "bg-purple-400",
  qa: "bg-error",
  docs: "bg-amber-400",
  memory: "bg-cyan-400",
};

export default function BrainstormSidebar({
  agents,
  skills,
  status,
  currentRound,
  maxRounds,
  onAdvance,
  onSkip,
  onSpawn,
  onSkillUpdate,
}: Props) {
  const isBrainstorming = status === "brainstorming";
  const isReadyToSpawn = status === "ready_to_spawn";
  const isSpawned = status === "spawned";

  return (
    <div className="space-y-5">
      {/* Round Status */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Status
        </h3>
        <div className="bg-base-50 border border-border rounded-lg p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-zinc-300 capitalize">{status.replace("_", " ")}</span>
            <span className="text-xs text-zinc-500">
              Round {currentRound}/{maxRounds}
            </span>
          </div>
          <div className="mt-2 w-full bg-zinc-800 rounded-full h-1.5">
            <div
              className="bg-info rounded-full h-1.5 transition-all"
              style={{ width: `${(currentRound / maxRounds) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Agents */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Agents
        </h3>
        <div className="space-y-1.5">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="flex items-center gap-2 bg-base-50 border border-border rounded px-3 py-2"
            >
              <span className={`w-2 h-2 rounded-full ${AGENT_COLORS[agent.agent_type] || "bg-zinc-500"}`} />
              <span className="text-xs text-zinc-300 flex-1 truncate">
                {agent.agent_name}
              </span>
              <span className="text-[10px] text-zinc-600 capitalize">{agent.status}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Skills */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Suggested Skills
        </h3>
        <div className="space-y-1.5">
          {skills.map((skill) => (
            <div
              key={skill.id}
              className="bg-base-50 border border-border rounded px-3 py-2"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-zinc-300 font-medium">{skill.skill_name}</span>
                <div className="flex gap-1">
                  {skill.status !== "accepted" && (
                    <button
                      onClick={() => onSkillUpdate(skill.id, "accepted")}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-healthy/10 text-healthy hover:bg-healthy/20"
                    >
                      Accept
                    </button>
                  )}
                  {skill.status !== "rejected" && (
                    <button
                      onClick={() => onSkillUpdate(skill.id, "rejected")}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400 hover:bg-zinc-600"
                    >
                      Reject
                    </button>
                  )}
                </div>
              </div>
              <p className="text-[10px] text-zinc-500">{skill.relevance_reason}</p>
            </div>
          ))}
          {skills.length === 0 && (
            <p className="text-xs text-zinc-500">Skills detected from your idea</p>
          )}
        </div>
      </div>

      {/* Actions */}
      <div>
        <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
          Actions
        </h3>
        <div className="space-y-2">
          {isBrainstorming && (
            <>
              <button
                onClick={onAdvance}
                className="w-full px-3 py-2 rounded-lg bg-info/10 text-info text-xs font-medium hover:bg-info/20 transition-colors"
              >
                Advance Round ({currentRound}/{maxRounds})
              </button>
              <button
                onClick={onSkip}
                className="w-full px-3 py-2 rounded-lg bg-zinc-800 text-zinc-400 text-xs font-medium hover:bg-zinc-700 transition-colors"
              >
                Skip to Plan
              </button>
            </>
          )}
          {(isReadyToSpawn || status === "refining") && !isSpawned && (
            <button
              onClick={onSpawn}
              className="w-full px-3 py-2.5 rounded-lg bg-healthy text-white text-sm font-medium hover:bg-healthy/90 transition-colors"
            >
              Finalize & Spawn Project
            </button>
          )}
          {isSpawned && (
            <p className="text-xs text-zinc-500 text-center py-2">
              Project spawned
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/components/BrainstormChat.tsx frontend/components/BrainstormSidebar.tsx
git commit -m "feat(3a): BrainstormChat and BrainstormSidebar components"
```

---

## Task 10: Brainstorm Room Page

**Files:**
- Create: `frontend/app/brainstorm/[id]/page.tsx`

- [ ] **Step 1: Create the brainstorm room page**

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { BrainstormRoomDetail } from "@/lib/types";
import BrainstormChat from "@/components/BrainstormChat";
import BrainstormSidebar from "@/components/BrainstormSidebar";

const STATUS_STYLES: Record<string, string> = {
  brainstorming: "bg-info/10 text-info",
  refining: "bg-amber-500/10 text-amber-400",
  ready_to_spawn: "bg-healthy/10 text-healthy",
  spawned: "bg-zinc-700/50 text-zinc-500",
};

const STATUS_LABELS: Record<string, string> = {
  brainstorming: "Brainstorming",
  refining: "Refining Plan",
  ready_to_spawn: "Ready to Spawn",
  spawned: "Spawned",
};

export default function BrainstormRoomPage() {
  const params = useParams();
  const router = useRouter();
  const roomId = params.id as string;

  const [room, setRoom] = useState<BrainstormRoomDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [spawning, setSpawning] = useState(false);

  const loadRoom = useCallback(async () => {
    try {
      const data = await api.getBrainstormRoom(roomId);
      setRoom(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load room");
    }
  }, [roomId]);

  useEffect(() => {
    loadRoom().then(() => setLoading(false));
  }, [loadRoom]);

  // Auto-refresh every 5s if brainstorming
  useEffect(() => {
    if (room?.status === "brainstorming") {
      const interval = setInterval(loadRoom, 5000);
      return () => clearInterval(interval);
    }
  }, [room?.status, loadRoom]);

  async function handleAdvance() {
    try {
      await api.advanceBrainstormRoom(roomId);
      await loadRoom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to advance");
    }
  }

  async function handleSendMessage(content: string, targetAgentType?: string) {
    try {
      await api.sendBrainstormMessage(roomId, content, targetAgentType);
      await loadRoom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
    }
  }

  async function handleSkip() {
    try {
      await api.skipBrainstormRoom(roomId);
      await loadRoom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to skip");
    }
  }

  async function handleSpawn() {
    setSpawning(true);
    try {
      const result = await api.spawnBrainstormRoom(roomId);
      router.push(`/project/${result.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to spawn");
      setSpawning(false);
    }
  }

  async function handleSkillUpdate(skillId: string, status: string) {
    try {
      await api.updateBrainstormSkill(roomId, skillId, status);
      await loadRoom();
    } catch {}
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 border-2 border-info border-t-transparent rounded-full animate-spin" />
          <span className="text-zinc-400">Loading room...</span>
        </div>
      </div>
    );
  }

  if (error && !room) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-zinc-400 text-sm">{error}</p>
        <button
          onClick={() => router.push("/")}
          className="text-sm text-info hover:text-info/80"
        >
          Back to Lobby
        </button>
      </div>
    );
  }

  if (!room) return null;

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-4 sm:px-6 py-4">
        <div className="max-w-[1400px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/")}
              className="text-zinc-500 hover:text-zinc-300 transition-colors text-sm flex items-center gap-1"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m15 18-6-6 6-6" />
              </svg>
              Lobby
            </button>
            <div className="w-px h-5 bg-border" />
            <h1 className="text-lg font-semibold truncate">{room.title}</h1>
            <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_STYLES[room.status]}`}>
              {STATUS_LABELS[room.status]}
            </span>
          </div>
          {error && <span className="text-xs text-error hidden sm:inline">{error}</span>}
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 px-4 sm:px-6 py-6 overflow-hidden">
        <div className="max-w-[1400px] mx-auto grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6 h-full">
          {/* Chat Panel */}
          <div className="min-h-[500px]">
            <BrainstormChat
              messages={room.messages}
              onSendMessage={handleSendMessage}
              disabled={room.status !== "brainstorming" || spawning}
            />
          </div>

          {/* Sidebar */}
          <div>
            <BrainstormSidebar
              agents={room.agents}
              skills={room.skills}
              status={room.status}
              currentRound={room.current_round}
              maxRounds={room.max_rounds}
              onAdvance={handleAdvance}
              onSkip={handleSkip}
              onSpawn={handleSpawn}
              onSkillUpdate={handleSkillUpdate}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/app/brainstorm/\[id\]/page.tsx
git commit -m "feat(3a): Brainstorm Room page with chat, sidebar, and spawn flow"
```

---

## Task 11: Integration Testing

**Files:** None new — manual testing

- [ ] **Step 1: Start backend**

Run: `cd backend && source venv/bin/activate && rm -f orka.db && uvicorn app.main:app --port 8000 &`

Wait 3 seconds.

- [ ] **Step 2: Test brainstorm lifecycle**

```bash
# 1. Create room
curl -s http://localhost:8000/api/brainstorms -X POST \
  -H "Content-Type: application/json" \
  -d '{"idea_text":"Build a web dashboard for analytics with real-time data"}' | python3 -m json.tool

# Save the room_id from response

# 2. Get room detail
curl -s http://localhost:8000/api/brainstorms/{room_id} | python3 -m json.tool

# 3. Advance round 1
curl -s http://localhost:8000/api/brainstorms/{room_id}/advance -X POST | python3 -m json.tool

# 4. Send user message
curl -s http://localhost:8000/api/brainstorms/{room_id}/message -X POST \
  -H "Content-Type: application/json" \
  -d '{"content":"We should use Next.js for the frontend"}' | python3 -m json.tool

# 5. Advance round 2
curl -s http://localhost:8000/api/brainstorms/{room_id}/advance -X POST | python3 -m json.tool

# 6. Skip to plan
curl -s http://localhost:8000/api/brainstorms/{room_id}/skip -X POST | python3 -m json.tool

# 7. Check skills
curl -s http://localhost:8000/api/brainstorms/{room_id}/skills | python3 -m json.tool

# 8. Spawn
curl -s http://localhost:8000/api/brainstorms/{room_id}/spawn -X POST | python3 -m json.tool

# 9. Verify project was created with tasks and memory
curl -s http://localhost:8000/api/tasks?project_id={project_id} | python3 -m json.tool
curl -s http://localhost:8000/api/memory/{project_id} | python3 -m json.tool
```

Expected: Full lifecycle completes. Project created with tasks, dependencies, and brainstorm context in memory.

- [ ] **Step 3: Test existing Phase 1/2 functionality still works**

```bash
# Create project directly (old way still works)
curl -s http://localhost:8000/api/projects -X POST \
  -H "Content-Type: application/json" \
  -d '{"name":"Direct Project","description":"Test existing flow"}' | python3 -m json.tool

# Create task, distribute, verify coordination still works
# (use project_id from above)
```

Expected: All existing endpoints return same responses as before.

- [ ] **Step 4: Start frontend and verify UI**

Run: `cd frontend && npm run dev`

Verify:
- `/` shows Global Lobby with brainstorm room cards
- Clicking a room goes to `/brainstorm/{id}` with chat + sidebar
- Advance/Skip/Spawn buttons work
- `/project/{id}` still works unchanged

- [ ] **Step 5: Stop servers, final commit**

```bash
kill $(lsof -ti:8000) 2>/dev/null
git add -A
git commit -m "feat: ORKA Phase 3A — multi-room brainstorm system complete"
```

---

## Self-Review Checklist

### Spec Coverage

| Spec Requirement | Task |
|-----------------|------|
| BrainstormRoom model | Task 1 |
| BrainstormMessage model | Task 1 |
| BrainstormAgent model | Task 1 |
| BrainstormSkill model | Task 1 |
| SpawnPlan strict schema | Task 1 (schemas) + Task 4 |
| BrainstormAgentBase ABC | Task 2 |
| SimulatedBrainstormAgent with variation | Task 2 |
| Deterministic SkillDetector | Task 3 |
| SpawnPlanGenerator | Task 4 |
| BrainstormContextBridge | Task 4 |
| Brainstorm API routes (all 8) | Task 5 |
| Auto-advance background task (60s fallback) | Task 6 |
| Hard round limit (max 4) | Task 5 (advance endpoint enforces) |
| Brainstorm → execution context transfer | Task 5 (spawn endpoint) |
| Frontend types + API client | Task 7 |
| Global Lobby page | Task 8 |
| Brainstorm Room page | Task 10 |
| BrainstormChat component | Task 9 |
| BrainstormSidebar component | Task 9 |
| No changes to existing project page | Confirmed — no files touched |

### Placeholder Scan

No TBD, TODO, or placeholder patterns found. All steps contain complete code.

### Type Consistency

- `SpawnPlanTask`, `SpawnPlanRisk`, `SpawnPlanSkillItem` defined in schemas.py and used consistently in spawn_plan_generator.py and brainstorms.py
- Frontend `BrainstormMessage`, `BrainstormAgent`, `BrainstormSkill`, `BrainstormRoomDetail` match backend response shapes
- API method return types match frontend interface definitions
