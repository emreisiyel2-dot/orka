# CLI-First Architecture Design

Date: 2026-04-24
Status: Draft
Scope: Phase 3B

## Summary

Update ORKA's execution model so CLI tools (Claude Code CLI, GLM Coding CLI) are the primary execution layer for coding tasks, with API providers as fallback. The system should feel like an automated Claude Code, not an API wrapper.

## Architecture

### Execution Flow

```
User → ORKA Dashboard → AgentRuntime → ModelRouter
                                              │
                                    ┌─────────┴─────────┐
                                    │ execution_mode?    │
                                    │                    │
                               CLI tasks            API/fallback tasks
                                    │                    │
                             CLIProviderAdapter    existing providers
                            ┌───────┴───────┐    (OpenAICompat, OpenRouter)
                            │               │
                    ClaudeCodeCLI     GLMCodingCLI
                    (subprocess)      (subprocess)
```

### Approach: Adapter Shell

Wrap the existing `TaskRunner` subprocess system in a `CLIProviderAdapter` that conforms to `BaseProvider`. The `ModelRouter` gains an `execution_mode` dimension before tier-based selection. API providers remain intact.

Chosen over:
- **Unified Executor** — would require rewriting existing provider system; too disruptive
- **Sidecar Worker** — adds operational complexity with message queues; unnecessary for single-machine use

## Components

### 1. CLIProviderAdapter (new)

**File**: `backend/app/providers/cli_base.py`

Abstract base extending `BaseProvider`. Satisfies the same interface as API providers so `ModelRouter` can select CLI or API transparently.

Interface:
- `complete(prompt, model, max_tokens, temperature)` → `ProviderResponse`
  - Runs CLI command via async subprocess
  - Waits for completion, parses output
  - Returns structured result
- `stream(prompt, model, max_tokens, temperature)` → `AsyncIterator[str]`
  - Runs CLI command, yields output chunks as they arrive
- `health_check()` → `bool`
  - Verifies CLI binary exists on PATH
  - Non-blocking; failure marks provider unavailable but app still boots
- `estimate_cost(tokens, model)` → `0.0`
  - CLI has no per-token cost
- `get_models()` → `list[ModelInfo]`
  - Returns models the CLI tool exposes (configured via env)

Abstract methods for subclasses:
- `build_command(prompt, model, max_tokens, temperature)` → command list
- `parse_output(raw_stdout)` → `ProviderResponse`
- `parse_stream_chunk(line)` → `str | None`

### 2. ClaudeCodeCLIProvider (new)

**File**: `backend/app/providers/cli_claude.py`

Non-interactive mode:
```
claude --print -p "{prompt}" --output-format json
```

Interactive/streaming mode:
```
claude
```
- Sends prompt via stdin
- Streams stdout/stderr
- Parses JSON output when `--output-format json` is available

### 3. GLMCodingCLIProvider (new)

**File**: `backend/app/providers/cli_glm.py`

Command:
```
glm {prompt}
```
- Adapts prompt format and output parsing for GLM CLI
- Same subprocess + prompt detection pattern

### 4. Shared Subprocess Engine (new)

**Files**: `backend/app/providers/cli_process.py` and `worker/cli_process.py`

Extracted from `worker/task_runner.py` — no duplication. Since the worker is a standalone process (no `backend/` imports), the subprocess engine lives in both locations as identical copies. During implementation, consider making `worker/` import from `backend/` via a shared package or symlinks if the project structure allows.

Handles:
- Subprocess spawn (`asyncio.create_subprocess_exec`)
- Output streaming (stdout/stderr line reader)
- Prompt detection (reuses `SAFE_PATTERNS` and `CRITICAL_PATTERNS`)
- Safe prompt auto-resolution (writes to stdin)
- Critical prompt escalation (returns to caller for dashboard escalation)
- Timeout enforcement
- Process cleanup on cancel/error

Returns `CLIExecutionResult`:
```python
@dataclass
class CLIExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    prompt_count: int
    auto_resolved_count: int
    escalated_count: int
    timed_out: bool
```

### 5. ModelRouter Updates

**File**: `backend/app/services/model_router.py`

**New field on `TaskProfile`:**
```python
execution_mode: str = "auto"  # "auto" | "cli" | "api" | "simulated"
```

**Routing decision order:**
1. Determine `execution_mode` from `task_type`:
   - `code_gen`, `review`, `planning` → `"cli"` if CLI provider available
   - `docs`, `analysis` → `"api"` if API provider available, else `"cli"`
   - Default → `"cli"` if available, else `"api"`, else `"simulated"`
2. Filter providers by execution mode
3. Apply existing tier-based selection on filtered providers
4. Fallback chain: CLI → API → simulated
   - Never silently use paid API
   - If no safe provider exists, pause task and show action required

**New methods:**
- `_find_cli_provider(task_id, db)` → check CLI providers: healthy + not quota-blocked
- `_find_api_provider(model_id, profile, db)` → existing `_find_available_provider` logic, scoped to API

**`classify_task()` update**: infers `execution_mode` based on task_type and available providers.

**RoutingDecision model**: add `execution_mode` field to log the mode alongside provider/model/reason.

### 6. CLIQuotaTracker (new)

**File**: `backend/app/services/cli_quota_tracker.py`

Parallel to existing `QuotaManager`. Does not replace it.

**Session tracking:**
```python
@dataclass
class CLISessionUsage:
    provider: str
    session_start: datetime
    session_duration_seconds: float
    command_count: int
    prompt_count: int
    task_count: int
    status: str  # "available" | "throttled" | "blocked"
    blocked_until: datetime | None
```

