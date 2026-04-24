from app.config.model_config import ModelRoutingConfig, ProviderConfig
from app.providers.base import BaseProvider, ModelInfo
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.openrouter import OpenRouterProvider


class ProviderRegistry:
    def __init__(self, config: ModelRoutingConfig):
        self._providers: dict[str, BaseProvider] = {}
        for pc in config.providers:
            if pc.name == "openrouter":
                provider = OpenRouterProvider(pc.name, pc.base_url, pc.api_key)
            else:
                provider = OpenAICompatProvider(pc.name, pc.base_url, pc.api_key)
            self._providers[pc.name] = provider

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
