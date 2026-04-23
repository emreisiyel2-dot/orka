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
        "realtime": "realtime layer",
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

        contribution_types = self._get_contribution_types(
            agent_type, round_number, len(conversation)
        )
        msg_type = contribution_types[0]

        templates = agent_templates.get(msg_type, agent_templates["analysis"])

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
