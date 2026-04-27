# CLI-First Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CLI tools (Claude Code, GLM Coding) the primary execution layer for coding tasks, with API providers as fallback.

**Architecture:** Adapter Shell — wrap subprocess execution in CLIProviderAdapter conforming to BaseProvider. ModelRouter gains execution_mode dimension. CLIQuotaTracker handles session-based quotas. All changes are additive; nothing removed.

**Tech Stack:** Python 3.14, asyncio subprocess, SQLite + SQLAlchemy, FastAPI

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/providers/cli_base.py` | Abstract CLIProviderAdapter extending BaseProvider |
| `backend/app/providers/cli_claude.py` | Claude Code CLI concrete adapter |
| `backend/app/providers/cli_glm.py` | GLM Coding CLI concrete adapter |
| `backend/app/providers/cli_process.py` | Shared subprocess engine (prompt detection, streaming, timeouts) |
| `backend/app/services/cli_quota_tracker.py` | Session-based CLI quota tracking |
| `worker/cli_process.py` | Mirror of `backend/app/providers/cli_process.py` for standalone worker |
| `tests/test_cli_providers.py` | Unit tests for CLI providers, subprocess engine, quota tracker |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/config/model_config.py` | Add `CLIProviderConfig`, env loading for CLI providers |
| `backend/app/providers/registry.py` | Register CLI providers, add `all_by_mode()`, `find_cli_provider()` |
| `backend/app/services/model_router.py` | Add `execution_mode` to `TaskProfile`, CLI-first routing logic |
| `backend/app/models.py` | Add `execution_mode` column to `RoutingDecision` |
| `backend/app/schemas.py` | Add `execution_mode` to `RoutingDecisionResponse` |
| `worker/task_runner.py` | Delegate real execution to `cli_process` engine |
| `tests/test_phase3b_e2e.py` | Update `classify_task` calls with `has_cli_providers` param |

---

### Task 1: Shared Subprocess Engine

**Files:**
- Create: `backend/app/providers/cli_process.py`

This is the foundation — the subprocess engine that all CLI adapters use. Extracted from the patterns in `worker/task_runner.py` but generalized for reuse.

- [ ] **Step 1: Create the subprocess engine with CLIExecutionResult and prompt patterns**

