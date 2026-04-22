"""
ORKA Task Runner.

Executes tasks with autonomous prompt handling. Detects safe vs critical
prompts in process output and either auto-resolves them or escalates to
the dashboard for human input.
"""

import asyncio
import logging
import re
import time

from session_manager import SessionManager

logger = logging.getLogger("orka-worker.task_runner")

# ── Pattern definitions ────────────────────────────────────────────────

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
    # These will NOT be auto-resolved — they escalate to the dashboard
    (r"delete.*permanent", None, "yes_no", "Destructive action detected"),
    (r"overwrite.*existing", None, "yes_no", "Overwrite warning"),
    (r"production", None, "yes_no", "Production system risk"),
    (r"password|credential|secret|token", None, "text", "Credential-related prompt"),
    (r"deploy.*prod", None, "yes_no", "Production deployment"),
    (r"drop.*table|database", None, "yes_no", "Database destruction risk"),
    (r"sudo|administrator", None, "yes_no", "Elevated privileges required"),
    (r"irreversible|cannot be undone", None, "yes_no", "Irreversible operation"),
]

# Simulation mode flag — set to False to run real subprocesses
SIMULATION_MODE = True


class TaskRunner:
    """Executes tasks and handles autonomous prompt resolution."""

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.active_processes: dict[str, asyncio.subprocess.Process] = {}

    def shutdown(self):
        """Signal all running tasks to stop."""
        for sid, proc in list(self.active_processes.items()):
            try:
                proc.kill()
            except Exception:
                pass
        self.active_processes.clear()

    async def _check_stuck_session(self, session_id: str, output_interval: float = 60.0) -> bool:
        """Check if a session appears stuck (no recent output). Always returns False in simulation."""
        return False  # Real implementation would track last output time

    # ── Public interface ───────────────────────────────────────────────

    async def run_task(self, session: dict, task: dict) -> None:
        """
        Main entry point for task execution.

        In simulation mode this runs a fake workflow. Otherwise it launches
        a real subprocess and streams its output through the prompt detector.
        """
        session_id = session.get("id", "unknown")
        command = task.get("command", task.get("description", ""))

        if SIMULATION_MODE:
            await self._simulate_claude_code(session, task)
            return

        await self.session_manager.add_log(
            session_id, "info", f"Starting task execution: {command}"
        )
        await self.session_manager.update_session(session_id, status="running")

        process = None
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self.active_processes[session_id] = process

            await asyncio.gather(
                self._stream_output(session_id, process.stdout, "output", process),
                self._stream_output(session_id, process.stderr, "warn", process),
            )

            try:
                await asyncio.wait_for(process.wait(), timeout=300)
            except asyncio.TimeoutError:
                logger.error(
                    "Task timed out after 300s for session %s — killing process",
                    session_id,
                )
                process.kill()
                await process.wait()
                await self.session_manager.mark_error(
                    session_id, "Task timed out after 300 seconds"
                )
                return

            exit_code = process.returncode if process.returncode is not None else 1

            if exit_code == 0:
                await self.session_manager.mark_completed(session_id, exit_code)
            else:
                await self.session_manager.mark_error(
                    session_id, f"Process exited with code {exit_code}"
                )

        except Exception as exc:
            logger.exception("Task execution failed for session %s", session_id)
            await self.session_manager.mark_error(session_id, str(exc))
        finally:
            self.active_processes.pop(session_id, None)

    # ── Output streaming ───────────────────────────────────────────────

    async def _stream_output(
        self,
        session_id: str,
        stream: asyncio.StreamReader | None,
        level: str,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Read lines from a subprocess stream, forward to backend, and detect prompts."""
        if stream is None:
            return

        while True:
            line_bytes = await stream.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()

            await self.session_manager.add_log(session_id, level, line)

            is_prompt, auto_response, input_type, reason = await self._check_prompt(line)
            if not is_prompt:
                continue

            if auto_response is not None:
                # Safe prompt — auto-resolve
                await self._handle_autonomous(
                    session_id, line, auto_response, reason
                )
                if process.stdin and not process.stdin.is_closing():
                    process.stdin.write(auto_response.encode("utf-8"))
                    await process.stdin.drain()
            else:
                # Critical prompt — escalate to dashboard
                input_value = await self._escalate_prompt(
                    session_id, line, input_type, reason
                )
                if input_value is not None and process.stdin and not process.stdin.is_closing():
                    process.stdin.write(f"{input_value}\n".encode("utf-8"))
                    await process.stdin.drain()
                else:
                    # No input received (timeout / cancelled) — kill process
                    process.kill()
                    await self.session_manager.add_log(
                        session_id,
                        "error",
                        "No dashboard input received; terminating process.",
                    )

    # ── Prompt detection ───────────────────────────────────────────────

    async def _check_prompt(
        self, line: str
    ) -> tuple[bool, str | None, str, str]:
        """
        Check whether *line* matches a known prompt pattern.

        Returns (is_prompt, auto_response_or_None, input_type, reason).
        Critical patterns always return auto_response=None so the caller
        knows to escalate.
        """
        line_lower = line.lower()

        # Check critical patterns first (higher priority)
        for pattern, _auto, input_type, reason in CRITICAL_PATTERNS:
            if re.search(pattern, line_lower):
                return (True, None, input_type, reason)

        # Then check safe patterns
        for pattern, auto_response, input_type, reason in SAFE_PATTERNS:
            if re.search(pattern, line_lower):
                return (True, auto_response, input_type, reason)

        return (False, None, "", "")

    # ── Autonomous resolution ──────────────────────────────────────────

    async def _handle_autonomous(
        self,
        session_id: str,
        prompt_text: str,
        auto_response: str,
        reason: str,
    ) -> None:
        """Auto-resolve a safe prompt and log the decision."""
        display_response = auto_response.replace("\n", "\\n").strip()
        decision = f"Auto-resolved prompt: responded '{display_response}'"

        logger.info(
            "Auto-resolving prompt on session %s: %s", session_id, reason
        )

        await self.session_manager.log_decision(
            session_id,
            decision=decision,
            reason=f"{reason} | Prompt: {prompt_text.strip()}",
            auto_resolved=True,
        )
        await self.session_manager.add_log(
            session_id,
            "info",
            f"[ORKA] Auto-resolved: {reason} -> '{display_response}'",
        )

    # ── Escalation ─────────────────────────────────────────────────────

    async def _escalate_prompt(
        self,
        session_id: str,
        prompt_text: str,
        input_type: str,
        reason: str,
    ) -> str | None:
        """
        Escalate a critical prompt to the dashboard.

        Sets the session to waiting_for_input and then polls until the
        dashboard provides input (or times out).
        """
        logger.warning(
            "Escalating critical prompt on session %s: %s",
            session_id,
            reason,
        )

        await self.session_manager.add_log(
            session_id,
            "warn",
            f"[ORKA] Escalating to dashboard: {reason}",
        )
        await self.session_manager.update_session(
            session_id,
            status="waiting_input",
            waiting_for_input=True,
            input_type=input_type,
            input_prompt_text=prompt_text.strip(),
        )
        await self.session_manager.log_decision(
            session_id,
            decision=f"Escalated to dashboard: {reason}",
            reason=f"Critical prompt detected: {prompt_text.strip()}",
            auto_resolved=False,
        )

        # Wait for the dashboard user to respond
        input_value = await self.session_manager.wait_for_input(
            session_id, timeout=300
        )

        if input_value is not None:
            await self.session_manager.update_session(
                session_id,
                status="running",
                waiting_for_input=False,
            )
            await self.session_manager.add_log(
                session_id,
                "info",
                f"[ORKA] Dashboard input received: '{input_value}'",
            )

        return input_value

    # ── Simulation mode ────────────────────────────────────────────────

    async def _simulate_claude_code(self, session: dict, task: dict) -> None:
        """
        Simulate a full Claude Code execution cycle for MVP demonstration.

        Demonstrates:
        1. Normal output streaming
        2. Safe prompt auto-resolution
        3. Critical prompt escalation with dashboard input
        4. Session completion
        """
        session_id = session.get("id", "unknown")
        task_description = task.get("content", task.get("description", "unknown task"))

        try:
            await self.session_manager.update_session(session_id, status="running")

            # ── Phase 1: Startup ───────────────────────────────────
            await self.session_manager.add_log(
                session_id, "info", "Starting Claude Code session..."
            )
            await asyncio.sleep(1.0)

            await self.session_manager.add_log(
                session_id, "output", f"Task: {task_description}"
            )
            await asyncio.sleep(0.5)

            await self.session_manager.add_log(
                session_id, "output", "Analyzing codebase..."
            )
            await asyncio.sleep(1.0)

            await self.session_manager.add_log(
                session_id, "output", "Found 3 files to modify..."
            )
            await asyncio.sleep(0.5)

            await self.session_manager.add_log(
                session_id, "output", "Generating changes..."
            )
            await asyncio.sleep(1.0)

            # ── Phase 2: Safe prompt (auto-resolved) ───────────────
            safe_prompt = "Do you want to continue? [y/N]"
            await self.session_manager.add_log(
                session_id, "output", safe_prompt
            )

            is_prompt, auto_response, input_type, reason = await self._check_prompt(
                safe_prompt
            )
            if is_prompt and auto_response is not None:
                await self._handle_autonomous(
                    session_id, safe_prompt, auto_response, reason
                )
            await asyncio.sleep(0.5)

            # ── Phase 3: More output ───────────────────────────────
            await self.session_manager.add_log(
                session_id, "output", "Applying changes to src/app.py..."
            )
            await asyncio.sleep(0.8)

            await self.session_manager.add_log(
                session_id, "output", "Applying changes to src/utils.py..."
            )
            await asyncio.sleep(0.8)

            await self.session_manager.add_log(
                session_id, "output", "Running tests..."
            )
            await asyncio.sleep(1.0)

            await self.session_manager.add_log(
                session_id, "output", "All tests passed (3/3)"
            )
            await asyncio.sleep(0.5)

            # ── Phase 4: Critical prompt (escalated) ───────────────
            critical_prompt = "This will modify production config. Continue? [y/N]"
            await self.session_manager.add_log(
                session_id, "output", critical_prompt
            )

            _, _, crit_input_type, crit_reason = await self._check_prompt(
                critical_prompt
            )
            input_value = await self._escalate_prompt(
                session_id, critical_prompt, crit_input_type, crit_reason
            )

            if input_value is not None:
                await self.session_manager.add_log(
                    session_id,
                    "output",
                    f"Proceeding with dashboard response: '{input_value}'",
                )
                await asyncio.sleep(0.5)
            else:
                await self.session_manager.add_log(
                    session_id,
                    "warn",
                    "No dashboard response received for critical prompt; continuing safely.",
                )
                await asyncio.sleep(0.5)

            # ── Phase 5: Completion ────────────────────────────────
            await self.session_manager.add_log(
                session_id, "output", "Finalizing changes..."
            )
            await asyncio.sleep(0.5)

            await self.session_manager.add_log(
                session_id, "output", "Task completed successfully."
            )

            await self.session_manager.mark_completed(session_id, exit_code=0)

        except Exception as exc:
            logger.exception(
                "Simulation failed for session %s", session_id
            )
            await self.session_manager.mark_error(session_id, str(exc))
