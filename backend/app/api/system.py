from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Run, RunEvent, WorkerSession
from app.services.cli_quota_tracker import CLIQuotaTracker

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system/stats")
async def system_stats(db: AsyncSession = Depends(get_db)):
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    total = await db.execute(
        select(func.count()).select_from(Run).where(Run.created_at >= today_start)
    )
    failed = await db.execute(
        select(func.count()).select_from(Run).where(
            Run.created_at >= today_start, Run.status == "failed"
        )
    )
    avg_dur = await db.execute(
        select(func.avg(Run.duration_seconds)).where(
            Run.created_at >= today_start, Run.duration_seconds.isnot(None)
        )
    )
    active_cli = await db.execute(
        select(func.count()).select_from(WorkerSession).where(
            WorkerSession.status == "running"
        )
    )
    event_count = await db.execute(
        select(func.count()).select_from(RunEvent)
    )

    total_runs = total.scalar() or 0
    failed_runs = failed.scalar() or 0

    tracker = CLIQuotaTracker()
    cli_providers = {}
    for provider_name in ("claude_code", "glm_coding"):
        status = tracker.get_provider_status(provider_name)
        if status:
            cli_providers[provider_name] = status

    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_runs_today": total_runs,
        "failed_runs_today": failed_runs,
        "failure_rate_today": round(failed_runs / total_runs, 3) if total_runs else 0.0,
        "avg_duration_seconds_today": round(avg_dur.scalar() or 0.0, 2),
        "active_cli_sessions": active_cli.scalar() or 0,
        "total_event_count": event_count.scalar() or 0,
        "providers": {"cli": cli_providers},
    }