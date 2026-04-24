from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageRecord
from app.providers.base import ProviderResponse


class UsageTracker:
    async def record(
        self,
        response: ProviderResponse,
        task_id: str | None,
        agent_type: str | None,
        routing_decision_id: str | None,
        db: AsyncSession,
    ) -> UsageRecord:
        record = UsageRecord(
            task_id=task_id,
            agent_type=agent_type,
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            routing_decision_id=routing_decision_id,
        )
        db.add(record)
        await db.flush()
        return record
