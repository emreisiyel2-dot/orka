from app.config.model_config import ModelRoutingConfig, ProviderConfig
from app.providers.base import BaseProvider, ModelInfo
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.openrouter import OpenRouterProvider


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
    # medium = high if available, else low
    _add(pc.model_high or pc.model_low or "", "medium")
    return models if models else None


class ProviderRegistry:
    def __init__(self, config: ModelRoutingConfig):
        self._providers: dict[str, BaseProvider] = {}
        for pc in config.providers:
            custom_models = _build_custom_models(pc)
            if pc.name == "openrouter":
                provider = OpenRouterProvider(pc.name, pc.base_url, pc.api_key)
            else:
                provider = OpenAICompatProvider(pc.name, pc.base_url, pc.api_key, custom_models=custom_models)
            self._providers[pc.name] = provider
            models_str = [m.id for m in provider.get_models()]
            print(f"[ProviderRegistry] '{pc.name}' base_url={pc.base_url} models={models_str}")

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
