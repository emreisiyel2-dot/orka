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