```python
# backend/app/providers/cli_process.py
"""Shared subprocess engine for CLI providers.

Handles async subprocess execution, output streaming, prompt detection,
safe auto-resolution, critical escalation, and timeouts.
"""

import asyncio
import re
import time
from dataclasses import dataclass


# ── Pattern definitions (shared with worker) ─────────────────────────────

SAFE_PATTERNS: list[tuple[str, str, str, str]] = [
    # (regex_pattern, auto_response, input_type, reason)
    (r"press enter to continue", "\n", "enter", "Safe continuation prompt"),
    (r"press any key", "\n", "enter", "Safe key prompt"),
    (r"do you want to continue\??", "y\n", "yes_no", "Standard continuation"),
    (r"\[y/N\]", "y\n", "yes_no", "Default yes for safe operation"),
    (r"\[Y/n\]", "y\n", "yes_no", "Default yes"),
    (r"are you sure you want to proceed\?", "y\n", "yes_no", "Standard confirmation"),
    (r"continue\?\s*\[y/n\]", "y\n", "yes_no", "Standard continue"),
    (r"is this ok\?", "y\n", "yes_no", "Standard ok prompt"),
]

CRITICAL_PATTERNS: list[tuple[str, None | str, str, str]] = [
    (r"delete.*permanent", None, "yes_no", "Destructive action detected"),
    (r"overwrite.*existing", None, "yes_no", "Overwrite warning"),
    (r"production", None, "yes_no", "Production system risk"),
    (r"password|credential|secret|token", None, "text", "Credential-related prompt"),
    (r"deploy.*prod", None, "yes_no", "Production deployment"),
    (r"drop.*table|database", None, "yes_no", "Database destruction risk"),
    (r"sudo|administrator", None, "yes_no", "Elevated privileges required"),
    (r"irreversible|cannot be undone", None, "yes_no", "Irreversible operation"),
]

RATE_LIMIT_PATTERNS: list[tuple[str, str]] = [
    (r"rate.?limit", "rate_limited"),
    (r"quota.?exceeded", "quota_exceeded"),
    (r"too many requests", "too_many_requests"),
    (r"usage limit", "usage_limit"),
]


@dataclass
class CLIExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    prompt_count: int = 0
    auto_resolved_count: int = 0
    escalated_count: int = 0
    timed_out: bool = False
    rate_limited: bool = False
    rate_limit_reason: str | None = None


def check_prompt(line: str) -> tuple[bool, str | None, str, str]:
    """Check whether line matches a known prompt pattern.

    Returns (is_prompt, auto_response_or_None, input_type, reason).
    """
    line_lower = line.lower()

    for pattern, _auto, input_type, reason in CRITICAL_PATTERNS:
        if re.search(pattern, line_lower):
            return (True, None, input_type, reason)

    for pattern, auto_response, input_type, reason in SAFE_PATTERNS:
        if re.search(pattern, line_lower):
            return (True, auto_response, input_type, reason)

    return (False, None, "", "")


def check_rate_limit(line: str) -> str | None:
    """Check whether line matches a rate-limit signal. Returns reason or None."""
    line_lower = line.lower()
    for pattern, reason in RATE_LIMIT_PATTERNS:
        if re.search(pattern, line_lower):
            return reason
    return None


async def execute_cli(
    command: list[str],
    stdin_text: str | None = None,
    timeout: float = 300.0,
    on_output=None,
    on_prompt=None,
    auto_resolve_safe: bool = True,
) -> CLIExecutionResult:
    """Execute a CLI command via subprocess.

    Args:
        command: Command and arguments (e.g., ["claude", "--print", "-p", "hello"])
        stdin_text: Optional text to pipe to stdin at start.
        timeout: Max seconds before killing the process.
        on_output: Optional async callback(line: str, stream: str) for streaming.
        on_prompt: Optional async callback(prompt_text: str, input_type: str, reason: str)
                   for critical prompts. Must return str | None.
        auto_resolve_safe: If True, automatically respond to safe prompts.

    Returns:
        CLIExecutionResult with exit code, output, and prompt stats.
    """
    start = time.monotonic()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    prompt_count = 0
    auto_resolved_count = 0
    escalated_count = 0
    rate_limited = False
    rate_limit_reason = None

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    if stdin_text and process.stdin and not process.stdin.is_closing():
        process.stdin.write(stdin_text.encode("utf-8"))
        await process.stdin.drain()

    async def _read_stream(
        stream: asyncio.StreamReader | None,
        dest: list[str],
        stream_name: str,
    ):
        nonlocal prompt_count, auto_resolved_count, escalated_count
        nonlocal rate_limited, rate_limit_reason

        if stream is None:
            return

        while True:
            line_bytes = await stream.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            dest.append(line)

            if on_output:
                await on_output(line, stream_name)

            rl = check_rate_limit(line)
            if rl:
                rate_limited = True
                rate_limit_reason = rl

            is_prompt, auto_response, input_type, reason = check_prompt(line)
            if not is_prompt:
                continue

            prompt_count += 1

            if auto_resolve_safe and auto_response is not None:
                auto_resolved_count += 1
                if process.stdin and not process.stdin.is_closing():
                    process.stdin.write(auto_response.encode("utf-8"))
                    await process.stdin.drain()
            elif on_prompt:
                escalated_count += 1
                response = await on_prompt(line, input_type, reason)
                if response is not None and process.stdin and not process.stdin.is_closing():
                    process.stdin.write(f"{response}\n".encode("utf-8"))
                    await process.stdin.drain()
                else:
                    process.kill()

    try:
        await asyncio.gather(
            _read_stream(process.stdout, stdout_lines, "stdout"),
            _read_stream(process.stderr, stderr_lines, "stderr"),
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return CLIExecutionResult(
                exit_code=-1,
                stdout="\n".join(stdout_lines),
                stderr="\n".join(stderr_lines),
                duration_seconds=time.monotonic() - start,
                prompt_count=prompt_count,
                auto_resolved_count=auto_resolved_count,
                escalated_count=escalated_count,
                timed_out=True,
                rate_limited=rate_limited,
                rate_limit_reason=rate_limit_reason,
            )

    except Exception:
        process.kill()
        await process.wait()
        raise

    return CLIExecutionResult(
        exit_code=process.returncode if process.returncode is not None else 1,
        stdout="\n".join(stdout_lines),
        stderr="\n".join(stderr_lines),
        duration_seconds=time.monotonic() - start,
        prompt_count=prompt_count,
        auto_resolved_count=auto_resolved_count,
        escalated_count=escalated_count,
        timed_out=False,
        rate_limited=rate_limited,
        rate_limit_reason=rate_limit_reason,
    )


async def check_binary_exists(binary: str) -> bool:
    """Check whether a CLI binary is available on PATH."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "which", binary,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except Exception:
        return False
```

- [ ] **Step 2: Commit the subprocess engine**

```bash
git add backend/app/providers/cli_process.py
git commit -m "feat(cli): shared subprocess engine for CLI providers

Extracted from worker/task_runner.py patterns. Handles async subprocess
execution, prompt detection, safe auto-resolution, critical escalation,
rate-limit detection, and timeouts."
```

---

### Task 2: Worker Copy of Subprocess Engine

**Files:**
- Create: `worker/cli_process.py`

Exact copy of `backend/app/providers/cli_process.py`. The worker is a standalone process with no `backend/` imports.

- [ ] **Step 1: Copy the subprocess engine to worker directory**

```bash
cp backend/app/providers/cli_process.py worker/cli_process.py
```

- [ ] **Step 2: Commit**

```bash
git add worker/cli_process.py
git commit -m "feat(worker): add subprocess engine copy for standalone worker

Identical to backend/app/providers/cli_process.py. Worker runs
independently without backend imports."
```

---

### Task 3: CLIProviderAdapter Base Class

