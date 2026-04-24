from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models import Agent, Base, Worker, WorkerSession, WorkerLog, AutonomousDecision, AgentMessage, TaskDependency, BrainstormRoom, BrainstormMessage, BrainstormAgent, BrainstormSkill, UsageRecord, RoutingDecision, BudgetConfigDB, ProviderQuotaState

DATABASE_URL = "sqlite+aiosqlite:///./orka.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_db() -> None:
    async with async_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(Agent))
        existing_agents = result.scalars().first()

        if existing_agents is not None:
            return

        agents = [
            Agent(name="Orchestrator", type="orchestrator", status="idle"),
            Agent(name="Backend Agent", type="backend", status="idle"),
            Agent(name="Frontend Agent", type="frontend", status="idle"),
            Agent(name="QA Agent", type="qa", status="idle"),
            Agent(name="Docs Agent", type="docs", status="idle"),
            Agent(name="Memory Agent", type="memory", status="idle"),
        ]

        session.add_all(agents)
        await session.commit()

        # Seed default budget config
        result = await session.execute(select(BudgetConfigDB))
        if not result.scalars().first():
            session.add(BudgetConfigDB())

        await session.commit()
