from app.providers.openai_compat import OpenAICompatProvider


class OpenRouterProvider(OpenAICompatProvider):
    """OpenRouter delegates to OpenAICompatProvider with different headers."""

    async def complete(self, prompt, model, max_tokens=4096, temperature=0.7):
        return await super().complete(prompt, model, max_tokens, temperature)

    def get_models(self):
        from app.providers.openai_compat import _MODELS
        return [m for m in _MODELS]
