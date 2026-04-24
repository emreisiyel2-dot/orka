import time
from typing import AsyncIterator

import httpx

from app.providers.base import BaseProvider, ModelInfo, ProviderResponse


_MODELS: list[ModelInfo] = [
    ModelInfo("gpt-4o", "openai", "high", 0.0025, 0.01, 128000, ["code", "reasoning"], "medium"),
    ModelInfo("gpt-4o-mini", "openai", "low", 0.00015, 0.0006, 128000, ["code", "general"], "fast"),
    ModelInfo("claude-sonnet-4-6", "anthropic", "medium", 0.003, 0.015, 200000, ["code", "reasoning", "analysis"], "medium"),
    ModelInfo("claude-opus-4-7", "anthropic", "high", 0.015, 0.075, 200000, ["reasoning", "analysis", "code"], "slow"),
    ModelInfo("gemini-2.5-flash", "google", "low", 0.000075, 0.0003, 1000000, ["code", "general"], "fast"),
]


class OpenAICompatProvider(BaseProvider):
    def __init__(self, name: str, base_url: str, api_key: str,
                 custom_models: list[ModelInfo] | None = None):
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._custom_models = custom_models

    def get_models(self) -> list[ModelInfo]:
        if self._custom_models is not None:
            return list(self._custom_models)
        return [m for m in _MODELS if m.provider == self.name]

    async def complete(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> ProviderResponse:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        latency = int((time.monotonic() - start) * 1000)
        usage = data.get("usage", {})
        choice = data["choices"][0]["message"]["content"]
        info = self._find_model_info(model)
        cost = 0.0
        if info:
            cost = (usage.get("prompt_tokens", 0) / 1000 * info.cost_per_1k_input
                    + usage.get("completion_tokens", 0) / 1000 * info.cost_per_1k_output)

        return ProviderResponse(
            content=choice,
            model=model,
            provider=self.name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cost_usd=cost,
            latency_ms=latency,
        )

    async def stream(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        import json
                        chunk = json.loads(line[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    def _find_model_info(self, model: str) -> ModelInfo | None:
        if self._custom_models:
            return next((m for m in self._custom_models if m.id == model), None)
        return next((m for m in _MODELS if m.id == model), None)

    def estimate_cost(self, tokens: int, model: str) -> float:
        info = self._find_model_info(model)
        if info:
            return tokens / 1000 * info.cost_per_1k_input
        return 0.0
