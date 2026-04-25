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
    model_low: str | None = None
    model_high: str | None = None


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
class CLIProviderConfig:
    name: str               # "claude_code" | "glm_coding"
    binary: str             # "claude" | "glm" or full path
    default_args: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    max_concurrent: int = 3
    max_sessions_per_hour: int = 20
    timeout_seconds: int = 300
    enabled: bool = True


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
    cli_enabled: bool = False
    cli_default: str = "claude_code"
    cli_providers: list[CLIProviderConfig] = field(default_factory=list)


def load_config() -> ModelRoutingConfig:
    providers: list[ProviderConfig] = []

    # OpenAI-compatible providers
    for prefix, name, default_url in [
        ("OPENAI", "openai", "https://api.openai.com/v1"),
        ("ZAI", "zai", ""),
        ("GEMINI", "gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ]:
        key = os.getenv(f"{prefix}_API_KEY", "")
        url = os.getenv(f"{prefix}_BASE_URL", "") or default_url
        if key and url:
            providers.append(ProviderConfig(
                name=name,
                base_url=url,
                api_key=key,
                quota_type=os.getenv(f"{prefix}_QUOTA_TYPE", "manual"),
                window_duration=_int_env(f"{prefix}_WINDOW_DURATION"),
                weekly_limit=_float_env(f"{prefix}_WEEKLY_LIMIT"),
                allow_paid_overage=os.getenv(f"{prefix}_ALLOW_PAID_OVERAGE", "false").lower() == "true",
                model_low=os.getenv(f"{prefix}_MODEL_LOW"),
                model_high=os.getenv(f"{prefix}_MODEL_HIGH"),
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

    # Derive tier models: prefer providers with custom model_low/model_high
    low_model = os.getenv("ORKA_LOW_TIER_MODEL", "")
    medium_model = os.getenv("ORKA_MEDIUM_TIER_MODEL", "")
    high_model = os.getenv("ORKA_HIGH_TIER_MODEL", "")

    if not low_model:
        # Find the provider with custom models configured
        custom_pc = next((p for p in providers if p.model_low), None)
        if custom_pc:
            low_model = custom_pc.model_low
            high_model = high_model or custom_pc.model_high or low_model
            medium_model = medium_model or high_model
        elif providers:
            # Fallback: use first provider's static catalog defaults
            low_model = "gpt-4o-mini"
            if not high_model:
                high_model = "gpt-4o"
            if not medium_model:
                medium_model = "gpt-4o"

    if not low_model:
        low_model = "gemini-2.5-flash"
    if not medium_model:
        medium_model = "claude-sonnet-4-6"
    if not high_model:
        high_model = "claude-opus-4-7"

    cli_providers = _load_cli_providers()
    cli_enabled = os.getenv("ORKA_CLI_ENABLED", "false").lower() == "true"
    cli_default = os.getenv("ORKA_CLI_DEFAULT", "claude_code")

    return ModelRoutingConfig(
        llm_enabled=os.getenv("ORKA_LLM_ENABLED", "false").lower() == "true",
        default_ai_mode=os.getenv("DEFAULT_AI_MODE", "quota_only"),
        allow_paid_overage=os.getenv("ALLOW_PAID_OVERAGE", "false").lower() == "true",
        fallback_policy=os.getenv("PROVIDER_FALLBACK_POLICY", "free_or_approved_only"),
        low_tier_model=low_model,
        medium_tier_model=medium_model,
        high_tier_model=high_model,
        providers=providers,
        budget=BudgetDefaults(
            daily_soft_limit=_float_env("ORKA_DAILY_SOFT_LIMIT") or 5.0,
            daily_hard_limit=_float_env("ORKA_DAILY_HARD_LIMIT") or 10.0,
            monthly_hard_limit=_float_env("ORKA_MONTHLY_HARD_LIMIT") or 100.0,
            per_task_max_cost=_float_env("ORKA_PER_TASK_MAX_COST") or 1.0,
        ),
        cli_enabled=cli_enabled,
        cli_default=cli_default,
        cli_providers=cli_providers,
    )


def _float_env(key: str) -> float | None:
    v = os.getenv(key)
    return float(v) if v else None


def _int_env(key: str) -> int | None:
    v = os.getenv(key)
    return int(v) if v else None


def _load_cli_providers() -> list[CLIProviderConfig]:
    providers: list[CLIProviderConfig] = []

    claude_binary = os.getenv("CLAUDE_CODE_BINARY", "claude")
    claude_models_str = os.getenv("CLAUDE_CODE_MODELS", "")
    providers.append(CLIProviderConfig(
        name="claude_code",
        binary=claude_binary,
        default_args=os.getenv("CLAUDE_CODE_ARGS", "").split() if os.getenv("CLAUDE_CODE_ARGS") else [],
        models=[m.strip() for m in claude_models_str.split(",") if m.strip()],
        max_concurrent=int(os.getenv("CLAUDE_CODE_MAX_CONCURRENT", "3")),
        max_sessions_per_hour=int(os.getenv("CLAUDE_CODE_MAX_SESSIONS_HOUR", "20")),
        timeout_seconds=int(os.getenv("CLAUDE_CODE_TIMEOUT", os.getenv("ORKA_CLI_TIMEOUT", "300"))),
        enabled=os.getenv("CLAUDE_CODE_ENABLED", "true").lower() == "true",
    ))

    glm_binary = os.getenv("GLM_CODING_BINARY", "glm")
    glm_models_str = os.getenv("GLM_CODING_MODELS", "")
    providers.append(CLIProviderConfig(
        name="glm_coding",
        binary=glm_binary,
        default_args=os.getenv("GLM_CODING_ARGS", "").split() if os.getenv("GLM_CODING_ARGS") else [],
        models=[m.strip() for m in glm_models_str.split(",") if m.strip()],
        max_concurrent=int(os.getenv("GLM_CODING_MAX_CONCURRENT", "3")),
        max_sessions_per_hour=int(os.getenv("GLM_CODING_MAX_SESSIONS_HOUR", "20")),
        timeout_seconds=int(os.getenv("GLM_CODING_TIMEOUT", os.getenv("ORKA_CLI_TIMEOUT", "300"))),
        enabled=os.getenv("GLM_CODING_ENABLED", "true").lower() == "true",
    ))

    return providers
