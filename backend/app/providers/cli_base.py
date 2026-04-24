"""Abstract CLI provider adapter.

CLIProviderAdapter extends BaseProvider so CLI tools satisfy the same
interface as API providers. ModelRouter can select CLI or API transparently.
"""

from abc import abstractmethod
from typing import AsyncIterator

from app.providers.base import BaseProvider, ModelInfo, ProviderResponse
from app.providers.cli_process import check_binary_exists, execute_cli


class CLIProviderAdapter(BaseProvider):
    """Base class for CLI-based providers. Subclasses define command building and output parsing."""

    def __init__(
        self,
        name: str,
        binary: str,
        models: list[ModelInfo],
        timeout: float = 300.0,
        default_args: list[str] | None = None,
    ):
        self.name = name
        self._binary = binary
        self._models = models
        self._timeout = timeout
        self._default_args = default_args or []
        self._available: bool | None = None

    @abstractmethod
    def build_command(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> list[str]:
        """Build the CLI command to execute. Returns command list."""
        ...

    @abstractmethod
    def parse_output(self, raw_stdout: str, model: str) -> ProviderResponse:
        """Parse raw CLI stdout into a ProviderResponse."""
        ...

    @abstractmethod
    def parse_stream_chunk(self, line: str) -> str | None:
        """Parse a streaming line into content. Return None to skip."""
        ...

    async def complete(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> ProviderResponse:
        command = self.build_command(prompt, model, max_tokens, temperature)
        result = await execute_cli(command, timeout=self._timeout)
        return self.parse_output(result.stdout, model)

    async def stream(
        self, prompt: str, model: str, max_tokens: int = 4096, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        command = self.build_command(prompt, model, max_tokens, temperature)
        import asyncio

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if process.stdout:
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                chunk = self.parse_stream_chunk(line)
                if chunk is not None:
                    yield chunk

        await process.wait()

    async def health_check(self) -> bool:
        if self._available is None:
            self._available = await check_binary_exists(self._binary)
        return self._available

    def get_models(self) -> list[ModelInfo]:
        return list(self._models)

    def estimate_cost(self, tokens: int, model: str) -> float:
        return 0.0

    def invalidate_cache(self) -> None:
        """Force re-check of binary availability on next health_check."""
        self._available = None
