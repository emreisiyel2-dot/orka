"""
ORKA Worker Session Manager.

Manages session lifecycle and communication with the ORKA backend API.
Uses httpx AsyncClient for all HTTP calls with retry logic.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger("orka-worker.session")


class SessionManager:
    """Manages session state and communication with the ORKA backend."""

    def __init__(self, api_base: str):
        self.api_base = api_base.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._max_retries = 5
        self._base_delay = 1.0

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create and return the shared httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        """Make an HTTP request with exponential backoff retry on failure."""
        client = await self._get_client()
        url = f"{self.api_base}{path}"
        delay = self._base_delay

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    json=json_data,
                    params=params,
                )
                if response.status_code < 500:
                    return response
                logger.warning(
                    "Server error %d on %s %s (attempt %d/%d)",
                    response.status_code,
                    method,
                    path,
                    attempt,
                    self._max_retries,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning(
                    "Connection error on %s %s: %s (attempt %d/%d)",
                    method,
                    path,
                    exc,
                    attempt,
                    self._max_retries,
                )

            if attempt < self._max_retries:
                jitter = delay * 0.1
                sleep_time = delay + asyncio.get_event_loop().time() % (jitter * 2) - jitter
                logger.info("Retrying in %.1fs ...", sleep_time)
                await asyncio.sleep(sleep_time)
                delay *= 2

        raise httpx.ConnectError(
            f"Failed to {method} {path} after {self._max_retries} attempts"
        )

    # ── Session lifecycle ──────────────────────────────────────────────

    async def create_session(
        self, worker_id: str, task_id: str, agent_id: str
    ) -> dict:
        """Create a new execution session via POST /api/workers/sessions."""
        response = await self._request_with_retry(
            "POST",
            "/api/workers/sessions",
            json_data={
                "worker_id": worker_id,
                "task_id": task_id,
                "agent_id": agent_id,
            },
        )
        response.raise_for_status()
        return response.json()

    async def update_session(self, session_id: str, **kwargs: Any) -> dict:
        """Update session state via PUT /api/workers/sessions/{session_id}."""
        response = await self._request_with_retry(
            "PUT",
            f"/api/workers/sessions/{session_id}",
            json_data=kwargs,
        )
        response.raise_for_status()
        return response.json()

    # ── Logging ────────────────────────────────────────────────────────

    async def add_log(self, session_id: str, level: str, content: str) -> None:
        """Append a log line via POST /api/workers/sessions/{id}/logs."""
        try:
            response = await self._request_with_retry(
                "POST",
                f"/api/workers/sessions/{session_id}/logs",
                json_data={"level": level, "content": content},
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error("Failed to add log to session %s: %s", session_id, exc)

    # ── Decision logging ───────────────────────────────────────────────

    async def log_decision(
        self,
        session_id: str,
        decision: str,
        reason: str,
        auto_resolved: bool = True,
    ) -> None:
        """Record an autonomous decision via the decisions API."""
        try:
            response = await self._request_with_retry(
                "POST",
                f"/api/workers/sessions/{session_id}/decisions",
                json_data={
                    "decision": decision,
                    "reason": reason,
                    "auto_resolved": auto_resolved,
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error(
                "Failed to log decision for session %s: %s", session_id, exc
            )

    # ── Input polling ──────────────────────────────────────────────────

    async def wait_for_input(
        self, session_id: str, timeout: float = 300, poll_interval: float = 3.0
    ) -> str | None:
        """
        Poll the session until waiting_for_input becomes False or timeout.

        Returns the input_value from the session data, or None on timeout.
        """
        elapsed = 0.0
        while elapsed < timeout:
            try:
                response = await self._request_with_retry(
                    "GET",
                    f"/api/sessions/{session_id}",
                )
                response.raise_for_status()
                data = response.json()

                if not data.get("waiting_for_input", False):
                    last_output = data.get("last_output", "") or ""
                    if last_output.startswith("[USER INPUT] "):
                        return last_output[len("[USER INPUT] "):]
                    return ""
                    # Session might have been cancelled
                    status = data.get("status", "")
                    if status in ("completed", "error", "cancelled"):
                        logger.warning(
                            "Session %s entered status '%s' while waiting for input",
                            session_id,
                            status,
                        )
                        return None
            except Exception as exc:
                logger.error("Error polling session %s: %s", session_id, exc)

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning(
            "Timed out waiting for input on session %s after %.0fs",
            session_id,
            timeout,
        )
        return None

    # ── Terminal states ────────────────────────────────────────────────

    async def mark_completed(self, session_id: str, exit_code: int = 0) -> None:
        """Mark a session as completed."""
        try:
            await self.update_session(
                session_id,
                status="completed",
                waiting_for_input=False,
                exit_code=exit_code,
            )
            logger.info("Session %s marked completed (exit_code=%d)", session_id, exit_code)
        except Exception as exc:
            logger.error("Failed to mark session %s completed: %s", session_id, exc)

    async def mark_error(self, session_id: str, error_msg: str) -> None:
        """Mark a session as errored."""
        try:
            await self.update_session(
                session_id,
                status="error",
                waiting_for_input=False,
                exit_code=1,
            )
            await self.add_log(session_id, "error", error_msg)
            logger.error("Session %s marked error: %s", session_id, error_msg)
        except Exception as exc:
            logger.error("Failed to mark session %s as error: %s", session_id, exc)


class LogBatcher:
    """Batches log entries and flushes them periodically or when full."""

    def __init__(self, session_manager: SessionManager, flush_interval: float = 2.0, max_size: int = 20):
        self.session_manager = session_manager
        self.flush_interval = flush_interval
        self.max_size = max_size
        self._buffer: list[tuple[str, str, str]] = []  # (session_id, level, content)
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None

    async def add(self, session_id: str, level: str, content: str):
        async with self._lock:
            self._buffer.append((session_id, level, content))
            if len(self._buffer) >= self.max_size:
                await self._flush()

    async def _flush(self):
        if not self._buffer:
            return
        batch = self._buffer.copy()
        self._buffer.clear()
        for session_id, level, content in batch:
            await self.session_manager.add_log(session_id, level, content)

    async def start(self):
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def _periodic_flush(self):
        while True:
            await asyncio.sleep(self.flush_interval)
            async with self._lock:
                await self._flush()

    async def stop(self):
        if self._flush_task:
            self._flush_task.cancel()
        async with self._lock:
            await self._flush()
