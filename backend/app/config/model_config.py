import os
from dataclasses import dataclass, field


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    quota_type: str = "manual"  # time_window | token_limit | request_limit | manual
    window_duration: int | None = None
    weekly_limit: float | None = None
    allow_paid_overage: bool = False


@dataclass
class QuotaConfig:
    threshold_percent: float = 0.2  # throttle when remaining < 20%


@dataclass
class BudgetDefaults:
    daily_soft_limit: float = 5.0
    daily_hard_limit: float = 10.0
    monthly_hard_limit: float = 100.0
    per_task_max_cost: float = 1.0


@dataclass
class ModelRoutingConfig:
    llm_enabled: bool = False
    default_ai_mode: str = "quota_only"
    allow_paid_overage: bool = False
    fallback_policy: str = "free_or_approved_only"
    low_tier_model: str = "gemini-2.5-flash"
    medium_tier_model: str = "claude-sonnet-4-6"
    high_tier_model: str = "claude-opus-4-7"
    providers: list[ProviderConfig] = field(default_factory=list)
    budget: BudgetDefaults = field(default_factory=BudgetDefaults)
    quota: QuotaConfig = field(default_factory=QuotaConfig)


def load_config() -> ModelRoutingConfig:
    providers: list[ProviderConfig] = []

    # OpenAI-compatible providers
    for prefix, name in [
        ("OPENAI", "openai"),
        ("ZAI", "zai"),
        ("GEMINI", "gemini"),
    ]:
        key = os.getenv(f"{prefix}_API_KEY", "")
        url = os.getenv(f"{prefix}_BASE_URL", "")
        if key:
            providers.append(ProviderConfig(
                name=name,
                base_url=url or f"https://api.{name.lower()}.com/v1",
                api_key=key,
                quota_type=os.getenv(f"{prefix}_QUOTA_TYPE", "manual"),
                window_duration=_int_env(f"{prefix}_WINDOW_DURATION"),
                weekly_limit=_float_env(f"{prefix}_WEEKLY_LIMIT"),
                allow_paid_overage=os.getenv(f"{prefix}_ALLOW_PAID_OVERAGE", "false").lower() == "true",
            ))

    # OpenRouter
    or_key = os.getenv("OPENROUTER_API_KEY", "")
    if or_key:
        providers.append(ProviderConfig(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=or_key,
            quota_type=os.getenv("OPENROUTER_QUOTA_TYPE", "token_limit"),
            weekly_limit=_float_env("OPENROUTER_WEEKLY_LIMIT") or 1_000_000,
            allow_paid_overage=os.getenv("OPENROUTER_ALLOW_PAID_OVERAGE", "false").lower() == "true",
        ))

    return ModelRoutingConfig(
        llm_enabled=os.getenv("ORKA_LLM_ENABLED", "false").lower() == "true",
        default_ai_mode=os.getenv("DEFAULT_AI_MODE", "quota_only"),
        allow_paid_overage=os.getenv("ALLOW_PAID_OVERAGE", "false").lower() == "true",
        fallback_policy=os.getenv("PROVIDER_FALLBACK_POLICY", "free_or_approved_only"),
        low_tier_model=os.getenv("ORKA_LOW_TIER_MODEL", "gemini-2.5-flash"),
        medium_tier_model=os.getenv("ORKA_MEDIUM_TIER_MODEL", "claude-sonnet-4-6"),
        high_tier_model=os.getenv("ORKA_HIGH_TIER_MODEL", "claude-opus-4-7"),
        providers=providers,
        budget=BudgetDefaults(
            daily_soft_limit=_float_env("ORKA_DAILY_SOFT_LIMIT") or 5.0,
            daily_hard_limit=_float_env("ORKA_DAILY_HARD_LIMIT") or 10.0,
            monthly_hard_limit=_float_env("ORKA_MONTHLY_HARD_LIMIT") or 100.0,
            per_task_max_cost=_float_env("ORKA_PER_TASK_MAX_COST") or 1.0,
        ),
    )


def _float_env(key: str) -> float | None:
    v = os.getenv(key)
    return float(v) if v else None


def _int_env(key: str) -> int | None:
    v = os.getenv(key)
    return int(v) if v else None
