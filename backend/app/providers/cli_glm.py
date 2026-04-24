"""GLM Coding CLI provider adapter.

Executes tasks via the `glm` CLI tool.
"""

from app.providers.base import ModelInfo, ProviderResponse
from app.providers.cli_base import CLIProviderAdapter


class GLMCodingCLIProvider(CLIProviderAdapter):
    """Adapter for GLM Coding CLI."""

    def __init__(
        self,
        binary: str = "glm",
        models: list[ModelInfo] | None = None,
        timeout: float = 300.0,
    ):
        default_models = models or [
            ModelInfo("glm-4-plus", "glm_coding", "medium", 0.0, 0.0, 128000, ["code", "reasoning"], "medium"),
        ]
        super().__init__(
            name="glm_coding",
            binary=binary,
            models=default_models,
            timeout=timeout,
        )

    def build_command(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> list[str]:
        cmd = [self._binary]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        if self._default_args:
            cmd.extend(self._default_args)
        return cmd

    def parse_output(self, raw_stdout: str, model: str) -> ProviderResponse:
        return ProviderResponse(
            content=raw_stdout.strip(),
            model=model,
            provider=self.name,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )

    def parse_stream_chunk(self, line: str) -> str | None:
        if not line.strip():
            return None
        return line