**Behaviors:**
- Track per-CLI-provider session metrics (not tokens)
- Session limits via env vars
- Throttle when approaching limits (20% threshold, same pattern as API quota)
- Detect rate-limit signals from CLI output (e.g., "rate limited", "quota exceeded") and auto-block
- If reset time detectable, set `blocked_until`; otherwise mark `blocked_manual_review`
- `check_available(provider)` → `"available"` / `"throttled"` / `"blocked"`
- `record_session(provider, result)` → update counters after execution
- `reset(provider)` → hourly/daily reset cycle

**Existing `QuotaManager` unchanged** — continues tracking token-based quotas for API providers. `ModelRouter` delegates to `CLIQuotaTracker` for CLI and `QuotaManager` for API.

### 7. Config Updates

**File**: `backend/app/config/model_config.py`

**New dataclass:**
```python
@dataclass
class CLIProviderConfig:
    name: str               # "claude_code" | "glm_coding"
    binary: str             # "claude" | "glm" or full path
    default_args: list[str] # extra CLI args
    models: list[str]       # models this CLI exposes
    max_concurrent: int     # max concurrent sessions
    max_sessions_per_hour: int
    timeout_seconds: int = 300
    enabled: bool = True
```

**New env vars:**
```
ORKA_CLI_ENABLED=true
ORKA_CLI_DEFAULT=claude_code
CLAUDE_CODE_BINARY=claude
GLM_CODING_BINARY=glm
ORKA_CLI_MAX_CONCURRENT=3
ORKA_CLI_MAX_SESSIONS_PER_HOUR=20
ORKA_CLI_TIMEOUT=300
```

**Auto-detection**: `load_config()` checks if CLI binaries exist on PATH. If not found, provider is unavailable but app boots normally.

### 8. Registry Updates

**File**: `backend/app/providers/registry.py`

- Auto-register CLI providers alongside API providers
- `all()` returns mixed dict of CLI + API providers
- New `all_by_mode()` → `{"cli": [...], "api": [...]}`
- New `find_cli_provider(name)` → CLI provider or None
- CLI providers are checked for binary existence during registration

### 9. TaskRunner Update

**File**: `worker/task_runner.py`

- `SIMULATION_MODE` flag retained for backward compatibility
- When `SIMULATION_MODE = False`, real execution now delegates to the CLI provider's subprocess engine
- The shared subprocess engine (`cli_process.py`) is the single source of truth for subprocess execution
- TaskRunner becomes a thin coordinator: picks provider, delegates execution, reports results

## What Stays the Same

- All existing API providers (OpenAICompat, OpenRouter)
- Existing `QuotaManager` for API token tracking
- `BudgetManager` and `UsageTracker`
- Dashboard frontend (no changes needed)
- Worker session management
- Database models (only additive: `execution_mode` field on `RoutingDecision`)
- `SIMULATION_MODE` behavior
- `quota_only` as default mode

## What Gets Removed / Deprecated

Nothing removed. All changes are additive. The API system remains as fallback.

## New Files Summary

| File | Purpose |
|------|---------|
| `backend/app/providers/cli_base.py` | Abstract CLIProviderAdapter |
| `backend/app/providers/cli_claude.py` | Claude Code CLI implementation |
| `backend/app/providers/cli_glm.py` | GLM Coding CLI implementation |
| `backend/app/providers/cli_process.py` | Shared subprocess engine (backend copy) |
| `worker/cli_process.py` | Shared subprocess engine (worker copy) |
| `backend/app/services/cli_quota_tracker.py` | Session-based quota tracking |

## Modified Files Summary

| File | Change |
|------|--------|
| `backend/app/config/model_config.py` | Add `CLIProviderConfig`, CLI env loading |
| `backend/app/providers/registry.py` | Register CLI providers, `all_by_mode()` |
| `backend/app/services/model_router.py` | `execution_mode` routing, CLI-first logic |
| `backend/app/models/__init__.py` | Add `execution_mode` to `RoutingDecision` |
| `worker/task_runner.py` | Delegate to shared subprocess engine |

## Data Flow: Typical Coding Task

1. User submits task through dashboard
2. `AgentRuntime` receives task, calls `classify_task()` → `TaskProfile(execution_mode="cli")`
3. `ModelRouter.route()` sees `execution_mode="cli"`
4. Checks `CLIQuotaTracker` → CLI available, not blocked
5. Selects `ClaudeCodeCLIProvider` (or default CLI provider)
6. `ClaudeCodeCLIProvider.complete()` → calls `cli_process.execute()`
7. Subprocess engine runs `claude --print -p "..." --output-format json`
8. Streams output, detects prompts, auto-resolves safe ones
9. Returns `CLIExecutionResult` → adapter converts to `ProviderResponse`
10. `ModelRouter` records routing decision with `execution_mode="cli"`
11. `CLIQuotaTracker.record_session()` updates session counters

## Data Flow: Fallback to API

1. Task classified as coding → `execution_mode="cli"`
2. `CLIQuotaTracker.check_available()` → `"blocked"` (quota exceeded)
3. `ModelRouter` falls back to API tier
4. Checks `QuotaManager.check_available()` for API providers
5. If API quota available and `allow_paid_overage` policy allows → use API
6. If no safe provider → pause task, show "action required" in dashboard

## Constraints

- No token estimation for CLI usage in Phase 3B
- No silent paid API fallback — always require policy approval
- CLI binary missing → provider unavailable, app still boots
- CLI health checks must be non-blocking
- API providers unchanged, all existing behavior preserved
- `quota_only` remains the default mode