**Files:**
- Create: `backend/app/providers/cli_base.py`

Abstract adapter extending `BaseProvider`. CLI adapters inherit from this.

- [ ] **Step 1: Create the abstract CLIProviderAdapter**

```python
# backend/app/providers/cli_base.py
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/providers/cli_base.py
git commit -m "feat(cli): abstract CLIProviderAdapter base class

Extends BaseProvider with subprocess-based execution. Subclasses
implement build_command, parse_output, and parse_stream_chunk."
```

---

### Task 4: Claude Code CLI Adapter

**Files:**
- Create: `backend/app/providers/cli_claude.py`

Concrete adapter for Claude Code CLI.

- [ ] **Step 1: Create ClaudeCodeCLIProvider**

```python
# backend/app/providers/cli_claude.py
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
        # Try JSON parse first (--output-format json may be available)
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

        # Fallback: treat raw stdout as content
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/providers/cli_claude.py
git commit -m "feat(cli): Claude Code CLI provider adapter

Uses 'claude --print -p' for non-interactive execution.
Parses JSON output when available, falls back to raw text."
```

---

### Task 5: GLM Coding CLI Adapter

**Files:**
- Create: `backend/app/providers/cli_glm.py`

Concrete adapter for GLM Coding CLI.

- [ ] **Step 1: Create GLMCodingCLIProvider**

```python
# backend/app/providers/cli_glm.py
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/providers/cli_glm.py
git commit -m "feat(cli): GLM Coding CLI provider adapter

Executes tasks via 'glm' CLI tool. Same subprocess pattern
as Claude Code adapter with GLM-specific command format."
```

---

### Task 6: CLI Config Integration

**Files:**
- Modify: `backend/app/config/model_config.py`

Add `CLIProviderConfig` dataclass and env-based loading. Detect CLI binaries.

- [ ] **Step 1: Add CLIProviderConfig and update load_config()**

Add the following after the existing `BudgetDefaults` dataclass (around line 30):

```python
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
```

Add to `ModelRoutingConfig` dataclass (after the `quota` field, around line 42):

```python
    cli_enabled: bool = False
    cli_default: str = "claude_code"
    cli_providers: list[CLIProviderConfig] = field(default_factory=list)
```

Add a new function after `_int_env`:

```python
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
```

Update `load_config()` — before the `return ModelRoutingConfig(...)` line, add:

```python
    cli_providers = _load_cli_providers()
    cli_enabled = os.getenv("ORKA_CLI_ENABLED", "false").lower() == "true"
    cli_default = os.getenv("ORKA_CLI_DEFAULT", "claude_code")
```

And add these three lines to the `ModelRoutingConfig(...)` constructor call:

```python
        cli_enabled=cli_enabled,
        cli_default=cli_default,
        cli_providers=cli_providers,
```

- [ ] **Step 2: Verify config loads without breaking existing behavior**

Run:
```bash
cd backend && source venv/bin/activate && PYTHONPATH=$(pwd) python3 -c "from app.config.model_config import load_config; c = load_config(); print(f'cli_enabled={c.cli_enabled}, cli_providers={[p.name for p in c.cli_providers]}, api_providers={[p.name for p in c.providers]}')"
```

Expected: `cli_enabled=False, cli_providers=['claude_code', 'glm_coding'], api_providers=[]` (or whatever API providers are configured via env).

- [ ] **Step 3: Commit**

```bash
git add backend/app/config/model_config.py
git commit -m "feat(config): add CLIProviderConfig and env-based CLI provider loading

Auto-detects Claude Code and GLM CLI providers via env vars.
CLI disabled by default (ORKA_CLI_ENABLED=false). App boots
normally if CLI binaries are missing."
```

---

### Task 7: Provider Registry CLI Support

**Files:**
- Modify: `backend/app/providers/registry.py`

Register CLI providers alongside API providers. Add `all_by_mode()` and `find_cli_provider()`.

- [ ] **Step 1: Update registry to handle CLI providers**

Replace the full content of `backend/app/providers/registry.py`:

```python
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
```

- [ ] **Step 2: Verify registry still works without CLI enabled**

Run:
```bash
cd backend && source venv/bin/activate && PYTHONPATH=$(pwd) python3 -c "
from app.config.model_config import load_config
from app.providers.registry import ProviderRegistry
c = load_config()
r = ProviderRegistry(c)
print('all:', list(r.all().keys()))
print('by_mode:', {k: [p.name for p in v] for k, v in r.all_by_mode().items()})
print('has_cli:', r.has_cli_providers())
"
```

Expected: `has_cli: False`, `by_mode: {'cli': [], 'api': [...]}`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/providers/registry.py
git commit -m "feat(registry): register CLI providers alongside API providers

