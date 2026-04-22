"""
ORKA Worker — standalone process that connects to the ORKA backend.

Responsibilities:
  1. Register with the backend on startup.
  2. Send periodic heartbeats.
  3. Poll for assigned tasks.
  4. For each task create a session and hand execution to TaskRunner.
  5. Process one task at a time (queue the rest).
"""

import asyncio
import logging
import platform
import signal
import socket
import sys
import uuid

import httpx

from session_manager import SessionManager
from task_runner import TaskRunner

# ── Configuration ──────────────────────────────────────────────────────

API_BASE = "http://localhost:8000"
WORKER_NAME = "orka-worker-1"
POLL_INTERVAL = 5  # seconds between task polls
HEARTBEAT_INTERVAL = 30  # seconds between heartbeats
MAX_CONCURRENT_TASKS = 1  # process one task at a time

# ── Logging setup ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orka-worker")

# ── HTTP helpers ───────────────────────────────────────────────────────

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def _request_with_retry(
    method: str,
    url: str,
    *,
    json_data: dict | None = None,
    params: dict | None = None,
    max_retries: int = 10,
    base_delay: float = 1.0,
) -> httpx.Response:
    """HTTP request with exponential backoff on transient failures."""
    client = await _get_client()
    delay = base_delay

    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.request(method, url, json=json_data, params=params)
            if resp.status_code < 500:
                return resp
            logger.warning(
                "Server error %d on %s %s (attempt %d/%d)",
                resp.status_code,
                method,
                url,
                attempt,
                max_retries,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(
                "Connection error on %s %s: %s (attempt %d/%d)",
                method,
                url,
                exc,
                attempt,
                max_retries,
            )

        if attempt < max_retries:
            jitter = delay * 0.1
            sleep_time = delay + (asyncio.get_event_loop().time() % (jitter * 2)) - jitter
            logger.info("Retrying in %.1fs ...", sleep_time)
            await asyncio.sleep(sleep_time)
            delay = min(delay * 2, 60.0)

    raise httpx.ConnectError(f"Failed after {max_retries} retries: {method} {url}")


# ── Registration ───────────────────────────────────────────────────────

async def register_worker() -> dict:
    """Register this worker with the backend and return the worker object."""
    hostname = socket.gethostname()
    plat = platform.system().lower()

    payload = {
        "name": WORKER_NAME,
        "hostname": hostname,
        "platform": plat,
    }

    logger.info("Registering worker '%s' at %s ...", WORKER_NAME, API_BASE)
    resp = await _request_with_retry(
        "POST",
        f"{API_BASE}/api/workers/register",
        json_data=payload,
    )
    resp.raise_for_status()
    worker = resp.json()
    logger.info("Registered — worker id: %s", worker.get("id"))
    return worker


# ── Heartbeat ──────────────────────────────────────────────────────────

async def heartbeat_loop(worker_id: str) -> None:
    """Send periodic heartbeats to keep the worker marked as alive."""
    while True:
        try:
            resp = await _request_with_retry(
                "PUT",
                f"{API_BASE}/api/workers/{worker_id}/heartbeat",
            )
            if resp.status_code == 200:
                logger.debug("Heartbeat OK")
            else:
                logger.warning("Heartbeat returned %d", resp.status_code)
        except Exception as exc:
            logger.error("Heartbeat failed: %s", exc)

        await asyncio.sleep(HEARTBEAT_INTERVAL)


# ── Task polling ───────────────────────────────────────────────────────

async def fetch_tasks(worker_id: str) -> list[dict]:
    """Fetch tasks assigned to this worker (all agent types)."""
    resp = await _request_with_retry(
        "GET",
        f"{API_BASE}/api/workers/{worker_id}/tasks",
    )
    if resp.status_code == 200:
        return resp.json() if isinstance(resp.json(), list) else []
    logger.warning("Fetch tasks returned %d", resp.status_code)
    return []


async def task_polling_loop(
    worker_id: str,
    session_manager: SessionManager,
    task_runner: TaskRunner,
) -> None:
    """
    Continuously poll for tasks and execute them one at a time.

    Only one task runs at a time; any additional tasks returned by the API
    are logged and will be picked up on subsequent polls.
    """
    current_task: asyncio.Task | None = None

    while True:
        try:
            # Wait for any in-flight task to finish before polling again
            if current_task is not None:
                if not current_task.done():
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                # Check for exceptions so they are not silently swallowed
                exc = current_task.exception()
                if exc:
                    logger.error("Task execution raised: %s", exc)
                current_task = None

            tasks = await fetch_tasks(worker_id)

            if not tasks:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Pick the first pending task
            task = tasks[0]
            task_id = task.get("id", "unknown")
            agent_id = task.get("assigned_agent_id") or str(uuid.uuid4())

            logger.info("Found task %s — creating session ...", task_id)

            session = await session_manager.create_session(
                worker_id, task_id, agent_id
            )
            session_id = session.get("id", "unknown")
            logger.info("Session %s created for task %s", session_id, task_id)

            # Fire-and-forget as an asyncio Task so the polling loop stays
            # responsive, but we gate on completion before accepting the next
            # task (see the done-check above).
            current_task = asyncio.create_task(
                task_runner.run_task(session, task),
                name=f"task-{task_id}",
            )

        except Exception as exc:
            logger.error("Error in polling loop: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)


# ── Main ───────────────────────────────────────────────────────────────

_shutdown_event: asyncio.Event | None = None


async def main() -> None:
    global _shutdown_event

    logger.info("ORKA Worker starting ...")

    # Register
    worker = await register_worker()
    worker_id = worker["id"]

    # Set up session manager and task runner
    session_manager = SessionManager(API_BASE)
    task_runner = TaskRunner(session_manager)

    # Set up graceful shutdown via signals
    _shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler():
        logger.info("Shutdown signal received — cleaning up ...")
        _shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info(
        "Worker ready — polling every %ds, heartbeat every %ds",
        POLL_INTERVAL,
        HEARTBEAT_INTERVAL,
    )

    try:
        # Run heartbeat and polling concurrently
        await asyncio.gather(
            heartbeat_loop(worker_id),
            task_polling_loop(worker_id, session_manager, task_runner),
        )
    finally:
        logger.info("Shutting down ...")
        task_runner.shutdown()
        await session_manager.close()
        logger.info("Worker shutdown complete")


async def run_with_recovery():
    """Run the worker with automatic recovery on crashes."""
    while True:
        try:
            await main()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.error("Worker crashed: %s — restarting in 10s", exc)
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(run_with_recovery())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
        sys.exit(0)
