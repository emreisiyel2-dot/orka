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
