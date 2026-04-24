from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ModelInfo:
    id: str
    provider: str
    tier: str  # "low" | "medium" | "high"
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_tokens: int
    strengths: list[str] = field(default_factory=list)
    speed: str = "medium"  # "fast" | "medium" | "slow"


@dataclass
class ProviderResponse:
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class BaseProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> ProviderResponse:
        ...

    @abstractmethod
    async def stream(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        ...

    @abstractmethod
    def get_models(self) -> list[ModelInfo]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @abstractmethod
    def estimate_cost(self, tokens: int, model: str) -> float:
        ...
