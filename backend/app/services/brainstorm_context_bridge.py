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