Adds all_by_mode(), find_cli_provider(), has_cli_providers().
CLI providers registered only when ORKA_CLI_ENABLED=true.
API provider registration unchanged."
```

---

### Task 8: CLIQuotaTracker

**Files:**
- Create: `backend/app/services/cli_quota_tracker.py`

Session-based quota tracking for CLI providers. Parallel to existing token-based `QuotaManager`.

- [ ] **Step 1: Create CLIQuotaTracker**

```python
# backend/app/services/cli_quota_tracker.py
"""Session-based quota tracker for CLI providers.

Parallel to the token-based QuotaManager. Tracks session duration,
command count, prompt count, and task count per CLI provider.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CLISessionUsage:
    provider: str
    session_count: int = 0
    total_duration_seconds: float = 0.0
    total_commands: int = 0
    total_prompts: int = 0
    total_tasks: int = 0
    status: str = "available"  # "available" | "throttled" | "blocked"
    blocked_until: datetime | None = None
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CLIQuotaTracker:
    def __init__(
        self,
        max_concurrent: int = 3,
        max_sessions_per_hour: int = 20,
        throttle_threshold: float = 0.2,
    ):
        self._max_concurrent = max_concurrent
        self._max_sessions_per_hour = max_sessions_per_hour
        self._throttle_threshold = throttle_threshold
        self._usage: dict[str, CLISessionUsage] = {}
        self._active_sessions: dict[str, int] = {}

    def _get_or_create(self, provider: str) -> CLISessionUsage:
        if provider not in self._usage:
            self._usage[provider] = CLISessionUsage(provider=provider)
        return self._usage[provider]

    def check_available(self, provider: str) -> str:
        """Check if a CLI provider has quota available.

        Returns: "available" | "throttled" | "blocked".
        """
        self._auto_reset_if_needed(provider)
        usage = self._get_or_create(provider)

        if usage.status == "blocked":
            if usage.blocked_until and datetime.now(timezone.utc) >= usage.blocked_until:
                self.reset(provider)
                return "available"
            return "blocked"

        if usage.session_count >= self._max_sessions_per_hour:
            usage.status = "blocked"
            return "blocked"

        active = self._active_sessions.get(provider, 0)
        if active >= self._max_concurrent:
            return "throttled"

        threshold = self._max_sessions_per_hour * self._throttle_threshold
        remaining = self._max_sessions_per_hour - usage.session_count
        if remaining <= threshold:
            usage.status = "throttled"
            return "throttled"

        return "available"

    def record_session(
        self,
        provider: str,
        duration_seconds: float,
        command_count: int = 1,
        prompt_count: int = 0,
        task_count: int = 1,
    ) -> None:
        """Record a completed CLI session."""
        usage = self._get_or_create(provider)
        usage.session_count += 1
        usage.total_duration_seconds += duration_seconds
        usage.total_commands += command_count
        usage.total_prompts += prompt_count
        usage.total_tasks += task_count

    def start_session(self, provider: str) -> None:
        """Track an active session start."""
        self._active_sessions[provider] = self._active_sessions.get(provider, 0) + 1

    def end_session(self, provider: str) -> None:
        """Track an active session end."""
        current = self._active_sessions.get(provider, 0)
        if current > 0:
            self._active_sessions[provider] = current - 1

    def mark_blocked(self, provider: str, reason: str, blocked_until: datetime | None = None) -> None:
        """Mark a CLI provider as blocked (e.g., rate-limit detected)."""
        usage = self._get_or_create(provider)
        usage.status = "blocked"
        usage.blocked_until = blocked_until

    def reset(self, provider: str) -> None:
        """Reset session counters for a provider."""
        if provider in self._usage:
            self._usage[provider] = CLISessionUsage(provider=provider)

    def _auto_reset_if_needed(self, provider: str) -> None:
        """Reset hourly counters if the window has passed."""
        usage = self._get_or_create(provider)
        now = datetime.now(timezone.utc)
        elapsed = (now - usage.window_start).total_seconds()
        if elapsed >= 3600:
            self._usage[provider] = CLISessionUsage(provider=provider)

    def get_usage(self, provider: str) -> CLISessionUsage | None:
        return self._usage.get(provider)

    def get_all_usage(self) -> dict[str, CLISessionUsage]:
        return dict(self._usage)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/cli_quota_tracker.py
git commit -m "feat(quota): session-based CLI quota tracker

Parallel to token-based QuotaManager. Tracks session count,
duration, commands, and prompts per CLI provider. Hourly
auto-reset, concurrent session limits, throttle at 20%."
```

---

### Task 9: Add execution_mode to RoutingDecision Model

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`

Additive column addition. SQLite `create_all` handles new columns on fresh DB.

- [ ] **Step 1: Add execution_mode column to RoutingDecision in models.py**

After line 486 (`blocked_reason` field), add:

```python
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="api")
```

The field must come before `created_at`.

- [ ] **Step 2: Add execution_mode to RoutingDecisionResponse in schemas.py**

After the `blocked_reason` field (around line 442), add:

```python
    execution_mode: str = "api"
```

- [ ] **Step 3: Delete the existing database to pick up new column**

Since this project uses `create_all` (no migrations), new columns only appear on fresh databases.

```bash
rm -f backend/orka.db
```

- [ ] **Step 4: Verify the app starts**

Run:
```bash
cd backend && source venv/bin/activate && PYTHONPATH=$(pwd) python3 -c "
import asyncio
from app.database import init_db
asyncio.run(init_db())
print('DB initialized successfully')
"
```

Expected: `DB initialized successfully`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/schemas.py
git commit -m "feat(models): add execution_mode to RoutingDecision

Defaults to 'api' for backward compatibility. Values: cli, api, simulated.
Also added to RoutingDecisionResponse schema."
```

---

### Task 10: ModelRouter CLI-First Routing

**Files:**
- Modify: `backend/app/services/model_router.py`

The core change: add `execution_mode` to `TaskProfile`, update `classify_task()`, and add CLI-first routing logic to `ModelRouter.route()`.

- [ ] **Step 1: Update TaskProfile and classify_task()**

Add import at the top of the file (after existing imports):

```python
from app.services.cli_quota_tracker import CLIQuotaTracker
```

Add constants after the existing `_COMPLEXITY_KEYWORDS` dict:

```python
# Task types that should prefer CLI execution
_CLI_PREFERRED_TASK_TYPES = {"code_gen", "review", "planning"}

# Task types that can use API for lightweight work
_API_PREFERRED_TASK_TYPES = {"docs", "analysis"}
```

Update `TaskProfile` dataclass — add `execution_mode` field:

```python
@dataclass
class TaskProfile:
    complexity: str       # "simple" | "medium" | "complex"
    importance: str       # "low" | "normal" | "critical"
    task_type: str        # "code_gen" | "analysis" | "docs" | "review" | "planning"
    context_size: int
    agent_type: str
    budget_tier: str      # "low" | "medium" | "high" | "dynamic"
    execution_mode: str = "auto"  # "auto" | "cli" | "api" | "simulated"
```

Update `classify_task()` function signature and body — add `has_cli_providers` parameter and `execution_mode` inference:

```python
def classify_task(
    content: str,
    agent_type: str,
    importance: str = "normal",
    has_cli_providers: bool = False,
) -> TaskProfile:
    budget_tier = _AGENT_TIER_DEFAULTS.get(agent_type, "medium")
    lower = content.lower()

    complexity = "medium"
    for level, keywords in _COMPLEXITY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            complexity = level
            break

    if len(content) < 100 and complexity == "medium":
        complexity = "simple"

    task_type = "code_gen"
    if any(w in lower for w in ["doc", "readme", "comment", "explain"]):
        task_type = "docs"
    elif any(w in lower for w in ["test", "qa", "review", "check"]):
        task_type = "review"
    elif any(w in lower for w in ["analyz", "investigat", "assess"]):
        task_type = "analysis"
    elif any(w in lower for w in ["plan", "design", "architect"]):
        task_type = "planning"

    context_size = len(content.split()) * 2

    if importance == "critical":
        budget_tier = "high"

    # Determine execution mode
    execution_mode = "api"
    if task_type in _CLI_PREFERRED_TASK_TYPES and has_cli_providers:
        execution_mode = "cli"
    elif task_type in _API_PREFERRED_TASK_TYPES:
        execution_mode = "api"
    elif has_cli_providers:
        execution_mode = "cli"

    return TaskProfile(
        complexity=complexity,
        importance=importance,
        task_type=task_type,
        context_size=context_size,
        agent_type=agent_type,
        budget_tier=budget_tier,
        execution_mode=execution_mode,
    )
```

- [ ] **Step 2: Update ModelRouter constructor**

Update `__init__` to create a `CLIQuotaTracker`:

```python
    def __init__(self, config: ModelRoutingConfig, registry: ProviderRegistry):
        self._config = config
        self._registry = registry
        self._quota = QuotaManager(config)
        self._budget = BudgetManager()
        self._tracker = UsageTracker()
        self._cli_quota = CLIQuotaTracker(
            max_concurrent=max(p.max_concurrent for p in config.cli_providers) if config.cli_providers else 3,
            max_sessions_per_hour=max(p.max_sessions_per_hour for p in config.cli_providers) if config.cli_providers else 20,
        )
```

- [ ] **Step 3: Update ModelRouter.route() method**

Replace the `route()` method with the CLI-first version that tries CLI before API:

```python
    async def route(
        self,
        prompt: str,
        profile: TaskProfile,
        task_id: str | None,
        db: AsyncSession,
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Route a task to the best available model. Returns (response, decision)."""
        available_providers = self._registry.all()
        if available_providers:
            for pname, prov in available_providers.items():
                models = [m.id for m in prov.get_models()]
                print(f"[ModelRouter] provider='{pname}' models={models}")
        else:
            print(f"[ModelRouter] WARNING: no providers configured")

        # 1. Determine execution mode
        execution_mode = self._resolve_execution_mode(profile)
        print(f"[ModelRouter] execution_mode={execution_mode} task_type={profile.task_type} tier={profile.budget_tier}")

        # 2. Try CLI path if applicable
        if execution_mode == "cli":
            response, decision = await self._try_cli_route(
                prompt, profile, task_id, db
            )
            if response is not None:
                return response, decision
            print(f"[ModelRouter] CLI route failed/blocked, falling back to API")

        # 3. Try API path
        response, decision = await self._try_api_route(
            prompt, profile, task_id, db, execution_mode
        )
        if response is not None:
            return response, decision

        # 4. No provider available
        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model="none",
            selected_provider="none",
            reason="all_providers_exhausted",
            fallback_from=None,
            quota_status="exhausted",
            cost_estimate=0.0,
            blocked_reason="no_provider_with_quota",
            execution_mode=execution_mode,
        )
        db.add(decision)
        await db.flush()
        return None, decision
