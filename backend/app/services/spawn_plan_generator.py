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

        areas = self._extract_areas_from_messages(messages)
        tasks = self._generate_tasks(idea_text, areas)
        risks = self._extract_risks(messages)

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
