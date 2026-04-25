from app.config.model_config import ModelRoutingConfig, ProviderConfig
from app.providers.base import BaseProvider, ModelInfo
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.openrouter import OpenRouterProvider
from app.providers.cli_claude import ClaudeCodeCLIProvider
from app.providers.cli_glm import GLMCodingCLIProvider


def _build_custom_models(pc: ProviderConfig) -> list[ModelInfo] | None:
    """Build model list from provider config env vars (model_low, model_high)."""
    seen_ids: set[str] = set()
    models: list[ModelInfo] = []

    def _add(mid: str, tier: str):
        if mid and mid not in seen_ids:
            seen_ids.add(mid)
            models.append(ModelInfo(mid, pc.name, tier, 0.0, 0.0, 128000,
                                    ["code", "reasoning"] if tier != "low" else ["general"],
                                    "fast" if tier == "low" else "medium"))

    _add(pc.model_low or "", "low")
    _add(pc.model_high or "", "high")
    _add(pc.model_high or pc.model_low or "", "medium")
    return models if models else None


def _build_cli_models(cli_config) -> list[ModelInfo] | None:
    """Build model list for a CLI provider from CLIProviderConfig."""
    if not cli_config.models:
        return None
    models: list[ModelInfo] = []
    for i, mid in enumerate(cli_config.models):
        tier = "medium" if i == 0 else "high" if i == 1 else "low"
        models.append(ModelInfo(mid, cli_config.name, tier, 0.0, 0.0, 128000, ["code"], "medium"))
    return models


class ProviderRegistry:
    def __init__(self, config: ModelRoutingConfig):
        self._providers: dict[str, BaseProvider] = {}
        self._cli_provider_names: set[str] = set()

        # Register API providers (unchanged)
        for pc in config.providers:
            custom_models = _build_custom_models(pc)
            if pc.name == "openrouter":
                provider = OpenRouterProvider(pc.name, pc.base_url, pc.api_key)
            else:
                provider = OpenAICompatProvider(pc.name, pc.base_url, pc.api_key, custom_models=custom_models)
            self._providers[pc.name] = provider
            models_str = [m.id for m in provider.get_models()]
            print(f"[ProviderRegistry] API provider='{pc.name}' base_url={pc.base_url} models={models_str}")

        # Register CLI providers
        if config.cli_enabled:
            for cc in config.cli_providers:
                if not cc.enabled:
                    print(f"[ProviderRegistry] CLI provider='{cc.name}' disabled, skipping")
                    continue
                try:
                    provider = self._create_cli_provider(cc)
                    if provider:
                        self._providers[cc.name] = provider
                        self._cli_provider_names.add(cc.name)
                        models_str = [m.id for m in provider.get_models()]
                        print(f"[ProviderRegistry] CLI provider='{cc.name}' binary={cc.binary} models={models_str}")
                except Exception as e:
                    print(f"[ProviderRegistry] CLI provider='{cc.name}' registration failed: {e}")
        else:
            print(f"[ProviderRegistry] CLI providers disabled (ORKA_CLI_ENABLED=false)")

    def _create_cli_provider(self, cc) -> BaseProvider | None:
        """Create a CLI provider instance from CLIProviderConfig."""
        if cc.name == "claude_code":
            models = _build_cli_models(cc)
            return ClaudeCodeCLIProvider(
                binary=cc.binary,
                models=models,
                timeout=float(cc.timeout_seconds),
            )
        elif cc.name == "glm_coding":
            models = _build_cli_models(cc)
            return GLMCodingCLIProvider(
                binary=cc.binary,
                models=models,
                timeout=float(cc.timeout_seconds),
            )
        else:
            print(f"[ProviderRegistry] Unknown CLI provider: {cc.name}")
            return None

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def all(self) -> dict[str, BaseProvider]:
        return dict(self._providers)

    def all_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        for p in self._providers.values():
            models.extend(p.get_models())
        return models

    def find_provider_for_model(self, model_id: str) -> BaseProvider | None:
        for p in self._providers.values():
            if any(m.id == model_id for m in p.get_models()):
                return p
        return None

    def find_providers_for_tier(self, tier: str) -> list[BaseProvider]:
        result = []
        for p in self._providers.values():
            if any(m.tier == tier for m in p.get_models()):
                result.append(p)
        return result

    def all_by_mode(self) -> dict[str, list[BaseProvider]]:
        """Return providers grouped by execution mode: 'cli' and 'api'."""
        cli_providers = []
        api_providers = []
        for name, provider in self._providers.items():
            if name in self._cli_provider_names:
                cli_providers.append(provider)
            else:
                api_providers.append(provider)
        return {"cli": cli_providers, "api": api_providers}

    def find_cli_provider(self, name: str | None = None) -> BaseProvider | None:
        """Find a CLI provider by name, or return the first available CLI provider."""
        if name:
            return self._providers.get(name) if name in self._cli_provider_names else None
        for n in self._cli_provider_names:
            return self._providers[n]
        return None

    def has_cli_providers(self) -> bool:
        return len(self._cli_provider_names) > 0