```

- [ ] **Step 4: Add new helper methods to ModelRouter**

Add these methods after `route()`:

```python
    def _resolve_execution_mode(self, profile: TaskProfile) -> str:
        """Resolve 'auto' execution mode to a concrete mode."""
        if profile.execution_mode != "auto":
            return profile.execution_mode

        has_cli = self._registry.has_cli_providers()
        has_api = len(self._registry.all_by_mode()["api"]) > 0

        if profile.task_type in _CLI_PREFERRED_TASK_TYPES and has_cli:
            return "cli"
        if profile.task_type in _API_PREFERRED_TASK_TYPES and has_api:
            return "api"
        if has_cli:
            return "cli"
        if has_api:
            return "api"
        return "simulated"

    async def _try_cli_route(
        self, prompt: str, profile: TaskProfile, task_id: str | None, db: AsyncSession
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Try to route via a CLI provider."""
        cli_providers = self._registry.all_by_mode()["cli"]
        if not cli_providers:
            return None, None

        provider = None
        quota_status = "available"
        for cp in cli_providers:
            quota_status = self._cli_quota.check_available(cp.name)
            if quota_status != "blocked":
                healthy = await cp.health_check()
                if healthy:
                    provider = cp
                    break
                else:
                    cp.invalidate_cache()

        if provider is None:
            return None, None

        models = provider.get_models()
        target_model = models[0].id if models else "unknown"

        self._cli_quota.start_session(provider.name)
        try:
            response = await provider.complete(prompt=prompt, model=target_model)
        except Exception as exc:
            self._cli_quota.end_session(provider.name)
            print(f"[ModelRouter] CLI provider '{provider.name}' error: {exc}")
            return None, None

        self._cli_quota.end_session(provider.name)
        self._cli_quota.record_session(provider.name, duration_seconds=response.latency_ms / 1000.0)

        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model=target_model,
            selected_provider=provider.name,
            reason="cli_primary",
            fallback_from=None,
            quota_status=quota_status,
            cost_estimate=0.0,
            actual_cost=0.0,
            execution_mode="cli",
        )
        db.add(decision)
        await db.flush()

        return response, decision

    async def _try_api_route(
        self, prompt: str, profile: TaskProfile, task_id: str | None,
        db: AsyncSession, execution_mode: str,
    ) -> tuple[ProviderResponse | None, RoutingDecision | None]:
        """Try to route via an API provider. Same logic as before."""
        target_model = _tier_to_model(profile.budget_tier, self._config)

        provider, model_info, quota_status = await self._find_available_provider(
            target_model, profile, db
        )

        fallback_from = None
        if provider is None and profile.budget_tier != "low":
            fallback_from = target_model
            lower_tier = "medium" if profile.budget_tier in ("high", "dynamic") else "low"
            target_model = _tier_to_model(lower_tier, self._config)
            provider, model_info, quota_status = await self._find_available_provider(
                target_model, profile, db
            )

        if provider is None:
            return None, None

        estimated_cost = provider.estimate_cost(profile.context_size, target_model)
        budget_state = await self._budget.get_state(db)
        if budget_state == "blocked" and profile.importance != "critical":
            decision = RoutingDecision(
                task_id=task_id,
                agent_type=profile.agent_type,
                requested_tier=profile.budget_tier,
                selected_model="none",
                selected_provider="none",
                reason="budget_blocked",
                fallback_from=fallback_from,
                quota_status=quota_status,
                cost_estimate=estimated_cost,
                blocked_reason="budget_exhausted",
                execution_mode="api",
            )
            db.add(decision)
            await db.flush()
            return None, decision

        reason = "auto"
        if fallback_from:
            reason = "fallback_quota_exhausted"
        elif quota_status == "throttled":
            reason = "quota_throttle"
        elif budget_state == "throttled":
            reason = "budget_throttle"

        try:
            response = await provider.complete(prompt=prompt, model=target_model)
        except Exception:
            decision = RoutingDecision(
                task_id=task_id,
                agent_type=profile.agent_type,
                requested_tier=profile.budget_tier,
                selected_model=target_model,
                selected_provider=provider.name,
                reason="provider_error",
                fallback_from=fallback_from,
                quota_status=quota_status,
                cost_estimate=estimated_cost,
                blocked_reason="provider_call_failed",
                execution_mode="api",
            )
            db.add(decision)
            await db.flush()
            return None, decision

        reason_str = "api_fallback" if execution_mode == "cli" else reason
        decision = RoutingDecision(
            task_id=task_id,
            agent_type=profile.agent_type,
            requested_tier=profile.budget_tier,
            selected_model=target_model,
            selected_provider=provider.name,
            reason=reason_str,
            fallback_from=fallback_from,
            quota_status=quota_status,
            cost_estimate=estimated_cost,
            actual_cost=response.cost_usd,
            execution_mode="api",
        )
        db.add(decision)
        await db.flush()

        await self._tracker.record(response, task_id, profile.agent_type, decision.id, db)
        await self._quota.consume(provider.name, response.input_tokens + response.output_tokens, db)

        return response, decision
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/model_router.py
git commit -m "feat(router): CLI-first routing with execution_mode

Adds execution_mode to TaskProfile (auto/cli/api/simulated).
Coding/debug/test tasks prefer CLI. Docs/analysis prefer API.
Falls back CLI->API->simulated. No silent paid fallback."
```

---

### Task 11: Update TaskRunner to Use Shared Engine

**Files:**
- Modify: `worker/task_runner.py`

Make TaskRunner delegate real execution to the shared `cli_process` engine.

- [ ] **Step 1: Update imports — remove `re`, import from `cli_process`**

Replace lines 1-16 (imports and pattern defs) with:

```python
"""
ORKA Task Runner.

Executes tasks with autonomous prompt handling. Detects safe vs critical
prompts in process output and either auto-resolves them or escalates to
the dashboard for human input.
"""

import asyncio
import logging
import time

from session_manager import SessionManager
from cli_process import execute_cli, CLIExecutionResult, check_prompt

logger = logging.getLogger("orka-worker.task_runner")

SIMULATION_MODE = True
```

This removes the duplicated `SAFE_PATTERNS`, `CRITICAL_PATTERNS`, and `re` import — all now in `cli_process.py`.

- [ ] **Step 2: Update run_task real execution path**

Replace the real execution block in `run_task` (the non-simulation branch) with:

```python
        await self.session_manager.add_log(
            session_id, "info", f"Starting task execution: {command}"
        )
        await self.session_manager.update_session(session_id, status="running")

        try:
            async def on_output(line: str, stream: str):
                level = "output" if stream == "stdout" else "warn"
                await self.session_manager.add_log(session_id, level, line)

            async def on_prompt(prompt_text: str, input_type: str, reason: str) -> str | None:
                return await self._escalate_prompt(session_id, prompt_text, input_type, reason)

            result = await execute_cli(
                command=command.split() if isinstance(command, str) else command,
                timeout=300.0,
                on_output=on_output,
                on_prompt=on_prompt,
                auto_resolve_safe=True,
            )

            if result.timed_out:
                await self.session_manager.mark_error(
                    session_id, "Task timed out after 300 seconds"
                )
            elif result.exit_code == 0:
                await self.session_manager.mark_completed(session_id, result.exit_code)
            else:
                await self.session_manager.mark_error(
                    session_id, f"Process exited with code {result.exit_code}"
                )

        except Exception as exc:
            logger.exception("Task execution failed for session %s", session_id)
            await self.session_manager.mark_error(session_id, str(exc))
```

- [ ] **Step 3: Remove unused methods**

Remove `_stream_output`, `_check_prompt`, and `_handle_autonomous` methods. Their logic is now in `cli_process.py`. Keep `_escalate_prompt` and `_simulate_claude_code`.

- [ ] **Step 4: Update _simulate_claude_code to use check_prompt**

In `_simulate_claude_code`, replace `await self._check_prompt(...)` calls with `check_prompt(...)` (no `await`, no `self`):

```python
is_prompt, auto_response, input_type, reason = check_prompt(safe_prompt)
```

and:

```python
_, _, crit_input_type, crit_reason = check_prompt(critical_prompt)
```

- [ ] **Step 5: Verify worker still works in simulation mode**

Run:
```bash
cd worker && source venv/bin/activate && python3 -c "from task_runner import TaskRunner; print('TaskRunner imported successfully')"
```

Expected: `TaskRunner imported successfully`

- [ ] **Step 6: Commit**

```bash
git add worker/task_runner.py
git commit -m "refactor(worker): delegate real execution to shared cli_process engine

TaskRunner now uses cli_process.execute_cli() for real subprocess
execution. Simulation mode unchanged. Removed duplicated prompt
patterns — sourced from cli_process.py."
```

---

### Task 12: Unit Tests for CLI Providers

**Files:**
- Create: `tests/test_cli_providers.py`

Test the subprocess engine, CLI adapters, and quota tracker without requiring actual CLI tools installed.

- [ ] **Step 1: Create the test file with 13 test cases**

Write `tests/test_cli_providers.py` with these 13 test cases. Each test uses print-based assertions and appends to a `results` list for summary output:

1. **CLIExecutionResult** — create instance, verify fields
2. **check_prompt (safe)** — test 4 cases: `[y/N]`, `Press Enter`, `[Y/n]`, normal line
3. **check_prompt (critical)** — test 3 cases: delete permanent, password, deploy prod
4. **check_rate_limit** — test 3 cases: rate limit, quota exceeded, normal output
5. **execute_cli (echo)** — run `echo hello world`, verify exit_code=0 and stdout
6. **execute_cli (timeout)** — run `sleep 10` with 1s timeout, verify timed_out=True
7. **ClaudeCodeCLIProvider build_command** — verify command has `--print`, `-p`, `--model`
8. **ClaudeCodeCLIProvider parse_output** — test JSON parse (`{"result":"fixed!"}`) and raw text fallback
9. **GLMCodingCLIProvider build_command** — verify command has `--model` and prompt
10. **CLIQuotaTracker** — test available→throttled→blocked→reset→concurrent lifecycle (6 checks)
11. **classify_task with execution_mode** — test coding+cli="cli", docs+cli="api", coding+no_cli="api"
12. **CLIConfig** — verify load_config().cli_enabled=False and 2 CLI providers listed
13. **Registry with CLI disabled** — verify has_cli_providers()=False and empty cli list

Use `PASS`/`FAIL` strings and `sys.exit(1)` on failure, same pattern as existing `test_phase3b_e2e.py`. Import backend modules via `sys.path.insert(0, ...)`.

- [ ] **Step 2: Run the tests**

Run:
```bash
cd backend && source venv/bin/activate && PYTHONPATH=$(pwd) python3 ../tests/test_cli_providers.py
```

Expected: All 13 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli_providers.py
git commit -m "test(cli): unit tests for CLI providers, subprocess engine, quota tracker

13 tests covering: CLIExecutionResult, prompt detection, rate-limit
detection, execute_cli, ClaudeCode/GLM adapters, CLIQuotaTracker,
classify_task execution_mode, config, and registry."
```

---

### Task 13: Update Existing Test Callers

**Files:**
- Modify: `tests/test_phase3b_e2e.py`

Ensure all existing `classify_task()` calls pass `has_cli_providers` parameter.

- [ ] **Step 1: Update classify_task calls**

Find all calls to `classify_task` and add `has_cli_providers=False`:

- Line ~85: `classify_task("What is 2+2? Reply with just the number.", "docs")` becomes `classify_task("What is 2+2? Reply with just the number.", "docs", has_cli_providers=False)`
- Line ~117: `classify_task("Explain what a REST API is in one sentence.", "backend")` becomes `classify_task("Explain what a REST API is in one sentence.", "backend", has_cli_providers=False)`
- Line ~237: `classify_task("Test task after exhaustion", "docs")` becomes `classify_task("Test task after exhaustion", "docs", has_cli_providers=False)`

Also check `backend/app/services/agent_simulator.py` for any `classify_task` calls — if found, pass `has_cli_providers=False` or `has_cli_providers=registry.has_cli_providers()` depending on context.

- [ ] **Step 2: Verify backward compatibility**

Run:
```bash
cd backend && source venv/bin/activate && PYTHONPATH=$(pwd) python3 -c "
from app.services.model_router import classify_task
p = classify_task('Fix bug', 'backend', has_cli_providers=False)
print(f'tier={p.budget_tier} mode={p.execution_mode} type={p.task_type}')
assert p.execution_mode == 'api', f'Expected api, got {p.execution_mode}'
print('OK: backward compatible')
"
```

Expected: `tier=high mode=api type=code_gen`

- [ ] **Step 3: Commit**

```bash
git add tests/test_phase3b_e2e.py
git commit -m "fix(tests): update classify_task calls with has_cli_providers param

Existing Phase 3B tests pass has_cli_providers=False to preserve
backward-compatible behavior."
```

---

### Task 14: Final Verification

**Files:**
- None (verification only)

- [ ] **Step 1: Verify backend starts cleanly**

Run:
```bash
cd backend && source venv/bin/activate && PYTHONPATH=$(pwd) python3 -c "
import asyncio
from app.database import init_db, seed_db
from app.config.model_config import load_config
from app.providers.registry import ProviderRegistry

async def verify():
    await init_db()
    await seed_db()
    config = load_config()
    registry = ProviderRegistry(config)
    print(f'CLI enabled: {config.cli_enabled}')
    print(f'CLI providers: {[p.name for p in config.cli_providers]}')
    print(f'Has CLI: {registry.has_cli_providers()}')
    print(f'All providers: {list(registry.all().keys())}')
    by_mode = registry.all_by_mode()
    print(f'CLI: {[p.name for p in by_mode[\"cli\"]]}, API: {[p.name for p in by_mode[\"api\"]]}')
    print('Backend starts OK')

asyncio.run(verify())
"
```

Expected: No errors. CLI enabled=False, providers listed but not registered.

- [ ] **Step 2: Run all CLI tests**

Run:
```bash
cd backend && source venv/bin/activate && PYTHONPATH=$(pwd) python3 ../tests/test_cli_providers.py
```

Expected: 13 passed, 0 failed.

- [ ] **Step 3: Verify worker imports work**

Run:
```bash
cd worker && source venv/bin/activate && python3 -c "from task_runner import TaskRunner; from cli_process import execute_cli, check_prompt; print('Worker imports OK')"
```

Expected: `Worker imports OK`
