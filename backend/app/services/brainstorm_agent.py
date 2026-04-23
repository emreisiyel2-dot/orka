"""Brainstorm agent interface — conversation-aware, mode-aware, LLM-ready."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class BrainstormResponse:
    content: str
    message_type: str


class BrainstormAgentBase(ABC):
    @abstractmethod
    def generate_response(
        self,
        agent_type: str,
        idea_text: str,
        conversation: list[dict],
        round_number: int,
        mode: str = "normal",
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

AGENT_ROLES = {
    "orchestrator": "Coordinates the team, defines scope and priorities",
    "backend": "Designs APIs, databases, and server architecture",
    "frontend": "Builds UI components, user flows, and interactions",
    "qa": "Identifies risks, edge cases, and testing strategies",
    "docs": "Plans documentation, guides, and knowledge transfer",
    "memory": "Tracks progress, summarizes discussions, identifies gaps",
}

AGENT_ORDER = ["orchestrator", "backend", "frontend", "qa", "docs", "memory"]

# Per-agent, per-contribution-type templates with {areas}, {count}, {issues}, {prev} placeholders
TEMPLATES: dict[str, dict[str, list[str]]] = {
    "orchestrator": {
        "analysis": [
            "Breaking this down: {areas}. The critical path goes through the foundation first.",
            "I see {count} workstreams here: {areas}. Let me sequence these by dependency.",
            "At a high level, we need to address {areas}. The highest-risk item should go first.",
            "This has {count} distinct concerns — {areas}. I'll map which ones block others.",
        ],
        "question": [
            "What's the primary user pain point? That determines our architecture.",
            "Who's the end user? Their technical sophistication shapes every decision.",
            "What scale are we targeting? 10 users vs 10K changes everything.",
            "Is this a greenfield build or does it integrate with existing systems?",
        ],
        "suggestion": [
            "I recommend we define the MVP boundary first — {areas} are must-haves, everything else is phase 2.",
            "Let's pick the riskiest assumption and validate it before building anything else.",
            "We should timebox the initial build. 2 weeks for core, then reassess scope.",
        ],
        "tradeoff": [
            "Trade-off: building fast with a simple stack vs. investing in scalable architecture upfront. For an MVP, I'd lean simple.",
            "We could go monolith first and extract later, or start with microservices. Monolith is faster to iterate on.",
        ],
        "convergence": [
            "The team is converging on {areas}. I see consensus forming on architecture. Let me lock this in.",
            "Based on the discussion, the path forward is clear: {areas}. I'll formalize the plan.",
        ],
    },
    "backend": {
        "analysis": [
            "The data layer needs to handle {areas}. I'd model this as 3-4 core entities with relationships.",
            "For {areas}, a REST API with versioned endpoints gives us room to evolve without breaking clients.",
            "The persistence challenge is {areas}. We need ACID guarantees for the core entities at minimum.",
            "Looking at {areas}, we'll want a service layer that encapsulates business logic away from the routes.",
        ],
        "question": [
            "What's the read vs. write ratio? Write-heavy needs different indexing than read-heavy.",
            "Do we need real-time updates, or is polling acceptable? This changes the whole backend design.",
            "Are there regulatory requirements for data storage? GDPR/CCPA affect schema design.",
            "Should the API be public-facing or internal only? That determines auth complexity.",
        ],
        "suggestion": [
            "Start with the data model. A clean entity-relationship diagram prevents costly migrations.",
            "I'd implement a repository pattern — routes call services, services call repos. Easy to test and swap.",
            "Define the API contract in OpenAPI before writing code. Frontend can work in parallel.",
        ],
        "risk": [
            "Schema migrations in production are the #1 risk. We need a migration strategy from day one.",
            "Without connection pooling, concurrent users will exhaust the database. Plan for it.",
            "Third-party API dependencies are a reliability risk. Every external call needs circuit breakers.",
        ],
        "tradeoff": [
            "Trade-off: SQL (relational, structured) vs NoSQL (flexible, fast iteration). Given the data model, I'd go SQL.",
            "We could use an ORM for speed or raw queries for control. ORM is better for a small team.",
            "Caching: Redis gives us speed but adds infrastructure. Start without it, add when profiling shows the bottleneck.",
        ],
        "deep_dive": [
            "Deep dive on the data model: the core entities are likely User, Content, and Relationship. Each has 5-10 fields. Let me think through the indexes...",
            "Drilling into the API: we need CRUD for each entity plus 2-3 aggregate endpoints. That's roughly 15 endpoints total.",
        ],
        "alternative": [
            "Alternative architecture: instead of a monolith, we could use event-driven microservices with a message queue. Higher complexity but better for scaling later.",
            "Another approach: serverless functions + managed database. Lower ops burden but harder to debug locally.",
        ],
    },
    "frontend": {
        "analysis": [
            "The user flows map to {areas}. Each flow needs its own route and state management slice.",
            "From a UI perspective, {areas} are the primary views. Navigation between them should be seamless.",
            "The component tree starts with a shell layout, then {areas} as page-level components with shared primitives.",
        ],
        "question": [
            "Mobile-first or desktop-first? This determines our breakpoint strategy and component sizing.",
            "Should we use a design system (MUI, shadcn) or build custom? Design systems speed things up.",
            "What's the animation/transition expectation? Heavy animations affect performance budget.",
        ],
        "suggestion": [
            "Build a component library first: Button, Input, Card, Modal. Reusing these saves 40% of frontend time.",
            "I'd set up the routing and layout shell before any page work. It gives us the skeleton to hang features on.",
            "Use a state management pattern early. Zustand or Context — don't leave it to prop drilling.",
        ],
        "risk": [
            "Responsive design is often an afterthought. If we don't test mobile from week 1, it'll be a painful rewrite.",
            "Bundle size creeps up fast. We need tree-shaking and code splitting from the start.",
            "State management sprawl: without clear patterns, every developer invents their own.",
        ],
        "tradeoff": [
            "Trade-off: SPA vs SSR. SPA is simpler to build; SSR is better for SEO and initial load. For a dashboard, SPA is fine.",
            "CSS: Tailwind gives speed but creates long class strings. CSS Modules are cleaner but slower to iterate.",
        ],
        "deep_dive": [
            "Deep dive on the main dashboard view: it needs a grid layout with 4-6 widget slots, each showing a different data slice. The tricky part is responsive rearrangement.",
        ],
        "alternative": [
            "Alternative: instead of a traditional dashboard, we could use a canvas-based layout where users drag and resize widgets. More complex but much more flexible.",
        ],
    },
    "qa": {
        "analysis": [
            "Quality risk assessment: {areas} are the critical paths. A bug in any of these is a showstopper.",
            "From a testing perspective, {areas} need integration tests at minimum. Unit tests for business logic.",
            "The test pyramid for this: 60% unit, 30% integration, 10% E2E. Focus integration on {areas}.",
        ],
        "question": [
            "What's our bug tolerance for launch? Zero-defect means 3x the timeline.",
            "Are there compliance or accessibility requirements? WCAG 2.1 AA adds significant test coverage.",
            "What's the expected peak concurrent load? This determines our performance test baseline.",
        ],
        "risk": [
            "Data validation gaps between frontend and backend cause silent data corruption — the worst kind of bug.",
            "Auth edge cases (expired tokens, concurrent sessions, role escalation) are frequently undertested.",
            "Third-party dependencies can break without warning. Every external integration needs a fallback plan.",
            "Race conditions in concurrent state updates are hard to reproduce and harder to fix. Test for them.",
        ],
        "suggestion": [
            "I'd set up CI with automated tests from day one. Tests that don't run automatically don't get maintained.",
            "Write acceptance criteria before implementation. If you can't define 'done', you can't test it.",
        ],
        "tradeoff": [
            "Trade-off: comprehensive test coverage vs. shipping speed. I'd recommend 80% coverage on critical paths, 50% elsewhere.",
            "Manual exploratory testing finds bugs automation misses. Budget for both.",
        ],
        "deep_dive": [
            "Deep dive on auth testing: we need tests for valid login, expired token, invalid credentials, session timeout, concurrent logins, password reset flow, and role-based access. That's at least 15 test cases.",
        ],
        "alternative": [
            "Alternative testing approach: instead of writing tests after code, we could use contract testing. Define the API contract and both sides test against it independently.",
        ],
    },
    "docs": {
        "analysis": [
            "Documentation needs: {areas}. API reference is non-negotiable; user guides depend on the audience.",
            "From a docs perspective, we need {areas}. The highest-value doc is always the getting-started guide.",
        ],
        "question": [
            "Who's the primary audience — developers, end users, or both? Tone and depth change completely.",
            "Is there existing documentation tooling (Notion, GitBook, ReadMe) we should integrate with?",
        ],
        "suggestion": [
            "Auto-generate API docs from code. They stay current; manually written API docs rot immediately.",
            "A 5-minute getting-started guide is worth more than 50 pages of reference docs.",
        ],
        "tradeoff": [
            "Trade-off: comprehensive docs vs. working software. For an MVP, API reference + getting-started is enough.",
        ],
    },
    "memory": {
        "analysis": [
            "Progress check: {count} topics covered so far across {areas}. {issues} distinct points raised by the team.",
            "Summary of discussion: the team has explored {areas}. Key open items remain around scope and architecture.",
            "Tracking: {count} areas addressed, {issues} contributions from the team. I'm noting the unresolved items.",
        ],
        "question": [
            "Are there disagreements I should track? Unresolved conflicts now become blockers during execution.",
            "Is the scope clear enough to estimate? If not, we need more discussion before finalizing.",
        ],
        "suggestion": [
            "The team has covered the key areas. I recommend we converge on scope and move toward a plan.",
            "Based on {issues} data points, we have enough to generate a solid project plan. I'd suggest moving to synthesis.",
            "I'm seeing good alignment on {areas}. The remaining unknowns are minor enough to resolve during execution.",
        ],
        "convergence": [
            "Convergence report: {count} decisions made, {issues} open questions, team is aligned on {areas}. Ready to formalize.",
        ],
        "synthesis": [
            "Synthesis: After {issues} contributions, the team agrees on the core architecture ({areas}). I'll prepare the summary.",
        ],
    },
}


def _extract_areas(idea_text: str) -> str:
    words = idea_text.lower().split()
    areas = []
    keywords_map = {
        "api": "API design", "database": "data layer", "ui": "user interface",
        "frontend": "frontend architecture", "backend": "backend services",
        "auth": "authentication", "payment": "payment flow", "dashboard": "dashboard views",
        "mobile": "mobile experience", "web": "web platform", "app": "application core",
        "user": "user management", "data": "data handling", "real-time": "realtime layer",
        "realtime": "realtime layer", "notification": "notification system",
        "search": "search functionality", "chat": "chat system", "ai": "AI integration",
        "ml": "ML pipeline", "analytics": "analytics", "report": "reporting",
    }
    for kw, area in keywords_map.items():
        if kw in words and area not in areas:
            areas.append(area)
    if not areas:
        areas = ["core functionality", "data layer", "user interface"]
    return ", ".join(areas[:4])


def _get_prev_mentions(conversation: list[dict], keyword: str) -> list[str]:
    """Extract previous statements mentioning a keyword."""
    return [
        m["content"][:80] for m in conversation[-6:]
        if keyword.lower() in m.get("content", "").lower()
    ]


def _used_types_for_agent(conversation: list[dict], agent_type: str) -> set[str]:
    """Track which message types this agent has already used to avoid repetition."""
    used = set()
    for m in conversation:
        if m.get("agent_type") == agent_type and m.get("message_type"):
            used.add(m["message_type"])
    return used


class SimulatedBrainstormAgent(BrainstormAgentBase):
    """Conversation-aware, mode-aware brainstorm agent."""

    def generate_response(
        self,
        agent_type: str,
        idea_text: str,
        conversation: list[dict],
        round_number: int,
        mode: str = "normal",
    ) -> BrainstormResponse:
        areas = _extract_areas(idea_text)
        used_types = _used_types_for_agent(conversation, agent_type)
        agent_templates = TEMPLATES.get(agent_type, TEMPLATES["orchestrator"])

        msg_type, template = self._select_contribution(
            agent_type, agent_templates, round_number, mode, used_types, len(conversation)
        )

        # Find previous relevant contribution to reference
        prev_summary = ""
        if len(conversation) > 2:
            recent = conversation[-3:]
            for m in reversed(recent):
                if m.get("agent_type") and m["agent_type"] != agent_type:
                    prev_summary = m.get("content", "")[:60]
                    break

        content = template.format(
            count=min(len(areas.split(",")), 5),
            areas=areas,
            issues=len(conversation),
            prev=prev_summary,
        )

        # If there's a previous point to build on, append a brief reference
        if prev_summary and round_number > 0 and agent_type != "memory":
            bridge = self._bridge_to_prev(agent_type, prev_summary)
            if bridge:
                content = bridge + " " + content

        return BrainstormResponse(content=content, message_type=msg_type)

    def _select_contribution(
        self,
        agent_type: str,
        templates: dict[str, list[str]],
        round_number: int,
        mode: str,
        used_types: set[str],
        conv_len: int,
    ) -> tuple[str, str]:
        """Select message type and template based on mode, round, and what's been used."""
        # Determine available types based on mode
        if mode == "deep_dive":
            preferred = ["deep_dive", "analysis", "tradeoff", "suggestion"]
        elif mode == "exploration":
            preferred = ["alternative", "analysis", "suggestion", "tradeoff"]
        elif mode == "decision":
            preferred = ["convergence", "synthesis", "suggestion", "tradeoff"]
        else:
            # Normal mode: round-dependent
            if round_number == 0:
                preferred = ["analysis", "question"]
            elif round_number == 1:
                preferred = ["question", "suggestion", "tradeoff"]
            else:
                preferred = ["suggestion", "risk", "tradeoff", "convergence"]

        # Agent-specific overrides
        if agent_type == "qa" and mode == "normal":
            preferred = ["risk"] + preferred
        if agent_type == "memory":
            if conv_len > 12:
                preferred = ["synthesis", "convergence"]
            elif conv_len > 6:
                preferred = ["suggestion", "convergence"]
            else:
                preferred = ["analysis", "question"]

        # Pick first preferred type that has templates and hasn't been overused
        msg_type = preferred[0]
        for pt in preferred:
            if pt in templates and templates[pt]:
                # Allow re-use of a type if we're past round 2 (we need to keep contributing)
                if pt not in used_types or round_number > 2:
                    msg_type = pt
                    break
        else:
            # Fallback: pick any available type
            for pt in preferred:
                if pt in templates and templates[pt]:
                    msg_type = pt
                    break

        template_list = templates.get(msg_type, templates.get("analysis", []))
        if not template_list:
            template_list = list(templates.values())[0] if templates else ["I see this involves {areas}."]

        idx = (round_number * 7 + hash(agent_type) + conv_len) % len(template_list)
        return msg_type, template_list[idx]

    def _bridge_to_prev(self, agent_type: str, prev: str) -> str:
        """Generate a brief bridge referencing the previous agent's point."""
        bridges = {
            "orchestrator": [
                f"Building on the backend point about \"{prev[:40]}...\" —",
                f"The frontend perspective aligns with that —",
            ],
            "backend": [
                f"From an API perspective, that aligns with —",
            ],
            "frontend": [
                f"On the UI side, this connects to —",
            ],
            "qa": [
                f"That introduces a potential risk —",
            ],
            "docs": [
                f"We should document that —",
            ],
        }
        options = bridges.get(agent_type, [])
        if not options:
            return ""
        return options[hash(prev) % len(options)]
