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

            is_prompt, auto_response, input_type, reason = check_prompt(
                safe_prompt
            )
            if is_prompt and auto_response is not None:
                await self.session_manager.add_log(
                    session_id, "info",
                    f"[ORKA] Auto-resolved: {reason} -> '{auto_response.strip()}'",
                )
                await self.session_manager.log_decision(
                    session_id,
                    decision=f"Auto-resolved prompt: responded '{auto_response.strip()}'",
                    reason=f"{reason} | Prompt: {safe_prompt.strip()}",
                    auto_resolved=True,
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

            _, _, crit_input_type, crit_reason = check_prompt(
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
