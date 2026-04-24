"""Claude Code CLI provider adapter.

Executes tasks via the `claude` CLI tool using --print mode for
non-interactive execution and --output-format json for structured output.
"""

import json

from app.providers.base import ModelInfo, ProviderResponse
from app.providers.cli_base import CLIProviderAdapter


class ClaudeCodeCLIProvider(CLIProviderAdapter):
    """Adapter for Anthropic's Claude Code CLI."""

    def __init__(
        self,
        binary: str = "claude",
        models: list[ModelInfo] | None = None,
        timeout: float = 300.0,
    ):
        default_models = models or [
            ModelInfo("claude-sonnet-4-6", "claude_code", "medium", 0.0, 0.0, 200000, ["code", "reasoning"], "medium"),
            ModelInfo("claude-opus-4-7", "claude_code", "high", 0.0, 0.0, 200000, ["reasoning", "analysis", "code"], "slow"),
        ]
        super().__init__(
            name="claude_code",
            binary=binary,
            models=default_models,
            timeout=timeout,
        )

    def build_command(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> list[str]:
        cmd = [self._binary, "--print", "-p", prompt]
        if model:
            cmd.extend(["--model", model])
        if self._default_args:
            cmd.extend(self._default_args)
        return cmd

    def parse_output(self, raw_stdout: str, model: str) -> ProviderResponse:
        try:
            data = json.loads(raw_stdout)
            content = data.get("result", data.get("content", raw_stdout))
            return ProviderResponse(
                content=content if isinstance(content, str) else json.dumps(content),
                model=data.get("model", model),
                provider=self.name,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=0,
            )
        except (json.JSONDecodeError, AttributeError):
            pass

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
