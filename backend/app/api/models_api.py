from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config.model_config import load_config
from app.providers.registry import ProviderRegistry
from app.schemas import ModelInfoResponse, ProviderStatusResponse
from app.services.quota_manager import QuotaManager

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models", response_model=list[ModelInfoResponse])
async def list_models():
    config = load_config()
    registry = ProviderRegistry(config)
    return registry.all_models()


@router.get("/models/available", response_model=list[ModelInfoResponse])
async def list_available_models(db: AsyncSession = Depends(get_db)):
    config = load_config()
    registry = ProviderRegistry(config)
    quota = QuotaManager(config)
    available = []
    for model in registry.all_models():
        state = await quota.get_state(model.provider, db)
        if state is None or state.status != "exhausted":
            available.append(model)
    return available


@router.get("/providers", response_model=list[ProviderStatusResponse])
async def list_providers(db: AsyncSession = Depends(get_db)):
    config = load_config()
    registry = ProviderRegistry(config)
    quota = QuotaManager(config)
    result = []
    for name, provider in registry.all().items():
        healthy = await provider.health_check()
        state = await quota.ensure_state(name, db)
        result.append(ProviderStatusResponse(
            name=name,
            healthy=healthy,
            quota_status=state.status,
            remaining_quota=state.remaining_quota,
            total_quota=state.total_quota,
            reset_at=state.reset_at,
            allow_paid_overage=state.allow_paid_overage,
            models=[ModelInfoResponse(**m.__dict__) for m in provider.get_models()],
        ))
    return result
